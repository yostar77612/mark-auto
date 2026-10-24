"""WFO WAL/FULL admission, lifecycle and durable snapshot boundaries."""

from contextlib import closing
import json
import multiprocessing
import shutil
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from quantlab import walk_forward as wf
from quantlab.core import ValidationError
from tests.test_walk_forward import inputs, fake_worker


def crash_child(directory, cut, sender):
    root = Path(directory)
    output = root / 'run'
    data, plan = inputs()
    original_save = wf._save_state
    original_connect = sqlite3.connect
    original_reserve = wf._reserve_holdout
    original_write = Path.write_text
    original_replace = wf.replace_file
    active = {}
    last = {}

    def pause(db):
        payload = db.execute('SELECT payload FROM state').fetchone()[0]
        sender.send(
            {
                'payload': last.get('payload', payload) if cut == 'uncommitted_spill' else payload,
                'mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                'full': db.execute('PRAGMA synchronous').fetchone()[0],
            }
        )
        sender.close()
        time.sleep(30)

    class Connection(sqlite3.Connection):
        def commit(db):
            super().commit()
            if cut == 'commit' and active.get('db') is db:
                pause(db)

    def connect(path, *args, **kwargs):
        if str(path).endswith('walk_forward.sqlite3'):
            kwargs['factory'] = Connection
        return original_connect(path, *args, **kwargs)

    def write(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if cut == 'json_write' and path.name == 'walk_forward.json.tmp':
            pause(active['db'])
        return result

    def replace(path, *args, **kwargs):
        result = original_replace(path, *args, **kwargs)
        if cut == 'replace' and path.name == 'walk_forward.json.tmp':
            pause(active['db'])
        return result

    def reserve(*args, **kwargs):
        value = original_reserve(*args, **kwargs)
        if cut == 'registry_commit':
            pause(active['db'])
        return value

    def save(db, folder, state):
        active['db'] = db
        original_save(db, folder, state)
        records = state['evaluations']
        if (
            cut == 'reservation'
            and state['registry_reservation'] is not None
            or cut == 'evaluation_reserved'
            and records
            and records[-1]['status'] == 'running'
            or cut == 'receipt'
            and records
            and records[-1]['status'] == 'evaluated'
            or cut == 'selection'
            and any(f['status'] == 'selection_frozen' for f in state['folds'])
            or cut == 'terminal'
            and state['status'] == 'completed'
        ):
            pause(db)
        if cut == 'uncommitted_spill':
            last['payload'] = db.execute('SELECT payload FROM state').fetchone()[0]
            db.execute('PRAGMA cache_size=1')
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE state SET payload=?', ('uncommitted' * 150000,))
            pause(db)

    with (
        patch.object(sqlite3, 'connect', side_effect=connect),
        patch.object(wf, '_save_state', side_effect=save),
        patch.object(wf, '_run_bounded', side_effect=fake_worker),
        patch.object(wf, '_reserve_holdout', side_effect=reserve),
        patch.object(Path, 'write_text', write),
        patch.object(wf, 'replace_file', replace),
    ):
        wf.run_walk_forward(data, plan=plan, output_dir=output, holdout_registry_path=root / 'controls' / 'holdout.sqlite3')


class WalkForwardWalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'run'
        self.path = self.output / 'walk_forward.sqlite3'
        self.registry = self.root / 'controls' / 'holdout.sqlite3'
        self.data, self.plan = inputs()

    def run_cancelled(self):
        return wf.run_walk_forward(self.data, plan=self.plan, output_dir=self.output, holdout_registry_path=self.registry, cancelled=lambda: True)

    def routes(self):
        return (
            self.run_cancelled,
            lambda: wf.read_walk_forward_state(self.output),
            lambda: wf.reconcile_interrupted_walk_forward(output_dir=self.output, descendants_stopped=True),
        )

    def test_all_entry_routes_reject_unsafe_runtime_before_any_sql_even_checkpointed_wal(self):
        self.run_cancelled()
        self.assertFalse(Path(str(self.path) + '-wal').exists())
        before = self.path.read_bytes()
        for route in self.routes():
            with self.subTest(route=route), patch.object(sqlite3, 'sqlite_version_info', (3, 51, 2)), patch.object(sqlite3, 'connect') as connect:
                with self.assertRaisesRegex(ValidationError, 'patched SQLite'):
                    route()
                connect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_entry_routes_reject_unverified_filesystem_before_any_sql(self):
        for route in self.routes():
            with (
                self.subTest(route=route),
                patch.object(wf, '_require_local_wal_path', side_effect=ValidationError('local filesystem')),
                patch.object(sqlite3, 'connect') as connect,
            ):
                with self.assertRaisesRegex(ValidationError, 'local filesystem'):
                    route()
                connect.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_new_journal_selects_full_wal_and_original_two_commit_export_boundaries(self):
        real = sqlite3.connect
        handles = []
        traces = []
        profiles = []
        original_save = wf._save_state

        def connect(path, *args, **kwargs):
            db = real(path, *args, **kwargs)
            if str(path).endswith('walk_forward.sqlite3'):
                handles.append(db)
                db.set_trace_callback(traces.append)
            return db

        def save(db, *args):
            profiles.append(tuple(db.execute('PRAGMA ' + key).fetchone()[0] for key in ('journal_mode', 'synchronous', 'wal_autocheckpoint')))
            return original_save(db, *args)

        with patch.object(sqlite3, 'connect', side_effect=connect), patch.object(wf, '_save_state', side_effect=save):
            self.run_cancelled()
        self.assertEqual(profiles, [('wal', 2, 1000)] * 2)
        self.assertEqual(traces.count('COMMIT'), 2)
        self.assertEqual(sum(t.startswith('INSERT OR REPLACE') for t in traces), 2)
        self.assertLess(traces.index('PRAGMA journal_mode=WAL'), traces.index('BEGIN'))
        self.assertLess(traces.index('BEGIN'), next(i for i, t in enumerate(traces) if t.startswith('CREATE TABLE')))
        for handle in handles:
            with self.assertRaises(sqlite3.ProgrammingError):
                handle.execute('SELECT 1')
        self.assertFalse(Path(str(self.path) + '-wal').exists())
        self.assertFalse(Path(str(self.path) + '-shm').exists())

    def test_complete_wal_and_legacy_delete_streams_have_identical_bytes_and_boundaries(self):
        original_connect = sqlite3.connect
        original_write = Path.write_text
        original_replace = wf.replace_file
        streams = []
        for legacy in (True, False):
            events = []
            modes = []
            if legacy:
                self.output.mkdir()
                self.path.touch()

            class Counting(sqlite3.Connection):
                def commit(db):
                    super().commit()
                    events.append(('commit', db.execute('SELECT payload FROM state').fetchone()[0]))
                    modes.append((db.execute('PRAGMA journal_mode').fetchone()[0], db.execute('PRAGMA synchronous').fetchone()[0]))

            def connect(path, *args, **kwargs):
                if str(path).endswith('walk_forward.sqlite3'):
                    kwargs['factory'] = Counting
                return original_connect(path, *args, **kwargs)

            def write(path, text, *args, **kwargs):
                value = original_write(path, text, *args, **kwargs)
                if path.name == 'walk_forward.json.tmp':
                    events.append(('write', text))
                return value

            def replace(path, *args, **kwargs):
                value = original_replace(path, *args, **kwargs)
                if path.name == 'walk_forward.json.tmp':
                    events.append(('replace', None))
                return value

            with (
                patch.object(sqlite3, 'connect', side_effect=connect),
                patch.object(wf.time, 'monotonic', return_value=100),
                patch.object(wf, '_run_bounded', side_effect=fake_worker),
                patch.object(Path, 'write_text', write),
                patch.object(wf, 'replace_file', replace),
            ):
                result = wf.run_walk_forward(self.data, plan=self.plan, output_dir=self.output, holdout_registry_path=self.registry)
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(modes)
            self.assertEqual(set(modes), {('delete' if legacy else 'wal', 2)})
            self.assertEqual([kind for kind, _ in events], ['commit', 'write', 'replace'] * len(modes))
            streams.append(events)
            shutil.rmtree(self.output)
            shutil.rmtree(self.registry.parent)
        self.assertEqual(streams[0], streams[1])

    def test_setup_refusal_closes_connection_before_schema_or_snapshot(self):
        real = sqlite3.connect
        for refused in ('PRAGMA synchronous', 'PRAGMA journal_mode=WAL', 'PRAGMA wal_autocheckpoint'):
            with self.subTest(refused=refused), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'run'
                handles = []
                traces = []

                class Refusal(sqlite3.Connection):
                    def execute(db, sql, *args):
                        if sql == refused:
                            return super().execute('SELECT -1')
                        return super().execute(sql, *args)

                def connect(path, *args, **kwargs):
                    if str(path).endswith('walk_forward.sqlite3'):
                        kwargs['factory'] = Refusal
                    db = real(path, *args, **kwargs)
                    handles.append(db)
                    db.set_trace_callback(traces.append)
                    return db

                with patch.object(sqlite3, 'connect', side_effect=connect):
                    with self.assertRaises(ValidationError):
                        wf.run_walk_forward(self.data, plan=self.plan, output_dir=output, holdout_registry_path=self.registry, cancelled=lambda: True)
                self.assertFalse(any(t.startswith('CREATE TABLE') for t in traces))
                self.assertFalse((output / 'walk_forward.json').exists())
                for db in handles:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        db.execute('SELECT 1')

    def test_legacy_delete_terminal_read_run_and_reconcile_preserve_exact_bytes_and_mode(self):
        state = self.run_cancelled()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone(), ('delete',))
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        traces = []
        real = sqlite3.connect

        def connect(*args, **kwargs):
            db = real(*args, **kwargs)
            db.set_trace_callback(traces.append)
            return db

        with patch.object(sqlite3, 'connect', side_effect=connect), patch.object(wf, '_save_state', side_effect=AssertionError('terminal write')):
            for route in self.routes():
                self.assertEqual(route(), state)
        self.assertNotIn('PRAGMA journal_mode=WAL', traces)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_pinned_reader_busy_checkpoint_retains_durable_commits_and_readonly_visibility(self):
        state = self.run_cancelled()
        with closing(sqlite3.connect(self.path, timeout=0)) as writer, closing(sqlite3.connect(self.path)) as reader:
            wf._configure_state_storage(writer)
            reader.execute('BEGIN')
            reader.execute('SELECT payload FROM state').fetchone()
            state['elapsed_seconds'] += 1
            wf._save_state(writer, self.output, state)
            self.assertEqual(writer.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()[0], 0)
            busy = writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            self.assertEqual(busy[0], 1)
            self.assertGreater(Path(str(self.path) + '-wal').stat().st_size, 32)
            self.assertEqual(wf.read_walk_forward_state(self.output), state)
            reader.rollback()
            self.assertEqual(writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone(), (0, 0, 0))
        self.assertEqual(wf.read_walk_forward_state(self.output), state)

    def test_real_death_cuts_keep_committed_wal_and_raw_restore_before_any_reopen(self):
        for cut in (
            'commit',
            'json_write',
            'replace',
            'registry_commit',
            'reservation',
            'evaluation_reserved',
            'receipt',
            'selection',
            'terminal',
            'uncommitted_spill',
        ):
            with self.subTest(cut=cut), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / 'run'
                path = output / 'walk_forward.sqlite3'
                context = multiprocessing.get_context('spawn')
                reader, sender = context.Pipe(duplex=False)
                child = context.Process(target=crash_child, args=(directory, cut, sender))
                child.start()
                sender.close()
                try:
                    self.assertTrue(reader.poll(10), 'crash cut not reached')
                    proof = reader.recv()
                finally:
                    if child.is_alive():
                        child.kill()
                    child.join(5)
                    reader.close()
                    stopped = not child.is_alive()
                    if stopped:
                        child.close()
                self.assertTrue(stopped)
                self.assertEqual((proof['mode'], proof['full']), ('wal', 2))
                self.assertGreater(Path(str(path) + '-wal').stat().st_size, 32)
                if cut == 'uncommitted_spill':
                    self.assertGreater(Path(str(path) + '-wal').stat().st_size, 1000000)
                # Capture all raw bytes before any SQLite open/checkpoint/recovery.
                archived = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
                self.assertIn('walk_forward.sqlite3-shm', archived)
                expected = json.loads(proof['payload'])
                registry_path = root / 'controls' / 'holdout.sqlite3'
                registry_count = 0
                if registry_path.exists():
                    with closing(sqlite3.connect(registry_path)) as registry:
                        registry_count = registry.execute('SELECT count(*) FROM reservations').fetchone()[0]
                for target in (root / 'fresh', root / 'missing-shm', output):
                    target.mkdir(exist_ok=True)
                    for p in target.iterdir():
                        if p.is_file():
                            p.unlink()
                    for name, raw in archived.items():
                        (target / name).write_bytes(raw)
                    self.assertEqual(archived, {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()})
                    if target.name == 'missing-shm':
                        (target / 'walk_forward.sqlite3-shm').unlink()
                    actual = wf.read_walk_forward_state(target)
                    self.assertEqual(actual, expected)
                    # Authoritative main/WAL bytes survive read-only observation;
                    # SHM is rebuildable auxiliary coordination data.
                    for name in ('walk_forward.sqlite3', 'walk_forward.sqlite3-wal'):
                        self.assertEqual((target / name).read_bytes(), archived[name])
                    with patch.object(wf, '_run_bounded', side_effect=AssertionError('must never repeat evaluation')):
                        reconciled = wf.reconcile_interrupted_walk_forward(output_dir=target, descendants_stopped=True)
                    self.assertEqual(len(reconciled['evaluations']), len(expected['evaluations']))
                    self.assertEqual(reconciled['registry_reservation'], expected['registry_reservation'])
                    self.assertEqual(reconciled['status'], 'completed' if cut == 'terminal' else 'blocked_interrupted')
                    self.assertTrue(all(row['status'] != 'running' for row in reconciled['evaluations']))
                    with (
                        patch.object(wf, '_run_bounded', side_effect=AssertionError('must never repeat evaluation')),
                        patch.object(wf, '_reserve_holdout', side_effect=AssertionError('must never reserve again')),
                    ):
                        self.assertEqual(wf.run_walk_forward(self.data, plan=self.plan, output_dir=target, holdout_registry_path=registry_path), reconciled)
                    if registry_path.exists():
                        with closing(sqlite3.connect(registry_path)) as registry:
                            self.assertEqual(registry.execute('SELECT count(*) FROM reservations').fetchone()[0], registry_count)
                    with closing(sqlite3.connect(target / 'walk_forward.sqlite3')) as db:
                        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))
