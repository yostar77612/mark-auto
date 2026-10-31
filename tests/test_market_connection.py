"""Offline settings persistence, explicit lifecycle and backwards wire defaults."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.application.registry import initialize
from quantlab.trading.runtime.market_connection import MarketConnection
from quantlab.research_core.adapters.settings_store import SettingsStore


class MarketConnectionTests(unittest.TestCase):
    def test_reference_settings_preserve_unrelated_preferences_and_no_startup_login(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            SettingsStore(root / 'settings.json').save({'appearance': 'dark'})
            calls = []
            controller = MarketConnection(root, lambda *args: calls.append('constructed'))
            self.assertFalse(controller.settings.enabled)
            saved = MarketDataSettings(enabled=True)
            receipt = controller.execute(UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 0, market_data_settings=saved))
            self.assertTrue(receipt.accepted)
            self.assertEqual([], calls)
            restored = MarketConnection(root)
            self.assertEqual(saved, restored.settings)
            self.assertEqual('dark', SettingsStore(root / 'settings.json').load()['appearance'])

    def test_connect_disconnect_are_background_and_do_not_touch_trading_context(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            calls = []
            fake = SimpleNamespace(connected=False)

            def connect():
                calls.append('connect')
                fake.connected = True

            def disconnect():
                calls.append('disconnect')
                fake.connected = False

            fake.connect, fake.disconnect = connect, disconnect
            controller = MarketConnection(Path(folder), lambda *args: fake)
            controller.on_connected = lambda session: calls.append('ready')
            controller.on_disconnected = lambda: calls.append('down')
            controller.execute(UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 0, market_data_settings=MarketDataSettings(enabled=True)))
            self.assertTrue(controller.execute(UiCommand(UiAction.CONNECT_MARKET_DATA, 0)).accepted)
            controller.worker.join(1)
            self.assertFalse(controller.worker.is_alive())
            self.assertEqual('CONNECTED', controller.connection_status())
            self.assertTrue(controller.execute(UiCommand(UiAction.DISCONNECT_MARKET_DATA, 0)).accepted)
            controller.worker.join(1)
            self.assertEqual(['connect', 'ready', 'down', 'disconnect'], calls)
            self.assertEqual('DISCONNECTED', controller.connection_status())

    def test_missing_settings_connection_is_rejected_without_constructing_sdk(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            controller = MarketConnection(Path(folder), lambda *args: self.fail('SDK must not construct'))
            receipt = controller.execute(UiCommand(UiAction.CONNECT_MARKET_DATA, 0))
            self.assertEqual('market_data_not_configured', receipt.code)
            self.assertFalse(receipt.accepted)

    def test_defaulted_command_field_retains_old_wire_payload_compatibility(self):
        initialize()
        old = json.loads(dumps(UiCommand(UiAction.STOP_NEW, 9)))
        old['fields'].pop('market_data_settings')
        self.assertEqual(UiCommand(UiAction.STOP_NEW, 9), loads(json.dumps(old)))
        new = UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 10, market_data_settings=MarketDataSettings(enabled=True))
        self.assertEqual(new, loads(dumps(new)))


if __name__ == '__main__':
    unittest.main()
