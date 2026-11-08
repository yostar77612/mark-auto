"""Real manual widgets and workers using typed fakes; no SDK or order transport."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.manual_intents import MANUAL_ACTIONS
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import OrderView, UiAction, UiReceipt
from quantlab.trading.application.manual_contracts import (
    ManualInstrumentView,
    ManualPendingView,
    ManualPreviewView,
    ManualPurpose,
    ManualScope,
    ManualTradingView,
)
from quantlab.trading.domain.models import Environment, Market, QuantityUnit, Side
from tests import test_trading_ui as support


class ManualFacade(support.RecordingFacade):
    def __init__(self):
        super().__init__()
        scope = ManualScope('sim-book', 1, Environment.BROKER_SIMULATION, 'sim-stock', 'login-generation', 2)
        instrument = ManualInstrumentView(
            'TWSE:2330',
            '2330 台積電',
            Market.STOCK,
            QuantityUnit.SHARE,
            1000,
            1000,
            Decimal('1'),
            bid=Decimal('40'),
            ask=Decimal('41'),
            quote_at=datetime.now(timezone.utc),
            tradable=True,
        )
        manual = ManualTradingView(
            scope=scope,
            book_id='manual-1',
            capital=Decimal('60000'),
            available_cash=Decimal('60000'),
            confirmed=True,
            halted=False,
            reasons=(),
            instruments=(instrument,),
            can_preview=True,
            can_submit=True,
            can_test=True,
            can_mutate=True,
            manual_order_ids=('owned-order',),
        )
        self.state = replace(
            self.state,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            environment=scope.environment,
            account_ref=scope.account_ref,
            manual=manual,
            sinopac_connection=replace(self.state.sinopac_connection, generation=scope.connection_generation, revision=scope.connection_revision),
            orders=(OrderView('owned-order', 'TWSE:2330', Side.BUY, 1000, 0, QuantityUnit.SHARE, 'ACCEPTED', False, scope.account_ref),),
        )
        self.unknown = False
        self.entered, self.release = Event(), Event()
        self.hold = False

    def execute(self, command):
        self.commands.append(command)
        if self.hold:
            self.entered.set()
            if not self.release.wait(2):
                raise TimeoutError('fake release missing')
        if command.action is UiAction.PREVIEW_MANUAL or command.action is UiAction.TEST_SIM_ORDER and command.manual_order is None:
            order = command.manual_order
            instrument = next((item for item in self.state.manual.instruments if order and item.instrument_id == order.instrument_id), None)
            now = datetime.now(timezone.utc)
            preview = ManualPreviewView(
                self.state.manual.scope,
                order.request_id if order else 'diagnostic-request',
                'preview-receipt',
                order.instrument_id if order else 'TAIFEX:TMF:202611',
                order.side if order else Side.BUY,
                order.quantity if order else 1,
                order.limit_price if order else Decimal('20000'),
                order.stop_price if order else Decimal('19990'),
                ManualPurpose.MANUAL if order else ManualPurpose.DIAGNOSTIC_TMF,
                True,
                Decimal('40001'),
                Decimal('100'),
                Decimal('1'),
                Decimal('60000'),
                'APP_VIRTUAL_SIMULATION',
                'fake-cost-v1',
                now,
                now + timedelta(seconds=30),
                quantity_unit=instrument.quantity_unit if instrument else QuantityUnit.CONTRACT if order is None else None,
                lot_size=instrument.lot_size if instrument else 1,
                bid=instrument.bid if instrument else None,
                ask=instrument.ask if instrument else None,
            )
            self.state = replace(self.state, manual=replace(self.state.manual, preview=preview))
            return UiReceipt(True, 'completed', '', preview.preview_id)
        intent = command.manual_order or command.manual_mutation
        if intent is not None and not self.unknown:
            result = ManualPendingView(intent.scope, intent.request_id, command.action.value, outcome_known=True)
            self.state = replace(self.state, manual=replace(self.state.manual, last_result=result))
        return UiReceipt(not self.unknown, 'outcome_unknown' if self.unknown else 'completed', '', 'owned-order')


class ManualUiTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    drain = support.TradingUiTests.drain
    tearDown = support.TradingUiTests.tearDown

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = ManualFacade()
        self.window = TradingWindow(self.facade, self.facade.state)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.navigation.setCurrentRow(3)
        self.window.show()
        self.app.processEvents()
        self.controls = self.window.manual_controls
        self.form = self.controls.form
        self.form.price.setText('40')
        self.form.stop.setText('39.9')

    def _preview(self):
        self.form.preview_button.click()
        self.drain()
        self.assertTrue(self.form.submit.isEnabled())

    def test_whole_lots_preview_then_same_identity_confirmed_submit(self):
        self.form.quantity.setValue(2)
        self._preview()
        first = self.facade.commands[-1]
        self.assertEqual(first.manual_order.quantity, 2000)
        self.assertEqual(first.manual_order.limit_price, Decimal('40'))
        self.assertFalse(first.manual_order.confirmed)
        with patch.object(self.window, '_confirm', return_value=True) as confirm:
            self.form.submit.click()
        self.drain()
        sent = self.facade.commands[-1]
        self.assertIs(sent.action, UiAction.SUBMIT_MANUAL)
        self.assertEqual(sent.manual_order.request_id, first.manual_order.request_id)
        self.assertEqual(sent.manual_order.preview_id, 'preview-receipt')
        self.assertEqual(sent.connection_generation, 'login-generation')
        self.assertEqual(sent.connection_revision, 2)
        self.assertTrue(sent.manual_order.confirmed)
        self.assertIn(ui_text('m2m.submit_warning'), confirm.call_args.args[0])
        self.assertFalse(self.form.submit.isEnabled())
        self.form.submit.click()
        self.assertEqual(len(self.facade.commands), 2)

    def test_live_and_local_refuse_widget_actions_and_live_programmatic_intents(self):
        for environment in (Environment.LIVE, Environment.LOCAL):
            self.window.apply_state(replace(self.window.state, environment=environment))
            for control in (self.form.prepare, self.form.preview_button, self.form.submit, self.form.test_order, self.controls.cancel, self.controls.amend):
                self.assertFalse(control.isEnabled())
                control.click()
            for action in MANUAL_ACTIONS:
                self.window.command(action)
            self.assertEqual(self.facade.commands, [])

    def test_diagnostic_preparation_never_confirms_and_cancel_sends_no_order(self):
        self.facade.state = replace(self.facade.state, manual=replace(self.facade.state.manual, can_submit=False, reasons=('manual_test_required',)))
        self.window.apply_state(self.facade.state)
        self.form.test_order.click()
        self.drain()
        self.assertIsNone(self.facade.commands[-1].manual_order)
        self.assertIn('TMF', self.form.preview.text())
        with patch.object(self.window, '_confirm', return_value=False) as confirm:
            self.form.submit.click()
        self.assertIn(ui_text('m2m.test_warning'), confirm.call_args.args[0])
        self.assertEqual(len(self.facade.commands), 1)
        with patch.object(self.window, '_confirm', return_value=True):
            self.form.submit.click()
        self.drain()
        sent = self.facade.commands[-1]
        self.assertIs(sent.action, UiAction.TEST_SIM_ORDER)
        self.assertIs(sent.manual_order.purpose, ManualPurpose.DIAGNOSTIC_TMF)
        self.assertEqual(sent.manual_order.quantity, 1)
        self.assertEqual(sent.manual_order.request_id, 'diagnostic-request')

    def test_nested_account_or_revision_change_refuses_reviewed_order(self):
        self._preview()

        def switch():
            self.window.apply_state(replace(self.window.state, account_ref='other-account'))
            return True

        with patch.object(self.window, '_confirm', side_effect=lambda _text: switch()):
            self.form.submit.click()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(self.window.notice.text(), ui_text('v2.state_conflict'))

    def test_unknown_retains_request_across_empty_projection_and_relogin(self):
        self._preview()
        self.facade.unknown = True
        with patch.object(self.window, '_confirm', return_value=True):
            self.form.submit.click()
        self.drain()
        request = self.facade.commands[-1].manual_order
        self.assertIn(request.request_id, self.controls.intents.pending)
        for change in ({}, {'scope': replace(request.scope, connection_generation='next-login')}):
            self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, preview=None, pending=None, **change)))
            self.assertFalse(self.form.preview_button.isEnabled())
            self.assertFalse(self.form.test_order.isEnabled())
        result = ManualPendingView(request.scope, request.request_id, 'submit', outcome_known=True)
        self.window.apply_state(replace(self.facade.state, manual=replace(self.facade.state.manual, last_result=result)))
        self.assertNotIn(request.request_id, self.controls.intents.pending)
        self.assertTrue(self.form.preview_button.isEnabled())

    def test_selected_owned_order_cancel_and_price_only_amend(self):
        self.window.orders.selectRow(0)
        self.assertTrue(self.controls.cancel.isEnabled())
        with patch.object(self.window, '_confirm', return_value=True):
            self.controls.cancel.click()
        self.drain()
        cancelled = self.facade.commands[-1].manual_mutation
        self.assertEqual(cancelled.order_id, 'owned-order')
        self.assertIsNone(cancelled.quantity)
        with (
            patch('desktop_app.features.trading.manual_actions.QInputDialog.getText', return_value=('41', True)),
            patch.object(self.window, '_confirm', return_value=True),
        ):
            self.controls.amend.click()
        self.drain()
        amended = self.facade.commands[-1].manual_mutation
        self.assertEqual(amended.price, Decimal('41'))
        self.assertIsNone(amended.quantity)
        self.assertNotEqual(amended.request_id, cancelled.request_id)

    def test_worker_delay_preserves_timer_responsiveness_and_duplicate_click_guard(self):
        self.facade.hold = True
        ticks = []
        timer = QTimer(self.window)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(1)
        try:
            self.form.test_order.click()
            self.assertTrue(self.facade.entered.wait(1))
            self.form.test_order.click()
            QTest.qWait(20)
            self.assertEqual(len(self.facade.commands), 1)
            self.assertFalse(self.form.test_order.isEnabled())
            self.assertTrue(ticks)
        finally:
            self.facade.release.set()
            timer.stop()
        self.drain()

    def test_preview_reply_cannot_authorize_a_different_edited_draft(self):
        self.facade.hold = True
        try:
            self.form.preview_button.click()
            self.assertTrue(self.facade.entered.wait(1))
            self.assertFalse(self.form.price.isEnabled())
            self.form.price.setText('42')
        finally:
            self.facade.release.set()
        self.drain()
        self.assertFalse(self.form.submit.isEnabled())
        self.assertEqual(self.form.price.text(), '42')
        self.assertEqual(len(self.facade.commands), 1)

    def test_expired_preview_or_new_book_version_cannot_submit(self):
        self._preview()
        preview = self.window.state.manual.preview
        expired = replace(preview, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, preview=expired)))
        self.assertFalse(self.form.submit.isEnabled())
        self.window.apply_state(replace(self.facade.state, version=self.facade.state.version + 1))
        self.assertFalse(self.form.submit.isEnabled())
        self.assertEqual(len(self.facade.commands), 1)

    def test_preparation_and_resume_require_explicit_unchanged_virtual_book(self):
        manual = replace(self.facade.state.manual, book_id='', confirmed=False, can_prepare=True, suggested_capital=Decimal('40000'))
        self.facade.state = replace(self.facade.state, manual=manual)
        self.window.apply_state(self.facade.state)
        self.form.capital.setText('35000')
        with patch.object(self.window, '_confirm', return_value=False):
            self.form.prepare.click()
        self.assertEqual(self.facade.commands, [])
        with patch.object(self.window, '_confirm', return_value=True):
            self.form.prepare.click()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.ENABLE_MANUAL_BOOK)
        self.assertEqual(command.manual_book.capital, Decimal('35000'))
        self.assertTrue(command.manual_book.confirmed)
        self.facade.state = replace(self.facade.state, manual=replace(manual, confirmed=True, halted=True, capital=Decimal('35000')))
        self.window.apply_state(self.facade.state)
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.resume_button.click()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.RESUME)
        self.assertEqual(command.manual_book.capital, Decimal('35000'))
        self.assertTrue(command.manual_book.confirmed)

    def test_native_confirmation_defaults_to_cancel_and_escape_sends_nothing(self):
        self._preview()
        observed = []

        def cancel():
            dialog = QApplication.activeModalWidget()
            observed.append((isinstance(dialog, QMessageBox), dialog.defaultButton() == dialog.button(QMessageBox.StandardButton.Cancel)))
            QTest.keyClick(dialog, Qt.Key.Key_Escape)

        def submit_from_application_loop():
            QTimer.singleShot(0, cancel)
            self.form.submit.click()
            self.app.quit()

        # Earlier fixtures may have exited the shared app. A real application
        # loop resets that state before the native nested confirmation loop.
        self.app.exit(0)
        QTimer.singleShot(0, submit_from_application_loop)
        self.assertEqual(self.app.exec(), 0)
        self.assertEqual(observed, [(True, True)])
        self.assertEqual(len(self.facade.commands), 1)

    def test_worker_exception_retains_pending_until_exact_known_result(self):
        self._preview()
        with patch.object(self.facade, 'execute', side_effect=ConnectionError('fake unavailable')), patch.object(self.window, '_confirm', return_value=True):
            self.form.submit.click()
            self.drain()
        self.assertEqual(len(self.controls.intents.pending), 1)
        self.assertFalse(self.form.preview_button.isEnabled())
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, preview=None, pending=None)))
        self.assertEqual(len(self.controls.intents.pending), 1)

    def test_missing_manual_projection_retains_unknown_warning_and_refuses_bare_resume(self):
        self.controls.intents.pending['uncertain-request'] = self.window.state.manual.scope
        self.window.apply_state(replace(self.window.state, manual=ManualTradingView()))
        self.assertIn(ui_text('m2m.pending'), self.form.status.text())
        self.assertFalse(self.window.resume_button.isEnabled())
        self.controls.resume()
        self.assertEqual(self.facade.commands, [])

    def test_resume_rechecks_unknown_arriving_inside_confirmation(self):
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, halted=True)))

        def unknown(_text):
            manual = self.window.state.manual
            pending = ManualPendingView(manual.scope, 'other-request', 'submit')
            self.window.apply_state(replace(self.window.state, manual=replace(manual, pending=pending)))
            return True

        with patch.object(self.window, '_confirm', side_effect=unknown):
            self.controls.resume()
        self.drain()
        self.assertEqual(self.facade.commands, [])

    def test_false_receipt_without_matching_known_result_never_clears_unknown(self):
        self._preview()
        order = self.facade.commands[-1].manual_order
        self.controls.intents.pending[order.request_id] = order.scope
        command = replace(self.facade.commands[-1], action=UiAction.SUBMIT_MANUAL, manual_order=replace(order, confirmed=True))
        for code in ('outcome_unknown', 'operation_failed', 'journal_failed', 'ownership_conflict', 'state_conflict'):
            self.controls.received(command, self.window.state, UiReceipt(False, code, ''))
            self.assertIn(order.request_id, self.controls.intents.pending, code)

    def test_diagnostic_results_and_reasons_are_distinct_at_same_book_version(self):
        observed = []
        for status, reason in (('PASSED', ''), ('FAILED', 'broker_rejected'), ('UNKNOWN', 'outcome_unknown')):
            self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, test_status=status, test_reason=reason)))
            observed.append(self.form.status.text())
        self.assertEqual(len(set(observed)), 3)

    def test_manual_commands_keep_accepted_epoch_without_navigation_choices(self):
        from quantlab.trading.application.contracts import ManualBookForm

        self.assertEqual(self.window.state.contexts, ())
        book = ManualBookForm(self.window.state.manual.scope, Decimal('60000'), True)
        with patch.object(self.window, '_run') as dispatch:
            for action in MANUAL_ACTIONS:
                self.window.command(action)
                command = dispatch.call_args.args[0]
                self.assertEqual(command.context_id, self.window.state.context_id)
                self.assertEqual(command.context_epoch, self.window.state.context_epoch)
            self.window.command(UiAction.RESUME, manual_book=book)
            self.assertEqual(dispatch.call_args.args[0].context_epoch, book.scope.context_epoch)

    def test_pending_book_capital_cannot_diverge_from_accepted_amount(self):
        self.facade.state = replace(self.facade.state, manual=replace(self.facade.state.manual, confirmed=False, can_prepare=True))
        self.window.apply_state(self.facade.state)
        self.form.capital.setText('35000')
        original = self.facade.execute

        def accept_book(command):
            receipt = original(command)
            self.facade.state = replace(self.facade.state, manual=replace(self.facade.state.manual, capital=command.manual_book.capital, confirmed=True))
            return receipt

        self.facade.hold = True
        try:
            with patch.object(self.facade, 'execute', side_effect=accept_book), patch.object(self.window, '_confirm', return_value=True):
                self.form.prepare.click()
                self.assertTrue(self.facade.entered.wait(1))
                self.assertFalse(self.form.capital.isEnabled())
                self.form.capital.setText('37000')
                self.facade.release.set()
                self.drain()
        finally:
            self.facade.release.set()
        self.assertFalse(self.form.capital.isEnabled())
        self.assertEqual(self.form.capital.text(), '35000')
        self.assertEqual(self.window.state.manual.capital, Decimal('35000'))

    def test_empty_simulation_tables_go_to_manual_form_or_connection(self):
        self.window.apply_state(replace(self.window.state, version=2, positions=(), orders=()))
        self.window.orders_empty.next.click()
        self.app.processEvents()
        self.assertEqual(self.window.navigation.currentRow(), 3)
        self.assertTrue(self.form.instrument.hasFocus())
        self.window.apply_state(replace(self.window.state, version=3, manual=ManualTradingView()))
        self.window.orders_empty.next.click()
        self.assertEqual(self.window.navigation.currentRow(), 5)
        self.window.apply_state(replace(self.window.state, version=4, environment=Environment.LOCAL))
        self.window.positions_empty.next.click()
        self.assertEqual(self.window.navigation.currentRow(), 1)

    def test_failed_poll_cannot_reuse_prior_manual_readiness(self):
        self._preview()
        self.window.orders.selectRow(0)
        with patch.object(self.facade, 'snapshot', side_effect=ConnectionError('fake unavailable')):
            self.window.refresh()
            self.drain()
        self.assertFalse(self.window._engine_reachable)
        for widget in (self.form.preview_button, self.form.submit, self.form.test_order, self.controls.cancel, self.controls.amend):
            self.assertFalse(widget.isEnabled())
        with patch.object(self.window, '_confirm') as confirm:
            self.controls._submit()
            self.controls._mutate(False)
            self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, halted=True)))
            self.controls.resume()
            confirm.assert_not_called()
        self.assertEqual(len(self.facade.commands), 1)
        self.window.refresh()
        self.drain()
        self.assertTrue(self.window._engine_reachable)
        self.assertTrue(self.form.submit.isEnabled())

    def test_connection_presentation_revision_never_replaces_manual_native_scope(self):
        native = self.facade.state.manual.scope
        self.facade.state = replace(
            self.facade.state,
            sinopac_connection=replace(self.facade.state.sinopac_connection, generation='settings-host', revision=1002),
        )
        self.window.apply_state(self.facade.state)
        self.assertTrue(self.form.preview_button.isEnabled())
        self._preview()
        with patch.object(self.window, '_confirm', return_value=True):
            self.form.submit.click()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.SUBMIT_MANUAL)
        self.assertEqual(command.manual_order.scope, native)
        self.assertEqual(command.connection_generation, native.connection_generation)
        self.assertEqual(command.connection_revision, native.connection_revision)

    def test_native_scope_change_inside_confirmation_refuses_old_preview(self):
        self._preview()

        def changed(_text):
            manual = self.window.state.manual
            self.window.apply_state(replace(self.window.state, manual=replace(manual, scope=replace(manual.scope, connection_revision=3))))
            return True

        with patch.object(self.window, '_confirm', side_effect=changed):
            self.form.submit.click()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertFalse(self.form.submit.isEnabled())

    def test_stock_diagnostic_prompt_requires_futures_without_claiming_stock_permission(self):
        manual = replace(self.facade.state.manual, can_test=False, reasons=('manual_futures_test_required',))
        self.window.apply_state(replace(self.window.state, manual=manual))
        self.assertFalse(self.form.test_order.isEnabled())
        self.assertIn('期貨帳戶', self.form.status.text())
        self.window.apply_state(replace(self.window.state, manual=replace(manual, test_status='PASSED', reasons=())))
        self.assertIn('微台已通過', self.form.status.text())
        self.assertIn('其他商品依券商回報', self.form.status.text())

    def test_preview_uses_supplied_stock_lots_futures_contracts_and_unknown_units(self):
        from desktop_app.features.trading.manual_presenter import preview_text

        self.form.quantity.setValue(2)
        self._preview()
        preview = self.window.state.manual.preview
        self.assertIn('2 張', self.form.preview.text())
        self.assertNotIn('2000 股／口', self.form.preview.text())
        self.assertIn('1 口', preview_text(replace(preview, quantity=1, quantity_unit=QuantityUnit.CONTRACT, lot_size=1)))
        self.assertIn(ui_text('watch.unknown'), preview_text(replace(preview, quantity_unit=None)))

    def test_cash_stock_sell_guides_to_explicit_position_exit(self):
        self.form.side.setCurrentIndex(self.form.side.findData(Side.SELL))
        self.assertFalse(self.form.preview_button.isEnabled())
        self.assertIn('部位頁', self.form.contract_details.text())
        self.controls._preview()
        self.assertEqual(self.facade.commands, [])
        self.form.positions_button.click()
        self.assertEqual(self.window.navigation.currentRow(), 2)

    def _owned_exit_position(self):
        manual = replace(self.facade.state.manual, halted=True, can_submit=False, can_mutate=True)
        position = replace(self.facade.state.positions[0], account_ref=manual.scope.account_ref, strategy_id=manual.book_id, sellable_quantity=1000)
        self.facade.state = replace(self.facade.state, version=2, manual=manual, positions=(position,), financial_facts_verified=False)
        self.window.apply_state(self.facade.state)
        self.window.positions.selectRow(0)
        self.assertTrue(self.window.flatten_button.isEnabled())
        return position

    def test_halted_manual_flatten_keeps_explicit_book_native_scope_and_target(self):
        position = self._owned_exit_position()
        with patch.object(self.window, '_confirm', return_value=True) as confirm:
            self.window.flatten_selected()
            self.drain()
        command = self.facade.commands[-1]
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL, UiAction.SUBMIT_MANUAL])
        self.assertEqual(command.manual_order.exit_lot_id, position.lot_id)
        self.assertIs(command.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(command.manual_order.scope, self.facade.state.manual.scope)
        self.assertTrue(command.manual_order.confirmed)
        self.assertEqual(command.manual_order.quantity, 1000)
        self.assertEqual(command.manual_order.limit_price, Decimal('40'))
        self.assertEqual(command.manual_order.request_id, self.facade.commands[0].manual_order.request_id)
        self.assertEqual(command.manual_order.preview_id, 'preview-receipt')
        self.assertEqual(command.connection_revision, 2)
        self.assertEqual(command.context_epoch, 1)
        self.assertIn('本機帳本保守估算', confirm.call_args.args[0])

    def test_manual_flatten_rejects_unknown_request_or_foreign_lot(self):
        position = self._owned_exit_position()
        self.controls.intents.pending['unknown-exit'] = self.window.state.manual.scope
        self.controls.render(self.window.state)
        self.assertFalse(self.window.flatten_button.isEnabled())
        with patch.object(self.window, '_confirm') as confirm:
            self.window.flatten_selected()
            confirm.assert_not_called()
        self.controls.intents.pending.clear()
        foreign = replace(position, strategy_id='foreign-book')
        self.window.apply_state(replace(self.window.state, version=3, positions=(foreign,)))
        self.window.positions.selectRow(0)
        self.assertFalse(self.window.flatten_button.isEnabled())
        with patch.object(self.window, '_confirm') as confirm:
            self.window.flatten_selected()
            confirm.assert_not_called()
        self.assertEqual(self.facade.commands, [])

    def test_manual_flatten_rechecks_nested_scope_change(self):
        self._owned_exit_position()

        def changed(_text):
            manual = self.window.state.manual
            self.window.apply_state(replace(self.window.state, manual=replace(manual, scope=replace(manual.scope, connection_revision=3))))
            return True

        with patch.object(self.window, '_confirm', side_effect=changed):
            self.window.flatten_selected()
            self.drain()
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL])
        self.assertFalse(self.facade.commands[0].manual_order.confirmed)

    def test_connection_readiness_explains_manual_preparation_and_risk_gates(self):
        from desktop_app.features.trading.sinopac_panel_text import reason_text

        for code, key in (
            ('manual_book_not_enabled', 'm2m.need_book'),
            ('manual_futures_test_required', 'm2m.need_futures_test'),
            ('manual_unprotected_position', 'm2m.unprotected'),
            ('stale_quote', 'm2m.stale_quote'),
            ('session_closed', 'm2m.session_closed'),
            ('risk_rejected', 'm2m.risk_rejected'),
        ):
            self.assertEqual(reason_text(code), ui_text(key), code)

    def test_typing_in_the_order_form_survives_the_background_refresh(self):
        # The one-second poll runs a read-only refresh; it must not disable the fields the user is typing in.
        self.window.show()
        self.app.processEvents()
        form = self.window.manual_controls.form
        for field in (form.price, form.stop):
            field.clear()
            field.setFocus()
            self.app.processEvents()
            self.assertTrue(field.hasFocus() and field.isEnabled())
            for digit in '12345':
                QTest.keyClick(field, Qt.Key(ord(digit)))
                self.window.refresh()
                self.assertTrue(field.isEnabled(), 'a refresh in flight disabled the field the user is typing in')
                self.drain()
                self.assertTrue(field.hasFocus(), 'focus left the field after a background refresh')
            self.assertEqual(field.text(), '12345')
