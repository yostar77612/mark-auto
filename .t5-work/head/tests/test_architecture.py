"""Release boundary: research is import-safe and never depends on legacy trading."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IsolationTests(unittest.TestCase):
    def test_no_legacy_or_broker_dependencies(self):
        banned = {"trader", "shioaji", "pickle", "subprocess"}
        for path in (ROOT / "quantlab").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [x.name.split(".")[0] for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [(node.module or "").split(".")[0]]
                else:
                    continue
                self.assertFalse(banned.intersection(modules), str(path))

    def test_import_is_offline_without_credentials(self):
        code = r'''
import os, socket, pathlib, tempfile, sys, importlib
root = pathlib.Path.cwd()
def denied(*a, **k): raise AssertionError("network access during research import")
class GuardedSocket(socket.socket):
    def __init__(self, *a, **k): denied()
socket.socket = GuardedSocket
socket.create_connection = denied
for key in list(os.environ):
    if any(s in key.lower() for s in ("token", "secret", "api_key", "password")):
        del os.environ[key]
before = set(root.iterdir())
for path in sorted((root / "quantlab").glob("*.py")):
    if path.name != "__main__.py":
        importlib.import_module("quantlab." + path.stem)
assert "trader" not in sys.modules and "shioaji" not in sys.modules
assert set(root.iterdir()) == before
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quantlab_contains_no_dynamic_code_execution(self):
        for path in (ROOT / "quantlab").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "compile", "__import__"}, str(path))


if __name__ == "__main__":
    unittest.main()
