"""A real spawned registrar import must never attempt Qt or the eager pages entry."""

import importlib
import importlib.abc
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest

import quantlab.desktop_runtime as runtime


def guarded_registrar_import(proof_path):
    attempts = []

    class RejectQt(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in ('PySide6', 'shiboken6'):
                attempts.append(fullname)
                raise AssertionError('Qt import attempted in a registrar-only child')
            return None

    blocker = RejectQt()
    sys.meta_path.insert(0, blocker)
    try:
        executor = runtime._worker_operation_executor('desktop_app.shell.main_window:execute_ui_operation')
        module = importlib.import_module('desktop_app.shell.main_window')
        refused = False
        try:
            module.create_window(None, None)
        except RuntimeError:
            refused = True
        proof = {
            'pid': os.getpid(),
            'real_child': multiprocessing.parent_process() is not None,
            'same_executor': executor is module.execute_ui_operation,
            'gui_refused': refused,
            'attempts': attempts,
            'qt': sorted(name for name in sys.modules if name.split('.')[0] in ('PySide6', 'shiboken6')),
            'pages': sorted(name for name in sys.modules if name == 'desktop_app.shell.pages' or name.startswith('desktop_app.shell.pages.')),
        }
        Path(proof_path).write_text(json.dumps(proof), encoding='utf-8')
    finally:
        sys.meta_path.remove(blocker)


class LayeredWorkerImportTests(unittest.TestCase):
    def test_actual_spawned_registrar_and_main_window_never_attempt_qt_or_pages(self):
        with tempfile.TemporaryDirectory(prefix='layered-import-') as directory:
            proof_path = Path(directory) / 'proof.json'
            child = multiprocessing.get_context('spawn').Process(target=guarded_registrar_import, args=(str(proof_path),))
            child.start()
            pid = child.pid
            try:
                child.join(10)
                self.assertFalse(child.is_alive(), 'registrar-only child did not stop within the original worker import bound')
                self.assertEqual(child.exitcode, 0)
                proof = json.loads(proof_path.read_text(encoding='utf-8'))
                self.assertEqual(proof, {'pid': pid, 'real_child': True, 'same_executor': True, 'gui_refused': True, 'attempts': [], 'qt': [], 'pages': []})
                self.assertNotEqual(pid, os.getpid())
            finally:
                if child.is_alive():
                    child.terminate()
                    child.join(5)
                child.close()


if __name__ == '__main__':
    unittest.main()
