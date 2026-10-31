"""Fake-only scheduling, coverage, quota, reconnect and history identity tests."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Event, get_ident
import tempfile
import unittest

from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.history_sync import HistorySettings, HistorySync
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage

NOW = datetime(2026, 10, 30, 6, tzinfo=timezone.utc)
STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', 'TSMC')
OTHER = WatchInstrument('TWSE:2317', WatchKind.STOCK, 'TSE', '2317', 'Hon Hai')
INDEX = WatchInstrument('INDEX:IX0001', WatchKind.INDEX, 'INDEX', 'IX0001', 'TAIEX')


def bar(instrument, start):
    price = Decimal('123.456789')
    return LiveBar(instrument.instrument_id, start, start + timedelta(minutes=1), start.date(), 'REGULAR', price, price, price, price, 1, final=True)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.quota = HistoryUsage(0, 500 * 1024 * 1024)
        self.error = None
        self.empty = True
        self.called = Event()
        self.thread_id = None

    def usage(self):
        if self.quota == 'error':
            raise RuntimeError('secret-key-must-not-leak')
        return self.quota

    def history(self, instrument, start, end):
        self.thread_id = get_ident()
        self.calls.append((instrument, start, end))
        self.called.set()
        if self.error:
            raise self.error
        return () if self.empty else (bar(instrument, start),)


class HistorySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KlineStore(Path(self.temp.name) / 'klines.sqlite3')
        self.session = FakeSession()
        self.now = NOW
        self.elapsed = 0.0
        self.waits = []
        self.sync = HistorySync(self.store, self.session, now=lambda: self.now, clock=lambda: self.elapsed, wait=self.wait, autostart=False)

    def tearDown(self):
        self.sync.close()
        self.store.close()
        self.temp.cleanup()

    def wait(self, seconds):
        self.waits.append(seconds)
        self.elapsed += seconds

    def drain(self):
        count = 0
        while self.sync.run_next():
            count += 1
            self.assertLess(count, 100)

    def test_29_day_chunk_boundaries_cross_month_and_empty_holiday_coverage(self):
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.sync.request(STOCK, start, start + timedelta(days=60))
        self.drain()
        self.assertEqual([(b - a).days for _, a, b in self.session.calls], [29, 29, 2])
        self.assertEqual(self.session.calls[0][2], self.session.calls[1][1])
        self.sync.request(STOCK, start, start + timedelta(days=60))
        self.drain()
        self.assertEqual(len(self.session.calls), 3)

    def test_empty_watchlist_fetches_indices_only_then_add_fetches_year(self):
        self.sync.connected((INDEX,), ())
        self.drain()
        self.assertTrue(all(item[0] == INDEX for item in self.session.calls))
        self.session.calls.clear()
        self.sync.watch_added(STOCK)
        self.drain()
        self.assertEqual(self.session.calls[0][1], NOW - timedelta(days=365))
        self.assertEqual(self.session.calls[-1][2], NOW)
        self.assertTrue(all(item[0] == STOCK for item in self.session.calls))

    def test_browse_gets_60_days_then_daily_extends_to_year_only_missing(self):
        self.sync.browse(STOCK)
        self.drain()
        self.assertEqual(self.session.calls[0][1], NOW - timedelta(days=60))
        self.session.calls.clear()
        self.sync.browse(STOCK, '1d')
        self.drain()
        self.assertEqual(self.session.calls[0][1], NOW - timedelta(days=365))
        self.assertEqual(self.session.calls[-1][2], NOW - timedelta(days=60))

    def test_priority_and_duplicate_queue_merging(self):
        self.sync.watch_added(OTHER)
        self.sync.watch_added(STOCK)
        self.sync.browse(STOCK, '1d')
        self.sync.connected((INDEX,), ())
        self.assertEqual(self.sync.state().pending, 3)
        self.drain()
        order = []
        for instrument, _, _ in self.session.calls:
            if instrument not in order:
                order.append(instrument)
        self.assertEqual(order, [STOCK, OTHER, INDEX])

    def test_quota_pause_retains_work_and_resume_continues(self):
        self.session.quota = HistoryUsage(96, 100)
        self.sync.browse(STOCK)
        self.sync.run_next()
        state = self.sync.state()
        self.assertTrue(state.paused)
        self.assertEqual(state.pending, 1)
        self.assertEqual(dict(state.history_error)[STOCK.instrument_id], 'history_quota_low')
        self.assertEqual(self.session.calls, [])
        self.session.quota = HistoryUsage(10, 100)
        self.sync.resume()
        self.drain()
        self.assertFalse(self.sync.state().paused)
        self.assertEqual(self.sync.state().history_error, ())
        self.assertEqual(len(self.session.calls), 3)

    def test_unknown_usage_proceeds_and_exposes_unknown(self):
        self.session.quota = 'error'
        self.sync.browse(STOCK)
        self.drain()
        self.assertFalse(self.sync.state().quota_known)
        self.assertEqual(len(self.session.calls), 3)

    def test_disconnect_recovery_only_fetches_uncovered_gap(self):
        self.sync.browse(STOCK)
        self.drain()
        self.session.calls.clear()
        self.sync.disconnected()
        self.now += timedelta(hours=2)
        self.sync.reconnected((STOCK,))
        self.drain()
        self.assertEqual(self.session.calls, [(STOCK, NOW, self.now)])

    def test_after_close_refresh_overrides_live_once_and_not_during_intraday(self):
        start = NOW.replace(hour=1)
        self.store.upsert((bar(STOCK, start),), source='LIVE_TICKS')
        self.store.mark_coverage(STOCK.instrument_id, start, NOW)
        self.sync.after_close((STOCK,))
        self.sync.after_close((STOCK,))
        self.drain()
        self.assertEqual(len(self.session.calls), 1)
        self.assertEqual(self.session.calls[0][1], start)
        self.now = NOW.replace(hour=3)
        self.sync.request(STOCK, start, self.now, force=True)
        self.drain()
        self.assertEqual(len(self.session.calls), 1)

    def test_per_day_persisted_bar_cap_pauses_and_resets_next_day(self):
        self.store.record_queried_bars(NOW.date(), 3_000_000)
        self.sync.browse(STOCK)
        self.sync.run_next()
        self.assertTrue(self.sync.state().paused)
        self.now += timedelta(days=1)
        self.sync.resume()
        self.drain()
        self.assertEqual(len(self.session.calls), 3)

    def test_next_trading_date_automatically_rearms_paused_history(self):
        self.store.record_queried_bars(NOW.date(), 3_000_000)
        self.sync.browse(STOCK)
        self.sync.run_next()
        self.assertTrue(self.sync.state().paused)
        self.now += timedelta(days=1)
        self.sync.resume_if_new_day()
        self.assertFalse(self.sync.state().paused)
        self.drain()
        self.assertEqual(len(self.session.calls), 3)

    def test_sdk_failure_retains_only_code_and_does_not_claim_coverage(self):
        self.session.error = RuntimeError('secret-key-must-not-leak')
        self.sync.browse(STOCK)
        self.drain()
        self.assertEqual(dict(self.sync.state().history_error)[STOCK.instrument_id], 'history_query_failed')
        self.assertNotIn('secret', repr(self.sync.state()))
        self.assertEqual(self.store.missing_ranges(STOCK.instrument_id, NOW - timedelta(days=60), NOW), ((NOW - timedelta(days=60), NOW),))

    def test_rate_limiter_never_starts_more_than_40_queries_per_10_seconds(self):
        self.sync.settings = HistorySettings(chunk_days=1)
        self.sync.request(STOCK, NOW - timedelta(days=45), NOW)
        self.drain()
        self.assertEqual(len(self.session.calls), 45)
        self.assertEqual(self.waits, [10.0])

    def test_successful_sparse_bars_persist_without_synthesizing_minutes(self):
        self.session.empty = False
        self.sync.request(STOCK, NOW - timedelta(minutes=10), NOW)
        self.drain()
        self.assertEqual(len(self.store.read(STOCK.instrument_id, NOW - timedelta(minutes=10), NOW)), 1)
        self.assertEqual(self.store.queried_bars(NOW.date()), 1)
        self.assertEqual(self.store.missing_ranges(STOCK.instrument_id, NOW - timedelta(minutes=10), NOW), ())

    def test_removed_watch_is_not_updated_and_existing_data_retained(self):
        self.store.upsert((bar(STOCK, NOW - timedelta(minutes=1)),))
        self.sync.watch_added(STOCK)
        self.sync.watch_removed(STOCK.instrument_id)
        self.drain()
        self.assertEqual(self.session.calls, [])
        self.assertIsNotNone(self.store.last_bar(STOCK.instrument_id))

    def test_remove_watch_during_inflight_query_cancels_remaining_chunks_and_publication(self):
        self.session.empty = False
        original = self.session.history

        def history(instrument, start, end):
            result = original(instrument, start, end)
            self.sync.watch_removed(instrument.instrument_id)
            return result

        self.session.history = history
        self.sync.watch_added(STOCK)
        self.drain()
        self.assertEqual(len(self.session.calls), 1)
        self.assertIsNone(self.store.last_bar(STOCK.instrument_id))
        self.assertEqual(self.store.queried_bars(NOW.date()), 1)
        self.assertEqual(self.store.missing_ranges(STOCK.instrument_id, NOW - timedelta(days=365), NOW), ((NOW - timedelta(days=365), NOW),))

    def test_default_background_worker_issues_io_off_ui_thread(self):
        self.sync.close()
        self.sync = HistorySync(self.store, self.session, now=lambda: NOW)
        self.sync.request(STOCK, NOW - timedelta(minutes=1), NOW)
        self.assertTrue(self.session.called.wait(2))
        self.sync.close()
        self.assertNotEqual(self.session.thread_id, get_ident())

    def test_invalid_settings_rejected(self):
        for values in (
            {'chunk_days': 30},
            {'minute_lookback_days': 366},
            {'quota_reserve_ratio': Decimal('1')},
            {'daily_bar_limit': 0},
            {'earliest': date(2019, 1, 1)},
        ):
            with self.subTest(values=values), self.assertRaises(DomainError):
                HistorySettings(**values)


if __name__ == '__main__':
    unittest.main()
