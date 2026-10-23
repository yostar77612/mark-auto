"""Structural budgets and locked source guards (checkout newline independent) for T11."""

import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'quantlab/saved_candidate_pool.py': 'admit_saved_campaign_pool',
    'quantlab/desktop_runtime.py': 'JobManager.start',
    'quantlab/walk_forward.py': 'run_walk_forward',
    'quantlab/paper.py': '_reduce',
    'quantlab/chart_data.py': 'aggregate_bars',
}


class FunctionLengthTests(unittest.TestCase):
    def test_five_function_budgets(self):
        for filename, qualified in TARGETS.items():
            with self.subTest(function=qualified):
                tree = ast.parse((ROOT / filename).read_text(encoding='utf-8-sig'))
                parts = qualified.split('.')
                for name in parts:
                    tree = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)
                self.assertLessEqual(tree.end_lineno - tree.lineno + 1, 80)

    def test_locked_source_text(self):
        for filename, expected in LOCKED_HASHES.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_text(encoding='utf-8-sig').encode('utf-8')).hexdigest(), expected)


LOCKED_HASHES = {
    'quantlab/research.py': '25902491cebcdd71359648cc6eaa0eea685b1082240566d74ada29d9139861d7',
    'quantlab/provider.py': 'c15c043156de1d6bf4679034328789b18d171344b56a85432a1d56d42a4fd79a',
    'quantlab/core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
    'quantlab/strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
    'quantlab/backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6',
    'quantlab/data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
    'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
    'desktop_chatgpt_provider.py': '0189228f63e44d57e4d3a11832178b49cb0d907d332d557c6c99bb8460d613ca',
}
