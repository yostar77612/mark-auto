"""Guard every top-level desktop UI module, including f-string text parts."""

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r'[\u3400-\u9fff\uff00-\uffef\u3000-\u303f]')
UI_MODULES = (
    'desktop_app/features/capital_scenario/worker.py',
    'desktop_app/components/privacy.py',
    'desktop_app/shell/accessibility.py',
    'desktop.py',
    'desktop_app/features/settings/automatic_backup.py',
    'desktop_app/components/charts.py',
    'desktop_app/features/market/chart_memory.py',
    'desktop_app/features/paper/order_lines.py',
    'desktop_app/features/assistant/connection.py',
    'desktop_app/features/assistant/states.py',
    'desktop_app/components/forms.py',
    'desktop_app/components/help.py',
    'desktop_app/components/icon.py',
    'desktop_app/features/market/dashboard.py',
    'quantlab/research_core/adapters/market_layout.py',
    'desktop_app/features/market/workspace.py',
    'desktop_app/features/market/chart_popout.py',
    'desktop_app/components/timeinput.py',
    'desktop_app/components/expiry_inputs.py',
    'desktop_app/components/formatting.py',
    'desktop_app/smoke/recovery.py',
    'desktop_app/research_session.py',
    'desktop_app/shell/theme.py',
    'desktop_app/shell/main_window.py',
    'desktop_app/shell/polish.py',
    'desktop_app/features/walk_forward/presenter.py',
)
UI_PACKAGE_MODULES = tuple(
    path.relative_to(ROOT).as_posix()
    for path in sorted(
        path
        for package in ('desktop_app',)
        for path in (ROOT / package).rglob('*.py')
        if not path.relative_to(ROOT).as_posix().startswith('desktop_app/strings/') and path.relative_to(ROOT).as_posix() != 'desktop_app/smoke/tls.py'
    )
)
# Migration debt must stay empty; every UI module is scanned below.
TODO_MODULES = {}
# These are not desktop UI modules. Keep the catalog and pinned non-UI sources
# outside the UI scan, without granting any per-literal exemptions.
NON_UI_MODULES = {
    'desktop_app/strings/catalog.py': 'The catalog is the intended home for UI text',
    'quantlab/assistant/adapters/chatgpt/auth.py': 'Pinned authentication implementation, not UI',
    'quantlab/assistant/adapters/chatgpt/provider.py': 'Pinned provider implementation, not UI',
    'desktop_app/smoke/tls.py': 'Command-line TLS diagnostic, not UI',
}
LITERAL_ALLOWLIST = {}  # No exceptions needed by migrated UI modules.


def hardcoded_ui_text(source, filename='<injected>'):
    """Return (line, literal) findings; exempt true docstrings/log arguments."""
    tree = ast.parse(source, filename=filename, feature_version=(3, 11))
    ignored = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ignored.add(value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                isinstance(owner, ast.Name)
                and owner.id in ('logging', 'logger', 'log')
                and node.func.attr in ('debug', 'info', 'warning', 'error', 'exception', 'critical', 'log')
            ):
                for argument in (*node.args, *(item.value for item in node.keywords)):
                    ignored.update(ast.walk(argument))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in ignored
        and CJK.search(node.value)
        and (filename, node.value) not in LITERAL_ALLOWLIST
    ]


