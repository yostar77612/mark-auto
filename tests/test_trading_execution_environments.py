"""Same execution core through a fault-capable, entirely local broker port.

The adapter translates environment tags only at its test boundary. All cash,
orders, fills, event sequences and failures belong to the real local simulator;
no SDK client, account, login or real brokerage command exists in these tests.
"""

from dataclasses import replace
from contextlib import closing
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import test_trading_adapters as fixtures
from quantlab.trading.adapters.simulated import SimulatedBroker
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import poll_events
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Quote, Side
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_history
from quantlab.trading.runtime.provenance import compute_profile
from quantlab.trading.application.sessions import DailyBaselineEvidence, confirm_daily_baseline, fee_fingerprint


class LocalEnvironmentPort:
    def __init__(self, broker, environment):
        self.broker, self.environment = broker, environment
        self.received = []
        self.allocation_cap = None

    def snapshot(self, account):
        snapshot = self.broker.snapshot(account)
        return replace(
            snapshot, environment=self.environment, allocated_cash=self.allocation_cap if self.allocation_cap is not None else snapshot.allocated_cash
        )

    def inspect(self, account):
        return replace(self.broker.inspect(account), environment=self.environment, ca_ready=True)

    def refresh(self, account):
        remote = self.broker.refresh(account)
        orders = tuple(replace(order, plan=replace(order.plan, environment=self.environment)) for order in remote.orders)
        return replace(remote, account=replace(remote.account, environment=self.environment), orders=orders)

    def submit(self, plan, order_id):
        if plan.environment is not self.environment:
            raise DomainError('capability_missing', 'wrong environment at injected port')
        self.received.append(plan)
        return self.broker.submit(replace(plan, environment=Environment.LOCAL), order_id)

    def cancel(self, order_id):
        return self.broker.cancel(order_id)

    def events(self, account, after_sequence=0):
        return self.broker.events(account, after_sequence)


