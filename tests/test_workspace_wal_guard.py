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

from quantlab.desktop_runtime import (
    AppPaths,
    BackupManager,
    RuntimeSafetyError,
    WorkspaceLocator,
    WORKSPACE_FORMAT,
    REPLAY_REQUIREMENT,
    _write_workspace_format,
)

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
        for name, data in [('replays/a.sqlite3', b'database'), ('replays/a.sqlite3-wal', b'committed frames'), ('replays/a.sqlite3-shm', b'shared memory')]:
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
        for value in (
            {**WORKSPACE_FORMAT, 'sqlite_replay': {'profile': 'wal_full'}},
            {**GUARDED, 'extra': True},
            {**GUARDED, 'schema_version': True},
            {**GUARDED, 'sqlite_replay': {**REPLAY_REQUIREMENT, 'minimum_runtime': '0'}},
        ):
            marker.write_text(json.dumps(value))
            before = marker.read_bytes()
            with self.assertRaises(RuntimeSafetyError):
                self.paths.ensure()
            self.assertEqual(before, marker.read_bytes())

    def test_recovery_does_not_remove_guard_from_token_retired_commit(self):
        self.paths.require_replay_wal()
        (self.paths.root / 'restore-transaction.json').write_text(
            json.dumps({'id': 'a' * 32, 'phase': 'committed', 'prior_format': WORKSPACE_FORMAT, 'restored_format': GUARDED})
        )
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
                    atomic_write(
                        paths.root / 'restore-transaction.json',
                        json.dumps(
                            {'id': 'a' * 32, 'phase': 'committed' if committed else 'prepared', 'prior_format': prior, 'restored_format': restored}
                        ).encode(),
                    )
                    BackupManager(paths).recover()
                    self.assertEqual((paths.state / 'item').read_bytes(), b'restored' if committed else b'prior')
                    self.assertEqual(json.loads((paths.root / 'workspace-format.json').read_text()), restored if committed else prior)

    def test_real_ui_adapter_guards_before_replay_constructor(self):
        # Compile the actual worker adapter without importing optional Qt widgets.
        import ast

        source = Path(__file__).resolve().parents[1] / 'desktop_ui.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        # Compile the entire replacement body, including every registered handler
        # and shared paper helper, so the constructor-order assertion stays real.
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and (
                node.name == 'execute_ui_operation'
                or node.name.startswith('_handle_ui_')
                or node.name in ('_prepare_paper_operation', '_finish_paper_operation')
            )
        ]
        registry = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == '_UI_OPERATION_HANDLERS' for target in node.targets)
        )
        broker = types.SimpleNamespace(reconcile=lambda snapshot: None, snapshot=lambda: {}, _margin_schedule=())
        namespace = {
            'UI_OPERATIONS': {'ui_paper_replay'},
            '_root': lambda paths: paths.state,
            '_paper': lambda root: broker,
            '_dataset': lambda root, payload: types.SimpleNamespace(manifest={'data_hash': 'data'}),
            'load_selection': lambda path: {'strategy_hash': 'strategy', 'strategy': {}},
            'content_hash': lambda value: 'binding',
            'StrategySpec': lambda **value: value,
        }
        exec(compile(ast.Module(body=[*functions, registry], type_ignores=[]), str(source), 'exec'), namespace)

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
        subprocess.run(
            [
                sys.executable,
                '-c',
                "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
                "c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA wal_autocheckpoint=0'); "
                "c.execute('CREATE TABLE proof(value TEXT)'); "
                "c.execute(\"INSERT INTO proof VALUES ('durable committed row')\"); c.commit(); os._exit(0)",
                str(database),
            ],
            check=True,
        )
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


