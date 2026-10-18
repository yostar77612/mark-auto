"""Keep all desktop QSS application in the theme module."""
import ast
from pathlib import Path
import unittest


# QPainter chart drawing uses no setStyleSheet calls, so no exceptions are needed.
STYLESHEET_ALLOWLIST = frozenset()
# The market dashboard keeps a widget-scoped dark theme (applied by desktop_theme.apply_market_theme)
# so it renders identically when hosted standalone, outside the main window's application theme.
WIDGET_STYLESHEET_ALLOWLIST = frozenset({'market_dashboard'})
ROOT = Path(__file__).resolve().parents[1]


def stylesheet_calls(source):
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'setStyleSheet']


class NoInlineStylesheetTests(unittest.TestCase):
    def test_desktop_and_tools_have_no_inline_stylesheet(self):
        sources = sorted(set(ROOT.glob('desktop*.py')) | set((ROOT/'tools').rglob('*.py')) | set((ROOT/'desktop_pages').rglob('*.py')))
        violations = []
        for path in sources:
            relative = path.relative_to(ROOT).as_posix()
            if relative == 'desktop_theme.py':
                continue
            for line in stylesheet_calls(path.read_text(encoding='utf-8-sig')):
                if (relative, line) not in STYLESHEET_ALLOWLIST:
                    violations.append((relative, line))
        self.assertEqual(violations, [])

    def test_detector_rejects_synthetic_inline_calls(self):
        self.assertEqual(stylesheet_calls('widget.setStyleSheet("color:red")'), [1])
        self.assertEqual(stylesheet_calls('widget.setStyleSheet(\n theme\n)'), [1])
        self.assertEqual(stylesheet_calls('widget.setProperty("status", "danger")'), [])
        self.assertEqual(stylesheet_calls('# widget.setStyleSheet("ignored")'), [])

    def test_package_injection_is_detected(self):
        sources = sorted((ROOT / 'desktop_pages').rglob('*.py'))
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(module=path.name):
                self.assertTrue(stylesheet_calls(path.read_text(encoding='utf-8-sig')
                                                 + '\nwidget.setStyleSheet("color:red")\n'))
