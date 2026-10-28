"""Actual widgets route typed commands and retain visible execution context.

These are offscreen presentation tests, not native desktop or broker acceptance.
"""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QThread, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from shiboken6 import isValid

from desktop_strings import ui_text
from desktop_trading import TradingWindow
from desktop_trading.wizard import StrategyWizard
from desktop_trading.widgets import fit_available_screen
from quantlab.trading.application.contracts import (
    AccountView,
    BrokerReadiness,
    MarketView,
    PerformanceView,
    PositionView,
    ReconciliationView,
    StrategyView,
    UiAction,
    UiReceipt,
    UiState,
)
from quantlab.trading.application.broker_settings import ReadinessCheck
from quantlab.trading.domain.models import Environment, HoldingKind, Market, QuantityUnit, Side


def state_fixture() -> UiState:
    return UiState(
        Environment.LOCAL,
        'local-stock',
        'STOPPED',
        'SWING:3-5',
        Decimal('100000'),
        Decimal('-15'),
        Decimal('1985'),
        'NO_DATA',
        1,
        '2026-10-23',
        True,
        strategies=(
            StrategyView(
                'strategy-1',
                'Local strategy',
                1,
                Market.STOCK,
                'TWSE:2330',
                HoldingKind.SWING,
                'SWING:3-5',
                'RESEARCHED',
                'local-stock',
                Environment.LOCAL,
                'fixture-only',
            ),
        ),
        positions=(
            PositionView(
                'lot-1',
                'TWSE:2330',
                'strategy-1',
                1,
                'SWING:3-5',
                1000,
                QuantityUnit.SHARE,
                0,
                '2026-10-23',
                0,
                '2026-10-28 / 2026-10-30',
                'EXIT_BLOCKED',
                '2026-10-23T05:30:00Z',
                'MANAGED',
                'local-stock',
            ),
        ),
        markets=(
            MarketView('TWSE:2330', Market.STOCK, QuantityUnit.SHARE, None, '', 'NO_DATA', 'LOCAL_SYNTHETIC'),
            MarketView('TAIFEX:TMF:202611', Market.INDEX_FUTURE, QuantityUnit.CONTRACT, Decimal('20000'), '2026-10-23T05:30:00Z', 'FRESH', 'LOCAL_SYNTHETIC'),
        ),
        accounts=(
            AccountView('local-stock', Environment.LOCAL, Market.STOCK, Decimal('60000'), 'LOCAL_READY'),
            AccountView('local-future', Environment.LOCAL, Market.INDEX_FUTURE, Decimal('40000'), 'LOCAL_READY'),
        ),
    )


class RecordingFacade:
    def __init__(self):
        self.state = state_fixture()
        self.commands = []
        self.failure = False

    def snapshot(self):
        if self.failure:
            raise ConnectionError('private transport detail must not reach UI')
        return self.state

    def execute(self, command):
        self.commands.append(command)
        return UiReceipt(False, 'eligibility_unknown', 'Account eligibility remains unknown', command.target_id)


class TradingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # processEvents() without an outer app.exec() does not guarantee
        # DeferredDelete delivery. Flush prior fixtures before timing this
        # operation, rather than charging their deferred cleanup to its 3s.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = RecordingFacade()
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.app.processEvents()

    def drain(self):
        started = time.monotonic()
        deadline = started + 3
        while (self.window._operation is not None or self.window._priority_operation is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)

        def phase(operation):
            if operation is None:
                return 'none'
            action = operation.command.action.value if operation.command else 'REFRESH'
            return f'action={action},running={operation.isRunning()},finished={operation.isFinished()}'

        details = f'elapsed={time.monotonic() - started:.3f}s,loop={QThread.currentThread().loopLevel()},commands={len(self.facade.commands)}'
        self.assertIsNone(self.window._operation, f'application operation failed to finish: {phase(self.window._operation)};{details}')
        self.assertIsNone(self.window._priority_operation, f'priority stop failed to finish: {phase(self.window._priority_operation)};{details}')
        self.app.processEvents()

    def tearDown(self):
        self.drain()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(self.window), 'the fixture must destroy its owned Qt window')
        self.app.processEvents()

    def test_six_workspaces_keep_account_policy_funds_and_stale_state_visible(self):
        self.assertEqual(self.window.navigation.count(), 6)
        for page in range(6):
            self.window.navigation.setCurrentRow(page)
            self.app.processEvents()
            self.assertEqual(self.window.pages.currentIndex(), page)
            self.assertTrue(self.window.context.isVisible())
            self.assertIn('local-stock', self.window.context.text())
            self.assertIn('100,000', self.window.summary.text())
            self.assertIn(ui_text('v2.quote_none'), self.window.summary.text())
        self.assertEqual(self.window.markets.item(0, 3).text(), ui_text('v2.unavailable'))
        self.assertEqual(self.window.positions.item(0, 2).text(), '0')
        self.assertIn('2026-10-23', self.window.positions.item(0, 6).text())
        self.assertIn(ui_text('v2.managed'), self.window.positions.item(0, 10).text())

    def test_stop_cancel_and_resume_send_distinct_versioned_commands(self):
        for widget, action in (
            (self.window.stop_button, UiAction.STOP_NEW),
            (self.window.cancel_entries_button, UiAction.CANCEL_ENTRIES),
            (self.window.resume_button, UiAction.RESUME),
        ):
            widget.click()
            self.drain()
            self.assertEqual(self.facade.commands[-1].action, action)
            self.assertEqual(self.facade.commands[-1].expected_version, 1)
        self.assertEqual(len(self.facade.commands), 3)

    def test_flatten_requires_selection_and_explicit_scoped_confirmation(self):
        self.window.flatten_selected()
        self.assertEqual(self.facade.commands, [])
        self.window.positions.selectRow(0)
        with patch.object(self.window, '_confirm', return_value=False) as confirm:
            self.window.flatten_selected()
            self.assertIn('TWSE:2330', confirm.call_args.args[0])
            self.assertIn('0', confirm.call_args.args[0])
        self.assertEqual(self.facade.commands, [])
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.flatten_selected()
        self.drain()
        self.assertEqual(self.facade.commands[-1].target_id, 'lot-1')
        self.assertEqual(self.facade.commands[-1].action, UiAction.FLATTEN)

    def test_deployment_summary_uses_selected_strategy_allocation_and_risk(self):
        selected = replace(self.window.state.strategies[0], allocation=Decimal('45000'), risk_fraction=Decimal('0.03'))
        self.window.apply_state(replace(self.window.state, version=2, strategies=(selected,)))
        self.window.strategies.selectRow(0)
        with patch.object(self.window, '_confirm', return_value=True) as confirm:
            self.window.deploy_selected()
            self.assertIn('45,000', confirm.call_args.args[0])
            self.assertIn('3.00%', confirm.call_args.args[0])
            self.assertIn('local-stock', confirm.call_args.args[0])
        self.drain()
        self.assertEqual(self.facade.commands[-1].action, UiAction.DEPLOY)
        self.assertEqual(self.facade.commands[-1].target_id, 'strategy-1:1')

    def test_deployment_summary_shows_explicit_roll_target_after_wizard_is_closed(self):
        strategy = replace(
            self.window.state.strategies[0],
            market=Market.INDEX_FUTURE,
            instrument_id='TAIFEX:TMF:202612',
            allocation=Decimal('40000'),
            expiry_action='ROLL',
            roll_contract_id='TAIFEX:TMF:202703',
        )
        self.window.apply_state(replace(self.window.state, version=2, strategies=(strategy,)))
        self.window.strategies.selectRow(0)
        with patch.object(self.window, '_confirm', return_value=False) as confirm:
            self.window.deploy_selected()
            self.assertIn('TAIFEX:TMF:202703', confirm.call_args.args[0])
            self.assertIn(ui_text('v2.expiry_roll'), confirm.call_args.args[0])
        self.assertFalse(self.facade.commands)

    def test_rejection_feedback_survives_poll_and_all_pending_issues_remain_accessible(self):
        self.window.stop_button.click()
        self.drain()
        feedback = self.window.notice.text()
        self.window.refresh()
        self.drain()
        self.assertEqual(self.window.notice.text(), feedback)
        issues = tuple(f'Issue {index}' for index in range(12))
        self.window.apply_state(replace(self.window.state, version=3, issues=issues))
        self.assertEqual(self.window.issue_details.count(), 12)
        self.assertIn('12', self.window.notice.text())

    def test_failed_engine_query_retains_prior_positions_and_no_private_error(self):
        self.facade.failure = True
        self.window.refresh()
        self.drain()
        self.assertEqual(self.window.positions.rowCount(), 1)
        self.assertEqual(self.window.state.version, 1)
        self.assertEqual(self.window.notice.text(), ui_text('v2.connection_failed'))
        self.assertNotIn('private', self.window.notice.text())

    def test_wizard_summary_uses_human_environment_labels_without_changing_dto(self):
        for environment, key in ((Environment.LOCAL, 'v2.local'), (Environment.BROKER_SIMULATION, 'v2.broker_sim'), (Environment.LIVE, 'v2.live')):
            state = replace(self.window.state, environment=environment)
            wizard = StrategyWizard(state, self.window)
            wizard._summary()
            self.assertIn(ui_text(key), wizard.summary.text())
            self.assertNotIn(environment.value, wizard.summary.text())
            self.assertIs(wizard.state.environment, environment)
            wizard.deleteLater()

    def test_execution_drawdown_distinguishes_unknown_history_from_proven_zero(self):
        legacy = PerformanceView('strategy-1', 1, Market.STOCK, 'SWING:3-5', Environment.LOCAL, Decimal('129'), Decimal('0'), Decimal('71'), None, '5')
        self.window.apply_state(replace(self.window.state, version=2, performance=(legacy,)))
        self.assertEqual(self.window.performance.horizontalHeaderItem(7).text(), ui_text('v2.attributed_pnl'))
        self.assertEqual(self.window.performance.horizontalHeaderItem(8).text(), ui_text('v2.drawdown_recorded'))
        self.assertIn(ui_text('v2.performance_valuation_hint'), self.window.performance.horizontalHeaderItem(8).toolTip())
        self.assertEqual(self.window.performance.item(0, 7).text(), ui_text('v2.drawdown_unknown'))
        self.assertEqual(self.window.performance.item(0, 8).text(), ui_text('v2.drawdown_unknown'))
        self.assertEqual(self.window.performance.item(0, 10).text(), ui_text('v2.drawdown_incomplete'))
        self.assertEqual(self.window.performance.item(0, 11).text(), ui_text('v2.drawdown_not_recorded'))
        known = replace(legacy, drawdown=Decimal('0'), attributed_pnl=Decimal('0'), drawdown_coverage='COMPLETE', drawdown_as_of='2026-10-23T09:05:00+08:00')
        self.window.apply_state(replace(self.window.state, version=3, performance=(known,)))
        self.assertEqual(self.window.performance.item(0, 7).text(), '0')
        self.assertEqual(self.window.performance.item(0, 8).text(), '0')
        self.assertEqual(self.window.performance.item(0, 10).text(), ui_text('v2.drawdown_complete'))
        self.assertEqual(self.window.performance.item(0, 11).text(), known.drawdown_as_of)

    def test_quote_revision_updates_price_without_ledger_version_change(self):
        self.window.strategies.selectRow(0)
        strategy_item = self.window.strategies.item(0, 0)
        self.window.stock_budget.setText('54321')
        self.window._dirty_settings()
        market = replace(self.window.state.markets[0], price=Decimal('123.45'), availability='FRESH')
        self.window.apply_state(replace(self.window.state, quote_revision=1, markets=(market,)))
        self.assertEqual(self.window.state.version, 1)
        self.assertEqual(self.window.markets.item(0, 3).text(), '123.45')

        self.assertEqual(self.window.markets.item(0, 5).text(), ui_text('v2.quote_fresh'))
        self.assertIs(self.window.strategies.item(0, 0), strategy_item)
        self.assertTrue(strategy_item.isSelected())
        self.assertEqual(self.window.stock_budget.text(), '54321')
        self.window.navigation.setCurrentRow(2)
        self.assertEqual(self.window.markets.item(0, 3).text(), '123.45')

    def test_market_workspace_characterization(self):
        self.window.navigation.setCurrentRow(2)
        page = self.window.pages.currentWidget()
        self.assertEqual(page.objectName(), 'market_scroll')
        self.assertTrue(page.isAncestorOf(self.window.markets))
        self.assertTrue(page.isAncestorOf(self.window.market_refresh_button))
        self.assertEqual(self.window.markets.columnCount(), 7)
        routes = []
        self.window.legacy_requested.connect(routes.append)
        for button, route in ((self.window.legacy_import_button, 'data'), (self.window.legacy_market_button, 'market')):
            with self.subTest(route=route):
                button.click()
                self.assertEqual(routes[-1], route)

    def test_snapshot_poll_quote_refresh_characterization(self):
        from unittest.mock import Mock

        tables = (self.window.strategies, self.window.positions, self.window.orders, self.window.markets, self.window.performance)
        changes = [Mock() for _ in tables]
        for table, changed in zip(tables, changes):
            table.model().dataChanged.connect(changed)
            if table.rowCount():
                table.selectRow(0)
        selected = [table.selectedItems() for table in tables]
        self.facade.state = replace(
            self.facade.state,
            quote_revision=1,
            markets=tuple(replace(item, price=Decimal('123.45')) for item in self.facade.state.markets),
            positions=tuple(replace(item, quote_time='new quote') for item in self.facade.state.positions),
        )
        self.assertEqual(self.window.poll.interval(), 1000)
        self.window.poll.timeout.emit()
        self.drain()
        self.assertEqual([change.called for change in changes], [False, True, False, True, False])
        for table, previous in zip(tables, selected):
            with self.subTest(table=table.objectName()):
                self.assertEqual(table.selectedItems(), previous)

    def test_removed_selected_lot_does_not_select_a_replacement_for_flatten(self):
        self.window.positions.selectRow(0)
        replacement = replace(self.window.state.positions[0], lot_id='unrelated-lot', source='EXTERNAL')
        self.window.apply_state(replace(self.window.state, version=2, positions=(replacement,)))
        self.assertEqual(self.window.positions.selectedItems(), [])
        self.window.flatten_selected()
        self.assertEqual(self.facade.commands, [])

    def test_reconciliation_shows_signed_quantities_and_does_not_flatten_external_scope(self):
        difference = ReconciliationView('local-stock', 'TWSE:2330', 1000, 3000, 3000, QuantityUnit.SHARE, as_of='2026-10-23T05:30:00Z')
        self.window.apply_state(replace(self.window.state, version=2, reconciliation=(difference,)))
        self.assertEqual(self.window.reconciliation.item(0, 3).text(), '+1,000 ' + ui_text('v2.shares'))
        self.assertEqual(self.window.reconciliation.item(0, 4).text(), '+3,000 ' + ui_text('v2.shares'))
        self.assertEqual(self.window.reconciliation.item(0, 5).text(), '+2,000 ' + ui_text('v2.shares'))
        self.window.positions.selectRow(0)
        self.window.reconciliation.selectRow(0)
        self.assertEqual(self.window.positions.selectedItems(), [])
        self.window.flatten_selected()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(self.window.notice.text(), ui_text('v2.reconciliation_cannot_flatten'))
        self.assertTrue(any('+2,000' in self.window.issue_details.item(i).text() for i in range(self.window.issue_details.count())))

    def test_unknown_reconciliation_quantity_stays_unknown_and_short_position_is_explicit(self):
        difference = ReconciliationView(
            'local-futures', 'TAIFEX:TMF:202612', None, -1, None, QuantityUnit.CONTRACT, kind='ORDER', broker_order_ref='broker-mobile-ref', status='ACCEPTED'
        )
        position = replace(self.window.state.positions[0], direction=Side.SELL)
        self.window.apply_state(replace(self.window.state, version=2, positions=(position,), reconciliation=(difference,)))
        self.assertEqual(self.window.reconciliation.item(0, 3).text(), ui_text('v2.reconciliation_quantity_unknown'))
        self.assertEqual(self.window.reconciliation.item(0, 4).text(), '-1 ' + ui_text('v2.contracts'))
        self.assertEqual(self.window.reconciliation.item(0, 5).text(), ui_text('v2.reconciliation_quantity_unknown'))
        self.assertEqual(self.window.reconciliation.item(0, 7).text(), 'broker-mobile-ref')
        self.assertIn(ui_text('v2.short'), self.window.positions.item(0, 1).text())

    def test_empty_reconciliation_is_unknown_until_verified_even_when_engine_is_closed(self):
        self.assertEqual(self.window.reconciliation_status.text(), ui_text('v2.reconciliation_unknown'))
        self.window.apply_state(replace(self.window.state, version=2, engine_state='CLOSED', reconciliation_verified=False))
        self.assertEqual(self.window.reconciliation_status.text(), ui_text('v2.reconciliation_unknown'))
        self.window.apply_state(replace(self.window.state, version=3, engine_state='STOPPED', reconciliation_verified=True))
        self.assertEqual(self.window.reconciliation_status.text(), ui_text('v2.reconciliation_clear'))

    def test_settings_collapsed_and_edited_amount_survives_refresh(self):
        self.window.navigation.setCurrentRow(5)
        self.assertFalse(self.window.advanced.isChecked())
        self.assertFalse(self.window.advanced_content.isVisible())
        self.window.advanced.setChecked(True)
        self.window.stock_budget.setText('55000')
        self.window._dirty_settings()
        self.window.apply_state(replace(self.window.state, version=2))
        self.assertEqual(self.window.stock_budget.text(), '55000')
        self.window.save_settings()
        self.drain()
        self.assertEqual(self.facade.commands[-1].settings.stock_allocation, Decimal('55000'))
        self.assertEqual(self.facade.commands[-1].expected_version, 2)
        self.assertEqual(self.window.stock_budget.text(), '55000', 'rejected settings must remain editable')

    def test_unavailable_environment_does_not_silently_switch_account(self):
        self.window.environment.setCurrentIndex(self.window.environment.findData(Environment.LIVE))
        self.assertEqual(self.window.state.environment, Environment.LOCAL)
        self.assertEqual(self.window.account.count(), 0)
        self.assertEqual(self.facade.commands, [])
        self.assertIn(ui_text('v2.no_account'), self.window.notice.text())

    def test_six_step_wizard_keeps_intraday_choice_and_decimal_form(self):
        wizard = StrategyWizard(self.window.state, self.window, parent_strategy_id='strategy-1')
        self.assertEqual(len(wizard.pageIds()), 6)
        self.assertEqual(wizard.form().holding_kind, HoldingKind.SWING)
        self.assertIsInstance(wizard.form().market, Market)
        self.assertIsInstance(wizard.form().holding_kind, HoldingKind)
        self.assertEqual(wizard.form().allocation, Decimal('60000'))
        self.assertEqual((wizard.form().min_days, wizard.form().max_days), (3, 5))
        wizard.policy.setCurrentIndex(1)
        self.assertEqual(wizard.form().holding_kind, HoldingKind.INTRADAY)
        self.assertEqual((wizard.form().min_days, wizard.form().max_days), (0, 0))
        self.assertEqual(wizard.form().parent_strategy_id, 'strategy-1')
        wizard.allocation.setText('NaN')
        wizard.accept()
        self.assertEqual(wizard.error.text(), ui_text('v2.form_invalid'))
        wizard.deleteLater()

    def test_structured_draft_is_plain_text_passed_to_application_not_executed_in_ui(self):
        wizard = StrategyWizard(self.window.state, self.window)
        wizard.rules.setCurrentIndex(wizard.rules.findData('STRUCTURED_JSON'))
        self.assertIn('"schema_version": 2', wizard.draft.toPlainText())
        self.assertIn(self.window.state.cost_version, wizard.draft.toPlainText())
        form = wizard.form()
        self.assertEqual(form.rule_kind, 'STRUCTURED_JSON')
        self.assertTrue(form.draft_json)
        malicious = '{"exec": "read_credentials_and_trade()"}'
        wizard.draft.setPlainText(malicious)
        self.assertEqual(wizard.form().draft_json, malicious)
        self.assertEqual(self.facade.commands, [])
        wizard.rules.setCurrentIndex(0)
        self.assertEqual(wizard.form().draft_json, '')
        wizard.deleteLater()

    def test_roll_requires_explicit_later_month_with_matching_underlying(self):
        earlier = replace(self.window.state.markets[1], underlying='TAIWAN_INDEX', delivery_month='202611', expiry_day='2026-11-18')
        later = replace(earlier, instrument_id='TAIFEX:TMF:202612', delivery_month='202612', expiry_day='2026-12-16')
        unrelated = replace(later, instrument_id='TAIFEX:OTHER:202612', underlying='OTHER')
        state = replace(self.window.state, markets=(self.window.state.markets[0], earlier, later, unrelated))
        wizard = StrategyWizard(state, self.window)
        wizard.market.setCurrentIndex(1)
        wizard.expiry_action.setCurrentIndex(wizard.expiry_action.findData('ROLL'))
        self.assertEqual(wizard.roll_contract.count(), 1)
        self.assertEqual(wizard.form().roll_contract_id, later.instrument_id)
        self.assertEqual(wizard.form().expiry_action, 'ROLL')
        wizard.market.setCurrentIndex(0)
        self.assertEqual(wizard.form().expiry_action, 'EXIT')
        self.assertEqual(wizard.form().roll_contract_id, '')
        wizard.deleteLater()

    def test_roll_without_resolved_metadata_does_not_guess_near_month(self):
        wizard = StrategyWizard(self.window.state, self.window)
        wizard.market.setCurrentIndex(1)
        wizard.expiry_action.setCurrentIndex(wizard.expiry_action.findData('ROLL'))
        self.assertEqual(wizard.roll_contract.count(), 0)
        with self.assertRaises(ValueError):
            wizard.form()
        wizard.deleteLater()

    def test_broker_settings_send_only_typed_references_and_never_enable_execution(self):
        panel = self.window.broker_panel
        self.assertFalse(panel.group.isChecked())
        panel.fields['profile_alias'].setText('offline-test')
        panel.fields['stock_account_ref'].setText('stock-alias')
        panel.fields['broker_secret_ref'].setText('MarkAuto/v2/broker/offline-test')
        panel._edited()
        panel._save()
        self.drain()
        command = self.facade.commands[-1]
        self.assertEqual(command.action, UiAction.SAVE_BROKER_SETTINGS)
        self.assertEqual(command.broker_settings.broker_secret_ref, 'MarkAuto/v2/broker/offline-test')
        self.assertIs(command.broker_settings.environment, Environment.BROKER_SIMULATION)
        self.assertTrue(command.broker_settings.read_only)
        self.assertFalse(command.broker_settings.execution_enabled)
        count = len(self.facade.commands)
        panel._check()
        self.assertEqual(len(self.facade.commands), count)
        self.assertEqual(panel.status.text(), ui_text('v2.broker_save_first'))

    def test_broker_metadata_success_is_still_shown_as_external_pending(self):
        settings = self.window.state.broker_settings
        readiness = BrokerReadiness(
            settings.profile_alias,
            settings.environment,
            True,
            False,
            (
                ReadinessCheck('sdk_version', True, 'configuration_valid'),
                ReadinessCheck('external_account_verified', False, 'external_verification_required', True),
            ),
            datetime.now(timezone.utc),
        )
        self.window.broker_panel.apply(settings, readiness)
        self.assertEqual(self.window.broker_panel.checks.rowCount(), 2)
        self.assertIn(ui_text('v2.broker_external_pending'), self.window.broker_panel.checks.item(1, 1).text())
        self.assertIn('不代表', self.window.broker_panel.status.text())

    def test_raw_secret_pasted_in_reference_field_is_rejected_before_dispatch(self):
        panel = self.window.broker_panel
        panel.fields['broker_secret_ref'].setText('not-an-os-credential-reference')
        panel._edited()
        panel._save()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(panel.status.text(), ui_text('v2.broker_form_invalid'))

    def test_layout_at_logical_100_150_200_percent_and_keyboard_navigation(self):
        for width, height in ((1366, 768), (910, 512), (683, 384)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertLessEqual(self.window.context.geometry().right(), self.window.centralWidget().width())
            self.assertLessEqual(self.window.summary.geometry().right(), self.window.centralWidget().width())
            for page in range(6):
                self.window.navigation.setCurrentRow(page)
                self.app.processEvents()
                scroll = self.window.pages.currentWidget()
                self.assertIsInstance(scroll, QScrollArea)
                self.assertTrue(scroll.widgetResizable())
                self.assertGreater(scroll.viewport().height(), 40)
        self.window.navigation.setFocus()
        self.window.navigation.setCurrentRow(0)
        QTest.keyClick(self.window.navigation, Qt.Key.Key_Down)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        for widget in self.window.findChildren(QPushButton):
            if widget.objectName():
                self.assertTrue(widget.accessibleName(), widget.objectName())

    def test_legacy_entries_emit_navigation_without_opening_storage(self):
        routes = []
        self.window.legacy_requested.connect(routes.append)
        self.window.legacy_import_button.click()
        self.window.legacy_backtest_button.click()
        self.window.legacy_recovery_button.click()
        self.assertEqual(routes, ['data', 'backtest', 'settings'])
        self.assertEqual(self.facade.commands, [])

    def test_busy_query_does_not_queue_duplicate_mutations_or_destroy_running_worker(self):
        entered = threading.Event()
        release = threading.Event()

        def held_snapshot():
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test release missing')
            return self.facade.state

        with patch.object(self.facade, 'snapshot', side_effect=held_snapshot):
            self.window.refresh()
            self.assertTrue(entered.wait(1))
            self.window.cancel_entries_button.click()
            self.window.cancel_entries_button.click()
            self.assertEqual(self.facade.commands, [])
            self.assertFalse(self.window.close())
            self.assertTrue(self.window.isVisible())
            release.set()
            self.drain()

    def test_priority_stop_is_accepted_while_research_blocks_and_old_result_cannot_restore_running(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        initial = replace(self.facade.state, version=2, engine_state='RUNNING')
        self.facade.state = initial
        self.window.apply_state(initial)
        research_thread = [None]

        def execute(command):
            self.facade.commands.append(command)
            if command.action is UiAction.RESEARCH:
                research_thread[0] = threading.get_ident()
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test release missing')
            elif command.action is UiAction.STOP_NEW:
                self.assertEqual(command.expected_version, self.facade.state.version)
                self.facade.state = replace(self.facade.state, version=3, engine_state='STOPPED')
                stopped.set()
            return UiReceipt(True, 'completed', 'Completed')

        def snapshot():
            return initial if threading.get_ident() == research_thread[0] else self.facade.state

        try:
            with patch.object(self.facade, 'execute', side_effect=execute), patch.object(self.facade, 'snapshot', side_effect=snapshot):
                self.window.command(UiAction.RESEARCH, 'strategy-1:1')
                self.assertTrue(entered.wait(1))
                self.window.stop_button.click()
                self.window.stop_button.click()
                deadline = time.monotonic() + 2
                while self.window._priority_operation is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    QTest.qWait(5)
                self.assertTrue(stopped.is_set(), 'stop was only queued behind research')
                self.assertIsNotNone(self.window._operation, 'research should still be blocked')
                self.assertEqual(self.window.state.engine_state, 'STOPPED')
                release.set()
                self.drain()
        finally:
            release.set()
        self.assertEqual(self.window.state.version, 3)
        self.assertEqual(self.window.state.engine_state, 'STOPPED')
        self.assertEqual(sum(c.action is UiAction.STOP_NEW for c in self.facade.commands), 1)

    def test_large_font_and_short_wizard_preserve_scrollable_controls(self):
        self.window.setFont(QFont(self.window.font().family(), 20))
        self.window.resize(1366, 768)
        self.window.navigation.setCurrentRow(5)
        self.window.advanced.setChecked(True)
        self.app.processEvents()
        scroll = self.window.pages.currentWidget()
        self.assertGreater(scroll.viewport().height(), 60)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        wizard = StrategyWizard(self.window.state, self.window)
        wizard.resize(683, 384)
        wizard.show()
        for page in range(6):
            self.app.processEvents()
            page_scroll = wizard.currentPage().findChild(QScrollArea)
            self.assertIsNotNone(page_scroll)
            self.assertGreater(page_scroll.viewport().height(), 20)
            if page < 5:
                wizard.next()
        self.assertEqual(wizard.currentId(), 5)
        self.assertTrue(wizard.button(StrategyWizard.WizardButton.FinishButton).isVisible())
        wizard.reject()
        wizard.deleteLater()

    def test_initial_window_and_each_wizard_page_fit_projected_available_screen_without_shrinking_font(self):
        # Projected logical rectangles exercise geometry only. Native device
        # pixel ratio, Windows chrome and actual keyboard checks remain separate.
        for width, height in ((910, 512), (683, 384)):
            available = QRect(40, 20, width, height)
            screen = SimpleNamespace(availableGeometry=lambda: available)
            font_size = self.window.font().pointSizeF()
            with patch.object(self.window, 'screen', return_value=screen):
                self.window.resize(1180, 720)
                fit_available_screen(self.window)
                self.app.processEvents()
                self.assertTrue(available.contains(self.window.frameGeometry()), self.window.frameGeometry())
                self.assertEqual(self.window.font().pointSizeF(), font_size)
                for page in range(6):
                    self.window.navigation.setCurrentRow(page)
                    self.app.processEvents()
                    self.assertGreater(self.window.pages.currentWidget().viewport().height(), 20)
            wizard = StrategyWizard(self.window.state, self.window)
            with patch.object(wizard, 'screen', return_value=screen):
                wizard.show()
                for page in range(6):
                    self.app.processEvents()
                    fit_available_screen(wizard)
                    self.app.processEvents()
                    self.assertTrue(available.contains(wizard.frameGeometry()), wizard.frameGeometry())
                    self.assertEqual(wizard.font().pointSizeF(), font_size)
                    control = wizard.button(StrategyWizard.WizardButton.NextButton if page < 5 else StrategyWizard.WizardButton.FinishButton)
                    self.assertTrue(control.isVisible())
                    self.assertTrue(wizard.rect().contains(control.mapTo(wizard, control.rect().bottomRight())))
                    if page < 5:
                        control.click()
                self.assertEqual(wizard.currentId(), 5)
            wizard.reject()
            wizard.deleteLater()

    def test_modal_wizard_six_pages_fit_real_small_owner_even_on_larger_screen(self):
        self.window.resize(683, 384)
        self.app.processEvents()
        owner_frame = self.window.frameGeometry()
        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        wizard = StrategyWizard(self.window.state, self.window)
        wizard.setWindowModality(Qt.WindowModality.WindowModal)
        font_size = wizard.font().pointSizeF()
        with patch.object(wizard, 'screen', return_value=screen):
            wizard.show()
            for page in range(6):
                self.app.processEvents()
                fit_available_screen(wizard)
                self.app.processEvents()
                self.assertTrue(owner_frame.contains(wizard.frameGeometry()), (owner_frame, wizard.frameGeometry()))
                self.assertEqual(wizard.font().pointSizeF(), font_size)
                self.assertGreaterEqual(font_size, 11)
                scroll = wizard.currentPage().findChild(QScrollArea)
                self.assertIsNotNone(scroll)
                self.assertGreater(scroll.viewport().height(), 20)
                control = wizard.button(StrategyWizard.WizardButton.NextButton if page < 5 else StrategyWizard.WizardButton.FinishButton)
                self.assertTrue(control.isVisible())
                self.assertTrue(owner_frame.contains(control.mapToGlobal(control.rect().bottomRight())))
                if page < 5:
                    control.click()
            self.assertEqual(wizard.currentId(), 5)
        wizard.reject()
        wizard.deleteLater()
