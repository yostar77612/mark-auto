"""Offline session contract: reference-only settings never grant trading access."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.market_session import MarketSession, TAIPEI
from quantlab.trading.adapters.shioaji.sdk import BrokerCredentials, SDK_VERSION
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind

STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', 'TSMC')


class FakeContracts:
    def __init__(self, calls):
        self.calls = calls
        self.values = {
            code: SimpleNamespace(code=code, security_type=kind, exchange=exchange)
            for code, kind, exchange in (('2330', 'STK', 'TSE'), ('IX0001', 'IND', 'TSE'), ('IX0043', 'IND', 'OTC'))
        }

    def list(self, kind):
        self.calls.append(('contracts.list', kind))
        return [value for value in self.values.values() if value.security_type == kind]

    def get(self, code):
        self.calls.append(('contracts.get', code))
        return self.values[code]

    def info(self, base):
        self.calls.append(('contracts.info', base.code))
        return SimpleNamespace(name='Name ' + base.code)


class FakeApi:
    def __init__(self):
        self.calls = []
        self.contracts = FakeContracts(self.calls)
        self.callbacks = {}
        self.fail_login = False
        wall = datetime(2026, 10, 30, 9, 1, tzinfo=timezone.utc)
        self.raw = SimpleNamespace(ts=[int(wall.timestamp() * 1e9)], Open=[100], High=[102], Low=[99], Close=[101], Volume=[4])

    def login(self, **kwargs):
        self.calls.append(('login', kwargs['subscribe_trade']))
        if self.fail_login:
            raise RuntimeError('SECRET_FAKE_API_KEY SECRET_FAKE_SECRET')
        return []

    def logout(self):
        self.calls.append(('logout',))

    def subscribe(self, contract, **kwargs):
        self.calls.append(('subscribe', contract.code, kwargs['quote_type']))

    def unsubscribe(self, contract, **kwargs):
        self.calls.append(('unsubscribe', contract.code, kwargs['quote_type']))

    def usage(self):
        return SimpleNamespace(bytes=100, limit_bytes=1000)

    def kbars(self, **kwargs):
        self.calls.append(('kbars', kwargs['contract'].code, kwargs['start'], kwargs['end']))
        return self.raw

    def set_on_tick_stk_v1_callback(self, callback, **kwargs):
        self.callbacks['stock'] = callback

    def set_on_tick_fop_v1_callback(self, callback, **kwargs):
        self.callbacks['fop'] = callback

    def set_on_bidask_stk_v1_callback(self, callback, **kwargs):
        self.callbacks['bidask'] = callback

    def set_on_quote_idx_v1_callback(self, callback):
        self.callbacks['index'] = callback

    def set_session_down_callback(self, callback):
        self.callbacks['down'] = callback

    def __getattr__(self, name):
        raise AssertionError('Unexpected SDK surface: ' + name)


class FakeSecrets:
    def __init__(self):
        self.references = []

    def broker_credentials(self, reference):
        self.references.append(reference)
        return BrokerCredentials('SECRET_FAKE_API_KEY', 'SECRET_FAKE_SECRET')

    def certificate_credentials(self, reference):
        raise AssertionError('Market session must never request CA')


class MarketSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.api = FakeApi()
        self.secret = FakeSecrets()
        self.simulations = []

        def construct(**kwargs):
            self.simulations.append(kwargs['simulation'])
            return self.api

        sdk = SimpleNamespace(__version__=SDK_VERSION, Shioaji=construct, QuoteType=lambda value: value, QuoteVersion=lambda value: value)
        clock = SimpleNamespace(now=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.directory = SymbolDirectory(Path(self.temp.name) / 'market' / 'symbol_directory.json')
        self.session = MarketSession(MarketDataSettings(enabled=True), self.secret, sdk, clock, self.directory)

    def test_only_reference_login_history_and_no_trading_surface(self):
        self.assertEqual([], self.api.calls)
        self.session.connect()
        self.session.subscribe(STOCK)
        self.session.subscribe(FIXED_INDICES[0])
        start = datetime(2026, 10, 30, tzinfo=TAIPEI).astimezone(timezone.utc)
        bars = self.session.history(STOCK, start, start + timedelta(days=1))
        self.assertEqual(1, len(bars))
        self.assertEqual(datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc), bars[0].start)
        self.assertEqual(Decimal('101'), bars[0].close)
        self.assertEqual('DAY', bars[0].session)
        self.assertTrue(bars[0].final)
        self.assertEqual(100, self.session.usage().used_bytes)
        self.session.disconnect()
        self.assertEqual([True], self.simulations)
        self.assertEqual(['MarkAuto/v2/broker/sinopac'], self.secret.references)
        names = {call[0] for call in self.api.calls}
        self.assertEqual({'login', 'contracts.list', 'contracts.info', 'contracts.get', 'subscribe', 'unsubscribe', 'kbars', 'logout'}, names)
        self.assertIn(('login', False), self.api.calls)
        self.assertIn(('subscribe', 'IX0001', 'quote'), self.api.calls)
        self.assertIn(('unsubscribe', '2330', 'tick'), self.api.calls)

    def test_stock_subscription_never_asks_the_options_only_tick_band_route(self):
        self.api.contracts.info = lambda base: SimpleNamespace(
            name='Name ' + base.code, reference=100, code=base.code, security_type='STK', exchange='TSE', region='TW'
        )

        def options_only(info):
            raise AttributeError('StockInfo has no attribute tick_rule')

        self.api.contracts.tick_bands = options_only
        self.session.connect()
        self.session.subscribe(STOCK)
        self.assertIn(('subscribe', '2330', 'tick'), self.api.calls)
        self.assertNotIn('price_tick', self.session.quote_details(STOCK.instrument_id))

    def test_login_error_never_contains_credentials_or_vendor_message(self):
        self.api.fail_login = True
        with self.assertRaises(DomainError) as caught:
            self.session.connect()
        self.assertEqual('market_data_login_failed', caught.exception.code)
        self.assertNotIn('SECRET_FAKE', str(caught.exception))
        self.assertIsNone(self.session.facade)
        self.assertIn(('logout',), self.api.calls)

    def test_stock_tick_naive_taipei_and_index_callback(self):
        self.session.connect()
        self.session.subscribe(STOCK)
        self.session.subscribe(FIXED_INDICES[0])
        raw = SimpleNamespace(code='2330', datetime=datetime(2026, 10, 30, 9, 0, 20), close=101, volume=3)
        self.api.callbacks['stock'](None, raw)
        self.api.callbacks['index'](SimpleNamespace(code='IX0001', datetime=raw.datetime, close=20000))
        ticks = self.session.drain_ticks(10)
        self.assertEqual(('TWSE:2330', 'INDEX:IX0001'), tuple(tick.instrument_id for tick in ticks))
        self.assertEqual(datetime(2026, 10, 30, 1, 0, 20, tzinfo=timezone.utc), ticks[0].source_at)
        self.assertEqual(0, ticks[1].volume)
        self.api.callbacks['down']()
        self.assertFalse(self.session.connected)
        self.assertEqual((), self.session.drain_ticks(10))

    def test_reconnect_logs_out_before_new_client_and_subscriptions_deduplicate(self):
        self.session.connect()
        self.session.subscribe(STOCK)
        self.session.subscribe(STOCK)
        self.assertEqual(1, sum(call[0] == 'subscribe' for call in self.api.calls))
        self.session.connect()
        self.assertLess(self.api.calls.index(('logout',)), len(self.api.calls) - 1)
        self.assertEqual(2, sum(call[0] == 'login' for call in self.api.calls))

    def test_market_settings_validation_and_live_is_data_only(self):
        for kwargs in ({'environment': Environment.LOCAL}, {'secret_ref': '/tmp/key'}, {'enabled': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DomainError):
                MarketDataSettings(**kwargs)
        self.session.settings = MarketDataSettings(Environment.LIVE, enabled=True)
        self.session.connect()
        self.assertEqual([False], self.simulations)


if __name__ == '__main__':
    unittest.main()
