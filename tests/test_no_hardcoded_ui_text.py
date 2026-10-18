"""Guard every top-level desktop UI module, including f-string text parts."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r'[\u3400-\u9fff\uff00-\uffef\u3000-\u303f]')
UI_MODULES = (
    'desktop_accessibility.py', 'desktop.py', 'desktop_automatic_backup.py', 'desktop_charts.py',
    'desktop_chatgpt_ui.py', 'desktop_forms.py', 'desktop_help.py', 'desktop_icon.py',
    'desktop_market.py', 'desktop_timeinput.py', 'desktop_expiry_inputs.py', 'desktop_presentation.py', 'desktop_recovery_smoke.py',
    'desktop_theme.py', 'desktop_ui.py', 'desktop_ui_polish.py', 'desktop_walk_forward.py',
)
UI_PACKAGE_MODULES = tuple(path.relative_to(ROOT).as_posix()
                           for path in sorted((ROOT / 'desktop_pages').rglob('*.py')))
# Migration debt must stay empty; every UI module is scanned below.
TODO_MODULES = {}
# These are not desktop UI modules. Keep the catalog and pinned non-UI sources
# outside the UI scan, without granting any per-literal exemptions.
NON_UI_MODULES = {
    'desktop_strings.py': 'The catalog is the intended home for UI text',
    'desktop_chatgpt_auth.py': 'Pinned authentication implementation, not UI',
    'desktop_chatgpt_provider.py': 'Pinned provider implementation, not UI',
    'desktop_tls_smoke.py': 'Command-line TLS diagnostic, not UI',
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
            if (isinstance(owner, ast.Name) and owner.id in ('logging', 'logger', 'log')
                    and node.func.attr in ('debug', 'info', 'warning', 'error', 'exception', 'critical', 'log')):
                for argument in (*node.args, *(item.value for item in node.keywords)):
                    ignored.update(ast.walk(argument))
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node not in ignored and CJK.search(node.value)
            and (filename, node.value) not in LITERAL_ALLOWLIST]


class HardcodedUITextTests(unittest.TestCase):
    def test_inventory_covers_all_desktop_modules(self):
        self.assertEqual({path.name for path in ROOT.glob('desktop*.py')},
                         set(UI_MODULES) | set(NON_UI_MODULES))
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
            for source in (f'label = {literal!r}', f'label = f"{literal}{{value}}"',
                           f'label = "\\u{ord(literal):04x}"'):
                with self.subTest(source=source):
                    self.assertTrue(hardcoded_ui_text(source))
        original = (ROOT / 'desktop_ui.py').read_text(encoding='utf-8-sig')
        self.assertTrue(hardcoded_ui_text(original + '\nlabel = "\u6e2c\u8a66"\n'))

    def test_package_injection_is_detected(self):
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
