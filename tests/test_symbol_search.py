"""Offline directory ranking and normalization; no broker or Qt required."""

import unittest

from quantlab.trading.application.symbol_search import search_symbols
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind


def stock(code, name):
    return WatchInstrument('TWSE:' + code, WatchKind.STOCK, 'TSE', code, name)


class SymbolSearchTests(unittest.TestCase):
    def test_exact_prefix_name_prefix_then_contains(self):
        items = (stock('9999', '2330 company'), stock('23300', 'other'), stock('2330', 'exact'), stock('8888', 'A2330'))
        self.assertEqual([item.code for item in search_symbols(items, '2330')], ['2330', '23300', '9999', '8888'])

    def test_normalization_indices_names_and_limit(self):
        items = (stock('2330', '台積電'), *FIXED_INDICES)
        for query in ('2330', '２３３０', '台積'):
            self.assertEqual(search_symbols(items, query), items[:1])
        self.assertEqual(search_symbols(items, 'ｉｘ０００１'), (FIXED_INDICES[0],))
        many = tuple(stock(str(code), 'sample') for code in range(1000, 1030))
        self.assertEqual(len(search_symbols(many, 'sample')), 20)
        self.assertEqual(search_symbols(items, 'missing'), ())
        self.assertEqual(search_symbols(items, '  '), ())


if __name__ == '__main__':
    unittest.main()
