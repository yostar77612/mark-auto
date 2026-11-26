"""Offline integration of independent subscriptions, durable history and chart pages."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from desktop_app.features.trading import series_reader
from desktop_app.features.trading.series_reader import SERIES_TAIL_BARS, read_latest, read_series
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.contracts import MarketSeriesPage, MarketSeriesQuery
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_terminal_service import DAY_CHART_LOOKBACK_DAYS, MarketTerminalService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import DataGap, LiveBar, MinuteState, aggregate_bars
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage
from tests import series_read_simulator as simulator

NOW = datetime(2026, 10, 30, 2, tzinfo=timezone.utc)
TAIPEI = ZoneInfo('Asia/Taipei')
STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', 'TSMC')
OTHER = WatchInstrument('TPEX:6104', WatchKind.STOCK, 'OTC', '6104', 'Other')


def bar(start=NOW, value='10', **values):
    price = Decimal(value)
    return replace(LiveBar(STOCK.instrument_id, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price, price, price, 2, final=True), **values)


class Session:
    def __init__(self):
        self.connected = False
        self.subscribed, self.unsubscribed, self.pending, self.queries = [], [], [], []
        self.bidask_subscribed, self.bidask_unsubscribed, self.latest_bidask = [], [], None

    def subscribe(self, item):
        self.subscribed.append(item.instrument_id)

    def unsubscribe(self, key):
        self.unsubscribed.append(key)

    def drain_ticks(self, limit):
        ticks, self.pending = tuple(self.pending[:limit]), self.pending[limit:]
        return ticks

    def drain_tick_losses(self):
        return ()

    def usage(self):
        return HistoryUsage(0, 100)

    def quote_details(self, instrument_id):
        return {}

    def subscribe_bidask(self, item):
        self.bidask_subscribed.append(item.instrument_id)

    def unsubscribe_bidask(self, key):
        self.bidask_unsubscribed.append(key)

    def bidask(self, instrument_id):
        return self.latest_bidask

    def history(self, item, start, end):
        self.queries.append((item.instrument_id, start, end))
        return ()


class TerminalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KlineStore(Path(self.temp.name) / 'klines.sqlite3')
        self.session = Session()
        self.now = NOW
        self.history = HistorySync(self.store, self.session, now=lambda: self.now, autostart=False)
        self.saved = []
        self.service = MarketTerminalService(
            self.store, self.history, self.session, lambda: (*FIXED_INDICES, STOCK, OTHER), now=lambda: self.now, save_watchlist=self.saved.append
        )

    def tearDown(self):
        self.history.close()
        self.store.close()
        self.temp.cleanup()

    def connect(self):
        self.session.connected = True
        self.service.connected()

    def test_empty_watchlist_only_indices_and_browse_is_temporary(self):
        self.connect()
        self.assertEqual(self.session.subscribed, [item.instrument_id for item in FIXED_INDICES])
        self.assertEqual(self.service.watchlist, ())
        self.assertTrue(self.service.select(STOCK.instrument_id))
        self.assertEqual(self.service.watchlist, ())
        self.assertTrue(self.service.select(OTHER.instrument_id))
        self.assertEqual(self.session.unsubscribed, [STOCK.instrument_id])
        self.assertEqual(self.service.temporary_id, OTHER.instrument_id)

    def test_unsubscribable_main_and_watched_instruments_do_not_fail_the_connection(self):
        def refuse(item):
            if item.instrument_id in (STOCK.instrument_id, OTHER.instrument_id):
                raise DomainError('market_data_not_connected')
            self.session.subscribed.append(item.instrument_id)

        self.session.subscribe = refuse
        self.service.selected = STOCK.instrument_id
        self.service.set_watchlist((OTHER.instrument_id,))
        self.session.connected = True
        self.service.connected()
        self.assertEqual(self.session.subscribed, [item.instrument_id for item in FIXED_INDICES])
        self.assertEqual(self.service.temporary_id, '')
        self.assertEqual(self.service.watchlist, (OTHER.instrument_id,))

    def test_refused_subscriptions_keep_the_connection_and_log_only_the_code(self):
        def refuse(item):
            if item.instrument_id in (STOCK.instrument_id, OTHER.instrument_id):
                raise DomainError('market_data_not_connected', 'C:/Users/private account 0001234')
            self.session.subscribed.append(item.instrument_id)

        self.session.subscribe = refuse
        self.service.selected = STOCK.instrument_id
        self.service.set_watchlist((OTHER.instrument_id,))
        self.session.connected = True
        with self.assertLogs('quantlab.trading.application.market_terminal_service', 'WARNING') as logs:
            self.service.connected()
        self.assertEqual(self.session.subscribed, [item.instrument_id for item in FIXED_INDICES])
        self.assertEqual(self.service.temporary_id, '')
        self.assertEqual(self.service.watchlist, (OTHER.instrument_id,))
        self.assertEqual(
            logs.output,
            ['WARNING:quantlab.trading.application.market_terminal_service:market subscription refused (market_data_not_connected)'] * 2,
        )

    def test_watch_promotion_and_demotion_do_not_duplicate_subscriptions(self):
        self.connect()
        self.service.select(STOCK.instrument_id)
        self.service.set_watchlist((STOCK.instrument_id,))
        self.assertEqual(self.service.temporary_id, '')
        self.assertEqual(self.session.subscribed.count(STOCK.instrument_id), 1)
        self.service.set_watchlist(())
        self.assertEqual(self.service.temporary_id, STOCK.instrument_id)
        self.assertEqual(self.session.unsubscribed, [])
        self.service.select(FIXED_INDICES[0].instrument_id)
        self.assertEqual(self.session.unsubscribed, [STOCK.instrument_id])
        self.assertEqual(self.saved, [(STOCK.instrument_id,), ()])

    def test_full_quota_keeps_history_access_and_rejected_watch_unchanged(self):
        self.service.settings = LiveMarketSettings(subscription_limit=3)
        self.connect()
        self.service.set_watchlist((STOCK.instrument_id,))
        self.assertFalse(self.service.select(OTHER.instrument_id))
        self.assertEqual(self.service.selected, OTHER.instrument_id)
        with self.assertRaises(DomainError) as caught:
            self.service.set_watchlist((STOCK.instrument_id, OTHER.instrument_id))
        self.assertEqual(caught.exception.code, 'subscription_limit_reached')
        self.assertEqual(self.service.watchlist, (STOCK.instrument_id,))
        self.assertEqual(self.service.series(MarketSeriesQuery(OTHER.instrument_id)).bars, ())

    def test_offline_directory_only_cached_instruments_and_fixed_indices(self):
        self.assertEqual(self.service.instruments(), FIXED_INDICES)
        self.store.upsert((bar(),))
        self.assertEqual(self.service.instruments(), (*FIXED_INDICES, STOCK))

    def test_corrupt_or_missing_directory_still_resolves_cached_stock_identity(self):
        self.store.upsert((bar(),))
        self.service.directory = lambda: FIXED_INDICES
        cached = self.service.resolve(STOCK.instrument_id)
        self.assertEqual((cached.instrument_id, cached.code, cached.name), (STOCK.instrument_id, '2330', '2330'))
        self.assertIn(cached, self.service.instruments())
        self.assertFalse(self.service.select(STOCK.instrument_id))
        self.assertEqual(len(self.service.series(MarketSeriesQuery(STOCK.instrument_id)).bars), 0)

    def test_tick_rollover_persists_only_completed_minutes_official_remains_authoritative(self):
        self.connect()
        self.service.select(STOCK.instrument_id)
        self.session.pending = [Tick(STOCK.instrument_id, Decimal('11'), 2, NOW, NOW, NOW.date())]
        self.service.poll()
        self.assertIsNone(self.store.last_bar(STOCK.instrument_id))
        forming = self.service.series(MarketSeriesQuery(STOCK.instrument_id)).bars
        self.assertFalse(forming[-1].final)
        self.now += timedelta(minutes=1)
        self.service.poll()
        self.assertTrue(self.store.last_bar(STOCK.instrument_id).final)
        self.store.upsert((bar(value='15'),))
        self.assertEqual(self.service.series(MarketSeriesQuery(STOCK.instrument_id)).bars[0].close, Decimal('15'))

    def test_all_seven_api_periods_remain_and_daily_final_is_per_trade_date(self):
        self.store.upsert(tuple(bar(NOW - timedelta(days=1) + timedelta(minutes=i), str(10 + i)) for i in range(15)))
        self.store.upsert((bar(NOW - timedelta(minutes=1), '30'),))
        for period in ('1m', '3m', '5m', '15m', '30m', '60m', '1d'):
            with self.subTest(period=period):
                page = self.service.series(MarketSeriesQuery(STOCK.instrument_id, period))
                self.assertTrue(page.bars)
        daily = self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars
        self.assertTrue(daily[0].final)
        self.assertFalse(daily[-1].final)
        self.assertEqual(daily[0].volume, 30)
        self.assertEqual(daily[0].open, Decimal('10'))
        self.assertEqual(daily[0].close, Decimal('24'))

    def oracle_days(self, start, end, instrument_id=STOCK.instrument_id):
        """The trade dates of the stored minutes aggregated one by one from a plain read, finality as the engine decides it."""
        groups = {}
        for item in self.store.read(instrument_id, start, end):
            groups.setdefault(item.trade_date, []).append(item)
        local = self.now.astimezone(TAIPEI)
        return tuple(
            aggregate_bars(
                tuple(members),
                '1d',
                now=self.now,
                trade_date_closed=day < local.date() or day == local.date() and local.hour * 60 + local.minute >= 13 * 60 + 30,
            )[0]
            for day, members in groups.items()
        )

    def oracle_weeks(self, days):
        """ISO weeks of the oracle days; a week is closed after it, or on its own Saturday and Sunday."""
        local = self.now.astimezone(TAIPEI).date()
        groups = {}
        for item in days:
            groups.setdefault(item.trade_date.isocalendar()[:2], []).append(item)
        closed = lambda key: key < local.isocalendar()[:2] or key == local.isocalendar()[:2] and local.isoweekday() >= 6
        return tuple(aggregate_bars(tuple(members), '1w', now=self.now, trade_date_closed=closed(key))[0] for key, members in groups.items())

    def test_daily_and_weekly_caches_past_their_cap_follow_interleaved_writes_and_clock_moves(self):
        import random

        rng = random.Random(20261126)
        keys = [STOCK.instrument_id, OTHER.instrument_id, 'TWSE:1101', 'TWSE:1102', 'TWSE:1103', 'TWSE:1104']  # past the four kept
        self.store.upsert(tuple(replace(bar(NOW - timedelta(days=1)), instrument_id=key) for key in keys))
        for number in range(400):
            action, key = rng.random(), rng.choice(keys)
            if action < 0.45:
                start = NOW - timedelta(days=rng.randrange(0, 900), minutes=rng.randrange(0, 300))
                self.store.upsert((replace(bar(start, str(rng.randrange(5, 50))), instrument_id=key, volume=rng.randrange(1, 9)),))
            elif action < 0.55:
                self.now += timedelta(hours=rng.randrange(1, 30))
            else:
                start = self.now - timedelta(days=DAY_CHART_LOOKBACK_DAYS)
                daily = self.service.series(MarketSeriesQuery(key, '1d')).bars
                with self.subTest(round=number, key=key):
                    self.assertEqual(daily, self.oracle_days(start, self.now, key))
                    self.assertEqual(self.service.series(MarketSeriesQuery(key, '1w')).bars, self.oracle_weeks(daily))

    def test_daily_and_weekly_charts_show_every_stored_trade_date_past_the_minute_lookback(self):
        three_years = NOW - timedelta(days=3 * 365)
        self.store.upsert((bar(three_years, '50'), bar(three_years + timedelta(minutes=1), '52'), bar(NOW - timedelta(days=1), '60')))
        self.assertEqual(len(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1m')).bars), 1)  # the minute chart keeps its year
        daily = self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars
        self.assertEqual(
            [(item.trade_date, item.open, item.close, item.volume) for item in daily],
            [(three_years.date(), Decimal('50'), Decimal('52'), 4), ((NOW - timedelta(days=1)).date(), Decimal('60'), Decimal('60'), 2)],
        )
        weekly = self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1w')).bars
        self.assertEqual([item.trade_date for item in weekly], [item.trade_date for item in daily])  # two different weeks
        self.assertEqual([item.final for item in weekly], [True, False])  # NOW is a Friday morning: this week still trades

    def test_daily_bars_equal_a_plain_aggregation_after_every_store_change(self):
        self.store.upsert(
            tuple(bar(NOW - timedelta(days=day, minutes=minute), str(10 + (day * 7 + minute) % 9)) for day in range(1, 6) for minute in range(1, 40, 3))
        )
        start = NOW - timedelta(days=DAY_CHART_LOOKBACK_DAYS)
        steps = (
            lambda: None,
            lambda: self.store.upsert((bar(NOW - timedelta(days=40), '7'),)),  # older history arrives
            lambda: self.store.upsert((bar(NOW - timedelta(days=3, minutes=1), '99'),)),  # an old minute is rewritten in place
            lambda: setattr(self, 'now', self.now + timedelta(hours=6)),  # only the clock moves: today closes
        )
        for number, step in enumerate(steps):
            step()
            with self.subTest(step=number):
                self.assertEqual(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars, self.oracle_days(start, self.now))

    def test_a_minute_stored_after_the_previous_read_end_is_shown_once_the_clock_reaches_it(self):
        self.store.upsert((bar(NOW - timedelta(days=1)), bar(NOW + timedelta(minutes=5), '30')))
        self.assertEqual(len(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars), 1)
        self.now = NOW + timedelta(minutes=10)
        daily = self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars
        self.assertEqual([item.close for item in daily], [Decimal('10'), Decimal('30')])

    def test_the_forming_minute_joins_todays_daily_and_weekly_bar(self):
        # The usual live case: the last stored minute ends exactly where the forming minute starts.
        self.store.upsert((bar(NOW - timedelta(days=1), '10'), bar(NOW - timedelta(minutes=1), '12')))
        self.connect()
        self.service.select(STOCK.instrument_id)
        self.session.pending = [Tick(STOCK.instrument_id, Decimal('15'), 3, NOW, NOW, NOW.date())]
        self.service.poll()
        for period in ('1d', '1w'):
            with self.subTest(period=period):
                latest = self.service.series(MarketSeriesQuery(STOCK.instrument_id, period)).bars[-1]
                self.assertEqual((latest.close, latest.high, latest.final), (Decimal('15'), Decimal('15'), False))
        self.assertEqual(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars[-1].volume, 5)

    def test_a_forming_minute_without_any_stored_minute_makes_todays_bar(self):
        self.connect()
        self.service.select(STOCK.instrument_id)
        self.session.pending = [Tick(STOCK.instrument_id, Decimal('15'), 3, NOW, NOW, NOW.date())]
        self.service.poll()
        for period in ('1d', '1w'):
            with self.subTest(period=period):
                (latest,) = self.service.series(MarketSeriesQuery(STOCK.instrument_id, period)).bars
                self.assertEqual((latest.close, latest.trade_date, latest.volume, latest.final), (Decimal('15'), NOW.date(), 3, False))

    def test_a_stale_forming_minute_counts_in_its_day_as_aggregating_the_minutes_would(self):
        stored = (bar(NOW - timedelta(minutes=3), '10'), bar(NOW - timedelta(minutes=1), '11'))
        self.store.upsert(stored)
        for start, close in ((NOW - timedelta(minutes=2), '9'), (NOW - timedelta(minutes=5), '8'), (NOW - timedelta(minutes=1), '50'), (NOW, '13')):
            price = Decimal(close)
            minute = LiveBar(STOCK.instrument_id, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price, price, price, 1, incomplete=True)
            self.service._minutes[STOCK.instrument_id] = MinuteState(minute, (start, -1), (start, -1), ('TEST', start.date(), 'DAY'))
            # The previous code merged the forming minute into the stored minutes unless its start was already stored.
            minutes = stored if start in {item.start for item in stored} else (*stored, minute)
            expected = aggregate_bars(minutes, '1d', now=self.now, trade_date_closed=False)
            with self.subTest(start=start):
                self.assertEqual(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars, expected)

    def test_a_stock_day_is_final_from_1330_in_taipei(self):
        self.store.upsert((bar(NOW - timedelta(hours=1)),))  # 09:00 in Taipei
        for now, final in ((datetime(2026, 10, 30, 5, 29, tzinfo=timezone.utc), False), (datetime(2026, 10, 30, 5, 30, tzinfo=timezone.utc), True)):
            self.now = now
            with self.subTest(now=now):
                self.assertEqual(self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1d')).bars[0].final, final)

    def test_browsing_the_weekly_chart_requests_the_annual_history(self):
        calls = []
        self.history._lookback = lambda instrument, days, priority: calls.append(days)
        self.history.browse(STOCK, '1w')
        self.history.browse(STOCK, '1m')
        self.assertEqual(calls, [self.history.settings.daily_lookback_days, self.history.settings.minute_lookback_days])

    def test_a_week_closes_once_the_next_begins_or_on_its_weekend(self):
        friday = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)  # 09:00 in Taipei on a Friday
        self.store.upsert(tuple(bar(friday - timedelta(days=days)) for days in (7, 4, 3, 2, 1)))  # last Friday, then Monday to Thursday
        for now, current_final in (
            (friday, False),  # Friday morning: today's session is open
            (friday + timedelta(hours=6), False),  # Friday 15:00: the week may still trade on its Saturday
            (friday + timedelta(days=1), True),  # Saturday: every day of the week has closed
            (friday + timedelta(days=3), True),  # Monday: the next week has begun
        ):
            self.now = now
            with self.subTest(now=now):
                weekly = self.service.series(MarketSeriesQuery(STOCK.instrument_id, '1w')).bars
                self.assertEqual([item.trade_date for item in weekly], [date(2026, 10, 23), date(2026, 10, 26)])
                self.assertEqual([item.final for item in weekly], [True, current_final])
                self.assertEqual(weekly[-1].volume, 8)

    def test_page_revision_survives_history_growth_and_unknown_quotes_stay_none(self):
        self.store.upsert(tuple(bar(NOW - timedelta(minutes=i)) for i in range(1, 5)))
        page = self.service.series(MarketSeriesQuery(STOCK.instrument_id, limit=2))
        self.store.upsert((bar(NOW - timedelta(minutes=5)),))
        tail = self.service.series(MarketSeriesQuery(STOCK.instrument_id, offset=2, limit=2, market_revision=page.market_revision))
        self.assertEqual(tail.total, 4)
        self.assertEqual(len(tail.bars), 2)
        self.assertTrue(all(view.price is None for view in self.service.views()))

    def test_watch_removed_does_not_delete_cached_bars(self):
        self.store.upsert((bar(),))
        self.service.set_watchlist((STOCK.instrument_id,))
        self.service.set_watchlist(())
        self.assertEqual(self.store.last_bar(STOCK.instrument_id), bar())

    def test_fast_reconnect_keeps_previous_quote_stopped_and_interrupted_bar_incomplete(self):
        self.connect()
        self.service.select(STOCK.instrument_id)
        self.session.pending = [Tick(STOCK.instrument_id, Decimal('11'), 2, NOW, NOW, NOW.date())]
        self.service.poll()
        self.assertEqual(self.service.views()[-1].health.freshness, 'LIVE')
        self.service.disconnected()
        self.service.connected()
        self.assertEqual(self.service.views()[-1].price, Decimal('11'))
        self.assertEqual(self.service.views()[-1].health.freshness, 'STOPPED')
        self.assertTrue(self.service.views()[-1].health.incomplete)
        self.now += timedelta(seconds=2)
        self.session.pending = [Tick(STOCK.instrument_id, Decimal('12'), 2, self.now, self.now, NOW.date())]
        self.service.poll()
        self.assertEqual(self.service.views()[-1].health.freshness, 'LIVE')
        self.now += timedelta(minutes=1)
        self.service.poll()
        self.assertIsNone(self.store.last_bar(STOCK.instrument_id))


class TerminalEngineReaderTests(unittest.TestCase):
    """OPT-1 P11: the shared tail reader against this engine, round by round (the engine every chart read reaches while the market connection is on)."""

    KEY = simulator.STOCK.instrument_id

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.feed = simulator.TerminalFeed(self.temp.name)
        self.addCleanup(self.feed.close)
        self.facade = self.feed.facade

    def assertSameSeries(self, result, period, key=None):
        page, bars, whole = result
        oracle = self.feed.whole(key or self.KEY, period)
        self.assertEqual(repr(bars), repr(oracle.bars))  # repr keeps Decimal exponents and every flag
        self.assertEqual((page.instrument_id, page.period, page.total, page.gaps), (oracle.instrument_id, oracle.period, oracle.total, oracle.gaps))

    def play(self, rounds=90):
        """The mismatching rounds and the rounds that read the whole series, over a script of every kind of change."""
        cache, mismatches, wholes = {}, [], []
        for number in range(rounds):
            period = '1m' if number < 50 else '5m' if number < 65 else '1d' if number < 75 else '1m'
            self.feed.tick()
            if number % 17 == 5:
                self.feed.backfill_older()
            if number % 11 == 3:
                self.feed.tick(lost=True)
            if number == 30:
                self.feed.tick(6 * 3600)  # the day session closes and the night session opens under the next trade date
            if number == 40:
                for _ in range(4):
                    self.feed.tick(lost=True)
            if number == 45:
                self.feed.tick(14 * 3600)  # the next morning: the day session of that trade date
            del self.facade.queries[:]
            result = read_series(self.facade, self.KEY, period, cache.get(period), pinned_tail=True)
            oracle = self.feed.whole(self.KEY, period)
            if repr(result[1]) != repr(oracle.bars) or result[0].total != oracle.total:
                mismatches.append(number)
            cache[period] = result[:2]
            if result[2]:
                wholes.append(number)
        return mismatches, wholes

    def test_the_engine_serves_a_page_past_the_first_only_from_a_named_snapshot(self):
        total = self.feed.whole(self.KEY, '1m').total
        with self.assertRaises(DomainError) as caught:
            self.facade.market_series(MarketSeriesQuery(self.KEY, '1m', offset=total - SERIES_TAIL_BARS))
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_cached_reads_equal_whole_reads_through_every_kind_of_change(self):
        mismatches, wholes = self.play()
        self.assertEqual(mismatches, [])
        # The first read of each period and every backfill that shifted the indexes of a long series read the whole series.
        self.assertLessEqual({0, 50, 65, 5, 22, 39, 56}, set(wholes))
        self.assertGreater(90 - len(wholes), 55)  # every other round only re-read the tail

    def test_removing_the_window_comparison_is_caught(self):
        with patch.object(series_reader, '_read_tail', simulator.without_window_check):
            mismatches, _ = self.play()
        self.assertTrue(mismatches)

    def test_a_steady_read_is_one_bar_then_the_tail_of_that_snapshot(self):
        first = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)
        self.assertTrue(first[2])
        self.feed.tick()
        del self.facade.queries[:]
        result = read_series(self.facade, self.KEY, '1m', first[:2], pinned_tail=True)
        self.assertFalse(result[2])
        head, tail = self.facade.queries
        self.assertEqual((head.offset, head.limit, head.market_revision), (0, 1, None))
        self.assertEqual((tail.offset, tail.limit), (len(first[1]) - SERIES_TAIL_BARS, MarketSeriesQuery(self.KEY).limit))
        self.assertIsNotNone(tail.market_revision)
        self.assertSameSeries(result, '1m')

    def test_the_retry_read_is_always_whole_and_its_first_page_asks_for_the_history_again(self):
        first = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)
        del self.facade.queries[:]
        result = read_series(self.facade, self.KEY, '1m', first[:2], retry_history=True, pinned_tail=True)
        self.assertTrue(result[2])
        self.assertTrue(self.facade.queries[0].retry_history)
        self.assertEqual(self.facade.queries[0].offset, 0)
        self.assertTrue(all(query.offset == 0 or query.market_revision is not None for query in self.facade.queries))
        self.assertFalse(any(query.retry_history for query in self.facade.queries[1:]))
        self.assertSameSeries(result, '1m')

    def test_a_snapshot_replaced_between_the_two_reads_falls_back_to_the_whole_series(self):
        first = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)
        feed, key = self.feed, self.KEY

        class Racing:
            """Another reader takes a newer snapshot of the same series right after this one's first-page read."""

            def __init__(self):
                self.queries = []

            def market_series(self, query):
                self.queries.append(query)
                page = feed.service.series(query)
                if query.limit == 1:
                    feed.tick()
                    feed.service.series(MarketSeriesQuery(key, '1m', limit=1))
                return page

        racing = Racing()
        feed.tick()
        result = read_series(racing, self.KEY, '1m', first[:2], pinned_tail=True)
        self.assertTrue(result[2])
        self.assertEqual([(query.offset > 0, query.limit == 1) for query in racing.queries[:2]], [(False, True), (True, False)])  # head, refused tail
        self.assertSameSeries(result, '1m')

    def test_other_errors_and_an_unpinned_refusal_are_not_swallowed(self):
        first = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)

        class Refusing:
            def __init__(self, code):
                self.code = code

            def market_series(self, query):
                raise DomainError(self.code)

        with self.assertRaises(DomainError) as caught:
            read_series(Refusing('capability_missing'), self.KEY, '1m', first[:2], pinned_tail=True)
        self.assertEqual(caught.exception.code, 'capability_missing')
        with self.assertRaises(DomainError) as caught:
            read_series(Refusing('state_conflict'), self.KEY, '1m', first[:2])  # the sector board's own unpinned read
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_a_short_series_is_read_from_its_first_page_without_pinning(self):
        other = simulator.OTHER.instrument_id
        first = read_series(self.facade, other, '1d', None, pinned_tail=True)
        self.assertLess(len(first[1]), SERIES_TAIL_BARS)
        self.feed.tick(6 * 3600)
        del self.facade.queries[:]
        result = read_series(self.facade, other, '1d', first[:2], pinned_tail=True)
        self.assertFalse(result[2])
        self.assertEqual([(query.offset, query.market_revision) for query in self.facade.queries], [(0, None)])
        self.assertSameSeries(result, '1d', other)

    def test_a_rewrite_of_older_bars_is_shown_after_the_next_whole_read(self):
        cached = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)[:2]
        self.feed.tick()
        self.feed.rewrite_old()  # same size, same tail, different closes for bars older than the tail window
        page, bars, whole = read_series(self.facade, self.KEY, '1m', cached, pinned_tail=True)
        full = self.feed.whole(self.KEY, '1m').bars
        self.assertFalse(whole)
        self.assertNotEqual(repr(bars[:-SERIES_TAIL_BARS]), repr(full[:-SERIES_TAIL_BARS]))  # the documented bound
        self.assertEqual(repr(bars[-SERIES_TAIL_BARS:]), repr(full[-SERIES_TAIL_BARS:]))
        self.assertSameSeries(read_series(self.facade, self.KEY, '1m', None, pinned_tail=True), '1m')  # the resync read

    def test_whole_round_tells_whole_reads_from_tail_reads(self):
        first = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)
        self.assertTrue(simulator.whole_round(self.facade.queries, self.KEY))
        self.assertFalse(simulator.whole_round(self.facade.queries, simulator.OTHER.instrument_id))
        self.feed.tick()
        del self.facade.queries[:]
        read_series(self.facade, self.KEY, '1m', first[:2], pinned_tail=True)
        self.assertFalse(simulator.whole_round(self.facade.queries, self.KEY))


