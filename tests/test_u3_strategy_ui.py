"""Typed strategy choices, explicit management and LIVE deployment guards."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
import shiboken6

from desktop_app.features.trading.wizard import StrategyWizard
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import StrategyParameters, UiAction, UiReceipt
from quantlab.trading.application.errors import ERROR_TABLE
from desktop_app.shell.theme import style_strategy_table, SIGN_ROLE
from quantlab.trading.domain.models import Environment, HoldingKind, Market
from tests import test_trading_ui as support


class TypedStrategyWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.wizard = StrategyWizard(support.state_fixture())
        self.wizard.show()
        self.app.processEvents()

    def tearDown(self):
        shiboken6.delete(self.wizard)

    def select_kind(self, kind):
        self.wizard.policy.setCurrentIndex(self.wizard.policy.findData(kind))

    def test_first_step_four_kinds_and_authoritative_defaults(self):
        self.assertEqual(self.wizard.page(0).title(), ui_text('u3.step_kind'))
        self.assertEqual(self.wizard.policy.count(), 4)
        for kind, expected in (
            (HoldingKind.SWING, (2, 10, '1d', Decimal('.03'))),
            (HoldingKind.POSITION, (10, 60, '1d', Decimal('.08'))),
            (HoldingKind.INTRADAY, (0, 0, '5m', Decimal('.01'))),
        ):
            self.select_kind(kind)
            parameters = self.wizard.options.parameters()
            self.assertEqual((self.wizard.minimum.value(), self.wizard.maximum.value(), parameters.bar_interval, parameters.stop_fraction), expected)

    def test_d6_intraday_default_is_only_tmf_swing_position_only_stocks(self):
        self.select_kind(HoldingKind.INTRADAY)
        self.assertEqual(self.wizard.market.count(), 1)
        self.assertEqual(self.wizard.market.currentData(), Market.INDEX_FUTURE)
        self.assertEqual(self.wizard.instrument.currentData(), 'TAIFEX:TMF:202611')
        self.assertFalse(self.wizard.options.stock_intraday.isChecked())
        self.assertTrue(self.wizard.options.stock_intraday.isVisible())
        self.assertFalse(self.wizard.minimum.isEnabled())
        self.assertFalse(self.wizard.maximum.isEnabled())
        for kind in (HoldingKind.SWING, HoldingKind.POSITION):
            self.select_kind(kind)
            self.assertEqual(self.wizard.market.count(), 1)
            self.assertEqual(self.wizard.market.currentData(), Market.STOCK)

    def test_stock_daytrade_needs_cancel_default_then_explicit_confirmation(self):
        self.select_kind(HoldingKind.INTRADAY)
        checkbox = self.wizard.options.stock_intraday

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIn('現股當沖資格與額度', box.text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            checkbox.setFocus()
            QTest.keyClick(checkbox, Qt.Key.Key_Space)
        self.assertFalse(checkbox.isChecked())
        self.assertEqual(self.wizard.market.findData(Market.STOCK), -1)
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes):
            checkbox.click()
        self.wizard.market.setCurrentIndex(self.wizard.market.findData(Market.STOCK))
        parameters = self.wizard.options.parameters()
        self.assertTrue(parameters.stock_intraday_enabled)
        self.assertTrue(parameters.stock_intraday_confirmed)
        self.assertEqual(parameters.instrument_rule, 'EXACT')

    def test_no_authoritative_products_does_not_invent_candidates(self):
        shiboken6.delete(self.wizard)
        self.wizard = StrategyWizard(replace(support.state_fixture(), strategy_products=()))
        self.assertEqual(self.wizard.instrument.count(), 0)
        self.assertEqual(self.wizard.account.count(), 0)
        self.wizard.accept()
        self.assertEqual(self.wizard.result(), StrategyWizard.DialogCode.Rejected)
        self.assertEqual(self.wizard.error.text(), ui_text('v2.form_invalid'))

    def test_stock_sizing_is_labelled_estimate_and_rejects_fractional_lot_expectation(self):
        quote = replace(self.wizard.state.markets[0], price=Decimal('40'))
        self.wizard.options.state = replace(self.wizard.state, markets=(quote, *self.wizard.state.markets[1:]))
        self.wizard.options.entry_amount.setText('39000')
        self.assertIn('0 張', self.wizard.options.size_hint.text())
        self.assertIn('不足一張不下單', self.wizard.options.size_hint.text())
        self.wizard.options.entry_amount.setText('60000')
        self.assertIn('1 張', self.wizard.options.size_hint.text())
        self.assertIn('未含費用', self.wizard.options.size_hint.text())

    def test_tmf_contracts_near_month_and_conservative_margin_are_explicit(self):
        self.select_kind(HoldingKind.INTRADAY)
        parameters = self.wizard.options.parameters()
        self.assertEqual((parameters.contracts, parameters.instrument_rule), (1, 'TMF_NEAR'))
        self.assertIn('50,000', self.wizard.options.size_hint.text())
        self.assertIn('配置不足', self.wizard.options.size_hint.text())
        self.assertIn('後端檢查', self.wizard.options.size_hint.text())

    def test_accept_freezes_validated_form_and_parameters(self):
        self.wizard.accept()
        self.assertEqual(self.wizard.result(), StrategyWizard.DialogCode.Accepted)
        self.assertIsInstance(self.wizard.accepted_parameters, StrategyParameters)
        self.assertEqual(self.wizard.accepted_form, self.wizard.form())


class StrategyManagementUiTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    setUp = support.TradingUiTests.setUp
    tearDown = support.TradingUiTests.tearDown
    drain = support.TradingUiTests.drain

    def select(self, **changes):
        strategy = replace(self.window.state.strategies[0], allocation=Decimal('60000'), **changes)
        state = replace(self.window.state, version=self.window.state.version + 1, strategies=(strategy,), positions=())
        self.facade.state = state
        self.window.apply_state(state)
        self.window.strategies.selectRow(0)
        return strategy

    def test_missing_research_shows_next_step_and_opens_relevant_research_tab(self):
        self.select(state='DRAFT', evidence='NONE')
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.assertIn(ui_text('u3.research_needed'), self.window.strategy_controls.details.text())
        self.window.go_strategy_research.click()
        self.assertEqual(self.window.strategy_tabs.currentIndex(), 1)
        self.assertEqual(self.facade.commands, [])

    def test_unchanged_poll_keeps_missing_evidence_and_empty_selection_disabled(self):
        self.select(state='DRAFT', evidence='NONE')
        self.window.apply_state(self.window.state)
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.window.strategies.clearSelection()
        self.window.apply_state(self.window.state)
        self.assertFalse(self.window.deploy_button.isEnabled())

    def test_composition_supplies_error_copy_stale_proof_and_financial_styling(self):
        self.window.strategy_error_texts = {code: (text.explanation, text.action) for code, text in ERROR_TABLE.items()}
        self.window.style_strategy_table = style_strategy_table
        self.select(entry_block_code='automatic_daily_execution_pending')
        self.assertIn(ERROR_TABLE['automatic_daily_execution_pending'].explanation, self.window.strategy_controls.details.text())
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.select(entry_block_code='', evidence=ERROR_TABLE['strategy_evidence_stale'].explanation)
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.select(evidence='fixture-only', today_pnl=Decimal('-1234.50'))
        self.assertEqual(self.window.strategies.item(0, 9).data(SIGN_ROLE), -1)

    def test_disable_and_delete_cancel_default_and_cancel_sends_nothing(self):
        self.select()

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            self.window.disable_strategy_button.click()
            self.window.delete_strategy_button.click()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(self.window.disable_strategy_button.property('role'), 'danger')
        self.assertEqual(self.window.delete_strategy_button.property('role'), 'danger')

    def test_clone_uses_exact_version_and_no_deployment_action(self):
        self.select()
        self.window.clone_strategy_button.click()
        self.drain()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertIs(self.facade.commands[0].action, UiAction.CLONE_STRATEGY)
        self.assertEqual(self.facade.commands[0].target_id, 'strategy-1:1')

    def test_delete_fill_refusal_disables_delete_and_keeps_disable_available(self):
        self.select()
        with (
            patch.object(self.facade, 'execute', return_value=UiReceipt(False, 'strategy_has_fills', '')),
            patch.object(self.window, '_confirm', return_value=True),
        ):
            self.window.delete_strategy_button.click()
            self.drain()
        self.assertFalse(self.window.delete_strategy_button.isEnabled())
        self.assertTrue(self.window.disable_strategy_button.isEnabled())

    def test_revise_restores_known_parameters_and_requires_explicit_direction_and_rules(self):
        parameters = StrategyParameters('1d', Decimal('.04'), Decimal('50000'))
        strategy = self.select(parameters=parameters)
        wizard = StrategyWizard(self.window.state, self.window, parent_strategy_id=strategy.strategy_id)
        try:
            self.window.strategy_controls.restore(wizard, strategy)
            self.assertEqual(wizard.options.stop.text(), '4.00')
            self.assertEqual(wizard.options.entry_amount.text(), '50000')
            self.assertEqual(wizard.direction.currentIndex(), -1)
            self.assertEqual(wizard.rules.currentIndex(), -1)
            wizard.accept()
            self.assertEqual(wizard.result(), StrategyWizard.DialogCode.Rejected)
        finally:
            shiboken6.delete(wizard)

    def test_live_and_nested_context_change_cannot_deploy(self):
        self.select()
        self.window.apply_state(replace(self.window.state, environment=Environment.LIVE))
        self.window.deploy_selected()
        self.assertEqual(self.facade.commands, [])
        self.window.apply_state(replace(self.window.state, environment=Environment.LOCAL))

        def changed(_):
            self.window.apply_state(replace(self.window.state, context_epoch=self.window.state.context_epoch + 1))
            return True

        with patch.object(self.window, '_confirm', side_effect=changed):
            self.window.deploy_selected()
        self.assertEqual(self.facade.commands, [])

    def test_six_default_columns_keep_environment_pnl_and_optional_recent_signal(self):
        self.assertEqual({i for i in range(self.window.strategies.columnCount()) if not self.window.strategies.isColumnHidden(i)}, {0, 3, 4, 5, 8, 9})
        self.select(today_pnl=Decimal('1234.50'), recent_signal='ENTRY')
        self.assertEqual(self.window.strategies.item(0, 9).text(), '1,234.50')
        self.assertEqual(self.window.strategies.item(0, 10).text(), ui_text('u3.entry_signal'))
