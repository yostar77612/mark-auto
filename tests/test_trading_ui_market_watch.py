"""Host-offscreen workspace wiring and control reachability, not native visual QA.

Market calculations and settings persistence belong to their existing tests.
"""

from dataclasses import replace
from decimal import Decimal
import time
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop_app.components.charts import CandlestickChart
from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.market_watch import MarketWatchWidget
from quantlab.trading.application.contracts import OrderView
from quantlab.trading.domain.models import QuantityUnit, Side
from tests.test_market_watch_ui import FakeFacade, view
from tests.test_trading_ui import state_fixture


class MarketWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = FakeFacade()
        self.facade.state = replace(
            state_fixture(),
            watchlist=('TMF', 'TX'),
            market_watch=(view(), view(instrument='TX')),
            orders=(OrderView('order-1', 'TMF', Side.BUY, 1, 0, QuantityUnit.CONTRACT, 'ACCEPTED', False),),
        )
        self.watch = MarketWatchWidget(self.facade, CandlestickChart(), self.facade.state)
        self.window = TradingWindow(self.facade, self.facade.state, market_watch=self.watch)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.wait_for(lambda: not self.watch._series_loading)

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(condition())
        self.app.processEvents()

    def tearDown(self):
        self.wait_for(lambda: self.window._operation is None and not self.watch._series_loading)
        QThreadPool.globalInstance().waitForDone(3000)
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_market_only_poll_updates_panels_and_retains_all_table_selections(self):
        tables = (self.window.strategies, self.window.positions, self.window.orders, self.window.markets, self.watch.table)
        for table in tables:
            table.selectRow(table.rowCount() - 1)
        selected = [table.selectedItems() for table in tables]
        spies = [(QSignalSpy(table.model().modelReset), QSignalSpy(table.model().dataChanged)) for table in tables[:4]]
        self.facade.page = replace(self.facade.page, market_revision=1, bars=(replace(self.facade.page.bars[0], close=Decimal('102')),))
        self.facade.state = replace(
            self.facade.state,
            market_revision=1,
            market_watch=(view(), replace(view(instrument='TX'), bid=Decimal('777'), price=Decimal('778'))),
            market_connection='DISCONNECTED',
        )
        before = len(self.facade.queries)
        header_before = self.watch.header.text()
        self.assertEqual(self.window.poll.interval(), 1000)
        self.window.poll.timeout.emit()
        self.wait_for(lambda: self.window.state.market_revision == 1 and not self.watch._series_loading)
        self.assertEqual(self.watch.table.item(1, 1).text(), '778')
        self.assertIn('777', self.watch.detail.text())
        self.assertEqual(self.watch.state.market_connection, 'DISCONNECTED')
        self.assertNotEqual(self.watch.header.text(), header_before)
        self.assertEqual(self.watch.chart.bars[-1].close, Decimal('102'))
        self.assertGreater(len(self.facade.queries), before)
        self.assertEqual(self.facade.queries[-1].instrument_id, 'TX')
        for table, previous in zip(tables, selected):
            with self.subTest(table=table.objectName()):
                self.assertEqual(table.selectedItems(), previous)
        for reset, changed in spies:
            self.assertEqual((reset.count(), changed.count()), (0, 0))

    def test_market_workspace_hosts_three_panels_and_collapsed_archive_routes(self):
        self.window.navigation.setCurrentRow(2)
        self.app.processEvents()
        page = self.window.pages.currentWidget()
        self.assertTrue(page.isAncestorOf(self.watch))
        self.assertEqual(self.watch.panels.count(), 3)
        self.assertFalse(self.window.market_archive.isChecked())
        self.assertFalse(self.window.markets.isVisible())
        self.window.market_archive.setFocus()
        QTest.keyClick(self.window.market_archive, Qt.Key.Key_Space)
        self.assertTrue(self.window.markets.isVisible())
        routes = []
        self.window.legacy_requested.connect(routes.append)
        for button, route in ((self.window.legacy_import_button, 'data'), (self.window.legacy_market_button, 'market')):
            with self.subTest(route=route):
                self.assertTrue(button.isVisible())
                button.click()
                self.assertEqual(routes[-1], route)

    def test_market_revision_does_not_hide_existing_freshness_invalidation(self):
        self.facade.state = replace(self.facade.state, market_revision=1, financial_facts_verified=False)
        self.window.poll.timeout.emit()
        self.wait_for(lambda: self.window.state.market_revision == 1)
        self.assertEqual(self.window.summary.text(), ui_text('v2.summary_unknown_line').format(Decimal('100000'), ui_text('v2.quote_none')))

    def test_large_font_minimum_window_required_controls_are_reachable(self):
        health = replace(view().health, incomplete=True, history_error='market_data_invalid')
        self.watch.render(replace(self.facade.state, market_watch=(replace(view(), health=health), view(instrument='TX'))))
        self.window.setFont(QFont('Arial', 20))
        self.window.resize(600, 300)
        self.window.navigation.setCurrentRow(2)
        self.app.processEvents()
        page = self.window.pages.currentWidget()
        self.assertGreater(page.viewport().height(), 20)
        controls = (self.watch.instrument, self.watch.add, self.watch.remove, *self.watch.period_buttons.values(), self.watch.retry, self.window.market_archive)
        for control in controls:
            with self.subTest(control=control.objectName()):
                page.ensureWidgetVisible(control)
                self.app.processEvents()
                self.assertTrue(control.isVisible())
                self.assertTrue(control.parentWidget().rect().contains(control.geometry()))
                self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
                self.assertTrue(page.viewport().rect().contains(control.mapTo(page.viewport(), control.rect().center())))
        for group in ((self.watch.instrument, self.watch.add, self.watch.remove), tuple(self.watch.period_buttons.values())):
            for before, after in zip(group, group[1:]):
                with self.subTest(before=before.objectName(), after=after.objectName()):
                    self.assertFalse(before.geometry().intersects(after.geometry()))
        self.watch.panels.moveSplitter(0, 1)
        self.app.processEvents()
        for index in range(3):
            with self.subTest(panel=index):
                panel = self.watch.panels.widget(index)
                self.assertTrue(panel.isVisible())
                self.assertGreater(panel.width(), 0)
                self.assertGreater(panel.height(), 0)
                self.assertTrue(self.watch.panels.rect().contains(panel.geometry()))
        self.assertLess(self.watch.table.mapTo(self.watch, QPoint()).x(), self.watch.chart.mapTo(self.watch, QPoint()).x())
        self.assertLess(self.watch.chart.mapTo(self.watch, QPoint()).x(), self.watch.detail.mapTo(self.watch, QPoint()).x())

    def test_keyboard_tab_order_and_period_activation_in_workspace(self):
        self.window.navigation.setCurrentRow(2)
        self.app.processEvents()
        self.watch.instrument.setFocus()
        focus = (self.watch.instrument, self.watch.add, self.watch.remove, self.watch.table, *self.watch.period_buttons.values())
        for before, after in zip(focus, focus[1:]):
            with self.subTest(before=before.objectName()):
                QTest.keyClick(before, Qt.Key.Key_Tab)
                self.assertIs(self.app.focusWidget(), after)
        QTest.keyClick(focus[-1], Qt.Key.Key_Space)
        self.wait_for(lambda: self.facade.queries[-1].period == '1d' and not self.watch._series_loading)
