"""Literal SIWC profile admission only: no grant, credential, or model calls."""
import hashlib
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import canonical_json, content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.saved_pool_fixtures import make_chatgpt_source


PROFILE = pools.SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1
ROOT = Path(__file__).resolve().parents[1]


def binding(profile=PROFILE, variant=0, target=None):
    implementation = to_dict(profile['chatgpt_plan_implementations'][variant])
    descriptor = {key: implementation[key] for key in (
        'source_sha256', 'dependency_versions', 'dependency_manifest_sha256',
        'dependency_artifact_evidence')}
    descriptor['dependency_target'] = target or implementation['dependency_targets'][0]
    return {'engine_source_hashes': to_dict(profile['engine_source_hashes']),
            'prompt_template_hash': profile['prompt_template_hash'],
            'provider': {'mode': 'chatgpt_plan', 'descriptor': descriptor}}


class SubscriptionProducerProfileTests(unittest.TestCase):
    def test_all_five_prior_profiles_remain_exact_and_frozen(self):
        prior = (
            (pools.AUDITED_PRODUCER, '97ef1ebf0e68ed6d7c5714caa806ece5b53592c984d0058ac8a1d73c06a419a5'),
            (pools.CURRENT_PRODUCER, '2c7655ab89a8beaf48e98105c85a2dd5860f1d41418e32d1452e7218ab620f26'),
            (pools.CURRENT_CHATGPT_PROFILE_V2, 'ce3b2af865ea0338575c065b988a64ebcd4974e58617a93779e6edb684ec37de'),
            (pools.TRANSPORT_VERIFIER_PRODUCER, '346eceee2a55514c22a32ae028402c8a74c9b52ab44befa0f90608ae68e549be'),
            (pools.TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2, 'e86f5b691ea3b0c015f0354ca2d6ec0b49c6300c25b62255b4f8a9da13f2b55e'))
        self.assertEqual(pools.SUPPORTED_PRODUCERS[:9], tuple(item[0] for item in prior)
                         + (PROFILE, pools.SIWC_ANALYSIS_CAPABLE_PROFILE_V1,
                            pools.SCALAR_TRANSPORT_PROFILE_V1, pools.SCALAR_SIWC_ANALYSIS_PROFILE_V1))
        for profile, digest in prior:
            self.assertEqual(content_hash(profile), digest)
            with self.assertRaises(TypeError): profile['protocol'] = 'changed'
            for index, implementation in enumerate(profile.get('chatgpt_plan_implementations', ())):
                for target in implementation['dependency_targets']:
                    self.assertIs(pools._select_producer(binding(profile, index, target)), profile)
        for prior_profile in (pools.AUDITED_PRODUCER, pools.CURRENT_PRODUCER, pools.TRANSPORT_VERIFIER_PRODUCER):
            original = {'engine_source_hashes': to_dict(prior_profile['engine_source_hashes']),
                        'prompt_template_hash': prior_profile['prompt_template_hash']}
            for mode in ('fixture', 'openai_compatible'):
                self.assertIs(pools._select_producer({**original, 'provider': {'mode': mode}}), prior_profile)

    def test_new_profile_is_frozen_literal_and_changes_only_reviewed_descriptor(self):
        self.assertEqual(content_hash(PROFILE), 'b4b257c6ab32da8631a8ef82ad4244f6f757c27a78246f96544649738009c2ea')
        restored = to_dict(PROFILE)
        previous = pools.TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2
        restored['protocol'] = previous['protocol']
        for new, old in zip(restored['chatgpt_plan_implementations'], previous['chatgpt_plan_implementations']):
            new['source_sha256'] = to_dict(old['source_sha256'])
        self.assertEqual(restored, previous)
        self.assertEqual(PROFILE['provider_modes'], ['chatgpt_plan'])
        with self.assertRaises(TypeError):
            PROFILE['chatgpt_plan_implementations'][0]['source_sha256']['desktop_chatgpt_auth.py'] = 'f' * 64

    def test_exact_lf_crlf_source_manifest_pins_and_declared_targets(self):
        # These reads verify reviewed literals only. Runtime admission never reads
        # current sources or accepts a dynamically generated profile.
        latest = pools.SIWC_ANALYSIS_CAPABLE_PROFILE_V1
        for index, implementation in enumerate(latest['chatgpt_plan_implementations']):
            for name, digest in implementation['source_sha256'].items():
                if name == 'desktop_chatgpt_provider.py':
                    self.assertEqual(digest, ('d20203c2398e939d0ecd24a697f890ed29276075ded3444e4050e5e55e354baf',
                        'fd8ddc12075630532127be72be24d5df1c298b6d0805c8554e76943fd41d43f9')[index])
                    continue
                raw = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
                if index: raw = raw.replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            raw = (ROOT/'desktop_chatgpt_dependency_manifest.json').read_bytes().replace(b'\r\n', b'\n')
            if index: raw = raw.replace(b'\n', b'\r\n')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), implementation['dependency_manifest_sha256'])
            windows = {'windows-cp311-amd64', 'windows-cp312-amd64', 'windows-cp313-amd64'}
            expected = windows if index else windows | {'linux-cp311-x86_64', 'linux-cp312-x86_64'}
            self.assertEqual(set(implementation['dependency_targets']), expected)
            for target in expected:
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    self.assertIs(pools._select_producer(binding(latest, variant=index, target=target)), latest)

    def test_mixed_unknown_old_new_tuples_and_unsupported_targets_reject(self):
        variants = PROFILE['chatgpt_plan_implementations']
        bad_bindings = []
        for index in (0, 1):
            other = variants[1-index]
            for field in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
                item = binding(variant=index)
                item['provider']['descriptor']['source_sha256'][field] = other['source_sha256'][field]
                bad_bindings.append(item)
                item = binding(variant=index)
                item['provider']['descriptor']['source_sha256'][field] = pools.TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2['chatgpt_plan_implementations'][index]['source_sha256'][field]
                bad_bindings.append(item)
            item = binding(variant=index)
            item['provider']['descriptor']['dependency_manifest_sha256'] = other['dependency_manifest_sha256']
            bad_bindings.append(item)
        for index, target in ((0, 'windows-cp314-amd64'), (0, 'linux-cp313-x86_64'), (1, 'linux-cp312-x86_64')):
            bad_bindings.append(binding(variant=index, target=target))
        item = binding(); item['provider']['descriptor']['dependency_versions']['cryptography'] = '50.0.1'; bad_bindings.append(item)
        item = binding(); item['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = 'f' * 64; bad_bindings.append(item)
        for index, item in enumerate(bad_bindings):
            with self.subTest(index=index), self.assertRaises(pools.SavedCandidatePoolError) as caught:
                pools._select_producer(item)
            self.assertEqual(caught.exception.reason_code, 'source_provider_provenance_invalid')
        for field in PROFILE['engine_source_hashes']:
            item = binding(); item['engine_source_hashes'][field] = 'f' * 64
            with self.assertRaises(pools.SavedCandidatePoolError) as caught: pools._select_producer(item)
            self.assertEqual(caught.exception.reason_code, 'source_producer_unsupported')

    def test_full_saved_campaign_admission_preserves_unknown_verification_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            for index in (0, 1):
                folder, reference, original, _ = make_chatgpt_source(
                    Path(temporary)/f'variant-{index}', implementation=index,
                    candidates=1, producer=PROFILE)
                before = {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    admission = pools.admit_saved_campaign_pool(
                        source_campaign_dir=folder, source_campaign_ref=reference,
                        original_dataset=original, original_dataset_ref='explicit-fixture-original',
                        first_training_timestamp=max(bar.end for bar in original.bars)+timedelta(days=1),
                        authoritative_registry_path=folder.parent/'source-registry.sqlite3')
                self.assertEqual(admission.admission['producer'], PROFILE)
                self.assertEqual(admission.admission['real_model_status'], 'not_verified')
                self.assertEqual(len(admission.candidate_pool), 1)
                self.assertNotIn('native_runtime_accepted', canonical_json(admission.admission))
                self.assertEqual(before, {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()})


if __name__ == '__main__': unittest.main()
