"""Literal scalar-dispatch provenance; synthetic receipts only, no model calls."""

import hashlib
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.saved_pool_fixtures import make_saved_source, make_chatgpt_source
from tests.test_subscription_producer_profile import binding

TRANSPORT = pools.SCALAR_TRANSPORT_PROFILE_V1
CHATGPT = pools.SCALAR_SIWC_ANALYSIS_PROFILE_V1


class ScalarProducerProfileTests(unittest.TestCase):
    def admit(self, folder, reference, original):
        return pools.admit_saved_campaign_pool(
            source_campaign_dir=folder,
            source_campaign_ref=reference,
            original_dataset=original,
            original_dataset_ref='explicit-generated-fixture',
            first_training_timestamp=max(bar.end for bar in original.bars) + timedelta(days=1),
            authoritative_registry_path=folder.parent / 'source-registry.sqlite3',
        )

    def test_all_seven_historical_profiles_keep_exact_identity(self):
        expected = [
            '97ef1ebf0e68ed6d7c5714caa806ece5b53592c984d0058ac8a1d73c06a419a5',
            '2c7655ab89a8beaf48e98105c85a2dd5860f1d41418e32d1452e7218ab620f26',
            'ce3b2af865ea0338575c065b988a64ebcd4974e58617a93779e6edb684ec37de',
            '346eceee2a55514c22a32ae028402c8a74c9b52ab44befa0f90608ae68e549be',
            'e86f5b691ea3b0c015f0354ca2d6ec0b49c6300c25b62255b4f8a9da13f2b55e',
            'b4b257c6ab32da8631a8ef82ad4244f6f757c27a78246f96544649738009c2ea',
            'e14aba96d7c734c46f0713a7bedf2be5d33e4ff50bba1c60ed9a447f380af4a1',
        ]
        self.assertEqual([content_hash(p) for p in pools.SUPPORTED_PRODUCERS[:7]], expected)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[7:9], (TRANSPORT, CHATGPT))

    def test_new_literals_match_exact_engine_and_lf_crlf_results(self):
        root = Path(__file__).resolve().parents[1] / 'quantlab'
        for profile in (TRANSPORT, CHATGPT):
            # This exact scalar profile predates the reviewed worker cleanup.
            self.assertEqual(profile['engine_source_hashes']['research.py'], 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a')
            self.assertEqual(
                {
                    name: content_hash((root / name).read_text(encoding='utf-8'))
                    for name in profile['engine_source_hashes']
                    if name not in ('research.py', 'backtest.py')
                },
                {name: digest for name, digest in profile['engine_source_hashes'].items() if name not in ('research.py', 'backtest.py')},
            )
            self.assertEqual(profile['engine_source_hashes']['backtest.py'], '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91')
            for index, hashes in enumerate(profile['result_source_hash_variants']):
                for name, digest in hashes.items():
                    if name == 'backtest.py':
                        self.assertEqual(
                            digest,
                            (
                                '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02',
                                '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575',
                            )[index],
                        )
                        continue
                    raw = (root / name).read_bytes().replace(b'\r\n', b'\n')
                    if index:
                        raw = raw.replace(b'\n', b'\r\n')
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            with self.assertRaises(TypeError):
                profile['engine_source_hashes']['core.py'] = 'f' * 64
        self.assertEqual(TRANSPORT['provider_modes'], ['fixture', 'openai_compatible'])
        self.assertNotIn('chatgpt_plan_implementations', TRANSPORT)
        self.assertEqual(CHATGPT['provider_modes'], ['chatgpt_plan'])
        self.assertEqual(CHATGPT['chatgpt_plan_implementations'], pools.SIWC_ANALYSIS_CAPABLE_PROFILE_V1['chatgpt_plan_implementations'])

    def test_new_chatgpt_selects_only_current_exact_descriptors(self):
        for index, variant in enumerate(CHATGPT['chatgpt_plan_implementations']):
            for target in variant['dependency_targets']:
                item = binding(CHATGPT, index, target)
                self.assertIs(pools._select_producer(item), CHATGPT)
                with patch.object(pools, 'SUPPORTED_PRODUCERS', tuple(reversed(pools.SUPPORTED_PRODUCERS))):
                    self.assertIs(pools._select_producer(item), CHATGPT)
            bad = binding(CHATGPT, index)
            bad['provider']['descriptor']['source_sha256'] = to_dict(
                pools.SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1['chatgpt_plan_implementations'][index]['source_sha256']
            )
            with self.assertRaises(pools.SavedCandidatePoolError):
                pools._select_producer(bad)
            for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
                bad = binding(CHATGPT, index)
                bad['provider']['descriptor']['source_sha256'][name] = CHATGPT['chatgpt_plan_implementations'][1 - index]['source_sha256'][name]
                with self.assertRaises(pools.SavedCandidatePoolError):
                    pools._select_producer(bad)
        for index, target in [(0, 'windows-cp314-amd64'), (1, 'linux-cp312-x86_64')]:
            with self.assertRaises(pools.SavedCandidatePoolError):
                pools._select_producer(binding(CHATGPT, index, target))
        for name in TRANSPORT['engine_source_hashes']:
            bad = binding(CHATGPT)
            bad['engine_source_hashes'][name] = 'f' * 64
            with self.assertRaises(pools.SavedCandidatePoolError):
                pools._select_producer(bad)

    def test_full_new_profiles_admit_exact_results_without_rewrite(self):
        provider = {
            'mode': 'openai_compatible',
            'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions',
            'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30},
        }
        with tempfile.TemporaryDirectory() as temporary:
            for index in (0, 1):
                for mode in ('fixture', 'openai_compatible', 'chatgpt_plan'):
                    profile = to_dict(CHATGPT if mode == 'chatgpt_plan' else TRANSPORT)
                    profile['result_source_hashes'] = profile['result_source_hash_variants'][index]
                    root = Path(temporary) / f'{index}-{mode}'
                    if mode == 'chatgpt_plan':
                        folder, ref, original, _ = make_chatgpt_source(root, producer=profile, implementation=index, candidates=1)
                    else:
                        folder, ref, original, _ = make_saved_source(
                            root, producer=profile, provider=provider if mode == 'openai_compatible' else None, candidates=1
                        )
                    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    admitted = self.admit(folder, ref, original)
                    self.assertEqual(admitted.admission['producer'], CHATGPT if mode == 'chatgpt_plan' else TRANSPORT)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_old_new_and_mixed_result_tuples_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            for base in (TRANSPORT, CHATGPT):
                variants = []
                for index in (0, 1):
                    old_core = pools.TRANSPORT_VERIFIER_PRODUCER['result_source_hash_variants'][index]['core.py']
                    profile = to_dict(base)
                    profile['result_source_hashes'] = to_dict(base['result_source_hash_variants'][index])
                    profile['result_source_hashes']['core.py'] = old_core
                    variants.append(profile)
                    profile = to_dict(base)
                    profile['result_source_hashes'] = to_dict(base['result_source_hash_variants'][index])
                    profile['result_source_hashes']['core.py'] = base['result_source_hash_variants'][1 - index]['core.py']
                    variants.append(profile)
                profile = to_dict(base)
                profile['engine_source_hashes']['core.py'] = pools.TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes']['core.py']
                variants.append(profile)
                for index, profile in enumerate(variants):
                    root = Path(temporary) / f"{base['protocol']}-{index}"
                    make = make_chatgpt_source if base is CHATGPT else make_saved_source
                    folder, ref, original, _ = make(root, producer=profile, candidates=1)
                    with self.assertRaises(pools.SavedCandidatePoolError):
                        self.admit(folder, ref, original)
