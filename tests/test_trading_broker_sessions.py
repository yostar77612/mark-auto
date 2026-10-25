"""Explicit calendar and trusted closing baselines through real local fault ports."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import test_trading_adapters as fixtures
from test_trading_execution_environments import LocalEnvironmentPort
from quantlab.trading.adapters.simulated import SimulatedBroker
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import poll_events, reconcile
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.sessions import (
    BASELINE_ISSUE,
    DailyBaselineEvidence,
    assert_daily_baseline,
    confirm_daily_baseline,
    fee_fingerprint,
    resolve_session,
    synchronize_session,
    validate_baseline,
)
from quantlab.trading.application.workflows import mark_risk, total_mark
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderStatus, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_history
from quantlab.trading.runtime.provenance import compute_profile

D = Decimal
TAIPEI = timezone(timedelta(hours=8))
SOURCE = 'LOCAL_FAULT_PORT_VERIFIED_CLOSE'


def calendar_fixture() -> TradingCalendar:
    days = (date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 28))
    sessions = [
        TradingSession(day, datetime(day.year, day.month, day.day, 9, tzinfo=TAIPEI), datetime(day.year, day.month, day.day, 13, 30, tzinfo=TAIPEI))
        for day in days
    ]
    sessions.append(TradingSession(days[2], datetime(2026, 10, 23, 15, tzinfo=TAIPEI), datetime(2026, 10, 24, 5, tzinfo=TAIPEI), 'NIGHT'))
    return TradingCalendar('broker-session-fixture', 'explicit-holiday-v1', 'LOCAL_ONLY_NOT_EXCHANGE', tuple(sorted(sessions, key=lambda s: s.opens_at)))


def evidence_fixture(calendar: TradingCalendar, fees: FeeSchedule, day: date, *, accounts=('test-stock',), pnl=D('0')) -> DailyBaselineEvidence:
    previous = calendar.days[calendar.index(day) - 1]
    return DailyBaselineEvidence(
        Environment.BROKER_SIMULATION,
        accounts,
        previous,
        day,
        calendar.calendar_id,
        calendar.version,
        fees.version,
        fee_fingerprint(fees),
        pnl,
        calendar.day_session(previous).closes_at,
        SOURCE,
    )


class SessionCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar, self.fees = calendar_fixture(), FeeSchedule()
        self.now = datetime(2026, 10, 26, 10, tzinfo=TAIPEI)

    def validate(self, evidence, **values) -> None:
        context = dict(
            environment=Environment.BROKER_SIMULATION,
            account_refs=('test-stock',),
            calendar=self.calendar,
            fees=self.fees,
            now=self.now,
            trade_date=date(2026, 10, 26),
            trusted_sources=frozenset((SOURCE,)),
        )
        context.update(values)
        validate_baseline(evidence, **context)

    def test_utc_and_market_timezone_resolve_the_same_explicit_day(self) -> None:
        self.assertEqual(resolve_session(self.calendar, self.now), resolve_session(self.calendar, self.now.astimezone(timezone.utc)))
        self.assertEqual(resolve_session(self.calendar, self.now).trade_date, date(2026, 10, 26))

    def test_weekend_and_declared_holiday_use_latest_opened_day_without_weekday_guess(self) -> None:
        weekend = resolve_session(self.calendar, datetime(2026, 10, 25, 10, tzinfo=TAIPEI))
        holiday = resolve_session(self.calendar, datetime(2026, 10, 27, 10, tzinfo=TAIPEI))
        self.assertEqual((weekend.trade_date, weekend.active), (date(2026, 10, 23), False))
        self.assertEqual((holiday.trade_date, holiday.active), (date(2026, 10, 26), False))

    def test_night_is_off_by_default_and_never_inferred_from_machine_date(self) -> None:
        now = datetime(2026, 10, 23, 16, tzinfo=TAIPEI)
        closed = resolve_session(self.calendar, now)
        enabled = resolve_session(self.calendar, now, night_enabled=True)
        self.assertEqual((closed.trade_date, closed.kind, closed.active), (date(2026, 10, 23), 'DAY', False))
        self.assertEqual((enabled.trade_date, enabled.kind, enabled.active), (date(2026, 10, 26), 'NIGHT', True))

    def test_missing_earlier_calendar_and_naive_clock_are_not_synthesized(self) -> None:
        for now in (datetime(2026, 10, 21, 10, tzinfo=TAIPEI), self.now.replace(tzinfo=None)):
            with self.assertRaises(DomainError):
                resolve_session(self.calendar, now)

    def test_baseline_requires_every_configured_account_exact_environment_and_trusted_source(self) -> None:
        evidence = evidence_fixture(self.calendar, self.fees, self.now.date())
        self.validate(evidence)
        for changes in ({'account_refs': ('other', 'test-stock')}, {'environment': Environment.LIVE}, {'trusted_sources': frozenset()}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.validate(evidence, **changes)

    def test_previous_day_calendar_closing_time_and_fee_values_are_all_bound(self) -> None:
        original = evidence_fixture(self.calendar, self.fees, self.now.date())
        variants = (
            replace(original, previous_trade_date=date(2026, 10, 22)),
            replace(original, calendar_version='other'),
            replace(original, as_of=original.as_of - timedelta(minutes=1)),
            replace(original, fee_version='other'),
            replace(original, source_id='UNVERIFIED_SOURCE'),
        )
        for evidence in variants:
            with self.subTest(evidence=evidence), self.assertRaises(DomainError):
                self.validate(evidence)
        with self.assertRaises(DomainError):
            self.validate(original, fees=replace(self.fees, minimum_fee=D('100')))

    def test_evidence_refuses_float_unsorted_accounts_and_wrong_valuation_axis(self) -> None:
        original = evidence_fixture(self.calendar, self.fees, self.now.date())
        for changes in (
            {'previous_close_total_pnl': 0.0},
            {'as_of': self.now.replace(tzinfo=None)},
            {'account_refs': ('z', 'a')},
            {'pnl_basis': 'BROKER_LIFETIME_CASH'},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(original, **changes)


class BrokerSessionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='broker-session-', dir=Path(__file__).resolve().parents[2] / 't')
        self.path = Path(self.temp.name) / 'ledger.sqlite'
        self.clock, self.calendar, self.fees = fixtures.MutableClock(), synthetic_calendar(), FeeSchedule()
        self.spec = replace(fixtures.instrument(Market.INDEX_FUTURE), effective_at=self.calendar.sessions[0].opens_at)
        self.catalog = Catalog((self.spec,))
        self.broker = SimulatedBroker(self.clock, fixtures.account(), (self.spec,), fixtures.capability())
        self.port = LocalEnvironmentPort(self.broker, Environment.BROKER_SIMULATION)
        self.execution_profile = ExecutionConfiguration(Environment.BROKER_SIMULATION, '', 'test-stock', False, True, False)
        self.open_engine()
        synchronize_session(self.engine)
        self.publish()

    def tearDown(self) -> None:
        self.engine.journal.close()
        self.temp.cleanup()

    def open_engine(self) -> None:
        now = datetime.now(timezone.utc)
        journal = Ledger(self.path, 'broker-session-test', now)
        self.engine = TradingEngine(
            journal,
            self.clock,
            self.calendar,
            self.catalog,
            {'test-stock': self.port},
            configuration=self.execution_profile,
            source_profile=compute_profile(),
            fees=self.fees,
            historical_bars=synthetic_history(self.catalog, self.calendar),
        )
        self.facade = LocalFacade(self.engine)

    def publish(self, price=D('100')) -> None:
        self.engine.quote(
            Quote(
                self.spec.instrument_id,
                price,
                price + D('1'),
                price,
                self.clock.now(),
                self.clock.now(),
                resolve_session(self.calendar, self.clock.now()).trade_date,
                sequence=self.engine.quote_count + 1,
                source='LOCAL_BASELINE_FIXTURE',
            )
        )

    def baseline(self, pnl=D('0')) -> DailyBaselineEvidence:
        return evidence_fixture(self.calendar, self.fees, self.engine.state.trading_day, pnl=pnl)

    def confirm(self, pnl=D('0')) -> None:
        confirm_daily_baseline(self.engine, self.baseline(pnl), trusted_sources=frozenset((SOURCE,)))

    def command(self, action, **values):
        receipt = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
        self.assertTrue(receipt.accepted, receipt)
        return receipt

    def open_position(self) -> None:
        self.confirm()
        self.command(UiAction.RESUME)
        form = StrategyForm(
            'session baseline',
            self.spec.market,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            self.spec.instrument_id,
            'test-stock',
            Environment.BROKER_SIMULATION,
            D('30000'),
            D('0.02'),
            'BUY_AND_HOLD',
        )
        reference = self.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            self.command(action, target_id=reference)
        record = self.engine.strategy(reference)
        plan = replace(
            fixtures.plan(self.spec, environment=Environment.BROKER_SIMULATION),
            strategy_id=record.strategy_id,
            strategy_version=record.version,
            limit_price=D('101'),
            stop_price=D('91'),
            state_version=self.engine.state.version,
        )
        order_id = self.engine.submit(plan, record.policy, 'session-position')
        fee = self.fees.transaction(self.spec, plan.side, plan.limit_price, 1)
        self.broker.fill(order_id, 1, plan.limit_price, fee=fee)
        poll_events(self.engine)

    def next_day(self) -> None:
        day = self.calendar.advance(self.engine.state.trading_day, 1)
        self.clock.value = self.calendar.day_session(day).opens_at + timedelta(minutes=5)
        self.broker.advance_trade_date(day)
        synchronize_session(self.engine)

    def test_new_nonlocal_engine_cannot_assume_zero_baseline_even_when_flat(self) -> None:
        self.assertTrue(self.engine.state.daily_baseline_required)
        with self.assertRaises(DomainError):
            assert_daily_baseline(self.engine)
        receipt = self.facade.execute(UiCommand(UiAction.RESUME, self.engine.state.version))
        self.assertFalse(receipt.accepted)
        self.assertIsNone(self.engine.state.daily_baseline_evidence)

    def test_explicit_trusted_baseline_still_requires_separate_resume(self) -> None:
        self.confirm()
        self.assertFalse(self.engine.state.daily_baseline_required)
        self.assertTrue(self.engine.state.stopped)
        self.assertTrue(self.engine.state.reconciled)
        assert_daily_baseline(self.engine)
        self.command(UiAction.RESUME)
        self.assertFalse(self.engine.state.stopped)

    def test_next_trading_day_keeps_dated_locks_and_unverified_pnl_without_zeroing(self) -> None:
        self.open_position()
        mark_risk(self.engine)
        old_day, old_pnl, old_base = self.engine.state.trading_day, self.engine.state.daily_pnl, self.engine.state.daily_baseline_pnl
        self.engine._persist('fixture_earlier_latched_daily_stop', replace(self.engine.state, daily_locks=(old_day,), stopped=True))
        self.next_day()
        self.assertEqual(self.engine.state.trading_day, date(2026, 10, 26))
        self.assertEqual(self.engine.state.daily_locks, (old_day,))
        self.assertEqual((self.engine.state.daily_pnl, self.engine.state.daily_baseline_pnl), (old_pnl, old_base))
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertFalse(self.engine.state.reconciled)

    def test_restart_reconciles_new_day_but_does_not_resume_or_fabricate_close(self) -> None:
        self.confirm()
        self.clock.value = self.calendar.day_session(date(2026, 10, 26)).opens_at
        self.engine.journal.close()
        self.open_engine()
        synchronize_session(self.engine)
        reconcile(self.engine)
        self.assertEqual(self.engine.state.trading_day, date(2026, 10, 26))
        self.assertTrue(self.engine.state.reconciled)
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertIn(BASELINE_ISSUE, self.engine.state.issues)
        with self.assertRaises(DomainError):
            assert_daily_baseline(self.engine)

    def test_missing_new_day_baseline_does_not_block_legally_executable_protection(self) -> None:
        self.open_position()
        self.next_day()
        self.publish()
        reconcile(self.engine)
        self.assertTrue(self.engine.state.daily_baseline_required)
        lot = self.engine.state.positions[0]
        exit_id = self.engine.exit_lot(lot.lot_id, protective=True)
        self.assertIsNotNone(exit_id)
        order = next(o for o in self.engine.state.orders if o.order_id == exit_id)
        self.broker.fill(exit_id, 1, order.plan.limit_price, fee=self.fees.transaction(self.spec, order.plan.side, order.plan.limit_price, 1))
        poll_events(self.engine)
        self.assertEqual(self.engine.state.positions[0].quantity, 0)
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.FILLED)
        self.assertTrue(self.engine.state.daily_baseline_required)

    def test_stale_or_missing_position_mark_cannot_confirm_a_zero_current_pnl(self) -> None:
        self.open_position()
        self.next_day()
        self.engine.quotes.clear()
        before = self.engine.state.daily_baseline_pnl
        with self.assertRaises(DomainError) as rejected:
            self.confirm(D('-82'))
        self.assertEqual(rejected.exception.code, 'stale_quote')
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertEqual(self.engine.state.daily_baseline_pnl, before)

    def test_fee_values_changed_under_same_version_invalidate_committed_baseline(self) -> None:
        self.confirm()
        self.engine.fees = replace(self.engine.fees, minimum_fee=D('30'))
        synchronize_session(self.engine)
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertTrue(self.engine.state.stopped)
        with self.assertRaises(DomainError):
            assert_daily_baseline(self.engine)

    def test_trusted_new_day_close_revalues_pnl_and_keeps_previous_dated_stop(self) -> None:
        self.open_position()
        old_day = self.engine.state.trading_day
        previous_close = total_mark(self.engine)
        self.engine._persist('fixture_prior_daily_stop', replace(self.engine.state, daily_locks=(old_day,), stopped=True))
        self.next_day()
        self.publish(D('105'))
        expected_pnl = total_mark(self.engine) - previous_close
        self.confirm(previous_close)
        self.assertEqual(self.engine.state.daily_pnl, expected_pnl)
        self.assertEqual(self.engine.state.daily_baseline_pnl, previous_close)
        self.assertEqual(self.engine.state.daily_locks, (old_day,))
        self.assertTrue(self.engine.state.stopped)
        self.command(UiAction.RESUME)
        self.assertFalse(self.engine.state.stopped)

    def test_clock_rollback_cannot_return_to_an_unlocked_older_risk_day(self) -> None:
        self.confirm()
        self.next_day()
        day = self.engine.state.trading_day
        self.clock.value = self.calendar.day_session(date(2026, 10, 23)).opens_at
        synchronize_session(self.engine)
        self.assertEqual(self.engine.state.trading_day, day)
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('state_conflict', self.engine.state.issues)


if __name__ == '__main__':
    unittest.main()
