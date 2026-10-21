"""Offline synthetic-only inference and fail-closed OOS projection evidence."""

import copy
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import random
import statistics
import shutil
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from desktop_strings import ui_text
from desktop_walk_forward import compact_walk_forward, oos_statistics_text
from quantlab.core import canonical_json
from quantlab import significance as sig

ROOT = Path(__file__).resolve().parents[1]
GOLDENS = json.loads((ROOT / 'tests/fixtures/significance_goldens.json').read_text(encoding='utf-8'))


@contextmanager
def journal_workspace():
    base = (ROOT / '.t-b2-work').resolve()
    root = base / uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        assert root.resolve().is_relative_to(base)
        shutil.rmtree(root)


def fold(index, start, values, status='evaluated'):
    rows = [{'trade_date': (date(2020, 1, 1) + timedelta(days=start + i)).isoformat(), 'return': value, 'reason': None} for i, value in enumerate(values)]
    return {'index': index, 'status': status, 'selection': None, 'candidates': [], 'oos': {'status': status, 'result': {'metrics': {'daily_returns': rows}}}}


def state(folds):
    return {
        'experiment_id': 'test',
        'status': 'completed',
        'binding': {'plan': {'candidate_pool': [], 'ranking': {}}, 'source_identity': 'synthetic'},
        'source_manifest': {'source_type': 'synthetic'},
        'summary': {},
        'elapsed_seconds': 0,
        'final_holdout_status': 'excluded_not_evaluated',
        'folds': folds,
        'final_holdout': {'sentinel': 987654321},
    }


