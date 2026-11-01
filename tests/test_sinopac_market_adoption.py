"""The existing M1 market service adopts a consumer without another login."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.market_session import MarketSession
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.models import Environment
from test_market_session import FakeApi, FakeSecrets, STOCK


class MarketAdoptionTests(unittest.TestCase):
    def test_authenticated_owner_serves_terminal_without_resolving_secrets_again(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            api, secrets = FakeApi(), FakeSecrets()
            module = SimpleNamespace(__version__='1.7.9', QuoteType=lambda value: value, QuoteVersion=lambda value: value)
            owner = SharedSDKSession(ShioajiSDKFacade(api, module, environment=Environment.BROKER_SIMULATION))
            owner.login(api_key='fake', secret_key='fake')
            clock = SimpleNamespace(now=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
            market = MarketSession(MarketDataSettings(enabled=True), secrets, module, clock, SymbolDirectory(Path(directory) / 'directory.json'))
            market.attach_authenticated(owner.consumer('terminal'))
            market.subscribe(STOCK)
            self.assertTrue(market.connected)
            self.assertEqual(len(market.directory.items), 3)
            self.assertEqual(market.usage().used_bytes, 100)
            market.disconnect()
            self.assertEqual(secrets.references, [])
            self.assertEqual([call for call in api.calls if call[0] == 'login'], [('login', True)])
            self.assertEqual([call for call in api.calls if call[0] == 'logout'], [])
            owner.close()
            self.assertEqual([call for call in api.calls if call[0] == 'logout'], [('logout',)])


if __name__ == '__main__':
    unittest.main()
