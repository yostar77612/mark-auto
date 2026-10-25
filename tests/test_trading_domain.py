"""Behavioral acceptance of v2 pure models, holding, risk and constrained strategies."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import unittest

from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.lifecycle import CorporateAction, apply_corporate_action, net_liquidation_pnl, plan_expiry
from quantlab.trading.domain.models import (
    AccountSnapshot,
    CapabilitySnapshot,
    Environment,
    HoldingKind,
    HoldingPolicy,
    InstrumentSpec,
    Market,
    OrderPlan,
    OrderStatus,
    PositionLot,
    QuantityUnit,
    Quote,
    Reservation,
    Side,
)
from quantlab.trading.domain.policies import ExitCoordinator, check_entry_eligibility, corporate_action, holding_window, transfer_position
from quantlab.trading.domain.risk import DailyRiskState, RiskPolicy, RiskService
from quantlab.trading.domain.strategy import (
    CompletedBar,
    ResearchEvidence,
    StrategyVersion,
    ai_context,
    ensure_execution_after_signal,
    features_at,
    parse_strategy,
)
from quantlab.trading.domain.validation import DomainError


D = Decimal
NOW = datetime(2026, 10, 23, 2, tzinfo=timezone.utc)
DAYS = (date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3))


def instrument(market: Market = Market.STOCK) -> InstrumentSpec:
    future = market is not Market.STOCK
    return InstrumentSpec(
        'TMF202611' if future else 'TWSE:2330',
        market,
        'TWD',
        QuantityUnit.CONTRACT if future else QuantityUnit.SHARE,
        1 if future else 1000,
        D('10') if future else D('1'),
        D('1') if future else D('0.05'),
        'TAIEX' if market is Market.INDEX_FUTURE else '2330',
        'spec-demo-v1',
        'explicit-test-fixture',
        NOW - timedelta(days=30),
        date(2026, 11, 18) if future else None,
        D('20000') if future else None,
        exchange='TAIFEX' if future else 'TWSE',
        delivery_month='202611' if future else None,
    )


def account(**changes: object) -> AccountSnapshot:
    return replace(AccountSnapshot('local-stock', Environment.LOCAL, D('100000'), D('100000'), D('100000'), D('100000'), D('0'), D('0'), NOW, 1), **changes)


def capability(**changes: object) -> CapabilitySnapshot:
    return replace(
        CapabilitySnapshot(
            'local-stock',
            Environment.LOCAL,
            frozenset(Market),
            False,
            False,
            False,
            True,
            True,
            'local-fixture',
            NOW - timedelta(days=1),
            NOW + timedelta(days=40),
            'cap-v1',
        ),
        **changes,
    )


def quote(spec: InstrumentSpec | None = None, **changes: object) -> Quote:
    spec = spec or instrument()
    price = D('200') if spec.market is not Market.STOCK else D('50')
    return replace(Quote(spec.instrument_id, price, price, price, NOW, NOW, DAYS[0], sequence=1), **changes)


def plan(spec: InstrumentSpec | None = None, **changes: object) -> OrderPlan:
    spec = spec or instrument()
    future = spec.market is not Market.STOCK
    return replace(
        OrderPlan(
            'p1',
            'local-stock',
            Environment.LOCAL,
            spec.instrument_id,
            'swing',
            1,
            Side.BUY,
            10 if future else 5000,
            spec.unit,
            D('200') if future else D('50'),
            D('190') if future else D('49'),
            False,
            NOW,
            NOW + timedelta(minutes=1),
            1,
        ),
        **changes,
    )


def calendar() -> TradingCalendar:
    return TradingCalendar(
        'explicit-demo-v1',
        'calendar-v1',
        'explicit-test-holiday-fixture',
        tuple(
            TradingSession(
                day,
                datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=1),
                datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=6),
            )
            for day in DAYS
        ),
    )


def lot(**changes: object) -> PositionLot:
    return replace(PositionLot('lot1', 'local-stock', 'TWSE:2330', 'swing', 1, HoldingPolicy(), 1000, D('50'), DAYS[0], 1000), **changes)


def draft() -> dict[str, object]:
    return {
        'schema_version': 2,
        'strategy_id': 'swing_stock',
        'version': 1,
        'market': 'STOCK',
        'holding_policy': {'kind': 'SWING', 'min_days': 3, 'max_days': 5, 'night_enabled': False, 'expiry_action': 'EXIT'},
        'bar_interval': '1d',
        'direction': 'LONG_ONLY',
        'entry': [{'field': 'close', 'operator': 'GT', 'value': '40'}],
        'exit': [{'field': 'close', 'operator': 'LT', 'value': '38'}],
        'cost_version': 'local-demo-cost-v1',
        'risk_ref': 'local-risk-v2',
    }


class StrictBoundaryTests(unittest.TestCase):
    def test_decimal_float_and_nan_are_rejected(self) -> None:
        for value in (1.0, '1', D('NaN'), D('Infinity')):
            with self.subTest(value=value), self.assertRaises(DomainError):
                replace(instrument(), multiplier=value)

    def test_timezone_bool_quantity_and_quantity_unit_are_rejected(self) -> None:
        for changes in ({'quantity': True}, {'quantity': 1.0}, {'unit': 'SHARE'}, {'decision_at': NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                plan(**changes)
        with self.assertRaises(DomainError):
            instrument().validate_quantity(1000, QuantityUnit.CONTRACT)

    def test_immutable_and_price_lot_boundaries(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            instrument().version = 'changed'
        with self.assertRaises(DomainError):
            instrument().validate_price(D('50.001'))
        with self.assertRaises(DomainError):
            instrument().validate_quantity(999, QuantityUnit.SHARE)
        instrument().validate_quantity(999, QuantityUnit.SHARE, odd_lot=True)
        self.assertEqual(instrument().round_price(D('50.001')), D('50.00'))
        self.assertEqual(instrument().round_price(D('50.001'), up=True), D('50.05'))

    def test_futures_require_actual_month_and_matching_expiry(self) -> None:
        for changes in ({'delivery_month': None}, {'expiry': None}, {'delivery_month': '202612'}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(instrument(Market.INDEX_FUTURE), **changes)

    def test_numeric_resource_bounds_reject_extreme_exponents_and_quantity(self) -> None:
        for value in (D('1e9999999'), D('1e-9999999'), D('1.000000000000000001e18')):
            with self.subTest(value=value), self.assertRaises(DomainError):
                replace(instrument(), tick_size=value)
        with self.assertRaises(DomainError):
            plan(quantity=10**100)

    def test_new_stock_future_spec_uses_same_risk(self) -> None:
        first = instrument(Market.STOCK_FUTURE)
        second = replace(first, instrument_id='CDF202611', underlying='2412')
        for spec in (first, second):
            decision = RiskService(RiskPolicy(), FeeSchedule()).preview(plan(spec), spec, quote(spec), account(), capability(), now=NOW)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.quantity, 4)


class HoldingAcceptanceTests(unittest.TestCase):
    def test_friday_entry_is_day_zero_and_holiday_is_skipped(self) -> None:
        window = holding_window(HoldingPolicy(), DAYS[0], calendar())
        self.assertEqual(window.earliest_normal_exit, date(2026, 10, 29))
        self.assertEqual(window.latest_exit, date(2026, 11, 2))
        self.assertEqual(calendar().age(DAYS[0], DAYS[0]), 0)
        self.assertEqual(calendar().age(DAYS[0], DAYS[2]), 2)

    def test_calendar_missing_date_or_insufficient_coverage_fails_closed(self) -> None:
        with self.assertRaises(DomainError):
            calendar().age(DAYS[0], date(2026, 10, 27))
        with self.assertRaises(DomainError):
            calendar().advance(DAYS[-1], 1)
        with self.assertRaises(DomainError):
            replace(calendar(), sessions=tuple(reversed(calendar().sessions)))

    def test_night_is_an_independent_disabled_policy(self) -> None:
        night = TradingSession(DAYS[1], NOW, NOW + timedelta(hours=1), 'NIGHT')
        cal = TradingCalendar('night', 'v1', 'fixture', (night,))
        with self.assertRaises(DomainError):
            cal.session_at(NOW)
        self.assertEqual(cal.session_at(NOW, allow_night=True).kind, 'NIGHT')

    def test_cash_swing_allowed_without_intraday_eligibility(self) -> None:
        check_entry_eligibility(instrument(), HoldingPolicy(), capability(), Side.BUY, NOW)
        with self.assertRaises(DomainError):
            check_entry_eligibility(instrument(), HoldingPolicy(HoldingKind.INTRADAY, 0, 0), capability(), Side.BUY, NOW)
        with self.assertRaises(DomainError):
            check_entry_eligibility(instrument(), HoldingPolicy(), capability(), Side.SELL, NOW)

    def test_today_new_stock_protection_cannot_invent_sellability(self) -> None:
        decision = ExitCoordinator().plan(lot(), instrument(), capability(), calendar(), DAYS[0], now=NOW, protective=True)
        self.assertTrue(decision.blocked)
        self.assertTrue(decision.requires_attention)
        self.assertEqual(decision.quantity, 0)

    def test_legal_protection_ignores_normal_minimum_but_deduplicates_pending(self) -> None:
        now = NOW + timedelta(days=3)
        common = (lot(), instrument(), capability(), calendar(), DAYS[1])
        self.assertTrue(ExitCoordinator().plan(*common, now=now).blocked)
        protective = ExitCoordinator().plan(*common, now=now, protective=True, pending_exit_quantity=400)
        self.assertEqual(protective.quantity, 600)
        duplicate = ExitCoordinator().plan(*common, now=now, protective=True, pending_exit_quantity=1000)
        self.assertEqual(duplicate.reason, 'exit_already_pending')
        self.assertFalse(duplicate.requires_attention)

    def test_protection_requires_current_capability_and_never_manages_external_lots(self) -> None:
        for current_lot, caps in ((lot(origin='EXTERNAL'), capability()), (lot(), capability(expires_at=NOW - timedelta(hours=1)))):
            result = ExitCoordinator().plan(current_lot, instrument(), caps, calendar(), DAYS[1], now=NOW + timedelta(days=3), protective=True)
            self.assertTrue(result.requires_attention)
            self.assertEqual(result.quantity, 0)

    def test_switching_policy_preserves_old_lot_and_requires_transfer(self) -> None:
        original = lot()
        long_policy = HoldingPolicy(HoldingKind.POSITION, 0, 100)
        moved = transfer_position(original, 'long', 2, long_policy, reconciled=True, pending_orders=0)
        self.assertEqual(original.policy.max_days, 5)
        self.assertEqual(moved.entry_trade_date, original.entry_trade_date)
        self.assertEqual(moved.policy.max_days, 100)
        with self.assertRaises(DomainError):
            transfer_position(original, 'long', 2, long_policy, reconciled=False, pending_orders=0)
        with self.assertRaises(DomainError):
            transfer_position(lot(policy=HoldingPolicy(HoldingKind.INTRADAY, 0, 0)), 'long', 2, long_policy, reconciled=True, pending_orders=0)

    def test_corporate_split_preserves_cost_basis_and_refuses_unresolved_fraction(self) -> None:
        old = instrument()
        new = replace(old, version='spec-v2', corporate_action_version='split-v2', effective_at=NOW)
        changed = corporate_action(lot(), old, new, D('2'))
        self.assertEqual(changed.quantity, 2000)
        self.assertEqual(changed.entry_price, D('25'))
        with self.assertRaises(DomainError):
            corporate_action(lot(quantity=999, sellable_quantity=999), old, new, D('0.5'))


class RiskAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.risk = RiskService(RiskPolicy(), FeeSchedule())

    def decision(self, **context: object):
        return self.risk.preview(plan(), instrument(), quote(), account(), capability(), now=NOW, **context)

    def test_two_percent_includes_costs_and_slippage_and_resizes_legal_lots(self) -> None:
        result = self.decision()
        self.assertTrue(result.allowed)
        self.assertEqual(result.quantity, 1000)
        self.assertLessEqual(result.risk_required, D('2000'))
        self.assertGreater(result.risk_required, D('1000'))
        self.assertGreater(result.cash_required, D('50000'))
        self.assertEqual(result.code, 'risk_resized')

    def test_three_percent_is_configurable_not_silently_selected(self) -> None:
        risk = RiskService(RiskPolicy(trade_fraction=D('0.03')), FeeSchedule())
        candidate = plan(limit_price=D('40'), stop_price=D('39'))
        current_quote = quote(bid=D('40'), ask=D('40'), last=D('40'))
        decision = risk.preview(candidate, instrument(), current_quote, account(), capability(), now=NOW)
        self.assertEqual(decision.quantity, 2000)
        self.assertEqual(self.risk.preview(candidate, instrument(), current_quote, account(), capability(), now=NOW).quantity, 1000)
        with self.assertRaises(DomainError):
            RiskPolicy(trade_fraction=D('0.04'))

    def test_daily_stop_blocks_entries_but_allows_legally_valid_reduce_plan(self) -> None:
        self.assertFalse(self.decision(daily_pnl=D('-10000')).allowed)
        self.assertFalse(self.decision(daily_locked=True).allowed)
        exit_plan = plan(quantity=1000, side=Side.SELL, reduce_only=True, exit_lot_id='lot1')
        decision = self.risk.preview(exit_plan, instrument(), quote(), account(), capability(), now=NOW, daily_locked=True, daily_pnl=D('-10000'))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk_required, 0)

    def test_shared_account_allocations_cannot_duplicate_platform_budget(self) -> None:
        other = account(account_ref='futures', allocated_cash=D('60000'))
        result = self.decision(allocations=(account(allocated_cash=D('60000')), other))
        self.assertFalse(result.allowed)
        self.assertFalse(self.decision(allocations=(account(), account())).allowed)

    def test_strategy_cash_cap_is_independent_of_other_strategy_account_reservations(self) -> None:
        reserve = Reservation('other-strategy', 'local-stock', 'OTHER', 'OTHER', D('20000'), D('1000'), 1, OrderStatus.UNKNOWN)
        result = self.decision(reservations=(reserve,), strategy_cash_limit=D('60000'))
        self.assertTrue(result.allowed)
        self.assertEqual(result.quantity, 1000)
        self.assertFalse(self.decision(reservations=(reserve,), strategy_cash_limit=D('1000')).allowed)
        with self.assertRaises(DomainError):
            self.decision(strategy_cash_limit=1000.0)
        with self.assertRaises(DomainError):
            self.decision(strategy_cash_limit=D('-1'))

    def test_unknown_partial_and_positions_keep_reservations(self) -> None:
        for status in (OrderStatus.UNKNOWN, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
            reservation = Reservation('r1', 'local-stock', 'TMF202611', 'TAIEX', D('90000'), D('1000'), 1, status)
            self.assertFalse(self.decision(reservations=(reservation,)).allowed)

    def test_stock_and_its_future_share_underlying_group_budget(self) -> None:
        reserve = Reservation('r1', 'future', 'CDF202611', '2330', D('20000'), D('3500'), 1, OrderStatus.UNKNOWN)
        self.assertFalse(self.decision(reservations=(reserve,)).allowed)

    def test_unsettled_receivables_are_not_available_cash(self) -> None:
        result = self.risk.preview(plan(), instrument(), quote(), account(settled_cash=D('2000'), unsettled_receivables=D('100000')), capability(), now=NOW)
        self.assertFalse(result.allowed)

    def test_missing_margin_stale_valuation_and_expired_capability_reject(self) -> None:
        spec = replace(instrument(Market.INDEX_FUTURE), margin=None)
        self.assertFalse(self.risk.preview(plan(spec), spec, quote(spec), account(), capability(), now=NOW).allowed)
        self.assertFalse(self.risk.preview(plan(), instrument(), quote(), account(as_of=NOW - timedelta(minutes=2)), capability(), now=NOW).allowed)
        self.assertFalse(self.risk.preview(plan(), instrument(), quote(), account(), capability(expires_at=NOW), now=NOW).allowed)

    def test_future_quote_wrong_identity_and_float_pnl_reject(self) -> None:
        for bad_quote in (
            quote(source_at=NOW - timedelta(seconds=31)),
            quote(source_at=NOW + timedelta(seconds=1), received_at=NOW + timedelta(seconds=1)),
            quote(instrument_id='other'),
        ):
            self.assertFalse(self.risk.preview(plan(), instrument(), bad_quote, account(), capability(), now=NOW).allowed)
        with self.assertRaises(DomainError):
            self.decision(daily_pnl=0.0)

    def test_futures_short_uses_same_core_and_requires_independent_permission(self) -> None:
        spec = instrument(Market.INDEX_FUTURE)
        short = plan(spec, side=Side.SELL, stop_price=D('210'))
        self.assertFalse(self.risk.preview(short, spec, quote(spec), account(), capability(), now=NOW).allowed)
        result = self.risk.preview(short, spec, quote(spec), account(), capability(short_sell=True), now=NOW)
        self.assertTrue(result.allowed)

    def test_daily_latch_cannot_be_cleared_by_profit_or_risk_change(self) -> None:
        state = DailyRiskState(DAYS[0].isoformat(), D('100000')).mark(D('-10000'), RiskPolicy())
        self.assertTrue(state.locked)
        self.assertTrue(state.mark(D('1000'), RiskPolicy(trade_fraction=D('0.03'))).locked)
        self.assertEqual(self.decision(daily_pnl=D('50000')).quantity, self.decision().quantity)

    def test_financial_results_do_not_depend_on_caller_decimal_precision(self) -> None:
        expected = self.decision()
        with localcontext() as context:
            context.prec = 5
            actual = self.decision()
        self.assertEqual(actual, expected)


class IncrementalCostTests(unittest.TestCase):
    def test_two_partial_fills_share_one_per_order_minimum(self) -> None:
        fees = FeeSchedule()
        spec = instrument()
        first = fees.incremental_transaction(spec, Side.BUY, D('9.75'), 1000, D('0'))
        second = fees.incremental_transaction(spec, Side.BUY, D('9.75'), 2000, first)
        self.assertEqual(first, D('20'))
        self.assertEqual(second, D('8'))
        self.assertEqual(first + second, fees.transaction(spec, Side.BUY, D('9.75'), 2000))

    def test_partial_vwap_tax_and_previous_fee_validation(self) -> None:
        fees = FeeSchedule()
        spec = instrument()
        first = fees.incremental_transaction(spec, Side.SELL, D('50'), 1000, D('0'))
        second = fees.incremental_transaction(spec, Side.SELL, D('50.5'), 2000, first)
        self.assertEqual(first + second, fees.transaction(spec, Side.SELL, D('50.5'), 2000))
        self.assertEqual(fees.incremental_transaction(spec, Side.SELL, D('50.5'), 2000, first + second), 0)
        for invalid in (D('-1'), 20.0, D('NaN')):
            with self.subTest(previous_fee=invalid), self.assertRaises(DomainError):
                fees.incremental_transaction(spec, Side.SELL, D('50'), 1000, invalid)


class StrategyAcceptanceTests(unittest.TestCase):
    def test_valid_structured_draft_and_offline_deterministic_rules(self) -> None:
        definition = parse_strategy(json.dumps(draft()))
        self.assertTrue(definition.entry[0].evaluate((('close', D('50')),)))
        self.assertFalse(definition.exit[0].evaluate((('close', D('50')),)))

    def test_arbitrary_code_tools_unknown_fields_and_decimal_floats_reject(self) -> None:
        for field, value in (('execute', '__import__("os").system("bad")'), ('api_key', 'not-a-real-key'), ('order', 'buy')):
            raw = draft()
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(DomainError):
                parse_strategy(json.dumps(raw))
        raw = draft()
        raw['entry'] = [{'field': 'close', 'operator': 'GT', 'value': 40.0}]
        with self.assertRaises(DomainError):
            parse_strategy(json.dumps(raw))

    def test_duplicate_json_nonfinite_operator_and_resource_bound_reject(self) -> None:
        for raw in ('{"schema_version":2,"schema_version":2}', '{"x":NaN}', ' ' * 65537):
            with self.subTest(raw=raw[:50]), self.assertRaises(DomainError):
                parse_strategy(raw)
        for changes in ([{'field': 'close', 'operator': 'EXEC', 'value': '1'}], [{'field': 'close', 'operator': 'GT', 'value': '1'}] * 17):
            raw = draft()
            raw['entry'] = changes
            with self.assertRaises(DomainError):
                parse_strategy(json.dumps(raw))

    def test_changes_create_new_version_and_invalidate_old_evidence(self) -> None:
        definition = parse_strategy(json.dumps(draft()))
        evidence = ResearchEvidence('RULES_VALID', definition.fingerprint, 'training1', 'trading-v2-test', NOW, 'TRAINING', 'a' * 64)
        old = StrategyVersion(definition).add_evidence(evidence)
        new = old.revised(policy=HoldingPolicy(HoldingKind.POSITION, 0, 100))
        self.assertEqual(new.definition.version, 2)
        self.assertEqual(new.evidence, ())
        self.assertEqual(old.evidence, (evidence,))
        with self.assertRaises(DomainError):
            new.add_evidence(evidence)

    def test_research_stages_cannot_skip_to_live_enablement(self) -> None:
        definition = parse_strategy(json.dumps(draft()))
        fake = ResearchEvidence('ENABLEABLE', definition.fingerprint, 'd1', 'trading-v2-test', NOW, 'TRAINING', 'a' * 64)
        with self.assertRaises(DomainError):
            StrategyVersion(definition, (fake,))

    def test_uncompleted_bar_and_same_bar_open_execution_are_rejected(self) -> None:
        bar = CompletedBar(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=1, seconds=1), D('50'), D('51'), 1000)
        with self.assertRaises(DomainError):
            features_at((bar,), NOW)
        with self.assertRaises(DomainError):
            ensure_execution_after_signal(bar, NOW)
        with self.assertRaises(DomainError):
            ensure_execution_after_signal(bar, bar.available_at)
        self.assertEqual(dict(features_at((bar,), bar.available_at))['close'], D('51'))
        ensure_execution_after_signal(bar, bar.available_at + timedelta(microseconds=1))

    def test_ai_export_never_accepts_oos_or_holdout_context(self) -> None:
        definition = parse_strategy(json.dumps(draft()))
        context = ai_context(definition)
        self.assertEqual(context.partition, 'TRAINING')
        self.assertNotIn('account', context.summary)
        for partition in ('OUT_OF_SAMPLE', 'FINAL_HOLDOUT'):
            with self.assertRaises(DomainError):
                ai_context(definition, partition=partition)

    def test_fractional_features_keep_deterministic_precision_and_remain_evaluable(self) -> None:
        bars = tuple(
            CompletedBar(NOW + timedelta(hours=i), NOW + timedelta(hours=i, minutes=30), NOW + timedelta(hours=i, minutes=30), D('30'), D(30 + i), 100)
            for i in range(6)
        )
        values = features_at(bars, NOW + timedelta(hours=6))
        self.assertTrue(dict(values)['return5'] > D('0.16'))
        raw = draft()
        raw['entry'] = [{'field': 'return5', 'operator': 'GT', 'value': '0.16'}]
        self.assertTrue(parse_strategy(json.dumps(raw)).entry[0].evaluate(values))


class LifecycleAcceptanceTests(unittest.TestCase):
    def expiry_calendar(self) -> TradingCalendar:
        days = (date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19))
        return TradingCalendar(
            'expiry-calendar',
            'v1',
            'explicit-fixture',
            tuple(
                TradingSession(
                    day, datetime(day.year, day.month, day.day, 1, tzinfo=timezone.utc), datetime(day.year, day.month, day.day, 6, tzinfo=timezone.utc)
                )
                for day in days
            ),
        )

    def test_roll_requires_two_independent_fills_and_both_legs_cost(self) -> None:
        old = instrument(Market.INDEX_FUTURE)
        new = replace(old, instrument_id='TMF202612', delivery_month='202612', expiry=date(2026, 12, 16))
        holding = lot(
            instrument_id=old.instrument_id,
            quantity=1,
            sellable_quantity=1,
            entry_price=D('200'),
            policy=HoldingPolicy(HoldingKind.POSITION, 0, 100, expiry_action='ROLL'),
        )
        decision = plan_expiry(
            holding,
            old,
            new,
            self.expiry_calendar(),
            now=datetime(2026, 11, 17, 2, tzinfo=timezone.utc),
            close_price=D('210'),
            open_price=D('215'),
            fees=FeeSchedule(),
        )
        self.assertEqual(decision.action, 'ROLL')
        self.assertEqual(decision.required_fills, 2)
        self.assertEqual(decision.close_side, Side.SELL)
        self.assertEqual(decision.open_side, Side.BUY)
        self.assertGreater(decision.estimated_cost, D('60'))
        self.assertEqual(holding.instrument_id, old.instrument_id)

    def test_expiry_exit_does_not_relabel_or_open_new_contract(self) -> None:
        old = instrument(Market.INDEX_FUTURE)
        holding = lot(instrument_id=old.instrument_id, quantity=1, sellable_quantity=1, entry_price=D('200'))
        decision = plan_expiry(
            holding,
            old,
            None,
            self.expiry_calendar(),
            now=datetime(2026, 11, 17, 2, tzinfo=timezone.utc),
            close_price=D('210'),
            open_price=None,
            fees=FeeSchedule(),
        )
        self.assertEqual(decision.action, 'EXIT')
        self.assertEqual(decision.required_fills, 1)
        self.assertIsNone(decision.open_instrument_id)

    def test_expiry_plan_waits_for_explicit_cutoff_and_rejects_unknown_roll(self) -> None:
        old = instrument(Market.INDEX_FUTURE)
        holding = lot(
            instrument_id=old.instrument_id,
            quantity=1,
            sellable_quantity=1,
            entry_price=D('200'),
            policy=HoldingPolicy(HoldingKind.POSITION, 0, 100, expiry_action='ROLL'),
        )
        early = datetime(2026, 11, 16, 2, tzinfo=timezone.utc)
        self.assertIsNone(plan_expiry(holding, old, None, self.expiry_calendar(), now=early, close_price=D('210'), open_price=None, fees=FeeSchedule()))
        with self.assertRaises(DomainError):
            plan_expiry(holding, old, None, self.expiry_calendar(), now=early + timedelta(days=1), close_price=D('210'), open_price=None, fees=FeeSchedule())
        with self.assertRaises(DomainError):
            plan_expiry(holding, old, None, self.expiry_calendar(), now=early + timedelta(days=3), close_price=D('210'), open_price=None, fees=FeeSchedule())

    def test_dividend_is_receivable_until_explicit_payable_date(self) -> None:
        old = instrument()
        new = replace(old, version='spec-v2', corporate_action_version='dividend-v1', effective_at=NOW)
        action = CorporateAction('dividend1', old.version, new.version, NOW, D('1'), D('2'), date(2026, 11, 2), 'fixture')
        result = apply_corporate_action(lot(), old, new, action, now=NOW)
        self.assertEqual(result.receivable, D('2000'))
        self.assertEqual(result.payable_date, date(2026, 11, 2))
        self.assertEqual(result.lot.quantity, 1000)
        self.assertEqual(result.lot.entry_price, D('50'))
        self.assertEqual(result.lot.risk_entry_price, D('48'))
        with self.assertRaises(DomainError):
            apply_corporate_action(lot(), old, new, action, now=NOW - timedelta(seconds=1))

    def test_adjusted_future_multiplier_preserves_economic_basis(self) -> None:
        old = instrument(Market.STOCK_FUTURE)
        new = replace(old, multiplier=D('20'), version='adjusted-v2', corporate_action_version='action-v2', effective_at=NOW)
        holding = lot(instrument_id=old.instrument_id, quantity=2, sellable_quantity=2, entry_price=D('200'))
        result = corporate_action(holding, old, new, D('1'))
        self.assertEqual(result.entry_price, D('100'))
        self.assertEqual(holding.entry_price * old.multiplier * holding.quantity, result.entry_price * new.multiplier * result.quantity)

    def test_mark_to_market_counts_fees_slippage_and_short_direction(self) -> None:
        fees = FeeSchedule()
        self.assertLess(net_liquidation_pnl(lot(), instrument(), D('50'), fees), 0)
        spec = instrument(Market.INDEX_FUTURE)
        holding = lot(instrument_id=spec.instrument_id, quantity=1, sellable_quantity=1, entry_price=D('200'), direction=Side.SELL)
        self.assertGreater(net_liquidation_pnl(holding, spec, D('180'), fees), 0)
        self.assertLess(net_liquidation_pnl(holding, spec, D('220'), fees), 0)


if __name__ == '__main__':
    unittest.main()
