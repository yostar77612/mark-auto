"""Native owner CAS survives presentation offsets without rebasing admissions."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import ContextOption, UiAction, UiCommand, UiReceipt, UiState
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualOrderForm, ManualPendingView, ManualScope, ManualTradingView
from quantlab.trading.application.sinopac_contracts import SinopacConnectionView
from quantlab.trading.domain.models import Environment, Side
from decimal import Decimal


class ManualPresentationScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope = ManualScope('sinopac-simulation', 0, Environment.BROKER_SIMULATION, 'selected-alias', 'native-generation', 7)
        self.state = UiState(
            environment=Environment.BROKER_SIMULATION,
            account_ref='selected-alias',
            version=11,
            engine_state='STOPPED',
            policy_label='',
            allocated_cash=Decimal('100000'),
            daily_pnl=None,
            remaining_risk=None,
            quote_status='UNKNOWN',
            trading_day='2026-10-23',
            synthetic_data=False,
            manual=ManualTradingView(self.scope),
            sinopac_connection=SinopacConnectionView(generation='native-generation', revision=7),
        )
        self.sent = []
        self.host = SimpleNamespace(snapshot=lambda: self.state, execute=lambda command: self.sent.append(command) or UiReceipt(True, 'ok', ''))
        self.contexts = SimpleNamespace(list_contexts=lambda: (ContextOption('sinopac-simulation', '', Environment.BROKER_SIMULATION, ('selected-alias',)),))
        self.client = CompositeFacade(self.contexts, 'sinopac-simulation', self.host)
        self.client._epoch = 4
        self.client._connection = self.host
        self.client._connection_offset = 100

    def test_only_current_scope_gets_context_epoch_native_revision_unchanged(self):
        admitted = ManualPendingView(self.scope, 'original-request', 'SUBMIT')
        self.state = replace(self.state, manual=replace(self.state.manual, pending=admitted, last_result=admitted))
        view = self.client.snapshot()
        self.assertEqual(view.sinopac_connection.revision, 107)
        self.assertEqual(view.manual.scope, replace(self.scope, context_epoch=4))
        self.assertEqual(view.manual.pending, admitted)
        self.assertEqual(view.manual.last_result.scope, self.scope)

    def test_native_inner_and_outer_scope_forwarded_without_connection_offset(self):
        scope = replace(self.scope, context_epoch=4)
        command = UiCommand(
            UiAction.ENABLE_MANUAL_BOOK,
            11,
            environment=scope.environment,
            account_ref=scope.account_ref,
            context_id=scope.context_id,
            context_epoch=4,
            connection_generation=scope.connection_generation,
            connection_revision=7,
            manual_book=ManualBookForm(scope, Decimal('40000'), True),
        )
        self.assertTrue(self.client.execute(command).accepted)
        self.assertEqual(self.sent, [command])

    def test_mixed_inner_context_and_foreign_account_never_forward(self):
        scope = replace(self.scope, context_epoch=4)
        command = UiCommand(
            UiAction.ENABLE_MANUAL_BOOK,
            11,
            environment=scope.environment,
            account_ref='other-alias',
            context_id=scope.context_id,
            context_epoch=4,
            connection_generation=scope.connection_generation,
            connection_revision=7,
            manual_book=ManualBookForm(scope, Decimal('40000'), True),
        )
        self.assertFalse(self.client.execute(command).accepted)
        self.assertEqual(self.sent, [])

    def test_old_ui_epoch_only_forwards_original_confirmed_request_for_denial(self):
        scope = replace(self.scope, context_epoch=3)
        form = ManualOrderForm(scope, 'outer-cas-refusal', 'TMF:202611', Side.BUY, 1, Decimal('25000'), Decimal('24900'), confirmed=True)
        command = UiCommand(
            UiAction.SUBMIT_MANUAL,
            11,
            environment=scope.environment,
            account_ref=scope.account_ref,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
            manual_order=form,
        )
        self.host.execute = lambda value: self.sent.append(value) or UiReceipt(False, 'state_conflict', '')
        result = self.client.execute(command)
        self.assertFalse(result.accepted)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].manual_no_admission)
        self.assertEqual(replace(self.sent[0], manual_no_admission=False), command)


if __name__ == '__main__':
    unittest.main()
