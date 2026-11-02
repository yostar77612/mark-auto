"""Installer handoff with native fake executables; no real installer or profile."""

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from quantlab import update_install as install
from quantlab.runtime_support import WindowsAppMutex
from quantlab.trading.domain.validation import DomainError
import trading_runtime


class InstallHandoffTests(unittest.TestCase):
    def tearDown(self):
        install._pending = None

    def test_only_supported_frozen_per_user_install_is_accepted(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': 'C:/isolated-user'}), patch.object(install.sys, 'platform', 'win32'):
            with patch.object(install.sys, 'frozen', True, create=True):
                with patch.object(install.sys, 'executable', 'C:/isolated-user/Programs/MarkAuto/payloads/1.0/new/MarkAuto.exe'):
                    self.assertTrue(install.can_install())
                for path in ('C:/other/MarkAuto.exe', 'C:/isolated-user/Programs/MarkAuto/payloads/1.0/new/python.exe'):
                    with patch.object(install.sys, 'executable', path):
                        self.assertFalse(install.can_install())
            with patch.object(install.sys, 'frozen', False, create=True):
                self.assertFalse(install.can_install())
        with self.assertRaisesRegex(ValueError, 'update_not_installed'):
            install.queue_install(Path('unused'), 'a' * 64, {})
        self.assertFalse(install.pending_install())

    def test_cancel_discards_only_the_download_and_no_installer_is_launched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            download = root / 'download'
            download.mkdir()
            executable = download / 'setup.exe'
            executable.write_bytes(b'complete-download')
            sentinel = root / 'workspace'
            sentinel.write_bytes(b'preserved')
            install._pending = install.InstallRequest(executable, 'a' * 64, root, {})
            launch = Mock()
            install.cancel_pending_install()
            install.launch_pending_install(launch)
            launch.assert_not_called()
            self.assertFalse(download.exists())
            self.assertEqual(sentinel.read_bytes(), b'preserved')

    def test_helper_launch_failure_keeps_request_available_for_explicit_cleanup(self):
        request = install.InstallRequest(Path('download/setup.exe'), 'a' * 64, Path('install'), {})
        install._pending = request
        launch = Mock(side_effect=OSError)
        with patch.object(install, '_helper_command', return_value=['powershell']):
            with self.assertRaises(OSError):
                install.launch_pending_install(launch)
        launch.assert_called_once_with(['powershell'])
        self.assertIs(install._pending, request)

    def test_helper_payload_is_encoded_data_and_does_not_change_execution_policy(self):
        with patch.dict(os.environ, {'SystemRoot': 'C:/Windows'}):
            request = install.InstallRequest(Path('C:/a space/quote\'$/setup.exe'), 'a' * 64, Path('C:/installed'), {'update_hash_mismatch': '雜湊不符'})
            command = install._helper_command(request, parent_pid=17)
        self.assertNotIn('-ExecutionPolicy', command)
        script = base64.b64decode(command[-1]).decode('utf-16-le')
        self.assertNotIn(str(request.installer), script)
        self.assertIn('WaitForExit', script)

    def test_runtime_launches_helper_only_after_owned_exit_and_guard_release(self):
        events = []
        guard = Mock()
        guard.close.side_effect = lambda: events.append('guard-released')
        with (
            patch.object(trading_runtime, 'WindowsAppMutex', return_value=guard),
            patch.object(trading_runtime, '_run_window', return_value=0),
            patch.object(trading_runtime, '_close_window_engines', side_effect=lambda previous: events.append('children-exited')),
            patch.object(install, 'launch_pending_install', side_effect=lambda launch: (events.append('helper-launched'), launch(['powershell']))),
            patch.object(trading_runtime.subprocess, 'Popen') as started,
        ):
            self.assertEqual(trading_runtime.run_window(), 0)
        self.assertEqual(events, ['children-exited', 'guard-released', 'helper-launched'])
        started.assert_called_once_with(
            ['powershell'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )

    def test_runtime_owned_shutdown_timeout_aborts_update_without_launch(self):
        install._pending = install.InstallRequest(Path('unused'), 'a' * 64, Path('install'), {})
        with (
            patch.object(trading_runtime, 'WindowsAppMutex'),
            patch.object(trading_runtime, '_run_window', return_value=0),
            patch.object(trading_runtime, '_close_window_engines', side_effect=DomainError('outcome_unknown')),
            patch.object(trading_runtime, '_abort_update') as abort,
            patch.object(install, 'launch_pending_install') as launch,
        ):
            self.assertEqual(trading_runtime.run_window(), 1)
        launch.assert_not_called()
        abort.assert_called_once_with('update_shutdown_failed')

    def test_runtime_abnormal_window_exit_discards_update_without_launch(self):
        with (
            patch.object(trading_runtime, 'WindowsAppMutex'),
            patch.object(trading_runtime, '_run_window', return_value=1),
            patch.object(trading_runtime, '_close_window_engines'),
            patch.object(install, 'cancel_pending_install') as cancel,
            patch.object(install, 'launch_pending_install') as launch,
        ):
            self.assertEqual(trading_runtime.run_window(), 1)
        cancel.assert_called_once_with()
        launch.assert_not_called()

    def test_release_pointer_has_exact_installer_digest_and_immutable_url(self):
        from datetime import datetime
        from quantlab.update_check import check_for_update

        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/windows-desktop.yml').read_text()
        generator = workflow.split('python - <<\'PY\'\n', 1)[1].split('\n          PY', 1)[0]
        source = '\n'.join(line[10:] for line in generator.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'release/installers/MarkAuto-2.0-windows-x64-setup.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'actual-installer-artifact')
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {'VERSION': '2.0', 'SOURCE_SHA': 'a' * 40, 'TAG': 'desktop-preview-123-1', 'PUBLISHED_AT': '2026-11-02T01:00:00Z'}):
                    exec(compile(source, 'release-manifest-generator', 'exec'), {})
            finally:
                os.chdir(previous)
            body = (root / 'release-manifest.json').read_bytes()
            manifest = json.loads(body)
        self.assertEqual(manifest['installer']['sha256'], sha256(b'actual-installer-artifact').hexdigest())
        self.assertEqual(
            manifest['installer']['url'], 'https://github.com/yostar77612/mark-auto/releases/download/desktop-preview-123-1/MarkAuto-2.0-windows-x64-setup.exe'
        )
        self.assertFalse(manifest['signature_verified'])
        datetime.fromisoformat(manifest['published_at'])
        result = check_for_update('1.0', transport=lambda url: (body, sha256(body).hexdigest()))
        self.assertEqual(result.status, 'update_available')


class NativeInstallerHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'nt':
            return
        cls.temp = tempfile.TemporaryDirectory(prefix='markauto-update-fixture-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.fixture = Path(cls.temp.name) / 'fixture.exe'
        source = Path(cls.temp.name) / 'fixture.cs'
        source.write_text(
            r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
class Fixture {
    static int Main(string[] args) {
        string own = Assembly.GetExecutingAssembly().Location;
        File.WriteAllText(own + ".pid", Process.GetCurrentProcess().Id.ToString());
        File.WriteAllLines(own + ".called", args);
        string folder = Path.GetDirectoryName(own);
        string delay = Path.Combine(folder, "delay.txt");
        if (File.Exists(delay)) Thread.Sleep(Int32.Parse(File.ReadAllText(delay)));
        foreach (string arg in args) {
            if (arg.StartsWith("/LOG=")) {
                string payload = File.ReadAllText(Path.Combine(folder, "payload.txt"));
                File.WriteAllText(arg.Substring(5), "MARKAUTO_PAYLOAD_VERIFIED=" + payload + "\r\n");
            }
        }
        string exit = Path.Combine(folder, "exit.txt");
        return File.Exists(exit) ? Int32.Parse(File.ReadAllText(exit)) : 0;
    }
}
''',
            encoding='utf-8',
        )
        compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        built = subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(cls.fixture), str(source)], capture_output=True, timeout=20)
        if built.returncode:
            raise AssertionError(built.stdout.decode(errors='replace') + built.stderr.decode(errors='replace'))

    def tree(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='markauto-update-case-')))
        self.download = self.folder / 'download with spaces'
        self.download.mkdir()
        self.installer = self.download / 'setup.exe'
        shutil.copyfile(self.fixture, self.installer)
        self.payload = self.folder / 'installed/payloads/2.0/new'
        self.payload.mkdir(parents=True)
        shutil.copyfile(self.fixture, self.payload / 'MarkAuto.exe')
        self.addCleanup(self.wait_fixture_exit, self.payload / 'MarkAuto.exe')
        (self.download / 'payload.txt').write_text(str(self.payload))
        self.result = self.folder / 'helper-result.json'
        self.mutex = 'Local\\MarkAuto.UpdateTest.' + uuid4().hex
        return install.InstallRequest(self.installer, sha256(self.installer.read_bytes()).hexdigest(), self.folder / 'installed', {})

    def wait_fixture_exit(self, executable):
        # The launched app is an independent child of PowerShell. Its startup
        # marker is not proof of exit: await its exact native process handle
        # before TemporaryDirectory tries to remove the executable image.
        pid_file = Path(str(executable) + '.pid')
        if not pid_file.exists():
            return
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, int(pid_file.read_text()))
        if not handle:
            self.assertEqual(ctypes.get_last_error(), 87, 'fixture process exit could not be confirmed')
            return
        try:
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0, 'restarted fixture did not exit normally')
        finally:
            kernel.CloseHandle(handle)

    def execute(self, request, **options):
        command = install._helper_command(
            request,
            parent_pid=2147483647,
            mutex_name=self.mutex,
            result_path=self.result,
            show_errors=False,
            **options,
        )
        process = subprocess.run(command, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertTrue(self.result.exists(), process.stderr.decode(errors='replace'))
        result = json.loads(self.result.read_text(encoding='utf-8-sig'))
        self.assertEqual(process.returncode, 0 if result['code'] == 'installed' else 1)
        self.assertFalse(self.installer.exists(), 'completed or rejected installer must be discarded')
        return result

    def test_native_installer_quiet_arguments_and_verified_new_payload_relaunch(self):
        if os.name != 'nt':
            self.assertFalse(install.can_install())
            return
        result = self.execute(self.tree())
        self.assertEqual(result, {'code': 'installed', 'exitCode': 0})
        arguments = Path(str(self.installer) + '.called').read_text().splitlines()
        self.assertEqual(arguments[:3], ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
        self.assertEqual(arguments[3], '/LOG=' + str(self.download / 'install.log'))
        marker = self.payload / 'MarkAuto.exe.called'
        until = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertTrue(marker.exists(), 'new installed application was not reopened')
        self.assertEqual(marker.read_text(), '')

    def test_native_nonzero_installer_exit_is_specific_and_never_relaunches(self):
        if os.name != 'nt':
            return
        request = self.tree()
        (self.download / 'exit.txt').write_text('23')
        self.assertEqual(self.execute(request), {'code': 'update_installer_failed', 'exitCode': 23})
        self.assertFalse((self.payload / 'MarkAuto.exe.called').exists())

    def test_native_hash_change_after_download_is_rejected_without_execution(self):
        if os.name != 'nt':
            return
        request = self.tree()
        with self.installer.open('ab') as stream:
            stream.write(b'changed-after-verification')
        self.assertEqual(self.execute(request)['code'], 'update_hash_mismatch')
        self.assertFalse(Path(str(self.installer) + '.called').exists())

    def test_native_remaining_installation_guard_aborts_without_touching_other_process(self):
        if os.name != 'nt':
            return
        request = self.tree()
        with patch('quantlab.runtime_support.WINDOWS_APP_MUTEX', self.mutex):
            guard = WindowsAppMutex()
        try:
            self.assertEqual(self.execute(request)['code'], 'update_app_running')
            self.assertIsNotNone(guard.handle)
        finally:
            guard.close()
        self.assertFalse(Path(str(self.installer) + '.called').exists())

    def test_native_parent_close_timeout_aborts_and_leaves_parent_alive(self):
        if os.name != 'nt':
            return
        request = self.tree()
        parent_dir = self.folder / 'parent'
        parent_dir.mkdir()
        parent_exe = parent_dir / 'parent.exe'
        shutil.copyfile(self.fixture, parent_exe)
        (parent_dir / 'delay.txt').write_text('6000')
        parent = subprocess.Popen([str(parent_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            command = install._helper_command(request, parent_pid=parent.pid, mutex_name=self.mutex, wait_ms=20, result_path=self.result, show_errors=False)
            finished = subprocess.run(command, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(finished.returncode, 1, finished.stderr)
            self.assertEqual(json.loads(self.result.read_text(encoding='utf-8-sig'))['code'], 'update_parent_timeout')
            self.assertIsNone(parent.poll(), 'helper must never force-close the parent')
            self.assertFalse(Path(str(self.installer) + '.called').exists())
        finally:
            self.assertEqual(parent.wait(timeout=10), 0)

    def test_native_success_with_untrusted_payload_log_refuses_relaunch(self):
        if os.name != 'nt':
            return
        request = self.tree()
        outside = self.folder / 'outside'
        outside.mkdir()
        shutil.copyfile(self.fixture, outside / 'MarkAuto.exe')
        (self.download / 'payload.txt').write_text(str(outside))
        self.assertEqual(self.execute(request)['code'], 'update_restart_failed')
        self.assertFalse((outside / 'MarkAuto.exe.called').exists())
        self.assertFalse((self.payload / 'MarkAuto.exe.called').exists())


if __name__ == '__main__':
    unittest.main()
