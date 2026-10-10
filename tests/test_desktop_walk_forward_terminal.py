"""Synthetic callback/cleanup failures; no Windows-client acceptance claim."""
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

from tests import test_desktop_walk_forward_runtime as runtime_tests
REFERENCE = runtime_tests.REFERENCE
from quantlab.desktop_runtime import RuntimeSafetyError
from desktop import _close_smoke_worker

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


class TerminalRuntimeProofTests(unittest.TestCase):
    def fixture(self):
        fixture = runtime_tests.WalkForwardRuntimeTests(methodName='runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        return fixture

    def test_stopped_corrupt_owner_releases_handles_without_reconciliation_proof(self):
        f = self.fixture(); job_id = f.start_fake()
        owner = f.manager._walk_forward_owner_path(REFERENCE)
        owner.write_text('{}')
        f.frame(result={'reference': REFERENCE, 'status': 'completed'}); f.alive = False
        with self.assertRaisesRegex(RuntimeSafetyError, 'ownership mismatch'): f.manager.poll()
        self.assertFalse(f.manager.active)
        f.process.close.assert_called_once(); f.tree.stop_and_join.assert_called_once()
        self.assertIsNone(f.manager._quiesced_walk_forward)
        self.assertEqual(_close_smoke_worker(f.manager), {'verified': False, 'error_type': None})
        self.assertEqual(_close_smoke_worker(f.manager), {'verified': False, 'error_type': None})
        self.assertEqual(owner.read_text(), '{}')
        with self.assertRaisesRegex(RuntimeSafetyError, 'stop proof'):
            f.manager.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})

    def test_join_failure_keeps_slot_handles_state_and_blocks_reconciliation(self):
        f = self.fixture(); job_id = f.start_fake()
        stopped = f.tree.stop_and_join.side_effect
        f.tree.stop_and_join.side_effect = RuntimeSafetyError('private exception text must not be reported')
        self.assertEqual(_close_smoke_worker(f.manager), {'verified': False, 'error_type': 'RuntimeSafetyError'})
        self.assertTrue(f.manager.active); f.process.close.assert_not_called()
        self.assertIsNone(f.manager._quiesced_walk_forward)
        self.assertTrue(f.manager._walk_forward_owner_path(REFERENCE).exists())
        with self.assertRaises(RuntimeSafetyError):
            f.manager.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})
        f.tree.stop_and_join.side_effect = stopped
        self.assertEqual(_close_smoke_worker(f.manager), {'verified': True, 'error_type': None})
        self.assertEqual(_close_smoke_worker(f.manager), {'verified': True, 'error_type': None})
        self.assertEqual(f.manager._quiesced_walk_forward, (job_id, REFERENCE))


class TerminalSmokeProcessTests(unittest.TestCase):
    def smoke(self, injected, *, retained, cleanup_verified=None, timed_out=False):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary); report = home / 'report.json'; pidfile = home / 'worker-pids.json'
            bootstrap = home / 'LocalAppData/MarkAuto' if sys.platform == 'win32' else home / '.local/share/MarkAuto'
            code = '''import sys, os, json
from pathlib import Path
import desktop
from quantlab.desktop_runtime import JobManager, AppPaths, RuntimeSafetyError
if sys.platform == 'win32':
 AppPaths.discover = classmethod(lambda cls: cls(Path(os.environ['LOCALAPPDATA']) / 'MarkAuto'))
from PySide6.QtWidgets import QMessageBox
QMessageBox.critical = QMessageBox.information = lambda *args: (_ for _ in ()).throw(AssertionError('No smoke modal'))
original_start = JobManager.start
pids = []
def tracked_start(self, operation, payload):
 value = original_start(self, operation, payload)
 if operation.startswith('ui_walk_forward_'):
  pids.append(self.process.pid)
  Path(sys.argv[2]).write_text(json.dumps(pids))
 return value
JobManager.start = tracked_start
'''
            code += injected + "\nraise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))\n"
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / 'LocalAppData'),
                       APPDATA=str(home / 'AppData'), QT_QPA_PLATFORM='offscreen', XDG_CACHE_HOME=str(home / 'qt-cache'))
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-c', code, str(report), str(pidfile)], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=40)
            self.assertLess(time.monotonic() - started, 40)
            self.assertEqual(result.returncode, 1, result.stderr[-3000:])
            self.assertTrue(report.exists(), result.stderr[-3000:])
            value = json.loads(report.read_text())
            self.assertEqual(value['status'], 'failed')
            self.assertEqual(value['walk_forward_smoke']['status'], 'failed')
            self.assertEqual(value['timed_out'], timed_out)
            self.assertEqual(len(value['steps']), 7)
            self.assertTrue(all(row['passed'] for row in value['steps']))
            self.assertNotIn('private exception', report.read_text())
            self.assertFalse(bootstrap.exists(), 'User root must remain absent')
            self.assertTrue(pidfile.exists())
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pidfile.read_text())))
            execution_root = Path(value['smoke_data_dir'])
            self.assertEqual(execution_root.exists(), retained)
            if cleanup_verified is not None:
                self.assertEqual(value['worker_cleanup']['verified'], cleanup_verified)
            if retained:
                self.assertTrue(execution_root.name.startswith('markauto-smoke-startup-'))
                # The process has exited and every recorded real spawned worker
                # is independently stopped before the test removes evidence.
                shutil.rmtree(execution_root)
            return value

    def test_corrupt_owner_emits_finite_failed_report_and_retains_unverified_evidence(self):
        self.smoke('''original = JobManager.start
def corrupt(self, operation, payload):
 result = original(self, operation, payload)
 if operation == 'ui_walk_forward_run': self._walk_forward_owner_path(payload['preview_identity']).write_text('{}')
 return result
JobManager.start = corrupt
''', retained=True, cleanup_verified=False)

    def test_join_failure_is_reported_without_fake_cleanup_or_evidence_deletion(self):
        self.smoke('''original = JobManager._join_descendants
def unverified(self, pid):
 original(self, pid)
 if self._operation == 'ui_walk_forward_run': raise RuntimeSafetyError('private exception join failure')
JobManager._join_descendants = unverified
''', retained=True, cleanup_verified=False)

    def test_poll_exception_cancels_real_spawned_worker_and_proves_cleanup(self):
        self.smoke('''original = JobManager.poll
raised = False
def fail(self):
 global raised
 if self._operation == 'ui_walk_forward_run' and not raised:
  raised = True
  raise RuntimeError('private exception poll failure')
 return original(self)
JobManager.poll = fail
''', retained=False, cleanup_verified=True)

    def test_global_deadline_cancels_real_spawn_without_adding_time_budget(self):
        value = self.smoke('''import time
original_time = time.monotonic
expired = False
def current(): return original_time() + (121 if expired else 0)
time.monotonic = current
original = JobManager.start
def expire(self, operation, payload):
 global expired
 result = original(self, operation, payload)
 if operation == 'ui_walk_forward_run': expired = True
 return result
JobManager.start = expire
''', retained=False, timed_out=True)
        self.assertFalse(value['walk_forward_smoke']['steps'][-1]['passed'])


if __name__ == '__main__': unittest.main()
