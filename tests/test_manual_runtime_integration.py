"""Authenticated fake owner -> real bundle/codec/dispatch/core, no subprocess.

The fixture supplies accepted owner state; login/navigation transitions have
their own real-boundary tests. Every native API below is an offline double.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from multiprocessing import Pipe
from multiprocessing.connection import answer_challenge, deliver_challenge
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from quantlab.trading.adapters.shioaji.account_discovery import discover_accounts
from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualOrderForm, ManualMutationForm
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import CapabilitySnapshot, Environment, Market, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.build import synthetic_calendar
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _BoundedAuthentication, _dispatch, _Handlers
from quantlab.trading.runtime.sinopac_resources import ContractPriceLimits, SinopacResources
import test_manual_trading as fixtures
from test_trading_adapters import MutableClock, instrument
from test_trading_sdk_facade import Unit

D = Decimal


class ManualRuntimeIntegrationTests(unittest.TestCase):
    sdk_class = fixtures.ManualSDK

    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.clock = MutableClock()
        self.spec = replace(instrument(Market.INDEX_FUTURE), instrument_id='TMF:202611', underlying='TMF', margin=D('35050'))
        self.native = self.sdk_class(self.spec)
        module = SimpleNamespace(__version__='1.7.9', Unit=Unit, Order=lambda **kwargs: SimpleNamespace(**kwargs))
        self.bundle = build_runtime(
            RuntimeLaunch(Path(self.temp.name), Environment.BROKER_SIMULATION, account_ref='sinopac-pending', sinopac=True), sinopac_clock=self.clock
        )
        self.addCleanup(self.bundle.close)
        owner = self.bundle.sinopac_connection
        self.assertIs(owner.clock, self.clock)
        owner.shared = SharedSDKSession(ShioajiSDKFacade(self.native, module, environment=Environment.BROKER_SIMULATION))
        owner.shared.login(api_key='offline-fixture', secret_key='offline-fixture')
        owner.accounts = discover_accounts(self.native._accounts, Environment.BROKER_SIMULATION)
        self.alias = next(row.alias for row in owner.accounts if row.market is Market.INDEX_FUTURE)
        owner.selected = tuple(row.alias for row in owner.accounts)
        owner.preferences.save_accounts(owner.accounts, Environment.BROKER_SIMULATION)
        owner.session = SimpleNamespace(
            connected=True,
            disconnect=lambda: None,
            drain_tick_losses=lambda: (),
            drain_ticks=lambda limit: (),
            usage=lambda: None,
            quote_details=lambda instrument_id: {},
        )
        owner.query_ready = True
        owner.publish(environment=Environment.BROKER_SIMULATION, generation='fake-login-a', phase='CONNECTED')
        capability = CapabilitySnapshot(
            self.alias,
            Environment.BROKER_SIMULATION,
            frozenset((Market.INDEX_FUTURE,)),
            False,
            False,
            False,
            True,
            False,
            'authenticated-account-query-readonly',
            self.clock.now(),
            self.clock.now() + timedelta(minutes=5),
            'fake-query-v1',
        )
        self.resources = SinopacResources(
            Catalog((self.spec,)),
            (InstrumentBinding(self.spec, 'TMFL6'),),
            synthetic_calendar(),
            FeeSchedule(version='fake-explicit-costs'),
            tuple(row for row in owner.accounts if row.alias == self.alias),
            (capability,),
            (ContractPriceLimits(self.spec.instrument_id, D('22500'), D('27500'), self.clock.now()),),
        )
        owner.resource_factory = lambda _owner, _alias: self.resources
        record = self.native._record

        def audited(name, *args, **kwargs):
            if name in ('list_accounts', 'update_status', 'list_trades', 'list_positions', 'trade_cache_health', 'snapshots'):
                engine = self.bundle.engine
                self.assertFalse(engine is not None and getattr(engine.lock._local, 'depth', 0), name + ' held writer')
            return record(name, *args, **kwargs)

        self.native._record = audited

        def snapshots(contracts, timeout=30000, cb=None):
            self.native._record('snapshots', contracts, timeout=timeout)
            stock = contracts[0].code == '0050'
            return [
                SimpleNamespace(
                    ts=int(self.clock.now().timestamp() * 1_000_000_000),
                    buy_price=19.99 if stock else 24999,
                    sell_price=20 if stock else 25000,
                    close=20 if stock else 25000,
                )
            ]

        self.native.snapshots = snapshots

    def request(self, operation, command=None, account=None):
        value = Request(
            uuid4().hex, Environment.BROKER_SIMULATION, account or self.alias, datetime.now(timezone.utc) + timedelta(seconds=10), operation, command
        )
        return loads(dumps(_dispatch(self.bundle, loads(dumps(value)))))

    def state(self):
        return self.request(Operation.SNAPSHOT).state

    def command(self, action, **fields):
        state = self.state()
        scope = state.manual.scope
        return UiCommand(
            action,
            state.version,
            environment=scope.environment,
            account_ref=scope.account_ref,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
            **fields,
        )

    def ready(self):
        self.assertIsNone(self.bundle.engine)
        self.bundle.poll_ports()
        self.assertEqual(self.bundle.manual_runtime.error, '')
        self.assertTrue(all(row.allocation == 0 for row in self.state().accounts))
        scope = self.state().manual.scope
        receipt = self.request(Operation.COMMAND, self.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(scope, D('40000'), True))).receipt
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(next(row.allocation for row in self.state().accounts if row.account_ref == self.alias), D('40000'))

    def test_actual_dispatch_diagnostic_canceled_then_normal_order_and_no_financial_projection(self):
        self.ready()
        prepared = self.request(Operation.COMMAND, self.command(UiAction.TEST_SIM_ORDER))
        self.assertTrue(prepared.receipt.accepted, prepared.receipt)
        preview = prepared.state.manual.preview
        self.assertIsNotNone(preview)
        form = ManualOrderForm(
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
        receipt = self.request(Operation.COMMAND, self.command(UiAction.TEST_SIM_ORDER, manual_order=form)).receipt
        self.assertTrue(receipt.accepted, receipt)
        self.bundle.poll_ports()
        self.assertEqual(self.state().manual.test_status, 'PASSED')
        self.assertTrue(self.state().manual.can_submit)
        scope = self.state().manual.scope
        order = ManualOrderForm(scope, 'normal-request', self.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        prepared = self.request(Operation.COMMAND, self.command(UiAction.PREVIEW_MANUAL, manual_order=order))
        self.assertTrue(prepared.receipt.accepted, prepared.receipt)
        order = replace(order, confirmed=True, preview_id=prepared.state.manual.preview.preview_id)
        command = self.command(UiAction.SUBMIT_MANUAL, manual_order=order)
        result = self.request(Operation.COMMAND, command)
        self.assertTrue(result.receipt.accepted, result.receipt)
        before = len([row for row in self.native._seen if row[0] == 'place_order'])
        self.assertTrue(self.request(Operation.COMMAND, command).receipt.accepted)
        self.assertEqual(len([row for row in self.native._seen if row[0] == 'place_order']), before)
        state = self.state()
        self.assertFalse(state.financial_facts_verified)
        self.assertIsNone(state.daily_pnl)
        self.assertIsNone(state.remaining_risk)
        self.assertEqual(self.native.financial_queries, 0)
        self.assertEqual(len([row for row in self.native._seen if row[0] == 'login']), 1)

    def test_materialization_without_confirmation_cannot_submit_and_pump_never_auto_cycles(self):
        self.bundle.poll_ports()
        self.assertTrue(self.state().manual.can_prepare)
        self.assertFalse(self.state().manual.can_submit)
        self.assertFalse(self.request(Operation.COMMAND, self.command(UiAction.TEST_SIM_ORDER)).receipt.accepted)
        with patch('quantlab.trading.application.coordinator.run_cycle', side_effect=AssertionError('automatic cycle')):
            self.bundle.pump()
        self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))

    def test_query_failure_clears_fresh_observation_and_old_scope_rejected_after_relogin(self):
        self.ready()
        scope = self.state().manual.scope
        self.native._failure['list_positions'] = RuntimeError('private-native-detail')
        self.bundle.poll_ports()
        self.assertFalse(self.bundle.engine.state.reconciled)
        self.assertEqual(self.bundle.engine.manual_observations, {})
        self.assertTrue(self.state().manual.halted)
        self.assertNotIn('private-native-detail', dumps(self.state()))
        self.bundle.sinopac_connection.publish(generation='fake-login-b')
        command = UiCommand(
            UiAction.TEST_SIM_ORDER,
            self.state().version,
            environment=scope.environment,
            account_ref=scope.account_ref,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
        )
        self.assertFalse(self.request(Operation.COMMAND, command).receipt.accepted)
        self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))

    def test_resource_completion_after_owned_close_cannot_open_a_manual_ledger(self):
        def delayed_resource(owner, alias):
            self.bundle.close()
            return self.resources

        self.bundle.sinopac_connection.resource_factory = delayed_resource
        self.bundle.poll_ports()
        self.assertIsNone(self.bundle.engine)
        self.assertIsNone(self.bundle.manual_runtime.resource_store.journal)
        self.assertFalse((self.bundle.launch.root / 'manual-trading-v2.sqlite').exists())
        self.assertEqual(len([row for row in self.native._seen if row[0] == 'logout']), 1)
        self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))

    def test_envelope_alias_and_form_scope_mismatch_rejected_before_native_sink(self):
        self.ready()
        scope = self.state().manual.scope
        command = replace(self.command(UiAction.TEST_SIM_ORDER), account_ref='foreign-alias')
        with self.assertRaises(DomainError):
            self.request(Operation.COMMAND, command)
        mutation = ManualMutationForm(replace(scope, context_epoch=9), 'wrong-scope', 'unknown-order', confirmed=True)
        self.assertFalse(self.request(Operation.COMMAND, self.command(UiAction.CANCEL_MANUAL, manual_mutation=mutation)).receipt.accepted)
        self.assertFalse(any(row[0] in ('place_order', 'cancel_order') for row in self.native._seen))

    def test_bare_stop_reconcile_and_cancel_all_stay_controls_bare_resume_is_rejected(self):
        self.ready()
        for action in (UiAction.STOP_NEW, UiAction.RECONCILE, UiAction.CANCEL_ENTRIES):
            receipt = self.request(Operation.COMMAND, UiCommand(action, self.state().version)).receipt
            self.assertTrue(receipt.accepted, receipt)
        self.assertTrue(self.state().manual.halted)
        with self.assertRaises(DomainError):
            self.request(Operation.COMMAND, UiCommand(UiAction.RESUME, self.state().version))
        self.assertEqual(self.native.financial_queries, 0)
        self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))

    def test_batch_observed_before_concurrent_stop_is_discarded_without_reviving_book(self):
        self.ready()
        original = self.native.list_positions

        def positions(*args, **kwargs):
            receipt = self.bundle.execute(UiCommand(UiAction.STOP_NEW, self.state().version))
            self.assertTrue(receipt.accepted, receipt)
            return original(*args, **kwargs)

        self.native.list_positions = positions
        with patch.object(self.bundle.manual_runtime.service, 'adopt', wraps=self.bundle.manual_runtime.service.adopt) as adopt:
            self.bundle.poll_ports()
            adopt.assert_not_called()
        self.assertTrue(self.state().manual.halted)
        self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))

    def test_authenticated_pipe_uses_real_handler_and_releases_owned_connection(self):
        self.ready()
        key = b'offline-owned-manual-pipe-auth-key'
        handlers = _Handlers(self.bundle, key)
        server, client = Pipe(duplex=True)
        try:
            handlers.start(server)
            authentication = _BoundedAuthentication(client)
            answer_challenge(authentication, key)
            deliver_challenge(authentication, key)
            command = self.command(UiAction.TEST_SIM_ORDER)
            request = Request(
                uuid4().hex, Environment.BROKER_SIMULATION, self.alias, datetime.now(timezone.utc) + timedelta(seconds=10), Operation.COMMAND, command
            )
            client.send_bytes(dumps(request).encode('utf-8'))
            self.assertTrue(client.poll(2), 'owned authenticated response deadline')
            response = loads(client.recv_bytes().decode('utf-8'))
            self.assertEqual(response.request_id, request.request_id)
            self.assertTrue(response.receipt.accepted, response)
            self.assertIsNotNone(response.state.manual.preview)
            self.assertFalse(any(row[0] == 'place_order' for row in self.native._seen))
        finally:
            client.close()
            handlers.join()
            server.close()
        self.assertFalse(handlers.threads)


class ManualAggregateRuntimeTests(ManualRuntimeIntegrationTests):
    sdk_class = fixtures.MultiAccountManualSDK

    def setUp(self):
        super().setUp()
        from test_trading_adapters import ShioajiContractTests

        stock = ShioajiContractTests()
        stock.setUp()
        binding = stock.adapter().bindings[stock.spec.instrument_id]
        owner = self.bundle.sinopac_connection
        self.stock_alias = next(row.alias for row in owner.accounts if row.market is Market.STOCK)
        resource = replace(
            self.resources,
            catalog=Catalog((binding.spec,)),
            bindings=(binding,),
            accounts=tuple(row for row in owner.accounts if row.alias == self.stock_alias),
            capabilities=(replace(self.resources.capabilities[0], account_ref=self.stock_alias, markets=frozenset((Market.STOCK,))),),
            limits=(ContractPriceLimits(binding.spec.instrument_id, D('18'), D('22'), self.clock.now()),),
        )
        owner.resource_factory = lambda _owner, alias: resource if alias == self.stock_alias else self.resources

    def test_all_aliases_share_one_engine_and_unselected_book_obligations_are_retained(self):
        self.ready()
        state = self.request(Operation.SNAPSHOT, account=self.stock_alias).state
        scope = state.manual.scope
        command = UiCommand(
            UiAction.ENABLE_MANUAL_BOOK,
            state.version,
            environment=scope.environment,
            account_ref=scope.account_ref,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
            manual_book=ManualBookForm(scope, D('60000'), True),
        )
        self.assertTrue(self.request(Operation.COMMAND, command, account=self.stock_alias).receipt.accepted)
        engine = self.bundle.engine
        self.assertEqual(set(engine.gateways), {self.alias, self.stock_alias})
        self.assertEqual(len({id(gateway) for gateway in engine.gateways.values()}), 1)
        books = engine.state.manual_books
        self.assertEqual(sum(row.capital for row in books), D('100000'))
        self.assertEqual(sum(row.allocation for row in self.state().accounts), D('100000'))
        owner = self.bundle.sinopac_connection
        owner.selected = (self.alias,)
        self.bundle.poll_ports()
        self.assertIs(self.bundle.engine, engine)
        self.assertEqual({row.account_ref: row.capital for row in engine.state.manual_books}, {row.account_ref: row.capital for row in books})
        self.assertEqual(set(engine.gateways), {self.alias, self.stock_alias})
        self.assertTrue(self.state().manual.halted)
        self.assertFalse(engine.state.reconciled)
        self.assertEqual(len([row for row in self.native._seen if row[0] == 'login']), 1)


if __name__ == '__main__':
    unittest.main()
