"""The workspace barrier is durable before WAL and survives byte-copy recovery."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from quantlab.desktop_runtime import (AppPaths, BackupManager, RuntimeSafetyError,
    WorkspaceLocator, WORKSPACE_FORMAT, REPLAY_REQUIREMENT, _write_workspace_format)

GUARDED = {**WORKSPACE_FORMAT, 'sqlite_replay': REPLAY_REQUIREMENT}


class WorkspaceWALGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths(self.root / 'workspace').ensure()
        self.runtime = patch('quantlab.desktop_runtime._verify_replay_runtime')
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def released_module(self):
        # Actual published 0.2.1 source, not a reimplementation of its check.
        fixture = Path(__file__).parent / 'fixtures' / 'desktop_runtime_0_2_1.py.txt'
        raw = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'f9ba44bd191d05347a183da62d706008000c41841b9871ab01b4f6f73385637d')
        source = raw.decode('utf-8')
        module = types.ModuleType('quantlab._released_runtime_guard_test')
        module.__package__ = 'quantlab'
        import sys
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        exec(compile(source, '<released 0.2.1 desktop_runtime>', 'exec'), module.__dict__)
        return module

    def test_published_old_app_refuses_guard_and_archive(self):
        old = self.released_module()
        old.AppPaths(self.paths.root).ensure()
        self.paths.require_replay_wal()
        with self.assertRaises(old.RuntimeSafetyError):
            old.AppPaths(self.paths.root).ensure()
        with self.assertRaises(old.RuntimeSafetyError):
            old.WorkspaceLocator(self.root / 'bootstrap')._validate(self.paths.root)
        archive = BackupManager(self.paths).create(self.root / 'guarded.zip')
        old_paths = old.AppPaths(self.root / 'old').ensure()
        with self.assertRaises(old.RuntimeSafetyError):
            old.BackupManager(old_paths).restore(archive)

    def test_torn_guard_is_fail_closed_and_does_not_touch_state(self):
        state = self.paths.state / 'proof.sqlite3-wal'
        state.write_bytes(b'untouched frames')
        marker = self.paths.root / 'workspace-format.json'
        marker.write_bytes(b'{"kind":')
        with self.assertRaises(RuntimeSafetyError):
            self.paths.require_replay_wal()
        self.assertEqual(state.read_bytes(), b'untouched frames')
        self.assertEqual(marker.read_bytes(), b'{"kind":')

    def test_fsync_failure_aborts_before_caller_can_open_wal(self):
        opened = []
        with patch('quantlab.desktop_runtime.os.fsync', side_effect=OSError('flush failed')):
            with self.assertRaises(OSError):
                self.paths.require_replay_wal()
                opened.append(True)
        self.assertEqual(opened, [])

    def test_guard_inplace_retains_inode_and_flushes_file_then_directory(self):
        marker = self.paths.root / 'workspace-format.json'
        inode = marker.stat().st_ino
        with patch('quantlab.desktop_runtime.os.fsync', wraps=__import__('os').fsync) as flush:
            self.paths.require_replay_wal()
        self.assertEqual(marker.stat().st_ino, inode)
        self.assertGreaterEqual(flush.call_count, 1)
        self.assertEqual(json.loads(marker.read_text()), GUARDED)

    def test_restore_preserves_every_raw_byte_and_guard_fresh_and_same_path(self):
        self.paths.require_replay_wal()
        for name, data in [('replays/a.sqlite3', b'database'),
                           ('replays/a.sqlite3-wal', b'committed frames'),
                           ('replays/a.sqlite3-shm', b'shared memory')]:
            path = self.paths.state / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        original = {p.relative_to(self.paths.state): p.read_bytes() for p in self.paths.state.rglob('*') if p.is_file()}
        archive = BackupManager(self.paths).create(self.root / 'backup.zip')
        for paths in (AppPaths(self.root / 'fresh'), self.paths):
            BackupManager(paths).restore(archive)
            paths.ensure()
            self.assertEqual(json.loads((paths.root / 'workspace-format.json').read_text()), GUARDED)
            self.assertEqual({p.relative_to(paths.state): p.read_bytes() for p in paths.state.rglob('*') if p.is_file()}, original)

    def test_restore_actual_preupgrade_snapshot_removes_guard_only_after_commit(self):
        (self.paths.state / 'legacy').write_bytes(b'old state')
        archive = BackupManager(self.paths).create(self.root / 'old.zip')
        self.paths.require_replay_wal()
        (self.paths.state / 'new.sqlite3-wal').write_bytes(b'new frames')
        BackupManager(self.paths).restore(archive)
        self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), WORKSPACE_FORMAT)
        self.released_module().AppPaths(self.paths.root).ensure()
        self.assertFalse((self.paths.state / 'new.sqlite3-wal').exists())

    def test_moved_workspace_keeps_guard(self):
        self.paths.require_replay_wal()
        destination = self.root / 'moved'
        shutil.move(self.paths.root, destination)
        locator = WorkspaceLocator(self.root / 'bootstrap')
        locator.configure(destination)
        locator.load().ensure()
        old = self.released_module()
        with self.assertRaises(old.RuntimeSafetyError):
            old.AppPaths(destination).ensure()

    def test_malformed_and_symlink_marker_denied_without_rewrite(self):
        marker = self.paths.root / 'workspace-format.json'
        for value in ({**WORKSPACE_FORMAT, 'sqlite_replay': {'profile': 'wal_full'}},
                      {**GUARDED, 'extra': True}, {**GUARDED, 'schema_version': True},
                      {**GUARDED, 'sqlite_replay': {**REPLAY_REQUIREMENT, 'minimum_runtime': '0'}}):
            marker.write_text(json.dumps(value))
            before = marker.read_bytes()
            with self.assertRaises(RuntimeSafetyError):
                self.paths.ensure()
            self.assertEqual(before, marker.read_bytes())

    def test_recovery_does_not_remove_guard_from_token_retired_commit(self):
        self.paths.require_replay_wal()
        (self.paths.root / 'restore-transaction.json').write_text(json.dumps({
            'id': 'a'*32, 'phase': 'committed', 'prior_format': WORKSPACE_FORMAT,
            'restored_format': GUARDED}))
        BackupManager(self.paths).recover()
        self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), GUARDED)

    def test_unpatched_runtime_refuses_guarded_workspace(self):
        self.paths.require_replay_wal()
        self.runtime.stop()
        with patch('sqlite3.sqlite_version_info', (3, 49, 1)):
            with self.assertRaises(RuntimeSafetyError):
                self.paths.ensure()

    def test_restore_crash_matrix_selects_matching_data_and_guard(self):
        from quantlab.desktop_runtime import atomic_write
        for prior, restored in ((WORKSPACE_FORMAT, GUARDED), (GUARDED, WORKSPACE_FORMAT)):
            for committed in (False, True):
                with self.subTest(prior=prior, committed=committed):
                    paths = AppPaths(self.root / ('matrix-' + __import__('uuid').uuid4().hex)).ensure()
                    _write_workspace_format(paths.root, GUARDED)  # conservative promotion barrier
                    (paths.state / 'item').write_bytes(b'restored')
                    rollback = paths.root / 'state-v1.rollback'
                    rollback.mkdir()
                    (rollback / 'item').write_bytes(b'prior')
                    atomic_write(paths.state / '.restore-transaction', b'{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
                    atomic_write(paths.root / 'restore-transaction.json', json.dumps({
                        'id': 'a'*32, 'phase': 'committed' if committed else 'prepared',
                        'prior_format': prior, 'restored_format': restored}).encode())
                    BackupManager(paths).recover()
                    self.assertEqual((paths.state / 'item').read_bytes(), b'restored' if committed else b'prior')
                    self.assertEqual(json.loads((paths.root / 'workspace-format.json').read_text()), restored if committed else prior)

    def test_real_ui_adapter_guards_before_replay_constructor(self):
        # Compile the actual worker adapter without importing optional Qt widgets.
        import ast
        source = Path(__file__).resolve().parents[1] / 'desktop_ui.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_ui_operation')
        broker = types.SimpleNamespace(reconcile=lambda snapshot: None, _margin_schedule=())
        namespace = {'UI_OPERATIONS': {'ui_paper_replay'}, '_root': lambda paths: paths.state,
                     '_paper': lambda root: broker,
                     '_dataset': lambda root, payload: types.SimpleNamespace(manifest={'data_hash': 'data'}),
                     'load_selection': lambda path: {'strategy_hash': 'strategy', 'strategy': {}},
                     'content_hash': lambda value: 'binding', 'StrategySpec': lambda **value: value}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        class ReachedConstructor(Exception):
            pass
        def constructor(*args, **kwargs):
            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), GUARDED)
            raise ReachedConstructor()
        with patch('quantlab.paper_replay.PaperReplay', side_effect=constructor):
            with self.assertRaises(ReachedConstructor):
                namespace['execute_ui_operation']('ui_paper_replay', {'reconcile_confirmed': True, 'snapshot': {}}, self.paths)

    def test_symlink_marker_never_follows_target(self):
        marker = self.paths.root / 'workspace-format.json'
        target = self.root / 'external'
        target.write_text(json.dumps(WORKSPACE_FORMAT))
        marker.unlink()
        try:
            marker.symlink_to(target)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaises(RuntimeSafetyError):
            self.paths.require_replay_wal()
        self.assertEqual(json.loads(target.read_text()), WORKSPACE_FORMAT)

    def test_real_committed_wal_survives_fresh_restore_and_reopen(self):
        import sqlite3
        import subprocess
        import sys
        if sqlite3.sqlite_version_info < (3, 51, 3):
            self.skipTest('Real WAL restore requires the supported SQLite runtime')
        self.runtime.stop()
        self.paths.require_replay_wal()
        database = self.paths.state / 'replay.sqlite3'
        # Exit without closing to model a stopped writer with committed WAL.
        subprocess.run([sys.executable, '-c',
            "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA wal_autocheckpoint=0'); "
            "c.execute('CREATE TABLE proof(value TEXT)'); "
            "c.execute(\"INSERT INTO proof VALUES ('durable committed row')\"); c.commit(); os._exit(0)",
            str(database)], check=True)
        wal = Path(str(database) + '-wal')
        self.assertGreater(wal.stat().st_size, 32)
        raw_wal = wal.read_bytes()
        archive = BackupManager(self.paths).create(self.root / 'real-wal.zip')
        fresh = AppPaths(self.root / 'real-fresh')
        BackupManager(fresh).restore(archive)
        self.assertEqual((fresh.state / 'replay.sqlite3-wal').read_bytes(), raw_wal)
        fresh.ensure()
        connection = sqlite3.connect(fresh.state / 'replay.sqlite3')
        try:
            self.assertEqual(connection.execute('SELECT value FROM proof').fetchall(), [('durable committed row',)])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        finally:
            connection.close()
