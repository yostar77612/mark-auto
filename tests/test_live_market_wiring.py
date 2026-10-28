"""Characterize existing engine snapshots and transport; no Domain rule tests."""

from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, PositionLot, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import StoredEvent
from quantlab.trading.runtime.build import SimulationClock, create_engine, synthetic_calendar, synthetic_catalog
from quantlab.trading.runtime.ipc import IpcFacade
from quantlab.trading.runtime.protocol import Operation, Response
from quantlab.trading.application.contracts import MarketHealthView, OverviewMarketSummary
from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.application.market_cycle import poll_market
from quantlab.trading.application.context import Catalog
from quantlab.trading.domain.live_bars import DataGap
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.live_market import RoutedMarketData, attach_market
from test_tick_adapters_contract import simulated_connector


def memory_engine(**kwargs):
    calendar, catalog = synthetic_calendar(), synthetic_catalog()
    clock = SimulationClock(calendar.sessions[0].opens_at + timedelta(minutes=5))
    journal = Mock()
    journal.replay.return_value = ()
    journal.append.side_effect = lambda kind, payload, now, expected_sequence: StoredEvent(expected_sequence + 1, kind, payload, '', '')
    return TradingEngine(journal, clock, calendar, catalog, {}, **kwargs)


class SnapshotCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = memory_engine()
        self.facade = LocalFacade(self.engine)

    def test_existing_snapshot_shape_and_quote_revision(self):
        before = self.facade.snapshot()
        existing = (
            'environment account_ref engine_state policy_label allocated_cash daily_pnl remaining_risk quote_status version trading_day synthetic_data '
            'issues strategies positions orders markets performance accounts events settings cost_version risk_version quote_revision broker_settings '
            'broker_readiness reconciliation reconciliation_verified contexts context_id context_epoch financial_facts_verified configuration_id'
        ).split()
        self.assertEqual([field.name for field in fields(before)][: len(existing)], existing)
        self.assertEqual((before.engine_state, before.quote_status, before.quote_revision), ('WAITING_RECONCILIATION', 'NO_DATA', 0))
        self.assertEqual(self.facade.snapshot(), before)
        spec = self.engine.catalog.instruments[0]
        now = self.engine.clock.now()
        quote = Quote(spec.instrument_id, Decimal('10'), Decimal('11'), Decimal('10'), now, now, now.date(), sequence=1)
        self.engine.quote(quote)
        after = self.facade.snapshot()
        self.assertEqual(after.version, before.version)
        self.assertEqual(after.quote_revision, 1)
        with self.assertRaises(DomainError):
            self.engine.quote(quote)
        self.assertEqual(self.facade.snapshot().quote_revision, 1)

    def test_existing_protocol_and_ipc_snapshot_preserve_state(self):
        state = self.facade.snapshot()
        self.assertEqual(loads(dumps(Response('characterization', state=state))).state, state)
        body = json.loads(dumps(state))
        del body['fields']['quote_revision']
        self.assertEqual(loads(json.dumps(body)).quote_revision, 0)
        client = IpcFacade(Path.cwd())
        with patch.object(client, 'request', return_value=Response('characterization', state=state)) as request:
            self.assertEqual(client.snapshot(), state)
        request.assert_called_once_with(Operation.SNAPSHOT)

    def test_existing_snapshot_keeps_legacy_defaults(self):
        state = self.facade.snapshot()
        self.assertEqual(loads(dumps(replace(state, quote_revision=7))), replace(state, quote_revision=7))

    def test_snapshot_short_mark_is_gross_last_price_not_liquidation(self):
        spec = self.engine.catalog.instruments[1]
        now = self.engine.clock.now()
        form = StrategyForm(
            'characterization',
            Market.INDEX_FUTURE,
            HoldingKind.SWING,
            3,
            5,
            Side.SELL,
            spec.instrument_id,
            'local-futures',
            Environment.LOCAL,
            Decimal('10000'),
            Decimal('.02'),
        )
        record = StrategyRecord('short', 1, form, HoldingPolicy())
        # Zero sellable quantity avoids any protection/order fixture dependency.
        lot = PositionLot('recorded', 'local-futures', spec.instrument_id, 'short', 1, record.policy, 2, Decimal('100'), now.date(), 0, direction=Side.SELL)
        self.engine.state = replace(self.engine.state, strategies=(record,), positions=(lot,))
        self.engine.quotes[spec.instrument_id] = Quote(spec.instrument_id, Decimal('109'), Decimal('111'), Decimal('110'), now, now, now.date())
        self.assertEqual(self.facade.snapshot().performance[0].unrealized_pnl, Decimal('-200'))


