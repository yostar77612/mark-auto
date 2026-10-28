"""Host-offscreen dashboard display, accessibility and command wiring.

Application fixtures supply facts; these tests do not recalculate trading rules.
"""

from dataclasses import replace
from decimal import Decimal
import time
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QTableWidget

from desktop_charts import CandlestickChart
from desktop_strings import ui_text
from desktop_trading import TradingWindow
from desktop_trading.market_watch import MarketWatchWidget
from quantlab.trading.application.contracts import OverviewMarketSummary, UiAction
from quantlab.trading.domain.models import Environment
from tests.test_market_watch_ui import FakeFacade, view
from tests.test_trading_ui import state_fixture


class DashboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = FakeFacade()
        quote = view()
        self.facade.state = replace(
            state_fixture(),
            environment=Environment.BROKER_SIMULATION,
            engine_state='RUNNING',
            reconciliation_verified=True,
            market_connection='CONNECTED',
            market_watch=(quote,),
            market_health=OverviewMarketSummary((quote.health,)),
            watchlist=('TMF',),
        )
        self.watch = MarketWatchWidget(self.facade, CandlestickChart(), self.facade.state)
        self.window = TradingWindow(self.facade, self.facade.state, market_watch=self.watch)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.dashboard = self.window.dashboard
        self.wait_for(lambda: not self.watch._series_loading)

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(condition())
        self.app.processEvents()

    def tearDown(self):
        self.wait_for(lambda: self.window._operation is None and self.window._priority_operation is None and not self.watch._series_loading)
        QThreadPool.globalInstance().waitForDone(3000)
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_shared_stopped_view_disconnect_retains_tables_and_red_text(self):
        tables = (self.dashboard.strategies, self.dashboard.positions)
        original = [table.item(0, 0) for table in tables]
        quote = view('STOPPED')
        state = replace(
            self.facade.state,
            market_revision=1,
            market_connection='DISCONNECTED',
            market_watch=(quote,),
            market_health=OverviewMarketSummary((quote.health,)),
        )
        self.window.apply_state(state)
        self.wait_for(lambda: not self.watch._series_loading)
        stopped = ui_text('watch.stopped').split('{')[0]
        for text in (self.watch.table.item(0, 5).text(), self.dashboard.lights['market'].text()):
            with self.subTest(text=text):
                self.assertIn(stopped, text)
        self.assertEqual(self.watch.table.item(0, 1).text(), '101')
        for table, item in zip(tables, original):
            with self.subTest(table=table.objectName()):
                self.assertEqual(table.rowCount(), 1)
                self.assertIs(table.item(0, 0), item)
        self.assertTrue(self.dashboard.red_summary.isVisible())
        self.assertIn(ui_text('dashboard.status.disconnected'), self.dashboard.red_summary.text())
        self.assertIn(stopped, self.dashboard.red_summary.text())
        self.assertEqual(self.dashboard.lights['market'].property('level'), 'red')

    def test_display_application_facts_and_unknown_non_live_position(self):
        state = replace(
            self.facade.state,
            version=2,
            daily_pnl=Decimal('17'),
            unrealized_pnl=Decimal('19'),
            remaining_risk=Decimal('23'),
            remaining_daily_loss=Decimal('29'),
            today_fill_count=3,
            strategies=(replace(self.facade.state.strategies[0], activity_state='RUNNING', today_order_count=7, today_pnl=Decimal('31')),),
            positions=(replace(self.facade.state.positions[0], quote_freshness='STOPPED', unrealized_pnl=Decimal('999')),),
            issues=('pending issue',),
            events=('entries_resumed_explicitly',),
        )
        self.window.apply_state(state)
        for value in ('17', '19', '23', '29', '3'):
            with self.subTest(value=value):
                self.assertIn(value, self.dashboard.today.text())
        self.assertEqual(self.dashboard.strategies.item(0, 3).text(), '7')
        self.assertEqual(self.dashboard.strategies.item(0, 4).text(), '31')
        self.assertEqual(self.dashboard.positions.item(0, 6).text(), ui_text('watch.unknown'))
        self.assertEqual(self.window.issue_details.item(0).text(), 'pending issue')
        self.assertLess(self.dashboard.issue_details.y(), self.dashboard.strategies.y())
        self.assertFalse(self.window.events.isVisible())
        self.dashboard.events_toggle.setFocus()
        QTest.keyClick(self.dashboard.events_toggle, Qt.Key.Key_Space)
        self.assertTrue(self.window.events.isVisible())
        self.assertEqual(self.window.events.item(0).text(), ui_text('v2.event_resumed'))

    def test_exact_operations_send_existing_actions_by_keyboard(self):
        self.assertEqual(set(self.dashboard.operation_buttons), {UiAction.STOP_NEW, UiAction.CANCEL_ENTRIES, UiAction.RECONCILE})
        self.assertEqual(len(self.dashboard.findChildren(QPushButton)), 4)  # three operations and event expansion
        controls = list(self.dashboard.operation_buttons.values())
        for before, after in zip(controls, controls[1:]):
            with self.subTest(tab=before.objectName()):
                before.setFocus()
                QTest.keyClick(before, Qt.Key.Key_Tab)
                self.assertIs(self.app.focusWidget(), after)
        for action, control in self.dashboard.operation_buttons.items():
            with self.subTest(action=action):
                control.setFocus()
                QTest.keyClick(control, Qt.Key.Key_Space)
                self.wait_for(lambda: self.window._operation is None and self.window._priority_operation is None)
                self.assertEqual(self.facade.commands[-1].action, action)

    def test_market_revision_keeps_table_items_and_selection_without_model_changes(self):
        tables = (self.dashboard.strategies, self.dashboard.positions)
        for table in tables:
            table.selectRow(0)
        previous = [table.selectedItems() for table in tables]
        spies = [(QSignalSpy(table.model().modelReset), QSignalSpy(table.model().dataChanged)) for table in tables]
        quote = view('DELAYED')
        self.window.apply_state(replace(self.facade.state, market_revision=1, market_watch=(quote,), market_health=OverviewMarketSummary((quote.health,))))
        self.assertEqual(self.dashboard.lights['market'].property('level'), 'warning')
        for table, selection, (reset, changed) in zip(tables, previous, spies):
            with self.subTest(table=table.objectName()):
                self.assertEqual(table.selectedItems(), selection)
                self.assertEqual((reset.count(), changed.count()), (0, 0))
        quote_cell = self.dashboard.positions.item(0, 7)
        self.window.apply_state(
            replace(
                self.facade.state,
                market_revision=2,
                unrealized_pnl=Decimal('41'),
                positions=(replace(self.facade.state.positions[0], quote_time='updated quote time'),),
            )
        )
        self.assertIs(self.dashboard.positions.item(0, 7), quote_cell)
        self.assertEqual(quote_cell.text(), 'updated quote time')
        self.assertIn('41', self.dashboard.today.text())
        self.assertEqual(self.dashboard.positions.selectedItems(), previous[1])

    def test_names_and_large_font_minimum_window_scroll_reachability(self):
        controls = [control for kind in (QPushButton, QLabel, QListWidget, QTableWidget) for control in self.dashboard.findChildren(kind)]
        for control in controls:
            with self.subTest(name=control.objectName()):
                self.assertTrue(control.objectName())
                self.assertTrue(control.accessibleName())
        self.window.setFont(QFont('Arial', 20))
        self.window.resize(self.window.minimumSize())
        self.app.processEvents()
        page = self.window.pages.widget(0)
        required = (
            self.dashboard.red_summary,
            self.dashboard.issue_details,
            *self.dashboard.lights.values(),
            self.dashboard.today,
            self.dashboard.strategies,
            self.dashboard.positions,
            *self.dashboard.operation_buttons.values(),
            self.dashboard.events_toggle,
            self.window.overview_new_strategy,
            self.window.overview_step,
        )
        # Ensure a visible anomaly summary is included in geometry evidence.
        self.window.apply_state(replace(self.facade.state, version=2, engine_state='STOPPED'))
        for control in required:
            with self.subTest(control=control.objectName()):
                page.ensureWidgetVisible(control)
                self.app.processEvents()
                self.assertTrue(control.isVisible())
                self.assertTrue(page.viewport().rect().contains(control.mapTo(page.viewport(), control.rect().center())))
                if isinstance(control, QPushButton):
                    self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
