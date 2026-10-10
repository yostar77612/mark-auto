"""Rollback-storage gates. Update EXPECTED_MODE with an approved mode change.

This is a test expectation, not a production setting or a fallback. Child
processes must observe it on the real PaperReplay connection before proceeding.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from quantlab.core import ValidationError, content_hash
from quantlab.desktop_runtime import AppPaths, BackupManager, atomic_write
from quantlab.reporting import synthetic_dataset
from quantlab.strategies import builtin_strategies
from tests import test_paper_replay as replay_fixtures


EXPECTED_MODE = 'delete'  # Current production; select only after native measurement.
ECONOMIC_FIELDS = ('cash', 'positions', 'orders', 'fills', 'order_send_timestamps')
JOURNAL_MAGIC = bytes.fromhex('d9d505f920a163d7')


def _fixture(state):
    fixture = replay_fixtures.ReplayTests()
    fixture.root = Path(state)
    fixture.data = synthetic_dataset(120)
    fixture.spec = builtin_strategies()[0]
    fixture.broker = fixture.new_broker()
    fixture.replay = fixture.new_replay()
    return fixture


def _economics(broker):
    state = broker.snapshot()
    return {key: state[key] for key in ECONOMIC_FIELDS}


def _check_mode(replay, mode):
    with replay._db() as db:
        actual = db.execute('PRAGMA journal_mode').fetchone()[0]
        synchronous = db.execute('PRAGMA synchronous').fetchone()[0]
    if actual != mode or synchronous != 2:
        raise AssertionError((actual, synchronous, mode))


def _die_at_boundary(state, witness, mode, boundary):
    """Real child entry: no inherited Python state and no graceful SQL close."""
    fixture = _fixture(state)
    replay, broker = fixture.replay, fixture.broker
    _check_mode(replay, mode)
    broker.reconcile(broker.snapshot())
    replay.targets = {1 if boundary == 'after_empty_cursor' else 0: 1}
    replay.start()

    def die(point):
        if point != boundary:
            return
        atomic_write(witness, json.dumps({'point': point, 'mode': mode,
                     'binding': replay.binding, 'economics': _economics(broker)}).encode())
        os._exit(73)

    replay._fault = die
    replay.step(max_bars=2)
    raise AssertionError('Requested process-death boundary was not exercised')


def _die_with_hot_journal(state, witness, mode):
    fixture = _fixture(state)
    replay, broker = fixture.replay, fixture.broker
    _check_mode(replay, mode)
    broker.reconcile(broker.snapshot())
    replay.targets = {0: 1}
    replay.start()

    class PlanSaved(Exception):
        pass

    def save_plan(point):
        if point == 'after_plan_before_submit':
            raise PlanSaved()

    replay._fault = save_plan
    try:
        replay.step(max_bars=1)
    except PlanSaved:
        pass
    else:
        raise AssertionError('Durable plan boundary was not exercised')
    with replay._db() as db:
        cursor, plan = db.execute('SELECT cursor,plan FROM replay WHERE id=1').fetchone()
        if cursor != 0 or not json.loads(plan):
            raise AssertionError('Missing committed pending plan')
        # A second btree makes the first modified replay page eligible for spill.
        # Only this disposable test database receives this extra table.
        db.execute('CREATE TABLE spill_probe (id INTEGER PRIMARY KEY, value TEXT)')
        db.execute("INSERT INTO spill_probe VALUES (1, 'committed')")
    economics = _economics(broker)
    before = replay.path.read_bytes()
    with replay._db() as db:
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        root_page = db.execute("SELECT rootpage FROM sqlite_master WHERE name='replay'").fetchone()[0]
        page_start = (root_page - 1) * page_size
        committed_page = before[page_start:page_start + page_size]
        db.execute('PRAGMA cache_size=1')
        db.execute('PRAGMA cache_spill=ON')
        if db.execute('PRAGMA cache_spill').fetchone()[0] == 0:
            raise AssertionError('Cache spill was not enabled')
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE replay SET cursor=999,plan=? WHERE id=1', ('uncommitted-' * 45000,))
        db.execute('UPDATE spill_probe SET value=? WHERE id=1', ('spill-' * 90000,))
        journal = Path(str(replay.path) + '-journal').read_bytes()
        changed_page = replay.path.read_bytes()[page_start:page_start + page_size]
        if (not db.in_transaction or journal[:8] != JOURNAL_MAGIC
                or int.from_bytes(journal[8:12], 'big') == 0
                or changed_page == committed_page):
            raise AssertionError('Required hot journal and spilled replay page were not produced')
        atomic_write(witness, json.dumps({'point': 'uncommitted_hot_journal', 'mode': mode,
            'binding': replay.binding, 'cursor': cursor, 'plan': plan, 'economics': economics,
            'page_start': page_start, 'page_size': page_size,
            'committed_page_sha256': hashlib.sha256(committed_page).hexdigest(),
            'spilled_page_sha256': hashlib.sha256(changed_page).hexdigest(),
            'journal_header': journal[:28].hex()}).encode())
        os._exit(73)  # Bypass rollback, context-manager exit, and interpreter cleanup.


class ReplayStorageTests(unittest.TestCase):
    expected_mode = EXPECTED_MODE

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'workspace').ensure()
        self.fixture = _fixture(self.paths.state)
        self.fixture.broker.reconcile({'account_id': 'replay', 'cash': '1000000',
                                       'positions': {}, 'orders': {}, 'fills': {}})

    def test_each_connection_configures_full_and_keeps_legacy_delete_state(self):
        replay = self.fixture.replay
        with closing(sqlite3.connect(replay.path)) as db, db:
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone(), ('delete',))
            db.execute("UPDATE replay SET cursor=3,active=1,plan='[]' WHERE id=1")
        rebound = self.fixture.new_replay()
        self.assertEqual(rebound.binding, replay.binding)
        for _ in range(3):
            with rebound._db() as db:
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), (self.expected_mode,))
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
                self.assertEqual(db.execute('SELECT cursor,active,plan FROM replay').fetchone(), (3, 1, '[]'))
        self.assertFalse(self.fixture.broker.snapshot()['orders'])
        with self.fixture.broker._transaction() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('delete',))
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))

    def test_full_setup_failure_closes_connection_before_replay_sql(self):
        real_connect = sqlite3.connect
        original = self.fixture.replay.path.read_bytes()
        economics = _economics(self.fixture.broker)
        opened, statements = [], []

        class FailedSetup(sqlite3.Connection):
            closed = False

            def execute(connection, sql, *args):
                statements.append(sql)
                if ''.join(sql.upper().split()) == 'PRAGMASYNCHRONOUS=FULL':
                    raise sqlite3.OperationalError('injected FULL setup failure')
                return super(FailedSetup, connection).execute(sql, *args)

            def close(connection):
                connection.closed = True
                return super(FailedSetup, connection).close()

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=FailedSetup)
            opened.append(connection)
            return connection

        try:
            with patch('quantlab.paper_replay.sqlite3.connect', side_effect=connect):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'injected FULL setup failure'):
                    self.fixture.new_replay()
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed)
            self.assertEqual(statements, ['PRAGMA synchronous=FULL'])
            with self.assertRaises(sqlite3.ProgrammingError):
                sqlite3.Connection.execute(opened[0], 'SELECT 1')
        finally:
            # Cleanup even when this regression correctly fails on an old build.
            for connection in opened:
                sqlite3.Connection.close(connection)
        self.assertEqual(self.fixture.replay.path.read_bytes(), original)
        self.assertEqual(_economics(self.fixture.broker), economics)

    def test_concurrent_snapshot_start_stop_and_step_do_not_retain_replay_lock(self):
        replay = self.fixture.replay
        other = self.fixture.new_replay()
        for instance in (replay, other):
            _check_mode(instance, self.expected_mode)
            instance.targets = {1: 1}
        replay.start()
        paused, release = threading.Event(), threading.Event()
        result, failures = [], []

        def pause(point):
            if point == 'after_empty_cursor':
                paused.set()
                if not release.wait(10):
                    raise AssertionError('Concurrent stop never released the committed boundary')

        def run():
            try:
                result.append(replay.step(max_bars=120))
            except BaseException as error:
                failures.append(error)

        replay._fault = pause
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            self.assertTrue(paused.wait(10), 'Committed empty-bar boundary was not exercised')
            self.assertEqual(other.snapshot()['cursor'], 1)
            self.assertEqual(other.start()['cursor'], 1)
            with self.assertRaisesRegex(ValidationError, 'already active'):
                other.step(max_bars=1)
            stopped = other.stop()
            self.assertEqual(stopped['cursor'], 1)
            self.assertFalse(stopped['active'])
            self.assertTrue(self.fixture.broker.snapshot()['kill_switch'])
        finally:
            release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive(), 'Step did not release after stop')
        self.assertFalse(failures, failures)
        self.assertEqual([value['cursor'] for value in result], [1])
        self.assertEqual(other.snapshot()['cursor'], 1)
        self.assertFalse(self.fixture.broker.snapshot()['orders'])

    def _child(self, function, boundary):
        witness = Path(self.temp.name) / (boundary + '.json')
        script = ('from tests.test_paper_replay_storage import ' + function + '\n' + function
                  + '(*__import__("json").loads(__import__("sys").argv[1]))')
        args = [str(self.paths.state), str(witness), self.expected_mode]
        if function == '_die_at_boundary':
            args.append(boundary)
        result = subprocess.run([sys.executable, '-c', script, json.dumps(args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        self.assertTrue(witness.is_file(), 'Child did not prove its requested boundary')
        proof = json.loads(witness.read_text(encoding='utf-8'))
        self.assertEqual(proof['point'], boundary)
        self.assertEqual(proof['mode'], self.expected_mode)
        return proof

    def _backup_restore_before_sqlite_open(self, boundary):
        # Only byte reads before backup: SQLite must not recover/normalize journals yet.
        before = {path.relative_to(self.paths.state).as_posix(): path.read_bytes()
                  for path in self.paths.state.rglob('*') if path.is_file()}
        journal = 'replay.sqlite3-journal'
        if self.expected_mode in ('truncate', 'persist') or boundary == 'uncommitted_hot_journal':
            self.assertIn(journal, before, 'Expected retained/hot journal was not exercised')
        manager = BackupManager(self.paths)
        archive = Path(self.temp.name) / (boundary + '.zip')
        manager.create(archive)
        with zipfile.ZipFile(archive) as source:
            self.assertEqual(set(source.namelist()), {'manifest.json'} | {'state/' + name for name in before})
            for name, raw in before.items():
                self.assertEqual(source.read('state/' + name), raw)
        original_path = self.fixture.replay.path.resolve()
        self.fixture.replay.path.write_bytes(b'owned fixture changed after verified backup')
        manager.restore(archive)
        self.assertEqual(self.fixture.replay.path.resolve(), original_path)
        restored = {path.relative_to(self.paths.state).as_posix(): path.read_bytes()
                    for path in self.paths.state.rglob('*') if path.is_file()}
        self.assertEqual(restored, before)

    def _resume_once(self, proof, cursor, pending, target_index):
        fixture = _fixture(self.paths.state)
        replay, broker = fixture.replay, fixture.broker
        _check_mode(replay, self.expected_mode)
        self.assertEqual(replay.binding, proof['binding'])
        state = replay.snapshot()
        self.assertEqual(state['cursor'], cursor)
        self.assertEqual(state['pending_plan'], pending)
        self.assertTrue(state['active'])
        self.assertEqual(_economics(broker), proof['economics'])
        if 'committed_page_sha256' in proof:
            raw = replay.path.read_bytes()
            start = proof['page_start']
            self.assertEqual(hashlib.sha256(raw[start:start + proof['page_size']]).hexdigest(),
                             proof['committed_page_sha256'])
        self.assertTrue(broker.snapshot()['reconciliation_required'])
        self.assertEqual(replay.step(max_bars=2)['cursor'], cursor)
        with self.assertRaisesRegex(ValidationError, 'Reconcile'):
            replay.start()
        if pending:
            with replay._db() as db:
                plan = db.execute('SELECT plan FROM replay WHERE id=1').fetchone()[0]
            self.assertEqual([order['client_order_id'] for order in json.loads(plan)],
                             [content_hash([replay.binding, 0, 0])])
            if 'plan' in proof:
                self.assertEqual(plan, proof['plan'])
        broker.reconcile(broker.snapshot())
        replay.targets = {target_index: 1}
        replay.start()
        self.assertEqual(replay.step(max_bars=2)['cursor'], cursor + 2)
        state = broker.snapshot()
        order_id = content_hash([replay.binding, target_index, 0])
        self.assertEqual(set(state['orders']), {order_id})
        self.assertEqual(set(state['fills']), {order_id + ':fill'})
        self.assertEqual(state['fills'][order_id + ':fill']['order_id'], order_id)
        self.assertEqual(len(state['order_send_timestamps']), 1)
        self.assertEqual(state['positions'], {fixture.broker.instrument.contract_id: 1})
        after = _economics(broker)
        if proof['economics']['fills']:
            self.assertEqual(after, proof['economics'])
        self.assertTrue(replay.step(max_bars=120)['complete'])
        replay.start()
        self.assertTrue(replay.step(max_bars=120)['complete'])
        self.assertEqual(_economics(broker), after)
        with broker._transaction() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('delete',))
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
            self.assertEqual(dict(db.execute("SELECT operation,COUNT(*) FROM journal WHERE operation IN ('intent','event') GROUP BY operation")),
                             {'intent': 1, 'event': 1})
        return replay

    def test_real_process_death_boundaries_backup_same_path_and_resume_exactly_once(self):
        for boundary in ('after_plan_before_submit', 'after_fill_before_cursor', 'after_empty_cursor'):
            with self.subTest(boundary=boundary):
                # Separate owned workspace per boundary; every restore retains its original absolute path.
                self.paths = AppPaths(Path(self.temp.name) / boundary).ensure()
                self.fixture = _fixture(self.paths.state)
                self.fixture.broker.reconcile({'account_id': 'replay', 'cash': '1000000',
                                               'positions': {}, 'orders': {}, 'fills': {}})
                proof = self._child('_die_at_boundary', boundary)
                filled = int(boundary == 'after_fill_before_cursor')
                self.assertEqual(len(proof['economics']['fills']), filled)
                self.assertEqual(len(proof['economics']['orders']), filled)
                self.assertEqual(len(proof['economics']['order_send_timestamps']), filled)
                self._backup_restore_before_sqlite_open(boundary)
                empty = boundary == 'after_empty_cursor'
                self._resume_once(proof, int(empty), not empty, int(empty))

    def test_real_hot_journal_is_restored_before_recovery_of_spilled_uncommitted_page(self):
        proof = self._child('_die_with_hot_journal', 'uncommitted_hot_journal')
        journal = Path(str(self.fixture.replay.path) + '-journal').read_bytes()
        self.assertEqual(journal[:8], JOURNAL_MAGIC)
        self.assertGreater(int.from_bytes(journal[8:12], 'big'), 0)
        self.assertEqual(journal[:28].hex(), proof['journal_header'])
        raw = self.fixture.replay.path.read_bytes()
        start = proof['page_start']
        spilled = hashlib.sha256(raw[start:start + proof['page_size']]).hexdigest()
        self.assertEqual(spilled, proof['spilled_page_sha256'])
        self.assertNotEqual(spilled, proof['committed_page_sha256'])
        self._backup_restore_before_sqlite_open('uncommitted_hot_journal')
        replay = self._resume_once(proof, 0, True, 0)
        with replay._db() as db:
            self.assertEqual(db.execute('SELECT value FROM spill_probe').fetchone(), ('committed',))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
