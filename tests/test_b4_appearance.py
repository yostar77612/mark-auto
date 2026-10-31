"""B4: bounded, offline presentation checks; no displayed windows or style resets."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget, QScrollArea

import desktop_app.shell.theme as theme
from desktop_app.components.charts import CandlestickChart
from desktop_app.components.result_widgets import KpiCards, ResultTable
from quantlab.research_core.adapters.workspace_store import AppPaths
from desktop_app.research_bootstrap import create_job_manager
from quantlab.research_core.adapters.settings_store import SettingsStore
from tests.test_t9_onboarding import sandbox_ui

ROOT = Path(__file__).resolve().parents[1]


def contrast_ratio(first, second):
    def luminance(color):
        channels = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in (color.redF(), color.greenF(), color.blueF())]
        return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), channels))

    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def effective_background(widget):
    """Composite transparent card labels over their rendered ancestor color."""
    color = widget.palette().color(QPalette.ColorRole.Window)
    if color.alpha() == 255:
        return color
    parent = widget.parentWidget()
    behind = effective_background(parent) if parent is not None else QApplication.palette().color(QPalette.ColorRole.Window)
    alpha = color.alphaF()
    return QColor.fromRgbF(*(front * alpha + back * (1 - alpha) for front, back in zip(color.getRgbF()[:3], behind.getRgbF()[:3])))


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # The authorized redesign changes app cards, spacing, task selection and
    # focus rules. Keep an exact new app pin and the unchanged market pin.
    def test_default_stylesheets_match_reviewed_ui_bytes(self):
        for builder, digest in (
            (theme.build_app_stylesheet, 'f4bc1159f8d0113902449efb3a34e7340ba40a422037bbd379d82109cd053b2e'),
            (theme.build_market_stylesheet, '7ce3a6cb5bc9c2c0eab3fdffc4fc4139327db3a3e9c546661f1b0ef5cde205cf'),
        ):
            self.assertEqual(hashlib.sha256(builder().encode()).hexdigest(), digest)
            self.assertEqual(builder(), builder('dark'))
            self.assertNotEqual(builder(), builder('light'))
        for palette in theme.THEMES.values():
            self.assertEqual(set(palette), set(theme.COLORS))
        for name in theme.THEMES:
            stylesheet = theme.build_app_stylesheet(name)
            for selector in (
                'QFrame[designCard="true"]',
                'QToolButton[designDisclosure="true"]',
                'QPushButton[role="taskChoice"]:checked',
                'QPushButton:focus',
            ):
                self.assertIn(selector, stylesheet)

    def test_settings_roundtrip_unknown_and_corruption(self):
        with sandbox_ui(), tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder) / 'settings.json')
            self.assertEqual(theme.load_appearance(store), ('dark', 'red_up'))
            for name in theme.THEMES:
                for convention in theme.CONVENTIONS:
                    store.save({theme.THEME_KEY: name, theme.CONVENTION_KEY: convention, 'unrelated': 3})
                    self.assertEqual(theme.load_appearance(store), (name, convention))
            for invalid in (None, [], {}, 'unknown', 3):
                store.save({theme.THEME_KEY: invalid, theme.CONVENTION_KEY: invalid})
                self.assertEqual(theme.load_appearance(store), ('dark', 'red_up'))
            store.path.write_text('{bad json', encoding='utf-8')
            self.assertEqual(theme.load_appearance(store), ('dark', 'red_up'))
            self.assertEqual(store.path.read_text(encoding='utf-8'), '{bad json')
        self.assertEqual(theme.up_down_colors(), ('#ff6575', '#35cf9b'))
        self.assertEqual(theme.up_down_colors(context='market'), ('#f58b8b', '#76d6b0'))
        self.assertEqual(theme.up_down_colors('green_up'), theme.up_down_colors()[::-1])
        with self.assertRaises(ValueError):
            theme.up_down_colors('unknown')

    def test_transparent_label_contrast_uses_its_visible_card_background(self):
        card = QWidget()
        self.addCleanup(card.deleteLater)
        palette = card.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor('white'))
        card.setPalette(palette)
        label = QLabel('Contrast fixture', card)
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        label.setPalette(palette)
        self.assertEqual(effective_background(label), QColor('white'))
        self.assertAlmostEqual(contrast_ratio(QColor('black'), effective_background(label)), 21, places=4)
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 128))
        label.setPalette(palette)
        self.assertLessEqual(abs(effective_background(label).red() - 127), 1)

    def test_live_convention_candles_cells_pnl_market_and_legend(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        chart = CandlestickChart(host)
        table = ResultTable(host)
        table.set_rows([{'return': '0.2', 'net_pnl': '-12'}])
        kpis = KpiCards(('net_pnl',), host)
        kpis.set_values({'net_pnl': 12})
        market = QWidget(host)
        market.setObjectName('market_dashboard')
        label = QLabel('12', market)
        theme.set_financial_label(label, 12)
        for name in theme.THEMES:
            host.setProperty('appearanceTheme', name)
            for convention in theme.CONVENTIONS:
                host.setProperty('appearanceConvention', convention)
                theme.apply_theme(host)
                pair = theme.up_down_colors(convention, theme=name, context='market')
                self.assertEqual(chart.UP.name(), theme.up_down_colors(convention)[0])
                self.assertEqual(chart.DOWN.name(), theme.up_down_colors(convention)[1])
                self.assertEqual(table.item(0, 0).foreground().color().name(), pair[0])
                self.assertEqual(table.item(0, 1).foreground().color().name(), pair[1])
                label.ensurePolished()
                kpis.labels['net_pnl'].ensurePolished()
                self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).name(), pair[0])
                self.assertEqual(
                    kpis.labels['net_pnl'].palette().color(QPalette.ColorRole.WindowText).name(),
                    theme.up_down_colors(convention, theme=name, context='status')[0],
                )
                self.assertEqual(
                    theme.chart_legend(chart), theme.ui_text('charts.paint_event.legend' if convention == 'red_up' else 'appearance.legend.green_up')
                )

    def test_chart_offscreen_background_and_palette(self):
        chart = CandlestickChart()
        self.addCleanup(chart.deleteLater)
        chart.resize(360, 280)
        pixels = []
        for name in theme.THEMES:
            chart.setProperty('appearanceTheme', name)
            theme.apply_theme(chart)
            pixels.append(chart.grab().toImage().pixelColor(0, 0).name())
            self.assertEqual(pixels[-1], theme.CHART_COLORS[name]['background'])
        self.assertNotEqual(*pixels)

    def test_theme_change_keeps_styles_and_ui_text_centralized(self):
        from tests.test_no_inline_stylesheet import NoInlineStylesheetTests
        from tests.test_no_hardcoded_ui_text import HardcodedUITextTests

        NoInlineStylesheetTests().test_desktop_and_tools_have_no_inline_stylesheet()
        HardcodedUITextTests().test_ui_modules_have_no_hardcoded_text()


class AppearanceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from desktop_app.shell.window import MainWindow

        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)
        cls.folder = tempfile.TemporaryDirectory(prefix='b4-appearance-')
        cls.addClassCleanup(cls.folder.cleanup)
        cls.paths = AppPaths(Path(cls.folder.name) / 'workspace').ensure()
        cls.jobs = create_job_manager(cls.paths)
        cls.addClassCleanup(cls.jobs.close)
        cls.store = SettingsStore(cls.paths.state / 'settings.json')
        cls.window = MainWindow(cls.paths, cls.jobs, cls.store, services=_c_create_ui_services(_c_create_operation_ports()))
        cls.addClassCleanup(cls.window.deleteLater)
        cls.addClassCleanup(cls.window.close)
        for timer in cls.window.findChildren(QTimer):
            timer.stop()

    def tearDown(self):
        self.window.findChild(QComboBox, 'appearance_theme').setCurrentIndex(0)
        self.window.findChild(QComboBox, 'appearance_convention').setCurrentIndex(0)

    def test_settings_controls_apply_and_persist_without_restart(self):
        w = self.window
        old = w.styleSheet()
        w.findChild(QComboBox, 'appearance_theme').setCurrentIndex(1)
        self.assertNotEqual(w.styleSheet(), old)
        self.assertEqual(w.styleSheet(), theme.build_app_stylesheet('light'))
        self.assertEqual(w.market.styleSheet(), theme.build_market_stylesheet('light'))
        self.assertEqual(theme.load_appearance(self.store), ('light', 'red_up'))
        w.findChild(QComboBox, 'appearance_convention').setCurrentIndex(1)
        self.assertEqual(theme.load_appearance(self.store), ('light', 'green_up'))
        self.assertEqual(theme.appearance(w.market.chart), ('light', 'green_up'))
        self.assertEqual(self.store.load()[theme.CONVENTION_KEY], 'green_up')

    def test_public_names_and_size_limits_unchanged(self):
        import ast
        from tests.test_ui_operations_registry import RegistryTests

        RegistryTests().test_public_names_unchanged()
        expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted({w.objectName() for w in [self.window, *self.window.findChildren(QWidget)] if w.objectName()}), expected)
        tree = ast.parse((ROOT / 'desktop_app/shell/window.py').read_text(encoding='utf-8'))
        window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
        self.assertLessEqual(window.end_lineno - window.lineno + 1, 400)

    def test_all_pages_theme_accessibility_and_layout(self):
        from desktop_app.shell.accessibility import INTERACTIVE, semantic_name, visual_focus_order
        from tests.test_scaled_layouts import layout_defects
        from tests.snapshot_cache import default_metrics

        started = time.perf_counter()
        metrics = default_metrics()
        self.assertEqual(len(metrics['pages']), 7)
        self.assertTrue(all(not p['unlabeled_inputs'] for p in metrics['pages'].values()))
        baseline = json.loads((ROOT / 'tests/fixtures/desktop_pages_before/metrics.json').read_text(encoding='utf-8'))
        redesigned = json.loads((ROOT / 'tests/fixtures/ui_redesign_empty_presentation.json').read_text(encoding='utf-8'))
        # Heights and font metrics are platform-dependent (the archive is Windows); compare the platform-independent facts.
        self.assertEqual(list(metrics['pages']), list(baseline['pages']))
        self.assertEqual(list(metrics['pages']), list(redesigned['pages']))
        for page_name, expected in redesigned['pages'].items():
            for field in (
                'visible_input_count',
                'button_count',
                'label_char_count',
                'unlabeled_inputs',
                'primary_button_count',
                'combo_items',
                'table_headers',
            ):
                self.assertEqual(metrics['pages'][page_name][field], expected[field], (page_name, field))
            self.assertEqual(
                [t.replace(chr(92), '/') for t in metrics['pages'][page_name]['visible_text']],
                [t.replace(chr(92), '/') for t in expected['visible_text']],
                page_name,
            )
        w = self.window
        for name in theme.THEMES:
            w.findChild(QComboBox, 'appearance_theme').setCurrentIndex(list(theme.THEMES).index(name))
            for index in range(7):
                w.navigation.setCurrentRow(index)
                page = w.stack.currentWidget()
                if isinstance(page, QScrollArea):
                    page = page.widget()
                page.ensurePolished()
                page.resize(1100, max(720, page.sizeHint().height()))
                if page.layout():
                    page.layout().activate()
                self.assertEqual(layout_defects(page)[0], [], (name, index))
                for control in visual_focus_order(page):
                    self.assertTrue(semantic_name(control), control.objectName())
                for control in page.findChildren(QWidget):
                    if isinstance(control, INTERACTIVE):
                        self.assertTrue(control.accessibleName(), control.objectName())
                    if isinstance(control, QLabel) and control.text() and control.isVisibleTo(page) and control.isEnabled():
                        control.ensurePolished()
                        palette = control.palette()
                        self.assertGreaterEqual(
                            contrast_ratio(palette.color(QPalette.ColorRole.WindowText), effective_background(control)),
                            4.5,
                            (name, index, control.objectName(), control.text()),
                        )
        print(f'B4 seven-page walk wall_seconds={time.perf_counter() - started:.3f}')
