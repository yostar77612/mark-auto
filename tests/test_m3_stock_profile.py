"""Append-only current source identity and exact historical source preservation."""

import ast
import copy
import hashlib
from pathlib import Path
import unittest

from quantlab import saved_candidate_pool as pools
from quantlab.core import content_hash, to_dict
from quantlab.research_core.domain.saved_pool import SavedCandidatePoolError
from tests.m3_stock_source_fixtures import prior_source_bytes, reviewed_prior_source

ROOT = Path(__file__).parents[1]
PROFILE = pools.STOCK_SIGNAL_PROFILE_V1


def blocks(raw):
    lines = raw.splitlines(keepends=True)
    return {
        node.targets[0].id: b''.join(lines[node.lineno - 1 : node.end_lineno])
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'freeze'
    }


class StockProfileTests(unittest.TestCase):
    def test_all_thirty_historical_literal_blocks_are_byte_identical(self):
        before = blocks(prior_source_bytes('quantlab/saved_candidate_pool.py'))
        current = blocks((ROOT / 'quantlab/saved_candidate_pool.py').read_bytes())
        self.assertEqual(len(before), 30)
        self.assertEqual(set(current), set(before) | {'STOCK_SIGNAL_PROFILE_V1'})
        for name, raw in before.items():
            self.assertIn(current[name], (raw, raw.replace(b'\n', b'\r\n')))
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 31)
        self.assertIs(pools.SUPPORTED_PRODUCERS[-1], PROFILE)

    def test_exact_current_profile_changes_only_authorized_source_identities(self):
        self.assertEqual(content_hash(PROFILE), '2adad40bc8d95363c6ec121756b6621f457df416fa10519a7d8a95acd82480e9')
        previous = pools.CORE_SPLIT_SIWC_PROFILE_V1
        restored = to_dict(PROFILE)
        restored['protocol'] = previous['protocol']
        for name in ('core.py', 'backtest.py'):
            restored['engine_source_hashes'][name] = previous['engine_source_hashes'][name]
            restored['result_source_hashes'][name] = previous['result_source_hashes'][name]
            for index, variant in enumerate(restored['result_source_hash_variants']):
                variant[name] = previous['result_source_hash_variants'][index][name]
        # The prospective-E1 reservation change (research.py) is the one other reviewed source change.
        restored['engine_source_hashes']['research.py'] = previous['engine_source_hashes']['research.py']
        self.assertEqual(restored, previous)
        for name, expected in PROFILE['engine_source_hashes'].items():
            self.assertEqual(content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')), expected)
        for index, variant in enumerate(PROFILE['result_source_hash_variants']):
            for name, expected in variant.items():
                raw = (ROOT / 'quantlab' / name).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(hashlib.sha256(raw.replace(b'\n', b'\r\n') if index else raw).hexdigest(), expected)

    def test_current_and_historical_binding_select_only_their_own_profile(self):
        for profile in (PROFILE, pools.CORE_SPLIT_SIWC_PROFILE_V1):
            for mode in ('fixture', 'openai_compatible'):
                binding = {
                    'engine_source_hashes': to_dict(profile['engine_source_hashes']),
                    'prompt_template_hash': profile['prompt_template_hash'],
                    'provider': {'mode': mode},
                }
                self.assertIs(pools._select_producer(binding), profile)
                for name in ('core.py', 'backtest.py'):
                    changed = copy.deepcopy(binding)
                    other = pools.CORE_SPLIT_SIWC_PROFILE_V1 if profile is PROFILE else PROFILE
                    changed['engine_source_hashes'][name] = other['engine_source_hashes'][name]
                    with self.assertRaises(SavedCandidatePoolError):
                        pools._select_producer(changed)

    def test_projection_rejects_any_unreviewed_current_source_byte(self):
        for name in ('core.py', 'backtest.py', 'saved_candidate_pool.py'):
            path = 'quantlab/' + name
            current = (ROOT / path).read_bytes()
            prior = reviewed_prior_source(path, current).replace(b'\r\n', b'\n')
            self.assertEqual(prior, prior_source_bytes(path))
            with self.assertRaises(ValueError):
                reviewed_prior_source(path, current + b'\n# unreviewed\n')


if __name__ == '__main__':
    unittest.main()
