"""End-to-end offline market connection and authenticated-protocol dispatch wiring."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.market_session import MarketSession
from quantlab.trading.adapters.shioaji.sdk import SDK_VERSION
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import MarketSeriesQuery, UiAction, UiCommand
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.market_terminal import SessionBridge
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _dispatch
from tests.test_market_session import FakeApi, FakeSecrets, STOCK
from tests.test_alert_service import fake_sdk
from quantlab.trading.application.alert_contracts import AlertCommand, AlertOperation, AlertRuleData
from quantlab.trading.domain.alerts import AlertRule, AlertKind
from decimal import Decimal


class MarketRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bundle = build_runtime(RuntimeLaunch(Path(self.temp.name)))
        self.api = FakeApi()
        self.api.set_on_scanner_callback = lambda callback: self.api.callbacks.update(scanner=callback)
        self.api.subscribe_scanner = lambda scanner, **kwargs: self.api.calls.append(('scanner_subscribe', scanner.id))
        self.api.unsubscribe_scanner = lambda scanner, **kwargs: self.api.calls.append(('scanner_unsubscribe', scanner.id))
        self.secrets = FakeSecrets()
        self.sdk = fake_sdk()
        self.sdk.__version__ = SDK_VERSION
        self.sdk.Shioaji = lambda **kw: self.api
        self.sdk.QuoteType = self.sdk.QuoteVersion = lambda value: value
        self.now = datetime(2026, 10, 30, 1, 10, tzinfo=timezone.utc)
        self.clock = SimpleNamespace(now=lambda: self.now)
        self.bundle.market_terminal.now = self.clock.now
        connection = self.bundle.market_connection
        connection.factory = lambda settings, directory: MarketSession(settings, self.secrets, self.sdk, self.clock, directory)
        self.bundle.market_history.close()
        history = HistorySync(self.bundle.kline_store, SessionBridge(connection), now=self.clock.now, autostart=False)
        self.bundle.market_history = self.bundle.market_terminal.history = history

    def tearDown(self):
        self.bundle.close()
        self.bundle.market_connection.close()
        self.temp.cleanup()

    def command(self, action, **kwargs):
        return self.bundle.execute(UiCommand(action, self.bundle.snapshot().version, **kwargs))

    def request(self, operation, **kwargs):
        request = Request('offline-m1', Environment.LOCAL, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=10), operation, **kwargs)
        return loads(dumps(_dispatch(self.bundle, loads(dumps(request)))))

    def test_sector_flow_cooldown_marks_use_the_minute_database(self):
        monitor = self.bundle.session_bridge.monitor
        self.assertIs(monitor.marks, self.bundle.sector_minute_store)

    def test_sector_board_serves_the_minute_aggregator_share_baselines(self):
        from quantlab.trading.application.sector_contracts import ShareBaseline

        self.bundle.sector_minutes.baselines = (ShareBaseline('industry.24', 120, 3),)
        self.assertEqual(self.bundle.sector.share_baselines(), (ShareBaseline('industry.24', 120, 3),))

    def test_each_sector_round_feeds_the_screener_after_the_sector_hooks_and_the_extra_close_round_only_the_screener(self):
        from quantlab.trading.domain.sector import QuoteRow
        from quantlab.trading.domain.watch import WatchInstrument, WatchKind

        taipei = timezone(timedelta(hours=8))
        clock = {'now': datetime(2026, 11, 9, 10, 0, tzinfo=taipei)}
        row = QuoteRow('1234', Decimal('110'), Decimal(10), '', 2000, 40_000_000, Decimal(4), clock['now'], Decimal(100), Decimal('110.5'), Decimal(99))
        sector = self.bundle.sector
        sector.directory = lambda: (WatchInstrument('TWSE:1234', WatchKind.STOCK, 'TSE', '1234', 'N1234', '24'),)
        sector.source = SimpleNamespace(connected=True, snapshots=lambda instruments: (row,))
        sector.now = lambda: clock['now']
        calls, requests = [], []
        self.bundle.sector_minutes.on_round = lambda now, stats: calls.append('minutes') or ()
        self.bundle.session_bridge.monitor.on_round = lambda now, stats: calls.append('monitor') or ()
        self.bundle.screener.history = SimpleNamespace(request=lambda *args: requests.append(args))
        sector.refresh()
        self.assertEqual(calls, ['minutes', 'monitor'])
        self.assertEqual([(item.code, priority) for item, _, _, priority in requests], [('1234', 10_000)])
        (event,) = (item for item in self.bundle.alerts.service.events if item.kind is AlertKind.SCREEN_DOWNLOAD)
        self.assertEqual((event.instrument_id, event.message_args), ('TWSE:1234', ('SURGE_RED', '1234', 'N1234')))
        clock['now'] = datetime(2026, 11, 9, 13, 40, tzinfo=taipei)
        self.assertTrue(sector.due())
        sector.refresh()
        self.assertEqual(calls, ['minutes', 'monitor'])  # the extra after-close round skips the sector hooks
        self.assertEqual(len(requests), 2)  # the screener extended today's download to now
        self.assertEqual(requests[1][2], clock['now'])

    def test_screener_requests_reach_the_real_bundle_and_saved_thresholds_reach_the_running_screener(self):
        from dataclasses import replace as replace_values

        from quantlab.trading.application.screener_contracts import ScreenerQuery

        offline = self.request(Operation.SCREENER, screener=ScreenerQuery('SURGE')).screener
        self.assertEqual((offline.list_id, offline.state, offline.rows), ('SURGE', 'OFFLINE', ()))
        self.assertEqual(self.request(Operation.SCREENER, screener=ScreenerQuery('DOWNLOADED')).screener.downloaded, ())
        params = self.request(Operation.SCREENER_SETTINGS).screener_params
        changed = replace_values(params, surge_ratio=Decimal(4), download_black=True)
        self.assertEqual(self.request(Operation.SCREENER_SETTINGS, screener_params=changed).screener_params, changed)
        self.assertEqual(self.bundle.screener.params(), changed)  # the next round judges with the saved values
        self.assertEqual(self.bundle.market_preferences.screener, changed)

    def test_the_daily_store_is_its_own_file_and_nothing_is_fetched_until_the_engine_asks(self):
        store = self.bundle.market_daily_store
        self.assertEqual(store.path, (Path(self.temp.name) / 'market' / 'market_daily.sqlite3').resolve())
        self.assertIsNone(self.bundle.market_daily_backfill)  # building a runtime never starts a network worker
        self.assertIs(self.bundle.screener.daily.store, store)
        self.assertFalse((Path(self.temp.name) / 'market' / 'market_daily.sqlite3-journal').exists())

    def test_start_market_daily_runs_the_backfill_through_the_given_fetcher_and_it_can_be_closed(self):
        import time

        from quantlab.trading.runtime.market_daily import start_market_daily

        fixtures = Path(__file__).parent / 'fixtures' / 'market_daily'
        urls = []

        def fetch(url):
            urls.append(url)
            return (fixtures / ('twse_holiday.json' if 'twse' in url else 'tpex_holiday.json')).read_bytes()

        start_market_daily(self.bundle, fetch)
        start_market_daily(self.bundle, fetch)  # asking twice does not start a second worker
        deadline = time.monotonic() + 5
        while not urls and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(urls)
        self.assertTrue(
            all(url.startswith(('https://www.twse.com.tw/exchangeReport/MI_INDEX?', 'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?')) for url in urls)
        )
        backfill = self.bundle.market_daily_backfill
        backfill.close()
        self.assertFalse(backfill._thread.is_alive())

    def test_an_unopenable_daily_file_is_named_on_the_breakout_list_and_the_rest_keeps_working(self):
        from unittest import mock

        from quantlab.trading.domain.validation import DomainError
        from quantlab.trading.runtime import market_daily as runtime_daily
        from quantlab.trading.application.screener_contracts import ScreenerQuery

        self.assertEqual(self.bundle.screener_board.daily_code(), '')  # a healthy file names nothing
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(runtime_daily, 'MarketDailyStore', side_effect=DomainError('market_daily_unavailable', 'locked')),
        ):
            bundle = build_runtime(RuntimeLaunch(Path(folder)))
            try:
                self.assertIsNone(bundle.market_daily_store)
                self.assertEqual(bundle.screener_board.daily_code(), 'market_daily_unavailable')
                view = bundle.screener_board.view(ScreenerQuery('BREAKOUT'))
                self.assertEqual((view.state, view.code), ('OFFLINE', ''))  # nothing connected: the offline state wins
                bundle.sector.source = SimpleNamespace(connected=True, snapshots=lambda instruments: ())
                bundle.sector.now = lambda: datetime(2026, 11, 9, 10, 0, tzinfo=timezone(timedelta(hours=8)))
                bundle.sector._fetched_at = bundle.sector.now()
                view = bundle.screener_board.view(ScreenerQuery('BREAKOUT'))
                self.assertEqual((view.state, view.code), ('ACCUMULATING', 'market_daily_unavailable'))
            finally:
                bundle.close()
                bundle.market_connection.close()

    def test_closing_the_bundle_stops_the_backfill_worker_and_closes_the_daily_store(self):
        import time

        import sqlite3

        from quantlab.trading.domain.validation import DomainError
        from quantlab.trading.runtime.market_daily import start_market_daily

        start_market_daily(self.bundle, lambda url: (_ for _ in ()).throw(DomainError('official_stock_invalid', 'offline')))
        backfill, store = self.bundle.market_daily_backfill, self.bundle.market_daily_store
        time.sleep(0.05)
        self.assertTrue(backfill._thread.is_alive())
        self.bundle.close()
        self.assertFalse(backfill._thread.is_alive())
        with self.assertRaises(sqlite3.ProgrammingError):
            store.upsert(())  # the store is closed with the bundle

    def test_a_failing_sector_hook_still_lets_the_screener_see_the_round(self):
        from quantlab.trading.domain.sector import QuoteRow
        from quantlab.trading.domain.watch import WatchInstrument, WatchKind

        taipei = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 9, 10, 0, tzinfo=taipei)
        row = QuoteRow('1234', Decimal('110'), Decimal(10), '', 2000, 40_000_000, Decimal(4), now, Decimal(100), Decimal('110.5'), Decimal(99))
        sector = self.bundle.sector
        sector.directory = lambda: (WatchInstrument('TWSE:1234', WatchKind.STOCK, 'TSE', '1234', 'N1234', '24'),)
        sector.source = SimpleNamespace(connected=True, snapshots=lambda instruments: (row,))
        sector.now = lambda: now
        requests = []

        def broken(now, stats):
            raise RuntimeError('minute store failed')

        self.bundle.sector_minutes.on_round = broken
        self.bundle.screener.history = SimpleNamespace(request=lambda *args: requests.append(args))
        with self.assertRaises(RuntimeError):
            sector.refresh()  # the aggregator's error still reaches the poller as before
        self.assertEqual(len(requests), 1)  # and the screener has queued its download

    def test_independent_connection_without_trading_fields_and_real_wire_roundtrips(self):
        self.assertTrue(self.command(UiAction.SAVE_MARKET_DATA_SETTINGS, market_data_settings=MarketDataSettings(enabled=True)).accepted)
        self.assertEqual(self.bundle.snapshot().watchlist, ())
        self.assertTrue(self.command(UiAction.CONNECT_MARKET_DATA).accepted)
        self.bundle.market_connection.worker.join(2)
        self.assertFalse(self.bundle.market_connection.worker.is_alive())
        state = self.bundle.snapshot()
        self.assertEqual(state.market_connection, 'CONNECTED')
        self.assertEqual(state.watchlist, ())
        self.assertEqual(state.market_health.subscription_count, 2)
        items = self.request(Operation.SYMBOL_DIRECTORY).instruments
        self.assertEqual(next(item.name for item in items if item.instrument_id == STOCK.instrument_id), 'Name 2330')
        selected = self.request(Operation.MARKET_SELECT, series=MarketSeriesQuery(STOCK.instrument_id))
        self.assertEqual(selected.receipt.reference, 'LIVE')
        self.assertEqual(self.request(Operation.MARKET_PREFERENCES).market_selected, STOCK.instrument_id)
        self.assertTrue(self.command(UiAction.SAVE_SETTINGS, watchlist=(STOCK.instrument_id,)).accepted)
        self.assertEqual(self.bundle.snapshot().watchlist, (STOCK.instrument_id,))
        self.assertEqual(sum(call[0] == 'subscribe' and call[1] == '2330' and call[2] == 'tick' for call in self.api.calls), 1)
        self.assertEqual(sum(call[0] == 'subscribe' and call[1] == '2330' and call[2] == 'bidask' for call in self.api.calls), 1)
        start = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.bundle.market_history.request(STOCK, start, start + timedelta(days=1), priority=-1)
        self.bundle.market_history.run_next()
        page = self.request(Operation.MARKET_SERIES, series=MarketSeriesQuery(STOCK.instrument_id)).series
        self.assertEqual(len(page.bars), 1)
        self.assertEqual(page.bars[0].start.hour, 1)
        status = self.request(Operation.MARKET_STATUS).market_status
        self.assertEqual(status.subscription_count, 4)  # two indices, the watched stock and its five-level slot
        self.assertTrue(status.connected)
        self.assertEqual(self.secrets.references, ['MarkAuto/v2/broker/sinopac'])
        self.assertTrue(self.command(UiAction.DISCONNECT_MARKET_DATA).accepted)
        self.bundle.market_connection.worker.join(2)
        self.assertEqual(self.bundle.snapshot().market_connection, 'DISCONNECTED')
        self.assertIn(('logout',), self.api.calls)

    def test_startup_and_preferences_never_resolve_credentials(self):
        self.assertEqual(self.secrets.references, [])
        self.assertEqual(self.api.calls, [])
        self.request(Operation.MARKET_PREFERENCES)
        self.request(Operation.SYMBOL_DIRECTORY)
        self.assertEqual(self.secrets.references, [])
        self.assertEqual(self.api.calls, [])

    def test_alert_command_and_live_tick_crossing_reach_same_authenticated_host(self):
        self.command(UiAction.SAVE_MARKET_DATA_SETTINGS, market_data_settings=MarketDataSettings(enabled=True))
        self.command(UiAction.CONNECT_MARKET_DATA)
        self.bundle.market_connection.worker.join(2)
        self.assertEqual(self.bundle.snapshot().market_connection, 'CONNECTED')
        self.request(Operation.MARKET_SELECT, series=MarketSeriesQuery(STOCK.instrument_id))
        rule = AlertRule('real-wire-alert', AlertKind.PRICE_CROSS, instrument_id=STOCK.instrument_id, params={'price': Decimal('100')})
        response = self.request(Operation.ALERTS, alert=AlertCommand(AlertOperation.ADD, rule=AlertRuleData.from_rule(rule)))
        self.assertEqual(len(response.alerts.rules), 1)
        while self.bundle.market_history.run_next():
            pass
        for price in (99, 101):
            self.api.callbacks['stock'](None, SimpleNamespace(code='2330', datetime=self.now, close=price, volume=1))
            self.bundle.market_terminal.poll()
            self.now += timedelta(seconds=1)
        response = self.request(Operation.ALERTS, alert=AlertCommand())
        self.assertEqual(len(response.alerts.events), 1)
        self.assertEqual(response.alerts.events[0].instrument_id, STOCK.instrument_id)
        self.assertEqual(response.alerts.events[0].value, Decimal('101'))


if __name__ == '__main__':
    unittest.main()
