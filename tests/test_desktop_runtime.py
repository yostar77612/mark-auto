import hashlib
import json
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from quantlab.desktop_runtime import (
    AppPaths, BackupManager, CredentialVault, JobManager, RuntimeGuard,
    RuntimeSafetyError, SettingsStore, WorkspaceLocator, RedactedEventLog,
)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'app').ensure()
        self.backups = BackupManager(self.paths)

    def test_settings_atomic_version_and_corruption(self):
        store = SettingsStore(self.paths.state / 'settings.json')
        self.assertEqual(store.load(), {})
        store.save({'language': 'zh-TW'})
        self.assertEqual(store.load(), {'language': 'zh-TW'})
        for value in ('{"schema_version":99,"settings":{}}', 'bad json'):
            store.path.write_text(value)
            with self.assertRaises(RuntimeSafetyError):
                store.save({})
            self.assertEqual(store.path.read_text(), value)

    def test_nonwindows_vault_fails_closed(self):
        with patch('quantlab.desktop_runtime.sys.platform', 'linux'):
            with self.assertRaises(RuntimeSafetyError):
                CredentialVault(self.paths).save('provider', 'test-only-not-a-real-key')
        self.assertEqual(list(self.paths.credentials.iterdir()), [])

    def test_backup_roundtrip_and_secret_exclusion(self):
        (self.paths.state / 'a.json').write_text('{"value":1}')
        (self.paths.credentials / 'secret.dpapi').write_bytes(b'encrypted-only')
        archive = Path(self.temp.name) / 'backup.zip'
        self.backups.create(archive)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {'manifest.json', 'state/a.json'})
        (self.paths.state / 'a.json').write_text('changed')
        self.backups.restore(archive)
        self.assertEqual((self.paths.state / 'a.json').read_text(), '{"value":1}')
        self.assertTrue((self.paths.credentials / 'secret.dpapi').exists())

    def _archive(self, name, raw=b'new', *, mode=None, version=1, digest=None):
        path = Path(self.temp.name) / 'bad.zip'
        with zipfile.ZipFile(path, 'w') as z:
            info = zipfile.ZipInfo('state/' + name)
            if mode:
                info.external_attr = mode << 16
            z.writestr(info, raw)
            z.writestr('manifest.json', json.dumps({'schema_version': version, 'files': {name: {'size': len(raw), 'sha256': digest or hashlib.sha256(raw).hexdigest()}}}))
        return path

    def test_restore_rejects_traversal_symlink_future_and_corruption(self):
        original = self.paths.state / 'keep'
        original.write_text('original')
        cases = [('a/../../escape', {}), ('C:/escape', {}), ('NUL.txt', {}), ('.restore-transaction', {}),
                 ('a', {'mode': stat.S_IFLNK | 0o777}), ('a', {'version': 99}),
                 ('a', {'digest': '0' * 64})]
        for name, options in cases:
            with self.subTest(name=name, options=options):
                with self.assertRaises(RuntimeSafetyError):
                    self.backups.restore(self._archive(name, **options))
                self.assertEqual(original.read_text(), 'original')

    def test_restore_recovers_interrupted_directory_switch(self):
        (self.paths.state / 'original').write_text('safe')
        self.paths.state.rename(self.paths.root / 'state-v1.rollback')
        self.backups.recover()
        self.assertEqual((self.paths.state / 'original').read_text(), 'safe')

    def test_ambiguous_recreated_state_never_deletes_rollback(self):
        (self.paths.state / 'original').write_text('must survive')
        self.paths.state.rename(self.paths.root / 'state-v1.rollback')
        # Regression: a clock/freeze callback wrote a notice in the rename gap.
        self.paths.state.mkdir()
        (self.paths.state / 'desktop_safety.json').write_text('{"frozen":true}')
        self.backups.recover()
        self.assertEqual((self.paths.state / 'original').read_text(), 'must survive')
        preserved = list(self.paths.root.glob('state-v1.interrupted-*'))
        self.assertEqual(len(preserved), 1)
        self.assertTrue((preserved[0] / 'desktop_safety.json').exists())
        self.backups.recover()  # Recovery remains idempotent.
        self.assertEqual((self.paths.state / 'original').read_text(), 'must survive')

    def test_restore_commit_requires_matching_promoted_identity(self):
        for matching in (False, True):
            with self.subTest(matching=matching):
                root = self.paths.root / ('matching' if matching else 'mismatch')
                paths = AppPaths(root).ensure()
                (paths.state / 'original').write_text('preserve until commit')
                paths.state.rename(root / 'state-v1.rollback')
                paths.state.mkdir()
                (paths.state / 'replacement').write_text('verified replacement')
                (paths.state / '.restore-transaction').write_text(json.dumps({'id': 'a' * 32 if matching else 'b' * 32}))
                (root / 'restore-transaction.json').write_text(json.dumps({'id': 'a' * 32, 'phase': 'committed'}))
                BackupManager(paths).recover()
                expected = 'replacement' if matching else 'original'
                self.assertTrue((paths.state / expected).exists())
                self.assertEqual(len(list(root.glob('state-v1.interrupted-*'))), 0 if matching else 1)

    def test_cancelled_restore_release_recovers_before_freeze_write(self):
        manager = JobManager(self.paths)
        (self.paths.state / 'original').write_text('safe')
        self.paths.state.rename(self.paths.root / 'state-v1.rollback')
        (self.paths.root / 'restore-transaction.json').write_text(json.dumps({'id': 'a' * 32, 'phase': 'prepared'}))
        manager._operation = 'ui_backup_restore'
        manager._release()  # Production cleanup after child termination/join.
        self.assertTrue((self.paths.state / 'original').exists())
        (self.paths.state / 'desktop_safety.json').write_text('{"frozen":true}')
        self.backups.recover()
        self.assertEqual((self.paths.state / 'original').read_text(), 'safe')

    def test_legacy_orphan_restore_token_does_not_poison_backup(self):
        (self.paths.state / 'original').write_text('keep data')
        (self.paths.state / '.restore-transaction').write_text(json.dumps({'id': 'a' * 32}))
        archive = Path(self.temp.name) / 'orphan-safe.zip'
        self.backups.create(archive)
        with zipfile.ZipFile(archive) as z:
            self.assertNotIn('state/.restore-transaction', z.namelist())
        self.backups.restore(archive)
        self.assertEqual((self.paths.state / 'original').read_text(), 'keep data')
        self.assertFalse((self.paths.state / '.restore-transaction').exists())

    def test_crash_retiring_restore_controls_keeps_usable_state(self):
        (self.paths.state / 'original').write_text('verified replacement')
        token = self.paths.state / '.restore-transaction'
        token.write_text(json.dumps({'id': 'a' * 32}))
        journal = self.paths.root / 'restore-transaction.json'
        journal.write_text(json.dumps({'id': 'a' * 32, 'phase': 'committed'}))
        real_unlink = Path.unlink
        def fail_journal(path, *args, **kwargs):
            if path == journal:
                raise OSError('simulated interruption retiring journal')
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_journal):
            with self.assertRaises(OSError):
                self.backups.recover()
        self.assertFalse(token.exists())
        self.assertTrue(journal.exists())
        self.backups.recover()
        archive = Path(self.temp.name) / 'after-control-crash.zip'
        self.backups.create(archive)
        self.backups.restore(archive)
        self.assertEqual((self.paths.state / 'original').read_text(), 'verified replacement')

    def test_restore_rolls_back_failed_promotion(self):
        (self.paths.state / 'keep').write_text('safe')
        archive = self._archive('new')
        import os
        real_replace = os.replace
        def fail_promotion(source, dest):
            if Path(source).name.startswith('.restore-'):
                raise OSError('injected failure')
            return real_replace(source, dest)
        with patch('quantlab.desktop_runtime.os.replace', side_effect=fail_promotion):
            with self.assertRaises(OSError):
                self.backups.restore(archive)
        self.assertEqual((self.paths.state / 'keep').read_text(), 'safe')

    def test_backup_refuses_active_jobs_and_recursive_destination(self):
        class Busy:
            active = True
        with self.assertRaises(RuntimeSafetyError):
            BackupManager(self.paths, Busy()).create(Path(self.temp.name) / 'a.zip')
        with self.assertRaises(RuntimeSafetyError):
            self.backups.create(self.paths.state / 'a.zip')

    def test_guard_crash_and_clock_discontinuity(self):
        guard = RuntimeGuard(self.paths)
        self.assertFalse(guard.start())
        self.assertTrue(RuntimeGuard(self.paths).start())
        guard.reconciliation_required = False
        guard.wall -= 100
        self.assertTrue(guard.check_clock())
        self.assertTrue(guard.reconciliation_required)
        guard.finish()
        self.assertFalse(guard.marker.exists())

    def test_job_whitelist_and_cancel(self):
        manager = JobManager(self.paths)
        self.addCleanup(manager.close)
        with self.assertRaises(RuntimeSafetyError):
            manager.start('eval', {'code': 'anything'})
        with self.assertRaises(RuntimeSafetyError):
            manager.start('demo', {'bars': 100000000})
        manager.start('demo', {'bars': 10000})
        with self.assertRaises(RuntimeSafetyError):
            manager.start('demo', {'bars': 30})
        manager.cancel()
        self.assertFalse(manager.active)
        self.assertEqual(manager.poll()[0]['type'], 'cancelled')

    def test_terminal_result_waits_for_child_exit(self):
        manager = JobManager(self.paths)
        manager.job_id = 'fixture-job'
        manager._operation = 'demo'
        class Process:
            alive = True
            def is_alive(self): return self.alive
            def join(self): pass
            def close(self): pass
        class Receiver:
            pending = True
            def poll(self): return self.pending
            def recv_bytes(self, limit):
                self.pending = False
                return b'{"job_id":"fixture-job","type":"result","result":{}}'
            def close(self): pass
        process = Process()
        manager.process, manager.receiver = process, Receiver()
        self.assertEqual(manager.poll(), [])
        self.assertTrue(manager.active)
        process.alive = False
        self.assertEqual(manager.poll()[0]['type'], 'result')
        self.assertFalse(manager.active)

    def test_terminal_error_is_not_relabelled_cancelled_during_cleanup(self):
        manager = JobManager(self.paths)
        manager.job_id = 'fixture-error'
        manager._operation = 'ui_import'
        class Process:
            pid = None
            def is_alive(self): return True
            def close(self): pass
        class Receiver:
            pending = True
            def poll(self): return self.pending
            def recv_bytes(self, limit):
                self.pending = False
                return b'{"job_id":"fixture-error","type":"error","message":"validation failed"}'
            def close(self): pass
        manager.process, manager.receiver = Process(), Receiver()
        self.assertEqual(manager.poll(), [])
        self.assertTrue(manager.active)
        manager.cancel()
        events = manager.poll()
        self.assertEqual([event['type'] for event in events], ['error'])
        self.assertEqual(events[0]['message'], 'validation failed')
        self.assertFalse(manager.active)

    def test_windows_closed_pipe_after_terminal_preserves_result(self):
        manager = JobManager(self.paths)
        manager.job_id, manager._operation = 'windows-pipe', 'demo'
        class Process:
            def is_alive(self): return False
            def join(self): pass
            def close(self): pass
        class Receiver:
            frames = [b'{"job_id":"windows-pipe","type":"progress"}',
                      b'{"job_id":"windows-pipe","type":"result","result":{"output":"fixture"}}']
            polls = 0
            def poll(self):
                self.polls += 1
                if not self.frames:
                    error = OSError('The pipe has been ended')
                    error.winerror = 109
                    raise error
                return True
            def recv_bytes(self, limit): return self.frames.pop(0)
            def close(self): pass
        receiver = Receiver()
        manager.process, manager.receiver = Process(), receiver
        events = manager.poll()
        self.assertEqual([e['type'] for e in events], ['progress', 'result'])
        self.assertEqual(receiver.polls, 2)
        self.assertFalse(manager.active)
        self.assertEqual(manager.poll(), [])

    def test_windows_pipe_eof_without_terminal_is_crash_not_malformed(self):
        manager = JobManager(self.paths)
        manager.job_id, manager._operation = 'windows-eof', 'demo'
        class Process:
            alive = True
            def is_alive(self): return self.alive
            def join(self): pass
            def close(self): pass
        class Receiver:
            polls = 0
            def poll(self):
                self.polls += 1
                error = OSError('The pipe has been ended')
                error.winerror = 109
                raise error
            def close(self): pass
        process, receiver = Process(), Receiver()
        manager.process, manager.receiver = process, receiver
        self.assertEqual(manager.poll(), [])
        self.assertTrue(manager.active)
        process.alive = False
        events = manager.poll()
        self.assertEqual(receiver.polls, 1)
        self.assertEqual([e['type'] for e in events], ['error'])
        self.assertIn('Worker stopped unexpectedly', events[0]['message'])
        self.assertFalse(manager.active)

    def test_non_eof_windows_pipe_error_still_rejected(self):
        manager = JobManager(self.paths)
        manager.job_id, manager._operation = 'invalid-pipe', 'demo'
        class Process:
            pid = None
            def close(self): pass
        class Receiver:
            def poll(self):
                error = OSError('invalid handle')
                error.winerror = 6
                raise error
            def close(self): pass
        manager.process, manager.receiver = Process(), Receiver()
        events = manager.poll()
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(events[-1]['message'], 'Worker response rejected')
        self.assertFalse(manager.active)

    def test_spawn_job_completes_and_can_restart(self):
        manager = JobManager(self.paths)
        self.addCleanup(manager.close)
        manager.start('demo', {'bars': 30})
        events = []
        deadline = time.monotonic() + 30
        while manager.active and time.monotonic() < deadline:
            events.extend(manager.poll())
            time.sleep(.02)
        self.assertFalse(manager.active)
        results = [e for e in events if e['type'] == 'result']
        self.assertEqual(len(results), 1, events)
        self.assertTrue((Path(results[0]['result']['output']) / 'dataset.json').exists())
        manager.start('backtest', {'dataset': '/does/not/exist'})
        deadline = time.monotonic() + 10
        events = []
        while manager.active and time.monotonic() < deadline:
            events.extend(manager.poll())
            time.sleep(.02)
        self.assertTrue(any(e['type'] == 'error' for e in events), events)


