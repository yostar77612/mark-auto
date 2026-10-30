"""Exact new auth provenance; generated offline receipts, never real OAuth."""

from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.saved_pool_fixtures import make_chatgpt_source
from tests.test_subscription_producer_profile import binding


PROFILE = pools.TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1
PREVIOUS = pools.DEADLINE_SIWC_ANALYSIS_PROFILE_V1
ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_HASHES = [
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
    '6abd264075063a536078d9d81b83daab4fa0632973991817d4142c260c06775a',
    '7277473a885a157eebd5b6cc199fdd3b8ad9501ab796317fa1bbb9e35f04de54',
    'ae17850d264a810ba51e499a50e28c72cc4f907a9f43c92ca07c282d1f11c632',
]


class TokenFormatProducerProfileTests(unittest.TestCase):
    def test_all_sixteen_historical_profiles_keep_exact_identity(self):
        self.assertEqual([content_hash(p) for p in pools.SUPPORTED_PRODUCERS[:16]], HISTORICAL_HASHES)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[15], PROFILE)
        for profile in pools.SUPPORTED_PRODUCERS:
            with self.assertRaises(TypeError):
                profile['protocol'] = 'rewritten'

    def test_literal_changes_only_protocol_and_reviewed_auth_pair(self):
        self.assertEqual(content_hash(PROFILE), 'ae17850d264a810ba51e499a50e28c72cc4f907a9f43c92ca07c282d1f11c632')
        self.assertNotEqual(PROFILE['protocol'], PREVIOUS['protocol'])
        restored = to_dict(PROFILE)
        restored['protocol'] = PREVIOUS['protocol']
        expected = ('3c2eef9d3b46b9ae74369fad67d5c016dbd97ea24d4c6f38a989d8b813f52f44', 'c62dc5ba0f06f04997d792e81552a41faa9f983f4a1fb6ef3a59e8596dee05b5')
        for index, implementation in enumerate(PROFILE['chatgpt_plan_implementations']):
            digest = implementation['source_sha256']['desktop_chatgpt_auth.py']
            self.assertEqual(digest, expected[index])
            restored['chatgpt_plan_implementations'][index]['source_sha256']['desktop_chatgpt_auth.py'] = PREVIOUS['chatgpt_plan_implementations'][index][
                'source_sha256'
            ]['desktop_chatgpt_auth.py']
            with self.assertRaises(TypeError):
                implementation['source_sha256']['desktop_chatgpt_auth.py'] = 'f' * 64
        self.assertEqual(restored, PREVIOUS)

    def test_exact_old_and_new_tuples_select_their_own_identity_in_any_order(self):
        for profile in (PREVIOUS, PROFILE):
            for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    item = binding(profile, index, target)
                    with self.subTest(protocol=profile['protocol'], variant=index, target=target):
                        self.assertIs(pools._select_producer(item), profile)
                        with patch.object(pools, 'SUPPORTED_PRODUCERS', tuple(reversed(pools.SUPPORTED_PRODUCERS))):
                            self.assertIs(pools._select_producer(item), profile)

    def test_mixed_unknown_or_tampered_descriptors_are_rejected(self):
        for index in (0, 1):
            bad = []
            for name in PROFILE['chatgpt_plan_implementations'][index]['source_sha256']:
                for digest in ('f' * 64, PROFILE['chatgpt_plan_implementations'][1 - index]['source_sha256'][name]):
                    item = binding(PROFILE, index)
                    item['provider']['descriptor']['source_sha256'][name] = digest
                    bad.append(item)
            for key, value in (
                ('dependency_manifest_sha256', 'f' * 64),
                ('dependency_manifest_sha256', PROFILE['chatgpt_plan_implementations'][1 - index]['dependency_manifest_sha256']),
                ('dependency_versions', {'PyJWT': '0'}),
                ('dependency_target', 'windows-cp314-amd64'),
                ('dependency_artifact_evidence', 'not_reviewed'),
            ):
                item = binding(PROFILE, index)
                item['provider']['descriptor'][key] = value
                bad.append(item)
            for item in bad:
                with self.subTest(variant=index), self.assertRaises(pools.SavedCandidatePoolError) as caught:
                    pools._select_producer(item)
                self.assertEqual(caught.exception.reason_code, 'source_provider_provenance_invalid')
            item = binding(PROFILE, index)
            item['engine_source_hashes']['research.py'] = 'f' * 64
            with self.assertRaises(pools.SavedCandidatePoolError) as caught:
                pools._select_producer(item)
            self.assertEqual(caught.exception.reason_code, 'source_producer_unsupported')

    def test_saved_old_and_new_campaigns_admit_read_only_without_live_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            for profile in (PREVIOUS, PROFILE):
                for index in (0, 1):
                    root = Path(temporary) / f"{profile['protocol']}-{index}"
                    folder, ref, original, _ = make_chatgpt_source(root, producer=profile, implementation=index, candidates=1)
                    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    with patch.dict(sys.modules, {'quantlab.assistant.adapters.chatgpt.auth': None, 'quantlab.assistant.adapters.chatgpt.provider': None}):
                        admission = pools.admit_saved_campaign_pool(
                            source_campaign_dir=folder,
                            source_campaign_ref=ref,
                            original_dataset=original,
                            original_dataset_ref='explicit-fixture-original',
                            first_training_timestamp=max(b.end for b in original.bars) + timedelta(days=1),
                            authoritative_registry_path=root / 'source-registry.sqlite3',
                        )
                    pools.validate_admission_snapshot(admission.admission, admission.candidate_pool)
                    self.assertEqual(admission.admission['producer'], profile)
                    self.assertEqual(admission.admission['real_model_status'], 'not_verified')
                    self.assertEqual(len(admission.candidate_pool), 1)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
