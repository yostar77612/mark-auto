"""Shared decisions through a local, fault-capable non-local-tagged exchange.

No SDK, authentication, credentials or remote orders are involved.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_trading_adapters as fixtures
from test_trading_execution_environments import LocalEnvironmentPort
from quantlab.trading.adapters.simulated import FaultPlan, SimulatedBroker
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.coordinator import run_cycle
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import reconcile
from quantlab.trading.application.sessions import DailyBaselineEvidence, confirm_daily_baseline, fee_fingerprint
from quantlab.trading.application.workflows import resume, run_research
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderStatus, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_history
from quantlab.trading.runtime.provenance import compute_profile

D = Decimal


@contextmanager
def laboratory(*, kind=HoldingKind.SWING, readonly=False, baseline=True, environment=Environment.BROKER_SIMULATION, quantity=1, rollover=False):
    workspace = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(dir=workspace / 't') as directory:
        clock, calendar = fixtures.MutableClock(), synthetic_calendar()
        spec = replace(fixtures.instrument(Market.INDEX_FUTURE), effective_at=calendar.sessions[0].opens_at, margin=D('5000'), lot_size=quantity)
        target = None
        if rollover:
            target = spec
            spec = replace(spec, instrument_id='TAIFEX:TMF:202610', expiry=calendar.advance(clock.now().date(), 2), delivery_month='202610')
        catalog = Catalog((spec, target) if target else (spec,))
        capability = replace(fixtures.capability(), expires_at=clock.now() + timedelta(days=200))
        broker = SimulatedBroker(clock, fixtures.account(), catalog.instruments, capability)
        port = LocalEnvironmentPort(broker, environment)
        config = ExecutionConfiguration(
            environment,
            '',
            'test-stock',
            readonly,
            not readonly and environment is Environment.BROKER_SIMULATION,
            not readonly and environment is Environment.LIVE,
        )
        journal = Ledger(Path(directory) / 'cycle.sqlite', 'cycle-fixture', clock.now())
        engine = TradingEngine(
            journal,
            clock,
            calendar,
            catalog,
            {'test-stock': port},
            configuration=config,
            ownership_clock=lambda: fixtures.NOW,
            source_profile=compute_profile(),
            fees=FeeSchedule(),
        )
        history = synthetic_history(catalog, calendar)
        engine.history = history
        try:
            for item in catalog.instruments:
                refresh_quote(engine, item)
            form = StrategyForm(
                'cycle',
                spec.market,
                kind,
                0 if kind is HoldingKind.INTRADAY else 3,
                0 if kind is HoldingKind.INTRADAY else 100 if rollover else 5,
                Side.BUY,
                spec.instrument_id,
                'test-stock',
                environment,
                D('30000'),
                D('.02'),
                'BUY_AND_HOLD',
                expiry_action='ROLL' if rollover else 'EXIT',
                roll_contract_id=target.instrument_id if target else '',
            )
            with engine.lock:
                reference = engine.create_strategy(form)
                engine.validate_strategy(reference)
                run_research(engine, reference, history[spec.instrument_id])
                engine.deploy(reference)
                if baseline:
                    attest(engine)
                    resume(engine)
            yield engine, broker, port, spec, history
        finally:
            journal.close()


def refresh_quote(engine, spec, *, last=D('101')):
    now = engine.clock.now()
    engine.quote(
        Quote(
            spec.instrument_id,
            last - 1,
            last,
            last,
            now,
            now,
            engine.calendar.session_at(now).trade_date,
            sequence=engine.quote_count + 1,
            source='LOCAL_FAULT_PORT',
        )
    )


def attest(engine):
    day = engine.state.trading_day
    previous = engine.calendar.days[engine.calendar.index(day) - 1]
    source = 'LOCAL_FIXTURE_VERIFIED_CLOSE'
    proof = DailyBaselineEvidence(
        engine.configuration.environment,
        tuple(sorted(engine.gateways)),
        previous,
        day,
        engine.calendar.calendar_id,
        engine.calendar.version,
        engine.fees.version,
        fee_fingerprint(engine.fees),
        D('0'),
        engine.calendar.day_session(previous).closes_at,
        source,
    )
    confirm_daily_baseline(engine, proof, trusted_sources=frozenset((source,)))


class SharedCoordinatorTests(unittest.TestCase):
    def test_readonly_default_never_submits_or_fills(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            with self.assertRaises(DomainError):
                run_cycle(engine, history)
            self.assertEqual(port.received, [])
            self.assertEqual(broker.refresh('test-stock').orders, ())

    def test_both_nonlocal_environments_use_reports_without_fill_or_clock_advance(self):
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment), laboratory(environment=environment) as (engine, broker, port, spec, history):
                before = engine.clock.now(), engine.state.trading_day
                run_cycle(engine, history)
                self.assertEqual(len(port.received), 1)
                self.assertIs(port.received[0].environment, environment)
                self.assertFalse(engine.state.positions)
                run_cycle(engine, history)
                self.assertEqual(len(port.received), 1)
                order = engine.state.orders[0]
                broker.fill(order.order_id, 1, D('101'))
                run_cycle(engine, history, allow_entries=False)
                self.assertEqual(engine.state.positions[0].quantity, 1)
                self.assertEqual((engine.clock.now(), engine.state.trading_day), before)

    def test_intraday_mid_session_keeps_position_then_explicit_close_window_exits(self):
        with laboratory(kind=HoldingKind.INTRADAY) as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            broker.fill(engine.state.orders[0].order_id, 1, D('101'))
            run_cycle(engine, history)
            self.assertEqual(len(port.received), 1, 'max_days=0 is not an immediate broker-tick exit')
            close = engine.calendar.day_session(engine.state.trading_day).closes_at
            engine.clock.value = close - timedelta(minutes=4)
            refresh_quote(engine, spec)
            run_cycle(engine, history)
            self.assertEqual(len(port.received), 2)
            self.assertTrue(port.received[-1].reduce_only)
            self.assertEqual(engine.state.positions[0].quantity, 1, 'submission is not a fill')
            broker.fill(engine.state.orders[-1].order_id, 1, D('100'))
            run_cycle(engine, history)
            self.assertFalse(any(p.quantity for p in engine.state.positions))
            self.assertEqual(len(port.received), 2, 'close window cannot open a replacement')

    def test_protective_exit_precedes_normal_minimum_and_missing_baseline(self):
        with laboratory() as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            broker.fill(engine.state.orders[0].order_id, 1, D('101'))
            # Quote arrives before the fill report: cycle must apply the report,
            # then evaluate its protection even when the new day lacks evidence.
            refresh_quote(engine, spec, last=D('90'))
            next_day = engine.calendar.advance(engine.state.trading_day, 1)
            engine.clock.value = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=5)
            refresh_quote(engine, spec, last=D('90'))
            run_cycle(engine, history)
            self.assertTrue(engine.state.daily_baseline_required)
            self.assertEqual(len(port.received), 2)
            self.assertTrue(port.received[-1].reduce_only)
            self.assertEqual(engine.state.positions[0].quantity, 1)

    def test_unknown_submit_and_rejection_do_not_retry_same_daily_decision(self):
        for fault in (FaultPlan(unknown_after_accept=True), FaultPlan(reject=True), FaultPlan(disconnect_before_submit=True)):
            with self.subTest(fault=fault), laboratory() as (engine, broker, port, spec, history):
                broker.queue_fault(fault)
                run_cycle(engine, history)
                run_cycle(engine, history)
                self.assertEqual(len(port.received), 1)
                self.assertFalse(any(p.quantity for p in engine.state.positions))

    def test_partial_and_duplicate_reports_preserve_actual_remaining_exposure(self):
        with laboratory(quantity=2) as (engine, broker, port, spec, history):
            broker.queue_fault(FaultPlan(partial_quantity=1, duplicate_event=True))
            run_cycle(engine, history)
            run_cycle(engine, history)
            self.assertEqual(engine.state.orders[0].filled, 1)
            self.assertEqual(engine.state.positions[0].quantity, 1)
            self.assertIs(engine.state.orders[0].status, OrderStatus.PARTIALLY_FILLED)
            self.assertEqual(len(port.received), 1)
            broker.fill(engine.state.orders[0].order_id, 1, D('101'))
            run_cycle(engine, history)
            self.assertEqual(engine.state.positions[0].quantity, 2)
            self.assertIs(engine.state.orders[0].status, OrderStatus.FILLED)

    def test_missing_baseline_and_closed_explicit_session_never_create_new_risk(self):
        with laboratory(baseline=False) as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            self.assertTrue(engine.state.daily_baseline_required)
            self.assertEqual(port.received, [])
        with laboratory() as (engine, broker, port, spec, history):
            engine.clock.value = engine.calendar.day_session(engine.state.trading_day).closes_at + timedelta(minutes=1)
            run_cycle(engine, history)
            self.assertEqual(port.received, [])

    def test_unresolved_external_difference_freezes_new_entries(self):
        from quantlab.trading.ports.contracts import BrokerPosition

        with laboratory() as (engine, broker, port, spec, history):
            broker.external_position(BrokerPosition('test-stock', spec.instrument_id, 1, 1, spec.unit, D('100')))
            with self.assertRaises(DomainError):
                reconcile(engine)
            run_cycle(engine, history)
            self.assertEqual(port.received, [])
            self.assertFalse(engine.state.reconciled)
            self.assertEqual(engine.state.reconciliation[0].broker_quantity, 1)

    def test_nonlocal_roll_waits_for_both_actual_fills_and_carries_policy_origin(self):
        with laboratory(kind=HoldingKind.POSITION, rollover=True) as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            broker.fill(engine.state.orders[0].order_id, 1, D('101'))
            run_cycle(engine, history)
            original = engine.state.positions[0]
            next_day = engine.calendar.advance(engine.state.trading_day, 1)
            engine.clock.value = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=5)
            for item in engine.catalog.instruments:
                refresh_quote(engine, item)
            with engine.lock:
                attest(engine)
                resume(engine)
            before_cost = engine.state.costs
            run_cycle(engine, history)
            self.assertEqual(len(engine.state.rolls), 1)
            job = engine.state.rolls[0]
            self.assertEqual(job.status, 'CLOSE_SUBMITTED')
            self.assertEqual(len(port.received), 2)
            self.assertEqual(len(engine.state.orders), 2, 'no target order before source close fill')
            run_cycle(engine, history)
            self.assertEqual(len(port.received), 2, 'pending close cannot submit another exit')
            broker.fill(job.close_order_id, 1, D('100'))
            run_cycle(engine, history)
            job = engine.state.rolls[0]
            self.assertEqual(job.status, 'OPEN_SUBMITTED')
            self.assertEqual(len(port.received), 3)
            self.assertFalse(any(p.quantity for p in engine.state.positions), 'target submit must not invent a fill')
            broker.fill(job.open_order_id, 1, D('101'))
            run_cycle(engine, history)
            job = engine.state.rolls[0]
            self.assertEqual(job.status, 'COMPLETED')
            close = next(o for o in engine.state.orders if o.order_id == job.close_order_id)
            opened = next(o for o in engine.state.orders if o.order_id == job.open_order_id)
            self.assertTrue(close.plan.reduce_only)
            self.assertFalse(opened.plan.reduce_only)
            self.assertGreater(close.costs, 0)
            self.assertGreater(opened.costs, 0)
            self.assertEqual(engine.state.costs - before_cost, close.costs + opened.costs)
            self.assertTrue(all(p.environment is Environment.BROKER_SIMULATION for p in port.received))
            carried = next(p for p in engine.state.positions if p.quantity)
            self.assertEqual(carried.holding_origin, original.holding_origin)
            self.assertEqual(carried.policy, original.policy)
            self.assertEqual(carried.entry_trade_date, next_day)
            self.assertEqual(carried.instrument_id, job.new_instrument_id)
            self.assertNotEqual(carried.strategy_version, original.strategy_version)

    def test_unrelated_difference_does_not_suppress_a_confirmed_scope_protection(self):
        from quantlab.trading.ports.contracts import BrokerPosition

        with laboratory(rollover=True) as (engine, broker, port, spec, history):
            target = engine.catalog.instruments[1]
            source = engine.state.strategies[0]
            form = replace(source.form, name='independent', instrument_id=target.instrument_id, expiry_action='EXIT', roll_contract_id='')
            with engine.lock:
                reference = engine.create_strategy(form)
                engine.validate_strategy(reference)
                run_research(engine, reference, history[target.instrument_id])
                engine.deploy(reference)
            run_cycle(engine, history)
            for order in engine.state.orders:
                broker.fill(order.order_id, 1, D('101'))
            run_cycle(engine, history)
            broker.external_position(BrokerPosition('test-stock', spec.instrument_id, 2, 2, spec.unit, D('101')))
            with self.assertRaises(DomainError):
                reconcile(engine)
            # Supply the normalized quote directly at this cycle boundary. The
            # separate quote-callback protection is covered by engine tests.
            quote = engine.quotes[target.instrument_id]
            engine.quotes[target.instrument_id] = replace(quote, bid=D('89'), ask=D('90'), last=D('90'))
            run_cycle(engine, history)
            reductions = [plan for plan in port.received if plan.reduce_only]
            self.assertEqual(len(reductions), 1)
            self.assertEqual(reductions[0].instrument_id, target.instrument_id)
            self.assertFalse(engine.state.reconciled)
            self.assertTrue(engine.state.stopped)

    def test_normal_deadline_exits_after_trading_days_without_fake_fill(self):
        with laboratory() as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            broker.fill(engine.state.orders[0].order_id, 1, D('101'))
            run_cycle(engine, history)
            origin = engine.state.trading_day
            day = engine.calendar.advance(origin, 5)
            engine.clock.value = engine.calendar.day_session(day).opens_at + timedelta(minutes=5)
            refresh_quote(engine, spec)
            run_cycle(engine, history)
            self.assertEqual(engine.calendar.age(origin, day), 5)
            self.assertTrue(port.received[-1].reduce_only)
            self.assertEqual(engine.state.positions[0].quantity, 1)

    def test_stale_quote_blocks_new_risk_and_journal_failure_propagates(self):
        with laboratory() as (engine, broker, port, spec, history):
            engine.clock.value += timedelta(seconds=31)
            run_cycle(engine, history)
            self.assertEqual(port.received, [])
            self.assertIn('stale_quote', engine.state.issues)
        with laboratory() as (engine, broker, port, spec, history):
            with patch.object(engine.journal, 'append', side_effect=OSError('injected full journal')):
                with self.assertRaises(DomainError) as raised:
                    run_cycle(engine, history)
            self.assertEqual(raised.exception.code, 'journal_failed')
            self.assertTrue(engine.storage_failed)
            self.assertEqual(port.received, [])


if __name__ == '__main__':
    unittest.main()
