"""Independent market settings and chart preferences retain both concurrent writes."""

from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest

from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.runtime.market_connection import MarketConnection
from quantlab.trading.runtime.market_terminal_settings import MarketTerminalSettings


class SettingsConcurrencyTests(unittest.TestCase):
    def test_two_sections_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = MarketConnection(root)
            preferences = MarketTerminalSettings(root / 'settings.json', lock=connection.settings_lock)
            captured, release, selected_read = Event(), Event(), Event()
            original_load = connection.store.load
            preference_load = preferences.store.load
            errors = []

            def paused_load():
                body = original_load()
                captured.set()
                if not release.wait(2):
                    raise TimeoutError('test release')
                return body

            def selected_load():
                selected_read.set()
                return preference_load()

            def save_connection():
                try:
                    receipt = connection.execute(UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 0, market_data_settings=MarketDataSettings(enabled=True)))
                    if not receipt.accepted:
                        errors.append(receipt.code)
                except Exception as error:
                    errors.append(type(error).__name__)

            connection.store.load = paused_load
            preferences.store.load = selected_load
            first = Thread(target=save_connection)
            second = Thread(target=lambda: preferences.save_selected('INDEX:IX0043'))
            first.start()
            try:
                self.assertTrue(captured.wait(1))
                second.start()
                self.assertFalse(selected_read.wait(0.05), 'second update must wait for the first complete read/write')
            finally:
                release.set()
                first.join(2)
                if second.ident is not None:
                    second.join(2)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(errors, [])
            body = original_load()
            self.assertTrue(body['market_data_v1']['enabled'])
            self.assertEqual(body['market_terminal_v1']['selected'], 'INDEX:IX0043')


if __name__ == '__main__':
    unittest.main()
