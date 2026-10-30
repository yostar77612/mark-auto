"""Real source-worker imports preserve parent GUI and operation isolation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import quantlab.desktop_runtime as runtime
from tests.layered_source_fixtures import CURRENT_PATHS

FORMER_PAGE_MODULES = {current.removesuffix('.py').replace('/', '.') for old, current in CURRENT_PATHS.items() if old.startswith('desktop_pages/')}

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
ORIGINAL_WORKER = runtime._job_worker


def observed_worker(sender, gate, operation, payload, root, bootstrap, job_id, reconciliation_admitted=False, *extra):
    """Observe the real one-job worker without substituting any operation."""
    try:
        ORIGINAL_WORKER(sender, gate, operation, payload, root, bootstrap, job_id, reconciliation_admitted, *extra)
    finally:
        # Observe the already-resolved registrar module in the actual child.
        import desktop_app.shell.main_window

        refused = False
        try:
            desktop_app.shell.main_window.create_window(None, None)
        except RuntimeError:
            refused = True
        qt = sorted(name for name in sys.modules if name == 'PySide6' or name.startswith('PySide6.'))
        pages = sorted(FORMER_PAGE_MODULES.intersection(list(sys.modules)))
        Path(root, 'worker-import-proof.json').write_text(json.dumps({'pid': os.getpid(), 'qt': qt, 'pages': pages, 'gui_refused': refused}), encoding='utf-8')


class SourceWorkerImportTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='wi-', dir=WORKSPACE / 't')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_actual_spawned_operation_worker_runs_real_demo_without_qt_or_pages(self):
        manager = runtime.JobManager(runtime.AppPaths(self.root).ensure())
        self.addCleanup(manager.close)
        with patch.object(runtime, '_job_worker', observed_worker):
            manager.start('ui_demo', {'bars': 120})
        child_pid = manager.process.pid
        events = []
        deadline = time.monotonic() + 10
        while manager.active and time.monotonic() < deadline:
            events.extend(manager.poll())
            time.sleep(0.01)
        self.assertFalse(manager.active, 'real isolated demo worker did not stop')
        self.assertTrue(any(e['type'] == 'result' for e in events), events)
        proof = json.loads((self.root / 'worker-import-proof.json').read_text(encoding='utf-8'))
        self.assertEqual(proof, {'pid': child_pid, 'qt': [], 'pages': [], 'gui_refused': True})
        self.assertNotEqual(child_pid, os.getpid())

    def test_first_parent_registrar_lookup_cannot_poison_real_mainwindow_or_public_aliases(self):
        code = '''from pathlib import Path
import sys
from quantlab.desktop_runtime import _worker_operation_executor, _is_worker_registrar_import, AppPaths, JobManager, SettingsStore, BackupManager, RuntimeGuard
executor = _worker_operation_executor('desktop_app.shell.main_window:execute_ui_operation')
assert not _is_worker_registrar_import()
import desktop_app.shell.main_window
from PySide6.QtWidgets import QApplication, QMainWindow
app = QApplication([])
paths = AppPaths(Path(sys.argv[1])).ensure()
manager = JobManager(paths)
window = desktop_app.shell.main_window.create_window(paths, manager, SettingsStore(paths.state / "settings.json"), BackupManager(paths, manager), RuntimeGuard(paths))
assert isinstance(window, QMainWindow)
assert executor is desktop_app.shell.main_window.execute_ui_operation
assert window.__class__ is desktop_app.shell.window.MainWindow
assert desktop_app.shell.main_window.QMainWindow is QMainWindow
manager.close()
window.close()
print('real parent GUI after first registrar lookup')
'''
        result = subprocess.run(
            [sys.executable, '-c', code, str(self.root)],
            cwd=ROOT,
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(ROOT)),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('real parent GUI', result.stdout)

    def test_failed_registrar_import_restores_process_role(self):
        self.assertFalse(runtime._is_worker_registrar_import())
        with self.assertRaises(ModuleNotFoundError):
            runtime._worker_operation_executor('_markauto_absent_worker_registrar:execute')
        self.assertFalse(runtime._is_worker_registrar_import())


if __name__ == '__main__':
    unittest.main()
