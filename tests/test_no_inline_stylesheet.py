"""Keep all desktop QSS application in the theme module."""
import ast
from pathlib import Path
import unittest


# QPainter chart drawing uses no setStyleSheet calls, so no exceptions are needed.
STYLESHEET_ALLOWLIST = frozenset()
WIDGET_STYLESHEET_ALLOWLIST = frozenset()
ROOT = Path(__file__).resolve().parents[1]


def stylesheet_calls(source):
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'setStyleSheet']


class NoInlineStylesheetTests(unittest.TestCase):
    def test_desktop_and_tools_have_no_inline_stylesheet(self):
        sources = sorted(set(ROOT.glob('desktop*.py')) | set((ROOT/'tools').rglob('*.py')))
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
