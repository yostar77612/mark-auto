"""Qt-free, constant-boundary checks for descriptive sample warnings."""

import unittest

from quantlab.backtest_summary import MIN_SAMPLE_BARS, MIN_SAMPLE_TRADES, warning_keys


class BacktestSummaryPolicyTests(unittest.TestCase):
    def test_short_and_long_samples(self):
        self.assertEqual(warning_keys(1, 1, 1), ('backtest.summary.sample_short',))
        self.assertEqual(warning_keys(MIN_SAMPLE_BARS, MIN_SAMPLE_TRADES, MIN_SAMPLE_TRADES), ())
        self.assertEqual(warning_keys(MIN_SAMPLE_BARS - 1, MIN_SAMPLE_TRADES, 1), ('backtest.summary.sample_short',))
        self.assertEqual(warning_keys(MIN_SAMPLE_BARS, MIN_SAMPLE_TRADES - 1, 1), ('backtest.summary.sample_short',))

    def test_zero_closed_trades_independent_of_sample(self):
        self.assertEqual(warning_keys(0, 0, 0), ('backtest.summary.sample_short', 'backtest.summary.no_closed_trades'))
        self.assertEqual(warning_keys(MIN_SAMPLE_BARS, MIN_SAMPLE_TRADES, 0), ('backtest.summary.no_closed_trades',))
        self.assertEqual(warning_keys(MIN_SAMPLE_BARS, MIN_SAMPLE_TRADES, 1), ())
