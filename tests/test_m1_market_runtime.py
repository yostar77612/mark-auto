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


class MarketRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bundle = build_runtime(RuntimeLaunch(Path(self.temp.name)))
        self.api = FakeApi()
        self.secrets = FakeSecrets()
        self.sdk = SimpleNamespace(__version__=SDK_VERSION, Shioaji=lambda **kw: self.api, QuoteType=lambda value: value, QuoteVersion=lambda value: value)
        self.clock = SimpleNamespace(now=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
        connection = self.bundle.market_connection
        connection.factory = lambda settings, directory: MarketSession(settings, self.secrets, self.sdk, self.clock, directory)
        self.bundle.market_history.close()
        history = HistorySync(self.bundle.kline_store, SessionBridge(connection), autostart=False)
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
        self.assertEqual(sum(call[0] == 'subscribe' and call[1] == '2330' for call in self.api.calls), 1)
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


if __name__ == '__main__':
    unittest.main()
