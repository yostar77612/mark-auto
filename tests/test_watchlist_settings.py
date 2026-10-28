"""Watchlist settings boundary and restore regressions; no market calculations."""

from pathlib import Path
import unittest
from unittest.mock import patch

from quantlab.trading.application.context import Catalog
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.watchlist_settings import WatchlistSettings
from test_live_market_wiring import memory_engine
from test_tick_adapters_contract import simulated_connector


class SettingsStub:
    def __init__(self, body):
        self.body = body

    def load(self):
        return self.body


class WatchlistSettingsTests(unittest.TestCase):
    def test_saved_watchlist_restores_when_market_becomes_available(self):
        with patch('quantlab.trading.runtime.watchlist_settings.SettingsStore', return_value=SettingsStub({'market_watch_v2': ['WATCH:1']})):
            settings = WatchlistSettings(Path('unused'))
        settings.restore(memory_engine())
        broker, clock, resolver = simulated_connector()
        service = LiveMarketService(broker, clock, resolver)
        engine = memory_engine(live_market=service)
        engine.catalog = Catalog((broker.resolve('WATCH:1'),))
        settings.restore(engine)
        self.assertEqual(settings.watchlist, ('WATCH:1',))
        self.assertEqual(service.watchlist, ('WATCH:1',))
        self.assertEqual(service.allocation.active, ('WATCH:1',))

    def test_unset_restore_preserves_existing_market_and_projects_its_views(self):
        broker, clock, resolver = simulated_connector()
        service = LiveMarketService(broker, clock, resolver)
        service.allocate((), ('WATCH:0',))
        service.poll(in_session=True)
        engine = memory_engine(live_market=service)
        before = service.allocation, service.market_revision, dict(broker.subscriptions)
        with patch('quantlab.trading.runtime.watchlist_settings.SettingsStore', return_value=SettingsStub({})):
            bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(engine), (), engine)
        self.assertIsNone(bundle.watch_settings.watchlist)
        self.assertIsNone(service.watchlist)
        self.assertEqual((service.allocation, service.market_revision, broker.subscriptions), before)
        self.assertEqual(bundle.snapshot().watchlist, ('WATCH:0',))

    def test_restore_without_market_preserves_saved_intent(self):
        for saved in (None, [], ['UNRESOLVED']):
            with self.subTest(saved=saved):
                with patch('quantlab.trading.runtime.watchlist_settings.SettingsStore', return_value=SettingsStub({'market_watch_v2': saved})):
                    settings = WatchlistSettings(Path('unused'))
                settings.restore(memory_engine())
                self.assertEqual(settings.watchlist, None if saved is None else tuple(saved))

    def test_explicit_empty_restore_clears_watch_subscriptions(self):
        broker, clock, resolver = simulated_connector()
        service = LiveMarketService(broker, clock, resolver)
        service.allocate((), ('WATCH:0',))
        engine = memory_engine(live_market=service)
        with patch('quantlab.trading.runtime.watchlist_settings.SettingsStore', return_value=SettingsStub({'market_watch_v2': []})):
            bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(engine), (), engine)
        self.assertEqual(service.watchlist, ())
        self.assertEqual(service.allocation.active, ())
        self.assertEqual(bundle.snapshot().watchlist, ())

    def test_invalid_settings_are_rejected_at_load_boundary(self):
        for saved in ('WATCH:0', [1], ['WATCH:0', 'WATCH:0'], [''], [f'WATCH:{i}' for i in range(21)]):
            with self.subTest(saved=saved):
                with patch('quantlab.trading.runtime.watchlist_settings.SettingsStore', return_value=SettingsStub({'market_watch_v2': saved})):
                    with self.assertRaises(DomainError):
                        WatchlistSettings(Path('unused'))