class ScriptedEngine:
    """A series held in memory and served in pages the way the two chart engines do.

    `snapshots` is the market terminal engine: a first-page read takes a snapshot and a page past the first is served only from
    it and only when the read names its revision. Without it (the live engine) every page is read from the current series and
    a read naming a revision other than the current one is refused.
    """

    PAGE_LIMIT = 300

    def __init__(self, bars, gaps=(), *, snapshots):
        self.bars, self.gaps, self.snapshots, self.revision, self.snapshot, self.queries = tuple(bars), tuple(gaps), snapshots, 1, None, []

    def put(self, bars, gaps=()):
        self.bars, self.gaps, self.revision = tuple(bars), tuple(gaps), self.revision + 1

    def market_series(self, query):
        self.queries.append(query)
        if query.offset == 0 and query.market_revision is None:
            self.snapshot = self.revision, self.bars, self.gaps
        if self.snapshots and query.offset:
            if self.snapshot is None or query.market_revision != self.snapshot[0]:
                raise DomainError('state_conflict', 'chart page revision changed')
            revision, bars, gaps = self.snapshot
        else:
            if query.market_revision is not None and query.market_revision != self.revision:
                raise DomainError('state_conflict', 'market changed; restart series read')
            revision, bars, gaps = self.revision, self.bars, self.gaps
        stop = query.offset + min(query.limit, self.PAGE_LIMIT)
        return MarketSeriesPage(
            query.instrument_id, query.period, bars[query.offset : stop], gaps, query.offset, len(bars), stop if stop < len(bars) else None, revision
        )


