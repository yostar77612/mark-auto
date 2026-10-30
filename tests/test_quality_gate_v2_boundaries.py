"""V2 capability upgrades cannot relax any existing research prohibition."""

import unittest

from tools.quality_gate import V2_PROCESS_OWNER, V2_SDK_LOADER, python_findings
from tools.check_trading_architecture import check_source


class V2ImportBoundaryTests(unittest.TestCase):
    def test_independent_layer_gate_only_allows_explicit_loader_and_version_metadata(self):
        source = "def load_pinned_sdk():\n import shioaji\n version = getattr(shioaji, '__version__', None)\n return shioaji\n"
        self.assertEqual(check_source(source, V2_SDK_LOADER), ())
        for label in ('quantlab/trading/adapters/shioaji/other.py', 'quantlab/trading/domain/new.py', 'quantlab/trading/application/new.py'):
            with self.subTest(label=label):
                self.assertTrue(check_source(source, label))

    def test_independent_layer_gate_rejects_client_construction_and_other_sdk_access_in_loader(self):
        for expression in (
            "shioaji.Shioaji()",
            "getattr(shioaji, 'Shioaji')()",
            "shioaji.login",
            "getattr(shioaji, field)",
            "vars(shioaji)['Shioaji']()",
            "locals()['shioaji'].Shioaji()",
            "getattr(shioaji, '__version__')()",
        ):
            source = 'def load_pinned_sdk():\n import shioaji\n return ' + expression + '\n'
            with self.subTest(expression=expression):
                self.assertTrue(check_source(source, V2_SDK_LOADER))
        self.assertTrue(check_source('import shioaji\nversion = shioaji.__version__', V2_SDK_LOADER))
        for mutation in ("shioaji.__version__ = '1.7.9'", "setattr(shioaji, '__version__', '1.7.9')", "delattr(shioaji, '__version__')"):
            with self.subTest(mutation=mutation):
                self.assertTrue(check_source('def load_pinned_sdk():\n import shioaji\n ' + mutation + '\n', V2_SDK_LOADER))

    def test_only_explicit_top_level_adapter_loader_may_lazily_import_pinned_sdk(self):
        source = 'def load_pinned_sdk():\n import shioaji\n return shioaji\n'
        self.assertEqual(python_findings(source, V2_SDK_LOADER, research=True), [])
        for label in (
            'quantlab/research.py',
            'quantlab/new.py',
            'quantlab/trading/domain/new.py',
            'quantlab/trading/runtime/broker.py',
            V2_SDK_LOADER + '.backup',
        ):
            with self.subTest(label=label):
                self.assertTrue(python_findings(source, label, research=True))

    def test_sdk_import_cannot_move_to_module_scope_other_function_or_submodule(self):
        for source in (
            'import shioaji',
            'def implicit_startup():\n import shioaji\n',
            'class Hidden:\n def load_pinned_sdk(self):\n  import shioaji\n',
            'async def load_pinned_sdk():\n import shioaji\n',
            'def load_pinned_sdk():\n from shioaji import API\n',
            'def load_pinned_sdk():\n import shioaji.internal\n',
        ):
            with self.subTest(source=source):
                self.assertTrue(python_findings(source, V2_SDK_LOADER, research=True))

    def test_process_import_is_only_for_the_one_runtime_owner(self):
        self.assertEqual(python_findings('import subprocess', V2_PROCESS_OWNER, research=True), [])
        for label in ('quantlab/research.py', 'quantlab/trading/domain/new.py', 'quantlab/trading/runtime/other.py', V2_SDK_LOADER):
            with self.subTest(label=label):
                self.assertTrue(python_findings('import subprocess', label, research=True))

    def test_both_authorized_boundaries_retain_all_other_bans(self):
        for label in (V2_SDK_LOADER, V2_PROCESS_OWNER):
            for source in ('import pickle', 'import trader', 'import archives', "eval('1')", "exec('1')", "compile('1', '', 'exec')", "__import__('shioaji')"):
                with self.subTest(label=label, source=source):
                    self.assertTrue(python_findings(source, label, research=True))
        self.assertTrue(python_findings('from PySide6.QtWidgets import QWidget', V2_SDK_LOADER, research=True))
        self.assertTrue(python_findings('import shioaji', 'desktop_app/shell/main_window.py', desktop=True))
