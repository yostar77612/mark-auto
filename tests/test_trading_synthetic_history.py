"""Preserve full LOCAL history values while bounding repeated calendar work."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
import unittest
from unittest.mock import patch

from quantlab.trading.application.codec import dumps
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.models import InstrumentSpec, Market
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_catalog, synthetic_history


@decimal_operation
def original_history(catalog, calendar):
    """Pre-optimization algorithm, retained as an independent value oracle."""
    result = {}
    paper_origin = calendar.index(date(2026, 10, 23))
    for spec in catalog.instruments:
        base = Decimal('20000') if spec.market is Market.INDEX_FUTURE else Decimal('50') if spec.market is Market.STOCK_FUTURE else Decimal('10')
        bars = []
        for index, day in enumerate(calendar.days):
            session = calendar.day_session(day)
            phase = index - paper_origin
            step = Decimal(phase % 12) - Decimal('6')
            opened = spec.shift_ticks(base, int(step))
            closed = spec.shift_ticks(opened, 2 if phase % 7 < 4 else -2)
            bars.append(CompletedBar(session.opens_at, session.closes_at, session.closes_at + timedelta(seconds=1), opened, closed, 100000))
        result[spec.instrument_id] = tuple(bars)
    return result


class SyntheticHistoryTests(unittest.TestCase):
    def small_calendar(self):
        calendar = synthetic_calendar()
        return replace(calendar, sessions=tuple(session for session in calendar.sessions if date(2026, 10, 22) <= session.trade_date <= date(2026, 10, 26)))

    def test_all_twenty_instruments_and_11440_bars_keep_exact_values_and_wire_bytes(self):
        initialize()
        catalog, calendar = synthetic_catalog(), synthetic_calendar()
        expected = original_history(catalog, calendar)
        actual = synthetic_history(catalog, calendar)
        self.assertEqual(len(actual), 20)
        self.assertEqual(sum(map(len, actual.values())), 11440)
        self.assertEqual(actual, expected)
        self.assertEqual(list(actual), list(expected))
        for instrument, bars in actual.items():
            with self.subTest(instrument=instrument):
                self.assertEqual(dumps(bars).encode('utf-8'), dumps(expected[instrument]).encode('utf-8'))

    def test_each_day_is_resolved_once_per_call_without_skipping_validation(self):
        calendar = self.small_calendar()
        original = TradingCalendar.day_session
        with patch.object(TradingCalendar, 'day_session', autospec=True, side_effect=original) as lookup:
            actual = synthetic_history(synthetic_catalog(), calendar)
        self.assertEqual(lookup.call_count, len(calendar.days))
        self.assertEqual([call.args for call in lookup.call_args_list], [(calendar, day) for day in calendar.days])
        self.assertEqual(len(actual), 20)
        self.assertTrue(all(len(bars) == len(calendar.days) for bars in actual.values()))

    def test_changed_calendar_is_resolved_again_and_results_are_not_shared_between_calls(self):
        catalog, calendar = synthetic_catalog(), self.small_calendar()
        first = synthetic_history(catalog, calendar)
        shifted = replace(calendar, sessions=tuple(replace(s, opens_at=s.opens_at + timedelta(minutes=7)) for s in calendar.sessions))
        second = synthetic_history(catalog, shifted)
        self.assertEqual(second, original_history(catalog, shifted))
        self.assertNotEqual(first, second)
        first.clear()
        self.assertEqual(synthetic_history(catalog, calendar), original_history(catalog, calendar))

    def test_missing_day_and_origin_fail_with_the_original_exact_error(self):
        calendar = self.small_calendar()
        for changed in (
            replace(calendar, sessions=tuple(replace(s, kind='NIGHT') for s in calendar.sessions)),
            replace(calendar, sessions=tuple(s for s in calendar.sessions if s.trade_date != date(2026, 10, 23))),
        ):
            with self.subTest(calendar=changed), self.assertRaises(DomainError) as expected:
                original_history(synthetic_catalog(), changed)
            with self.assertRaises(DomainError) as actual:
                synthetic_history(synthetic_catalog(), changed)
            self.assertEqual((actual.exception.code, actual.exception.detail), (expected.exception.code, expected.exception.detail))

    def test_empty_catalog_still_checks_origin_but_does_not_require_day_session(self):
        calendar = self.small_calendar()
        night_only = replace(calendar, sessions=tuple(replace(s, kind='NIGHT') for s in calendar.sessions))
        with patch.object(TradingCalendar, 'day_session', side_effect=AssertionError('unused session')):
            self.assertEqual(synthetic_history(Catalog(()), night_only), {})
        no_origin = replace(calendar, sessions=(calendar.sessions[0],))
        with self.assertRaises(DomainError) as expected:
            original_history(Catalog(()), no_origin)
        with self.assertRaises(DomainError) as actual:
            synthetic_history(Catalog(()), no_origin)
        self.assertEqual(str(actual.exception), str(expected.exception))

    def test_first_bar_failure_precedes_later_missing_day_as_before(self):
        calendar = self.small_calendar()
        mixed = replace(calendar, sessions=(*calendar.sessions[:-1], replace(calendar.sessions[-1], kind='NIGHT')))
        for generate in (original_history, synthetic_history):
            with self.subTest(generator=generate.__name__), patch.object(InstrumentSpec, 'shift_ticks', side_effect=DomainError('first_bar_failed')):
                with self.assertRaises(DomainError) as error:
                    generate(synthetic_catalog(), mixed)
                self.assertEqual(error.exception.code, 'first_bar_failed')

    def test_decimal_context_and_instrument_order_remain_unchanged(self):
        catalog, calendar = synthetic_catalog(), self.small_calendar()
        reversed_catalog = Catalog(tuple(reversed(catalog.instruments)))
        expected = original_history(reversed_catalog, calendar)
        with localcontext() as context:
            context.prec = 1
            actual = synthetic_history(reversed_catalog, calendar)
            self.assertEqual(context.prec, 1)
        self.assertEqual(list(actual), list(expected))
        self.assertEqual(actual, expected)