def scripted_bar(index, close=100):
    start = NOW + timedelta(minutes=index)
    return LiveBar(
        STOCK.instrument_id,
        start,
        start + timedelta(minutes=1),
        start.date(),
        'DAY',
        Decimal(close),
        Decimal(close + 3),
        Decimal(close - 1),
        Decimal(close),
        1,
        True,
    )


class ReaderFallbackTests(unittest.TestCase):
    """OPT-1 P11: each condition under which the tail does not line up must send the reader back to the whole series, on its own."""

    KEY = STOCK.instrument_id
    MODES = (('live engine', False), ('terminal engine', True))  # (label, snapshots): the reader's pinned_tail follows the engine

    def read(self, engine, cached, snapshots):
        page, bars, whole = read_series(engine, self.KEY, '1m', cached, pinned_tail=snapshots)
        self.assertEqual(repr(bars), repr(engine.bars))  # whatever path it took, the answer is the series the engine holds now
        return page, bars, whole

    def test_a_shift_inside_the_window_with_the_same_total_and_the_same_last_bar_reads_the_whole_series(self):
        for label, snapshots in self.MODES:
            with self.subTest(label):
                bars = [scripted_bar(index) for index in range(1, 701)]
                engine = ScriptedEngine(bars, snapshots=snapshots)
                cached = self.read(engine, None, snapshots)[:2]
                # One bar older than everything held arrives and one bar inside the re-read window is gone: the total and
                # the newest bar are what they were, only the content of the window moved.
                engine.put([scripted_bar(0, 177), *bars[:600], *bars[601:]])
                self.assertEqual((len(engine.bars), engine.bars[-1]), (len(bars), bars[-1]))
                self.assertTrue(self.read(engine, cached, snapshots)[2])

    def test_a_changed_gap_list_reads_the_whole_series(self):
        bars = [scripted_bar(index) for index in range(1, 701)]
        gap = DataGap(bars[5].start, bars[9].end)
        engine = ScriptedEngine(bars, (gap,), snapshots=False)  # the terminal engine reports no gaps
        cached = self.read(engine, None, False)[:2]
        recovered = list(bars)
        for index in range(5, 9):  # the gap is filled: old bars, far outside the window, now carry real prices
            recovered[index] = scripted_bar(index + 1, 150)
        engine.put(recovered, ())
        self.assertTrue(self.read(engine, cached, False)[2])

    def test_more_than_one_page_of_new_bars_reads_the_whole_series(self):
        for label, snapshots in self.MODES:
            with self.subTest(label):
                bars = [scripted_bar(index) for index in range(1, 701)]
                engine = ScriptedEngine(bars, snapshots=snapshots)
                cached = self.read(engine, None, snapshots)[:2]
                engine.put([*bars, *(scripted_bar(index) for index in range(701, 1101))])  # 400 new bars, more than a 300-bar page
                self.assertTrue(self.read(engine, cached, snapshots)[2])

    def test_a_series_that_lines_up_is_read_as_a_tail_in_one_or_two_calls(self):
        for label, snapshots in self.MODES:
            with self.subTest(label):
                bars = [scripted_bar(index) for index in range(1, 701)]
                engine = ScriptedEngine(bars, snapshots=snapshots)
                cached = self.read(engine, None, snapshots)[:2]
                engine.put([*bars[:-1], scripted_bar(700, 120), scripted_bar(701)])  # the forming bar changed and a new one began
                del engine.queries[:]
                self.assertFalse(self.read(engine, cached, snapshots)[2])
                self.assertEqual(len(engine.queries), 2 if snapshots else 1)


