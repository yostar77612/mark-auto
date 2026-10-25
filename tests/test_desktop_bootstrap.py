"""Process-entry dispatch must not initialize the desktop in frozen workers."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopBootstrapTests(unittest.TestCase):
    def run_probe(self, code):
        result = subprocess.run(
            [sys.executable, '-s', '-c', code, str(ROOT / 'desktop.py')],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_frozen_worker_diverts_before_any_desktop_import(self):
        output = self.run_probe("""
import importlib.abc
import runpy
import sys
from types import SimpleNamespace

class DesktopImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('desktop_', 'quantlab', 'PySide6', 'shioaji')):
            raise RuntimeError('Desktop dependency loaded before worker dispatch')

def dispatch_worker():
    print('worker-dispatched-before-desktop')
    raise SystemExit(0)

sys.meta_path.insert(0, DesktopImportGuard())
sys.modules['multiprocessing'] = SimpleNamespace(freeze_support=dispatch_worker)
runpy.run_path(sys.argv[1], run_name='__main__')
raise AssertionError('Worker dispatch returned into the desktop')
""")
        self.assertEqual(output.strip(), 'worker-dispatched-before-desktop')

    def test_import_does_not_dispatch_worker_or_initialize_qt(self):
        output = self.run_probe("""
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

def unexpected_dispatch():
    raise AssertionError('Import is not an executable process entry')

sys.modules['multiprocessing'] = SimpleNamespace(freeze_support=unexpected_dispatch)
module = runpy.run_path(sys.argv[1], run_name='desktop_import_probe')
report = Path(sys.argv[1]).resolve().with_name('bootstrap-synthetic-report.json')
args = module['parse_args'](['--smoke-test', str(report), '--smoke-isolated'])
assert args.smoke_test == report and args.smoke_isolated
assert not any(name.startswith(('PySide6', 'shioaji')) for name in sys.modules)
assert not report.exists()
print('import-is-passive-and-arguments-preserved')
""")
        self.assertEqual(output.strip(), 'import-is-passive-and-arguments-preserved')

    def test_normal_main_retains_help_and_dispatches_once(self):
        output = self.run_probe("""
import multiprocessing
import runpy
import sys

calls = []
multiprocessing.freeze_support = lambda: calls.append(True)
source = sys.argv[1]
sys.argv = [source, '--help']
try:
    runpy.run_path(source, run_name='__main__')
except SystemExit as exc:
    assert exc.code == 0
else:
    raise AssertionError('Help must exit without launching Qt')
assert calls == [True]
assert not any(name.startswith(('PySide6', 'shioaji')) for name in sys.modules)
""")
        self.assertIn('--smoke-test', output)
        self.assertIn('--smoke-isolated', output)


if __name__ == '__main__':
    unittest.main()
