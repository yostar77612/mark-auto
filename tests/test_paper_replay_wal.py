"""Additional WAL/FULL gates; existing rollback fixtures and gates stay intact."""
from contextlib import closing
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from quantlab.core import ValidationError
from quantlab.paper_replay import PaperReplay, _require_local_wal_path
from tests import test_paper_replay as replay_tests
from tests import test_paper_replay_storage as storage_tests


def wal_replay(fixture):
    return PaperReplay(fixture.root / 'replay.sqlite3', dataset=fixture.data,
                       strategy=fixture.spec, broker=fixture.broker,
                       margin_per_contract=Decimal('100000'), margin_version='synthetic-v1',
                       storage_profile='wal_full')


class WalReplayTests(replay_tests.ReplayTests):
    # Run the complete original replay behavioral corpus with actual WAL storage.
    def new_replay(self):
        return wal_replay(self)

    def test_runtime_rejected_before_any_sql_or_path_creation(self):
        missing = self.root / 'missing' / 'replay.sqlite3'
        with patch('quantlab.paper_replay.sqlite3.sqlite_version_info', (3, 49, 1)), patch('quantlab.paper_replay.sqlite3.connect') as connect:
            with self.assertRaisesRegex(ValidationError, 'patched SQLite'):
                PaperReplay(missing, dataset=self.data, strategy=self.spec,
                            broker=self.broker, storage_profile='wal_full')
            connect.assert_not_called()
        self.assertFalse(missing.parent.exists())

    def test_legacy_caller_cannot_recover_existing_wal_on_unsafe_runtime(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch('quantlab.paper_replay.sqlite3.sqlite_version_info', (3, 49, 1)), patch('quantlab.paper_replay.sqlite3.connect') as connect:
            with self.assertRaisesRegex(ValidationError, 'patched SQLite'):
                replay_tests.ReplayTests.new_replay(self)
            connect.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_reuse_keeps_exactly_one_full_commit_per_empty_bar(self):
        self.replay.targets = {}
        self.replay.start()
        opened, statements, observed = [], [], []
        real_connect = sqlite3.connect
        def connect(path, *args, **kwargs):
            db = real_connect(path, *args, **kwargs)
            if Path(path) == self.replay.path:
                opened.append(db)
                db.set_trace_callback(statements.append)
            return db
        def boundary(point):
            if point == 'after_empty_cursor':
                db = opened[0]
                observed.append((db.in_transaction, db.execute('PRAGMA synchronous').fetchone()[0]))
        self.replay._fault = boundary
        with patch('quantlab.paper_replay.sqlite3.connect', side_effect=connect):
            self.assertTrue(self.replay.step(max_bars=120)['complete'])
        self.assertEqual(len(opened), 1)
        self.assertEqual(observed, [(False, 2)] * 120)
        self.assertEqual(statements.count('BEGIN '), 120)
        self.assertEqual(statements.count('COMMIT'), 120)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute('SELECT 1')

    def test_failed_commit_rolls_back_and_closes_step_handle(self):
        self.replay.targets = {}
        self.replay.start()
        real_connect = sqlite3.connect
        opened = []
        class FailedCommit(sqlite3.Connection):
            def __exit__(db, *args):
                if db.in_transaction:
                    db.rollback()
                    raise sqlite3.OperationalError('injected WAL commit failure')
                return super().__exit__(*args)
        def connect(path, *args, **kwargs):
            db = real_connect(path, *args, factory=FailedCommit, **kwargs)
            if Path(path) == self.replay.path:
                opened.append(db)
            return db
        with patch('quantlab.paper_replay.sqlite3.connect', side_effect=connect):
            with self.assertRaisesRegex(ValidationError, 'storage is unavailable'):
                self.replay.step(max_bars=1)
        self.assertEqual(self.replay.snapshot()['cursor'], 0)
        for db in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
        self.assertEqual(self.replay.step(max_bars=1)['cursor'], 1)

    def test_external_journal_mode_change_is_not_silently_accepted(self):
        with closing(sqlite3.connect(self.replay.path)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone(), ('delete',))
        with self.assertRaisesRegex(ValidationError, 'changed externally'):
            self.replay.snapshot()

    def test_full_readback_failure_closes_without_any_replay_writes(self):
        real_connect = sqlite3.connect
        opened = []
        class WrongFull(sqlite3.Connection):
            def execute(db, sql, *args):
                if sql == 'PRAGMA synchronous':
                    return super().execute('SELECT 1')
                return super().execute(sql, *args)
        def connect(path, *args, **kwargs):
            db = real_connect(path, *args, factory=WrongFull, **kwargs)
            opened.append(db)
            return db
        with patch('quantlab.paper_replay.sqlite3.connect', side_effect=connect):
            with self.assertRaisesRegex(ValidationError, 'FULL replay durability'):
                self.replay.snapshot()
        for db in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
        self.assertEqual(self.replay.snapshot()['cursor'], 0)

    def test_windows_network_or_unavailable_drive_is_rejected(self):
        for drive_type in (0, 1, 4, 5):
            with self.subTest(drive_type=drive_type), patch('quantlab.paper_replay.sys.platform', 'win32'), patch('ctypes.windll', create=True) as windll:
                windll.kernel32.GetDriveTypeW.return_value = drive_type
                with self.assertRaisesRegex(ValidationError, 'local drive'):
                    _require_local_wal_path(self.root)

    def test_linux_nested_network_mount_and_unknown_filesystem_are_rejected(self):
        for filesystem in ('nfs', 'cifs', 'fuse.sshfs', 'unknown'):
            mounts = '1 0 0:1 / / rw - ext4 /dev/root rw\n2 1 0:2 / /mnt/net rw - ' + filesystem + ' source rw\n'
            with self.subTest(filesystem=filesystem), patch('quantlab.paper_replay.sys.platform', 'linux'), patch.object(Path, 'read_text', return_value=mounts):
                with self.assertRaisesRegex(ValidationError, 'verified local'):
                    _require_local_wal_path(Path('/mnt/net/replay.sqlite3'))


class WalStorageTests(unittest.TestCase):
    expected_mode = 'wal'
    setUp = storage_tests.ReplayStorageTests.setUp
    _child = storage_tests.ReplayStorageTests._child
    _resume_once = storage_tests.ReplayStorageTests._resume_once
    test_full_setup_failure_closes_connection_before_replay_sql = storage_tests.ReplayStorageTests.test_full_setup_failure_closes_connection_before_replay_sql
    test_concurrent_snapshot_start_stop_and_step_do_not_retain_replay_lock = storage_tests.ReplayStorageTests.test_concurrent_snapshot_start_stop_and_step_do_not_retain_replay_lock
    test_real_process_death_boundaries_backup_same_path_and_resume_exactly_once = storage_tests.ReplayStorageTests.test_real_process_death_boundaries_backup_same_path_and_resume_exactly_once

    def setUp(self):
        storage_tests.ReplayStorageTests.setUp(self)
        self.fixture.replay = wal_replay(self.fixture)

    def test_same_instance_concurrent_controls_use_separate_connections(self):
        self.fixture.new_replay = lambda: self.fixture.replay
        storage_tests.ReplayStorageTests.test_concurrent_snapshot_start_stop_and_step_do_not_retain_replay_lock(self)

    def _child(self, function, boundary):
        # Original death corpus creates a fresh workspace at each boundary.
        self.fixture.replay = wal_replay(self.fixture)
        return storage_tests.ReplayStorageTests._child(self, function, boundary)

    def _backup_restore_before_sqlite_open(self, boundary):
        wal = Path(str(self.fixture.replay.path) + '-wal')
        self.assertTrue(wal.is_file(), 'Death must leave actual uncheckpointed WAL')
        self.assertGreater(wal.stat().st_size, 32)
        self.assertTrue(Path(str(self.fixture.replay.path) + '-shm').is_file())
        storage_tests.ReplayStorageTests._backup_restore_before_sqlite_open(self, boundary)

    def test_migration_preserves_legacy_binding_cursor_and_pending_plan(self):
        replay = self.fixture.replay
        with closing(sqlite3.connect(replay.path)) as db, db:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute("UPDATE replay SET cursor=3,active=1,plan='[]' WHERE id=1")
        migrated = wal_replay(self.fixture)
        self.assertEqual(migrated.binding, replay.binding)
        with migrated._db() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
            self.assertEqual(db.execute('SELECT cursor,active,plan FROM replay').fetchone(), (3, 1, '[]'))

    def test_legacy_hot_journal_recovers_before_wal_migration(self):
        with closing(sqlite3.connect(self.fixture.replay.path)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone(), ('delete',))
        self.expected_mode = 'delete'
        proof = storage_tests.ReplayStorageTests._child(self, '_die_with_hot_journal', 'uncommitted_hot_journal')
        journal = Path(str(self.fixture.replay.path) + '-journal').read_bytes()
        self.assertEqual(journal[:8], storage_tests.JOURNAL_MAGIC)
        storage_tests.ReplayStorageTests._backup_restore_before_sqlite_open(self, 'uncommitted_hot_journal')
        self.fixture.replay = wal_replay(self.fixture)
        self.expected_mode = 'wal'
        replay = self._resume_once(proof, 0, True, 0)
        with replay._db() as db:
            self.assertEqual(db.execute('SELECT value FROM spill_probe').fetchone(), ('committed',))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_uncommitted_wal_spill_is_discarded_after_death_backup_restore(self):
        witness = self.paths.root / 'witness.json'
        result = subprocess.run([sys.executable, '-c',
            'from tests.test_paper_replay_wal import die_uncommitted; import sys; die_uncommitted(*sys.argv[1:])',
            str(self.paths.state), str(witness)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        proof = json.loads(witness.read_text())
        self.assertGreater(proof['wal_size'], proof['committed_wal_size'])
        self.assertTrue(proof['in_transaction'])
        self._backup_restore_before_sqlite_open('uncommitted_wal')
        fixture = storage_tests._fixture(self.paths.state)
        with fixture.replay._db() as db:
            self.assertEqual(db.execute('SELECT cursor,plan FROM replay').fetchone(), (1, None))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertFalse(fixture.broker.snapshot()['orders'])
        self.assertTrue(fixture.broker.snapshot()['reconciliation_required'])
        fixture.broker.reconcile(fixture.broker.snapshot())
        fixture.replay.targets = {}
        fixture.replay.start()
        self.assertTrue(fixture.replay.step(max_bars=120)['complete'])
        self.assertFalse(fixture.broker.snapshot()['orders'])


def die_uncommitted(state, witness):
    fixture = storage_tests._fixture(state)
    replay = wal_replay(fixture)
    fixture.broker.reconcile(fixture.broker.snapshot())
    replay.start()
    # Keep a real connection alive so the committed cursor stays in the WAL.
    with replay._connection() as db:
        with replay._db(db):
            db.execute('UPDATE replay SET cursor=1 WHERE id=1')
        committed_size = Path(str(replay.path) + '-wal').stat().st_size
        db.execute('PRAGMA cache_size=1')
        db.execute('PRAGMA cache_spill=ON')
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE replay SET cursor=999,plan=? WHERE id=1', ('uncommitted-' * 45000,))
        size = Path(str(replay.path) + '-wal').stat().st_size
        if size <= committed_size or not db.in_transaction:
            raise AssertionError('Uncommitted WAL spill was not exercised')
        Path(witness).write_text(json.dumps({'wal_size': size,
            'committed_wal_size': committed_size, 'in_transaction': db.in_transaction}))
        os._exit(73)