class SignificanceTests(unittest.TestCase):
    def test_offline_literal_goldens_and_precision(self):
        self.assertEqual(GOLDENS['scipy_version'], '1.16.3')
        self.assertIn("alternative='greater'", GOLDENS['generating_script'])
        for case in GOLDENS['cases']:
            with self.subTest(n=case['n']):
                result = sig.mean_positive_test(case['returns'], n_bootstrap=100)
                self.assertEqual(result['n'], case['n'])
                self.assertAlmostEqual(float(result['p_value_t']), case['p_value_t'], delta=1e-6)
                self.assertAlmostEqual(float(result['t']), case['t'], delta=1e-6)
                for key in ('mean', 'sd', 't', 'p_value_t', 'p_value_bootstrap', 'ci_lower', 'ci_upper'):
                    self.assertIs(type(result[key]), Decimal)
                    self.assertEqual(result[key].as_tuple().exponent, -12)
                self.assertLessEqual(result['ci_lower'], result['ci_upper'])
        self.assertAlmostEqual(GOLDENS['cases'][0]['p_value_t'], 0.008609930703981776, delta=1e-15)
        self.assertAlmostEqual(GOLDENS['cases'][1]['p_value_t'], 0.1426067748492822, delta=1e-15)
        result = sig.mean_positive_test(GOLDENS['cases'][0]['returns'], n_bootstrap=5)
        self.assertAlmostEqual(float(result['mean']), 0.0010166666666666668, delta=1e-12)
        self.assertAlmostEqual(float(result['sd']), 0.003212748264715021, delta=1e-12)
        self.assertEqual(result['explanation'], ui_text('walk_forward.statistics.explanation'))

    def test_reproducibility_and_private_random(self):
        values = GOLDENS['cases'][1]['returns']
        before = random.getstate()
        first = sig.mean_positive_test(values)
        second = sig.mean_positive_test(values)
        self.assertEqual(canonical_json(first).encode(), canonical_json(second).encode())
        self.assertEqual(before, random.getstate())
        self.assertNotEqual(first['p_value_bootstrap'], sig.mean_positive_test(values, seed=42)['p_value_bootstrap'])

    def test_small_bootstrap_matches_independent_reference(self):
        values = [-0.03, 0.01, 0.04, 0.02, -0.01]
        observed = statistics.mean(values)
        centered = [value - observed for value in values]
        rng = random.Random(91)
        null_means = [math.fsum(rng.choices(centered, k=len(values))) / len(values) for _ in range(127)]
        p = sum(value >= observed for value in null_means) / 127
        result = sig.mean_positive_test(values, n_bootstrap=127, seed=91)
        self.assertAlmostEqual(float(result['p_value_bootstrap']), p, delta=1e-12)
        null_means.sort()
        for key, q in (('ci_lower', 0.025), ('ci_upper', 0.975)):
            position = 126 * q
            index = int(position)
            expected = observed + null_means[index] + (position - index) * (null_means[index + 1] - null_means[index])
            self.assertAlmostEqual(float(result[key]), expected, delta=1e-12)

    def test_missing_nonfinite_and_short_samples_are_atomic(self):
        for values in ([], ['.1'], ['.1', None, '.2'], ['.1', 'NaN'], ['Infinity', '0'], ['-Infinity', '0']):
            with self.subTest(values=values):
                result = sig.mean_positive_test(values)
                for key in sig.STATISTICS:
                    self.assertIsNone(result[key])
                    self.assertTrue(result[key + '_reason'])
                required = sig.required_observations(values)
                self.assertIsNone(required['required_observations'])
                self.assertTrue(required['required_observations_reason'])

    def test_zero_variance(self):
        for value in ('0.001', '0'):
            result = sig.mean_positive_test([value] * 60)
            for key in ('p_value_t', 'p_value_bootstrap'):
                self.assertIsNone(result[key])
                self.assertEqual(result[key + '_reason'], sig.ZERO_VARIANCE)
            self.assertIsNone(sig.required_observations([value] * 60)['required_observations'])

    def test_positive_zero_negative_means(self):
        scale = math.sqrt(59 / 60) * 0.01
        symmetric = [-scale, scale] * 30
        positive = [value + 0.005 for value in symmetric]
        for values, significant in ((positive, True), (symmetric, False)):
            result = sig.mean_positive_test(values)
            for key in ('p_value_t', 'p_value_bootstrap'):
                self.assertEqual(result[key] < Decimal('.05'), significant)
        self.assertEqual(sig.mean_positive_test(symmetric)['p_value_t'], Decimal('.500000000000'))
        self.assertGreater(sig.mean_positive_test([-value for value in positive])['p_value_t'], Decimal('.5'))

    def test_required_moment_rule_and_cap(self):
        for mean, sd, expected in (
            ('.001', '.01', 619),
            ('.005', '.01', 30),
            ('0', '.01', None),
            ('-.1', '.01', None),
            ('.1', '0', None),
            ('1e-9', '.01', None),
        ):
            result = sig.required_sample_size(mean, sd)
            self.assertEqual(result['required_observations'], expected)
            self.assertEqual(result['required_observations_reason'] is None, expected is not None)
        scale = math.sqrt(59 / 60) * 0.01
        values = [0.001 - scale, 0.001 + scale] * 30
        self.assertEqual(sig.required_observations(values)['required_observations'], 619)

    def test_cap_planning_and_large_repeated_sample(self):
        # Patch only expensive sampling to test cap arithmetic independently.
        with patch.object(sig, '_resample_means', side_effect=lambda values, mean, actual, rng: iter([0.0] * actual)):
            result = sig.mean_positive_test(['-.01', '.01'] * 500, n_bootstrap=100000)
            self.assertEqual(result['n_bootstrap_actual'], 50000)
            self.assertTrue(result['bootstrap_note'])
            self.assertEqual(sig.mean_positive_test(['0', '.01'], n_bootstrap=999)['n_bootstrap_actual'], 999)
        started = time.perf_counter()
        result = sig.mean_positive_test(['-.01', '.01'] * 50000)
        self.assertEqual(result['n_bootstrap_actual'], 1000)
        self.assertTrue(result['bootstrap_note'])
        self.assertLess(time.perf_counter() - started, 5)

    def test_pure_inputs_and_no_dependency_or_io(self):
        values = [Decimal(value) for value in GOLDENS['cases'][1]['returns']]
        before = copy.deepcopy(values)
        sig.mean_positive_test(values, n_bootstrap=100)
        sig.required_observations(values)
        self.assertEqual(values, before)
        source = (ROOT / 'quantlab/significance.py').read_text(encoding='utf-8')
        for forbidden in ('scipy', 'numpy', 'PySide', 'open(', 'Path(', 'time.', 'requests'):
            self.assertNotIn(forbidden, source)


