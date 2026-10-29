"""Keep all desktop QSS application in the theme module."""

import ast
from pathlib import Path
import unittest
import tempfile
from tests.layered_source_fixtures import CURRENT_PATHS, physical_path, page_sources


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


def stylesheet_sources(root):
    """Project the original root/pages/smoke guard and scan every new desktop file."""
    moved = {root / new for new in CURRENT_PATHS.values()}
    projected = {root / new for old, new in CURRENT_PATHS.items() if not old.startswith('desktop_trading/') and (root / new).is_file()}
    additions = set((root / 'desktop_app').rglob('*.py')) - moved
    return sorted(projected | additions | set(root.glob('desktop*.py')) | set((root / 'tools').rglob('*.py')))


def stylesheet_violations(root):
    violations = []
    for path in stylesheet_sources(root):
        relative = path.relative_to(root).as_posix()
        if relative == 'desktop_app/shell/theme.py':
            continue
        for line in stylesheet_calls(path.read_text(encoding='utf-8-sig')):
            if (relative, line) not in STYLESHEET_ALLOWLIST:
                violations.append((relative, line))
    return violations


class NoInlineStylesheetTests(unittest.TestCase):
    def test_f6_memory_scanned(self):
        self.assertEqual(stylesheet_calls((ROOT / 'desktop_app/features/market/chart_memory.py').read_text(encoding='utf-8')), [])

    def test_f5_backup_inspection_scanned(self):
        path = ROOT / 'desktop_app/features/settings/backup_inspection.py'
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_f2_overlay_scanned(self):
        path = ROOT / 'desktop_app/features/compare/compare_equity.py'
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_f1_gap_widget_is_scanned(self):
        path = ROOT / 'desktop_app/features/data/data_gaps.py'
        self.assertTrue(path.is_file())
        self.assertEqual(stylesheet_calls(path.read_text(encoding='utf-8')), [])

    def test_quick_start_uses_theme_only(self):
        for name in ('quick_start.py', 'quick_start_chain.py'):
            self.assertEqual(stylesheet_calls((ROOT / physical_path('desktop_pages' + '/' + str(name))).read_text(encoding='utf-8')), [])

    def test_desktop_and_tools_have_no_inline_stylesheet(self):
        self.assertEqual(stylesheet_violations(ROOT), [])

    def test_original_scope_and_new_trading_sources_keep_their_classification(self):
        actual = set(stylesheet_sources(ROOT))
        prior = {ROOT / new for old, new in CURRENT_PATHS.items() if not old.startswith('desktop_trading/')}
        excluded = {ROOT / new for old, new in CURRENT_PATHS.items() if old.startswith('desktop_trading/')}
        self.assertEqual(len(excluded), 14)
        self.assertLessEqual(prior, actual)
        self.assertFalse(excluded & actual)
        self.assertEqual(STYLESHEET_ALLOWLIST, frozenset())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / CURRENT_PATHS['desktop_trading/dashboard.py']
            old.parent.mkdir(parents=True)
            old.write_text('widget.setStyleSheet("prior trading scope")', encoding='utf-8')
            self.assertEqual(stylesheet_violations(root), [])
            for relative in (
                'desktop_app/features/trading/unknown.py',
                'desktop_app/features/trading/nested/unknown.py',
                'desktop_app/components/nested/unknown.py',
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('widget.setStyleSheet("injected")', encoding='utf-8')
                self.assertIn(path, stylesheet_sources(root))
                self.assertIn((relative, 1), stylesheet_violations(root))

    def test_detector_rejects_synthetic_inline_calls(self):
        self.assertEqual(stylesheet_calls('widget.setStyleSheet("color:red")'), [1])
        self.assertEqual(stylesheet_calls('widget.setStyleSheet(\n theme\n)'), [1])
        self.assertEqual(stylesheet_calls('widget.setProperty("status", "danger")'), [])
        self.assertEqual(stylesheet_calls('# widget.setStyleSheet("ignored")'), [])

    def test_package_injection_is_detected(self):
        sources = page_sources(ROOT)
        self.assertTrue({'command_palette.py', 'palette_commands.py', 'backtest_summary_card.py'} <= {path.name for path in sources})
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(module=path.name):
                source = path.read_text(encoding='utf-8-sig')
                self.assertEqual(stylesheet_calls(source), [])
                self.assertTrue(stylesheet_calls(source + '\nwidget.setStyleSheet("color:red")\n'))
