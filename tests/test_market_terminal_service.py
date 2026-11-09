"""Offline integration of independent subscriptions, durable history and chart pages."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_terminal_service import MarketTerminalService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage

NOW = datetime(2026, 10, 30, 2, tzinfo=timezone.utc)
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


if __name__ == '__main__':
    unittest.main()
