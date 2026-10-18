"""New WFO schema joins its first snapshot; original durable boundaries remain."""
from contextlib import closing
import json
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from quantlab import walk_forward as wf
from quantlab.core import canonical_json, content_hash
from tests.test_walk_forward import inputs


def pending_schema_child(directory, sender):
    data, plan = inputs()
    root = Path(directory)
    def pause(db, output, state):
        sender.send({'pending': db.in_transaction})
        sender.close()
        import time
        time.sleep(30)
    with patch.object(wf, '_save_state', side_effect=pause):
        wf.run_walk_forward(data, plan=plan, output_dir=root / 'run',
                            holdout_registry_path=root / 'controls' / 'holdout.sqlite3')


class WalkForwardInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'run'
        self.database = self.output / 'walk_forward.sqlite3'
        self.registry = self.root / 'controls' / 'holdout.sqlite3'
        self.data, self.plan = inputs()

    def run_cancelled(self):
        return wf.run_walk_forward(self.data, plan=self.plan, output_dir=self.output,
                                   holdout_registry_path=self.registry, cancelled=lambda: True)

    def state_tables(self):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='state'").fetchall()

    def test_schema_and_first_snapshot_are_one_transaction_with_original_commit_export_order(self):
        events = []; original_connect = sqlite3.connect; original_write = Path.write_text
        def connect(path, *args, **kwargs):
            db = original_connect(path, *args, **kwargs)
            if Path(path).name == 'walk_forward.sqlite3':
                db.set_trace_callback(lambda sql: events.append(sql))
            return db
        def write(path, *args, **kwargs):
            if path.name == 'walk_forward.json.tmp': events.append('EXPORT')
            return original_write(path, *args, **kwargs)
        original_save = wf._save_state; calls = []
        def save(db, output, state):
            if not calls:
                self.assertTrue(db.in_transaction)
                self.assertEqual(self.state_tables(), [])
            expected = dict(state)
            expected['summary'] = wf._state_summary(expected)
            expected['state_hash'] = content_hash({k: v for k, v in expected.items() if k != 'state_hash'})
            original_save(db, output, state)
            self.assertFalse(db.in_transaction)
            self.assertEqual((output / 'walk_forward.json').read_text(encoding='utf-8'), canonical_json(expected))
            self.assertEqual(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0], canonical_json(expected))
            calls.append(state['status'])
        with patch.object(sqlite3, 'connect', side_effect=connect), patch.object(Path, 'write_text', write), \
                patch.object(wf, '_save_state', side_effect=save):
            result = self.run_cancelled()
        begin = next(i for i, text in enumerate(events) if text == 'BEGIN')
        create = next(i for i, text in enumerate(events) if text.startswith('CREATE TABLE'))
        insert = next(i for i, text in enumerate(events) if text.startswith('INSERT OR REPLACE'))
        self.assertLess(begin, create); self.assertLess(create, insert)
        self.assertLess(insert, events.index('COMMIT')); self.assertLess(events.index('COMMIT'), events.index('EXPORT'))
        self.assertEqual(events.count('COMMIT'), 2); self.assertEqual(events.count('EXPORT'), 2)
        self.assertEqual(calls, ['running', 'cancelled'])
        self.assertEqual(result['evaluations'], []); self.assertFalse(self.registry.exists())
        with closing(original_connect(self.database)) as db:
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))

    def test_initial_snapshot_exception_rolls_back_schema_and_releases_both_connections(self):
        with patch.object(wf, '_save_state', side_effect=RuntimeError('before first commit')):
            with self.assertRaisesRegex(RuntimeError, 'before first commit'): self.run_cancelled()
        self.assertEqual(self.state_tables(), [])
        self.assertFalse(self.registry.exists())
        self.assertFalse((self.output / 'walk_forward.json').exists())
        with closing(sqlite3.connect(self.output / 'walk_forward.lock.sqlite3', timeout=0)) as lock:
            lock.execute('BEGIN EXCLUSIVE'); lock.rollback()
        self.assertEqual(self.run_cancelled()['status'], 'cancelled')

    def test_initial_commit_failure_cannot_publish_schema_snapshot_or_registry(self):
        original = sqlite3.connect
        class Failure(sqlite3.Connection):
            def commit(self): raise sqlite3.OperationalError('initial commit failure')
        def connect(path, *args, **kwargs):
            if Path(path).name == 'walk_forward.sqlite3': kwargs['factory'] = Failure
            return original(path, *args, **kwargs)
        with patch.object(sqlite3, 'connect', side_effect=connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'initial commit failure'): self.run_cancelled()
        self.assertEqual(self.state_tables(), [])
        self.assertFalse((self.output / 'walk_forward.json').exists()); self.assertFalse(self.registry.exists())
        self.assertEqual(self.run_cancelled()['status'], 'cancelled')

    def test_export_failure_preserves_committed_first_snapshot_and_terminal_reopen(self):
        original = Path.write_text
        def fail(path, *args, **kwargs):
            if path.name == 'walk_forward.json.tmp': raise OSError('initial export failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail):
            with self.assertRaisesRegex(OSError, 'initial export failure'): self.run_cancelled()
        state = wf.read_walk_forward_state(self.output)
        self.assertEqual(state['status'], 'running'); self.assertEqual(state['evaluations'], [])
        self.assertIsNone(state['registry_reservation']); self.assertFalse(self.registry.exists())
        with patch.object(wf, '_run_bounded', side_effect=AssertionError('must not evaluate')):
            result = self.run_cancelled()
        self.assertEqual(result['status'], 'blocked_interrupted'); self.assertFalse(self.registry.exists())

    def test_existing_terminal_journal_reopen_preserves_bytes_and_storage_mode(self):
        original = self.run_cancelled()
        # Explicit historical rollback fixture: new journals now select WAL.
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone(), ('delete',))
        before = {path.name: path.read_bytes() for path in self.output.iterdir() if path.is_file()}
        with patch.object(wf, '_save_state', side_effect=AssertionError('terminal must stay read-only')):
            self.assertEqual(self.run_cancelled(), original)
            self.assertEqual(wf.read_walk_forward_state(self.output), original)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir() if path.is_file()})
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('delete',))

    def test_existing_empty_file_keeps_legacy_initialization_path(self):
        self.output.mkdir(); self.database.touch()
        original_save = wf._save_state; observed = []
        def save(db, output, state):
            observed.append(db.in_transaction)
            return original_save(db, output, state)
        with patch.object(wf, '_save_state', side_effect=save): self.run_cancelled()
        self.assertEqual(observed, [False, False])

    def test_real_process_death_before_first_snapshot_leaves_no_accepted_state_or_reservation(self):
        context = multiprocessing.get_context('spawn')
        reader, sender = context.Pipe(duplex=False)
        process = context.Process(target=pending_schema_child, args=(str(self.root), sender))
        process.start(); sender.close()
        try:
            self.assertTrue(reader.poll(5), 'initialization child did not reach precommit cut')
            self.assertEqual(reader.recv(), {'pending': True})
        finally:
            if process.is_alive(): process.kill()
            process.join(5); reader.close()
        self.assertFalse(process.is_alive(), 'owned child was not reaped')
        self.assertEqual(self.state_tables(), [])
        self.assertFalse(self.registry.exists()); self.assertFalse((self.output / 'walk_forward.json').exists())
        self.assertEqual(self.run_cancelled()['status'], 'cancelled')
