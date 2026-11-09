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
        self.assertEqual(status.subscription_count, 3)
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
