"""Synthetic-only B3 ordering, pure output and selection-isolation evidence."""

import ast
import copy
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop_strings import ui_text
from desktop_walk_forward import compact_walk_forward, oos_statistics_text
from quantlab import significance as sig, verdict
from quantlab.core import canonical_json, content_hash
from quantlab.research import _eligible
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
        for key in ('p_value_t', 'p_value_bootstrap'):
            stats = statistics()
            stats[key] = Decimal('.05')
            self.assertEqual(judge(stats, flags=high)['level'], verdict.LUCK_SUSPECTED)

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
            self.assertEqual(context.flags, before_flags)
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
