"""M2-6 first-round UI safety and full-data layout; no SDK or financial operations."""

from dataclasses import replace
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.trading_page import LIVE_ORDER_ACTIONS, install_trading_environment
from desktop_app.shell.theme import _apply_trading_page_theme
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import AccountView, ContextOption, OrderView, UiAction, UiReceipt
from quantlab.trading.domain.models import Environment, Market, QuantityUnit, Side
from tests import test_trading_ui as support


class EnvironmentSwitchFacade(support.RecordingFacade):
    def __init__(self):
        super().__init__()
        self.state = replace(
            self.state,
            accounts=self.state.accounts
            + (
                AccountView('sim-futures', Environment.BROKER_SIMULATION, Market.INDEX_FUTURE, self.state.allocated_cash, 'EXTERNAL_REQUIRED'),
                AccountView('live-stock', Environment.LIVE, Market.STOCK, self.state.allocated_cash, 'EXTERNAL_REQUIRED'),
            ),
        )
        self.accept_switch = True
        self.hold = False
        self.entered, self.release = Event(), Event()
        self.state = replace(
            self.state, orders=(OrderView('local-order', 'TWSE:2330', Side.BUY, 1000, 0, QuantityUnit.SHARE, 'ACCEPTED', False, 'local-stock'),)
        )

    def execute(self, command):
        self.commands.append(command)
        if command.action is UiAction.SWITCH_CONTEXT:
            self.entered.set()
            if self.hold and not self.release.wait(2):
                raise TimeoutError('synthetic navigation release missing')
            if not self.accept_switch:
                return UiReceipt(False, 'state_conflict', 'Synthetic switch rejected')
            position = replace(
                self.state.positions[0],
                lot_id=command.environment.value,
                instrument_id='TAIFEX:TMF:202611' if command.environment is Environment.BROKER_SIMULATION else 'TWSE:2330',
                account_ref=command.account_ref,
            )
            self.state = replace(
                self.state,
                version=self.state.version + 1,
                environment=command.environment,
                account_ref=command.account_ref,
                positions=(position,),
                context_id=command.context_id or self.state.context_id,
                context_epoch=self.state.context_epoch + bool(self.state.contexts),
                orders=(
                    replace(self.state.orders[0], order_id=command.environment.value, instrument_id=position.instrument_id, account_ref=command.account_ref),
                ),
            )
        return UiReceipt(True, 'completed', '')