class LiveMarketWiringTests(unittest.TestCase):
    def test_attach_transfers_bootstrap_receipts_and_preserves_injected_service(self):
        broker, _, _ = simulated_connector()
        for _ in range(20):
            broker.subscribe(('WATCH:0',))
        engine = memory_engine()
        engine.catalog = Catalog((broker.resolve('WATCH:0'),))
        engine.gateways = {'local-stock': broker}
        attach_market(engine)
        self.assertEqual(broker.subscriptions, {})
        engine.live_market.allocate(('WATCH:0',))
        service = engine.live_market
        attach_market(engine)
        self.assertIs(engine.live_market, service)
        self.assertEqual(len(broker.subscriptions), 1)

    def test_market_poll_failure_is_published_before_reaching_host(self):
        service = Mock()
        engine = memory_engine(live_market=service)
        service.poll.side_effect = DomainError('outcome_unknown', 'synthetic failed drain')
        with self.assertRaises(DomainError):
            poll_market(engine)
        self.assertIn('outcome_unknown', engine.state.issues)
        self.assertEqual(engine.state.events[-1], 'live_market_requires_attention')
        version = engine.state.version
        with self.assertRaises(DomainError):
            poll_market(engine)
        self.assertEqual(engine.state.version, version)

    def test_local_composition_injects_feeds_and_service_with_single_subscription_owner(self):
        def journal():
            value = Mock()
            value.replay.return_value = ()
            value.append.side_effect = lambda kind, payload, now, expected_sequence: StoredEvent(expected_sequence + 1, kind, payload, '', '')
            return value

        with (
            patch('quantlab.trading.runtime.build.Ledger', side_effect=(journal(), journal())),
            patch('quantlab.trading.runtime.build.compute_profile', return_value=None),
            patch('quantlab.trading.runtime.build.SpawnResearchRunner'),
        ):
            engine = create_engine(Path.cwd())
        self.assertIsNotNone(engine.live_market)
        self.assertEqual(len(LocalFacade(engine).snapshot().market_watch), 20)
        self.assertEqual(sum(len(port.subscriptions) for port in engine.gateways.values()), 20)
        for gateway in engine.gateways.values():
            self.assertIsNotNone(gateway.tick_feed)
            self.assertFalse(gateway.tick_feed.catch_up)
        bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(engine), (), engine)
        before = engine.quote_count
        bundle.pump()
        self.assertEqual(engine.quote_count, before)

    def test_old_snapshot_defaults_and_nonempty_market_response_roundtrip(self):
        broker, clock, resolver = simulated_connector()
        service = LiveMarketService(broker, clock, resolver)
        engine = memory_engine(live_market=service)
        facade = LocalFacade(engine)
        service.allocate(('WATCH:0',))
        service.poll(in_session=True)
        state = facade.snapshot()
        self.assertEqual(state.market_watch, service.views())
        self.assertEqual(state.market_health, service.overview())
        self.assertEqual(state.market_revision, service.market_revision)
        self.assertEqual(state.quote_revision, 0)
        watch = replace(
            state.market_watch[0],
            gaps=(DataGap(clock.now(), clock.now() + timedelta(minutes=1)),),
            health=MarketHealthView('WATCH:0', 'DELAYED', 'rate_limited', True),
        )
        response = Response('market', state=replace(state, market_watch=(watch,)))
        self.assertEqual(loads(dumps(response)), response)
        # The real IPC snapshot method uses the decoded protocol response.
        client = IpcFacade(Path.cwd())
        with patch.object(client, 'request', return_value=loads(dumps(response))):
            self.assertEqual(client.snapshot(), response.state)
        body = json.loads(dumps(state))
        for name in ('market_revision', 'market_watch', 'market_health'):
            del body['fields'][name]
        old = loads(json.dumps(body))
        self.assertEqual((old.market_revision, old.market_watch, old.market_health), (0, (), OverviewMarketSummary()))

    def test_host_pump_drives_local_market_service_without_changing_quotes(self):
        engine = memory_engine(live_market=Mock())
        bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(engine), (), engine)
        with patch('quantlab.trading.application.market_cycle.poll_market') as poll:
            bundle.pump()
            poll.assert_called_once_with(engine)
            poll.reset_mock()
            bundle.closing = True
            bundle.pump()
            poll.assert_not_called()
        self.assertEqual(engine.quote_count, 0)

    def test_routed_connectors_drain_once_with_one_shared_budget(self):
        first, clock, resolver = simulated_connector()
        second, _, _ = simulated_connector()
        routed = RoutedMarketData({'WATCH:0': first, 'WATCH:1': first, 'WATCH:2': second}, clock)
        receipt = routed.subscribe(('WATCH:0', 'WATCH:1', 'WATCH:2'))
        self.assertTrue(receipt.active)
        with patch.object(first, 'drain_ticks', wraps=first.drain_ticks) as left, patch.object(second, 'drain_ticks', wraps=second.drain_ticks) as right:
            self.assertEqual(len(routed.drain_ticks(2)), 2)
            left.assert_called_once_with(2)
            right.assert_not_called()
            self.assertEqual(len(routed.drain_ticks(1)), 1)
            right.assert_called_once_with(1)
        routed.unsubscribe(receipt.subscription_id)
        self.assertEqual((first.subscriptions, second.subscriptions), ({}, {}))


if __name__ == '__main__':
    unittest.main()
