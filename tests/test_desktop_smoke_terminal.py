"""Synthetic generic smoke failure/cleanup evidence, not Windows acceptance.

Windows source tests pin only discovery to a disposable fixture. OS known-folder
resolution remains a separate native gate. Unprovable stop can delay Python's
multiprocessing exit join; tests never equate a failed report with stopped work.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

from desktop import _close_smoke_worker
from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError

ROOT = Path(__file__).resolve().parents[1]


def process_can_run(pid):
    if sys.platform == 'win32':
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87: return False
            raise AssertionError('Cannot inspect worker PID safely')
        try:
            status = w.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)):
                raise AssertionError('Cannot inspect worker exit state')
            return status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    if sys.platform.startswith('linux'):
        try: return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
        except FileNotFoundError: return False
    return True


class GenericCleanupProofTests(unittest.TestCase):
    def test_unproved_join_retains_slot_and_handles_until_real_cleanup_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(AppPaths(Path(temporary).resolve()))
            process = Mock(pid=424242); process.is_alive.return_value = False
            manager.process = process; manager.receiver = Mock(); manager.tree = Mock()
            manager.tree.stop_and_join.side_effect = RuntimeSafetyError('private exception text')
            self.assertEqual(_close_smoke_worker(manager), {'verified': False, 'error_type': 'RuntimeSafetyError'})
            self.assertTrue(manager.active); process.close.assert_not_called()
            self.assertIsNone(manager._quiesced_subscription_id)
            manager.tree.stop_and_join.side_effect = None
            self.assertEqual(_close_smoke_worker(manager), {'verified': True, 'error_type': None})
            self.assertEqual(_close_smoke_worker(manager), {'verified': True, 'error_type': None})
            process.close.assert_called_once()
            self.assertEqual(_close_smoke_worker(None), {'verified': True, 'error_type': None})


class GenericSmokeTerminalProcessTests(unittest.TestCase):
    def smoke(self, injected='', *, expected='failed', retained=False, verified=True,
              timed_out=False, expect_worker=True, complete=False):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve(); report = home / 'report.json'; pidfile = home / 'worker-pids.json'
            writes = home / 'report-writes.jsonl'
            bootstrap = home / 'LocalAppData/MarkAuto' if sys.platform == 'win32' else home / '.local/share/MarkAuto'
            code = '''import sys, os, json
from pathlib import Path
import desktop
import quantlab.desktop_runtime as runtime
from quantlab.desktop_runtime import JobManager, AppPaths, RuntimeSafetyError
if sys.platform == 'win32':
 AppPaths.discover = classmethod(lambda cls: cls(Path(os.environ['LOCALAPPDATA']) / 'MarkAuto'))
from PySide6.QtWidgets import QMessageBox
QMessageBox.critical = QMessageBox.information = lambda *args: (_ for _ in ()).throw(AssertionError('No smoke modal'))
original_write = runtime.atomic_write
def audited_write(path, raw):
 if Path(path) == Path(sys.argv[1]):
  with Path(sys.argv[3]).open('a') as stream: stream.write(json.dumps(json.loads(raw)) + '\\n')
 return original_write(path, raw)
runtime.atomic_write = audited_write
original_start = JobManager.start
pids = []
def tracked_start(self, operation, payload):
 value = original_start(self, operation, payload)
 pids.append(self.process.pid)
 Path(sys.argv[2]).write_text(json.dumps(pids))
 return value
JobManager.start = tracked_start
'''
            code += injected + "\nraise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))\n"
            (home / 'sitecustomize.py').write_text("import socket\ndef denied(*args, **kwargs): raise AssertionError('No network')\nsocket.create_connection = socket.getaddrinfo = denied\noriginal = socket.socket.connect\ndef connect(self, address):\n if self.family in (socket.AF_INET, socket.AF_INET6): return denied()\n return original(self, address)\nsocket.socket.connect = socket.socket.connect_ex = connect\n")
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / 'LocalAppData'),
                       APPDATA=str(home / 'AppData'), QT_QPA_PLATFORM='offscreen', XDG_CACHE_HOME=str(home / 'qt-cache'),
                       PYTHONPATH=str(home) + os.pathsep + str(ROOT))
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-c', code, str(report), str(pidfile), str(writes)], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=40)
            self.assertLess(time.monotonic() - started, 40)
            self.assertEqual(result.returncode, 0 if expected == 'passed' else 1, result.stderr[-3000:])
            self.assertTrue(report.exists(), result.stderr[-3000:])
            value = json.loads(report.read_text())
            self.assertEqual(value['status'], expected)
            self.assertEqual(value['worker_cleanup']['verified'], verified)
            self.assertEqual(value.get('timed_out', False), timed_out)
            self.assertNotIn('private exception', report.read_text())
            self.assertFalse(bootstrap.exists(), 'User root must remain absent')
            self.assertEqual(pidfile.exists(), expect_worker)
            if expect_worker:
                self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pidfile.read_text())))
            # In particular a final cleanup failure must never publish a stale PASS.
            self.assertEqual([json.loads(line)['status'] for line in writes.read_text().splitlines()], [expected])
            execution_root = Path(value['smoke_data_dir'])
            self.assertEqual(execution_root.exists(), retained)
            if retained:
                self.assertTrue(execution_root.name.startswith('markauto-smoke-startup-'))
                shutil.rmtree(execution_root)  # Process and every recorded worker are independently stopped.
            if complete:
                self.assertEqual(len(value['steps']), 7)
                self.assertTrue(all(row['passed'] for row in value['steps']))
                for key in ('auth_smoke', 'market_smoke', 'history_smoke'):
                    self.assertEqual(value[key]['status'], 'passed')
                self.assertEqual(value['history_smoke']['chart_render_checks'], 24)
            return value

    def test_success_publishes_once_only_after_verified_cleanup(self):
        self.smoke(expected='passed', complete=True)

    def test_poll_exception_cancels_and_joins_actual_spawned_worker(self):
        self.smoke('''original = JobManager.poll
raised = False
def fail(self):
 global raised
 if self._operation == 'ui_campaign' and not raised:
  raised = True
  if not self.process.is_alive(): raise AssertionError('Expected real live worker')
  raise RuntimeError('private exception poll failure')
 return original(self)
JobManager.poll = fail
''')

    def test_join_proof_failure_retains_state_without_claiming_bounded_unprovable_stop(self):
        # Actual processes are stopped first, then the proof operation fails.
        # This is not evidence of bounded exit when OS termination itself fails.
        self.smoke('''original = JobManager._join_descendants
def unverified(self, pid):
 original(self, pid)
 if self._operation == 'ui_demo': raise RuntimeSafetyError('private exception join failure')
JobManager._join_descendants = unverified
''', retained=True, verified=False)

    def test_original_global_deadline_cancels_actual_worker(self):
        self.smoke('''import time
original_time = time.monotonic
expired = False
def current(): return original_time() + (121 if expired else 0)
time.monotonic = current
original = JobManager.start
def expire(self, operation, payload):
 global expired
 result = original(self, operation, payload)
 if operation == 'ui_campaign': expired = True
 return result
JobManager.start = expire
''', timed_out=True)

    def test_late_worker_cleanup_failure_changes_pass_to_single_failed_report(self):
        self.smoke('''original = JobManager.close
original_cleanup = desktop._close_smoke_worker
finalizing = False
def fail_final(self):
 if finalizing and self._operation is not None: raise RuntimeSafetyError('private exception final close failure')
 return original(self)
def cleanup(manager):
 global finalizing
 finalizing = True
 try: return original_cleanup(manager)
 finally: finalizing = False
JobManager.close = fail_final
desktop._close_smoke_worker = cleanup
''', retained=True, verified=False, complete=True)

    def test_late_directory_cleanup_failure_cannot_leave_pass_or_zero_exit(self):
        self.smoke('''import tempfile
original = tempfile.TemporaryDirectory.cleanup
def fail_final(self):
 if Path(self.name).name.startswith('markauto-smoke-startup-'): raise OSError('private exception final directory failure')
 return original(self)
tempfile.TemporaryDirectory.cleanup = fail_final
''', retained=True, verified=False, complete=True)

    def test_late_base_exception_cannot_suppress_failed_shutdown_evidence(self):
        for error in ('KeyboardInterrupt', 'SystemExit'):
            with self.subTest(error=error):
                self.smoke("""from quantlab.desktop_runtime import RuntimeGuard
original = RuntimeGuard.finish
calls = 0
def interrupt(self):
 global calls
 calls += 1
 if calls == 2: raise """ + error + """('private exception interrupted shutdown')
 return original(self)
RuntimeGuard.finish = interrupt
""", complete=True)

    def test_startup_error_and_final_cleanup_failure_still_emit_failure(self):
        self.smoke('''def startup_error(*args): raise RuntimeError('private exception startup failure')
desktop._history_smoke_fixture = startup_error
def cleanup_error(*args): raise RuntimeSafetyError('private exception startup close failure')
JobManager.close = cleanup_error
''', retained=True, verified=False, expect_worker=False)


if __name__ == '__main__': unittest.main()
