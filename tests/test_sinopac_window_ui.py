"""Connection control revision and pending intents never replace a viewed book."""

from dataclasses import replace
from decimal import Decimal
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QWidget

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.sinopac_ui import CONNECTION_ACTIONS
from desktop_app.shell.theme import _apply_trading_page_theme
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import SinopacConnectionView, UiAction, UiReceipt
from quantlab.trading.domain.models import Environment
from tests import test_m2_trading_page as support
from tests.test_sinopac_panel_ui import connected_view


class ConnectionFacade(support.EnvironmentSwitchFacade):
    def __init__(self):
        super().__init__()
        self.hold_connection, self.reject_connection = False, False
        self.connection_entered, self.connection_release = Event(), Event()

    def execute(self, command):
        if command.action not in CONNECTION_ACTIONS:
            return super().execute(command)
        self.commands.append(command)
        self.connection_entered.set()
        if self.hold_connection and not self.connection_release.wait(2):
            raise TimeoutError('fixture release was not set')
        view = self.state.sinopac_connection
        if (command.connection_revision, command.connection_generation) != (view.revision, view.generation):
            return UiReceipt(False, 'state_conflict', '')
        if self.reject_connection:
            changed = replace(view, revision=view.revision + 1, error_code='broker_permission_missing')
            self.state = replace(self.state, sinopac_connection=changed)
            return UiReceipt(False, 'broker_permission_missing', 'UNSAFE_VENDOR_MESSAGE')
        if command.action is UiAction.SAVE_AND_CONNECT_SINOPAC:
            changed = replace(view, settings=command.sinopac_settings, revision=view.revision + 1, generation='fixture-generation', phase='CONNECTING')
        elif command.action is UiAction.SELECT_SINOPAC_ACCOUNTS:
            changed = replace(
                view,
                revision=view.revision + 1,
                accounts=tuple(replace(account, selected=account.alias in command.sinopac_accounts) for account in view.accounts),
            )
        elif command.action is UiAction.ACTIVATE_SINOPAC_CA:
            changed = replace(view, revision=view.revision + 1, settings=command.sinopac_settings, certificate_status='READY')
        else:
            changed = SinopacConnectionView(settings=view.settings, revision=view.revision + 1, generation=view.generation)
        self.state = replace(self.state, sinopac_connection=changed)
        return UiReceipt(True, 'connection_pending' if changed.phase == 'CONNECTING' else 'completed', '')


