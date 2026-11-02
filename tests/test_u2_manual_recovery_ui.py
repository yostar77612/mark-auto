"""Explicit candidate recovery under real widgets and worker dispatch."""

from dataclasses import replace
from unittest.mock import patch
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ManualPendingView, UiAction, UiReceipt
from quantlab.trading.domain.models import Environment
from tests import test_m2_manual_ui as support


class RecoveryFacade(support.ManualFacade):
    def execute(self, command):
        if command.action not in (UiAction.ADOPT_MANUAL_ORDER, UiAction.DECLARE_MANUAL_NOT_SENT):
            return super().execute(command)
        self.commands.append(command)
        mutation = command.manual_mutation
        result = ManualPendingView(
            mutation.scope,
            mutation.request_id,
            'ADOPT' if command.action is UiAction.ADOPT_MANUAL_ORDER else 'DECLARE',
            order_id=mutation.order_id,
            status='RESOLVED',
            outcome_known=True,
        )
        pending = self.state.manual.pending if command.action is UiAction.ADOPT_MANUAL_ORDER else None
        self.state = replace(self.state, manual=replace(self.state.manual, last_result=result, pending=pending))
        return UiReceipt(True, 'ok', '', mutation.order_id)


class ManualRecoveryUiTests(unittest.TestCase):
    setUpClass = classmethod(support.ManualUiTests.setUpClass.__func__)
    tearDown = support.ManualUiTests.tearDown
    drain = support.ManualUiTests.drain

    def setUp(self):
        support.ManualUiTests.setUp(self)
        self.facade = RecoveryFacade()
        self.window.facade = self.facade
        self.recovery = self.controls.recovery
        self.set_pending(('broker-a', 'broker-b'))

    def set_pending(self, candidates):
        state = self.facade.state
        pending = ManualPendingView(state.manual.scope, 'unknown-request', 'SUBMIT', order_id='owned-order', status='UNKNOWN', candidates=candidates)
        self.facade.state = replace(
            state, manual=replace(state.manual, pending=pending, halted=True, can_mutate=False), orders=(replace(state.orders[0], state='UNKNOWN'),)
        )
        self.window.apply_state(self.facade.state)
        self.controls.intents.pending[pending.request_id] = pending.scope

    def test_candidate_selection_is_keyboard_accessible_and_confirm_cancel_default(self):
        self.assertTrue(self.recovery.adopt.isEnabled())
        self.assertFalse(self.recovery.declare.isEnabled())
        self.assertEqual(self.recovery.declare.property('role'), 'danger')
        self.recovery.candidates.setFocus()
        QTest.keyClick(self.recovery.candidates, Qt.Key.Key_Down)
        self.assertEqual(self.recovery.candidates.currentData(), 'broker-b')

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIs(box.textFormat(), Qt.TextFormat.PlainText)
            self.assertIn('broker-b', box.text())
            self.assertIn('不會再送出', box.text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            self.recovery.adopt.click()
        self.assertEqual(self.facade.commands, [])
        self.assertTrue(self.recovery.candidates.accessibleName())

    def test_adopt_binds_exact_candidate_and_waits_for_observed_resolution(self):
        self.recovery.candidates.setCurrentIndex(1)
        with patch.object(self.window, '_confirm', return_value=True):
            self.recovery.adopt.click()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.ADOPT_MANUAL_ORDER)
        self.assertEqual(command.target_id, 'broker-b')
        self.assertEqual(command.manual_mutation.order_id, 'owned-order')
        self.assertTrue(command.manual_mutation.confirmed)
        self.assertEqual(command.manual_mutation.scope, self.window.state.manual.scope)
        self.assertIn('unknown-request', self.controls.intents.pending)
        self.assertFalse(self.recovery.adopt.isEnabled())
        self.facade.state = replace(self.facade.state, manual=replace(self.facade.state.manual, pending=None))
        self.window.apply_state(self.facade.state)
        self.assertNotIn('unknown-request', self.controls.intents.pending)
        self.assertTrue(self.window.state.manual.halted)
        self.assertEqual(len(self.facade.commands), 1)

    def test_declare_requires_cancel_default_and_clears_only_proven_original_request(self):
        self.set_pending(())
        self.assertTrue(self.recovery.declare.isEnabled())
        self.assertFalse(self.recovery.adopt.isEnabled())

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIn('釋放', box.text())
            self.assertIn('不會重送', box.text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            self.recovery.declare.click()
        self.assertEqual(self.facade.commands, [])
        with patch.object(self.window, '_confirm', return_value=True):
            self.recovery.declare.click()
        self.drain()
        self.assertIs(self.facade.commands[-1].action, UiAction.DECLARE_MANUAL_NOT_SENT)
        self.assertEqual(self.facade.commands[-1].target_id, '')
        self.assertNotIn('unknown-request', self.controls.intents.pending)
        self.assertTrue(self.window.state.manual.halted)

    def test_candidate_change_during_confirmation_is_not_sent(self):
        def changed(_):
            self.set_pending(('new-broker',))
            return True

        with patch.object(self.window, '_confirm', side_effect=changed):
            self.recovery.adopt.click()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(self.window.notice.text(), ui_text('v2.state_conflict'))

    def test_empty_projection_without_resolution_does_not_discharge_unknown(self):
        self.window.apply_state(replace(self.window.state, manual=replace(self.window.state.manual, pending=None)))
        self.assertIn('unknown-request', self.controls.intents.pending)
        self.assertFalse(self.form.submit.isEnabled())

    def test_live_blocks_widgets_direct_handlers_and_programmatic_actions(self):
        self.window.apply_state(replace(self.window.state, environment=Environment.LIVE))
        self.assertFalse(self.recovery.adopt.isEnabled())
        self.assertFalse(self.recovery.declare.isEnabled())
        with patch.object(self.window, '_confirm') as confirm:
            self.recovery.resolve(True)
            self.recovery.resolve(False)
            confirm.assert_not_called()
        for action in (UiAction.ADOPT_MANUAL_ORDER, UiAction.DECLARE_MANUAL_NOT_SENT):
            self.window.command(action)
        self.assertEqual(self.facade.commands, [])