class EventLogTests(unittest.TestCase):
    def test_only_fixed_codes_saved_and_rotation_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            log = RedactedEventLog(Path(temp) / 'events.jsonl')
            log.MAX_BYTES = 256
            for _ in range(20):
                log.append('ui_demo', 'result')
            self.assertTrue(log.path.with_suffix('.jsonl.1').exists())
            self.assertLess(log.path.stat().st_size, 512)
            self.assertTrue(log.tail())
            self.assertTrue(all(json.loads(line)['operation'] == 'ui_demo' for line in log.tail()))
            for operation, event in (('secret-key-value', 'result'), ('ui_demo', 'secret-error-message')):
                with self.assertRaises(RuntimeSafetyError):
                    log.append(operation, event)
            self.assertNotIn('secret', log.path.read_text())
            with log.path.open('a') as stream:
                stream.write('{"time":1,"operation":"ui_demo","event":"result","payload":"private"}\n')
            self.assertNotIn('private', '\n'.join(log.tail()))
            with self.assertRaises(RuntimeSafetyError):
                log.tail(100000)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bootstrap = self.base / 'bootstrap'
        self.current = AppPaths(self.bootstrap).ensure()
        self.locator = WorkspaceLocator(self.bootstrap)

    def test_pointer_changes_only_next_launch_and_keeps_credentials_lock(self):
        (self.current.state / 'source.txt').write_text('original data')
        (self.current.credentials / 'key.dpapi').write_bytes(b'protected')
        active = self.locator.load()
        lock = self.locator.lock_path
        destination = self.base / 'new-workspace'
        self.locator.configure(destination)
        self.assertEqual(active.root, self.bootstrap)
        self.assertEqual(list(destination.iterdir()), [])
        restarted = self.locator.load().ensure()
        self.assertEqual(restarted.root.resolve(), destination.resolve())
        self.assertEqual(restarted.credentials, self.current.credentials)
        self.assertEqual(self.locator.lock_path, lock)
        self.assertFalse((destination / 'credentials').exists())
        self.assertEqual((self.current.state / 'source.txt').read_text(), 'original data')
        self.assertEqual((self.current.credentials / 'key.dpapi').read_bytes(), b'protected')
        archive = self.base / 'state.zip'
        BackupManager(restarted).create(archive)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.namelist(), ['manifest.json'])
        self.assertTrue(self.locator.pointer.exists())

    def test_fixed_audit_controls_survive_workspace_backup_restore(self):
        (self.current.controls / 'budget-and-holdout-sentinel').write_text('reserved and examined')
        destination = self.base / 'research-workspace'
        self.locator.configure(destination)
        restarted = self.locator.load().ensure()
        self.assertEqual(restarted.controls, self.current.controls)
        self.assertFalse((destination / 'control-v1').exists())
        archive = self.base / 'research-only.zip'
        BackupManager(restarted).create(archive)
        with zipfile.ZipFile(archive) as z:
            self.assertFalse(any('control-v1' in name for name in z.namelist()))
        (self.current.controls / 'budget-and-holdout-sentinel').write_text('newer irreversible reservation')
        BackupManager(restarted).restore(archive)
        self.assertEqual((restarted.controls / 'budget-and-holdout-sentinel').read_text(), 'newer irreversible reservation')
        with self.assertRaises(RuntimeSafetyError):
            self.locator.configure(self.current.controls / 'nested-workspace')

    def test_existing_compatible_workspace_preserved(self):
        target = AppPaths(self.base / 'existing').ensure()
        (target.state / 'sentinel').write_text('keep')
        self.locator.configure(target.root)
        self.assertEqual(self.locator.load().root.resolve(), target.root.resolve())
        self.assertEqual((target.state / 'sentinel').read_text(), 'keep')

    def test_pointer_atomic_failure_leaves_old_selection(self):
        first = self.base / 'first'
        self.locator.configure(first)
        original = self.locator.pointer.read_bytes()
        with patch('quantlab.desktop_runtime.os.replace', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                self.locator.configure(self.base / 'second')
        self.assertEqual(self.locator.pointer.read_bytes(), original)
        self.assertEqual(self.locator.load().root.resolve(), first.resolve())

    def test_invalid_and_unrelated_folders_are_never_overwritten(self):
        unrelated = self.base / 'unrelated'
        unrelated.mkdir()
        sentinel = unrelated / 'important'
        sentinel.write_text('keep')
        for value in ('relative/path', '//server/share/path', '\\\\server\\share', Path('/'), unrelated,
                      self.bootstrap / 'credentials' / 'nested', self.bootstrap / 'state-v1' / 'nested'):
            with self.subTest(path=str(value)), self.assertRaises(RuntimeSafetyError):
                self.locator.configure(value)
        self.assertFalse(self.locator.pointer.exists())
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_reparse_and_system_locations_rejected(self):
        system = self.base / 'simulated-system'
        with patch.object(WorkspaceLocator, '_protected_windows_locations', return_value=[system]):
            with self.assertRaises(RuntimeSafetyError):
                self.locator.configure(system / 'data')
        destination = self.base / 'real'
        destination.mkdir()
        link = self.base / 'link'
        try:
            link.symlink_to(destination, target_is_directory=True)
        except OSError:
            return  # Windows symlink privilege may be disabled; junction test below covers it.
        with self.assertRaises(RuntimeSafetyError):
            self.locator.configure(link / 'data')

    def test_future_pointer_and_state_fail_closed(self):
        self.locator.pointer.write_text('{"schema_version":99,"root":"future"}')
        original = self.locator.pointer.read_bytes()
        with self.assertRaises(RuntimeSafetyError):
            self.locator.load()
        self.assertEqual(self.locator.pointer.read_bytes(), original)
        with self.assertRaises(RuntimeSafetyError):
            self.locator.configure(self.base / 'empty-new-folder')
        self.assertFalse((self.base / 'empty-new-folder').exists())
        future = AppPaths(self.base / 'future').ensure()
        (future.root / 'workspace-format.json').write_text('{"kind":"markauto_workspace","schema_version":99}')
        with self.assertRaises(RuntimeSafetyError):
            self.locator.configure(future.root)
        self.assertEqual(self.locator.pointer.read_bytes(), original)

    def test_destination_changed_before_restart_is_rejected(self):
        target = self.base / 'selected'
        self.locator.configure(target)
        (target / 'unrelated-new-file').write_text('preserve')
        with self.assertRaises(RuntimeSafetyError):
            self.locator.load()
        self.assertEqual((target / 'unrelated-new-file').read_text(), 'preserve')


@unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows DPAPI and Job Object integration')
class WindowsRuntimeTests(unittest.TestCase):
    def test_installer_mutex_lifetime(self):
        import ctypes
        from ctypes import wintypes
        from quantlab.desktop_runtime import WindowsAppMutex, WINDOWS_APP_MUTEX
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        guard = WindowsAppMutex()
        try:
            handle = kernel.OpenMutexW(0x00100000, False, WINDOWS_APP_MUTEX)
            self.assertTrue(handle)
            if handle: kernel.CloseHandle(handle)
        finally:
            guard.close()
        self.assertFalse(kernel.OpenMutexW(0x00100000, False, WINDOWS_APP_MUTEX))

    def test_dpapi_roundtrip_and_corrupt_blob(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths(Path(temp)).ensure()
            vault = CredentialVault(paths)
            dummy = 'test-only-credential-never-a-real-secret'
            vault.save('test', dummy)
            self.assertEqual(vault.load('test'), dummy)
            blob = paths.credentials / 'test.dpapi'
            self.assertNotIn(dummy.encode(), blob.read_bytes())
            blob.write_bytes(b'invalid-dpapi-blob')
            with self.assertRaises(RuntimeSafetyError):
                vault.load('test')
            vault.delete('test')
            self.assertIsNone(vault.load('test'))

    def _tree_test(self, crash_parent):
        import ctypes
        import subprocess
        import sys
        from ctypes import wintypes
        # The supervisor owns the Job Object. The worker spawns its grandchild
        # only after the supervisor assigns it, matching the production gate.
        worker = "import subprocess,sys,time; sys.stdin.readline(); p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)']); print(p.pid,flush=True); time.sleep(90)"
        supervisor = "\n".join([
            'import subprocess,sys,time',
            'from quantlab.desktop_runtime import _WindowsProcessTree',
            f'p=subprocess.Popen([sys.executable,"-c",{worker!r}],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)',
            'tree=_WindowsProcessTree(p.pid)',
            'p.stdin.write("start\\n"); p.stdin.flush()',
            'print(str(p.pid)+" "+p.stdout.readline().strip(),flush=True)',
            'sys.stdin.readline()',
            'tree.close()',
            'p.wait(timeout=10)',
        ])
        parent = subprocess.Popen([sys.executable, '-c', supervisor], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: parent.kill() if parent.poll() is None else None)
        # A timeout thread prevents a broken test from waiting forever on stdout.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(parent.stdout.readline)
            try:
                line = future.result(timeout=20)
            except concurrent.futures.TimeoutError:
                parent.kill()
                self.fail('Job Object fixture failed to start')
        pids = [int(v) for v in line.split()]
        self.assertEqual(len(pids), 2, line)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handles = [kernel.OpenProcess(0x00100000, False, pid) for pid in pids]
        try:
            self.assertTrue(all(handles))
            if crash_parent:
                parent.kill()
            else:
                parent.stdin.write('cancel\n'); parent.stdin.flush()
            parent.wait(timeout=10)
            for handle in handles:
                self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0, 'Descendant survived Job Object close')
        finally:
            for handle in handles:
                if handle: kernel.CloseHandle(handle)
            parent.stdin.close(); parent.stdout.close()

    def test_job_object_cancel_kills_descendants(self):
        self._tree_test(False)

    def test_parent_crash_kills_descendants(self):
        self._tree_test(True)

    def test_backup_rejects_windows_junction(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths(Path(temp) / 'app').ensure()
            (paths.credentials / 'must-not-back-up').write_text('dummy')
            junction = paths.state / 'junction'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(paths.credentials)], check=True, capture_output=True)
            try:
                with self.assertRaises(RuntimeSafetyError):
                    BackupManager(paths).create(Path(temp) / 'backup.zip')
                with self.assertRaises(RuntimeSafetyError):
                    WorkspaceLocator(paths.root).configure(junction / 'data')
            finally:
                junction.rmdir()


if __name__ == '__main__':
    unittest.main()
