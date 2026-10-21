"""Cheap independent boundaries and immutable synthetic backtest evidence for B1."""

import copy
from decimal import Decimal, Inexact, localcontext, ROUND_DOWN
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from desktop_pages.backtest_summary_card import ReportSummaryCard
from desktop_strings import ui_text
from quantlab.core import ValidationError, content_hash
from quantlab.trade_statistics import THRESHOLDS, QUANTUM, describe, breakeven, red_flags
from tests.test_backtest import bar, dataset, run

D = Decimal
ROOT = Path(__file__).resolve().parents[1]


def ledger(values):
    return [{'net_pnl': D(str(value)), 'exit_timestamp': f'2026-01-{i + 1:02}T00:00:00Z'} for i, value in enumerate(values)]


class TradeStatisticsTests(unittest.TestCase):
    def test_reference_sample_and_numeric_types(self):
        source = ledger([100, -50, 100, -50])
        before = copy.deepcopy(source)
        stats = describe(source)
        expected = dict(
            n=4,
            wins=2,
            losses=2,
            ties=0,
            expectancy=D(25),
            avg_win=D(100),
            avg_loss=D(50),
            payoff_ratio=D(2),
            win_rate=D('0.5'),
            max_losing_streak=1,
            largest_win=D(100),
            largest_win_share=D('0.5'),
            profit_factor=D(2),
        )
        for key, value in expected.items():
            self.assertEqual(stats[key], value)
            self.assertIs(type(stats[key]), type(value))
            self.assertIsNone(stats[key + '_reason'])
            if type(value) is D:
                self.assertEqual(stats[key].as_tuple().exponent, -8)
        self.assertEqual(breakeven(stats)['breakeven_payoff_ratio'], D(1))
        self.assertEqual(breakeven(stats)['breakeven_win_rate'], D('0.33333333'))
        for key, value in breakeven(stats).items():
            if not key.endswith('_reason'):
                self.assertIs(type(value), D)
                self.assertEqual(value.as_tuple().exponent, -8)
        strings = [{**row, 'net_pnl': str(row['net_pnl'])} for row in source]
        self.assertEqual(describe(strings), stats)
        self.assertEqual(describe([{'net_pnl': '12.50'}]), describe([{'net_pnl': D('12.50')}]))
        self.assertEqual(source, before)

    def test_ties_empty_and_one_sided_samples(self):
        stats = describe(ledger([100, 0, -50, 100, -50]))
        self.assertEqual((stats['n'], stats['ties']), (5, 1))
        result = breakeven(stats)
        self.assertEqual(result['breakeven_payoff_ratio'], D(1))
        self.assertIsNone(result['breakeven_win_rate'])
        self.assertIn('tie_lots', result['breakeven_win_rate_reason'])
        for values in ([10, 20], [-10, -20], [0, 0]):
            stats = describe(ledger(values))
            self.assertIsNone(stats['payoff_ratio'])
            self.assertTrue(stats['payoff_ratio_reason'])
            red_flags(stats)
            breakeven(stats)
        stats = describe([])
        for result in (stats, breakeven(stats)):
            for key, value in result.items():
                self.assertTrue(value) if key.endswith('_reason') else self.assertIsNone(value)
        self.assertEqual(red_flags(stats, D(1)), [])

    def test_validation_and_stable_timestamp_order(self):
        for value in (None, {}, 'ledger', iter([])):
            with self.assertRaises(ValidationError):
                describe(value)
        for value in ('NaN', 'Infinity', '-Infinity', 'invalid', None, True, {}, D('sNaN')):
            with self.assertRaises(ValidationError):
                describe([{'net_pnl': value}])
        source = ledger([-1, -1, -1, 1, -1])
        self.assertEqual(describe([source[i] for i in (4, 2, 0, 3, 1)]), describe(source))
        source[1]['exit_timestamp'] = source[0]['exit_timestamp']
        self.assertEqual(describe(source)['max_losing_streak'], 3)
        tied = [{'net_pnl': D(pnl), 'exit_timestamp': '2026-01-01T00:00:00Z'} for pnl in (-1, 1, -1)]
        self.assertEqual(describe(tied)['max_losing_streak'], 1)
        with localcontext() as context:
            context.prec, context.rounding = 6, ROUND_DOWN
            context.traps[Inexact] = True
            self.assertEqual(describe(ledger([100, -50, 100, -50]))['payoff_ratio'], D(2))
            self.assertEqual(breakeven(describe(ledger([100, -50, 100, -50])))['breakeven_win_rate'], D('0.33333333'))

    def test_flag_boundaries_and_order(self):
        base = describe(ledger([100, -50, 100, -50]))
        cases = (
            ('negative_expectancy', 'expectancy', ('-0.01', '0', '0.01'), (True, False, False), {}),
            ('single_trade_dominance', 'largest_win_share', ('0.4999', '0.50', '0.5001'), (False, False, True), {}),
            ('small_wins_big_losses', 'win_rate', ('0.6999', '0.70', '0.7001'), (False, False, True), {'payoff_ratio': D('0.39')}),
            ('small_wins_big_losses', 'payoff_ratio', ('0.3999', '0.40', '0.4001'), (True, False, False), {'win_rate': D('0.7001')}),
            ('thin_edge_margin', 'payoff_ratio', ('0.9999', '1', '1.0001', '1.2499', '1.25', '1.2501'), (False, False, True, True, False, False), {}),
            ('long_losing_streak', 'max_losing_streak', (7, 8, 9), (False, True, True), {}),
            ('marginal_profit_factor', 'profit_factor', ('0', '1.09', '1.1', '1.1001'), (False, True, False, False), {'n': 20}),
        )
        for code, key, values, expected, overrides in cases:
            for value, applies in zip(values, expected):
                stats = {**base, **overrides, key: D(value) if isinstance(value, str) else value}
                with self.subTest(code=code, value=value):
                    self.assertEqual(code in [f['code'] for f in red_flags(stats)], applies)
        for value, applies in (('0.4999', False), ('0.50', False), ('0.5001', True)):
            self.assertEqual('severe_drawdown' in [f['code'] for f in red_flags(base, D(value))], applies)
        for n, pf in ((19, D('1.09')), (20, None), (19, D('0.1'))):
            self.assertNotIn('marginal_profit_factor', [f['code'] for f in red_flags({**base, 'n': n, 'profit_factor': pf})])
        all_stats = {
            **base,
            'n': 20,
            'expectancy': D(-1),
            'largest_win_share': D('0.6'),
            'win_rate': D('0.8'),
            'payoff_ratio': D('0.39'),
            'wins': 16,
            'losses': 5,
            'profit_factor': D('1.09'),
            'max_losing_streak': 8,
        }
        flags = red_flags(all_stats, D('0.6'))
        self.assertEqual([f['code'] for f in flags], list(THRESHOLDS))
        for flag in flags:
            self.assertEqual(flag['severity'], THRESHOLDS[flag['code']][-1])
            self.assertEqual(flag['key'], 'trade_structure.flag.' + flag['code'])

    def test_contract_thresholds_equal_constants(self):
        text = (ROOT / 'docs/agent/IMPLEMENTATION_CONTRACTS.md').read_text(encoding='utf-8')
        section = text.split('### Lane R \u2014 B1:', 1)[1]
        rows = [line.split('|')[1:3] for line in section.splitlines() if line.startswith('| ')][2:]
        documented = {code.strip(): constants.strip() for code, constants in rows}
        self.assertEqual(documented, {code: ', '.join(str(v) for v in values) for code, values in THRESHOLDS.items()})
        self.assertEqual(QUANTUM, D('0.00000001'))

    def test_real_synthetic_backtest_is_read_only(self):
        result = run(dataset([bar(0, '100'), bar(1, '100'), bar(2, '110'), bar(3, '90')]), [(0, 1), (2, 0)])
        before, identity = copy.deepcopy(result), content_hash(result)
        with patch('builtins.open', side_effect=AssertionError('No I/O')):
            stats = describe(result.ledger)
            breakeven(stats)
            red_flags(stats, result.metrics.get('max_drawdown_pct'))
        self.assertEqual(result, before)
        self.assertEqual(content_hash(result), identity)
        self.assertIsInstance(result.ledger, tuple)


class TradeStructureWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_text_severity_reasons_privacy_and_default(self):
        card = ReportSummaryCard()
        self.addCleanup(card.close)
        self.assertFalse(hasattr(card, 'structure'))
        card.set_values({'closed_lots': 2}, ledger=ledger([-10, 2]))
        text = card.structure.text()
        for key in ('trade_structure.expectancy', 'trade_structure.severity.high', 'trade_structure.flag.negative_expectancy'):
            self.assertIn(ui_text(key), text)
        self.assertTrue(card.structure.accessibleName())
        card.privacy = SimpleNamespace(enabled=True)
        card.structure._privacy_render()
        self.assertIn('\u2022\u2022\u2022\u2022', card.structure.text())
        self.assertNotIn('-4.00000000', card.structure.text())
        card.set_values({'closed_lots': 0}, ledger=[])
        self.assertIn(ui_text('trade_structure.reason.no_closed_lots'), card.structure.text())
        card.set_values({})
        self.assertTrue(card.isHidden())
        self.assertTrue(card.structure.isHidden())
        self.assertEqual(card.label.text(), ui_text('backtest.summary.empty'))
