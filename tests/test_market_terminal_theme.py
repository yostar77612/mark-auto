"""Scoped terminal selectors preserve dynamic theme, convention and muted states."""

from dataclasses import replace
from decimal import Decimal
import time
import unittest

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
import shiboken6

from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.workspace import WorkspacePanel
from desktop_app.features.trading.market_terminal import MarketTerminalWidget
from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
from desktop_app.shell import theme
from quantlab.research_core.adapters.market_layout import LayoutStore
from quantlab.trading.domain.watch import FIXED_INDICES
from tests.test_market_terminal_ui import FakeFacade, STOCK, quote


class TerminalThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.host.setProperty('appearanceTheme', 'light')
        self.host.setProperty('appearanceConvention', 'red_up')
        self.facade = FakeFacade((STOCK.instrument_id,))
        self.widget = MarketTerminalWidget(
            self.facade,
            CandlestickChart(),
            self.facade.state,
            self.host,
            layout_store=LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset()),
            index_chart=CandlestickChart(show_volume=False),
            panel_factory=WorkspacePanel,
            colours=lambda widget: theme.up_down_colors(theme.appearance(widget)[1], theme=theme.appearance(widget)[0], context='market'),
            style_terminal=theme._apply_terminal_theme,
        )
        QVBoxLayout(self.host).addWidget(self.widget)
        self.widget.select_instrument(STOCK.instrument_id)
        self.host.resize(1366, 768)
        self.host.show()
        deadline = time.monotonic() + 3
        while self.widget._requests and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.widget._requests)

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(3000)
        self.app.processEvents()
        shiboken6.delete(self.host)
        self.app.processEvents()

    def colour(self, widget):
        widget.ensurePolished()
        return widget.palette().color(QPalette.ColorRole.WindowText).name()

    def test_live_theme_and_convention_update_labels_and_table_without_new_market_data(self):
        index = replace(quote(FIXED_INDICES[0]), change=Decimal('-1'))
        self.widget.render(replace(self.facade.state, market_watch=(quote(), index)))
        for name in ('dark', 'light'):
            self.host.setProperty('appearanceTheme', name)
            for convention in ('red_up', 'green_up'):
                with self.subTest(theme=name, convention=convention):
                    self.host.setProperty('appearanceConvention', convention)
                    theme.apply_theme(self.host)
                    rise, fall = theme.up_down_colors(convention, theme=name, context='market')
                    self.assertEqual(self.colour(self.widget.title), rise)
                    self.assertEqual(self.colour(self.widget.index_title), fall)
                    self.assertEqual(self.widget.table.item(0, 2).foreground().color().name(), rise)
                    self.assertEqual(self.widget.index_table.item(0, 2).foreground().color().name(), fall)
                    self.assertEqual(self.colour(self.widget.freshness), theme.THEMES[name]['success'])

    def test_freshness_and_unknown_financial_values_use_muted_style(self):
        for name in ('dark', 'light'):
            self.host.setProperty('appearanceTheme', name)
            for freshness in ('DELAYED', 'STOPPED', 'CLOSED', 'UNKNOWN'):
                with self.subTest(theme=name, freshness=freshness):
                    view = replace(quote(freshness=freshness), price=None, change=None, change_percent=None)
                    self.widget.render(replace(self.facade.state, market_watch=(view,)))
                    theme.apply_theme(self.host)
                    expected = theme.THEMES[name]['warning' if freshness == 'DELAYED' else 'disabled_text']
                    self.assertEqual(self.colour(self.widget.freshness), expected)
                    self.assertEqual(self.widget.table.item(0, 2).foreground().color().name(), '#808080')
                    self.assertEqual(self.widget.title.property('terminalDirection'), 'FLAT')
                    self.assertEqual(self.colour(self.widget.title), self.widget.palette().text().color().name())

    def test_period_style_is_scoped_and_existing_control_names_remain(self):
        for name, button in self.widget.period_buttons.items():
            self.assertTrue(button.property('terminalPeriod'))
            self.assertEqual(button.objectName(), 'watch_period_' + name)
            self.assertTrue(button.accessibleName())
            self.assertEqual(button.styleSheet(), '')
        stylesheet = self.widget.styleSheet()
        self.assertIn('QWidget#market_terminal QPushButton[terminalPeriod="true"]:checked', stylesheet)
        self.assertNotIn('@', stylesheet)
        self.assertEqual(self.widget.freshness.styleSheet(), '')
        self.assertEqual(self.widget.title.styleSheet(), '')
        self.assertEqual(self.widget.index_title.styleSheet(), '')


if __name__ == '__main__':
    unittest.main()
