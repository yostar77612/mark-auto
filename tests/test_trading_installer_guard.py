"""Installer-visible guard belongs independently to the v2 UI and engine."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from quantlab.runtime_support import RuntimeSafetyError, WINDOWS_APP_MUTEX, WindowsAppMutex
from quantlab.trading.runtime import server
from quantlab.trading.runtime.protocol import Operation
import trading_runtime


WORKSPACE = Path(__file__).resolve().parents[2]


class InstallerGuardBoundaryTests(unittest.TestCase):
    def test_ui_acquires_before_body_and_releases_on_return_or_exception(self):
        for error in (None, RuntimeError('controlled UI body failure')):
            events = []
            guard = Mock()
            guard.close.side_effect = lambda: events.append('close')

            def acquire():
                events.append('acquire')
                return guard

            def body(*args, **kwargs):
                events.append('body')
                if error is not None:
                    raise error
                return 17

            with self.subTest(error=error), patch.object(trading_runtime, 'WindowsAppMutex', side_effect=acquire):
                with patch.object(trading_runtime, '_run_window', side_effect=body):
                    if error is None:
                        self.assertEqual(trading_runtime.run_window(), 17)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'controlled UI body failure'):
                            trading_runtime.run_window()
            self.assertEqual(events, ['acquire', 'body', 'close'])
            guard.close.assert_called_once_with()

    def test_ui_guard_failure_cannot_open_context_workspace_or_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'not-created'
            with (
                patch.object(trading_runtime, 'WindowsAppMutex', side_effect=RuntimeSafetyError('guard unavailable')),
                patch.object(trading_runtime, '_run_window') as body,
                patch.object(trading_runtime, 'RuntimeContextManager') as contexts,
            ):
                with self.assertRaises(RuntimeSafetyError):
                    trading_runtime.run_window(root)
                body.assert_not_called()
                contexts.assert_not_called()
            self.assertFalse(root.exists())

    def test_engine_guard_failure_precedes_endpoint_and_engine_factory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'not-created'
            factory = Mock()
            with (
                patch.object(server, 'WindowsAppMutex', side_effect=RuntimeSafetyError('guard unavailable')),
                patch.object(server, '_serve') as body,
                patch.object(server, 'unix_endpoint') as endpoint,
            ):
                with self.assertRaises(RuntimeSafetyError):
                    server.serve(root, engine_factory=factory)
                body.assert_not_called()
                endpoint.assert_not_called()
                factory.assert_not_called()
            self.assertFalse(root.exists())

    def test_engine_releases_guard_on_return_and_startup_exception(self):
        for error in (None, RuntimeError('controlled engine body failure')):
            guard = Mock()
            with self.subTest(error=error), patch.object(server, 'WindowsAppMutex', return_value=guard):
                with patch.object(server, '_serve', return_value=0, side_effect=error), patch.object(server, 'unix_endpoint'):
                    if error is None:
                        self.assertEqual(server.serve(Path('unused')), 0)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'controlled engine body failure'):
                            server.serve(Path('unused'))
            guard.close.assert_called_once_with()

    def test_shared_guard_remains_a_noop_on_non_windows(self):
        with patch('quantlab.runtime_support.sys.platform', 'linux'):
            with patch('quantlab.runtime_support.ctypes.WinDLL', create=True) as windows_api:
                guard = WindowsAppMutex()
                self.assertIsNone(guard.handle)
                guard.close()
                windows_api.assert_not_called()


class WindowsInstallerGuardLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (WORKSPACE / 't').mkdir(parents=True, exist_ok=True)

    def visible(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        ctypes.set_last_error(0)
        handle = kernel.OpenMutexW(0x00100000, False, WINDOWS_APP_MUTEX)
        if handle:
            kernel.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        if error != 2:
            raise ctypes.WinError(error)
        return False

    def start_ui_entry(self, root):
        ready, stop = root / 'ui-ready', root / 'ui-stop'
        source = '''import sys,time
from pathlib import Path
import trading_runtime
root=Path(sys.argv[1])
def controlled_body(*args,**kwargs):
    (root/'ui-ready').write_text('public UI entry acquired guard',encoding='utf-8')
    while not (root/'ui-stop').exists(): time.sleep(0.02)
    if (root/'ui-fail').exists(): raise RuntimeError('controlled public UI body failure')
    return 0
trading_runtime._run_window=controlled_body
raise SystemExit(trading_runtime.run_window(root))
'''
        process = subprocess.Popen(
            [sys.executable, '-c', source, str(root)],
            cwd=Path(trading_runtime.__file__).parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'owned UI entry did not reach guarded body')
            self.assertIsNone(process.poll())
            return process, stop
        except BaseException:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            raise

    def native_platform(self):
        if os.name == 'nt':
            return True
        # The actual non-Windows contract is a no-op, not a new applicability
        # skip. This does not claim native Windows evidence on a Unix runner.
        guard = WindowsAppMutex()
        self.assertIsNone(guard.handle)
        guard.close()
        with patch.object(trading_runtime, '_run_window', return_value=23):
            self.assertEqual(trading_runtime.run_window(), 23)
        return False

    def test_native_guard_survives_either_owned_process_exiting_first(self):
        # Real OpenMutex/guard handles and a real authenticated local engine.
        # The UI child's private body is controlled, not rendered desktop QA.
        if not self.native_platform():
            return
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        evidence = []
        for first in ('ui', 'engine'):
            self.assertFalse(self.visible(), 'A preexisting app lifetime must not be disturbed')
            with self.subTest(first=first), tempfile.TemporaryDirectory(prefix='v2-install-guard-', dir=WORKSPACE / 't') as temporary:
                root = Path(temporary)
                engine_root = root / 'engine'
                ui_process = engine_process = None
                stop = root / 'ui-stop'
                row = {'first_exit': first, 'before': False, 'ui_body_controlled_not_rendered': True, 'elevated': elevated}
                try:
                    if first == 'engine':
                        ui_process, stop = self.start_ui_entry(root)
                        self.assertTrue(self.visible())
                        row['ui_only_visible'] = True
                    facade = trading_runtime.ensure_engine(engine_root)
                    engine_process = trading_runtime._STARTED[engine_root.resolve()]
                    self.assertEqual(facade.request(Operation.METRICS).metrics.process_id, engine_process.pid)
                    self.assertTrue(self.visible())
                    row.update(engine_pid=engine_process.pid, engine_visible=True)
                    if ui_process is None:
                        ui_process, stop = self.start_ui_entry(root)
                    row['ui_pid'] = ui_process.pid
                    if first == 'ui':
                        stop.write_text('close only owned UI', encoding='utf-8')
                        self.assertEqual(ui_process.wait(timeout=15), 0)
                        self.assertTrue(self.visible(), 'Engine must retain guard after UI closes')
                        self.assertEqual(facade.request(Operation.METRICS).metrics.process_id, engine_process.pid)
                        trading_runtime.shutdown(engine_root)
                    else:
                        trading_runtime.shutdown(engine_root)
                        self.assertTrue(self.visible(), 'UI must retain guard after engine closes')
                        self.assertIsNone(ui_process.poll())
                        stop.write_text('close only owned UI', encoding='utf-8')
                        self.assertEqual(ui_process.wait(timeout=15), 0)
                    row['guard_survived_first_exit'] = True
                    self.assertFalse(self.visible())
                    row['after_both_exit'] = False
                finally:
                    if ui_process is not None and ui_process.poll() is None:
                        stop.write_text('cleanup owned UI', encoding='utf-8')
                        try:
                            ui_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            ui_process.terminate()
                            ui_process.wait(timeout=5)
                    engine_process = engine_process or trading_runtime._STARTED.get(engine_root.resolve())
                    if engine_process is not None and engine_process.poll() is None:
                        try:
                            trading_runtime.shutdown(engine_root)
                        finally:
                            if engine_process.poll() is None:
                                engine_process.terminate()
                                engine_process.wait(timeout=5)
                    row['owned_cleanup_verified'] = all(process is None or process.poll() is not None for process in (ui_process, engine_process))
                    evidence.append(row)
        directory = Path(os.environ.get('TEMP', str(WORKSPACE / 't')))
        (directory / 'v2-installer-guard-native.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')

    def test_native_ui_exception_releases_guard_without_engine_or_workspace(self):
        if not self.native_platform():
            return
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        self.assertFalse(self.visible(), 'A preexisting app lifetime must not be disturbed')
        with tempfile.TemporaryDirectory(prefix='v2-install-ui-fail-', dir=WORKSPACE / 't') as temporary:
            root = Path(temporary)
            (root / 'ui-fail').write_text('controlled failure after ready', encoding='utf-8')
            process = None
            try:
                process, stop = self.start_ui_entry(root)
                self.assertTrue(self.visible())
                stop.write_text('raise only in owned body', encoding='utf-8')
                self.assertNotEqual(process.wait(timeout=15), 0)
                self.assertFalse(self.visible())
                self.assertFalse((root / 'engine-session-v2.json').exists())
                self.assertFalse((root / 'trading-v2.sqlite').exists())
                self.assertEqual({path.name for path in root.iterdir()}, {'ui-fail', 'ui-ready', 'ui-stop'})
                directory = Path(os.environ.get('TEMP', str(WORKSPACE / 't')))
                (directory / 'v2-installer-guard-exception.json').write_text(
                    json.dumps(
                        {
                            'elevated': elevated,
                            'owned_ui_pid': process.pid,
                            'actual_exit_code': process.returncode,
                            'guard_visible_after_exception': False,
                            'ui_body_controlled_not_rendered': True,
                        },
                        indent=2,
                    ),
                    encoding='utf-8',
                )
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
