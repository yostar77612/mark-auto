"""Draft UI survives observation CAS races without replaying asset commands."""

from dataclasses import replace
import time
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.wizard import StrategyWizard
from quantlab.trading.application.contracts import ContextOption, StrategyForm, UiAction, UiReceipt
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Side
from decimal import Decimal
from test_trading_ui import state_fixture


class DraftFaultFacade:
    def __init__(self, fault='accept'):
        initial = state_fixture()
        self.prototype = initial.strategies[0]
        self.state = replace(
            initial,
            strategies=(),
            context_id='local',
            context_epoch=0,
            contexts=(ContextOption('local', 'Local', Environment.LOCAL, ('local-stock', 'local-future'), 'CONFIGURED'),),
        )
        self.fault, self.commands, self.first_snapshot = fault, [], True

    def snapshot(self):
        if self.first_snapshot:
            self.first_snapshot = False
            if self.fault == 'observation-before-save':
                self.state = replace(self.state, version=self.state.version + 1)
            elif self.fault == 'context-changed':
                self.state = replace(self.state, context_epoch=1)
        return self.state

    def execute(self, command):
        self.commands.append(command)
        if self.fault == 'always-conflict' or (self.fault == 'one-conflict' and len(self.commands) == 1):
            self.state = replace(self.state, version=self.state.version + 1)
            return UiReceipt(False, 'state_conflict', '')
        if self.fault == 'same-version-refusal':
            return UiReceipt(False, 'state_conflict', '')
        if self.fault == 'referenced-refusal':
            self.state = replace(self.state, version=self.state.version + 1)
            return UiReceipt(False, 'state_conflict', '', 'uncertain-existing-draft:1')
        if self.fault == 'unknown-receipt':
            return UiReceipt(False, 'outcome_unknown', '')
        if command.expected_version != self.state.version:
            return UiReceipt(False, 'state_conflict', '')
        view = replace(self.prototype, name=command.strategy.name, state='DRAFT')
        self.state = replace(self.state, strategies=(*self.state.strategies, view), version=self.state.version + 1)
        if self.fault == 'unknown-after-commit':
            raise ConnectionError('injected lost response, not permission to replay')
        return UiReceipt(True, 'completed', '', 'strategy-1:1')


class DraftConcurrencyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window = None

    def show(self, fault):
        self.facade = DraftFaultFacade(fault)
        self.window = TradingWindow(self.facade, self.facade.state)
        self.window.poll.stop()
        self.window.show()
        self.app.processEvents()

    def drain(self):
        deadline = time.monotonic() + 3
        while self.window._operation is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNone(self.window._operation, self.window.notice.text())
        self.app.processEvents()

    def tearDown(self):
        if self.window is not None:
            self.drain()
            self.window.setProperty('allow_close_for_tests', True)
            self.window.close()
            self.window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(self.window))

    def form(self):
        return StrategyForm(
            'Exact immutable draft',
            Market.STOCK,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            'TWSE:2330',
            'local-stock',
            Environment.LOCAL,
            Decimal('60000'),
            Decimal('0.02'),
        )

    def save(self, name='Retained input'):
        errors = []

        def accept():
            try:
                wizard = self.app.activeModalWidget()
                self.assertIsInstance(wizard, StrategyWizard)
                if name is None:
                    self.assertEqual(wizard.name.text(), 'Retained input')
                else:
                    wizard.name.setText(name)
                wizard.accept()
            except BaseException as exc:
                errors.append(exc)
                if isinstance(self.app.activeModalWidget(), StrategyWizard):
                    self.app.activeModalWidget().reject()

        def open_modal():
            QTimer.singleShot(0, accept)
            try:
                self.window.new_strategy()
            finally:
                self.app.exit(0)

        QTimer.singleShot(0, open_modal)
        self.app.exec()
        if errors:
            raise errors[0]
        self.drain()

    def test_background_observation_before_save_uses_current_cas_without_changing_form(self):
        self.show('observation-before-save')
        form = self.form()
        self.window.command(UiAction.CREATE_STRATEGY, strategy=form)
        self.drain()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(self.facade.commands[0].expected_version, 2)
        self.assertIs(self.facade.commands[0].strategy, form)
        self.assertEqual([row.name for row in self.window.state.strategies], [form.name])

    def test_known_cas_refusal_retries_only_once_and_creates_exactly_one_draft(self):
        self.show('one-conflict')
        self.save()
        self.assertEqual([c.expected_version for c in self.facade.commands], [1, 2])
        self.assertIs(self.facade.commands[0].strategy, self.facade.commands[1].strategy)
        self.assertEqual([row.name for row in self.window.state.strategies], ['Retained input'])
        self.assertIsNone(self.window._pending_wizard)

    def test_repeated_known_refusal_preserves_input_and_reports_state_change(self):
        self.show('always-conflict')
        self.save()
        self.assertEqual(len(self.facade.commands), 2)
        self.assertEqual(self.window.notice.accessibleName(), 'state_conflict')
        self.assertIn(ui_text('v2.state_conflict'), self.window.notice.text())
        self.assertIn(ui_text('v2.draft_retained'), self.window.notice.text())
        self.assertNotEqual(self.window.notice.text(), ui_text('v2.connection_failed'))
        self.assertIsNotNone(self.window._pending_wizard)
        self.facade.fault = 'accept'
        self.save(name=None)
        self.assertEqual(len(self.facade.commands), 3)
        self.assertEqual(len(self.facade.state.strategies), 1)

    def test_unknown_response_after_commit_does_not_resend_or_create_duplicate(self):
        self.show('unknown-after-commit')
        self.window.command(UiAction.CREATE_STRATEGY, strategy=self.form())
        self.drain()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(len(self.facade.state.strategies), 1)
        self.assertEqual(self.window.state.strategies, ())
        self.assertEqual(self.window.notice.text(), ui_text('v2.connection_failed'))
        self.window.refresh()
        self.drain()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(len(self.window.state.strategies), 1)

    def test_unknown_receipt_and_nonversion_refusal_are_never_retried(self):
        for fault in ('unknown-receipt', 'same-version-refusal', 'referenced-refusal'):
            self.show(fault)
            self.window.command(UiAction.CREATE_STRATEGY, strategy=self.form())
            self.drain()
            self.assertEqual(len(self.facade.commands), 1)
            self.window.setProperty('allow_close_for_tests', True)
            self.window.close()
            self.window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.window = None

    def test_changed_context_never_saves_draft_in_a_new_context(self):
        self.show('context-changed')
        self.window.command(UiAction.CREATE_STRATEGY, strategy=self.form())
        self.drain()
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(self.window.notice.accessibleName(), 'state_conflict')

    def test_asset_command_retains_reviewed_version_and_is_never_retried(self):
        self.show('always-conflict')
        self.facade.state = replace(self.facade.state, version=9)
        self.window.command(UiAction.DEPLOY, 'strategy-1:1')
        self.drain()
        self.assertEqual(len(self.facade.commands), 1)
        self.assertEqual(self.facade.commands[0].expected_version, 1)