class WalkForwardWorkspaceGuardTests(unittest.TestCase):
    setUp = WorkspaceWALGuardTests.setUp
    released_module = WorkspaceWALGuardTests.released_module

    def formats(self):
        from quantlab.desktop_runtime import WALK_FORWARD_REQUIREMENT

        wfo = {**WORKSPACE_FORMAT, 'sqlite_walk_forward': WALK_FORWARD_REQUIREMENT}
        return WORKSPACE_FORMAT, GUARDED, wfo, {**GUARDED, **wfo}

    def test_exact_composed_formats_and_both_setter_orders(self):
        from quantlab.desktop_runtime import _workspace_format

        base, replay, wfo, both = self.formats()
        for value in (base, replay, wfo, both):
            self.assertEqual(_workspace_format(value), value)
        for order in (('require_replay_wal', 'require_walk_forward_wal'), ('require_walk_forward_wal', 'require_replay_wal')):
            _write_workspace_format(self.paths.root, WORKSPACE_FORMAT)
            for method in order:
                getattr(self.paths, method)()
            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), both)
        for value in (
            {**wfo, 'extra': True},
            {**wfo, 'schema_version': True},
            {**wfo, 'sqlite_walk_forward': {'profile': 'wal_full'}},
            {**both, 'sqlite_replay': {**REPLAY_REQUIREMENT, 'minimum_runtime': '0'}},
        ):
            with self.assertRaises(RuntimeSafetyError):
                _workspace_format(value)

    def test_old_binary_rejects_wfo_and_both_workspaces_and_archives(self):
        old = self.released_module()
        for index, value in enumerate(self.formats()[2:]):
            _write_workspace_format(self.paths.root, value)
            with self.assertRaises(old.RuntimeSafetyError):
                old.AppPaths(self.paths.root).ensure()
            with self.assertRaises(old.RuntimeSafetyError):
                old.WorkspaceLocator(self.root / 'bootstrap')._validate(self.paths.root)
            archive = BackupManager(self.paths).create(self.root / f'guarded-{index}.zip')
            with zipfile.ZipFile(archive) as source:
                manifest = json.loads(source.read('manifest.json'))
            self.assertEqual(manifest['schema_version'], 2)
            self.assertEqual(manifest['workspace_format'], value)
            with self.assertRaises(old.RuntimeSafetyError):
                old.BackupManager(old.AppPaths(self.root / f'old-{index}').ensure()).restore(archive)

    def test_wfo_and_both_guards_reject_unpatched_runtime_before_state_changes(self):
        self.runtime.stop()
        for value in self.formats()[2:]:
            _write_workspace_format(self.paths.root, value)
            marker = self.paths.root / 'workspace-format.json'
            original = marker.read_bytes()
            with patch('sqlite3.sqlite_version_info', (3, 49, 1)):
                with self.assertRaises(RuntimeSafetyError):
                    self.paths.ensure()
            self.assertEqual(marker.read_bytes(), original)

    def test_unpatched_restore_refuses_wfo_and_both_before_promotion(self):
        for index, value in enumerate(self.formats()[2:]):
            _write_workspace_format(self.paths.root, value)
            archive = BackupManager(self.paths).create(self.root / f'runtime-{index}.zip')
            target = AppPaths(self.root / f'unsupported-{index}').ensure()
            (target.state / 'proof').write_bytes(b'unchanged')
            marker = target.root / 'workspace-format.json'
            before = marker.read_bytes()
            self.runtime.stop()
            try:
                with patch('sqlite3.sqlite_version_info', (3, 49, 1)):
                    with self.assertRaises(RuntimeSafetyError):
                        BackupManager(target).restore(archive)
            finally:
                self.runtime.start()
            self.assertEqual(marker.read_bytes(), before)
            self.assertEqual((target.state / 'proof').read_bytes(), b'unchanged')
            self.assertFalse((target.root / 'state-v1.rollback').exists())

    def test_real_wfo_and_both_committed_wal_restore_and_reopen(self):
        import sqlite3
        import subprocess
        import sys

        if sqlite3.sqlite_version_info < (3, 51, 3):
            self.skipTest('Real WAL restore requires the supported SQLite runtime')
        for index, value in enumerate(self.formats()[2:]):
            source = AppPaths(self.root / f'real-source-{index}').ensure()
            _write_workspace_format(source.root, value)
            database = source.state / 'walk_forward.sqlite3'
            subprocess.run(
                [
                    sys.executable,
                    '-c',
                    "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
                    "c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=FULL'); "
                    "c.execute('PRAGMA wal_autocheckpoint=0'); c.execute('CREATE TABLE proof(value TEXT)'); "
                    "c.execute(\"INSERT INTO proof VALUES ('committed WFO row')\"); c.commit(); os._exit(0)",
                    str(database),
                ],
                check=True,
                timeout=10,
            )
            raw_wal = Path(str(database) + '-wal').read_bytes()
            self.assertGreater(len(raw_wal), 32)
            archive = BackupManager(source).create(self.root / f'real-wfo-{index}.zip')
            target = AppPaths(self.root / f'real-restored-{index}')
            BackupManager(target).restore(archive)
            self.assertEqual((target.state / 'walk_forward.sqlite3-wal').read_bytes(), raw_wal)
            self.assertEqual(json.loads((target.root / 'workspace-format.json').read_text()), value)
            self.runtime.stop()
            try:
                target.ensure()
            finally:
                self.runtime.start()
            connection = sqlite3.connect(target.state / 'walk_forward.sqlite3')
            try:
                self.assertEqual(connection.execute('SELECT value FROM proof').fetchall(), [('committed WFO row',)])
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            finally:
                connection.close()

    def test_either_guard_restores_raw_sidecars_and_exact_format(self):
        for index, value in enumerate(self.formats()[1:]):
            _write_workspace_format(self.paths.root, value)
            folder = self.paths.state / 'walk_forward'
            folder.mkdir(exist_ok=True)
            for name, raw in (
                ('walk_forward.sqlite3', b'database'),
                ('walk_forward.sqlite3-wal', b'committed frames'),
                ('walk_forward.sqlite3-shm', b'shared memory'),
            ):
                (folder / name).write_bytes(raw)
            before = {p.relative_to(self.paths.state): p.read_bytes() for p in self.paths.state.rglob('*') if p.is_file()}
            archive = BackupManager(self.paths).create(self.root / f'raw-{index}.zip')
            target = AppPaths(self.root / f'fresh-{index}')
            BackupManager(target).restore(archive)
            self.assertEqual(json.loads((target.root / 'workspace-format.json').read_text()), value)
            self.assertEqual(before, {p.relative_to(target.state): p.read_bytes() for p in target.state.rglob('*') if p.is_file()})

    def test_restore_union_protects_both_prior_and_incoming_before_promotion(self):
        _, replay, wfo, both = self.formats()
        for index, (prior, incoming) in enumerate(((replay, wfo), (wfo, replay))):
            source = AppPaths(self.root / f'source-{index}').ensure()
            _write_workspace_format(source.root, incoming)
            (source.state / 'proof').write_bytes(b'incoming state')
            archive = BackupManager(source).create(self.root / f'union-{index}.zip')
            _write_workspace_format(self.paths.root, prior)
            (self.paths.state / 'proof').write_bytes(b'prior state')

            def before_promotion(*args, **kwargs):
                self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), both)
                self.assertEqual((self.paths.state / 'proof').read_bytes(), b'prior state')
                raise OSError('before promotion')

            with patch('quantlab.analysis_recovery.advance_restore_epoch', side_effect=before_promotion):
                with self.assertRaisesRegex(OSError, 'before promotion'):
                    BackupManager(self.paths).restore(archive)
            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), both)
            self.assertEqual((self.paths.state / 'proof').read_bytes(), b'prior state')

    def test_composed_restore_crash_matrix_selects_exact_matching_format(self):
        from quantlab.desktop_runtime import atomic_write

        for prior_index, prior in enumerate(self.formats()):
            for incoming_index, incoming in enumerate(self.formats()):
                for committed in (False, True):
                    with self.subTest(prior=prior_index, incoming=incoming_index, committed=committed):
                        paths = AppPaths(self.root / f'matrix-{prior_index}-{incoming_index}-{committed}').ensure()
                        _write_workspace_format(paths.root, {**prior, **incoming})
                        (paths.state / 'proof').write_bytes(b'incoming')
                        rollback = paths.root / 'state-v1.rollback'
                        rollback.mkdir()
                        (rollback / 'proof').write_bytes(b'prior')
                        atomic_write(paths.state / '.restore-transaction', b'{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
                        atomic_write(
                            paths.root / 'restore-transaction.json',
                            json.dumps(
                                {'id': 'a' * 32, 'phase': 'committed' if committed else 'prepared', 'prior_format': prior, 'restored_format': incoming}
                            ).encode(),
                        )
                        BackupManager(paths).recover()
                        self.assertEqual((paths.state / 'proof').read_bytes(), b'incoming' if committed else b'prior')
                        self.assertEqual(json.loads((paths.root / 'workspace-format.json').read_text()), incoming if committed else prior)

    def test_new_host_run_guards_before_owner_and_fsync_failure_prevents_claim(self):
        from quantlab.desktop_runtime import JobManager
        from tests.test_desktop_walk_forward_runtime import plan_payload

        manager = JobManager(self.paths)
        payload = {'plan': plan_payload(), 'preview_identity': 'a' * 64}

        def claimed(*args):
            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), self.formats()[2])
            raise RuntimeError('reached ownership')

        with patch.object(manager, '_claim_walk_forward', side_effect=claimed):
            with self.assertRaisesRegex(RuntimeError, 'reached ownership'):
                manager.start('ui_walk_forward_run', payload)
        _write_workspace_format(self.paths.root, WORKSPACE_FORMAT)
        with (
            patch('quantlab.desktop_runtime.os.fsync', side_effect=OSError('flush failed')),
            patch.object(manager, '_claim_walk_forward') as claim,
            patch('quantlab.desktop_runtime.mp.get_context') as spawn,
        ):
            with self.assertRaisesRegex(OSError, 'flush failed'):
                manager.start('ui_walk_forward_run', payload)
            claim.assert_not_called()
            spawn.assert_not_called()

    def test_existing_host_journal_is_rejected_without_marker_mutation(self):
        from quantlab.desktop_runtime import JobManager
        from tests.test_desktop_walk_forward_runtime import plan_payload

        folder = self.paths.state / 'walk_forward' / ('a' * 64)
        folder.mkdir(parents=True)
        (folder / 'walk_forward.sqlite3').write_bytes(b'original database')
        marker = self.paths.root / 'workspace-format.json'
        before = marker.read_bytes()
        with patch.object(AppPaths, 'require_walk_forward_wal') as require:
            with self.assertRaisesRegex(RuntimeSafetyError, 'read-only'):
                JobManager(self.paths).start('ui_walk_forward_run', {'plan': plan_payload(), 'preview_identity': 'a' * 64})
            require.assert_not_called()
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual((folder / 'walk_forward.sqlite3').read_bytes(), b'original database')

    def test_direct_adapter_guards_only_new_journal_before_core_call(self):
        import sys
        import desktop_walk_forward as adapter
        from tests.test_desktop_walk_forward_runtime import plan_payload

        identity = 'b' * 64
        preview = {'preview_identity': identity, 'plan': plan_payload()}
        fake_ui = types.ModuleType('desktop_presentation')
        fake_ui._dataset = lambda *args: object()
        fake_ui.research_controls = lambda paths: paths.controls

        def run(*args, **kwargs):
            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), self.formats()[2])
            raise RuntimeError('reached core')

        with (
            patch.dict(sys.modules, {'desktop_presentation': fake_ui}),
            patch.object(adapter, 'preview_walk_forward', return_value=preview),
            patch.object(adapter, 'run_walk_forward', side_effect=run),
        ):
            with self.assertRaisesRegex(RuntimeError, 'reached core'):
                adapter.execute_walk_forward('ui_walk_forward_run', {'plan': preview['plan'], 'preview_identity': identity}, self.paths)
            folder = self.paths.state / 'walk_forward' / identity
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'walk_forward.sqlite3').write_bytes(b'old data')
            _write_workspace_format(self.paths.root, WORKSPACE_FORMAT)
            before = (self.paths.root / 'workspace-format.json').read_bytes()
            with (
                patch.object(AppPaths, 'require_walk_forward_wal') as require,
                patch.object(adapter, 'read_walk_forward_state', return_value={'old': True}),
                patch.object(adapter, 'compact_walk_forward', return_value={'old': True}),
            ):
                self.assertEqual(
                    adapter.execute_walk_forward('ui_walk_forward_run', {'plan': preview['plan'], 'preview_identity': identity}, self.paths), {'old': True}
                )
                require.assert_not_called()
            self.assertEqual((self.paths.root / 'workspace-format.json').read_bytes(), before)