class ExecutionEnvironmentTests(unittest.TestCase):
    def test_history_injection_rejects_invalid_series_before_writing_and_owns_its_mapping(self):
        workspace = Path(__file__).resolve().parents[2]
        clock, calendar = fixtures.MutableClock(), synthetic_calendar()
        spec = fixtures.instrument(Market.INDEX_FUTURE)
        catalog = Catalog((spec,))
        broker = SimulatedBroker(clock, fixtures.account(), (spec,), fixtures.capability())
        port = LocalEnvironmentPort(broker, Environment.BROKER_SIMULATION)
        config = ExecutionConfiguration(Environment.BROKER_SIMULATION, '', 'test-stock', True, False, False)
        series = synthetic_history(catalog, calendar)[spec.instrument_id][:2]
        with tempfile.TemporaryDirectory(dir=workspace / 't') as directory:
            with closing(Ledger(Path(directory) / 'history.sqlite', 'history-injection-test', clock.now())) as journal:
                for invalid in (
                    {spec.instrument_id: list(series)},
                    {spec.instrument_id: (series[0], series[0])},
                    {spec.instrument_id: tuple(reversed(series))},
                    {'unresolved': series},
                ):
                    with self.subTest(invalid=type(next(iter(invalid.values()))).__name__), self.assertRaises(DomainError):
                        TradingEngine(
                            journal, clock, calendar, catalog, {'test-stock': port}, configuration=config, ownership_clock=clock.now, historical_bars=invalid
                        )
                    self.assertFalse(journal.replay())
                supplied = {spec.instrument_id: series}
                engine = TradingEngine(
                    journal, clock, calendar, catalog, {'test-stock': port}, configuration=config, ownership_clock=clock.now, historical_bars=supplied
                )
                supplied.clear()
                self.assertEqual(engine.history[spec.instrument_id], series)
                self.assertEqual(broker.submission_count, 0)

    def test_controlled_nonlocal_entry_fill_protection_and_performance_keep_environment(self):
        workspace = Path(__file__).resolve().parents[2]
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment), tempfile.TemporaryDirectory(dir=workspace / 't') as directory:
                clock, calendar = fixtures.MutableClock(), synthetic_calendar()
                spec = replace(fixtures.instrument(Market.INDEX_FUTURE), effective_at=calendar.sessions[0].opens_at)
                catalog = Catalog((spec,))
                broker = SimulatedBroker(clock, fixtures.account(), (spec,), fixtures.capability())
                port = LocalEnvironmentPort(broker, environment)
                with closing(Ledger(Path(directory) / 'engine.sqlite', 'local-injected-environment', clock.now())) as journal:
                    config = ExecutionConfiguration(environment, '', 'test-stock', True, False, False)
                    engine = TradingEngine(
                        journal,
                        clock,
                        calendar,
                        catalog,
                        {'test-stock': port},
                        configuration=config,
                        ownership_clock=clock.now,
                        source_profile=compute_profile(),
                        fees=FeeSchedule(),
                        historical_bars=synthetic_history(catalog, calendar),
                    )
                    self.assertEqual(engine.account('test-stock').allocated_cash, Decimal('40000'))
                    port.allocation_cap = Decimal('5000')
                    self.assertEqual(engine.account('test-stock').allocated_cash, Decimal('5000'))
                    port.allocation_cap = None
                    with self.assertRaises(DomainError):
                        engine.assert_execution_allowed()
                    # Only this in-memory injected simulator is explicitly armed.
                    engine.configuration = replace(
                        config,
                        read_only=False,
                        broker_simulation_enabled=environment is Environment.BROKER_SIMULATION,
                        live_execution_enabled=environment is Environment.LIVE,
                    )
                    facade = LocalFacade(engine)
                    for action in (UiAction.RECONCILE, UiAction.RESUME):
                        if action is UiAction.RESUME:
                            previous = calendar.days[calendar.index(engine.state.trading_day) - 1]
                            evidence = DailyBaselineEvidence(
                                environment,
                                ('test-stock',),
                                previous,
                                engine.state.trading_day,
                                calendar.calendar_id,
                                calendar.version,
                                engine.fees.version,
                                fee_fingerprint(engine.fees),
                                Decimal('0'),
                                calendar.day_session(previous).closes_at,
                                'LOCAL_TEST_ATTESTATION',
                            )
                            confirm_daily_baseline(engine, evidence, trusted_sources=frozenset(('LOCAL_TEST_ATTESTATION',)))
                        receipt = facade.execute(UiCommand(action, engine.state.version))
                        self.assertTrue(receipt.accepted, receipt)
                    engine.quote(
                        Quote(
                            spec.instrument_id,
                            Decimal('100'),
                            Decimal('101'),
                            Decimal('100'),
                            clock.now(),
                            clock.now(),
                            clock.now().date(),
                            source='LOCAL_INJECTED_TEST',
                        )
                    )
                    form = StrategyForm(
                        'injected-only',
                        spec.market,
                        HoldingKind.SWING,
                        3,
                        5,
                        Side.BUY,
                        spec.instrument_id,
                        'test-stock',
                        environment,
                        Decimal('30000'),
                        Decimal('0.02'),
                        'BUY_AND_HOLD',
                    )
                    created = facade.execute(UiCommand(UiAction.CREATE_STRATEGY, engine.state.version, strategy=form))
                    self.assertTrue(created.accepted, created)
                    for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
                        receipt = facade.execute(UiCommand(action, engine.state.version, target_id=created.reference))
                        self.assertTrue(receipt.accepted, receipt)
                    record = engine.strategy(created.reference)
                    plan = replace(
                        fixtures.plan(spec, environment=environment),
                        strategy_id=record.strategy_id,
                        strategy_version=record.version,
                        limit_price=Decimal('101'),
                        deadline=clock.now() + timedelta(seconds=30),
                        state_version=engine.state.version,
                    )
                    order_id = engine.submit(plan, record.policy, 'injected-entry')
                    broker.fill(order_id, 1, plan.limit_price)
                    poll_events(engine)
                    lot = next(lot for lot in engine.state.positions if lot.quantity)
                    exit_id = engine.exit_lot(lot.lot_id, protective=True)
                    self.assertIsNotNone(exit_id)
                    broker.fill(exit_id, 1, Decimal('100'))
                    poll_events(engine)
                    self.assertFalse(any(lot.quantity for lot in engine.state.positions))
                    self.assertEqual(len(port.received), 2)
                    self.assertTrue(all(plan.environment is environment for plan in port.received))
                    self.assertTrue(all(row.environment is environment for row in facade.snapshot().performance))
                    self.assertEqual(facade.snapshot().environment, environment)
                    self.assertEqual(facade.snapshot().markets[0].source, 'LOCAL_INJECTED_TEST')
                    from datetime import datetime, timezone
                    from uuid import uuid4
                    from quantlab.trading.runtime.protocol import Operation, Request
                    from quantlab.trading.runtime.server import _dispatch
                    from quantlab.trading.runtime.ipc import IpcFacade

                    request = Request(uuid4().hex, environment, 'test-stock', datetime.now(timezone.utc) + timedelta(seconds=10), Operation.SNAPSHOT)
                    self.assertEqual(_dispatch(engine, facade, request).state.environment, environment)
                    with self.assertRaises(DomainError):
                        _dispatch(engine, facade, replace(request, environment=Environment.LOCAL))
                    client = IpcFacade(Path(directory), environment=environment, account_ref='test-stock')
                    self.assertEqual((client.environment, client.account_ref), (environment, 'test-stock'))


if __name__ == '__main__':
    unittest.main()
