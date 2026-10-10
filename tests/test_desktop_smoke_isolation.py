"""Synthetic source-launch smoke must never mutate the user workspace.

Windows uses a pinned disposable discovery path, real mutex/Qt/spawn, and all
preservation assertions. OS known-folder discovery is not verified here; native
discovery and installed-package gates remain separate and unchanged.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    if not root.exists():
        return None
    return {str(p.relative_to(root)): None if p.is_dir() else p.read_bytes()
            for p in root.rglob('*')}


class ReadOnlyWorkspaceTests(unittest.TestCase):
    def test_read_only_default_does_not_create_user_directories(self):
        from quantlab.desktop_runtime import WorkspaceLocator
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'absent-bootstrap'
            self.assertEqual(WorkspaceLocator(root).load(probe=False).root, root)
            self.assertFalse(root.exists())

    def test_read_only_redirect_validates_without_mkdir_or_probe(self):
        from quantlab.desktop_runtime import AppPaths, WorkspaceLocator
        with tempfile.TemporaryDirectory() as temporary:
            bootstrap = Path(temporary) / 'bootstrap'; bootstrap.mkdir()
            workspace = Path(temporary) / 'redirected'
            pointer = bootstrap / 'workspace-location.json'
            pointer.write_text(json.dumps({'schema_version': 1, 'root': str(workspace)}))
            locator = WorkspaceLocator(bootstrap)
            with patch('quantlab.desktop_runtime.tempfile.mkstemp', side_effect=AssertionError('Write probe forbidden')):
                self.assertEqual(locator.load(probe=False), AppPaths(workspace, bootstrap))
            self.assertFalse(workspace.exists())
            with patch('quantlab.desktop_runtime.tempfile.mkstemp', side_effect=AssertionError('Normal startup still probes')):
                with self.assertRaisesRegex(AssertionError, 'still probes'):
                    locator.load()

    def test_read_only_redirect_rejects_invalid_paths(self):
        from quantlab.desktop_runtime import RuntimeSafetyError, WorkspaceLocator
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); bootstrap = root / 'bootstrap'; bootstrap.mkdir()
            pointer = bootstrap / 'workspace-location.json'
            locator = WorkspaceLocator(bootstrap)
            for value in ({'schema_version': 99, 'root': str(root / 'other')},
                          {'schema_version': 1, 'root': '../relative'},
                          {'schema_version': 1, 'root': str(root)}):
                pointer.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(RuntimeSafetyError):
                    locator.load(probe=False)

    def test_read_only_redirect_rejects_symlink_when_supported(self):
        from quantlab.desktop_runtime import RuntimeSafetyError, WorkspaceLocator
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); bootstrap = root / 'bootstrap'; bootstrap.mkdir()
            pointer = bootstrap / 'workspace-location.json'
            locator = WorkspaceLocator(bootstrap)
            target = root / 'target'; target.mkdir()
            alias = root / 'alias'
            try:
                alias.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest('Symlink fixture unsupported on this platform: ' + type(exc).__name__)
            pointer.write_text(json.dumps({'schema_version': 1, 'root': str(alias)}))
            with self.assertRaises(RuntimeSafetyError): locator.load(probe=False)


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for isolated desktop launch')
class SmokeUserStateIsolationTests(unittest.TestCase):
    def smoke(self, *, redirected=False, injected='', expected_status='passed', seeded=True):
        from desktop import _smoke_steps
        from desktop_ui import _paper
        from quantlab.desktop_runtime import AppPaths
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            local_appdata = home / 'LocalAppData'
            bootstrap = local_appdata / 'MarkAuto' if sys.platform == 'win32' else home / '.local/share/MarkAuto'
            workspace = home / 'configured-workspace' if redirected else bootstrap
            if seeded:
                paths = AppPaths(workspace, bootstrap).ensure()
                (paths.state / 'settings.json').write_bytes(b'{\n "schema_version": 1, "settings": {"sentinel": "preserve exact bytes", "persist_logs": false}\n}\n')
                policy = _smoke_steps()[4][1]['policy']
                (paths.state / 'paper_policy.json').write_text(json.dumps(policy))
                broker = _paper(paths.state)
                broker.reconcile(_smoke_steps()[4][1]['snapshot'])
                broker.set_kill_switch(False)
                (paths.state / 'desktop_safety.json').write_text('{"reconciliation_required":false,"reason":"preserve exact sentinel bytes"}\n')
                (paths.state / 'research-sentinel.bin').write_bytes(b'original research state\x00\xff')
                (paths.controls / 'preservation-sentinel.bin').write_bytes(b'original control state')
                (paths.credentials / 'preservation-sentinel.bin').write_bytes(b'nonsecret test sentinel')
                # Recovery is a normal-startup action, never part of a read-only
                # smoke lookup of the user's active or redirected workspace.
                rollback = workspace / 'state-v1.rollback'; rollback.mkdir()
                (rollback / 'original.bin').write_bytes(b'pending recovery must remain untouched')
                (workspace / 'restore-transaction.json').write_text(json.dumps({'phase': 'prepared', 'id': 'a' * 32}))
                (workspace / 'session.json').write_bytes(b'{"sentinel":"preserve previous session evidence"}\n')
                if redirected:
                    (bootstrap / 'workspace-location.json').write_text(json.dumps({'schema_version': 1, 'root': str(workspace)}))
            roots = [bootstrap] + ([workspace] if redirected else [])
            before = [snapshot(root) for root in roots]
            report = home / 'report.json'; attempted_writes = home / 'forbidden-writes.txt'
            # Snapshot comparisons catch durable changes; an audit hook also
            # rejects temporary probes, locks, repairs and write-then-restore.
            code = "import sys, os\nfrom pathlib import Path\n"
            code += "roots = [Path(p) for p in " + repr([str(p) for p in roots]) + "]\n"
            code += "attempts = Path(" + repr(str(attempted_writes)) + ")\n"
            code += '''def audit(event, args):
 if event == 'open':
  mode, flags = args[1], args[2]
  if not ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))): return
  values = args[:1]
 elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate', 'os.utime'):
  values = args[:1]
 elif event in ('os.rename', 'os.link', 'os.symlink'):
  values = args[:2]
 else: return
 for value in values:
  if isinstance(value, (str, bytes, os.PathLike)):
   path = Path(os.fsdecode(value)).absolute()
   if any(path == root or path.is_relative_to(root) for root in roots):
    with attempts.open('a') as stream: stream.write(event + ': ' + str(path) + '\\n')
    raise AssertionError('Smoke attempted a user-state write')
sys.addaudithook(audit)
import desktop
from quantlab.desktop_runtime import AppPaths
# SHGetFolderPathW uses the registered profile, not necessarily LOCALAPPDATA.
# Pin only discovery in this test subprocess; no runner profile is inspected.
# The real Qt startup, Windows mutex, workers and application paths still run.
if sys.platform == 'win32':
 AppPaths.discover = classmethod(lambda cls: cls(Path(os.environ['LOCALAPPDATA']) / 'MarkAuto'))
from PySide6.QtWidgets import QMessageBox
QMessageBox.critical = QMessageBox.information = lambda *args: (_ for _ in ()).throw(AssertionError('Unexpected smoke modal'))
'''
            code += injected + "\nraise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))\n"
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                       LOCALAPPDATA=str(local_appdata), APPDATA=str(home / 'AppData'),
                       QT_QPA_PLATFORM='offscreen', XDG_CACHE_HOME=str(home / 'qt-cache'))
            result = subprocess.run([sys.executable, '-c', code, str(report)], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=150)
            self.assertEqual([snapshot(root) for root in roots], before, 'All real user files and directories must be unchanged')
            self.assertFalse(attempted_writes.exists(), attempted_writes.read_text() if attempted_writes.exists() else '')
            self.assertTrue(report.exists(), result.stderr[-3000:])
            evidence = json.loads(report.read_text())
            self.assertEqual(evidence['status'], expected_status, result.stderr[-3000:] + str(evidence))
            self.assertEqual(result.returncode, 0 if expected_status == 'passed' else 1, result.stderr[-3000:])
            self.assertEqual(evidence['data_dir'], str(workspace))
            self.assertIs(evidence['user_state_read_only'], True)
            execution_root = Path(evidence['smoke_data_dir'])
            self.assertNotIn(execution_root, roots)
            self.assertFalse(any(execution_root.is_relative_to(root) for root in roots))
            self.assertFalse(execution_root.exists(), 'Disposable startup workspace must be cleaned')
            if expected_status == 'passed':
                self.assertEqual(len(evidence['steps']), 7)
                self.assertTrue(all(row['passed'] for row in evidence['steps']))
                for key in ('auth_smoke', 'market_smoke', 'history_smoke'):
                    self.assertEqual(evidence[key]['status'], 'passed')
                self.assertEqual(evidence['history_smoke']['chart_render_checks'], 24)
            return evidence

    def test_success_preserves_default_and_redirected_user_state_bytes(self):
        for redirected in (False, True):
            with self.subTest(redirected=redirected): self.smoke(redirected=redirected)

    def test_failure_preserves_user_state_and_pending_recovery(self):
        self.smoke(injected="sys.modules['quantlab.market_history'] = None", expected_status='failed')
        self.smoke(redirected=True, injected="original = desktop._history_smoke_fixture\ndef missing(root):\n report, payload = original(root)\n payload['local_path'] = str(root / 'missing.csv')\n return report, payload\ndesktop._history_smoke_fixture = missing", expected_status='failed')

    def test_smoke_does_not_create_an_absent_user_workspace(self):
        self.smoke(seeded=False, injected="sys.modules['quantlab.market_history'] = None", expected_status='failed')


if __name__ == '__main__':
    unittest.main()
