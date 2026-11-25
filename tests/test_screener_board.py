"""M6-2: the screener read model: lists, the K-line column, the downloaded-K-line catalogue and the manual download."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from quantlab.trading.application.screener_board import DOWNLOADED_TTL, ScreenerBoard
from quantlab.trading.application.screener_contracts import ScreenerQuery, ScreenerRowView, ScreenerView
from quantlab.trading.application.stock_screener import SCREENER_PRIORITY, StockScreener, download_window
from quantlab.trading.domain.screener import ScreenerParams
from quantlab.trading.domain.market_daily import DailyStats
from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind, watch_future

TAIPEI = timezone(timedelta(hours=8))
MONDAY_1000 = datetime(2026, 11, 9, 10, 0, tzinfo=TAIPEI)
MONDAY_0905 = datetime(2026, 11, 9, 9, 5, tzinfo=TAIPEI)


def stock(code, name=None):
    return WatchInstrument(f'TWSE:{code}', WatchKind.STOCK, 'TSE', code, name or 'N' + code, '24')


def quote(code, when=MONDAY_1000, red=True, ratio='4', amount=40_000_000):
    if red:
        return QuoteRow(code, Decimal('110'), Decimal(10), '', 2000, amount, Decimal(ratio), when, Decimal(100), Decimal('110.5'), Decimal(99))
    return QuoteRow(code, Decimal(90), Decimal(-10), '', 2000, amount, Decimal(ratio), when, Decimal(100), Decimal(101), Decimal('89.5'))


class FakeHistory:
    def __init__(self):
        self.requests, self.running, self.errors = [], set(), ()

    def request(self, instrument, start, end, priority=0):
        self.requests.append((instrument.code, start, end, priority))

    def is_backfilling(self, instrument_id):
        return instrument_id in self.running

    def state(self):
        return SimpleNamespace(history_error=self.errors)


class FakeStore:
    def __init__(self):
        self.missing, self.extents, self.fail, self.calls = {}, {}, None, 0

    def instrument_ids(self):
        self.calls += 1
        if self.fail:
            raise DomainError(self.fail)
        return tuple(self.extents)

    def minute_extent(self, instrument_id):
        return self.extents[instrument_id]

    def missing_ranges(self, instrument_id, start, end):
        if self.fail:
            raise DomainError(self.fail)
        return self.missing.get(instrument_id, ())


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.now, self.status, self.clock_value, self.params = MONDAY_1000, 'LIVE', 0.0, ScreenerParams()
        self.stocks = (stock('1234', '甲'), stock('2345', '乙'), stock('3456', '丙'))
        self.history, self.store = FakeHistory(), FakeStore()
        self.screener = StockScreener(lambda: self.params, lambda: self.stocks, self.history, lambda *args: None)
        self.board = ScreenerBoard(
            lambda: self.status,
            lambda: self.now,
            lambda: (*self.stocks, *FIXED_INDICES),
            self.screener,
            self.store,
            self.history,
            lambda: self.params,
            clock=lambda: self.clock_value,
        )

    def round(self, *rows, when=None):
        self.screener.on_round(when or self.now, {row.code: row for row in rows})

    def test_the_surge_list_has_names_patterns_and_the_filters_split_red_from_black(self):
        self.round(quote('1234'), quote('2345', red=False), quote('3456', ratio='1.2', amount=10))
        every = self.board.view(ScreenerQuery('SURGE'))
        self.assertEqual((every.list_id, every.state, every.min_volume_lots, every.data_at), ('SURGE', 'LIVE', 500, MONDAY_1000))
        self.assertEqual(
            [(row.code, row.name, row.label) for row in every.rows], [('1234', '甲', 'SURGE_RED'), ('2345', '乙', 'SURGE_BLACK'), ('3456', '丙', '')]
        )
        self.assertEqual([row.code for row in self.board.view(ScreenerQuery('SURGE', 'RED')).rows], ['1234'])
        self.assertEqual([row.code for row in self.board.view(ScreenerQuery('SURGE', 'BLACK')).rows], ['2345'])
        self.assertEqual(every.rows[0], ScreenerRowView('TWSE:1234', '1234', '甲', Decimal(110), Decimal(10), Decimal(4), 'SURGE_RED', 'YEAR', False))

    def test_rows_for_codes_outside_the_directory_are_dropped(self):
        self.round(quote('1234'), quote('9999'))
        self.assertEqual([row.code for row in self.board.view(ScreenerQuery('SURGE')).rows], ['1234'])

    def test_offline_and_empty_have_no_rows_and_the_warmup_shows_no_list(self):
        for state in ('OFFLINE', 'EMPTY'):
            self.status = state
            view = self.board.view(ScreenerQuery('SURGE'))
            self.assertEqual((view.state, view.rows), (state, ()))
        self.status, self.now = 'LIVE', MONDAY_0905
        self.round(quote('1234', when=MONDAY_0905), when=MONDAY_0905)
        view = self.board.view(ScreenerQuery('SURGE'))
        self.assertEqual((view.state, view.rows), ('WARMUP', ()))
        self.status = 'CLOSED'
        self.assertEqual(self.board.view(ScreenerQuery('SURGE')).state, 'CLOSED')

    def test_the_kline_column_says_year_downloading_failed_or_nothing(self):
        self.round(quote('1234'), quote('2345'), quote('3456'))
        self.store.missing = {'TWSE:2345': ((MONDAY_1000, MONDAY_1000 + timedelta(days=1)),), 'TWSE:3456': ((MONDAY_1000, MONDAY_1000 + timedelta(days=1)),)}
        self.history.running = {'TWSE:3456'}
        states = {row.code: row.kline for row in self.board.view(ScreenerQuery('SURGE')).rows}
        self.assertEqual(states, {'1234': 'YEAR', '2345': '', '3456': 'DOWNLOADING'})
        self.history.running, self.history.errors = set(), (('TWSE:2345', 'history_query_failed'),)
        self.assertEqual({row.code: row.kline for row in self.board.view(ScreenerQuery('SURGE')).rows}['2345'], 'FAILED')

    def test_the_kline_year_check_uses_the_same_window_as_the_download(self):
        self.round(quote('1234'))
        seen = []
        self.store.missing_ranges = lambda instrument_id, start, end: seen.append((start, end)) or ()
        self.board.view(ScreenerQuery('SURGE'))
        self.assertEqual(seen, [download_window(self.now, 365)])

    def test_an_unreadable_kline_store_still_shows_the_list_with_a_reason_code(self):
        self.round(quote('1234'))
        self.store.fail = 'kline_store_unavailable'
        view = self.board.view(ScreenerQuery('SURGE'))
        self.assertEqual(([row.kline for row in view.rows], view.code), ([''], 'kline_store_unavailable'))

    def test_any_failure_of_the_kline_store_becomes_the_reason_code_not_a_failed_read(self):
        import sqlite3

        self.round(quote('1234'))
        self.store.missing_ranges = lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('database is locked'))
        view = self.board.view(ScreenerQuery('SURGE'))
        self.assertEqual(([row.code for row in view.rows], [row.kline for row in view.rows], view.code), (['1234'], [''], 'kline_store_unavailable'))
        self.store.instrument_ids = lambda: (_ for _ in ()).throw(sqlite3.OperationalError('database is locked'))
        view = self.board.view(ScreenerQuery('DOWNLOADED'))
        self.assertEqual((view.downloaded, view.code), ((), 'kline_store_unavailable'))

    def test_the_breakout_list_only_accumulates_until_the_daily_quotes_cover_the_shortest_window(self):
        view = self.board.view(ScreenerQuery('BREAKOUT'))
        self.assertEqual((view.state, view.rows, view.progress_days, view.progress_needed), ('ACCUMULATING', (), 0, 60))
        daily = SimpleNamespace(stats=lambda day: {'1234': DailyStats(59, (), 1000, 80_000_000)}, days=lambda day: 59, record_close=lambda day, rows: None)
        self.screener.daily = daily
        self.round(quote('1234'))
        view = self.board.view(ScreenerQuery('BREAKOUT'))
        self.assertEqual((view.state, view.progress_days, view.progress_needed, view.data_at), ('ACCUMULATING', 59, 60, MONDAY_1000))

    def test_an_unusable_daily_file_is_named_while_the_list_accumulates(self):
        board = ScreenerBoard(
            lambda: 'LIVE',
            lambda: self.now,
            lambda: (*self.stocks, *FIXED_INDICES),
            self.screener,
            self.store,
            self.history,
            lambda: self.params,
            clock=lambda: self.clock_value,
            daily_code=lambda: 'market_daily_unavailable',
        )
        view = board.view(ScreenerQuery('BREAKOUT'))
        self.assertEqual((view.state, view.code, view.progress_days), ('ACCUMULATING', 'market_daily_unavailable', 0))
        self.assertEqual(self.board.view(ScreenerQuery('BREAKOUT')).code, '')  # a healthy file names nothing

    def test_the_breakout_list_names_the_window_the_strength_and_whether_it_is_provisional(self):
        stats = {
            '1234': DailyStats(240, ((60, Decimal(105)), (120, Decimal(108))), 1000, 80_000_000),
            '2345': DailyStats(240, ((60, Decimal(105)),), 1000, 80_000_000),
        }
        self.screener.daily = SimpleNamespace(stats=lambda day: stats, days=lambda day: 240, record_close=lambda day, rows: None)
        self.round(quote('1234'), quote('2345', ratio='2.5'), quote('3456', ratio='9'))
        view = self.board.view(ScreenerQuery('BREAKOUT'))
        self.assertEqual(
            [(row.code, row.name, row.label, row.ratio, row.provisional, row.kline) for row in view.rows],
            [('1234', '甲', '120', Decimal(4), True, 'YEAR'), ('2345', '乙', '60', Decimal('2.5'), True, 'YEAR')],
        )
        self.assertEqual((view.state, view.min_volume_lots), ('LIVE', 500))
        self.status = 'OFFLINE'
        self.assertEqual(self.board.view(ScreenerQuery('BREAKOUT')).rows, ())
        self.status = 'LIVE'
        self.now = MONDAY_0905
        self.round(quote('1234', when=MONDAY_0905), when=MONDAY_0905)
        self.assertEqual(self.board.view(ScreenerQuery('BREAKOUT')).state, 'WARMUP')

    def test_the_downloaded_list_reads_extents_without_counting_and_sorts_by_code(self):
        early, late, updated = MONDAY_1000 - timedelta(days=364), MONDAY_1000, MONDAY_1000 + timedelta(hours=1)
        self.store.extents = {'TWSE:3456': (early, late, updated), 'TWSE:1234': (early, late, None), 'TWSE:7777': (early, late, updated), 'INDEX:IX0001': None}
        view = self.board.view(ScreenerQuery('DOWNLOADED'))
        self.assertEqual([(row.code, row.name) for row in view.downloaded], [('1234', '甲'), ('3456', '丙'), ('7777', '7777')])
        self.assertEqual((view.downloaded[0].first, view.downloaded[0].last, view.downloaded[0].updated), (early, late, None))
        self.assertEqual(view.downloaded[1].updated, updated)

    def test_downloaded_stock_futures_are_not_listed_because_the_terminal_cannot_open_them(self):
        self.store.extents = {'TWSE:1234': (MONDAY_1000, MONDAY_1000, None), 'TAIFEX:CDFR1': (MONDAY_1000, MONDAY_1000, None)}
        self.assertEqual([row.code for row in self.board.view(ScreenerQuery('DOWNLOADED')).downloaded], ['1234'])

    def test_watchable_futures_in_the_store_still_list_whether_or_not_the_directory_knows_them(self):
        self.store.extents = {
            'TAIFEX:TXFR1': (MONDAY_1000, MONDAY_1000, None),  # whitelisted and in the directory below: its name
            'TAIFEX:MXFR1': (MONDAY_1000, MONDAY_1000, None),  # whitelisted but the directory (broker futures list unavailable) lacks it: the code
            'TAIFEX:CDFR1': (MONDAY_1000, MONDAY_1000, None),  # a downloaded stock future: data only
        }
        self.board.directory = lambda: (*self.stocks, *FIXED_INDICES, watch_future('TXFR1'))
        self.assertEqual(
            [(row.code, row.name) for row in self.board.view(ScreenerQuery('DOWNLOADED')).downloaded], [('MXFR1', 'MXFR1'), ('TXFR1', '臺股期貨近月')]
        )

    def test_the_downloaded_list_is_cached_briefly_and_a_download_refreshes_it(self):
        self.store.extents = {'TWSE:1234': (MONDAY_1000, MONDAY_1000, None)}
        self.board.view(ScreenerQuery('DOWNLOADED'))
        self.board.view(ScreenerQuery('DOWNLOADED'))
        self.assertEqual(self.store.calls, 1)
        self.clock_value = DOWNLOADED_TTL + 1
        self.board.view(ScreenerQuery('DOWNLOADED'))
        self.assertEqual(self.store.calls, 2)
        self.board.view(ScreenerQuery('DOWNLOADED', download_id='TWSE:1234'))
        self.assertEqual(self.store.calls, 3)

    def test_an_unreadable_store_gives_an_empty_downloaded_list_with_a_reason_code(self):
        self.store.fail = 'kline_store_unavailable'
        view = self.board.view(ScreenerQuery('DOWNLOADED'))
        self.assertEqual((view.downloaded, view.code), ((), 'kline_store_unavailable'))

    def test_a_manual_download_uses_the_automatic_path_priority_and_window(self):
        self.round(quote('1234'))
        self.history.requests.clear()  # the automatic trigger of the long red is not under test here
        view = self.board.view(ScreenerQuery('SURGE', 'ALL', 'TWSE:3456'))
        self.assertIsInstance(view, ScreenerView)
        start, end = download_window(self.now, 365)
        self.assertEqual(self.history.requests, [('3456', start, end, SCREENER_PRIORITY)])

    def test_a_manual_download_of_an_unknown_instrument_is_refused(self):
        with self.assertRaises(DomainError):
            self.board.view(ScreenerQuery('SURGE', 'ALL', 'TWSE:0000'))
        self.assertEqual(self.history.requests, [])

    def test_a_query_must_name_a_known_list_and_pattern(self):
        for values in (dict(list_id='GAP'), dict(pattern='GREEN'), dict(download_id='x' * 201)):
            with self.subTest(values=values), self.assertRaises(DomainError):
                ScreenerQuery(**values)


if __name__ == '__main__':
    unittest.main()
