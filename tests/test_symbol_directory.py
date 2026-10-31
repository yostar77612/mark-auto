"""Contract V2 directory cache, names and fail-safe offline fallback."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.domain.watch import FIXED_INDICES


class SymbolDirectoryTests(unittest.TestCase):
    def test_fixed_indices_available_without_network_and_bad_cache_preserved(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / 'symbol_directory.json'
            path.write_text('{broken', encoding='utf-8')
            directory = SymbolDirectory(path)
            self.assertEqual(FIXED_INDICES, directory.items)
            self.assertEqual('{broken', path.read_text(encoding='utf-8'))

    def test_names_fetched_once_per_refresh_not_search_and_warrants_excluded(self):
        calls = []
        stocks = [
            SimpleNamespace(code=code, exchange=exchange)
            for code, exchange in [('2330', 'TSE'), ('0050', 'TSE'), ('006208', 'TSE'), ('6104', 'OTC'), ('030001', 'TSE')]
        ]
        indices = [SimpleNamespace(code='IX0999', exchange='TSE')]
        facade = SimpleNamespace(
            market_contracts=lambda kind: stocks if kind == 'STK' else indices,
            market_contract_info=lambda base: calls.append(base.code) or SimpleNamespace(name='Name ' + base.code),
        )
        now = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / 'symbol_directory.json'
            directory = SymbolDirectory(path)
            items = directory.refresh(facade, now)
            self.assertEqual({'2330', '0050', '006208', '6104', 'IX0999'}, set(calls))
            self.assertIn('TPEX:6104', {item.instrument_id for item in items})
            self.assertIn('INDEX:IX0999', {item.instrument_id for item in items})
            directory.refresh(facade, now + timedelta(hours=2))
            self.assertEqual(5, len(calls))
            self.assertEqual(items, SymbolDirectory(path).items)
            self.assertEqual(1, json.loads(path.read_text(encoding='utf-8'))['version'])
            self.assertGreaterEqual(directory.refresh_seconds, 0)
            directory.refresh(facade, now + timedelta(days=1))
            self.assertEqual(10, len(calls))


if __name__ == '__main__':
    unittest.main()
