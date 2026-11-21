"""Independent market settings and chart preferences retain both concurrent writes."""

from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.screener import ScreenerParams
from decimal import Decimal
from quantlab.trading.runtime.market_connection import MarketConnection
from quantlab.trading.runtime.market_terminal_settings import MarketTerminalSettings


class ScreenerSettingsTests(unittest.TestCase):
    def test_thresholds_default_then_save_and_reload_without_touching_the_watchlist(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            preferences = MarketTerminalSettings(path)
            self.assertEqual(preferences.screener, ScreenerParams())
            preferences.save_watchlist(('TWSE:2330',))
            self.assertNotIn('screener', preferences.store.load()['market_terminal_v1'])  # nothing saved, nothing written
            changed = ScreenerParams(surge_ratio=Decimal('2.5'), quiet_amount=80_000_000, download_black=True, download_red=False)
            self.assertEqual(preferences.save_screener(changed), changed)
            reloaded = MarketTerminalSettings(path)
            self.assertEqual((reloaded.screener, reloaded.watchlist), (changed, ('TWSE:2330',)))
            preferences.save_selected('TWSE:2317')
            self.assertEqual(MarketTerminalSettings(path).screener, changed)  # a later watchlist or selection save keeps it

    def test_damaged_or_out_of_range_thresholds_fall_back_to_the_defaults_and_the_file_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            for saved in ({'surge_ratio': '99'}, {'surge_ratio': 'abc'}, {'download_red': 1}, 'text', [1]):
                with self.subTest(saved=saved):
                    SettingsStore(path).save({'market_terminal_v1': {'watchlist': [], 'selected': 'INDEX:IX0001', 'screener': saved}})
                    before = path.read_text('utf-8')
                    self.assertEqual(MarketTerminalSettings(path).screener, ScreenerParams())
                    self.assertEqual(path.read_text('utf-8'), before)

    def test_a_failed_write_keeps_the_previous_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            preferences = MarketTerminalSettings(Path(temporary) / 'settings.json')
            before = preferences.screener
            preferences.store.save = lambda body: (_ for _ in ()).throw(OSError('disk'))
            with self.assertRaises(DomainError):
                preferences.save_screener(ScreenerParams(surge_ratio=Decimal(5)))
            self.assertEqual(preferences.screener, before)


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