def day_bar(index, day, close=100):
    """A scripted bar: `index` minutes after NOW, in trade day number `day`."""
    bar = scripted_bar(index, close)
    return replace(bar, trade_date=NOW.date() + timedelta(days=day))


class ReadLatestTests(unittest.TestCase):
    """OPT-1 P11b: the page a chart that draws only the newest trade date reads, against the real engine and a scripted one."""

    KEY = simulator.INDEX_ID

    def old_last_page(self, engine):
        """The read the terminal made before: the first page, then the last page of the snapshot it took."""
        page = engine.market_series(MarketSeriesQuery(self.KEY, '1m'))
        if page.next_offset is not None:
            page = engine.market_series(MarketSeriesQuery(self.KEY, '1m', offset=max(0, page.total - len(page.bars)), market_revision=page.market_revision))
        return page

    def newest_day(self, page):
        latest = page.bars[-1].trade_date if page.bars else None
        return tuple(bar for bar in page.bars if bar.trade_date == latest)

    def scripted(self, bars, *, snapshots=True):
        engine = ScriptedEngine(bars, snapshots=snapshots)
        engine.PAGE_LIMIT = 4000  # the real page limit
        return engine

    def test_the_newest_trade_date_is_the_same_as_in_the_last_page_of_the_whole_read(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            feed = simulator.TerminalFeed(folder, index_days=16)
            try:
                self.assertIsNotNone(feed.service.series(MarketSeriesQuery(self.KEY, '1m')).next_offset)  # the case that needed a second page
                events = ('tick', 'tick', 'tick', 'backfill', 'tick', 'new day', 'tick', 'tick', 'backfill', 'tick')
                for number, event in enumerate(events * 4):
                    if event == 'tick':
                        feed.tick_index()
                    elif event == 'backfill':
                        feed.backfill_index_older()
                    else:
                        feed.tick_index(new_day=True)  # a later trade date begins
                    del feed.facade.queries[:]
                    page = read_latest(feed.facade, self.KEY, '1m')
                    with self.subTest(round=number, event=event):
                        self.assertEqual(repr(self.newest_day(page)), repr(self.newest_day(self.old_last_page(feed.facade))))
                        self.assertLessEqual(len(page.bars), 400)
                        head, tail = feed.facade.queries[:2]
                        self.assertEqual((head.offset, head.limit, head.market_revision), (0, 1, None))
                        self.assertEqual((tail.offset > 0, tail.market_revision is not None), (True, True))
            finally:
                feed.close()

    def test_a_series_no_longer_than_the_window_is_read_whole_from_its_first_page(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            feed = simulator.TerminalFeed(folder, index_days=1)
            try:
                page = read_latest(feed.facade, self.KEY, '1m')
                self.assertEqual(len(page.bars), 270)
                self.assertEqual(
                    [(query.offset, query.limit == 1, query.market_revision) for query in feed.facade.queries], [(0, True, None), (0, False, None)]
                )
                self.assertEqual(repr(page.bars), repr(feed.whole(self.KEY, '1m').bars))
            finally:
                feed.close()

    def test_a_newest_trade_date_that_may_start_before_the_window_reads_the_last_page_of_the_whole_read(self):
        bars = [day_bar(index, 0) for index in range(1000)]  # one trade date of 1,000 bars: longer than the 400-bar window
        for label, snapshots in (('terminal engine', True), ('live engine', False)):
            with self.subTest(label):
                engine = self.scripted(bars, snapshots=snapshots)
                self.assertEqual(repr(read_latest(engine, self.KEY, '1m').bars), repr(self.old_last_page(engine).bars))
                self.assertEqual(len(read_latest(engine, self.KEY, '1m').bars), 1000)

    def test_a_window_that_starts_on_an_earlier_date_is_enough(self):
        bars = [day_bar(index, index // 270) for index in range(1000)]  # 270 bars a day: the newest day starts well inside the window
        engine = self.scripted(bars)
        del engine.queries[:]
        page = read_latest(engine, self.KEY, '1m')
        self.assertEqual((len(page.bars), len(engine.queries)), (400, 2))
        self.assertEqual(repr(self.newest_day(page)), repr(self.newest_day(self.old_last_page(engine))))

    def test_an_error_other_than_state_conflict_at_the_tail_is_raised_without_another_read(self):
        engine = self.scripted([day_bar(index, index // 270) for index in range(1000)])

        class TailFails:
            """The first-page read works; the tail read fails with an error that is not a lost snapshot."""

            def __init__(self):
                self.queries = []

            def market_series(self, query):
                self.queries.append(query)
                if query.offset:
                    raise DomainError('capability_missing')
                return engine.market_series(query)

        failing = TailFails()
        with self.assertRaises(DomainError) as caught:
            read_latest(failing, self.KEY, '1m')
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertEqual([(query.offset > 0, query.limit == 1) for query in failing.queries], [(False, True), (True, False)])  # no fallback read

    def test_a_window_that_runs_on_to_a_second_page_reads_the_last_page_of_the_whole_read(self):
        bars = [day_bar(index, index // 270) for index in range(1000)]
        engine = self.scripted(bars)
        engine.PAGE_LIMIT = 300  # an engine whose pages are smaller than the 400-bar window
        page = read_latest(engine, self.KEY, '1m')
        self.assertEqual(repr(page.bars), repr(self.old_last_page(engine).bars))
        self.assertEqual(page.bars[-1], bars[-1])  # still ends at the newest bar

    def test_a_refused_tail_falls_back_to_the_last_page_and_other_errors_are_not_swallowed(self):
        bars = [day_bar(index, index // 270) for index in range(1000)]
        engine = self.scripted(bars)

        class Racing:
            """Another reader takes a newer snapshot of the series right after this one's first-page read."""

            def __init__(self):
                self.queries = []

            def market_series(self, query):
                self.queries.append(query)
                page = engine.market_series(query)
                if query.limit == 1:
                    engine.put([*bars, day_bar(1000, 3)])
                    engine.market_series(MarketSeriesQuery(ReadLatestTests.KEY, '1m', limit=1))
                return page

        racing = Racing()
        page = read_latest(racing, self.KEY, '1m')
        self.assertEqual(repr(page.bars), repr(self.old_last_page(engine).bars))

        class Refusing:
            def market_series(self, query):
                raise DomainError('capability_missing')

        with self.assertRaises(DomainError) as caught:
            read_latest(Refusing(), self.KEY, '1m')
        self.assertEqual(caught.exception.code, 'capability_missing')


if __name__ == '__main__':
    unittest.main()
