"""The shared runtime rejection type remains unique across real service boundaries."""

import ast
from pathlib import Path
import pickle
import unittest

from quantlab import desktop_runtime, runtime_support
from quantlab.shared.runtime_errors import RuntimeSafetyError

ROOT = Path(__file__).resolve().parents[1]


class SharedRuntimeErrorTests(unittest.TestCase):
    def test_actual_runtime_modules_share_the_original_error_type(self):
        self.assertIs(desktop_runtime.RuntimeSafetyError, RuntimeSafetyError)
        self.assertIs(runtime_support.RuntimeSafetyError, RuntimeSafetyError)
        self.assertEqual(RuntimeSafetyError.__bases__, (ValueError,))
        original = RuntimeSafetyError('unchanged rejection message')
        restored = pickle.loads(pickle.dumps(original))
        self.assertIs(type(restored), RuntimeSafetyError)
        self.assertEqual(restored.args, original.args)

    def test_actual_registry_rejections_keep_exact_type_and_messages(self):
        registry = desktop_runtime._OperationExecutorRegistry()
        for action, expected in (
            (registry.executor, 'No operation executor is registered'),
            (lambda: registry.register(None), 'Operation executor must be callable'),
        ):
            with self.subTest(expected=expected), self.assertRaises(RuntimeSafetyError) as caught:
                action()
            self.assertIs(type(caught.exception), RuntimeSafetyError)
            self.assertEqual(str(caught.exception), expected)
        callback = lambda: None
        registry.register(callback)
        registry.register(callback)
        with self.assertRaises(RuntimeSafetyError) as caught:
            registry.register(lambda: None)
        self.assertEqual(str(caught.exception), 'A different operation executor is already registered')

    def test_one_actual_definition_and_shared_leaf_has_no_imports(self):
        definitions = []
        for path in (ROOT / 'quantlab').rglob('*.py'):
            for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
                if isinstance(node, ast.ClassDef) and node.name == 'RuntimeSafetyError':
                    definitions.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(definitions, ['quantlab/shared/runtime_errors.py'])
        leaf = ast.parse((ROOT / definitions[0]).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(leaf)))
