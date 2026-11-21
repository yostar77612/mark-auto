"""M6-3: market-wide daily quotes: parsers (offline fixtures), store, statistics, breakout judgement and the backfill."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.official.market_daily_data import OfficialDailySource, parse_tpex, parse_twse, tpex_url, twse_url
from quantlab.trading.adapters.storage.market_daily_store import MarketDailyStore
from quantlab.trading.application.market_daily import MarketDaily, MarketDailyBackfill, snapshot_quotes
from quantlab.trading.domain.market_daily import DailyQuote, DailyRow, DailyStats, breakout_window, daily_stats, volume_breakout
from quantlab.trading.domain.screener import ScreenerParams
from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.market_daily import validate_daily_url

FIXTURES = Path(__file__).parent / 'fixtures' / 'market_daily'
FRIDAY = date(2026, 11, 20)
TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=TAIPEI)


def fixture(name):
    return (FIXTURES / name).read_bytes()


def quote(code='1234', day=FRIDAY, close='100', high='101', volume=1000, amount=100_000_000, source='OFFICIAL'):
    return DailyQuote(code, day, Decimal('99'), Decimal(high), Decimal('98'), Decimal(close), volume, amount, source)


class ParserTests(unittest.TestCase):
    def test_twse_rows_are_ordinary_shares_that_traded_with_lots_and_exact_decimals(self):
        quotes = parse_twse(fixture('twse_20261120.json'), FRIDAY)
        self.assertEqual({item.code for item in quotes}, {'2330', '2317', '1101'})  # the ETF and the no-trade 1538 are out
        tsmc = next(item for item in quotes if item.code == '2330')
        self.assertEqual(
            (tsmc.open, tsmc.high, tsmc.low, tsmc.close, tsmc.volume, tsmc.amount, tsmc.source, tsmc.trade_date),
            (Decimal('2035.00'), Decimal('2060.00'), Decimal('1970.00'), Decimal('2000.00'), 88179, 177_284_650_683, 'OFFICIAL', FRIDAY),
        )
        self.assertEqual(next(item for item in quotes if item.code == '1101').close, Decimal('24.35'))

    def test_tpex_rows_use_their_own_column_order(self):
        quotes = parse_tpex(fixture('tpex_20261120.json'), FRIDAY)
        self.assertEqual({item.code for item in quotes}, {'3293', '6488', '8069'})  # the ETF and the no-trade 2235 are out
        first = next(item for item in quotes if item.code == '3293')
        self.assertEqual(
            (first.open, first.high, first.low, first.close, first.volume, first.amount),
            (Decimal('771.00'), Decimal('783.00'), Decimal('749.00'), Decimal('754.00'), 2099, 1_599_525_000),
        )

    def test_a_holiday_is_a_recognised_empty_answer(self):
        self.assertIsNone(parse_twse(fixture('twse_holiday.json'), date(2026, 11, 21)))
        self.assertIsNone(parse_tpex(fixture('tpex_holiday.json'), date(2026, 11, 21)))

    def test_anything_else_is_refused_and_never_taken_for_a_holiday(self):
        twse = json.loads(fixture('twse_20261120.json'))
        for raw in (
            b'',
            b'not json',
            b'[]',
            b'{"stat":"OK"}',  # no tables
            b'{"stat":"too many requests"}',  # an error text is not the recognised no-data answer
            json.dumps({**twse, 'date': '20261119'}).encode(),  # answers for another day
            json.dumps({**twse, 'stat': 'busy'}).encode(),
            json.dumps({**twse, 'tables': [twse['tables'][0]]}).encode(),  # no daily table
            json.dumps({**twse, 'tables': [{**twse['tables'][1], 'fields': ['x']}]}).encode(),
            b'x' * (8 * 1024 * 1024 + 1),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(DomainError):
                parse_twse(raw, FRIDAY)
        tpex = json.loads(fixture('tpex_20261120.json'))
        for raw in (
            b'{}',
            json.dumps({**tpex, 'date': '20261119'}).encode(),
            json.dumps({**tpex, 'stat': 'error'}).encode(),
            json.dumps({**tpex, 'tables': []}).encode(),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(DomainError):
                parse_tpex(raw, FRIDAY)

    def test_a_duplicate_code_or_a_day_of_unparseable_rows_is_refused(self):
        twse = json.loads(fixture('twse_20261120.json'))
        table = twse['tables'][1]
        twice = {**twse, 'tables': [twse['tables'][0], {**table, 'data': [table['data'][0], table['data'][0]]}]}
        with self.assertRaises(DomainError):
            parse_twse(json.dumps(twice).encode(), FRIDAY)
        broken = [[row[0], *row[1:5], 'x', 'x', 'x', 'x', *row[9:]] for row in table['data'] if row[0] == '2330']
        with self.assertRaises(DomainError):
            parse_twse(json.dumps({**twse, 'tables': [twse['tables'][0], {**table, 'data': broken}]}).encode(), FRIDAY)

    def test_the_port_picks_the_right_parser_and_url(self):
        source = OfficialDailySource()
        self.assertEqual(source.url('TWSE', FRIDAY), twse_url(FRIDAY))
        self.assertEqual(source.url('TPEX', FRIDAY), tpex_url(FRIDAY))
        self.assertEqual(len(source.parse('TWSE', fixture('twse_20261120.json'), FRIDAY)), 3)
        self.assertEqual(len(source.parse('TPEX', fixture('tpex_20261120.json'), FRIDAY)), 3)

    def test_urls_are_the_two_fixed_official_endpoints(self):
        self.assertEqual(twse_url(FRIDAY), 'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=20261120&type=ALLBUT0999')
        self.assertEqual(tpex_url(FRIDAY), 'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=2026%2F11%2F20&type=EW&response=json')
        for url in (twse_url(FRIDAY), tpex_url(FRIDAY)):
            self.assertEqual(validate_daily_url(url), url)
        for url in (
            twse_url(FRIDAY).replace('https', 'http'),
            twse_url(FRIDAY) + '&token=x',
            twse_url(FRIDAY).replace('ALLBUT0999', 'ALL'),
            twse_url(FRIDAY).replace('www.twse.com.tw', 'example.com'),
            twse_url(FRIDAY).replace('20261120', '2026-11-20'),
            tpex_url(FRIDAY).replace('EW', 'AL'),
            tpex_url(FRIDAY) + '#frag',
            'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261101&stockNo=2330',
        ):
            with self.subTest(url=url), self.assertRaises(DomainError):
                validate_daily_url(url)


class DomainTests(unittest.TestCase):
    def rows(self, count, high='100', volume=1000, amount=100_000_000):
        start = date(2026, 1, 5)
        return [DailyRow(start + timedelta(days=index), Decimal(high), volume, amount) for index in range(count)]

    def test_a_window_or_average_the_history_cannot_cover_is_absent(self):
        stats = daily_stats(self.rows(59), (60, 120, 240), 20)
        self.assertEqual((stats.days, stats.highs), (59, ()))
        self.assertEqual((stats.avg_volume, stats.avg_amount), (1000, 100_000_000))
        self.assertEqual(daily_stats(self.rows(60), (60, 120, 240), 20).highs, ((60, Decimal(100)),))
        self.assertEqual([window for window, _ in daily_stats(self.rows(120), (240, 60, 120), 20).highs], [60, 120])
        short = daily_stats(self.rows(19), (60,), 20)
        self.assertEqual((short.avg_volume, short.avg_amount), (None, None))

    def test_windows_look_at_the_latest_days_only_and_the_average_is_integer_lots_and_nt_dollars(self):
        rows = self.rows(70)
        rows[0] = DailyRow(rows[0].trade_date, Decimal(500), 9, 9)  # older than every 60-day window
        rows[-1] = DailyRow(rows[-1].trade_date, Decimal(120), 2000, 300_000_000)
        stats = daily_stats(rows, (60,), 20)
        self.assertEqual(stats.highs, ((60, Decimal(120)),))
        self.assertEqual((stats.avg_volume, stats.avg_amount), ((19 * 1000 + 2000) // 20, (19 * 100_000_000 + 300_000_000) // 20))

    def test_the_largest_window_whose_high_the_price_exceeds_is_reported(self):
        stats = DailyStats(240, ((60, Decimal(100)), (120, Decimal(110)), (240, Decimal(130))))
        self.assertIsNone(breakout_window(Decimal(100), stats))  # equal is not above
        self.assertEqual(breakout_window(Decimal('100.01'), stats), 60)
        self.assertEqual(breakout_window(Decimal('110.01'), stats), 120)
        self.assertEqual(breakout_window(Decimal('130.01'), stats), 240)
        self.assertIsNone(breakout_window(Decimal(200), DailyStats(10)))

    def test_final_breakout_needs_the_volume_multiple_and_provisional_needs_the_volume_ratio(self):
        stats = DailyStats(240, ((60, Decimal(100)),), 1000, 100_000_000)
        final = dict(final=True, multiple=Decimal(2), intraday_ratio=Decimal(2))
        self.assertEqual(volume_breakout(Decimal(101), 2000, None, stats, **final), (60, Decimal(2)))  # exactly twice the average
        self.assertIsNone(volume_breakout(Decimal(101), 1999, None, stats, **final))
        self.assertIsNone(volume_breakout(Decimal(100), 5000, None, stats, **final))  # not above the high
        self.assertIsNone(volume_breakout(Decimal(101), 5000, None, DailyStats(240, ((60, Decimal(100)),)), **final))  # no average yet
        provisional = dict(final=False, multiple=Decimal(2), intraday_ratio=Decimal(2))
        self.assertEqual(volume_breakout(Decimal(101), 10, Decimal(2), stats, **provisional), (60, Decimal(2)))
        self.assertIsNone(volume_breakout(Decimal(101), 10**6, Decimal('1.99'), stats, **provisional))
        self.assertIsNone(volume_breakout(Decimal(101), 10**6, None, stats, **provisional))

    def test_a_daily_quote_must_be_a_real_bar(self):
        for values in (dict(high='97'), dict(close='0'), dict(volume=-1), dict(source='GUESS')):
            with self.subTest(values=values), self.assertRaises(DomainError):
                quote(**values)

    def test_the_new_breakout_thresholds_are_validated(self):
        for values in (
            dict(window_short=120),  # windows must increase
            dict(window_mid=60),
            dict(average_days=4),
            dict(breakout_volume_multiple=Decimal('0.5')),
            dict(breakout_intraday_ratio=Decimal(21)),
            dict(download_breakout=1),
        ):
            with self.subTest(values=values), self.assertRaises(DomainError):
                ScreenerParams(**values)
        self.assertEqual(ScreenerParams().windows, (60, 120, 240))
        self.assertEqual(ScreenerParams.from_dict(ScreenerParams(window_long=300).as_dict()).window_long, 300)
        self.assertEqual(ScreenerParams.from_dict({'surge_ratio': '4'}).window_short, 60)  # an older settings file still loads


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'market' / 'market_daily.sqlite3'
        self.store = MarketDailyStore(self.path.resolve())
        self.addCleanup(self.store.close)

    def days(self, count, start=date(2026, 1, 5)):
        return [start + timedelta(days=index) for index in range(count)]

    def test_an_official_row_replaces_a_snapshot_row_but_never_the_other_way_round(self):
        self.store.upsert((quote(close='100', source='SNAPSHOT'),))
        self.store.upsert((quote(close='101', source='OFFICIAL'),))
        self.store.upsert((quote(close='102', source='SNAPSHOT'),))
        self.store.mark(FRIDAY, 'TWSE', 'https://x/1', 1, NOW)
        (row,) = (rows for _, rows in self.store.history(FRIDAY + timedelta(days=1), 5))
        self.assertEqual((row[0].high, row[0].volume), (Decimal('101'), 1000))
        self.store.upsert((quote(close='103', high='104', source='SNAPSHOT'),))
        self.assertEqual(next(rows for _, rows in self.store.history(FRIDAY + timedelta(days=1), 5))[0].high, Decimal('101'))

    def test_the_ledger_records_what_was_fetched_with_its_url_and_a_holiday_as_zero_rows(self):
        self.assertEqual(self.store.fetched(FRIDAY), {})
        self.store.mark(FRIDAY, 'TWSE', 'https://x/1', 1100, NOW)
        self.store.mark(FRIDAY, 'TPEX', 'https://x/2', 0, NOW)
        self.assertEqual(self.store.fetched(FRIDAY), {'TWSE': 1100, 'TPEX': 0})
        with self.assertRaises(DomainError):
            self.store.mark(FRIDAY, 'NYSE', 'https://x/3', 1, NOW)

    def test_trade_days_are_days_with_rows_before_a_date_latest_first_limited_and_ascending(self):
        for index, day in enumerate(self.days(6)):
            self.store.mark(day, 'TWSE', 'https://x/' + str(index), 0 if index == 2 else 10, NOW)
        days = self.days(6)
        self.assertEqual(self.store.trade_days(days[-1] + timedelta(days=1), 10), (days[0], days[1], days[3], days[4], days[5]))
        self.assertEqual(self.store.trade_days(days[-1] + timedelta(days=1), 2), (days[4], days[5]))
        self.assertEqual(self.store.trade_days(days[3], 10), (days[0], days[1]))  # strictly before

    def test_history_streams_one_stock_at_a_time_in_date_order_inside_the_window(self):
        days = self.days(5)
        for day in days:
            self.store.upsert((quote('1111', day, high=str(100 + day.day)), quote('2222', day, high='98', volume=day.day)))
            self.store.mark(day, 'TWSE', 'https://x/' + day.isoformat(), 2, NOW)
        history = dict(self.store.history(days[-1] + timedelta(days=1), 3))
        self.assertEqual(sorted(history), ['1111', '2222'])
        self.assertEqual([row.trade_date for row in history['1111']], days[2:])
        self.assertEqual([row.volume for row in history['2222']], [day.day for day in days[2:]])
        self.assertEqual(history['1111'][0].high, Decimal(100 + days[2].day))
        self.assertEqual(dict(self.store.history(days[0], 3)), {})  # nothing before the first day

    def test_revision_advances_on_every_write_and_purge_drops_old_days(self):
        before = self.store.revision
        self.store.upsert((quote(),))
        self.store.mark(FRIDAY, 'TWSE', 'https://x/1', 1, NOW)
        self.assertEqual(self.store.revision, before + 2)
        old = date(2024, 1, 2)
        self.store.upsert((quote(day=old),))
        self.store.mark(old, 'TWSE', 'https://x/old', 1, NOW)
        self.assertEqual(self.store.purge(FRIDAY), 1)
        self.assertEqual(self.store.fetched(old), {})
        self.assertEqual(self.store.fetched(FRIDAY), {'TWSE': 1})

    def test_a_damaged_file_is_set_aside_and_a_fresh_one_starts(self):
        self.store.close()
        self.path.write_bytes(b'this is not a database' * 100)
        store = MarketDailyStore(self.path.resolve())
        self.addCleanup(store.close)
        self.assertEqual(store.warning, 'market_daily_corrupt')
        self.assertEqual(len(list(self.path.parent.glob('market_daily.sqlite3.bad-*'))), 1)
        store.upsert((quote(),))
        self.assertEqual(store.revision, 1)
        self.store = store

    def test_the_store_is_a_separate_file_from_the_kline_store(self):
        self.assertEqual(self.path.name, 'market_daily.sqlite3')
        self.assertTrue(self.path.exists())
        self.assertFalse((self.path.parent / 'klines.sqlite3').exists())


class MarketDailyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MarketDailyStore((Path(self.temp.name) / 'market_daily.sqlite3').resolve())
        self.addCleanup(self.store.close)
        self.params, self.clock_value = SimpleNamespace(windows=(3, 5, 8), average_days=5), 0.0  # short windows keep the fixture small
        self.daily = MarketDaily(self.store, lambda: self.params, lambda: NOW, ttl=60.0, clock=lambda: self.clock_value)
        self.days = [date(2026, 11, 9) + timedelta(days=index) for index in range(5)]  # Mon-Fri
        for index, day in enumerate(self.days):
            self.store.upsert((quote('1111', day, high=str(100 + index), volume=1000 * (index + 1), amount=10_000_000 * (index + 1)),))
            self.store.mark(day, 'TWSE', 'https://x/' + day.isoformat(), 1, NOW)

    def test_statistics_cover_the_days_before_the_judged_day(self):
        stats = self.daily.stats(date(2026, 11, 14))
        self.assertEqual(stats['1111'].days, 5)
        self.assertEqual(stats['1111'].highs, ((3, Decimal(104)), (5, Decimal(104))))
        self.assertEqual((stats['1111'].avg_volume, stats['1111'].avg_amount), (3000, 30_000_000))  # the last 5 days
        self.assertEqual(self.daily.stats(self.days[-1])['1111'].days, 4)  # the judged day itself is never part of its own history
        self.assertEqual(self.daily.days(date(2026, 11, 14)), 5)
        self.assertEqual(self.daily.days(self.days[2]), 2)

    def test_statistics_are_cached_until_the_store_changes_then_rebuilt_at_most_once_per_ttl(self):
        day = date(2026, 11, 14)
        first = self.daily.stats(day)
        self.assertIs(self.daily.stats(day), first)
        self.store.mark(date(2026, 11, 2), 'TWSE', 'https://x/older', 0, NOW)  # a store change inside the ttl
        self.assertIs(self.daily.stats(day), first)
        self.clock_value = 61.0
        self.assertIsNot(self.daily.stats(day), first)
        rebuilt = self.daily.stats(day)
        self.assertIs(self.daily.stats(day), rebuilt)
        self.assertIsNot(self.daily.stats(date(2026, 11, 15)), rebuilt)  # another day rebuilds at once
        self.params = SimpleNamespace(windows=(4, 5, 8), average_days=5)
        self.assertEqual([window for window, _ in self.daily.stats(date(2026, 11, 15))['1111'].highs], [4, 5])  # so do new thresholds

    def test_the_closing_snapshot_is_written_as_snapshot_rows_and_skips_rows_without_open_high_low(self):
        day = date(2026, 11, 16)
        full = QuoteRow('2222', Decimal(110), Decimal(10), '', 2000, 40_000_000, Decimal(4), NOW, Decimal(100), Decimal('110.5'), Decimal(99))
        partial = QuoteRow('3333', Decimal(110), Decimal(10), '', 2000, 40_000_000, Decimal(4), NOW)
        etf = QuoteRow('0050', Decimal(110), Decimal(10), '', 2000, 40_000_000, Decimal(4), NOW, Decimal(100), Decimal('110.5'), Decimal(99))
        self.daily.record_close(day, {'2222': full, '3333': partial, '0050': etf})
        self.assertEqual([item.code for item in snapshot_quotes({'2222': full, '3333': partial, '0050': etf}, day)], ['2222'])
        self.assertEqual(self.store.fetched(day), {'SNAPSHOT': 1})
        history = dict(self.store.history(date(2026, 11, 17), 5))
        self.assertEqual(history['2222'][-1].high, Decimal('110.5'))
        self.assertNotIn('3333', history)


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MarketDailyStore((Path(self.temp.name) / 'market_daily.sqlite3').resolve())
        self.addCleanup(self.store.close)
        self.today, self.fetched, self.fail = date(2026, 11, 21), [], False  # a Saturday
        self.holidays = {date(2026, 11, 18)}
        parsed = {
            'TWSE': lambda raw, day: None if day in self.holidays else (quote('1111', day),),
            'TPEX': lambda raw, day: None if day in self.holidays else (quote('2222', day),),
        }
        source = SimpleNamespace(
            url=lambda market, day: f'https://example.test/{market}/{day.isoformat()}', parse=lambda market, raw, day: parsed[market](raw, day)
        )

        def fetch(url):
            if self.fail:
                raise DomainError('official_stock_invalid', 'down')
            self.fetched.append(url)
            return b'{}'

        self.backfill = MarketDailyBackfill(self.store, source, fetch, lambda: self.today, lambda: NOW, target_days=3, max_age_days=30, pause=0, idle=0.01)

    def run_all(self):
        while self.backfill.step():
            pass

    def test_it_goes_newest_first_skips_weekends_and_today_and_stops_at_the_target_number_of_trading_days(self):
        self.run_all()
        days = sorted({url.rsplit('/', 1)[1] for url in self.fetched}, reverse=True)
        self.assertEqual(days, ['2026-11-20', '2026-11-19', '2026-11-18', '2026-11-17'])  # the 18th was a holiday: 3 trading days need 4 dates
        self.assertEqual(self.fetched[:2], ['https://example.test/TWSE/2026-11-20', 'https://example.test/TPEX/2026-11-20'])
        self.assertNotIn('2026-11-21', ''.join(self.fetched))  # today (Saturday) and the weekend are never asked for
        self.assertFalse(self.backfill.step())

    def test_every_request_is_recorded_with_its_url_a_holiday_as_zero_rows(self):
        self.run_all()
        self.assertEqual(self.store.fetched(date(2026, 11, 20)), {'TWSE': 1, 'TPEX': 1})
        self.assertEqual(self.store.fetched(date(2026, 11, 18)), {'TWSE': 0, 'TPEX': 0})
        self.assertEqual(self.store.trade_days(self.today, 10), (date(2026, 11, 17), date(2026, 11, 19), date(2026, 11, 20)))
        self.assertEqual(len(self.fetched), 8)

    def test_a_run_resumes_where_it_stopped_and_fetches_nothing_twice(self):
        for _ in range(3):
            self.backfill.step()
        done = list(self.fetched)
        self.run_all()
        self.assertEqual(len(self.fetched), 8)
        self.assertEqual(len(set(self.fetched)), 8)
        self.assertEqual(self.fetched[:3], done)

    def test_a_failed_fetch_records_nothing_and_is_tried_again(self):
        self.fail = True
        with self.assertRaises(DomainError):
            self.backfill.step()
        self.assertEqual(self.store.fetched(date(2026, 11, 20)), {})
        self.fail = False
        self.assertTrue(self.backfill.step())
        self.assertEqual(self.store.fetched(date(2026, 11, 20)), {'TWSE': 1})

    def test_it_never_looks_further_back_than_the_maximum_age(self):
        self.backfill.max_age_days, self.backfill.target_days = 5, 99
        self.run_all()
        self.assertEqual(min(url.rsplit('/', 1)[1] for url in self.fetched), '2026-11-16')

    def test_the_worker_thread_fills_the_store_and_stops_on_close(self):
        import time

        self.backfill.start()
        deadline = time.monotonic() + 5
        while self.backfill.next_pending() is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(self.backfill.next_pending())
        self.backfill.close()
        self.assertFalse(self.backfill._thread.is_alive())

    def test_the_worker_survives_a_failing_fetch_and_backs_off(self):
        import time

        self.fail = True
        self.backfill.start()
        time.sleep(0.2)
        self.assertTrue(self.backfill._thread.is_alive())  # waiting out its back-off, not dead
        self.backfill.close(timeout=0.1)


if __name__ == '__main__':
    unittest.main()
