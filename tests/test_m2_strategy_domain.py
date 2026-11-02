"""M2 typed strategy boundaries and sizing, entirely offline and deterministic."""

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, localcontext
import unittest

from test_trading_adapters import instrument
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import HoldingKind, Market, Side
from quantlab.trading.domain.strategy import (
    StrategyParameters,
    TMF_CONSERVATIVE_MARGIN,
    effective_strategy_spec,
    is_tmf,
    resolve_tmf_near,
    strategy_defaults,
    strategy_quantity,
    validate_strategy_parameters,
)
from quantlab.trading.domain.validation import DomainError

D = Decimal


def parameters(**changes):
    return replace(StrategyParameters('5m', D('.01'), D('50000')), **changes)


def expiry_calendar():
    # Tuesday 17th is an explicit holiday: Monday is the prior trading day.
    days = (date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 19))
    return TradingCalendar(
        'expiry-fixture',
        'v1',
        'EXPLICIT_TEST_ONLY',
        tuple(
            TradingSession(
                day, datetime(day.year, day.month, day.day, 0, 45, tzinfo=timezone.utc), datetime(day.year, day.month, day.day, 5, 45, tzinfo=timezone.utc)
            )
            for day in days
        ),
    )


class M2StrategyDomainTests(unittest.TestCase):
    def assert_code(self, code, function, *args):
        with self.assertRaises(DomainError) as rejected:
            function(*args)
        self.assertEqual(rejected.exception.code, code)

    def test_four_type_defaults_match_owner_values(self):
        intraday = strategy_defaults(HoldingKind.INTRADAY)
        self.assertEqual(
            (intraday.min_days, intraday.max_days, intraday.bar_interval, intraday.intervals, intraday.stop_fraction), (0, 0, '5m', ('1m', '5m'), D('.01'))
        )
        self.assertEqual((intraday.futures_exit_at, intraday.stock_exit_at), (time(13, 35), time(13, 20)))
        for kind, expected in (
            (HoldingKind.SWING, (2, 10, '1d', ('5m', '1d'), D('.03'))),
            (HoldingKind.POSITION, (10, 60, '1d', ('1d',), D('.08'))),
            (HoldingKind.CUSTOM, (None, None, '1d', ('1m', '5m', '1d'), None)),
        ):
            actual = strategy_defaults(kind)
            self.assertEqual((actual.min_days, actual.max_days, actual.bar_interval, actual.intervals, actual.stop_fraction), expected)

    def test_type_intervals_are_enforced_independently(self):
        for kind, interval in ((HoldingKind.INTRADAY, '1d'), (HoldingKind.SWING, '1m'), (HoldingKind.POSITION, '5m')):
            with self.subTest(kind=kind):
                self.assert_code('strategy_parameters_invalid', validate_strategy_parameters, kind, instrument(), parameters(bar_interval=interval))
        for interval in ('1m', '5m', '1d'):
            validate_strategy_parameters(HoldingKind.CUSTOM, instrument(), parameters(bar_interval=interval))

    def test_swing_and_position_reject_futures(self):
        for kind in (HoldingKind.SWING, HoldingKind.POSITION):
            with self.subTest(kind=kind):
                self.assert_code(
                    'strategy_instrument_restricted', validate_strategy_parameters, kind, instrument(Market.INDEX_FUTURE), parameters(bar_interval='1d')
                )

    def test_only_actual_tmf_contracts_are_supported(self):
        future = instrument(Market.INDEX_FUTURE)
        for name in ('TAIFEX:TMF:202611', 'TMF202611', 'TMF:202611'):
            self.assertTrue(is_tmf(replace(future, instrument_id=name)))
        for rejected in (
            replace(future, instrument_id='TAIFEX:MTX:202611'),
            replace(future, instrument_id='TMFfake202611'),
            instrument(Market.STOCK_FUTURE),
            replace(future, market=Market.STOCK_FUTURE),
            replace(future, exchange='OTHER'),
        ):
            self.assertFalse(is_tmf(rejected))
            self.assert_code('strategy_instrument_restricted', validate_strategy_parameters, HoldingKind.INTRADAY, rejected, parameters())
        validate_strategy_parameters(HoldingKind.INTRADAY, future, parameters())
        validate_strategy_parameters(HoldingKind.CUSTOM, future, parameters())

    def test_stock_daytrade_requires_checkbox_even_with_confirmation(self):
        self.assert_code(
            'strategy_daytrade_confirmation_required',
            validate_strategy_parameters,
            HoldingKind.INTRADAY,
            instrument(),
            parameters(stock_intraday_confirmed=True),
        )

    def test_stock_daytrade_requires_confirmation_even_with_checkbox(self):
        self.assert_code(
            'strategy_daytrade_confirmation_required', validate_strategy_parameters, HoldingKind.INTRADAY, instrument(), parameters(stock_intraday_enabled=True)
        )
        validate_strategy_parameters(HoldingKind.INTRADAY, instrument(), parameters(stock_intraday_enabled=True, stock_intraday_confirmed=True))

    def test_near_month_rule_rejects_stock_even_when_daytrade_confirmed(self):
        self.assert_code(
            'strategy_instrument_restricted',
            validate_strategy_parameters,
            HoldingKind.INTRADAY,
            instrument(),
            parameters(instrument_rule='TMF_NEAR', stock_intraday_enabled=True, stock_intraday_confirmed=True),
        )

    def test_parameters_validate_contract_count_stop_flags_and_interval_at_boundary(self):
        for change in (
            {'contracts': 0},
            {'contracts': 6},
            {'stop_fraction': D('0')},
            {'stop_fraction': D('1')},
            {'entry_amount': D('0')},
            {'bar_interval': '15m'},
            {'instrument_rule': 'ANY'},
            {'stock_intraday_enabled': 1},
            {'stock_intraday_confirmed': 1},
        ):
            with self.subTest(change=change), self.assertRaises(DomainError):
                parameters(**change)
        self.assertEqual(parameters().contracts, 1)
        self.assertEqual(parameters(contracts=5).contracts, 5)

    def test_stock_amount_floors_to_whole_lots_and_includes_shared_costs(self):
        spec, fees = instrument(), FeeSchedule()
        result = strategy_quantity(spec, parameters(entry_amount=D('50000')), D('20'), D('100000'), fees)
        self.assertEqual(result.quantity, 2000)
        self.assertEqual(result.required_cash, fees.entry_cash(spec, D('20'), 2000))
        self.assertEqual(result.margin_source, 'NOT_APPLICABLE')
        # Two lots' price fits exactly but their costs do not: one legal lot.
        result = strategy_quantity(spec, parameters(entry_amount=D('40000')), D('20'), D('100000'), fees)
        self.assertEqual(result.quantity, 1000)

    def test_stock_insufficient_for_one_lot_never_returns_zero_or_odd_lot(self):
        self.assert_code(
            'strategy_size_insufficient', strategy_quantity, instrument(), parameters(entry_amount=D('19999')), D('20'), D('100000'), FeeSchedule()
        )

    def test_stock_available_cash_limits_requested_amount(self):
        result = strategy_quantity(instrument(), parameters(), D('20'), D('30000'), FeeSchedule())
        self.assertEqual(result.quantity, 1000)
        self.assertLessEqual(result.required_cash, D('30000'))
        self.assert_code('strategy_size_insufficient', strategy_quantity, instrument(), parameters(), D('20'), D('1'), FeeSchedule())

    def test_sizing_rejects_negative_price_and_available_at_boundary(self):
        self.assert_code('validation_failed', strategy_quantity, instrument(), parameters(), D('-20'), D('100000'), FeeSchedule())
        self.assert_code('validation_failed', strategy_quantity, instrument(), parameters(), D('20'), D('-1'), FeeSchedule())

    def test_tmf_uses_requested_contracts_and_broker_margin(self):
        spec, fees = instrument(Market.INDEX_FUTURE), FeeSchedule()
        result = strategy_quantity(spec, parameters(contracts=3), D('22000'), D('100000'), fees)
        self.assertEqual((result.quantity, result.margin_source), (3, 'BROKER'))
        self.assertEqual(result.required_cash, fees.entry_cash(spec, D('22000'), 3))
        self.assertIs(effective_strategy_spec(spec), spec)

    def test_tmf_missing_margin_uses_labelled_conservative_value(self):
        spec, fees = replace(instrument(Market.INDEX_FUTURE), margin=None), FeeSchedule()
        effective = effective_strategy_spec(spec)
        self.assertEqual(effective.margin, TMF_CONSERVATIVE_MARGIN)
        self.assertIsNone(spec.margin)
        result = strategy_quantity(spec, parameters(), D('22000'), D('100000'), fees)
        self.assertEqual((result.quantity, result.margin_source), (1, 'BUILTIN_CONSERVATIVE'))
        self.assertEqual(result.required_cash, fees.entry_cash(effective, D('22000'), 1))

    def test_tmf_margin_and_costs_must_both_fit_available_cash(self):
        spec, fees = instrument(Market.INDEX_FUTURE), FeeSchedule()
        self.assert_code('strategy_size_insufficient', strategy_quantity, spec, parameters(), D('22000'), spec.margin, fees)
        self.assert_code('strategy_size_insufficient', strategy_quantity, replace(spec, margin=None), parameters(), D('22000'), D('49999'), fees)

    def test_sizing_rejects_non_tmf_future_without_relying_on_creation(self):
        self.assert_code(
            'strategy_instrument_restricted', strategy_quantity, instrument(Market.STOCK_FUTURE), parameters(), D('20'), D('100000'), FeeSchedule()
        )

    def test_sizing_is_stable_in_callers_low_precision_context(self):
        args = instrument(), parameters(), D('20.01'), D('49999'), FeeSchedule(), Side.BUY
        expected = strategy_quantity(*args)
        with localcontext() as context:
            context.prec = 4
            self.assertEqual(strategy_quantity(*args), expected)

    def test_roll_uses_prior_trading_day_across_holiday_gap(self):
        calendar = expiry_calendar()
        front = instrument(Market.INDEX_FUTURE)
        successor = replace(front, instrument_id='TAIFEX:TMF:202612', expiry=date(2026, 12, 16), delivery_month='202612')
        unrelated = replace(front, instrument_id='TAIFEX:MTX:202611')
        contracts = successor, unrelated, front
        self.assertEqual(resolve_tmf_near(contracts, calendar, date(2026, 11, 13)), front)
        self.assertEqual(resolve_tmf_near(contracts, calendar, date(2026, 11, 16)), successor)

    def test_expired_contract_is_not_a_near_month_candidate(self):
        front = instrument(Market.INDEX_FUTURE)
        expired = replace(front, instrument_id='TAIFEX:TMF:202610', expiry=date(2026, 10, 21), delivery_month='202610')
        self.assertEqual(resolve_tmf_near((expired, front), expiry_calendar(), date(2026, 11, 13)), front)

    def test_settlement_day_blocks_entries_even_with_next_month_available(self):
        front = instrument(Market.INDEX_FUTURE)
        successor = replace(front, instrument_id='TAIFEX:TMF:202612', expiry=date(2026, 12, 16), delivery_month='202612')
        self.assert_code('strategy_settlement_day', resolve_tmf_near, (front, successor), expiry_calendar(), front.expiry)

    def test_roll_without_next_contract_is_unresolved(self):
        self.assert_code('instrument_unresolved', resolve_tmf_near, (instrument(Market.INDEX_FUTURE),), expiry_calendar(), date(2026, 11, 16))

    def test_missing_near_contract_does_not_select_another_product(self):
        self.assert_code('instrument_unresolved', resolve_tmf_near, (instrument(), instrument(Market.STOCK_FUTURE)), expiry_calendar(), date(2026, 11, 13))


if __name__ == '__main__':
    unittest.main()
