"""Empty accepted product catalogues give a visible, read-only next step."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWizard
import shiboken6

from desktop_app.features.trading.wizard import StrategyWizard
from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Environment, HoldingKind
from tests import test_trading_ui as support


class EmptyMarketWizardTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)

    def tearDown(self):
        shiboken6.delete(self.wizard)
        self.app.processEvents()

    def show_market(self, environment, phase='DISCONNECTED', *, products=()):
        state = support.state_fixture()
        state = replace(state, environment=environment, strategy_products=products, sinopac_connection=replace(state.sinopac_connection, phase=phase))
        self.wizard = StrategyWizard(state)
        self.wizard.show()
        self.app.processEvents()
        self.assertTrue(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())
        self.wizard.next()
        self.app.processEvents()

    def test_disconnected_empty_catalogue_explains_connection_and_blocks_next(self):
        self.show_market(Environment.BROKER_SIMULATION)
        self.assertEqual(self.wizard.currentId(), 1)
        self.assertEqual(self.wizard.market.count(), 0)
        self.assertTrue(self.wizard.market_empty.isVisible())
        self.assertEqual(self.wizard.market_empty_reason.text(), ui_text('strategy.empty.disconnected'))
        self.assertFalse(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())
        QTest.keyClick(self.wizard, Qt.Key.Key_Return)
        self.assertEqual(self.wizard.currentId(), 1)
        self.assertIsNone(self.wizard.accepted_form)

    def test_connected_empty_catalogue_does_not_claim_login_failure(self):
        self.show_market(Environment.BROKER_SIMULATION, 'CONNECTED')
        self.assertEqual(self.wizard.market_empty_reason.text(), ui_text('strategy.empty.catalog'))
        self.assertFalse(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())

    def test_local_empty_catalogue_does_not_require_broker_login(self):
        self.show_market(Environment.LOCAL)
        self.assertEqual(self.wizard.market_empty_reason.text(), ui_text('strategy.empty.local'))
        self.assertEqual(self.wizard.market_empty_reason.accessibleName(), self.wizard.market_empty_reason.text())

    def test_keyboard_settings_closes_without_accepting_a_strategy(self):
        self.show_market(Environment.BROKER_SIMULATION)
        self.wizard.market_settings.setFocus()
        QTest.keyClick(self.wizard.market_settings, Qt.Key.Key_Space)
        self.assertEqual(self.wizard.market_settings.accessibleName(), ui_text('strategy.empty.settings'))
        self.assertTrue(self.wizard.open_settings_requested)
        self.assertEqual(self.wizard.result(), QWizard.DialogCode.Rejected)
        self.assertIsNone(self.wizard.accepted_form)

    def test_nonempty_and_filtered_catalogue_update_page_completeness(self):
        product = support.state_fixture().strategy_products[0]
        self.show_market(Environment.LOCAL, products=(product,))
        self.assertTrue(self.wizard.market_empty.isHidden())
        self.assertTrue(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())
        self.wizard.back()
        self.wizard.policy.setCurrentIndex(self.wizard.policy.findData(HoldingKind.INTRADAY))
        self.wizard.next()
        self.assertFalse(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())
        self.assertEqual(self.wizard.market_empty_reason.text(), ui_text('u3.no_products'))
        self.wizard.back()
        self.wizard.policy.setCurrentIndex(self.wizard.policy.findData(HoldingKind.SWING))
        self.wizard.next()
        self.assertTrue(self.wizard.button(QWizard.WizardButton.NextButton).isEnabled())


class EmptyMarketNavigationTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    setUp = support.TradingUiTests.setUp
    tearDown = support.TradingUiTests.tearDown
    drain = support.TradingUiTests.drain

    def test_settings_route_sends_nothing_and_does_not_keep_empty_snapshot(self):
        original = self.window.state
        self.window.apply_state(replace(original, version=original.version + 1, strategy_products=()))

        def open_settings(wizard):
            wizard._open_settings()
            return wizard.result()

        with patch.object(StrategyWizard, 'exec', open_settings):
            self.window.new_strategy()
        self.assertEqual(self.window.navigation.currentRow(), 5)
        self.assertIsNone(self.window._pending_wizard)
        self.assertEqual(self.facade.commands, [])
        self.window.apply_state(replace(original, version=self.window.state.version + 1))

        def reopen(wizard):
            self.assertGreater(wizard.market.count(), 0)
            self.assertFalse(wizard.open_settings_requested)
            return QWizard.DialogCode.Rejected

        with patch.object(StrategyWizard, 'exec', reopen):
            self.window.new_strategy()
        self.assertEqual(self.facade.commands, [])
