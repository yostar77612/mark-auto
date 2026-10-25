"""Frozen runtime dispatch keeps SQLite first and the GUI out of pure children."""

import ast
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'packaging' / 'early_multiprocessing_runtime_hook.py'


class EarlyRuntimeBootstrapTests(unittest.TestCase):
    def run_probe(self, frozen, platform, argv, expected):
        code = """
import importlib.abc
import multiprocessing.spawn as spawn
from pathlib import Path
import runpy
import sys

hook, frozen, platform, arguments, expected = sys.argv[1:]
import json
sys.frozen = json.loads(frozen)
sys.platform = platform
sys.argv = json.loads(arguments)
calls = []
def dispatch():
    calls.append(True)
    raise SystemExit(0)
spawn.freeze_support = dispatch
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide6', 'desktop_', 'shioaji')):
            raise AssertionError('Pure child imported a UI or SDK dependency')
sys.meta_path.insert(0, BlockQt())
try:
    runpy.run_path(hook, run_name='runtime_hook_probe')
except SystemExit as error:
    assert error.code == 0
assert len(calls) == int(expected), calls
assert not Path('MUST_NOT_EXECUTE.txt').exists()
"""
        import json

        result = subprocess.run(
            [sys.executable, '-s', '-c', code, str(HOOK), json.dumps(frozen), platform, json.dumps(argv), str(expected)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_windows_child_dispatches_without_qt_or_sdk(self):
        self.run_probe(True, 'win32', ['MarkAuto.exe', '--multiprocessing-fork', 'parent_pid=1', 'pipe_handle=2'], 1)

    def test_normal_parent_remains_passive_for_full_original_hooks(self):
        self.run_probe(True, 'win32', ['MarkAuto.exe', '--smoke-isolated'], 0)

    def test_nonfrozen_and_nonwindows_children_remain_passive(self):
        self.run_probe(False, 'win32', ['python.exe', '--multiprocessing-fork'], 0)
        self.run_probe(True, 'linux', ['MarkAuto', '--multiprocessing-fork'], 0)

    def test_command_strings_are_never_executed_by_this_hook(self):
        command = "open('MUST_NOT_EXECUTE.txt', 'w').write('forbidden')"
        self.run_probe(True, 'win32', ['MarkAuto.exe', '-c', command], 0)
        for prefix in ('from multiprocessing.resource_tracker import main', 'from multiprocessing.forkserver import main'):
            self.run_probe(True, 'win32', ['MarkAuto.exe', '-c', prefix + '; ' + command], 0)

    def test_sqlite_gate_precedes_dispatch_in_actual_spec(self):
        tree = ast.parse((ROOT / 'packaging' / 'markauto.spec').read_text(encoding='utf-8'))
        analysis = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Analysis')
        hooks = next(keyword.value for keyword in analysis.keywords if keyword.arg == 'runtime_hooks')
        self.assertIsInstance(hooks, ast.List)
        paths = [node.value for entry in hooks.elts for node in ast.walk(entry) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertEqual(paths, ['packaging/sqlite_runtime_hook.py', 'packaging/early_multiprocessing_runtime_hook.py'])

    def test_sqlite_verification_failure_prevents_worker_dispatch(self):
        code = """
import multiprocessing.spawn as spawn
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

root = Path(sys.argv[1])
sys.frozen = True
sys._MEIPASS = str(root)
sys.argv = ['MarkAuto.exe', '--multiprocessing-fork', 'parent_pid=1', 'pipe_handle=2']
calls = []
def reject_sqlite(*args):
    calls.append('sqlite')
    raise RuntimeError('Pinned SQLite verification failed')
def dispatch():
    calls.append('worker')
    raise AssertionError('SQLite rejection must stop dispatch')
sys.modules['quantlab.sqlite_runtime'] = SimpleNamespace(verify=reject_sqlite)
spawn.freeze_support = dispatch
try:
    for hook in ('sqlite_runtime_hook.py', 'early_multiprocessing_runtime_hook.py'):
        runpy.run_path(str(root / 'packaging' / hook))
except RuntimeError as error:
    assert str(error) == 'Pinned SQLite verification failed'
else:
    raise AssertionError('SQLite failure must propagate')
assert calls == ['sqlite'], calls
"""
        result = subprocess.run([sys.executable, '-s', '-c', code, str(ROOT)], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
