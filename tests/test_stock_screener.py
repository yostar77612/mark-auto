"""M6-1: surge ranking, long red / long black patterns and condition-triggered K-line downloads."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.stock_screener import (
    SCREENER_PRIORITY,
    SURGE_BLACK,
    SURGE_RED,
    ScreenerParams,
    StockScreener,
    download_window,
    eligible_row,
    rank_surges,
    ranking_open,
    surge_pattern,
    typical_amount,
)
from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind

TAIPEI = timezone(timedelta(hours=8))


def at(day, hour, minute, second=0):
    """November 2026: the 9th is a Monday."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=TAIPEI)


MONDAY_0905, MONDAY_0910, MONDAY_1000, MONDAY_1340 = at(9, 9, 5), at(9, 9, 10), at(9, 10, 0), at(9, 13, 40)


def quote(code='1234', price='110', open='100', high='110.5', low='99', pct='10', ratio='4', volume=2000, amount=40_000_000, when=MONDAY_1000):
    """Defaults qualify as a long red candle: +10%, 4x volume, 0.45% below the high, usually 10M traded."""
    return QuoteRow(
        code,
        Decimal(price),
        Decimal(pct),
        '',
        volume,
        amount,
        Decimal(ratio) if ratio is not None else None,
        when,
        Decimal(open) if open is not None else None,
        Decimal(high) if high is not None else None,
        Decimal(low) if low is not None else None,
    )


def black(code='1234', **kwargs):
    values = dict(price='90', open='100', high='101', low='89.5', pct='-10', ratio='4')
    return quote(code, **{**values, **kwargs})


def stock(code):
    return WatchInstrument(f'TWSE:{code}', WatchKind.STOCK, 'TSE', code, 'N' + code, '24')


