"""Actual preview facts and exactly-once explicit confirmation for manual exits."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import unittest

from PySide6.QtWidgets import QMessageBox

from desktop_app.features.trading.manual_presenter import preview_text, reason_text
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, UiReceipt
from tests import test_m2_manual_ui as support


class ManualExitPreviewUiTests(unittest.TestCase):
    setUpClass = classmethod(support.ManualUiTests.setUpClass.__func__)
    setUp = support.ManualUiTests.setUp
    tearDown = support.ManualUiTests.tearDown
    drain = support.ManualUiTests.drain
    _owned_exit_position = support.ManualUiTests._owned_exit_position

    def test_flatten_previews_before_cancel_default_and_cancel_never_submits(self):
        position = self._owned_exit_position()
        seen = []

        def cancel(box):
            seen.append(box.text())
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIn('40', box.text())
            self.assertIn('41', box.text())
            self.assertIn('不會自動重送', box.text())
            self.assertIn('1 張', box.text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            self.window.flatten_selected()
            self.drain()
        self.assertEqual(len(seen), 1)
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL])
        order = self.facade.commands[0].manual_order
        self.assertEqual(order.exit_lot_id, position.lot_id)
        self.assertFalse(order.confirmed)
        self.assertEqual(order.limit_price, Decimal('40'))

    def test_confirmed_exit_uses_same_request_preview_quantity_price_and_scope(self):
        position = self._owned_exit_position()
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.flatten_selected()
            self.drain()
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL, UiAction.SUBMIT_MANUAL])
        first, sent = [item.manual_order for item in self.facade.commands]
        self.assertEqual((sent.request_id, sent.exit_lot_id, sent.scope), (first.request_id, position.lot_id, first.scope))
        self.assertEqual((sent.quantity, sent.limit_price, sent.preview_id), (1000, Decimal('40'), 'preview-receipt'))
        self.assertTrue(sent.confirmed)
        self.assertFalse(self.form.submit.isEnabled())

    def test_changed_scope_during_confirmation_never_submits(self):
        self._owned_exit_position()

        def change(_):
            manual = self.window.state.manual
            self.window.apply_state(replace(self.window.state, manual=replace(manual, scope=replace(manual.scope, connection_revision=3))))
            return True

        with patch.object(self.window, '_confirm', side_effect=change):
            self.window.flatten_selected()
            self.drain()
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL])

    def test_quote_or_eligibility_missing_does_not_make_up_exit_price(self):
        self._owned_exit_position()
        instruments = tuple(replace(item, bid=None, ask=None) for item in self.window.state.manual.instruments)
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, instruments=instruments)))
        self.window.positions.selectRow(0)
        self.window.flatten_selected()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(self.window.notice.text(), ui_text('m2m.stale_quote'))

    def test_preview_and_confirmation_show_bid_ask_and_price_deviation_is_actionable(self):
        self.form.preview_button.click()
        self.drain()
        preview = self.window.state.manual.preview
        text = preview_text(preview)
        self.assertIn('買一 40', text)
        self.assertIn('賣一 41', text)
        self.assertIn('1%', reason_text('price_deviation'))
        rejected = replace(preview, allowed=False, reasons=('price_deviation',))
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, preview=rejected)))
        self.assertIn('1%', self.form.preview.text())
        self.assertFalse(self.form.submit.isEnabled())

    def test_expired_preview_cannot_be_confirmed_or_reused(self):
        self._owned_exit_position()
        original = self.facade.execute

        def expire(command):
            receipt = original(command)
            if command.action is UiAction.PREVIEW_MANUAL:
                preview = replace(self.facade.state.manual.preview, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                self.facade.state = replace(self.facade.state, manual=replace(self.facade.state.manual, preview=preview))
            return receipt

        with patch.object(self.facade, 'execute', side_effect=expire), patch.object(self.window, '_confirm') as confirm:
            self.window.flatten_selected()
            self.drain()
            confirm.assert_not_called()
        self.assertEqual([item.action for item in self.facade.commands], [UiAction.PREVIEW_MANUAL])

    def test_confirmation_rejection_shows_price_deviation_and_never_retries(self):
        original = self.facade.execute

        def reject(command):
            receipt = original(command)
            return UiReceipt(False, 'price_deviation', '') if command.action is UiAction.SUBMIT_MANUAL else receipt

        self.form.preview_button.click()
        self.drain()
        with patch.object(self.facade, 'execute', side_effect=reject), patch.object(self.window, '_confirm', return_value=True):
            self.form.submit.click()
            self.drain()
        self.assertEqual(self.window.notice.text(), ui_text('u2.price_deviation'))
        self.assertFalse(self.form.submit.isEnabled())
        self.assertEqual(len(self.facade.commands), 2)
