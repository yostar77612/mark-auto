"""Synthetic-only B3 ordering, pure output and selection-isolation evidence."""

import ast
import copy
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop_app.strings.catalog import ui_text
from desktop_app.features.walk_forward.presenter import compact_walk_forward, oos_statistics_text
from quantlab import significance as sig, verdict
from quantlab.core import canonical_json, content_hash
from quantlab.research import _eligible
from quantlab.research_core.application.walk_forward_projection import oos_statistics_data
from quantlab import walk_forward as wf
from tests.test_significance_b2 import fold, state

ROOT = Path(__file__).resolve().parents[1]


def statistics(n=60, mean='0.01', p='0.001'):
    return dict(
        n=n,
        mean=Decimal(mean),
        sd=Decimal('.02'),
        t=Decimal(4),
        p_value_t=Decimal(p),
        p_value_bootstrap=Decimal(p),
        ci_lower=Decimal('.001'),
        ci_upper=Decimal('.02'),
        n_bootstrap_actual=100,
        t_hac=Decimal(4),
        p_value_t_hac=Decimal(p),
        hac_lag=3,
        p_value_block_bootstrap=Decimal(p),
        block_length=4,
    )


def judge(stats=None, returns=None, flags=(), required=None):
    return verdict.judge(
        statistics() if stats is None else stats,
        {'required_observations': 30} if required is None else required,
        ['.01', '.02'] * 30 if returns is None else returns,
        flags,
    )


