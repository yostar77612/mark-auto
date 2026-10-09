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
    RuntimeSafetyError, SettingsStore,
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
        cases = [('a/../../escape', {}), ('C:/escape', {}), ('NUL.txt', {}),
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


@unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows DPAPI and Job Object integration')
class WindowsRuntimeTests(unittest.TestCase):
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
            finally:
                junction.rmdir()


if __name__ == '__main__':
    unittest.main()
