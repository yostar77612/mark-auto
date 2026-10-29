"""Independent hand arithmetic for market-indicators-b3-v1; tolerance 1e-24."""

from decimal import Decimal as D
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from quantlab import indicators as ta


class IndicatorExpansionTests(unittest.TestCase):
    def assert_series(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for value, golden in zip(actual, expected):
            if golden is None:
                self.assertIsNone(value)
            else:
                self.assertIsInstance(value, D)
                self.assertLessEqual(abs(value - D(golden)), D('1e-24'))

    def test_hand_goldens(self):
        # TR = 2,3,4,2; SMA2=2.5; Wilder next=(2.5+4)/2=3.25, then2.625.
        self.assert_series(ta.atr([11, 13, 16, 16], [9, 11, 12, 14], [10, 12, 15, 15], period=2), [None, '2.5', '3.25', '2.625'])
        # Midpoints=10,12,14; ATR2=2.5,3.25; multiplier1 lower=9.5,10.75.
        self.assert_series(ta.supertrend([11, 13, 16], [9, 11, 12], [10, 12, 15], period=2, multiplier=1), [None, '9.5', '10.75'])
        # Rising seed=low0=9; next 9+.02*(13-9), clamped to low0=9;
        # new extreme16 raises AF to.04; next9+.04*(16-9)=9.28.
        self.assert_series(ta.sar([11, 13, 16, 17], [9, 11, 12, 14], [10, 12, 15, 16]), [None, '9', '9', '9.28'])
        # Initial0, up adds5, equal adds0, down subtracts2, zero volume adds0.
        self.assert_series(ta.obv([10, 11, 11, 9, 10], [3, 5, 8, 2, 0]), ['0', '5', '5', '3', '3'])
        # SMA2=15,25; envelope10% => upper16.5,27.5; lower13.5,22.5.
        bands = ta.ma_channel([10, 20, 30], period=2, percent=10)
        for key, expected in {'middle': [None, '15', '25'], 'upper': [None, '16.5', '27.5'], 'lower': [None, '13.5', '22.5']}.items():
            self.assert_series(bands[key], expected)

    def calls(self, h, l, c, v):
        return [
            (ta.atr, (h, l, c), {'period': 3}),
            (ta.supertrend, (h, l, c), {'period': 3}),
            (ta.sar, (h, l, c), {}),
            (ta.obv, (c, v), {}),
            (ta.ma_channel, (c,), {'period': 3}),
        ]

    def test_every_prefix_and_future_mutation(self):
        rng = random.Random(310)
        c = [D(rng.randrange(10, 50)) for _ in range(25)]
        h, l, v = [x + 2 for x in c], [x - 2 for x in c], [rng.randrange(10) for _ in c]
        for fn, args, kwargs in self.calls(h, l, c, v):
            full = fn(*args, **kwargs)
            for n in range(1, len(c) + 1):
                expected = {k: x[:n] for k, x in full.items()} if isinstance(full, dict) else full[:n]
                self.assertEqual(fn(*(x[:n] for x in args), **kwargs), expected)
                mutated = [x[:n] + [item + 1 for item in x[n:]] for x in args]
                out = fn(*mutated, **kwargs)
                self.assertEqual({k: x[:n] for k, x in out.items()} if isinstance(out, dict) else out[:n], expected)

    def test_warmup_gaps_flat_and_zero_volume(self):
        for fn, args, kwargs in self.calls([2] * 8, [2] * 8, [2] * 8, [0] * 8):
            out = fn(*args, **kwargs)
            series = out['middle'] if isinstance(out, dict) else out
            count = {ta.atr: 2, ta.supertrend: 2, ta.sar: 1, ta.obv: 0, ta.ma_channel: 2}[fn]
            self.assertEqual(next(i for i, x in enumerate(series) if x is not None), count)
            gap_args = [x[:3] + [None] + x[4:] for x in args]
            gap = fn(*gap_args, **kwargs)
            gap = gap['middle'] if isinstance(gap, dict) else gap
            self.assertEqual(gap[3 : 4 + count], (None,) * (count + 1))
        self.assertEqual(ta.atr([2] * 4, [2] * 4, [2] * 4, period=2), (None, D(0), D(0), D(0)))
        self.assertEqual(ta.obv([1, 2, 1], [0, 0, 0]), (D(0),) * 3)

    def test_invalid_and_resource_limits(self):
        for fn, args, kwargs in self.calls([2] * 4, [1] * 4, [2] * 4, [3] * 4):
            for bad in (True, float('nan'), float('inf')):
                for index in range(len(args)):
                    invalid = list(args)
                    invalid[index] = [bad] * 4
                    with self.assertRaises(ValueError):
                        fn(*invalid, **kwargs)
            with patch.object(ta, 'MAX_OBSERVATIONS', 3), self.assertRaises(ta.IndicatorResourceLimitError):
                fn(*args, **kwargs)
            with self.assertRaises(TypeError):
                fn(None, *args[1:], **kwargs)
            if 'period' in kwargs:
                for bad in (0, -1, True, None):
                    with self.assertRaises(ValueError):
                        fn(*args, period=bad)
        for fn in (ta.atr, ta.supertrend, ta.sar):
            with self.assertRaises(ValueError):
                fn([1], [2], [1])
            with self.assertRaises(ValueError):
                fn([2], [], [1])
        with self.assertRaises(ValueError):
            ta.obv([1], [])
        with self.assertRaises(ValueError):
            ta.obv([1], [-1])

    def test_version_contract(self):
        contract = Path('docs/agent/IMPLEMENTATION_CONTRACTS.md').read_text(encoding='utf-8')
        for fn in (ta.atr, ta.supertrend, ta.sar, ta.obv, ta.ma_channel):
            self.assertIn('market-indicators-b3-v1', fn.__doc__)
            self.assertIn(fn.__name__, contract)
        self.assertIn('market-indicators-b3-v1', contract)

    def test_default_and_unit_period_warmups(self):
        for fn, count in ((ta.atr, 13), (ta.supertrend, 9), (ta.ma_channel, 19)):
            args = ([2] * 25,) if fn is ta.ma_channel else ([2] * 25, [2] * 25, [2] * 25)
            for kwargs, expected in (({}, count), ({'period': 1}, 0), ({'period': 5}, 4)):
                out = fn(*args, **kwargs)
                series = out['middle'] if isinstance(out, dict) else out
                self.assertEqual(series[:expected], (None,) * expected)
                self.assertIsNotNone(series[expected])

    def test_parameters_and_keyword_volume_bound(self):
        for fn, args, parameter in (
            (ta.supertrend, ([2], [1], [2]), 'multiplier'),
            (ta.sar, ([2], [1], [2]), 'step'),
            (ta.sar, ([2], [1], [2]), 'maximum'),
            (ta.ma_channel, ([2],), 'percent'),
        ):
            for bad in (None, True, float('nan'), float('inf'), -1):
                with self.assertRaises(ValueError):
                    fn(*args, **{parameter: bad})
        with patch.object(ta, 'MAX_OBSERVATIONS', 2), self.assertRaises(ta.IndicatorResourceLimitError):
            ta.obv(closes=[1], volumes=iter([1, 2, 3]))

    def test_no_dynamic_code_and_ui_catalog(self):
        import ast
        from tests.test_no_hardcoded_ui_text import hardcoded_ui_text

        for filename in ('quantlab/indicators.py', 'desktop_app/features/market/dashboard.py', 'desktop_app/strings/catalog.py'):
            source = Path(filename).read_text(encoding='utf-8')
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ('eval', 'exec', 'compile'))
            if filename == 'desktop_app/features/market/dashboard.py':
                self.assertEqual(hardcoded_ui_text(source), [])
