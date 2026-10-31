"""Exact new identity and immutable historical producers across the core split."""

from quantlab.research_core.domain import saved_pool


import ast
import copy
import hashlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from quantlab import saved_candidate_pool as pools
from quantlab.assistant.adapters.chatgpt.provenance import implementation_provenance
from quantlab.assistant.domain.source_components import SOURCE_COMPONENTS
from quantlab.core import content_hash, to_dict
from tests.core_split_source_fixtures import CURRENT_SOURCES, layered_source_bytes

ROOT = Path(__file__).resolve().parents[1]
PROFILE = pools.CORE_SPLIT_SIWC_PROFILE_V1


def binding(index=0):
    item = to_dict(PROFILE['chatgpt_plan_implementations'][index])
    descriptor = {key: value for key, value in item.items() if key != 'dependency_targets'}
    descriptor['dependency_target'] = item['dependency_targets'][0]
    return {
        'engine_source_hashes': to_dict(PROFILE['engine_source_hashes']),
        'prompt_template_hash': PROFILE['prompt_template_hash'],
        'provider': {'mode': 'chatgpt_plan', 'descriptor': descriptor},
    }


def frozen_blocks(raw):
    lines = raw.splitlines(keepends=True)
    return {
        node.targets[0].id: b''.join(lines[node.lineno - 1 : node.end_lineno])
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'freeze'
    }


class CoreSplitProfileTests(unittest.TestCase):
    def test_exact_new_profile_and_complete_source_set(self):
        self.assertEqual(content_hash(PROFILE), '556e130985bac86253a10d22c68a171e06fa169ca1f6c254384db61e6ac1b2c4')
        self.assertEqual(dict(SOURCE_COMPONENTS), CURRENT_SOURCES)
        self.assertEqual(len(SOURCE_COMPONENTS), len(CURRENT_SOURCES))
        self.assertEqual(PROFILE['protocol'], 'mark_auto_0_2_2_campaign_core_split_siwc_v1')
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 30)
        self.assertIs(pools.SUPPORTED_PRODUCERS[-1], PROFILE)
        self.assertEqual(PROFILE['provider_modes'], ['fixture', 'openai_compatible', 'chatgpt_plan'])
        for mode in ('fixture', 'openai_compatible'):
            value = binding()
            value['provider'] = {'mode': mode}
            self.assertIs(pools._select_producer(value), PROFILE)
        for index, implementation in enumerate(PROFILE['chatgpt_plan_implementations']):
            self.assertEqual(set(implementation['source_sha256']), set(CURRENT_SOURCES))
            for key, filename in CURRENT_SOURCES.items():
                raw = (ROOT / filename).read_bytes().replace(b'\r\n', b'\n')
                if index and key in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
                    raw = raw.replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), implementation['source_sha256'][key], filename)
            for target in implementation['dependency_targets']:
                value = binding(index)
                value['provider']['descriptor']['dependency_target'] = target
                self.assertIs(pools._select_producer(value), PROFILE)

    def test_actual_runtime_identity_selects_new_profile(self):
        versions = PROFILE['chatgpt_plan_implementations'][0]['dependency_versions']
        with patch('importlib.metadata.version', side_effect=versions.__getitem__):
            actual = implementation_provenance()
        value = binding()
        value['provider']['descriptor'] = actual
        self.assertIs(pools._select_producer(value), PROFILE)
        from quantlab.research import _validated_provider_descriptor

        self.assertEqual(_validated_provider_descriptor({**actual, 'version': 1}), {**actual, 'version': 1})

    def test_engine_result_and_receipt_source_identity(self):
        expected_keys = {'research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py', 'research_core/domain/receipts.py'}
        self.assertEqual(set(PROFILE['engine_source_hashes']), expected_keys)
        for name, expected in PROFILE['engine_source_hashes'].items():
            raw = (ROOT / 'quantlab' / name).read_bytes().replace(b'\r\n', b'\n')
            for body in (raw, raw.replace(b'\n', b'\r\n')):
                with io.TextIOWrapper(io.BytesIO(body), encoding='utf-8') as stream:
                    self.assertEqual(content_hash(stream.read()), expected)
        previous = pools.LAYERED_PATHS_SIWC_PROFILE_V1
        self.assertEqual(PROFILE['result_source_hashes'], previous['result_source_hashes'])
        self.assertEqual(PROFILE['result_source_hash_variants'], previous['result_source_hash_variants'])
        actual_results = {name: hashlib.sha256((ROOT / 'quantlab' / name).read_bytes()).hexdigest() for name in PROFILE['result_source_hashes']}
        self.assertIn(actual_results, PROFILE['result_source_hash_variants'])
        original = layered_source_bytes('quantlab/research.py').decode()
        current = (ROOT / 'quantlab/research_core/domain/receipts.py').read_text(encoding='utf-8')
        extract = lambda text: next(
            ast.get_source_segment(text, node)
            for node in ast.parse(text).body
            if isinstance(node, ast.FunctionDef) and node.name == '_validated_receipt_snapshot'
        )
        self.assertEqual(extract(original), extract(current))
        import quantlab.research as research
        from quantlab.research_core.domain.receipts import _validated_receipt_snapshot

        self.assertIs(research._validated_receipt_snapshot, _validated_receipt_snapshot)

    def test_historical_blocks_are_byte_identical_and_one_byte_mutation_fails(self):
        baseline = frozen_blocks(layered_source_bytes('quantlab/saved_candidate_pool.py'))
        current = frozen_blocks((ROOT / 'quantlab/saved_candidate_pool.py').read_bytes())
        self.assertEqual(len(baseline), 29)
        self.assertEqual(set(current), set(baseline) | {'CORE_SPLIT_SIWC_PROFILE_V1'})
        for name, block in baseline.items():
            with self.subTest(name=name):
                allowed = (block, block.replace(b'\n', b'\r\n'))
                self.assertIn(current[name], allowed)
                mutated = current[name].replace(b'protocol', b'protocoL', 1)
                self.assertNotIn(mutated, allowed)

    def test_tampered_missing_mixed_components_and_targets_fail_closed(self):
        for index in (0, 1):
            value = binding(index)
            for key in CURRENT_SOURCES:
                for mutation in ('tamper', 'missing'):
                    changed = copy.deepcopy(value)
                    sources = changed['provider']['descriptor']['source_sha256']
                    if mutation == 'missing':
                        del sources[key]
                    else:
                        sources[key] = 'f' * 64
                    with self.subTest(index=index, key=key, mutation=mutation), self.assertRaises(saved_pool.SavedCandidatePoolError):
                        pools._select_producer(changed)
            changed = copy.deepcopy(value)
            changed['provider']['descriptor']['source_sha256']['desktop_chatgpt_auth.py'] = PROFILE['chatgpt_plan_implementations'][1 - index]['source_sha256'][
                'desktop_chatgpt_auth.py'
            ]
            with self.assertRaises(saved_pool.SavedCandidatePoolError):
                pools._select_producer(changed)
            for target in ('linux-cp313-x86_64', 'windows-cp314-amd64', 'linux-cp311-x86_64' if index else 'unknown'):
                changed = copy.deepcopy(value)
                changed['provider']['descriptor']['dependency_target'] = target
                with self.assertRaises(saved_pool.SavedCandidatePoolError):
                    pools._select_producer(changed)
            changed = copy.deepcopy(value)
            changed['engine_source_hashes']['research_core/domain/receipts.py'] = 'f' * 64
            with self.assertRaises(saved_pool.SavedCandidatePoolError):
                pools._select_producer(changed)


if __name__ == '__main__':
    unittest.main()
