"""Qt-free U2-C6 tests: this module imports no desktop widget package."""

from decimal import Decimal as D
from pathlib import Path
import unittest

from quantlab.paper_tab_data import EVENT_LIMIT, account_counts, event_rows, position_rows, scaled_fractions, working_order
from desktop_app.strings.catalog import ZH_TW, ui_text

ROOT = Path(__file__).resolve().parents[1]
CID = 'TAIFEX:TMF:202601'


def generated():
    return {
        'positions': {CID: 3},
        'orders': {
            '0': {'intent': {'contract_id': CID}, 'status': 'accepted'},
            '1': {'status': 'partial'},
            **{str(i): {'status': 'filled'} for i in range(2, 34)},
        },
        'fills': {'f': {'order_id': '0', 'multiplier': '10'}},
        'lots': [{'entry_fill_id': 'f', 'quantity': 3, 'direction': 1, 'price': '100'}],
        'last_mark_price': '105',
    }


class PaperTabPureTests(unittest.TestCase):
    def test_only_nonterminal_orders_count_as_working(self):
        for status in ('accepted', 'partial', 'submitting', 'cancel_pending', 'unknown'):
            self.assertTrue(working_order({'status': status}))
        for status in ('filled', 'cancelled', 'rejected', None):
            self.assertFalse(working_order({'status': status}))

    def test_counts_none_empty_and_fixed_seed_accounts(self):
        for account in (None, {}, dict(positions=None, orders=None, fills=None)):
            self.assertEqual(account_counts(account), dict(positions=0, orders=0, fills=0, active=0))
        for _ in range(5):
            account = generated()
            counts = account_counts(account)
            self.assertEqual(counts, dict(positions=1, orders=34, fills=1, active=2))

    def test_scaling_zero_positive_negative_mixed_equal_unknown(self):
        for values, expected in (
            ([0, 0], [0, 0]),
            ([1, 2], [D('.5'), 1]),
            ([-2, -1], [1, D('.5')]),
            ([-4, 2, 0], [1, D('.5'), 0]),
            ([2, 2], [1, 1]),
            ([None, 'NaN'], [None, None]),
            ([], []),
        ):
            self.assertEqual(scaled_fractions(values), expected)

    def test_pnl_uses_journaled_mark_lots_and_explicit_multiplier(self):
        account = generated()
        self.assertEqual(position_rows(account)[0]['pnl'], D(150))
        account['lots'][0]['direction'] = -1
        account['positions'][CID] = -3
        self.assertEqual(position_rows(account)[0]['pnl'], D(-150))
        for key in ('last_mark_price', 'lots', 'fills'):
            missing = generated()
            missing.pop(key)
            self.assertIsNone(position_rows(missing)[0]['pnl'])
        account = generated()
        account['fills']['f'].pop('multiplier')
        self.assertIsNone(position_rows(account)[0]['pnl'])

    def test_pnl_never_guesses_contract_or_partial_cost_basis(self):
        for mutate in (
            lambda a: a['positions'].update(other=1),
            lambda a: a['positions'].update({CID: 4}),
            lambda a: a['orders']['0']['intent'].update(contract_id='other'),
        ):
            account = generated()
            mutate(account)
            self.assertTrue(all(row['pnl'] is None for row in position_rows(account)))

    def test_events_bounded_and_payloads_never_echoed(self):
        account = {
            'events': [{'operation': 'fill', 'payload': {'secret': 'SECRET-SENTINEL', 'oos': 'OOS-SENTINEL'}, 'message': 'SECRET-SENTINEL'} for _ in range(500)]
        }
        rows = event_rows(account)
        self.assertEqual(len(rows), EVENT_LIMIT)
        self.assertEqual(rows[0]['sequence'], 301)
        self.assertNotIn('SENTINEL', str(rows))
        self.assertEqual(len(event_rows(generated())), 1)

    def test_catalog_neutral_and_pure_module_has_no_qt(self):
        strings = [value for key, value in ZH_TW.items() if key.startswith('paper.tabs.')]
        for value in strings:
            for forbidden in ('guarantee', 'guaranteed', '\u4fdd\u8b49', '\u7a69\u8cfa', '\u5fc5\u8cfa'):
                self.assertNotIn(forbidden, value.lower())
        self.assertIn('\u6a21\u64ec', ui_text('paper.tabs.simulated_pnl'))
        source = (ROOT / 'quantlab/paper_tab_data.py').read_text(encoding='utf-8')
        self.assertNotIn('PySide', source)


if __name__ == '__main__':
    unittest.main()