class HardcodedUITextTests(unittest.TestCase):
    def test_f5_inspection_is_in_package_inventory(self):
        self.assertIn('desktop_app/features/settings/backup_inspection.py', UI_PACKAGE_MODULES)

    def test_f2_overlay_registered(self):
        self.assertIn('desktop_app/features/compare/compare_equity.py', UI_PACKAGE_MODULES)

    def test_quick_start_catalog_inventory(self):
        self.assertIn('desktop_app/features/onboarding/quick_start.py', UI_PACKAGE_MODULES)
        self.assertIn('desktop_app/features/onboarding/quick_start_chain.py', UI_PACKAGE_MODULES)

    def test_backtest_summary_u4_in_ui_catalog_scan(self):
        self.assertIn('desktop_app/features/backtest/backtest_summary_card.py', UI_PACKAGE_MODULES)

    def test_manifest_d12_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/assistant_manifest.py', UI_PACKAGE_MODULES)

    def test_assistant_d10_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/assistant_models.py', UI_PACKAGE_MODULES)

    def test_assistant_d6_module_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/assistant_completion.py', UI_PACKAGE_MODULES)

    def test_connection_d9_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/connection_test.py', UI_PACKAGE_MODULES)

    def test_assistant_d8_permissions_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/assistant_permissions.py', UI_PACKAGE_MODULES)

    def test_assistant_d5_details_in_inventory(self):
        self.assertIn('desktop_app/features/assistant/assistant_details.py', UI_PACKAGE_MODULES)

    def test_assistant_d4_package_modules_in_inventory(self):
        self.assertTrue({'desktop_app/features/assistant/assistant.py', 'desktop_app/features/assistant/worker.py'} <= set(UI_PACKAGE_MODULES))

    def test_c6_modules_registered(self):
        self.assertIn('desktop_app/features/paper/paper_tabs.py', UI_PACKAGE_MODULES)
        self.assertEqual(hardcoded_ui_text((ROOT / 'quantlab/paper_tab_data.py').read_text(encoding='utf-8')), [])

    def test_f1_gap_widget_registered(self):
        self.assertIn('desktop_app/features/data/data_gaps.py', UI_PACKAGE_MODULES)

    def test_inventory_covers_all_desktop_modules(self):
        actual = {path.relative_to(ROOT).as_posix() for path in ROOT.glob('desktop*.py')} | {
            path.relative_to(ROOT).as_posix() for path in (ROOT / 'desktop_app').rglob('*.py')
        }
        actual |= {
            path
            for path in (
                'quantlab/assistant/adapters/chatgpt/auth.py',
                'quantlab/assistant/adapters/chatgpt/provider.py',
                'quantlab/research_core/adapters/market_layout.py',
            )
            if (ROOT / path).is_file()
        }
        shared = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'desktop_app/strings').rglob('*.py')}
        self.assertEqual(actual, set(UI_MODULES) | set(UI_PACKAGE_MODULES) | set(NON_UI_MODULES) | shared)
        self.assertEqual(TODO_MODULES, {})
        self.assertFalse(set(UI_MODULES) & set(NON_UI_MODULES))

    def test_ui_modules_have_no_hardcoded_text(self):
        findings = []
        for name in (*UI_MODULES, *UI_PACKAGE_MODULES):
            current = hardcoded_ui_text((ROOT / name).read_text(encoding='utf-8-sig'), name)
            findings.extend((name, line, text) for line, text in current)
        self.assertEqual(findings, [])

    def test_injected_literals_are_detected(self):
        for literal in ('\u4e2d', '\u3400', '\uff01', '\u3001'):
            for source in (f'label = {literal!r}', f'label = f"{literal}{{value}}"', f'label = "\\u{ord(literal):04x}"'):
                with self.subTest(source=source):
                    self.assertTrue(hardcoded_ui_text(source))
        original = (ROOT / 'desktop_app/shell/main_window.py').read_text(encoding='utf-8-sig')
        self.assertTrue(hardcoded_ui_text(original + '\nlabel = "\u6e2c\u8a66"\n'))

    def test_package_injection_is_detected(self):
        self.assertIn('desktop_app/components/command_palette.py', UI_PACKAGE_MODULES)
        self.assertIn('desktop_app/shell/palette_commands.py', UI_PACKAGE_MODULES)
        self.assertIn('desktop_app/components/async_status.py', UI_PACKAGE_MODULES)
        self.assertIn('desktop_app/shell/app_header.py', UI_PACKAGE_MODULES)
        self.assertTrue(UI_PACKAGE_MODULES)
        for name in UI_PACKAGE_MODULES:
            source = (ROOT / name).read_text(encoding='utf-8-sig')
            with self.subTest(module=name):
                self.assertTrue(hardcoded_ui_text(source + '\nlabel = "\u6e2c\u8a66"\n', name))

    def test_only_docstrings_and_logging_are_exempt(self):
        self.assertEqual(hardcoded_ui_text('"\u8aaa\u660e"\nlogger.info("\u65e5\u8a8c")'), [])
        self.assertTrue(hardcoded_ui_text('widget.info("\u6587\u5b57")'))
        self.assertTrue(hardcoded_ui_text('value = "\u6587\u5b57"'))


if __name__ == '__main__':
    unittest.main()
