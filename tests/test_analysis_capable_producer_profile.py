"""Ordinary campaign provenance for the analysis-capable provider implementation.

Analysis documents keep their own schema. All sources and receipts here are
manufactured offline fixtures; no inference, identity, or profit claim is made.
"""

import copy
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import canonical_json, content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.saved_pool_fixtures import make_chatgpt_source, write_source
from tests.test_subscription_producer_profile import binding


PROFILE = pools.SIWC_ANALYSIS_CAPABLE_PROFILE_V1


class AnalysisCapableProducerProfileTests(unittest.TestCase):
    def admit(self, folder, reference, original):
        return pools.admit_saved_campaign_pool(
            source_campaign_dir=folder,
            source_campaign_ref=reference,
            original_dataset=original,
            original_dataset_ref='explicit-fixture-original',
            first_training_timestamp=max(bar.end for bar in original.bars) + timedelta(days=1),
            authoritative_registry_path=folder.parent / 'source-registry.sqlite3',
        )

    def test_prior_safety_profile_remains_exact_and_new_profile_is_frozen(self):
        old = pools.SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1
        self.assertEqual(content_hash(old), 'b4b257c6ab32da8631a8ef82ad4244f6f757c27a78246f96544649738009c2ea')
        self.assertEqual(content_hash(PROFILE), 'e14aba96d7c734c46f0713a7bedf2be5d33e4ff50bba1c60ed9a447f380af4a1')
        restored = to_dict(PROFILE)
        restored['protocol'] = old['protocol']
        for new, previous in zip(restored['chatgpt_plan_implementations'], old['chatgpt_plan_implementations']):
            new['source_sha256'] = to_dict(previous['source_sha256'])
        self.assertEqual(restored, old)
        self.assertEqual(PROFILE['provider_modes'], ['chatgpt_plan'])
        with self.assertRaises(TypeError):
            PROFILE['chatgpt_plan_implementations'][0]['source_sha256']['desktop_chatgpt_provider.py'] = 'f' * 64

    def test_both_exact_profile_generations_and_all_declared_targets_select_uniquely(self):
        for profile in (pools.SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1, PROFILE):
            for index, variant in enumerate(profile['chatgpt_plan_implementations']):
                for target in variant['dependency_targets']:
                    with self.subTest(protocol=profile['protocol'], variant=index, target=target):
                        value = binding(profile, index, target)
                        with patch.dict(sys.modules, {'quantlab.assistant.adapters.chatgpt.auth': None, 'quantlab.assistant.adapters.chatgpt.provider': None}):
                            self.assertIs(pools._select_producer(value), profile)
                            with patch.object(pools, 'SUPPORTED_PRODUCERS', tuple(reversed(pools.SUPPORTED_PRODUCERS))):
                                self.assertIs(pools._select_producer(value), profile)

    def test_mixed_line_endings_unknown_sources_and_unsupported_targets_reject(self):
        bad = []
        variants = PROFILE['chatgpt_plan_implementations']
        for index in (0, 1):
            for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
                value = binding(PROFILE, index)
                value['provider']['descriptor']['source_sha256'][name] = variants[1 - index]['source_sha256'][name]
                bad.append(value)
                value = binding(PROFILE, index)
                value['provider']['descriptor']['source_sha256'][name] = pools.SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1['chatgpt_plan_implementations'][index][
                    'source_sha256'
                ][name]
                bad.append(value)
            value = binding(PROFILE, index)
            value['provider']['descriptor']['dependency_manifest_sha256'] = variants[1 - index]['dependency_manifest_sha256']
            bad.append(value)
            value = binding(PROFILE, index)
            value['provider']['descriptor']['source_sha256']['desktop_chatgpt_auth.py'] = pools.TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2[
                'chatgpt_plan_implementations'
            ][index]['source_sha256']['desktop_chatgpt_auth.py']
            bad.append(value)
        for index, target in ((0, 'windows-cp314-amd64'), (0, 'linux-cp313-x86_64'), (1, 'linux-cp312-x86_64')):
            bad.append(binding(PROFILE, index, target))
        value = binding(PROFILE)
        value['provider']['descriptor']['dependency_versions']['PyJWT'] = '2.15.0'
        bad.append(value)
        value = binding(PROFILE)
        value['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = 'f' * 64
        bad.append(value)
        for index, value in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(pools.SavedCandidatePoolError) as caught:
                pools._select_producer(value)
            self.assertEqual(caught.exception.reason_code, 'source_provider_provenance_invalid')

    def test_full_ordinary_campaign_admits_without_auth_import_or_source_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            for variant in (0, 1):
                folder, reference, original, _ = make_chatgpt_source(
                    Path(temporary) / f'variant-{variant}', producer=PROFILE, implementation=variant, candidates=1
                )
                before = {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()}
                with patch.dict(sys.modules, {'quantlab.assistant.adapters.chatgpt.auth': None, 'quantlab.assistant.adapters.chatgpt.provider': None}):
                    admitted = self.admit(folder, reference, original)
                self.assertEqual(admitted.admission['producer'], PROFILE)
                self.assertEqual(admitted.admission['real_model_status'], 'not_verified')
                self.assertEqual(len(admitted.candidate_pool), 1)
                self.assertEqual(before, {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()})

    def test_analysis_request_receipt_is_not_ordinary_campaign_certification(self):
        from quantlab.research_analysis import ANALYSIS_PROMPT

        with tempfile.TemporaryDirectory() as temporary:
            folder, reference, original, state = make_chatgpt_source(Path(temporary), producer=PROFILE, candidates=1)
            attempt = state['attempts'][0]
            request = {
                'model': state['binding']['provider']['model'],
                'instructions': ANALYSIS_PROMPT,
                'input': [{'role': 'user', 'content': canonical_json(attempt['generator_context'])}],
                'store': False,
                'stream': True,
            }
            changed = copy.deepcopy(state)
            changed['provider_receipts'][0].update(request_hash=content_hash(request), request_bytes=len(canonical_json(request).encode('utf-8')))
            write_source(folder, changed)
            before = {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()}
            with self.assertRaises(pools.SavedCandidatePoolError) as caught:
                self.admit(folder, reference, original)
            self.assertEqual(caught.exception.reason_code, 'source_provider_receipt_invalid')
            self.assertEqual(before, {path: path.read_bytes() for path in folder.parent.rglob('*') if path.is_file()})


if __name__ == '__main__':
    unittest.main()
