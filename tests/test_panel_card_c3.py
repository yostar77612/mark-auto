"""Offscreen structural and palette contracts; no raster or platform metrics."""

import ast
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from desktop_pages.widgets import PANEL_TITLE_HEIGHT, PanelCard
from desktop_pages.market import MarketPage
from desktop_pages.paper import PaperPage
from desktop_pages.widgets import WidgetTools
from desktop_strings import ui_text
from desktop_theme import apply_theme, build_app_stylesheet, theme_colors
import desktop_theme as theme_module
from quantlab.paper import RiskLimits
from tests.test_b4_appearance import contrast_ratio


class PolishCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.StyleChange:
            self.count += 1
        return False


class PanelCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def keep(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget

    def test_controls_keep_order_and_right_edge_at_two_widths(self):
        panel = self.keep(PanelCard(ui_text('ui.paper_page.snapshot_advanced')))
        controls = [QPushButton(ui_text('async.retry')), QPushButton(ui_text('async.refresh'))]
        for control in controls:
            control.setFixedSize(40, 22)
            panel.add_control(control)
        offsets = []
        for width in (320, 640):
            panel.resize(width, 140)
            panel.layout().activate()
            panel.title_bar.layout().activate()
            panel.controls.layout().activate()
            self.assertEqual(panel.title_bar.height(), PANEL_TITLE_HEIGHT)
            self.assertEqual([panel.controls.layout().itemAt(i).widget() for i in range(2)], controls)
            self.assertLess(controls[0].geometry().right(), controls[1].x())
            offsets.append(panel.title_bar.width() - panel.controls.geometry().right())
        self.assertEqual(offsets[0], offsets[1])
        self.assertTrue(panel.controls.objectName())
        empty = self.keep(PanelCard())
        self.assertEqual(empty.title_label.title(), '')
        self.assertTrue(empty.title_bar.accessibleName())
        self.assertTrue(empty.controls.accessibleName())
        label = QLabel(ui_text('ui.paper_page.policy_advanced'))
        empty.content_layout().addWidget(label)
        self.assertIs(label.parentWidget(), empty.content)

    def test_theme_switch_resolves_selectors_and_preserves_group_title_contrast(self):
        panel = self.keep(PanelCard(ui_text('ui.paper_page.policy_advanced')))
        observer = PolishCounter()
        panel.installEventFilter(observer)
        for theme in ('dark', 'light', 'dark'):
            panel.setProperty('appearanceTheme', theme)
            with patch('desktop_theme.set_theme_property', wraps=theme_module.set_theme_property) as refresh:
                apply_theme(panel)
                self.assertTrue(any(call.args[0] is panel for call in refresh.call_args_list))
            panel.ensurePolished()
            panel.title_bar.ensurePolished()
            panel.title_label.ensurePolished()
            colors = theme_colors(panel)
            title_color = panel.title_label.palette().color(QPalette.ColorRole.WindowText)
            background = panel.title_bar.palette().color(QPalette.ColorRole.Window)
            self.assertEqual(title_color, QColor(colors['text']))
            self.assertEqual(background, QColor(colors['background']))
            # e0e604f market group titles used these same theme tokens.
            baseline = contrast_ratio(QColor(colors['text']), QColor(colors['background']))
            self.assertGreaterEqual(contrast_ratio(title_color, background), baseline)
            self.assertGreaterEqual(contrast_ratio(title_color, background), 4.5)
            stylesheet = build_app_stylesheet(theme)
            self.assertNotIn('@', stylesheet)
            for part in ('panelCard', 'panelTitleBar', 'panelTitle'):
                self.assertIn('themePart="' + part + '"', stylesheet)
        self.assertGreaterEqual(observer.count, 3)

    def test_pages_build_without_show_using_namespace_hosts_and_keep_existing_names(self):
        state = SimpleNamespace(_section_toggles={}, _advanced_values={}, actions=[], stack=self.keep(QStackedWidget()))
        host = SimpleNamespace(
            state=state, callbacks={'paper_risk_limits': lambda: RiskLimits(1, 1, Decimal('100'), 30)}, mount_page=lambda page, title: QVBoxLayout(page)
        )
        tools = WidgetTools(host)
        for name in ('_advanced', '_button', '_text', '_remember'):
            setattr(host, name, getattr(tools, name))
        paper = self.keep(PaperPage(host))
        market = self.keep(MarketPage(SimpleNamespace(state=state, mount_market=lambda page, title: None)))
        for page, count in ((market, 6), (paper, 2)):
            self.assertGreaterEqual(len(page.findChildren(PanelCard)), count)
            for theme in ('dark', 'light'):
                page.setProperty('appearanceTheme', theme)
                apply_theme(page)
                for panel in page.findChildren(PanelCard):
                    self.assertTrue(panel.title_bar.accessibleName())
                    self.assertTrue(panel.controls.accessibleName())
                    panel.title_bar.ensurePolished()
                    panel.title_label.ensurePolished()
                    colors = theme_colors(panel)
                    foreground = panel.title_label.palette().color(QPalette.ColorRole.WindowText)
                    background = panel.title_bar.palette().color(QPalette.ColorRole.Window)
                    self.assertEqual(foreground, QColor(colors['text']))
                    self.assertEqual(background, QColor(colors['background']))
                    self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5)
        for name in ('paper_submit', 'paper_fixed_risk_summary', 'paper_positions_results', 'paper_orders_results', 'paper_fills_results'):
            self.assertIsNotNone(paper.findChild(QWidget, name), name)
        for name in ('market_card_TAIEX', 'market_card_TX', 'market_card_MXF', 'market_card_TMF', 'market_state_risk', 'market_indicator_MA'):
            self.assertIsNotNone(market.findChild(QWidget, name), name)
        # Help relocation moves the whole section through an existing child's
        # parent. An intermediate content QWidget strands the visible title.
        for child in (market.trading_labels['strategy'], market._indicator_widgets['MA'][0]):
            self.assertIsInstance(child.parentWidget(), PanelCard)
            section = child.parentWidget()
            section.hide()
            self.assertFalse(section.title_bar.isVisibleTo(market))
        fixture = json.loads((Path(__file__).parent / 'fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        for panel in paper.findChildren(PanelCard):
            for widget in (panel, panel.title_bar, panel.title_label, panel.controls, panel.content):
                self.assertIn(widget.objectName(), fixture)

    def test_hosted_page_class_budgets(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / 'desktop_pages').glob('*.py'):
            for node in ast.parse(path.read_text(encoding='utf-8')).body:
                if isinstance(node, ast.ClassDef) and node.name.endswith('Page'):
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 500, node.name)