class M2TradingPageTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    drain = support.TradingUiTests.drain
    tearDown = support.TradingUiTests.tearDown

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = EnvironmentSwitchFacade()
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        _apply_trading_page_theme(self.window)
        self.window.navigation.setCurrentRow(3)
        self.window.show()
        self.app.processEvents()

    def test_environment_installation_uses_the_explicit_page_owner(self):
        page = QWidget()
        self.addCleanup(page.deleteLater)
        page_layout = QVBoxLayout(page)
        header = QHBoxLayout()
        page_layout.addLayout(header)
        layout_owner = QWidget(page)
        layout_owner.setObjectName('independent_layout_owner')
        page_layout.addWidget(layout_owner)
        layout = QVBoxLayout(layout_owner)
        host = SimpleNamespace(page_headers={'trading': header}, environment=QComboBox(page))

        install_trading_environment(host, layout, page)

        self.assertIs(host.trading_execution_page, page)
        self.assertEqual(page.objectName(), 'trading_execution_page')
        self.assertEqual(layout_owner.objectName(), 'independent_layout_owner')
        self.assertIs(self.window.trading_execution_page, self.window.pages.widget(3).widget())
        self.assertEqual(self.window.trading_execution_page.property('executionEnvironment'), Environment.LOCAL.value)

    def test_switch_pending_keeps_accepted_environment_then_isolates_books(self):
        window = self.window
        self.facade.hold = True
        try:
            with patch.object(window, '_confirm', return_value=True):
                window.trading_environment.setCurrentIndex(window.trading_environment.findData(Environment.BROKER_SIMULATION))
            self.assertTrue(self.facade.entered.wait(1))
            for selector in (window.environment, window.trading_environment):
                self.assertIs(Environment(selector.currentData()), Environment.LOCAL)
            self.assertEqual(window.positions.item(0, 0).text(), 'TWSE:2330')
            self.assertEqual(window.trading_environment_notice.text(), ui_text('m2t.local'))
        finally:
            self.facade.release.set()
        self.drain()
        for selector in (window.environment, window.trading_environment):
            self.assertIs(Environment(selector.currentData()), Environment.BROKER_SIMULATION)
        self.assertEqual(window.positions.rowCount(), 1)
        self.assertEqual(window.positions.item(0, 0).text(), 'TAIFEX:TMF:202611')
        self.assertEqual(window.positions.item(0, 4).text(), 'sim-futures')
        self.assertEqual(window.orders.rowCount(), 1)
        self.assertEqual(window.orders.item(0, 0).text(), 'TAIFEX:TMF:202611')
        self.assertEqual(window.orders.item(0, 6).text(), 'sim-futures')
        self.assertEqual(self.facade.commands[0].action, UiAction.SWITCH_CONTEXT)

    def test_settings_switch_rejected_or_unavailable_never_looks_successful(self):
        window = self.window
        self.facade.accept_switch = False
        with patch.object(window, '_confirm', return_value=True):
            window.environment.setCurrentIndex(window.environment.findData(Environment.LIVE))
        self.drain()
        for selector in (window.environment, window.trading_environment):
            self.assertIs(Environment(selector.currentData()), Environment.LOCAL)
        self.assertEqual(window.trading_environment_notice.text(), ui_text('m2t.local'))
        self.assertEqual(window.positions.item(0, 4).text(), 'local-stock')
        self.facade.state = replace(window.state, accounts=tuple(a for a in window.state.accounts if a.environment is Environment.LOCAL), version=2)
        window.apply_state(self.facade.state)
        window.trading_environment.setCurrentIndex(window.trading_environment.findData(Environment.LIVE))
        for selector in (window.environment, window.trading_environment):
            self.assertIs(Environment(selector.currentData()), Environment.LOCAL)
        self.assertEqual(len(self.facade.commands), 1)
        self.assertIn(ui_text('v2.no_account'), window.notice.text())

    def test_nested_confirmation_poll_keeps_the_requested_context_tuple(self):
        contexts = (ContextOption('local', '', Environment.LOCAL, ('local-stock',)), ContextOption('sim', '', Environment.BROKER_SIMULATION, ('sim-futures',)))
        self.facade.state = replace(self.window.state, version=2, context_id='local', contexts=contexts)
        self.window.apply_state(self.facade.state)
        with patch.object(self.window, '_confirm', side_effect=lambda _: (self.window.apply_state(self.window.state), True)[1]):
            self.window.trading_environment.setCurrentIndex(self.window.trading_environment.findData(Environment.BROKER_SIMULATION))
        self.drain()
        command = self.facade.commands[0]
        self.assertEqual((command.environment, command.account_ref, command.context_id), (Environment.BROKER_SIMULATION, 'sim-futures', 'sim'))

    def test_first_broker_profile_import_requires_an_explicit_environment(self):
        self.facade.state = replace(
            self.window.state, version=2, context_id='local', contexts=(ContextOption('local', '', Environment.LOCAL, ('local-stock',)),)
        )
        self.window.apply_state(self.facade.state)
        self.window.trading_environment.setCurrentIndex(self.window.trading_environment.findData(Environment.BROKER_SIMULATION))
        with (
            patch('PySide6.QtWidgets.QInputDialog.getItem', return_value=(ui_text('v2.broker_sim'), True)) as choose,
            patch('desktop_app.features.trading.window.QFileDialog.getOpenFileName', return_value=('fixture-profile.json', '')) as file,
        ):
            self.window.add_context()
        self.drain()
        choose.assert_called_once()
        self.assertEqual(choose.call_args.args[3], [ui_text('v2.broker_sim'), ui_text('v2.live')])
        file.assert_called_once()
        self.assertEqual(
            [(c.action, c.environment, c.profile_ref) for c in self.facade.commands],
            [(UiAction.ADD_CONTEXT, Environment.BROKER_SIMULATION, 'fixture-profile.json')],
        )
        self.assertIs(self.window.state.environment, Environment.LOCAL)
        self.assertEqual(self.window.positions.item(0, 0).text(), 'TWSE:2330')

    def test_first_profile_cancellation_emits_no_command(self):
        self.facade.state = replace(
            self.window.state, version=2, context_id='local', contexts=(ContextOption('local', '', Environment.LOCAL, ('local-stock',)),)
        )
        self.window.apply_state(self.facade.state)
        with (
            patch('PySide6.QtWidgets.QInputDialog.getItem', return_value=('', False)),
            patch('desktop_app.features.trading.window.QFileDialog.getOpenFileName') as file,
        ):
            self.window.add_context()
            file.assert_not_called()
        with (
            patch('PySide6.QtWidgets.QInputDialog.getItem', return_value=(ui_text('v2.broker_sim'), True)),
            patch('desktop_app.features.trading.window.QFileDialog.getOpenFileName', return_value=('', '')),
        ):
            self.window.add_context()
        self.assertEqual(self.facade.commands, [])

    def test_leaving_live_does_not_unlock_orders_before_simulation_is_accepted(self):
        window = self.window
        self.facade.state = replace(window.state, environment=Environment.LIVE, version=2)
        window.apply_state(self.facade.state)
        self.facade.hold = True
        try:
            with patch.object(window, '_confirm', return_value=True):
                window.trading_environment.setCurrentIndex(window.trading_environment.findData(Environment.BROKER_SIMULATION))
            self.assertTrue(self.facade.entered.wait(1))
            for selector in (window.environment, window.trading_environment):
                self.assertIs(Environment(selector.currentData()), Environment.LIVE)
            self.assertFalse(window.flatten_button.isEnabled())
            window.command(UiAction.FLATTEN, 'lot-1')
            self.assertEqual([command.action for command in self.facade.commands], [UiAction.SWITCH_CONTEXT])
        finally:
            self.facade.release.set()
        self.drain()
        self.assertIs(window.state.environment, Environment.BROKER_SIMULATION)
        self.assertTrue(window.flatten_button.isEnabled())

    def test_live_disables_controls_and_rejects_every_current_order_intent(self):
        window = self.window
        self.facade.state = replace(window.state, environment=Environment.LIVE, version=2)
        window.apply_state(self.facade.state)
        for name in ('deploy_button', 'resume_button', 'cancel_entries_button', 'flatten_button', 'overview_step', 'overview_cancel_entries'):
            control = getattr(window, name)
            self.assertFalse(control.isEnabled(), name)
            control.click()
        expected = frozenset((UiAction.DEPLOY, UiAction.STEP, UiAction.RESUME, UiAction.CANCEL_ENTRIES, UiAction.FLATTEN))
        self.assertEqual(LIVE_ORDER_ACTIONS, expected)
        for action in expected:
            window.command(action, 'lot-1')
            self.assertIsNone(window._operation)
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(window.notice.text(), ui_text('m2t.orders_disabled'))
        self.assertTrue(window.stop_button.isEnabled())
        self.assertEqual(window.stop_button.text(), ui_text('m2t.live_stop'))
        self.assertEqual(window.stop_button.toolTip(), ui_text('m2t.live_stop_hint'))
        self.assertEqual(window.overview_stop.text(), ui_text('m2t.live_stop'))
        self.assertTrue(window.overview_stop.isEnabled())
        self.assertTrue(window.reconcile_button.isEnabled())
        with patch.object(window, '_confirm', return_value=True):
            window.stop_button.click()
        self.drain()
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.STOP_NEW])
        window.reconcile_button.click()
        self.drain()
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.STOP_NEW, UiAction.RECONCILE])
        window.apply_state(replace(window.state, environment=Environment.LOCAL, version=3))
        self.assertEqual(window.stop_button.text(), ui_text('v2.stop_new'))
        self.assertEqual(window.stop_button.toolTip(), ui_text('m2t.stop_hint'))

    def test_environment_band_and_live_border_have_actual_distinct_colors(self):
        for number, (environment, text, background) in enumerate(
            (
                (Environment.LOCAL, '#31465d', '#e5edf7'),
                (Environment.BROKER_SIMULATION, '#1b6335', '#e8f5ec'),
                (Environment.LIVE, '#9c1b24', '#fff0f0'),
            ),
            start=2,
        ):
            self.window.apply_state(replace(self.window.state, version=number, environment=environment))
            self.app.processEvents()
            banner = self.window.trading_environment_notice
            self.assertEqual(banner.palette().color(QPalette.ColorRole.WindowText).name(), text)
            self.assertEqual(banner.palette().color(QPalette.ColorRole.Window).name(), background)
            self.assertEqual(self.window.trading_execution_page.property('executionEnvironment'), environment.value)
        self.assertIn(ui_text('m2t.orders_disabled'), self.window.trading_environment_notice.text())
        self.assertEqual(self.window.trading_execution_page.grab().toImage().pixelColor(0, 0).name(), '#b52c36')

    def test_1366_full_positions_keep_first_column_and_all_columns_in_view(self):
        position = replace(
            self.window.state.positions[0],
            instrument_id='TAIFEX:TMF:202611',
            strategy_id='strategy-0123456789-abcdef-0123456789',
            account_ref='sim-futures-account-001',
            quantity=5,
            unit=QuantityUnit.CONTRACT,
            quote_time='2026-11-02 09:15:00',
        )
        self.window.resize(1366, 768)
        self.window.apply_state(replace(self.window.state, version=2, positions=tuple(replace(position, lot_id=f'lot-{i}') for i in range(3))))
        self.app.processEvents()
        table = self.window.positions
        self.assertEqual(table.columnCount(), 12)
        self.assertEqual({column for column in range(12) if not table.isColumnHidden(column)}, {0, 1, 2, 5, 8, 9})
        self.assertEqual(table.rowCount(), 3)
        self.assertFalse(table.horizontalScrollBar().isVisible())
        self.assertEqual(table.horizontalScrollBar().maximum(), 0)
        self.assertEqual(table.horizontalHeader().sectionViewportPosition(0), 0)
        first = table.item(0, 0)
        self.assertGreaterEqual(table.columnWidth(0), table.fontMetrics().horizontalAdvance(first.text()) + 6)
        self.assertTrue(table.viewport().rect().contains(table.visualItemRect(first)))
        self.assertLessEqual(table.horizontalHeader().sectionViewportPosition(9) + table.columnWidth(9), table.viewport().width())
        scroll = self.window.findChild(QScrollArea, 'trading_scroll')
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                self.assertEqual(table.item(row, column).toolTip(), table.item(row, column).text())
        for column in range(table.columnCount()):
            self.assertTrue(table.horizontalHeaderItem(column).toolTip())

    def test_plain_language_hints_and_keyboard_environment_access(self):
        for name in ('transfer_button', 'reconcile_button', 'stop_button', 'cancel_entries_button', 'flatten_button', 'resume_button'):
            control = getattr(self.window, name)
            self.assertGreater(len(control.toolTip()), len(control.text()))
        selector = self.window.trading_environment
        self.assertTrue(selector.accessibleName())
        self.assertTrue(selector.toolTip())
        self.assertTrue(selector.focusPolicy() & Qt.FocusPolicy.TabFocus)
