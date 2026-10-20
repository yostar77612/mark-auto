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
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'setStyleSheet'
    ]


class NoInlineStylesheetTests(unittest.TestCase):
    def test_f6_memory_scanned(self):
        self.assertEqual(stylesheet_calls((ROOT / 'desktop_chart_memory.py').read_text(encoding='utf-8')), [])

    def test_f5_backup_inspection_scanned(self):
        path = ROOT / 'desktop_pages/backup_inspection.py'
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_f2_overlay_scanned(self):
        path = ROOT / 'desktop_pages/compare_equity.py'
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_f1_gap_widget_is_scanned(self):
        path = ROOT / 'desktop_pages/data_gaps.py'
        self.assertTrue(path.is_file())
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_quick_start_uses_theme_only(self):
        for name in ('quick_start.py', 'quick_start_chain.py'):
            self.assertEqual(stylesheet_calls((ROOT / 'desktop_pages' / name).read_text(encoding='utf-8')), [])

    def test_desktop_and_tools_have_no_inline_stylesheet(self):
        sources = sorted(
            set(ROOT.glob('desktop*.py'))
            | set((ROOT / 'tools').rglob('*.py'))
            | set((ROOT / 'desktop_pages').rglob('*.py'))
            | set((ROOT / 'desktop_smoke').rglob('*.py'))
        )
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
        self.assertTrue({'command_palette.py', 'palette_commands.py', 'backtest_summary_card.py'} <= {path.name for path in sources})
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(module=path.name):
                self.assertTrue(stylesheet_calls(path.read_text(encoding='utf-8-sig') + '\nwidget.setStyleSheet("color:red")\n'))