class PatternTests(unittest.TestCase):
    def pattern(self, row, params=None):
        params = params or ScreenerParams()
        return surge_pattern(row, params, typical_amount(row))

    def test_a_qualifying_long_red_is_recognised(self):
        self.assertEqual(self.pattern(quote()), SURGE_RED)

    def test_red_thresholds_are_inclusive_at_the_boundary_and_exclusive_just_past_it(self):
        cases = (
            (dict(ratio='3', amount=30_000_000), SURGE_RED),  # ratio exactly 3
            (dict(ratio='2.99', amount=30_000_000), ''),
            (dict(price='105', open='100', high='105.5', pct='5'), SURGE_RED),  # +5% exactly
            (dict(price='105', open='100', high='105.5', pct='4.99'), ''),
            (dict(price='98.5', open='90', high='100', pct='9'), SURGE_RED),  # exactly 1.5% under the high
            (dict(price='98.5', open='90', high='100.01', pct='9'), ''),
            (dict(ratio='4', amount=199_999_996), SURGE_RED),  # usually 49,999,999: quiet
            (dict(ratio='4', amount=200_000_000), ''),  # usually exactly 50,000,000: not below the limit
            (dict(price='100', open='100', high='100.5', pct='9'), ''),  # closing at the open is not a red candle
            (dict(open=None), ''),
            (dict(high=None), ''),
            (dict(ratio=None), ''),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(self.pattern(quote(**values)), expected)

    def test_a_busy_stock_is_not_a_quiet_one_even_with_a_perfect_candle(self):
        self.assertEqual(self.pattern(quote(amount=4_000_000_000)), '')

    def test_a_qualifying_long_black_is_recognised_and_needs_no_quiet_history(self):
        self.assertEqual(self.pattern(black()), SURGE_BLACK)
        self.assertEqual(self.pattern(black(amount=4_000_000_000)), SURGE_BLACK)

    def test_black_thresholds_are_inclusive_at_the_boundary_and_exclusive_just_past_it(self):
        cases = (
            (dict(price='101.5', open='110', low='100', pct='-7'), SURGE_BLACK),  # exactly 1.5% above the low
            (dict(price='101.5', open='110', low='99.9', pct='-7'), ''),
            (dict(price='95', open='100', low='94.9', pct='-5'), SURGE_BLACK),  # -5% exactly
            (dict(price='95', open='100', low='94.9', pct='-4.99'), ''),
            (dict(ratio='3'), SURGE_BLACK),
            (dict(ratio='2.99'), ''),
            (dict(price='100', open='100', low='99.9', pct='-6'), ''),  # closing at the open is not a black candle
            (dict(low=None), ''),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(self.pattern(black(**values)), expected)

    def test_every_threshold_can_be_changed(self):
        row = quote(ratio='2.5', amount=25_000_000, pct='4')
        self.assertEqual(self.pattern(row), '')
        looser = ScreenerParams(surge_ratio=Decimal(2), red_change_pct=Decimal(3))
        self.assertEqual(self.pattern(row, looser), SURGE_RED)
        self.assertEqual(self.pattern(quote(amount=200_000_000), ScreenerParams(quiet_amount=60_000_000)), SURGE_RED)

    def test_parameter_ranges_are_validated(self):
        for values in (
            dict(min_price=Decimal(0)),
            dict(surge_ratio=Decimal('0.5')),
            dict(red_change_pct=Decimal(11)),
            dict(near_extreme_pct=Decimal('0.05')),
            dict(min_volume_lots=-1),
            dict(warmup_minutes=61),
            dict(list_rows=9),
            dict(quiet_amount=0),
            dict(download_red=1),
        ):
            with self.subTest(values=values), self.assertRaises(DomainError):
                ScreenerParams(**values)


class FilterAndRankTests(unittest.TestCase):
    def test_only_ordinary_priced_and_traded_stocks_are_eligible(self):
        params = ScreenerParams()
        self.assertTrue(eligible_row('1234', quote(price='10', volume=500), params))
        self.assertFalse(eligible_row('1234', quote(price='9.99', volume=500), params))
        self.assertFalse(eligible_row('1234', quote(price='10', volume=499), params))
        self.assertFalse(eligible_row('0050', quote('0050'), params))
        self.assertFalse(eligible_row('2882A', quote('2882A'), params))

    def test_typical_amount_is_the_amount_divided_by_the_volume_ratio(self):
        self.assertEqual(typical_amount(quote(amount=40_000_000, ratio='4')), 10_000_000)
        self.assertIsNone(typical_amount(quote(ratio=None)))
        self.assertIsNone(typical_amount(quote(ratio='0')))

    def test_rows_rank_by_ratio_then_amount_then_code_and_skip_ineligible_ones(self):
        rows = {
            '1111': quote('1111', ratio='2', amount=10),
            '2222': quote('2222', ratio='5', amount=10),
            '3333': quote('3333', ratio='5', amount=20),
            '4444': quote('4444', ratio='5', amount=20),
            '0050': quote('0050', ratio='9'),
            '5555': quote('5555', ratio='9', price='9'),
            '6666': quote('6666', ratio=None),
        }
        ranked = rank_surges(rows, ScreenerParams(), lambda code, row: typical_amount(row))
        self.assertEqual([entry.code for entry in ranked], ['3333', '4444', '2222', '1111'])

    def test_ranking_starts_after_the_warmup_in_session_and_is_always_open_off_session(self):
        params = ScreenerParams()
        self.assertFalse(ranking_open(MONDAY_0905, params))
        self.assertFalse(ranking_open(at(9, 8, 56), params))
        self.assertTrue(ranking_open(MONDAY_0910, params))
        self.assertTrue(ranking_open(MONDAY_1340, params))
        self.assertTrue(ranking_open(at(9, 8, 30), params))  # before the session: yesterday's final data
        self.assertTrue(ranking_open(at(14, 10, 0), params))  # a Saturday
        self.assertFalse(ranking_open(at(9, 9, 20), ScreenerParams(warmup_minutes=30)))
        self.assertTrue(ranking_open(at(9, 9, 1), ScreenerParams(warmup_minutes=0)))


class DownloadWindowTests(unittest.TestCase):
    def test_intraday_requests_stop_at_the_previous_weekday_close(self):
        start, end = download_window(MONDAY_1000, 365)
        self.assertEqual((start, end), (MONDAY_1000 - timedelta(days=365), at(6, 13, 35)))  # Friday
        self.assertEqual(download_window(at(10, 11, 0), 365)[1], at(9, 13, 35))  # Tuesday -> Monday

    def test_after_the_close_and_on_weekends_the_request_reaches_now(self):
        self.assertEqual(download_window(MONDAY_1340, 365)[1], MONDAY_1340)
        self.assertEqual(download_window(at(14, 10, 0), 365)[1], at(14, 10, 0))
        self.assertEqual(download_window(at(9, 13, 35), 365)[1], at(6, 13, 35))  # the close minute itself is still in session


class Recorder:
    def __init__(self):
        self.requests = []

    def request(self, instrument, start, end, priority=0):
        self.requests.append((instrument.code, start, end, priority))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.history, self.logged, self.params = Recorder(), [], ScreenerParams()
        self.stocks = tuple(stock(code) for code in ('1234', '2345', '3456'))
        self.screener = StockScreener(
            lambda: self.params, lambda: self.stocks, self.history, lambda item, condition, when: self.logged.append((item.code, condition, when))
        )

    def rows(self, *rows):
        return {row.code: row for row in rows}

    def test_no_list_and_no_download_before_the_warmup_ends(self):
        self.screener.on_round(MONDAY_0905, self.rows(quote(when=MONDAY_0905)))
        result = self.screener.result()
        self.assertEqual((result.ranking, result.surges, result.trade_date), (False, (), date(2026, 11, 9)))
        self.assertEqual((self.history.requests, self.logged), ([], []))

    def test_a_long_red_is_listed_downloaded_for_a_year_at_low_priority_and_logged(self):
        self.screener.on_round(
            MONDAY_0910, self.rows(quote(when=MONDAY_0910), quote('2345', ratio='1.2', pct='1', price='100', high='101', amount=1, when=MONDAY_0910))
        )
        self.assertEqual([entry.code for entry in self.screener.result().surges], ['1234', '2345'])
        self.assertEqual(self.screener.result().surges[0].pattern, SURGE_RED)
        self.assertEqual(self.history.requests, [('1234', MONDAY_0910 - timedelta(days=365), at(6, 13, 35), SCREENER_PRIORITY)])
        self.assertEqual(self.logged, [('1234', SURGE_RED, MONDAY_0910)])

    def test_the_download_priority_is_below_the_chart_and_every_watchlist_position(self):
        self.assertGreater(SCREENER_PRIORITY, 2 + 1000)

    def test_one_trigger_per_stock_condition_and_day(self):
        rows = self.rows(quote(when=MONDAY_1000))
        self.screener.on_round(MONDAY_1000, rows)
        self.screener.on_round(MONDAY_1000 + timedelta(seconds=10), rows)
        self.assertEqual(len(self.history.requests), 1)
        self.assertEqual(len(self.logged), 1)
        tuesday = at(10, 10, 0)
        self.screener.on_round(tuesday, self.rows(quote(when=tuesday)))
        self.assertEqual(len(self.history.requests), 2)  # the next day triggers again
        self.assertEqual(self.history.requests[1][2], at(9, 13, 35))

    def test_long_black_is_listed_but_not_downloaded_until_enabled(self):
        rows = self.rows(black(when=MONDAY_1000))
        self.screener.on_round(MONDAY_1000, rows)
        self.assertEqual(self.screener.result().surges[0].pattern, SURGE_BLACK)
        self.assertEqual((self.history.requests, self.logged), ([], []))
        self.params = replace(self.params, download_black=True)
        self.screener.on_round(MONDAY_1000 + timedelta(seconds=10), rows)
        self.assertEqual(self.logged, [('1234', SURGE_BLACK, MONDAY_1000 + timedelta(seconds=10))])
        self.assertEqual(len(self.history.requests), 1)

    def test_red_download_can_be_switched_off_and_the_row_is_still_listed(self):
        self.params = replace(self.params, download_red=False)
        self.screener.on_round(MONDAY_1000, self.rows(quote(when=MONDAY_1000)))
        self.assertEqual(self.screener.result().surges[0].pattern, SURGE_RED)
        self.assertEqual(self.history.requests, [])

    def test_matches_beyond_the_list_cap_still_trigger(self):
        self.params = ScreenerParams(list_rows=10)
        crowd = [quote(f'{5000 + index}', ratio='8', pct='1', price='100', high='100', amount=10**9, when=MONDAY_1000) for index in range(12)]
        self.stocks = (*self.stocks, *(stock(row.code) for row in crowd))
        self.screener.on_round(MONDAY_1000, self.rows(*crowd, quote(ratio='3', when=MONDAY_1000)))
        self.assertEqual(len(self.screener.result().surges), 10)
        self.assertNotIn('1234', [entry.code for entry in self.screener.result().surges])
        self.assertEqual([code for code, *_ in self.history.requests], ['1234'])

    def test_a_stock_missing_from_the_directory_is_skipped_and_tried_again_next_round(self):
        self.stocks = ()
        self.screener.on_round(MONDAY_1000, self.rows(quote(when=MONDAY_1000)))
        self.assertEqual((self.history.requests, self.logged), ([], []))
        self.stocks = (stock('1234'),)
        self.screener.on_round(MONDAY_1000 + timedelta(seconds=10), self.rows(quote(when=MONDAY_1000)))
        self.assertEqual(len(self.history.requests), 1)

    def test_triggers_already_in_the_alert_log_are_not_repeated_after_a_restart(self):
        self.screener.seed(((date(2026, 11, 9), '1234', SURGE_RED),))
        self.screener.on_round(MONDAY_1000, self.rows(quote(when=MONDAY_1000)))
        self.assertEqual((self.history.requests, self.logged), ([], []))

    def test_after_the_close_todays_triggers_are_extended_to_now_once(self):
        self.screener.on_round(
            MONDAY_1000, self.rows(quote(when=MONDAY_1000), quote('2345', ratio='1.1', pct='1', price='100', high='101', amount=1, when=MONDAY_1000))
        )
        self.assertEqual(len(self.history.requests), 1)
        closing = MONDAY_1340
        rows = self.rows(quote(when=at(9, 13, 30)))
        self.screener.on_round(closing, rows)
        self.assertEqual(self.history.requests[1:], [('1234', closing - timedelta(days=365), closing, SCREENER_PRIORITY)])
        self.screener.on_round(closing + timedelta(minutes=5), rows)
        self.assertEqual(len(self.history.requests), 2)

    def test_the_closing_round_downloads_a_first_time_match_up_to_now(self):
        self.screener.on_round(MONDAY_1340, self.rows(quote(when=at(9, 13, 30))))
        self.assertEqual(self.history.requests[0][2], MONDAY_1340)
        self.assertEqual(len(self.history.requests), 1)
        self.assertEqual(len(self.logged), 1)

    def test_weekend_data_is_judged_under_the_last_trading_day_and_never_refilled(self):
        saturday = at(14, 10, 0)
        self.screener.seed(((date(2026, 11, 13), '1234', SURGE_RED),))  # Friday's trigger is already logged
        self.screener.on_round(saturday, self.rows(quote(when=at(13, 13, 30))))
        self.assertEqual(self.screener.result().trade_date, date(2026, 11, 13))
        self.assertEqual((self.history.requests, self.logged), ([], []))

    def test_an_empty_round_changes_nothing(self):
        self.screener.on_round(MONDAY_1000, {})
        self.assertEqual(self.screener.result().ranking, False)
        self.assertEqual(self.history.requests, [])

    def test_a_paused_history_sync_still_lists_and_keeps_the_download_queued(self):
        sync = HistorySync(SimpleNamespace(), SimpleNamespace(), now=lambda: MONDAY_1000, autostart=False)
        sync.disconnected()
        screener = StockScreener(lambda: self.params, lambda: self.stocks, sync, lambda *args: None)
        screener.on_round(MONDAY_1000, self.rows(quote(when=MONDAY_1000)))
        self.assertEqual([entry.pattern for entry in screener.result().surges], [SURGE_RED])
        state = sync.state()
        self.assertEqual((state.paused, state.pending), (True, 1))
        sync.close()

    def test_the_download_goes_through_the_real_history_queue_below_a_watchlist_request(self):
        sync = HistorySync(SimpleNamespace(), SimpleNamespace(), now=lambda: MONDAY_1000, autostart=False)
        screener = StockScreener(lambda: self.params, lambda: self.stocks, sync, lambda *args: None)
        screener.on_round(MONDAY_1000, self.rows(quote(when=MONDAY_1000)))
        sync.request(self.stocks[1], MONDAY_1000 - timedelta(days=30), MONDAY_1000, priority=2)
        order = sorted(sync._queue, key=lambda item: item.priority)
        self.assertEqual([item.instrument.code for item in order], ['2345', '1234'])
        sync.close()


if __name__ == '__main__':
    unittest.main()