class VerdictTests(unittest.TestCase):
    def test_order_table_including_adjacent_overlaps(self):
        high = [{'severity': 'high', 'code': 'concentration'}]
        cases = (
            (statistics(20, '-.002', '.5'), high, verdict.INSUFFICIENT),
            (statistics(40, '-.002', '.5'), high, verdict.NEGATIVE_EXPECTANCY),
            (statistics(40, '.0005', '.05'), high, verdict.LUCK_SUSPECTED),
            (statistics(), high, verdict.FRAGILE_EDGE),
            (statistics(), (), verdict.STATISTICAL_EDGE),
        )
        for stats, flags, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(judge(stats, flags=flags)['level'], expected)
        for key in verdict.STATISTICS + ('n',):
            stats = statistics(mean='-.002')
            stats[key] = None
            self.assertEqual(judge(stats)['level'], verdict.INSUFFICIENT, key)
        self.assertEqual(verdict.P_VALUES, ('p_value_t', 'p_value_bootstrap', 'p_value_t_hac', 'p_value_block_bootstrap'))
        for key in verdict.P_VALUES:
            stats = statistics()
            stats[key] = Decimal('.05')
            self.assertEqual(judge(stats, flags=high)['level'], verdict.LUCK_SUSPECTED, key)
            stats[key] = Decimal('1.000000000001')
            self.assertEqual(judge(stats)['level'], verdict.INSUFFICIENT, key)

    def test_closed_trades_below_minimum_or_unknown_are_insufficient(self):
        self.assertEqual(verdict.MIN_CLOSED_TRADES, 30)
        required = {'required_observations': 30}
        returns = ['.01', '.02'] * 30
        self.assertEqual(verdict.judge(statistics(), required, returns, ())['level'], verdict.STATISTICAL_EDGE)
        self.assertEqual(verdict.judge(statistics(), required, returns, (), closed_trades=30)['level'], verdict.STATISTICAL_EDGE)
        for count in (29, 1, 0, -1, None, True, '30', 30.0):
            with self.subTest(count=count):
                result = verdict.judge(statistics(), required, returns, (), closed_trades=count)
                self.assertEqual(result['level'], verdict.INSUFFICIENT)
                self.assertEqual(len(result['reasons']), 1)
                self.assertTrue(result['reasons'][0].startswith('insufficient_closed_trades: '))
        # A short sample and too few trades report both reasons, statistics first.
        result = verdict.judge(statistics(20), required, returns, (), closed_trades=2)
        self.assertEqual(result['reasons'], ['insufficient_statistics', 'recommended_observations: 30', 'insufficient_closed_trades: 2 < 30'])
        # Trade count outranks a negative mean, exactly like a short sample does.
        self.assertEqual(verdict.judge(statistics(mean='-.002'), required, returns, (), closed_trades=5)['level'], verdict.INSUFFICIENT)

    def test_real_b2_twenty_negative_and_noisy_samples(self):
        cases = (
            (['.001', '.002'] * 10, verdict.INSUFFICIENT),
            (['-.001', '-.003'] * 20, verdict.NEGATIVE_EXPECTANCY),
            (['-.0195', '.0205'] * 20, verdict.LUCK_SUSPECTED),
        )
        for returns, expected in cases:
            stats = sig.mean_positive_test(returns, n_bootstrap=100)
            required = sig.required_observations(returns)
            result = verdict.judge(stats, required, returns, [])
            self.assertEqual(result['level'], expected)
            self.assertEqual(result['display_name'], verdict.NAMES[verdict.LEVELS.index(expected)])
        result = judge(statistics(20), required={'required_observations': 123})
        self.assertIn('123', ' '.join(result['reasons']))
        result = judge(statistics(20), required={'required_observations': None, 'required_observations_reason': 'planning undefined'})
        self.assertIn('planning undefined', result['reasons'])
        self.assertIsNone(result['recommended_observations'])

    def test_compounded_drawdown_strict_boundary_and_initial_peak(self):
        for loss, expected in (('-.5', verdict.STATISTICAL_EDGE), ('-.500000000001', verdict.FRAGILE_EDGE)):
            result = judge(returns=[loss] + ['.01'] * 59)
            self.assertEqual(result['level'], expected)
            self.assertEqual('severe_drawdown' in result['reasons'], expected == verdict.FRAGILE_EDGE)
        self.assertEqual(verdict.compounded_drawdown(['-.2', '-.4']), Decimal('.52'))
        self.assertEqual(verdict.compounded_drawdown(['-1', '.4']), Decimal(1))
        returns = ['.3'] * 30 + ['-.04'] * 30
        stats = sig.mean_positive_test(returns, n_bootstrap=100)
        self.assertLess(stats['p_value_t'], Decimal('.05'))
        self.assertLess(stats['p_value_bootstrap'], Decimal('.05'))
        self.assertEqual(judge(stats, returns)['level'], verdict.FRAGILE_EDGE)

    def test_medium_notes_deterministic_pure_and_context_independent(self):
        flags = [{'severity': 'medium', 'code': 'z'}, {'severity': 'medium', 'code': 'a'}, {'severity': 'medium', 'code': 'a'}]
        args = [statistics(), {'required_observations': 30}, ['.01', '.02'] * 30, flags]
        before = copy.deepcopy(args)
        result = verdict.judge(*args)
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(verdict.judge(*args), result)
            before_flags = dict(context.flags)
            self.assertEqual(judge(returns=['bad'] * 60)['level'], verdict.INSUFFICIENT)
            self.assertEqual(dict(context.flags), before_flags)
        self.assertEqual(args, before)
        self.assertEqual(result['reasons'], ['positive_significant_mean', 'note: a', 'note: z'])
        self.assertEqual(set(result), {'level', 'display_name', 'reasons', 'recommended_observations'})
        self.assertIs(type(result['recommended_observations']), int)
        self.assertTrue(all(type(reason) is str for reason in result['reasons']))
        self.assertEqual(judge(flags=flags[::-1]), result)
        for level, name in zip(verdict.LEVELS, verdict.NAMES):
            self.assertEqual(ui_text('walk_forward.verdict.' + level + '.name'), name)
            self.assertNotIn('勸退', name)

    def test_odd_inputs_fail_closed_without_mutation(self):
        for odd in (None, True, 7, 'bad', [], {}, {'mean': 'NaN'}, {'n': []}):
            original = copy.deepcopy(odd)
            result = verdict.judge(odd, odd, odd, odd)
            self.assertEqual(odd, original)
            self.assertIn(result['level'], (None, verdict.INSUFFICIENT))
            self.assertTrue(result['reasons'])
        for returns in ([None] * 60, ['NaN'] * 60, ['-1.1'] * 60):
            self.assertEqual(judge(returns=returns)['level'], verdict.INSUFFICIENT)
        self.assertIsNone(judge(returns=[])['level'])

    def test_half_sample_flags_need_both_chronological_halves_to_compound_up(self):
        high = [{'severity': 'high', 'code': 'half_sample_not_positive'}]
        self.assertEqual(verdict.half_sample_flags(['.01', '.01', '.01', '.01']), [])
        self.assertEqual(verdict.half_sample_flags(['-.01', '.005', '.03', '.01']), high)
        self.assertEqual(verdict.half_sample_flags(['.03', '.01', '-.01', '.005']), high)
        # Break-even (1.25 * 0.8 compounds to exactly 1) is not positive.
        self.assertEqual(verdict.half_sample_flags(['.25', '-.2', '.05', '.05']), high)
        # An odd day joins the second half: [.1] then [-.1, .05] = 0.945.
        self.assertEqual(verdict.half_sample_flags(['.1', '-.1', '.05']), high)
        self.assertEqual(verdict.half_sample_flags(['.01', '-.005', '.02']), [])
        for invalid in ([], ['.01'], ['bad', '.01'], ['-1.5', '.01'], 'not-a-list', None):
            self.assertEqual(verdict.half_sample_flags(invalid), [], invalid)
        returns = ['.01', '.02'] * 30
        self.assertEqual(judge(returns=returns, flags=verdict.half_sample_flags(['-.01'] * 30 + ['.03'] * 30))['level'], verdict.FRAGILE_EDGE)

    def test_walk_forward_verdict_counts_evaluated_oos_closed_trades(self):
        returns = ['.001', '.002'] * 15

        def level(*folds):
            return oos_statistics_data(state(list(folds)))['verdict']['level']

        self.assertEqual(level(fold(0, 0, returns, trades=15), fold(1, 30, returns, trades=15)), verdict.STATISTICAL_EDGE)
        self.assertEqual(level(fold(0, 0, returns, trades=15), fold(1, 30, returns, trades=14)), verdict.INSUFFICIENT)
        # An unknown count anywhere in the merged folds fails closed, even when the known folds alone
        # already reach the minimum (so skipping or zeroing the unknown fold would wrongly pass).
        for bad in (None, -1, '15', True):
            self.assertEqual(level(fold(0, 0, returns, trades=30), fold(1, 30, returns, trades=bad)), verdict.INSUFFICIENT, bad)
        self.assertEqual(level(fold(0, 0, returns, trades=30), fold(1, 30, returns, trades=0)), verdict.STATISTICAL_EDGE)
        # A skipped fold contributes neither returns nor trades.
        skipped = fold(1, 30, returns, status='failed', trades=1000)
        self.assertEqual(level(fold(0, 0, returns * 2, trades=29), skipped), verdict.INSUFFICIENT)
        self.assertEqual(level(fold(0, 0, returns * 2, trades=30), skipped), verdict.STATISTICAL_EDGE)

    def test_display_names_the_closed_trade_shortfall_instead_of_days(self):
        many_days = ['.001', '.002'] * 50
        text = oos_statistics_text(state([fold(0, 0, many_days, trades=10), fold(1, 100, many_days, trades=10)]))
        verdict_line = text.splitlines()[1]
        trades = ui_text('walk_forward.verdict.insufficient.trades_explanation').format(20, 30)
        self.assertEqual(verdict_line, ui_text('walk_forward.verdict.line').format(ui_text('walk_forward.verdict.insufficient.name'), trades))
        self.assertNotIn(ui_text('walk_forward.verdict.insufficient.explanation'), text)
        self.assertNotIn(ui_text('walk_forward.verdict.recommended').format(30), text)
        unknown = oos_statistics_text(state([fold(0, 0, many_days, trades=None)]))
        self.assertIn(ui_text('walk_forward.verdict.trades_unknown').format(30), unknown)
        # A qualifying run states the rule it actually passed: four tests and at least 30 closed trades.
        edge = oos_statistics_text(state([fold(0, 0, many_days, trades=30)]))
        self.assertIn(ui_text('walk_forward.verdict.statistical_edge.explanation'), edge.splitlines()[1])
        self.assertIn('30', ui_text('walk_forward.verdict.statistical_edge.explanation'))
        # Too few days AND too few trades: the day-count explanation stays and the trade line follows it.
        both = oos_statistics_text(state([fold(0, 0, ['.001', '.002'] * 5, trades=2)]))
        self.assertIn(ui_text('walk_forward.verdict.insufficient.explanation'), both)
        self.assertIn(ui_text('walk_forward.verdict.insufficient.trades_explanation').format(2, 30), both)

    def test_display_shows_all_four_p_values_in_order(self):
        source = state([fold(0, 0, (['.012'] * 10 + ['-.008'] * 10) * 8, trades=80)])
        stats = oos_statistics_data(source)['stats']
        expected = ui_text('walk_forward.statistics.p_values').format(
            stats['p_value_t'], stats['p_value_bootstrap'], stats['p_value_t_hac'], stats['p_value_block_bootstrap']
        )
        self.assertIn(expected, oos_statistics_text(source).splitlines())
        self.assertEqual(len({stats[key] for key in verdict.P_VALUES}), 4)

    def test_robust_fields_missing_from_old_statistics_are_insufficient(self):
        for key in ('t_hac', 'p_value_t_hac', 'hac_lag', 'p_value_block_bootstrap', 'block_length'):
            stats = statistics()
            del stats[key]
            self.assertEqual(judge(stats)['level'], verdict.INSUFFICIENT, key)
        self.assertEqual(sig.P_VALUES, verdict.P_VALUES)
        self.assertEqual(sig.STATISTICS, ('n',) + verdict.STATISTICS)

    def test_display_top_unavailable_and_no_state_or_hash_writes(self):
        source = state([fold(0, 0, ['.001', '.002'] * 30)])
        source['state_hash'] = content_hash(source)
        before = canonical_json(source)
        before_hash = content_hash(source)
        text = oos_statistics_text(source)
        self.assertIn(ui_text('walk_forward.verdict.statistical_edge.name'), text.splitlines()[1])
        self.assertIn(ui_text('walk_forward.verdict.scope'), text)
        compact_walk_forward(source, 'test')
        self.assertEqual(canonical_json(source), before)
        self.assertEqual(content_hash(source), before_hash)
        for status in ('failed', 'interrupted', 'running', 'completed_with_errors'):
            source['status'] = status
            text = oos_statistics_text(source)
            self.assertEqual(text.splitlines()[1:], [ui_text('walk_forward.verdict.run_unavailable')])
            for name in verdict.NAMES:
                self.assertNotIn(name, text)
        text = oos_statistics_text(state([]))
        self.assertEqual(text.splitlines(), [ui_text('walk_forward.statistics.title'), ui_text('walk_forward.statistics.no_folds')])
        for name in verdict.NAMES:
            self.assertNotIn(name, text)

    def test_imports_are_stdlib_only_no_io_or_mutable_globals(self):
        tree = ast.parse((ROOT / 'quantlab/verdict.py').read_text(encoding='utf-8'))
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(imports, ['decimal'])
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n.value, (ast.Dict, ast.List, ast.Set)) for n in tree.body if isinstance(n, ast.Assign)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ('open', 'eval', 'exec', '__import__'))

    def test_real_selection_and_eligibility_identical_with_verdict(self):
        ranking = {'minimum': '0', 'min_trades': 1, 'max_drawdown_pct': '.1'}
        specs = ({'strategy_id': 'a'}, {'strategy_id': 'b'}, {'strategy_id': 'c'})
        plan = SimpleNamespace(folds=(wf.WalkForwardFold((0, 2), (2, 4), (4, 6)),), candidate_pool=specs, ranking=ranking)

        def run(with_verdict):
            selected = {'folds': [], 'experiment_id': 'synthetic'}

            def evaluate(index, role, split, spec):
                if with_verdict:
                    judge(statistics(mean='-.002', p='.5'))
                return {
                    'status': 'evaluated',
                    'result': {
                        'metrics': {'net_pnl': '-10' if spec['strategy_id'] == 'c' else '10', 'trade_count': 3, 'max_drawdown_pct': '.02'},
                        'result_hash': 'fixed',
                    },
                }

            with patch.object(wf, '_slice', return_value=SimpleNamespace(manifest={'data_hash': 'fixed'})):
                wf._score_walk_forward_folds(None, plan, selected, evaluate, lambda: None)
            summaries = [c['validation']['result'] for c in selected['folds'][0]['candidates']]
            eligible = [_eligible(summary, ranking) for summary in summaries]
            self.assertEqual(eligible, [True, True, False])
            self.assertEqual(selected['folds'][0]['selection']['pool_index'], 0)
            return canonical_json({'eligible': eligible, 'state': selected, 'state_hash': content_hash(selected)})

        self.assertEqual(run(False), run(True))
