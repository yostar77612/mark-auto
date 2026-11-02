"""Offline pure rule acceptance; import name is supplied by the draft runner."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest
from zoneinfo import ZoneInfo

from quantlab.trading.domain import auto_cycle as cycle
from quantlab.trading.domain.calendar import TradingSession
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import HoldingKind, Market
from quantlab.trading.domain.validation import DomainError

D = Decimal
TAIPEI = ZoneInfo('Asia/Taipei')
DAY = date(2026, 11, 2)
OPEN = datetime(2026, 11, 2, 8, 45, tzinfo=TAIPEI)
SESSION = TradingSession(DAY, OPEN, OPEN + timedelta(hours=5))


def bars(count=5, start=OPEN):
    return tuple(
        LiveBar(
            'TAIFEX:TMF:202611',
            start + timedelta(minutes=n),
            start + timedelta(minutes=n + 1),
            DAY,
            'DAY',
            D(100 + n),
            D(103 + n),
            D(98 + n),
            D(101 + n),
            n + 1,
            final=True,
        )
        for n in range(count)
    )


class CompletedBucketTests(unittest.TestCase):
    def evaluate(self, values, interval='5m', *, session=SESSION, now=None):
        return cycle.complete_buckets(values, interval, session, now or session.closes_at)

    def test_ohlcv_uses_all_five_minutes_and_does_not_modify_inputs(self):
        values = bars()
        original = repr(values)
        (result,) = self.evaluate(values)
        self.assertEqual((result.start, result.end), (OPEN, OPEN + timedelta(minutes=5)))
        self.assertEqual((result.open, result.high, result.low, result.close, result.volume), (D(100), D(107), D(98), D(105), 15))
        self.assertTrue(result.final)
        self.assertFalse(result.incomplete)
        self.assertEqual(repr(values), original)
        with self.assertRaises(FrozenInstanceError):
            result.volume = 99

    def test_forming_minute_is_never_eligible_even_when_its_end_elapsed(self):
        self.assertEqual(self.evaluate((replace(bars(1)[0], final=False),), '1m'), ())

    def test_incomplete_minute_is_never_eligible(self):
        self.assertEqual(self.evaluate((replace(bars(1)[0], incomplete=True),), '1m'), ())

    def test_future_completed_flag_does_not_make_information_available(self):
        self.assertEqual(self.evaluate(bars(1), '1m', now=OPEN + timedelta(seconds=59)), ())

    def test_missing_middle_minute_cannot_form_a_five_minute_bucket(self):
        values = bars()
        self.assertEqual(self.evaluate(values[:2] + values[3:]), ())

    def test_five_discontinuous_minutes_do_not_satisfy_count(self):
        values = bars(6)
        self.assertEqual(self.evaluate(values[:2] + values[3:]), ())

    def test_equal_replay_duplicates_count_once(self):
        values = bars()
        self.assertEqual(self.evaluate(values + values), self.evaluate(values))
        self.assertEqual(len(self.evaluate((values[0], values[0]), '1m')), 1)

    def test_conflicting_duplicate_poisoned_minute_is_not_arbitrarily_selected(self):
        value = bars(1)[0]
        self.assertEqual(self.evaluate((value, replace(value, close=D(102))), '1m'), ())

    def test_session_date_and_kind_cannot_be_mixed(self):
        value = bars(1)[0]
        for change in ({'trade_date': date(2026, 11, 3)}, {'session': 'NIGHT'}):
            with self.subTest(change=change):
                self.assertEqual(self.evaluate((replace(value, **change),), '1m'), ())

    def test_data_outside_provided_market_session_is_not_evaluated(self):
        earlier = bars(1, OPEN - timedelta(minutes=1))[0]
        after = bars(1, SESSION.closes_at)[0]
        self.assertEqual(self.evaluate((earlier, after), '1m', now=SESSION.closes_at + timedelta(minutes=1)), ())

    def test_non_minute_duration_and_off_grid_start_are_not_minute_data(self):
        value = bars(1)[0]
        for change in ({'end': value.start + timedelta(seconds=30)}, {'start': value.start + timedelta(seconds=1), 'end': value.end + timedelta(seconds=1)}):
            with self.subTest(change=change):
                self.assertEqual(self.evaluate((replace(value, **change),), '1m'), ())

    def test_instruments_cannot_fill_each_others_missing_minutes(self):
        values = bars()
        mixed = values[:2] + tuple(replace(value, instrument_id='TWSE:2330') for value in values[2:])
        self.assertEqual(self.evaluate(mixed), ())

    def test_daily_requires_entire_actual_session_and_close(self):
        values = bars(300)
        (result,) = self.evaluate(values, '1d')
        self.assertEqual((result.start, result.end), (SESSION.opens_at, SESSION.closes_at))
        self.assertEqual(result.volume, 300 * 301 // 2)
        self.assertEqual(self.evaluate(values[:-1], '1d'), ())
        self.assertEqual(self.evaluate(values, '1d', now=SESSION.closes_at - timedelta(microseconds=1)), ())

    def test_partial_five_minute_tail_is_not_a_shortened_bucket(self):
        session = replace(SESSION, closes_at=OPEN + timedelta(minutes=7))
        self.assertEqual(len(self.evaluate(bars(10), session=session)), 1)

    def test_fractional_session_tail_is_never_silently_rounded_into_daily_bar(self):
        session = replace(SESSION, closes_at=SESSION.closes_at - timedelta(seconds=1))
        self.assertEqual(self.evaluate(bars(299), '1d', session=session), ())

    def test_night_session_and_unsupported_interval_are_refused(self):
        self.assertEqual(self.evaluate(tuple(replace(bar, session='NIGHT') for bar in bars()), session=replace(SESSION, kind='NIGHT')), ())
        with self.assertRaises(DomainError):
            self.evaluate(bars(), '15m')


class EvaluationCursorTests(unittest.TestCase):
    def setUp(self):
        self.cursor = cycle.EvaluationCursor('strategy-1', 2, 'TMF', '5m', OPEN)

    def test_only_strictly_newer_bar_is_evaluated(self):
        for offset, expected in ((-1, False), (0, False), (1, True)):
            self.assertIs(cycle.should_evaluate(self.cursor, 'strategy-1', 2, 'TMF', '5m', OPEN + timedelta(minutes=offset)), expected)
        self.assertTrue(cycle.should_evaluate(None, 'strategy-1', 2, 'TMF', '5m', OPEN))

    def test_identity_mismatch_never_reuses_another_cursor(self):
        for strategy, version, instrument, interval in (
            ('other', 2, 'TMF', '5m'),
            ('strategy-1', 3, 'TMF', '5m'),
            ('strategy-1', 2, 'NEXT', '5m'),
            ('strategy-1', 2, 'TMF', '1m'),
        ):
            self.assertFalse(cycle.should_evaluate(self.cursor, strategy, version, instrument, interval, OPEN + timedelta(minutes=5)))
        with self.assertRaises(FrozenInstanceError):
            self.cursor.bar_end = OPEN + timedelta(minutes=1)

    def test_equal_instants_in_another_timezone_do_not_replay(self):
        self.assertFalse(cycle.should_evaluate(self.cursor, 'strategy-1', 2, 'TMF', '5m', OPEN.astimezone(timezone.utc)))


class ForceExitTimingTests(unittest.TestCase):
    def test_regular_tmf_and_stock_use_their_configured_market_times(self):
        future = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, SESSION)
        stock_session = TradingSession(DAY, OPEN.replace(hour=9, minute=0), OPEN.replace(hour=13, minute=30))
        stock = cycle.force_exit_window(HoldingKind.INTRADAY, Market.STOCK, stock_session)
        self.assertEqual(future.due_at, OPEN.replace(hour=13, minute=35))
        self.assertEqual(stock.due_at, OPEN.replace(hour=13, minute=20))
        self.assertEqual(future.retry_cutoff, OPEN.replace(hour=13, minute=43))
        self.assertEqual(stock.retry_cutoff, OPEN.replace(hour=13, minute=28))

    def test_settlement_or_short_session_caps_due_at_actual_close_minus_ten(self):
        session = replace(SESSION, closes_at=OPEN.replace(hour=13, minute=30))
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, session)
        self.assertEqual(window.due_at, OPEN.replace(hour=13, minute=20))
        self.assertEqual(window.closes_at, session.closes_at)

    def test_very_short_session_never_schedules_before_it_opens(self):
        session = replace(SESSION, closes_at=OPEN + timedelta(minutes=5))
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, session)
        self.assertEqual(window.due_at, OPEN)

    def test_forced_exit_does_not_start_before_due_time(self):
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, SESSION)
        self.assertFalse(cycle.force_exit_due(window, window.due_at - timedelta(microseconds=1)))
        self.assertTrue(cycle.force_exit_due(window, window.due_at))

    def test_retry_waits_the_full_thirty_seconds(self):
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, SESSION)
        self.assertFalse(cycle.force_exit_due(window, window.due_at + timedelta(seconds=29), window.due_at))
        self.assertTrue(cycle.force_exit_due(window, window.due_at + timedelta(seconds=30), window.due_at))
        self.assertFalse(cycle.force_exit_due(window, window.due_at, window.due_at + timedelta(seconds=1)))

    def test_no_retry_past_actual_close_minus_two_minutes(self):
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, SESSION)
        self.assertTrue(cycle.force_exit_due(window, window.retry_cutoff))
        self.assertFalse(cycle.force_exit_due(window, window.retry_cutoff + timedelta(microseconds=1)))
        self.assertFalse(cycle.force_exit_due(window, window.closes_at + timedelta(minutes=1)))

    def test_after_close_remainder_becomes_an_anomaly(self):
        window = cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, SESSION)
        self.assertFalse(cycle.position_overdue(window, window.closes_at, 1))
        self.assertTrue(cycle.position_overdue(window, window.closes_at + timedelta(microseconds=1), 1))
        self.assertFalse(cycle.position_overdue(window, window.closes_at + timedelta(minutes=1), 0))

    def test_non_intraday_and_night_do_not_schedule_forced_day_exit(self):
        self.assertIsNone(cycle.force_exit_window(HoldingKind.SWING, Market.STOCK, SESSION))
        self.assertIsNone(cycle.force_exit_window(HoldingKind.INTRADAY, Market.INDEX_FUTURE, replace(SESSION, kind='NIGHT')))
        with self.assertRaises(DomainError):
            cycle.force_exit_window(HoldingKind.INTRADAY, Market.STOCK_FUTURE, SESSION)


if __name__ == '__main__':
    unittest.main()
