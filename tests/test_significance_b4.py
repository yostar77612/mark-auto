"""Synthetic-only fixed-fold Welch decline evidence."""

import copy
from decimal import Decimal
import inspect
import json
import math
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from desktop_strings import ui_text
from desktop_walk_forward import compact_walk_forward, oos_statistics_text
from quantlab import significance as sig
from quantlab.core import canonical_json
from tests.test_significance_b2 import fold, state

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / 'tests/fixtures/welch_goldens.json').read_text(encoding='utf-8'))


class WelchDeclineTests(unittest.TestCase):
    def test_offline_golden_and_mirrored_tail(self):
        self.assertEqual(GOLDEN['scipy_version'], '1.16.3')
        result = sig.welch_decline_test(GOLDEN['early'], GOLDEN['recent'])
        for key in ('t', 'df', 'p_value'):
            self.assertAlmostEqual(float(result[key]), GOLDEN[key], delta=1e-6)
        self.assertAlmostEqual(float(result['p_value']), 0.0030299809388781, delta=1e-6)
        reverse = sig.welch_decline_test(GOLDEN['recent'], GOLDEN['early'])
        self.assertAlmostEqual(float(reverse['p_value']), 0.9969700190611219, delta=1e-6)
        self.assertEqual(reverse['classification'], 'significant_increase')
        self.assertEqual(result['classification'], 'significant_decline')
        self.assertEqual(result['p_value'], reverse['p_value_increase'])

    def test_deterministic_effect_and_display_states(self):
        scale = math.sqrt(39 / 40) * 0.01
        centered = [-scale, scale] * 20
        early = [x + 0.005 for x in centered]
        recent = [x - 0.005 for x in centered]
        for left, right, classification, phrase in (
            (early, recent, 'significant_decline', '\u986f\u8457\u4e0b\u964d'),
            (recent, early, 'significant_increase', '\u975e\u672a\u4f86\u4fdd\u8b49'),
            (centered, centered, 'no_significant_difference', '\u4e0d\u7b49\u65bc\u6c92\u6709\u8b8a\u5316'),
        ):
            result = sig.welch_decline_test(left, right)
            self.assertEqual(result['classification'], classification)
            source = state([fold(0, 0, left), fold(1, 40, right)])
            text = oos_statistics_text(source)
            self.assertIn(phrase, text)
            self.assertEqual(len(text.splitlines()), 12)
            self.assertEqual(text.count(ui_text('walk_forward.decline.line').split('{0}')[0]), 1)
            if classification == 'significant_decline':
                self.assertLess(result['p_value'], Decimal('.05'))

    def test_precision_repeatability_purity_and_no_mutation(self):
        source = state([fold(0, 0, GOLDEN['early']), fold(1, 40, GOLDEN['recent'])])
        before, rng = copy.deepcopy(source), random.getstate()
        with patch.object(sig, '_t_tail', wraps=sig._t_tail) as tail:
            result = sig.oos_decline_test(source)
            self.assertEqual(tail.call_count, 2)
        for key in ('t', 'df', 'p_value', 'p_value_increase'):
            self.assertIs(type(result[key]), Decimal)
            self.assertEqual(result[key].as_tuple().exponent, -12)
        self.assertEqual(canonical_json(result).encode(), canonical_json(sig.oos_decline_test(source)).encode())
        self.assertEqual(source, before)
        self.assertEqual(random.getstate(), rng)
        compact = compact_walk_forward(source, 'test')
        self.assertNotIn('daily_returns', canonical_json(compact))
        self.assertNotIn('p_value_increase', canonical_json(compact))
        self.assertEqual(source, before)

    def test_fixed_split_membership_and_shuffled_invariance(self):
        self.assertEqual(list(inspect.signature(sig.welch_decline_test).parameters), ['early', 'recent'])
        self.assertEqual(list(inspect.signature(sig.split_oos_daily_returns).parameters), ['state'])
        for k in (2, 3, 4, 5):
            folds = [fold(i, i * 3, [str(i), str(i + 1)]) for i in range(k)]
            ordered = sig.split_oos_daily_returns(state(folds))
            self.assertEqual(ordered['early_indices'], list(range(k // 2)))
            self.assertEqual(ordered['recent_indices'], list(range(k // 2, k)))
            self.assertEqual(ordered['early'], [str(x) for i in range(k // 2) for x in (i, i + 1)])
            self.assertEqual(ordered['recent'], [str(x) for i in range(k // 2, k) for x in (i, i + 1)])
            self.assertEqual(ordered, sig.split_oos_daily_returns(state(folds[::-1])))

    def test_atomic_invalid_samples_with_reasons(self):
        for early, recent in (
            ([], [1, 2]),
            ([1], [1, 2]),
            ([1, None], [1, 2]),
            ([1, 2], [None, 1]),
            ([1, 1], [2, 2]),
            (['NaN', 1], [1, 2]),
            ([1, 2], ['Infinity', 2]),
        ):
            result = sig.welch_decline_test(early, recent)
            for key in ('classification', 'p_value', 'p_value_increase', 't', 'df'):
                self.assertIsNone(result[key])
                self.assertTrue(result[key + '_reason'])
        self.assertIsNotNone(sig.welch_decline_test([1, 1], [1, 2])['p_value'])

    def test_merge_validation_skips_and_holdout_never_read(self):
        class Unreadable(dict):
            def get(self, *args):
                raise AssertionError('excluded data read')

        source = state([fold(0, 0, [1, 2]), fold(1, 3, [1, 2]), {'index': 2, 'status': 'failed', 'oos': {'status': 'failed'}}])
        source['final_holdout'] = Unreadable()
        self.assertIsNotNone(sig.oos_decline_test(source)['classification'])
        source['folds'][1] = fold(1, 1, [1, 2])
        self.assertEqual(sig.oos_decline_test(source)['reason'], 'dates_not_strictly_increasing')
        self.assertIsNone(sig.split_oos_daily_returns(source)['early'])
        for folds in ([], [fold(0, 0, [1, 2])], [fold(0, 0, [1]), fold(1, 2, [1, 2])]):
            result = sig.oos_decline_test(state(folds))
            self.assertIsNone(result['classification'])
            self.assertTrue(result['reason'])
            self.assertEqual(len(oos_statistics_text(state(folds)).splitlines()), 2 if not folds else 13)


if __name__ == '__main__':
    unittest.main()
