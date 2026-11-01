"""Boundary refusal records original identity without admitting an SDK mutation."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from multiprocessing import Pipe
from multiprocessing.connection import answer_challenge, deliver_challenge
from types import SimpleNamespace
import unittest
from uuid import uuid4

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import ContextOption, UiAction, UiCommand
from quantlab.trading.application.manual_contracts import ManualOrderForm, ManualTradingView
from quantlab.trading.application.manual_routing import refusal_command
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _BoundedAuthentication, _dispatch, _Handlers
import test_manual_runtime_integration as fixtures
import test_sinopac_runtime_routing as routing


class ManualNoAdmissionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.ManualRuntimeIntegrationTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.ready()
        self.form = self.prepare(3)
        self.host = routing.HostView(self.case.bundle, self.case.alias)
        self.opened = []
        contexts = SimpleNamespace(
            list_contexts=lambda: (ContextOption('sinopac-simulation', '', Environment.BROKER_SIMULATION, (self.case.alias,)),),
            open_context=lambda *args: self.opened.append(args),
        )
        self.client = CompositeFacade(contexts, 'sinopac-simulation', self.host)
        self.client._epoch = 4

    def prepare(self, epoch):
        command = replace(self.case.command(UiAction.TEST_SIM_ORDER), context_epoch=epoch)
        state = self.case.request(Operation.COMMAND, command).state
        preview = state.manual.preview
        return ManualOrderForm(
            preview.scope,
            preview.request_id,
            preview.instrument_id,
            preview.side,
            preview.quantity,
            preview.limit_price,
            preview.stop_price,
            preview.purpose,
            True,
            preview.preview_id,
        )

    def command(self, epoch=3, **changes):
        scope = replace(self.form.scope, context_epoch=epoch)
        form = replace(self.form, scope=scope)
        return replace(self.case.command(UiAction.TEST_SIM_ORDER, manual_order=form), context_epoch=epoch, **changes)

    def financial_calls(self):
        return [row for row in self.case.native._seen if row[0] in ('place_order', 'cancel_order', 'update_order')]

    def test_old_composite_epoch_seals_only_absent_key_with_original_scope(self):
        command = self.command()
        before = self.financial_calls()
        receipt = self.client.execute(command)
        self.assertFalse(receipt.accepted)
        result = self.client.snapshot().manual.last_result
        self.assertEqual((result.request_id, result.scope), (command.manual_order.request_id, command.manual_order.scope))
        self.assertEqual((result.status, result.outcome_known, result.reason), ('REJECTED', True, 'state_conflict'))
        self.assertEqual(self.financial_calls(), before)
        self.assertEqual(self.opened, [])

    def test_same_key_unknown_survives_old_composite_epoch_and_deny_marker(self):
        command = self.command()
        self.case.native.place_mode = 'TIMEOUT'
        first = self.case.request(Operation.COMMAND, command)
        self.assertFalse(first.receipt.accepted)
        original = first.state.manual.pending
        self.assertIsNotNone(original)
        self.assertFalse(original.outcome_known)
        before = self.financial_calls()
        denied = self.client.execute(command)
        self.assertFalse(denied.accepted)
        pending = self.client.snapshot().manual.pending
        self.assertEqual(pending, original)
        self.assertEqual(self.financial_calls(), before)

    def test_changed_ui_book_uses_existing_owner_control_only_for_refusal(self):
        command = self.command()
        original = self.case.state()
        local = replace(original, environment=Environment.LOCAL, account_ref='local-stock', manual=ManualTradingView())
        self.client.contexts.list_contexts = lambda: (
            ContextOption('local', '', Environment.LOCAL, ('local-stock',)),
            ContextOption('sinopac-simulation', '', Environment.BROKER_SIMULATION, (self.case.alias,)),
        )
        self.client._current = SimpleNamespace(snapshot=lambda: local, execute=lambda _: self.fail('refusal executed a LOCAL book action'))
        self.client._context_id = 'local'
        self.client._connection = routing.HostView(self.case.bundle, 'sinopac-pending')
        self.assertFalse(self.client.execute(command).accepted)
        result = self.case.state().manual.last_result
        self.assertEqual((result.request_id, result.scope), (command.manual_order.request_id, command.manual_order.scope))
        self.assertTrue(result.outcome_known)
        self.assertEqual(self.client.snapshot().environment, Environment.LOCAL)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.financial_calls(), [])

    def test_wrong_envelope_forwards_only_denial_to_same_owner(self):
        command = self.command(epoch=4)
        request = Request(
            uuid4().hex, Environment.BROKER_SIMULATION, 'sinopac-pending', datetime.now(timezone.utc) + timedelta(seconds=10), Operation.COMMAND, command
        )
        response = _dispatch(self.case.bundle, loads(dumps(request)))
        self.assertFalse(response.receipt.accepted)
        result = self.case.state().manual.last_result
        self.assertEqual(result.scope, command.manual_order.scope)
        self.assertTrue(result.outcome_known)
        self.assertEqual(result.status, 'REJECTED')
        self.assertEqual(self.financial_calls(), [])

    def test_marker_on_current_valid_request_never_falls_through_and_stale_native_scope_is_not_sealed(self):
        self.form = self.prepare(4)
        command = self.command(epoch=4)
        receipt = self.client.execute(refusal_command(command))
        self.assertFalse(receipt.accepted)
        self.assertTrue(self.client.snapshot().manual.last_result.outcome_known)
        self.assertEqual(self.financial_calls(), [])
        stale = replace(
            command,
            connection_generation='old-generation',
            manual_order=replace(
                command.manual_order, request_id='new-stale-id', scope=replace(command.manual_order.scope, connection_generation='old-generation')
            ),
        )
        self.assertFalse(self.client.execute(stale).accepted)
        self.assertNotEqual(self.client.snapshot().manual.last_result.request_id, 'new-stale-id')
        self.assertEqual(self.opened, [])

    def test_live_and_nonfinancial_marker_never_dispatch_or_open_context(self):
        before = list(self.case.native._seen)
        live = replace(self.command(), environment=Environment.LIVE, manual_no_admission=True)
        self.assertFalse(self.client.execute(live).accepted)
        switch = UiCommand(UiAction.SWITCH_CONTEXT, self.case.state().version, manual_no_admission=True)
        self.assertFalse(self.client.execute(switch).accepted)
        self.assertFalse(self.case.bundle.execute(switch).accepted)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.financial_calls(), [])
        self.assertEqual([row for row in self.case.native._seen if row[0] == 'login'], [row for row in before if row[0] == 'login'])

    def test_malformed_marker_and_unconfirmed_form_cannot_record_a_result(self):
        command = self.command(epoch=4)
        for value in (0, 1, 'true'):
            with self.subTest(value=value), self.assertRaises(DomainError):
                self.case.request(Operation.COMMAND, replace(command, manual_no_admission=value))
        unconfirmed = replace(command, manual_no_admission=True, manual_order=replace(command.manual_order, confirmed=False))
        self.assertFalse(self.client.execute(unconfirmed).accepted)
        self.assertIsNone(self.case.state().manual.last_result)
        self.assertEqual(self.financial_calls(), [])

    def test_authenticated_ipc_wrong_envelope_returns_known_refusal_without_mutation(self):
        command = self.command(epoch=4)
        key = b'owned-no-admission-pipe-auth-key'
        handlers = _Handlers(self.case.bundle, key)
        server, client = Pipe(duplex=True)
        try:
            handlers.start(server)
            authentication = _BoundedAuthentication(client)
            answer_challenge(authentication, key)
            deliver_challenge(authentication, key)
            request = Request(
                uuid4().hex, Environment.BROKER_SIMULATION, 'sinopac-pending', datetime.now(timezone.utc) + timedelta(seconds=10), Operation.COMMAND, command
            )
            client.send_bytes(dumps(request).encode('utf-8'))
            self.assertTrue(client.poll(2))
            response = loads(client.recv_bytes().decode('utf-8'))
            self.assertEqual(response.request_id, request.request_id)
            self.assertFalse(response.receipt.accepted)
            self.assertEqual(response.receipt.code, 'state_conflict')
            result = self.case.state().manual.last_result
            self.assertEqual((result.request_id, result.scope), (command.manual_order.request_id, command.manual_order.scope))
            self.assertTrue(result.outcome_known)
            self.assertEqual(self.financial_calls(), [])
        finally:
            client.close()
            handlers.join()
            server.close()
        self.assertFalse(handlers.threads)


if __name__ == '__main__':
    unittest.main()
