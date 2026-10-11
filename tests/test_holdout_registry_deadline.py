"""Deterministic SQLite busy-wait budgets, without relaxing wall-clock gates."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from quantlab import research
from quantlab.reporting import synthetic_dataset


class RegistryDeadlineTests(unittest.TestCase):
    def run_reservation(self, *, deadline=1.0, schema_delays=(0.0, 0.0),
                        connect_delay=0.0, locked=False, select_delay=0.0,
                        busy_delay=None, as_walk_forward=False, busy_code=sqlite3.SQLITE_BUSY):
        clock = [0.0]
        events = []

        class Connection:
            def __init__(self, timeout):
                self.busy = int(timeout * 1000) / 1000  # sqlite3.connect uses integer milliseconds.
                self.schemas = iter(schema_delays)
            def __enter__(self):
                return self
            def __exit__(self, kind, value, traceback):
                events.append(('rollback' if kind else 'commit', clock[0]))
            def close(self):
                events.append(('close', clock[0]))
            def execute(self, sql, parameters=()):
                events.append(('execute', sql, clock[0], self.busy))
                if sql.startswith('PRAGMA busy_timeout='):
                    self.busy = int(sql.split('=')[1]) / 1000
                elif sql.startswith('CREATE TABLE'):
                    clock[0] += next(self.schemas)
                elif sql == 'BEGIN IMMEDIATE' and locked:
                    clock[0] += self.busy if busy_delay is None else busy_delay
                    error = sqlite3.OperationalError('fixture registry locked')
                    error.sqlite_errorcode = busy_code
                    raise error
                elif sql.startswith('SELECT DISTINCT'):
                    clock[0] += select_delay
                return self
            def fetchall(self):
                return []
            def executemany(self, sql, parameters):
                events.append(('executemany', sql, tuple(parameters)))

        real_connect = sqlite3.connect
        def connect(path, timeout):
            if Path(path) != target_registry:
                return real_connect(path, timeout=timeout)
            events.append(('connect', timeout))
            clock[0] += connect_delay
            return Connection(timeout)

        dataset = synthetic_dataset(10)
        result = error = None
        with tempfile.TemporaryDirectory() as temporary:
            target_registry = Path(temporary) / 'registry.sqlite3'
            if as_walk_forward:
                from tests.test_walk_forward import inputs
                from quantlab.walk_forward import run_walk_forward
                dataset, plan = inputs(max_runtime_seconds=1)
            with patch.object(research.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(research.sqlite3, 'connect', side_effect=connect):
                try:
                    if as_walk_forward:
                        result = run_walk_forward(dataset, plan=plan,
                            holdout_registry_path=target_registry, output_dir=Path(temporary) / 'output')
                    else:
                        result = research._reserve_holdout(dataset,
                            registry_path=target_registry, campaign_id='fixture',
                            selection_hash='fixture', output_dir=Path(temporary) / 'output', deadline=deadline)
                except (research.ResourceTimeout, sqlite3.OperationalError) as exc:
                    error = exc
        return result, error, clock[0], events

    def test_schema_time_is_subtracted_before_busy_begin(self):
        result, error, elapsed, events = self.run_reservation(schema_delays=(.35, .35), locked=True)
        self.assertIsNone(result)
        self.assertIsInstance(error, research.ResourceTimeout)
        self.assertLessEqual(elapsed, 1.0)
        busy = [e[3] for e in events if e[0] == 'execute' and
                (e[1].startswith('CREATE TABLE') or e[1] == 'BEGIN IMMEDIATE')]
        self.assertEqual(busy, [1.0, .65, .3])
        self.assertEqual(events[-2][0], 'rollback')
        self.assertEqual(events[-1][0], 'close')
        self.assertFalse(any(e[0] == 'executemany' for e in events))

    def test_expired_schema_budget_prevents_next_schema_and_begin(self):
        result, error, elapsed, events = self.run_reservation(schema_delays=(1.1, 0))
        self.assertIsNone(result)
        self.assertIsInstance(error, research.ResourceTimeout)
        statements = [e[1] for e in events if e[0] == 'execute']
        self.assertEqual(sum(s.startswith('CREATE TABLE') for s in statements), 1)
        self.assertNotIn('BEGIN IMMEDIATE', statements)
        self.assertEqual(elapsed, 1.1)  # Executed SQL itself is not preemptible.

    def test_connect_time_can_exhaust_budget_before_any_schema(self):
        result, error, elapsed, events = self.run_reservation(connect_delay=1.0)
        self.assertIsNone(result)
        self.assertIsInstance(error, research.ResourceTimeout)
        self.assertFalse(any(e[0] == 'execute' for e in events))
        self.assertEqual(elapsed, 1.0)

    def test_no_deadline_keeps_original_ten_second_timeout_and_commit(self):
        result, error, _, events = self.run_reservation(deadline=None)
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'reserved_consumed')
        self.assertEqual(events[0], ('connect', 10))
        self.assertFalse(any(e[0] == 'execute' and e[1].startswith('PRAGMA') for e in events))
        self.assertEqual(sum(e[0] == 'commit' for e in events), 1)
        self.assertEqual(sum(e[0] == 'executemany' for e in events), 1)
        self.assertEqual(events[-1][0], 'close')

    def test_long_deadline_never_expands_original_ten_second_busy_limit(self):
        result, error, _, events = self.run_reservation(deadline=30)
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'reserved_consumed')
        guarded = [e for e in events if e[0] == 'execute' and
                   (e[1].startswith('CREATE TABLE') or e[1] == 'BEGIN IMMEDIATE')]
        self.assertEqual([e[3] for e in guarded], [10, 10, 10])

    def test_submillisecond_budget_is_not_rounded_up(self):
        result, error, elapsed, events = self.run_reservation(deadline=.0005, locked=True)
        self.assertIsNone(result)
        self.assertIsInstance(error, research.ResourceTimeout)
        self.assertLessEqual(elapsed, .0005)
        begin = next(e for e in events if e[0] == 'execute' and e[1] == 'BEGIN IMMEDIATE')
        self.assertEqual(begin[3], 0)

    def test_original_final_deadline_check_prevents_reservation_insert(self):
        result, error, _, events = self.run_reservation(select_delay=1.1)
        self.assertIsNone(result)
        self.assertIsInstance(error, research.ResourceTimeout)
        self.assertFalse(any(e[0] == 'execute' and e[1].startswith('INSERT') for e in events))
        self.assertFalse(any(e[0] == 'executemany' for e in events))
        self.assertEqual(events[-2][0], 'rollback')

    def test_real_sqlite_locked_registry_keeps_reservation_unchanged(self):
        dataset = synthetic_dataset(10)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'registry.sqlite3'
            options = dict(registry_path=path, campaign_id='fixture', selection_hash='fixture',
                           output_dir=Path(temporary) / 'output')
            original = research._reserve_holdout(dataset, **options)
            self.assertEqual(original['status'], 'reserved_consumed')
            with closing(sqlite3.connect(path)) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                started = time.monotonic()
                with self.assertRaises((research.ResourceTimeout, sqlite3.OperationalError)):
                    research._reserve_holdout(dataset, deadline=started + .1, **options)
                elapsed = time.monotonic() - started
                blocker.rollback()
            self.assertLess(elapsed, 2)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT campaign_id FROM reservations').fetchone()[0], 'fixture')

    def test_real_sqlite_success_keeps_one_atomic_commit_and_full_sync(self):
        dataset = synthetic_dataset(10)
        statements = []
        connect = sqlite3.connect
        def traced(*args, **kwargs):
            db = connect(*args, **kwargs)
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            db.set_trace_callback(statements.append)
            return db
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'registry.sqlite3'
            with patch.object(research.sqlite3, 'connect', side_effect=traced):
                result = research._reserve_holdout(dataset, registry_path=path,
                    campaign_id='fixture', selection_hash='fixture',
                    output_dir=Path(temporary) / 'output', deadline=time.monotonic() + 10)
            self.assertEqual(result['status'], 'reserved_consumed')
            self.assertEqual(statements.count('BEGIN IMMEDIATE'), 1)
            self.assertEqual(statements.count('COMMIT'), 1)
            self.assertEqual(sum(s.startswith('PRAGMA busy_timeout=') for s in statements), 3)
            self.assertEqual(sum(s.startswith('INSERT INTO reservations') for s in statements), 1)
            with closing(connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM coverage').fetchone()[0], 1)

    def test_walk_forward_exhausted_millisecond_wait_is_budget_exhausted(self):
        result, error, elapsed, _ = self.run_reservation(
            as_walk_forward=True, schema_delays=(.3502, .35), locked=True)
        self.assertIsNone(error)
        self.assertLess(elapsed, 1)
        self.assertLess(1 - elapsed, .001)
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(result['evaluations'], [])
        self.assertIsNone(result['registry_reservation'])

    def test_walk_forward_genuinely_early_busy_remains_blocked(self):
        result, error, elapsed, _ = self.run_reservation(
            as_walk_forward=True, schema_delays=(.3502, .35), locked=True, busy_delay=.01)
        self.assertIsNone(error)
        self.assertGreater(1 - elapsed, .001)
        self.assertEqual(result['status'], 'blocked_registry_busy')
        self.assertEqual(result['evaluations'], [])
        self.assertIsNone(result['registry_reservation'])

    def test_walk_forward_locked_is_not_relabelled_as_busy_budget(self):
        result, error, elapsed, _ = self.run_reservation(as_walk_forward=True,
            schema_delays=(.3502, .35), locked=True, busy_code=sqlite3.SQLITE_LOCKED)
        self.assertIsNone(error)
        self.assertLess(1 - elapsed, .001)
        self.assertEqual(result['status'], 'blocked_registry_busy')
        self.assertEqual(result['evaluations'], [])
        self.assertIsNone(result['registry_reservation'])

    def test_other_sqlite_errors_are_not_relabelled_at_deadline(self):
        result, error, _, _ = self.run_reservation(
            schema_delays=(.3502, .35), locked=True, busy_code=sqlite3.SQLITE_IOERR)
        self.assertIsNone(result)
        self.assertIsInstance(error, sqlite3.OperationalError)
        self.assertEqual(error.sqlite_errorcode, sqlite3.SQLITE_IOERR)