class SinopacWindowUiTests(unittest.TestCase):
    setUpClass = classmethod(support.M2TradingPageTests.setUpClass.__func__)
    tearDown = support.M2TradingPageTests.tearDown
    drain = support.M2TradingPageTests.drain

    def setUp(self):
        self.facade = ConnectionFacade()
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        _apply_trading_page_theme(self.window)
        self.window.navigation.setCurrentRow(5)
        self.window.show()
        self.app.processEvents()

    def _connected(self):
        self.facade.state = replace(self.facade.state, sinopac_connection=connected_view())
        self.window.apply_state(self.facade.state)

    def test_only_one_connection_form_and_one_primary_without_old_hidden_controls(self):
        self.assertEqual(
            CONNECTION_ACTIONS, {UiAction.SAVE_AND_CONNECT_SINOPAC, UiAction.SELECT_SINOPAC_ACCOUNTS, UiAction.ACTIVATE_SINOPAC_CA, UiAction.DISCONNECT_SINOPAC}
        )
        page = self.window.pages.widget(5)
        primaries = [button for button in page.findChildren(QPushButton) if button.property('role') == 'primary']
        self.assertEqual([button.objectName() for button in primaries], ['sinopac_save_connect'])
        names = {widget.objectName() for widget in page.findChildren(QPushButton)}
        self.assertTrue(names.isdisjoint({'market_data_save', 'market_data_connect', 'broker_save_button', 'broker_check_button', 'connect_read_only_button'}))
        self.assertIsNone(page.findChild(QLabel, 'market_data_status'))
        self.assertEqual(self.window.broker_panel.view.phase, 'DISCONNECTED')
        self.assertFalse(self.window.advanced.isChecked())
        self.assertFalse(self.window.add_context_button.isVisibleTo(page))

    def test_pending_rpc_remains_responsive_and_never_changes_local_book_or_selectors(self):
        self.facade.hold_connection = True
        original = self.window.state.positions
        heartbeat = []
        try:
            self.window.broker_panel.save_connect.click()
            self.assertTrue(self.facade.connection_entered.wait(1))
            QTimer.singleShot(0, lambda: heartbeat.append(True))
            QTest.qWait(15)
            self.app.processEvents()
            self.assertEqual(heartbeat, [True])
            self.assertFalse(self.window.broker_panel.save_connect.isEnabled())
            self.assertNotIn(ui_text('m2.connection.connected'), self.window.broker_panel.status.text())
            for selector in (self.window.environment, self.window.trading_environment):
                self.assertIs(Environment(selector.currentData()), Environment.LOCAL)
            self.assertEqual(self.window.state.positions, original)
        finally:
            self.facade.connection_release.set()
        self.drain()
        self.assertEqual(self.window.state.sinopac_connection.phase, 'CONNECTING')
        self.assertIn(ui_text('m2.connection.pending'), self.window.broker_panel.status.text())
        self.assertEqual(self.window.state.version, 1)
        self.assertEqual(self.window.state.positions, original)

    def test_connection_revision_updates_before_same_book_and_market_only_shortcuts(self):
        original = self.window.state.positions
        self._connected()
        self.assertIn(ui_text('m2.connection.connected'), self.window.broker_panel.status.text())
        self.assertEqual(self.window.state.version, 1)
        newer = replace(connected_view(2), accounts=(replace(connected_view().accounts[0], signed=None),))
        self.facade.state = replace(self.facade.state, market_revision=1, sinopac_connection=newer)
        self.window.apply_state(self.facade.state)
        self.assertIn(ui_text('m2.connection.signed_unknown'), self.window.broker_panel.account_boxes['stock-1'].text())
        self.window.apply_state(replace(self.facade.state, sinopac_connection=connected_view(1)))
        self.assertEqual(self.window.state.sinopac_connection.revision, 2)
        self.assertEqual(self.window.state.positions, original)
        self.assertIs(self.window.state.environment, Environment.LOCAL)

    def test_refusal_and_no_reply_do_not_claim_success_or_echo_vendor_details(self):
        self.facade.reject_connection = True
        self.window.broker_panel.save_connect.click()
        self.drain()
        self.assertIn(ui_text('m2.connection.permission_denied'), self.window.broker_panel.status.text())
        self.assertFalse(self.window.broker_panel.account_boxes)
        for label in self.window.findChildren(QLabel):
            self.assertNotIn('UNSAFE_VENDOR_MESSAGE', label.text())
        self._connected()
        self.facade.failure = True
        try:
            self.window.refresh()
            self.drain()
            self.assertIn(ui_text('m2.connection.outcome_unknown'), self.window.broker_panel.status.text())
            self.assertIn(ui_text('m2.connection.unknown'), self.window.broker_panel.readiness_labels['market'].text())
        finally:
            self.facade.failure = False

    def test_account_mutations_use_accepted_cas_and_never_optimistically_select(self):
        self._connected()
        panel = self.window.broker_panel
        self.facade.hold_connection = True
        try:
            panel.account_boxes['future-1'].setFocus()
            QTest.keyClick(panel.account_boxes['future-1'], Qt.Key.Key_Space)
            self.assertTrue(self.facade.connection_entered.wait(1))
            self.assertFalse(panel.account_boxes['future-1'].isChecked())
            self.assertFalse(panel.account_boxes['future-1'].isEnabled())
        finally:
            self.facade.connection_release.set()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.SELECT_SINOPAC_ACCOUNTS)
        self.assertEqual(command.sinopac_accounts, ('stock-1', 'future-1'))
        self.assertEqual((command.connection_revision, command.connection_generation), (1, 'fixture-generation'))
        self.assertTrue(panel.account_boxes['future-1'].isChecked())
        self.assertIs(self.window.state.environment, Environment.LOCAL)

    def test_fee_and_connection_draft_survive_polls_then_follow_accepted_persistence(self):
        panel = self.window.broker_panel
        panel.fee_group.setChecked(True)
        panel.fee_discount.selectAll()
        QTest.keyClicks(panel.fee_discount, '0.25')
        self.window.apply_state(replace(self.window.state, market_revision=1))
        self.assertEqual(panel.settings().fee_discount, Decimal('0.25'))
        panel.save_connect.click()
        self.drain()
        self.assertEqual(self.facade.commands[-1].sinopac_settings.fee_discount, Decimal('0.25'))
        self.assertFalse(panel.dirty)
        restored = TradingWindow(self.facade, self.facade.snapshot())
        restored.poll.stop()
        restored.setProperty('allow_close_for_tests', True)
        try:
            self.assertEqual(restored.broker_panel.fee_discount.text(), '0.25')
        finally:
            restored.close()
            restored.deleteLater()

    def test_book_navigation_keeps_connection_draft_and_never_implicitly_connects(self):
        panel = self.window.broker_panel
        panel.environment.setCurrentIndex(panel.environment.findData(Environment.LIVE))
        self.assertTrue(panel.dirty)
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.trading_environment.setCurrentIndex(self.window.trading_environment.findData(Environment.BROKER_SIMULATION))
        self.drain()
        self.assertIs(self.window.state.environment, Environment.BROKER_SIMULATION)
        self.assertIs(Environment(panel.environment.currentData()), Environment.LIVE)
        self.assertTrue(panel.dirty)
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.SWITCH_CONTEXT])

    def test_certificate_and_disconnect_routes_preserve_references_cas_and_default_cancel(self):
        self._connected()
        panel = self.window.broker_panel
        panel.certificate_group.setChecked(True)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('C:/fake/account.pfx', '')):
            panel.choose_certificate.click()
        panel.activate_certificate.click()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.ACTIVATE_SINOPAC_CA)
        self.assertEqual(command.sinopac_settings.certificate_path, 'C:/fake/account.pfx')
        self.assertEqual((command.connection_revision, command.connection_generation), (1, 'fixture-generation'))
        self.assertEqual(panel.view.certificate_status, 'READY')
        defaults = []

        def cancel(dialog):
            defaults.append(dialog.defaultButton().text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            panel.disconnect_button.click()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(defaults, [ui_text('v2.cancel')])
        with patch.object(self.window, '_confirm', return_value=True):
            panel.disconnect_button.click()
        self.drain()
        self.assertIs(self.facade.commands[-1].action, UiAction.DISCONNECT_SINOPAC)
        self.assertEqual(panel.view.phase, 'DISCONNECTED')

    def test_settings_at_both_sizes_and_keyboard_help_preserve_full_explanation(self):
        self._connected()
        panel = self.window.broker_panel
        for width, height in ((1366, 768), (1920, 1080)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertEqual((self.window.width(), self.window.height()), (width, height))
            page = self.window.pages.widget(5)
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)
            for widget in (panel.key_ref, panel.environment, *panel.account_boxes.values()):
                page.ensureWidgetVisible(widget)
                self.app.processEvents()
                self.assertLessEqual(widget.width(), page.viewport().width())
                self.assertTrue(widget.accessibleName())
            row = self.window.findChild(QWidget, 'sinopac_connection_help_row')
            row.button.setFocus()
            QTest.keyClick(row.button, Qt.Key.Key_Space)
            self.app.processEvents()
            self.assertTrue(row.dialog.isVisible())
            self.assertEqual(row.details.text(), ui_text('m2.connection.help_full'))
            self.assertGreaterEqual(row.details.height(), row.details.heightForWidth(row.details.width()))
            self.assertEqual(row.details.textFormat(), Qt.TextFormat.PlainText)
            QTest.keyClick(row.dialog, Qt.Key.Key_Escape)
            self.assertFalse(row.dialog.isVisible())

    def test_refused_account_selection_restores_accepted_checks_and_explains_failure(self):
        self._connected()
        self.facade.reject_connection = True
        panel = self.window.broker_panel
        panel.account_boxes['future-1'].setFocus()
        QTest.keyClick(panel.account_boxes['future-1'], Qt.Key.Key_Space)
        self.drain()
        self.assertFalse(panel.account_boxes['future-1'].isChecked())
        self.assertTrue(panel.account_boxes['stock-1'].isChecked())
        self.assertIn(ui_text('m2.connection.permission_denied'), panel.status.text())
        self.assertEqual(self.window.state.sinopac_connection.accounts, connected_view().accounts)