class OosProjectionTests(unittest.TestCase):
    def test_real_synthetic_journal_and_hashes_remain_byte_identical(self):
        # Use the existing in-process synthetic scorer, never a subprocess/model.
        from quantlab.walk_forward import run_walk_forward, read_walk_forward_state

        # Reuse fixture helpers only for the synthetic journal case.
        from tests.test_walk_forward import inputs, fake_worker

        def worker(function, args, **kwargs):
            result = fake_worker(function, args, **kwargs)
            split = args[0].manifest['walk_forward_split']
            if split['role'] == 'oos':
                result['value']['metrics']['daily_returns'] = fold(split['fold'], split['fold'] * 30, GOLDENS['cases'][1]['returns'])['oos']['result'][
                    'metrics'
                ]['daily_returns']
            return result

        with journal_workspace() as root:
            data, plan = inputs()
            with patch('quantlab.walk_forward._run_bounded', side_effect=worker):
                run_walk_forward(data, plan=plan, output_dir=root / 'run', holdout_registry_path=root / 'registry.sqlite3')
            before = read_walk_forward_state(root / 'run')
            files = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            reference = before['experiment_id']
            result = compact_walk_forward(before, reference)
            self.assertIn(ui_text('walk_forward.statistics.title'), result['oos_statistics_text'])
            after = read_walk_forward_state(root / 'run')
            self.assertEqual(canonical_json(before), canonical_json(after))
            self.assertEqual(before['experiment_id'], after['experiment_id'])
            self.assertEqual(before['state_hash'], after['state_hash'])
            self.assertEqual(files, {path: path.read_bytes() for path in root.rglob('*') if path.is_file()})

    def test_merge_order_skips_and_atomic_rejection(self):
        first, second = fold(0, 0, ['.001', '-.001']), fold(1, 2, ['.002', '.003'])
        original = state([second, fold(2, 4, ['9'], 'evaluation_failed'), first])
        before = copy.deepcopy(original)
        merged = sig.merge_oos_daily_returns(original)
        self.assertEqual(merged['returns'], ['.001', '-.001', '.002', '.003'])
        self.assertEqual((merged['evaluated_folds'], merged['skipped_folds']), (2, 1))
        self.assertEqual(original, before)
        for bad in (state([first, fold(1, 1, ['.1'])]), state([]), state([fold(0, 0, [], 'evaluation_failed')])):
            result = sig.merge_oos_daily_returns(bad)
            self.assertIsNone(result['returns'])
            self.assertTrue(result['reason'])
        for rows in (None, {}, [], [{'trade_date': 'invalid', 'return': '.1'}]):
            bad = state([copy.deepcopy(first)])
            bad['folds'][0]['oos']['result']['metrics']['daily_returns'] = rows
            self.assertIsNone(sig.merge_oos_daily_returns(bad)['returns'])

    def test_ui_text_and_no_holdout_access(self):
        class GuardedState(dict):
            def get(self, key, default=None):
                if key.startswith('final_holdout') and key != 'final_holdout_status':
                    raise AssertionError('holdout read')
                return super().get(key, default)

            def __getitem__(self, key):
                if key.startswith('final_holdout') and key != 'final_holdout_status':
                    raise AssertionError('holdout read')
                return super().__getitem__(key)

        source = GuardedState(state([fold(0, 0, GOLDENS['cases'][0]['returns'])]))
        text = oos_statistics_text(source)
        for key in ('title', 'source', 'explanation'):
            self.assertIn(ui_text('walk_forward.statistics.' + key), text)
        self.assertIn('60', text)
        self.assertIn('Student t', text)
        self.assertNotIn('987654321', text)
        for invalid in (None, 'evaluated'):
            source['final_holdout_status'] = invalid
            self.assertIn(ui_text('walk_forward.statistics.holdout_unconfirmed'), oos_statistics_text(source))
        missing = state([fold(0, 0, ['.001', None])])
        self.assertIn(ui_text('walk_forward.statistics.missing_value'), oos_statistics_text(missing))
        constant = state([fold(0, 0, ['.001'] * 60)])
        self.assertIn(ui_text('walk_forward.statistics.zero_variance'), oos_statistics_text(constant))

    def test_twenty_fold_compaction_bounded_and_read_only(self):
        source = state([fold(i, i * 30, GOLDENS['cases'][1]['returns']) for i in range(20)])
        before = copy.deepcopy(source)
        result = compact_walk_forward(source, 'test')
        encoded = canonical_json(result)
        self.assertEqual(source, before)
        self.assertLess(len(encoded.encode()), 15000)
        self.assertNotIn('daily_returns', encoded)
        self.assertNotIn('987654321', result['oos_statistics_text'])

    def test_existing_panel_displays_precomputed_text_without_calculating(self):
        # Delay Qt to this display-only test; numerical tests remain Qt-free.
        from PySide6.QtWidgets import QApplication

        # Load the UI panel only for the display-only case.
        from desktop_pages.result_panels import WalkForwardResults

        app = QApplication.instance() or QApplication([])
        panel = WalkForwardResults()
        self.assertFalse(hasattr(panel, '_oos_statistics'))
        with patch('desktop_walk_forward.oos_statistics_text', side_effect=AssertionError('refresh computed stats')):
            panel.set_result({'oos_statistics_text': 'synthetic precomputed statistics'})
        self.assertEqual(panel._oos_statistics.text(), 'synthetic precomputed statistics')
        panel.set_result({})
        self.assertTrue(panel._oos_statistics.isHidden())
        panel.close()
        self.assertIsNotNone(app)
