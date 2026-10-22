"""Frozen R1 producer additions, preserving all historical source identities."""

import hashlib
from pathlib import Path
import unittest

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.test_subscription_producer_profile import binding

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = pools.UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1
SIWC = pools.UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1
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
    'e1262b61e647d3b716ce6451c184921f4d2b3b797317af152de0a2b460ccd492',
    '797b5bcfcf94f111144eda6cb6cc01a0c9cc6b24ec9aa2d9d9dec3b34d78c729',
    '04d0ef09054c123ecd0d5655f643eb1a14a34a6db670cbf93561f819918a33f0',
]
NEW_HASHES = ['10edb26c0161f79567532707d67fc86461459b980d6ab44c980247b60e9c9a13', '7ea8576b63a971756257b0b93c260c2439621c00e5d19be0ee0f702988dff7bf']


class UnknownReconciliationProducerProfileTests(unittest.TestCase):
    def test_all_nineteen_historical_profiles_keep_exact_identity(self):
        self.assertEqual([content_hash(p) for p in pools.SUPPORTED_PRODUCERS[:19]], HISTORICAL_HASHES)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[19:21], (TRANSPORT, SIWC))
        self.assertEqual([content_hash(p) for p in (TRANSPORT, SIWC)], NEW_HASHES)
        for profile in pools.SUPPORTED_PRODUCERS:
            with self.assertRaises(TypeError):
                profile['protocol'] = 'rewritten'

    def test_only_reviewed_engine_provider_and_protocol_fields_change(self):
        for current, previous in ((TRANSPORT, pools.DEADLINE_TRANSPORT_PROFILE_V1), (SIWC, pools.CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1)):
            restored = to_dict(current)
            restored['protocol'] = previous['protocol']
            restored['engine_source_hashes']['research.py'] = previous['engine_source_hashes']['research.py']
            if current is SIWC:
                for new, old in zip(restored['chatgpt_plan_implementations'], previous['chatgpt_plan_implementations']):
                    new['source_sha256']['desktop_chatgpt_provider.py'] = old['source_sha256']['desktop_chatgpt_provider.py']
            self.assertEqual(restored, previous)

    def test_new_literal_sources_match_current_engine_and_lf_crlf_provider(self):
        for profile in (TRANSPORT, SIWC):
            self.assertEqual(
                {name: content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')) for name in profile['engine_source_hashes']},
                profile['engine_source_hashes'],
            )
        # R2 re-pin: current provider bytes now match the appended R2 profile; this
        # profile's own literals stay pinned by NEW_HASHES above.
        latest = pools.STREAM_CONTENT_TYPE_SIWC_PROFILE_V1
        for index, implementation in enumerate(latest['chatgpt_plan_implementations']):
            for name, digest in implementation['source_sha256'].items():
                raw = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                if index:
                    raw = raw.replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_new_and_historical_exact_tuples_select_only_their_own_profile(self):
        for profile in (pools.CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1, SIWC):
            for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    self.assertIs(pools._select_producer(binding(profile, index, target)), profile)
        for profile in (pools.DEADLINE_TRANSPORT_PROFILE_V1, TRANSPORT):
            for mode in ('fixture', 'openai_compatible'):
                item = {
                    'engine_source_hashes': to_dict(profile['engine_source_hashes']),
                    'prompt_template_hash': profile['prompt_template_hash'],
                    'provider': {'mode': mode},
                }
                self.assertIs(pools._select_producer(item), profile)

    def test_mixed_old_new_or_unknown_source_tuples_are_rejected(self):
        old = pools.CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1
        for index in (0, 1):
            for field, value in (
                ('engine', old['engine_source_hashes']['research.py']),
                ('engine', 'f' * 64),
                ('provider', old['chatgpt_plan_implementations'][index]['source_sha256']['desktop_chatgpt_provider.py']),
                ('provider', SIWC['chatgpt_plan_implementations'][1 - index]['source_sha256']['desktop_chatgpt_provider.py']),
                ('provider', 'f' * 64),
            ):
                item = binding(SIWC, index)
                if field == 'engine':
                    item['engine_source_hashes']['research.py'] = value
                else:
                    item['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = value
                with self.subTest(field=field, index=index), self.assertRaises(pools.SavedCandidatePoolError):
                    pools._select_producer(item)

    def test_new_siwc_saved_admission_is_readonly_and_never_accepts_consumed_receipts(self):
        from datetime import timedelta
        import sys
        import tempfile
        from unittest.mock import patch
        from tests.saved_pool_fixtures import make_chatgpt_source, write_source

        with tempfile.TemporaryDirectory() as temporary:
            for index in (0, 1):
                root = Path(temporary) / str(index)
                folder, reference, original, state = make_chatgpt_source(root, producer=SIWC, implementation=index, candidates=1)
                arguments = dict(
                    source_campaign_dir=folder,
                    source_campaign_ref=reference,
                    original_dataset=original,
                    original_dataset_ref='explicit-fixture-original',
                    first_training_timestamp=max(bar.end for bar in original.bars) + timedelta(days=1),
                    authoritative_registry_path=root / 'source-registry.sqlite3',
                )
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    admission = pools.admit_saved_campaign_pool(**arguments)
                pools.validate_admission_snapshot(admission.admission, admission.candidate_pool)
                self.assertEqual(admission.admission['producer'], SIWC)
                self.assertEqual(len(admission.candidate_pool), 1)
                self.assertEqual(admission.admission['real_model_status'], 'not_verified')
                self.assertEqual({path: path.read_bytes() for path in root.rglob('*') if path.is_file()}, before)
                state['provider_receipts'][0]['status'] = 'user_confirmed_consumed'
                write_source(folder, state)
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    with self.assertRaises(pools.SavedCandidatePoolError) as caught:
                        pools.admit_saved_campaign_pool(**arguments)
                self.assertEqual(caught.exception.reason_code, 'source_provider_receipt_invalid')
                self.assertEqual({path: path.read_bytes() for path in root.rglob('*') if path.is_file()}, before)
