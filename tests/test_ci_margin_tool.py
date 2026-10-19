"""Pure arithmetic checks for the opt-in CI margin tool; it never spawns processes here."""

import unittest

from tools.measure_ci_margin import BUDGETS, headroom, summarize


class MarginToolTests(unittest.TestCase):
    def test_summary_and_headroom(self):
        self.assertEqual(summarize([3, 1, 2]), {'median': 2, 'min': 1.0, 'max': 3.0, 'n': 3})
        self.assertEqual(headroom(0.5, 10.0), 20.0)
        for bad in (0, -1, None, '1', True):
            self.assertIsNone(headroom(bad, 10.0))
        with self.assertRaises(ValueError):
            summarize([])

    def test_budgets_are_unchanged_reference_values(self):
        self.assertEqual(BUDGETS, {'paper_diagnostics_seconds': 10.0, 'smoke_seconds': 40.0})


if __name__ == '__main__':
    unittest.main()
