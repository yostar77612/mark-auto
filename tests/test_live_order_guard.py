"""Every production mutation boundary rejects LIVE using entirely local fakes."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_trading_adapters as fixtures
from test_trading_sdk_facade import StrictSDK, contract
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.state import AppState, LocalOrder
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.execution_policy import orders_enabled
from quantlab.trading.domain.models import Environment, HoldingPolicy, OrderStatus, PositionLot, Quote, Reservation
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder
from quantlab.trading.ports.storage import StoredEvent
from quantlab.trading.runtime.build import synthetic_calendar


class GuardJournal:
    """An in-memory journal; no desktop engine, child process or shared files."""

    def __init__(self):
        self.events = []

    def append(self, kind, payload, now, *, expected_sequence):
        if expected_sequence != len(self.events):
            raise DomainError('journal_failed', 'fixture sequence conflict')
        event = StoredEvent(len(self.events) + 1, kind, payload, 'fixture', 'fixture')
        self.events.append(event)
        return event

    def replay(self):
        return tuple(self.events)

    def heartbeat(self, now):
        return None


def live_adapter():
    case = fixtures.ShioajiContractTests()
    case.setUp()
    case.environment = Environment.LIVE
    adapter = case.adapter(enabled=True)
    adapter.capabilities['test-stock'] = replace(adapter.capabilities['test-stock'], ca_ready=True)
    case.client.cancel_order = Mock(side_effect=AssertionError('LIVE cancel reached SDK'))
    case.client.update_order = Mock(side_effect=AssertionError('LIVE amend reached SDK'))
    return case, adapter


class LiveOrderGuardTests(unittest.TestCase):
    def test_policy_rejects_live_and_non_enum_values(self):
        self.assertTrue(orders_enabled(Environment.LOCAL))
        self.assertTrue(orders_enabled(Environment.BROKER_SIMULATION))
        for value in (Environment.LIVE, 'LOCAL', 'BROKER_SIMULATION', None, True):
            with self.subTest(value=value):
                self.assertFalse(orders_enabled(value))

    def test_live_facade_denies_mutations_despite_native_simulation_flags(self):
        vendor = StrictSDK()
        vendor.simulation, vendor.signed, vendor.ca_ready = True, True, True
        bridge = ShioajiSDKFacade(vendor, SimpleNamespace(__version__='1.7.9'), environment=Environment.LIVE)
        for operation in (
            lambda: bridge.place_order(contract(), object()),
            lambda: bridge.update_order(object(), price=20.0, qty=1),
            lambda: bridge.cancel_order(object()),
        ):
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.assertEqual(vendor._seen, [])

    def test_simulation_facade_preserves_mutations_and_original_deadlines(self):
        vendor = StrictSDK()
        bridge = ShioajiSDKFacade(vendor, SimpleNamespace(__version__='1.7.9'), environment=Environment.BROKER_SIMULATION)
        bridge.place_order(contract(), object())
        bridge.update_order(object(), price=20.0, qty=1)
        bridge.cancel_order(object())
        self.assertEqual([call[0] for call in vendor._seen], ['place_order', 'update_order', 'cancel_order'])
        self.assertTrue(all(call[2]['timeout'] == 10000 for call in vendor._seen))
        self.assertEqual(bridge.query_timeout_ms, 2500)

    def test_live_adapter_blocks_inspect_submit_cancel_and_amend(self):
        case, adapter = live_adapter()
        plan = fixtures.plan(case.spec, environment=Environment.LIVE)
        adapter.orders['owned'] = BrokerOrder('owned', plan, 0, Decimal('0'), OrderStatus.ACCEPTED, 'broker-owned', fixtures.NOW)
        adapter.trades['owned'] = object()
        self.assertFalse(adapter.inspect('test-stock').can_trade)
        # Even an incorrect readiness/certificate projection cannot bypass the
        # independent environment check at the actual mutation authority.
        with patch.object(adapter, 'inspect', return_value=replace(fixtures.capability(Environment.LIVE), ca_ready=True)):
            for operation in (
                lambda: adapter.submit(plan, 'new-order'),
                lambda: adapter.cancel('owned'),
                lambda: adapter.amend('owned', Decimal('20.1'), 1000),
            ):
                with self.assertRaises(DomainError) as caught:
                    operation()
                self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.assertEqual(case.client.placed, [])
        self.assertEqual(case.client.order_calls, [])
        case.client.cancel_order.assert_not_called()
        case.client.update_order.assert_not_called()

    def test_live_execution_service_blocks_before_persistence_or_broker_call(self):
        plan = fixtures.plan(fixtures.instrument(), environment=Environment.LIVE)
        reservation = Reservation('owned', 'test-stock', plan.instrument_id, '0050', Decimal('20000'), Decimal('1000'), 1000, OrderStatus.RESERVED)
        policy = HoldingPolicy()
        order = LocalOrder('owned', 'key', 'hash', plan, policy, reservation, OrderStatus.ACCEPTED)
        state = AppState(environment=Environment.LIVE, orders=(order,), stopped=False, reconciled=True)
        broker, persist, fence = Mock(), Mock(), Mock()
        service = ExecutionService(broker, persist, fence, lambda: fixtures.NOW)
        for operation in (
            lambda: service.commit(state, plan, policy, reservation, 'new-key', fence),
            lambda: service.cancel(state, 'owned'),
        ):
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
        persist.assert_not_called()
        fence.assert_not_called()
        broker.submit.assert_not_called()
        broker.cancel.assert_not_called()

    def test_live_engine_and_ui_stop_paths_never_call_mutations(self):
        case, adapter = live_adapter()
        config = ExecutionConfiguration(Environment.LIVE, 'test-stock', '', False, False, True)
        engine = TradingEngine(
            GuardJournal(),
            case.clock,
            synthetic_calendar(),
            Catalog((case.spec,)),
            {'test-stock': adapter},
            configuration=config,
            ownership_clock=case.clock.now,
            fees=FeeSchedule(),
        )
        engine.quote(Quote(case.spec.instrument_id, Decimal('20'), Decimal('20'), Decimal('20'), fixtures.NOW, fixtures.NOW, fixtures.NOW.date()))
        policy = HoldingPolicy()
        plan = replace(fixtures.plan(case.spec, environment=Environment.LIVE), state_version=engine.state.version)
        reservation = Reservation('owned', 'test-stock', plan.instrument_id, '0050', Decimal('20000'), Decimal('1000'), 1000, OrderStatus.RESERVED)
        order = LocalOrder('owned', 'key', 'hash', plan, policy, reservation, OrderStatus.ACCEPTED)
        lot = PositionLot('owned', 'test-stock', plan.instrument_id, 'swing', 1, policy, 1000, Decimal('20'), fixtures.NOW.date(), 1000)
        engine._persist('fixture_owned_order', replace(engine.state, orders=(order,), positions=(lot,), stopped=False, reconciled=True))
        for operation in (engine.assert_execution_allowed, lambda: engine.submit(plan, policy, 'new-key'), lambda: engine.exit_lot('owned', protective=True)):
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
        facade = LocalFacade(engine)
        receipt = facade.execute(UiCommand(UiAction.STOP_NEW, engine.state.version))
        self.assertTrue(receipt.accepted)
        self.assertTrue(engine.state.stopped)
        for action in (UiAction.CANCEL_ENTRIES, UiAction.FLATTEN):
            receipt = facade.execute(UiCommand(action, engine.state.version, target_id='owned'))
            self.assertFalse(receipt.accepted)
            self.assertEqual(receipt.code, 'production_orders_disabled')
        self.assertEqual(case.client.placed, [])
        case.client.cancel_order.assert_not_called()
        case.client.update_order.assert_not_called()
