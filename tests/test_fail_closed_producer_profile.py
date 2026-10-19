"""Exact fail-closed producer provenance. Offline manufactured receipts only."""

import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from quantlab.core import content_hash, to_dict
from quantlab.saved_candidate_pool import (
    CLEANUP_TRANSPORT_PROFILE_V1,
    CLEANUP_SIWC_ANALYSIS_PROFILE_V1,
    FAIL_CLOSED_TRANSPORT_PROFILE_V1,
    FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1,
    DEADLINE_TRANSPORT_PROFILE_V1,
    DEADLINE_SIWC_ANALYSIS_PROFILE_V1,
    CURRENT_PRODUCER,
    TRANSPORT_VERIFIER_PRODUCER,
    TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2,
    SUPPORTED_PRODUCERS,
    SavedCandidatePoolError,
)
from tests.saved_pool_fixtures import make_saved_source, make_chatgpt_source
from tests import test_saved_candidate_pool as saved_tests


class FailClosedProducerProfileTests(unittest.TestCase):
    setUp = saved_tests.SavedCandidatePoolTests.setUp
    tearDown = saved_tests.SavedCandidatePoolTests.tearDown
    admit = saved_tests.SavedCandidatePoolTests.admit

    def test_current_literal_sources_and_only_reviewed_changes(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(len(SUPPORTED_PRODUCERS), 19)
        self.assertEqual(SUPPORTED_PRODUCERS[11:13], (FAIL_CLOSED_TRANSPORT_PROFILE_V1, FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1))
        for old, new in (
            (CLEANUP_TRANSPORT_PROFILE_V1, FAIL_CLOSED_TRANSPORT_PROFILE_V1),
            (CLEANUP_SIWC_ANALYSIS_PROFILE_V1, FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1),
        ):
            # Historical research pins remain covered by the all-thirteen hash
            # check; this current-checkout assertion includes the newly reviewed pin.
            expected_sources = dict(new['engine_source_hashes'])
            expected_sources['research.py'] = DEADLINE_TRANSPORT_PROFILE_V1['engine_source_hashes']['research.py']
            self.assertEqual(
                {name: content_hash((root / 'quantlab' / name).read_text(encoding='utf-8')) for name in new['engine_source_hashes']}, expected_sources
            )
            restored = to_dict(new)
            restored['protocol'] = old['protocol']
            restored['engine_source_hashes']['backtest.py'] = old['engine_source_hashes']['backtest.py']
            restored['result_source_hashes']['backtest.py'] = old['result_source_hashes']['backtest.py']
            for index, hashes in enumerate(new['result_source_hash_variants']):
                for name, digest in hashes.items():
                    raw = (root / 'quantlab' / name).read_bytes().replace(b'\r\n', b'\n')
                    if index:
                        raw = raw.replace(b'\n', b'\r\n')
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                restored['result_source_hash_variants'][index]['backtest.py'] = old['result_source_hash_variants'][index]['backtest.py']
            self.assertEqual(new['result_source_hashes'], new['result_source_hash_variants'][0])
            for index, impl in enumerate(new.get('chatgpt_plan_implementations', ())):
                for name, digest in impl['source_sha256'].items():
                    if name == 'desktop_chatgpt_auth.py':
                        # Historical auth stays pinned; current bytes are checked
                        # against the appended profile, never relabeled as history.
                        self.assertEqual(
                            digest,
                            (
                                '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                            )[index],
                        )
                        continue
                    if name == 'desktop_chatgpt_provider.py':
                        # Provider bytes changed later (TLS trust anchors); the
                        # historical pin stays and the current bytes are checked
                        # against the appended TLS-anchor profile.
                        self.assertEqual(
                            digest,
                            (
                                '4de519504894985359b24980d0e7e258c945af646002a3a1b9743d51c3b186e8',
                                '7134b7c175646beae042efad1b2f9dedf377792657c2def2785b64a94573c81a',
                            )[index],
                        )
                        continue
                    raw = (root / name).read_bytes().replace(b'\r\n', b'\n')
                    if index:
                        raw = raw.replace(b'\n', b'\r\n')
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                restored['chatgpt_plan_implementations'][index]['source_sha256']['desktop_chatgpt_provider.py'] = old['chatgpt_plan_implementations'][index][
                    'source_sha256'
                ]['desktop_chatgpt_provider.py']
            self.assertEqual(restored, old)
            with self.assertRaises(TypeError):
                new['engine_source_hashes']['backtest.py'] = 'f' * 64

    def test_all_eleven_released_profiles_retain_identity_and_artifact_bytes(self):
        expected = [
            '97ef1ebf0e68ed6d7c5714caa806ece5b53592c984d0058ac8a1d73c06a419a5',
            '2c7655ab89a8beaf48e98105c85a2dd5860f1d41418e32d1452e7218ab620f26',
            'ce3b2af865ea0338575c065b988a64ebcd4974e58617a93779e6edb684ec37de',
            '346eceee2a55514c22a32ae028402c8a74c9b52ab44befa0f90608ae68e549be',
            'e86f5b691ea3b0c015f0354ca2d6ec0b49c6300c25b62255b4f8a9da13f2b55e',
            'b4b257c6ab32da8631a8ef82ad4244f6f757c27a78246f96544649738009c2ea',
            'e14aba96d7c734c46f0713a7bedf2be5d33e4ff50bba1c60ed9a447f380af4a1',
            '468525fa690bf831d5a61d5f0b3bed18313aa61269b40dbed4d917f814aafa6b',
            '356d04b67089df38575ec32fb9204861fc13a0581a3fab225383f21bc8c5b033',
            'f4d60d7d4db212aa8d4bd44eba9c30189a00bfebc4ccfa4c302e1c5227462498',
            '84930138726b1a61b28645078076b1b71ca9f6e5ec6c495dc463ddd8f9a163cb',
        ]
        self.assertEqual([content_hash(p) for p in SUPPORTED_PRODUCERS[:11]], expected)
        for index, profile in enumerate(SUPPORTED_PRODUCERS[:11]):
            make = make_chatgpt_source if profile.get('provider_modes') == ['chatgpt_plan'] else make_saved_source
            root = self.root / f'history-{index}'
            folder, ref, original, _ = make(root, producer=profile, candidates=1)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(admission.admission['producer'], profile)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_new_engine_rejects_old_results_and_old_provider_descriptors(self):
        for mode, base, old in (
            ('fixture', FAIL_CLOSED_TRANSPORT_PROFILE_V1, CLEANUP_TRANSPORT_PROFILE_V1),
            ('chatgpt_plan', FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1, CLEANUP_SIWC_ANALYSIS_PROFILE_V1),
        ):
            variants = []
            for index in (0, 1):
                profile = to_dict(base)
                profile['result_source_hashes'] = to_dict(old['result_source_hash_variants'][index])
                variants.append(profile)
            if mode == 'chatgpt_plan':
                profile = to_dict(base)
                profile['chatgpt_plan_implementations'] = [to_dict(item) for item in old['chatgpt_plan_implementations']]
                variants.append(profile)
                profile = to_dict(base)
                profile['engine_source_hashes']['backtest.py'] = old['engine_source_hashes']['backtest.py']
                variants.append(profile)
            for index, profile in enumerate(variants):
                make = make_chatgpt_source if mode == 'chatgpt_plan' else make_saved_source
                folder, ref, original, _ = make(self.root / f'mixed-{mode}-{index}', producer=profile, candidates=1)
                with self.assertRaises(SavedCandidatePoolError):
                    self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_fail_closed_profiles_admit_exact_variants_without_rewrites(self):
        compatible = {
            'mode': 'openai_compatible',
            'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions',
            'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30},
        }
        for result_index in (0, 1):
            for mode in ('fixture', 'openai_compatible', 'chatgpt_plan'):
                expected = FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1 if mode == 'chatgpt_plan' else FAIL_CLOSED_TRANSPORT_PROFILE_V1
                profile = to_dict(expected)
                profile['result_source_hashes'] = profile['result_source_hash_variants'][result_index]
                root = self.root / f'cleanup-exact-{result_index}-{mode}'
                if mode == 'chatgpt_plan':
                    folder, ref, original, _ = make_chatgpt_source(root, producer=profile, implementation=result_index, candidates=1)
                else:
                    folder, ref, original, _ = make_saved_source(
                        root, producer=profile, provider=compatible if mode == 'openai_compatible' else None, candidates=1
                    )
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS', tuple(reversed(SUPPORTED_PRODUCERS))):
                    reordered = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                self.assertEqual(admission.admission['producer'], expected)
                self.assertEqual(admission.admission, reordered.admission)
                self.assertEqual(before, {path: path.read_bytes() for path in root.rglob('*') if path.is_file()})

    def test_fail_closed_profiles_reject_tampered_and_mixed_engine_result_tuples(self):
        for base in (FAIL_CLOSED_TRANSPORT_PROFILE_V1, FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1):
            variants = []
            for name in base['engine_source_hashes']:
                profile = to_dict(base)
                profile['engine_source_hashes'][name] = 'f' * 64
                variants.append(profile)
            for name in ('core.py', 'provider.py'):
                profile = to_dict(base)
                profile['engine_source_hashes'][name] = CURRENT_PRODUCER['engine_source_hashes'][name]
                variants.append(profile)
            profile = to_dict(base)
            profile['prompt_template_hash'] = 'f' * 64
            variants.append(profile)
            for result_index in (0, 1):
                for core_hash in (
                    TRANSPORT_VERIFIER_PRODUCER['result_source_hash_variants'][result_index]['core.py'],
                    base['result_source_hash_variants'][1 - result_index]['core.py'],
                    'f' * 64,
                ):
                    profile = to_dict(base)
                    profile['result_source_hashes'] = to_dict(base['result_source_hash_variants'][result_index])
                    profile['result_source_hashes']['core.py'] = core_hash
                    variants.append(profile)
            for index, profile in enumerate(variants):
                with self.subTest(protocol=base['protocol'], index=index):
                    make = make_chatgpt_source if base is FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1 else make_saved_source
                    folder, ref, original, _ = make(self.root / f"cleanup-tamper-{base['protocol']}-{index}", producer=profile, candidates=1)
                    with self.assertRaises(SavedCandidatePoolError):
                        self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_fail_closed_chatgpt_requires_exact_reviewed_descriptors_and_targets(self):
        from tests.test_subscription_producer_profile import binding
        from quantlab.saved_candidate_pool import _select_producer

        profile = FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1
        for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
            for target in implementation['dependency_targets']:
                self.assertIs(_select_producer(binding(profile, index, target)), profile)
            for name in implementation['source_sha256']:
                bad = binding(profile, index)
                bad['provider']['descriptor']['source_sha256'][name] = profile['chatgpt_plan_implementations'][1 - index]['source_sha256'][name]
                with self.assertRaises(SavedCandidatePoolError):
                    _select_producer(bad)
            for key, value in (('dependency_manifest_sha256', 'f' * 64), ('dependency_versions', {'PyJWT': '0'}), ('dependency_target', 'windows-cp314-amd64')):
                bad = binding(profile, index)
                bad['provider']['descriptor'][key] = value
                with self.assertRaises(SavedCandidatePoolError):
                    _select_producer(bad)
            bad = binding(profile, index)
            bad['provider']['descriptor']['source_sha256'] = to_dict(
                TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2['chatgpt_plan_implementations'][index]['source_sha256']
            )
            with self.assertRaises(SavedCandidatePoolError):
                _select_producer(bad)


class DeadlineProducerProfileTests(unittest.TestCase):
    setUp = saved_tests.SavedCandidatePoolTests.setUp
    tearDown = saved_tests.SavedCandidatePoolTests.tearDown
    admit = saved_tests.SavedCandidatePoolTests.admit

    def test_current_exact_literals_change_only_protocol_and_research(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(SUPPORTED_PRODUCERS[13:15], (DEADLINE_TRANSPORT_PROFILE_V1, DEADLINE_SIWC_ANALYSIS_PROFILE_V1))
        for old, new in (
            (FAIL_CLOSED_TRANSPORT_PROFILE_V1, DEADLINE_TRANSPORT_PROFILE_V1),
            (FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1, DEADLINE_SIWC_ANALYSIS_PROFILE_V1),
        ):
            self.assertEqual(
                {name: content_hash((root / 'quantlab' / name).read_text(encoding='utf-8')) for name in new['engine_source_hashes']},
                new['engine_source_hashes'],
            )
            restored = to_dict(new)
            self.assertNotEqual(new['protocol'], old['protocol'])
            self.assertNotEqual(new['engine_source_hashes']['research.py'], old['engine_source_hashes']['research.py'])
            restored['protocol'] = old['protocol']
            restored['engine_source_hashes']['research.py'] = old['engine_source_hashes']['research.py']
            self.assertEqual(restored, old)
            with self.assertRaises(TypeError):
                new['engine_source_hashes']['research.py'] = 'f' * 64

    def test_all_thirteen_historical_profile_hashes_are_unchanged(self):
        expected = [
            '97ef1ebf0e68ed6d7c5714caa806ece5b53592c984d0058ac8a1d73c06a419a5',
            '2c7655ab89a8beaf48e98105c85a2dd5860f1d41418e32d1452e7218ab620f26',
            'ce3b2af865ea0338575c065b988a64ebcd4974e58617a93779e6edb684ec37de',
            '346eceee2a55514c22a32ae028402c8a74c9b52ab44befa0f90608ae68e549be',
            'e86f5b691ea3b0c015f0354ca2d6ec0b49c6300c25b62255b4f8a9da13f2b55e',
            'b4b257c6ab32da8631a8ef82ad4244f6f757c27a78246f96544649738009c2ea',
            'e14aba96d7c734c46f0713a7bedf2be5d33e4ff50bba1c60ed9a447f380af4a1',
            '468525fa690bf831d5a61d5f0b3bed18313aa61269b40dbed4d917f814aafa6b',
            '356d04b67089df38575ec32fb9204861fc13a0581a3fab225383f21bc8c5b033',
            'f4d60d7d4db212aa8d4bd44eba9c30189a00bfebc4ccfa4c302e1c5227462498',
            '84930138726b1a61b28645078076b1b71ca9f6e5ec6c495dc463ddd8f9a163cb',
            '3c1960b8abe579630f2784d8782992a0d6cdb3e82f7c881d9fe94a0b08e9056e',
            '640c63a2b09ada4d836c6e73ea6aafb5380aa53934f9246c55a0f0a48cccd542',
        ]
        self.assertEqual([content_hash(profile) for profile in SUPPORTED_PRODUCERS[:13]], expected)

    def test_exact_new_variants_admit_read_only_and_order_independently(self):
        compatible = {
            'mode': 'openai_compatible',
            'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions',
            'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30},
        }
        for result_index in (0, 1):
            for mode in ('fixture', 'openai_compatible', 'chatgpt_plan'):
                expected = DEADLINE_SIWC_ANALYSIS_PROFILE_V1 if mode == 'chatgpt_plan' else DEADLINE_TRANSPORT_PROFILE_V1
                profile = to_dict(expected)
                profile['result_source_hashes'] = profile['result_source_hash_variants'][result_index]
                root = self.root / f'deadline-exact-{result_index}-{mode}'
                if mode == 'chatgpt_plan':
                    folder, ref, original, _ = make_chatgpt_source(root, producer=profile, implementation=result_index, candidates=1)
                else:
                    folder, ref, original, _ = make_saved_source(
                        root, producer=profile, provider=compatible if mode == 'openai_compatible' else None, candidates=1
                    )
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS', tuple(reversed(SUPPORTED_PRODUCERS))):
                    reordered = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                self.assertEqual(admission.admission['producer'], expected)
                self.assertEqual(admission.admission, reordered.admission)
                self.assertEqual(before, {path: path.read_bytes() for path in root.rglob('*') if path.is_file()})

    def test_new_profiles_reject_tampered_or_unreviewed_mixed_tuples(self):
        for base in (DEADLINE_TRANSPORT_PROFILE_V1, DEADLINE_SIWC_ANALYSIS_PROFILE_V1):
            variants = []
            for name in base['engine_source_hashes']:
                profile = to_dict(base)
                profile['engine_source_hashes'][name] = 'f' * 64
                variants.append(profile)
            profile = to_dict(base)
            profile['engine_source_hashes']['backtest.py'] = CLEANUP_TRANSPORT_PROFILE_V1['engine_source_hashes']['backtest.py']
            variants.append(profile)
            for index in (0, 1):
                profile = to_dict(base)
                profile['result_source_hashes'] = to_dict(base['result_source_hash_variants'][index])
                profile['result_source_hashes']['core.py'] = base['result_source_hash_variants'][1 - index]['core.py']
                variants.append(profile)
            for index, profile in enumerate(variants):
                with self.subTest(protocol=base['protocol'], index=index):
                    make = make_chatgpt_source if base is DEADLINE_SIWC_ANALYSIS_PROFILE_V1 else make_saved_source
                    folder, ref, original, _ = make(self.root / f"deadline-invalid-{base['protocol']}-{index}", producer=profile, candidates=1)
                    with self.assertRaises(SavedCandidatePoolError):
                        self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_new_siwc_requires_exact_descriptors_and_dependency_targets(self):
        from tests.test_subscription_producer_profile import binding
        from quantlab.saved_candidate_pool import _select_producer

        profile = DEADLINE_SIWC_ANALYSIS_PROFILE_V1
        for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
            for target in implementation['dependency_targets']:
                self.assertIs(_select_producer(binding(profile, index, target)), profile)
            for name in implementation['source_sha256']:
                bad = binding(profile, index)
                bad['provider']['descriptor']['source_sha256'][name] = profile['chatgpt_plan_implementations'][1 - index]['source_sha256'][name]
                with self.assertRaises(SavedCandidatePoolError):
                    _select_producer(bad)
            for key, value in (('dependency_manifest_sha256', 'f' * 64), ('dependency_versions', {'PyJWT': '0'}), ('dependency_target', 'windows-cp314-amd64')):
                bad = binding(profile, index)
                bad['provider']['descriptor'][key] = value
                with self.assertRaises(SavedCandidatePoolError):
                    _select_producer(bad)
