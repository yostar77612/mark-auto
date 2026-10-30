"""Append-only path compatibility pins; never relax source or receipt admission."""

from quantlab import saved_candidate_pool as pool_profiles

from quantlab.research_core.application import saved_pool_validation
from quantlab.research_core.domain import saved_pool


import hashlib
from pathlib import Path
import tempfile
import unittest
from tests.layered_source_fixtures import reviewed_source_bytes

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.test_subscription_producer_profile import binding
from tests.test_unknown_reconciliation_producer_profile import HISTORICAL_HASHES, NEW_HASHES as R1_HASHES

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = pools.LONG_PATH_TRANSPORT_PROFILE_V1
SIWC = pools.LONG_PATH_SIWC_PROFILE_V1


class LongPathProducerProfileTests(unittest.TestCase):
    def test_all_twenty_four_historical_identities_and_new_exact_pins(self):
        historical = (
            HISTORICAL_HASHES
            + R1_HASHES
            + [
                '6556b818ab781de47f75d358a928566ca334a745ed2876c9b766d5038b488bf8',
                '1d2c8d049113a97895710e41e180c6ac28f0a2307f45688a1a938508d43465a3',
                '0adfd0b63c351b39e2afba74312edf26fd47b5ab7277141be3068eacbf0e1677',
            ]
        )
        self.assertEqual([content_hash(profile) for profile in pools.SUPPORTED_PRODUCERS[:24]], historical)
        self.assertEqual(
            pools.SUPPORTED_PRODUCERS[24:29],
            (TRANSPORT, SIWC, pools.ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, pools.ATOMIC_REPLACE_SIWC_PROFILE_V1, pools.LAYERED_PATHS_SIWC_PROFILE_V1),
        )
        # Append the owner-approved current identity; retain every historical pin.
        self.assertEqual(content_hash(pools.LAYERED_PATHS_SIWC_PROFILE_V1), '27419b0e7cd6b481a6cdf27b0fb7c728cfd32544bde29c52c0082b5fe38ae4c5')
        self.assertEqual(content_hash(TRANSPORT), '092877b654abacbf244e985a8d5d6a75785a4561be48b4d8cfd5f940cd44857d')
        self.assertEqual(content_hash(SIWC), '9a83126852a5a89a90fe939c930ac91badfaeb16ea239e2ee387ba2904cd7692')

    def test_only_protocol_research_and_provider_uri_source_pins_change(self):
        for current, previous in ((TRANSPORT, pools.UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1), (SIWC, pools.COMPLETED_ITEMS_SIWC_PROFILE_V1)):
            restored = to_dict(current)
            restored['protocol'] = previous['protocol']
            restored['engine_source_hashes']['research.py'] = previous['engine_source_hashes']['research.py']
            for new, old in zip(restored.get('chatgpt_plan_implementations', ()), previous.get('chatgpt_plan_implementations', ())):
                new['source_sha256']['desktop_chatgpt_provider.py'] = old['source_sha256']['desktop_chatgpt_provider.py']
            self.assertEqual(restored, to_dict(previous))
            with self.assertRaises(TypeError):
                current['protocol'] = 'changed'

    def test_current_engine_and_both_provider_checkout_variants_match(self):
        for profile in (TRANSPORT, SIWC):
            actual = {
                name: content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')) for name in pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes']
            }
            expected = dict(pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'])
            self.assertEqual(actual, expected)
            self.assertNotEqual(actual['research.py'], profile['engine_source_hashes']['research.py'])
        for index, implementation in enumerate(pools.CORE_SPLIT_SIWC_PROFILE_V1['chatgpt_plan_implementations']):
            for name, expected in implementation['source_sha256'].items():
                raw = reviewed_source_bytes(ROOT, name, current=True).replace(b'\r\n', b'\n')
                self.assertEqual(
                    hashlib.sha256(
                        raw.replace(b'\n', b'\r\n') if index and name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py') else raw
                    ).hexdigest(),
                    expected,
                )

    def test_exact_selector_and_mixed_provider_refusal(self):
        item = {
            'engine_source_hashes': TRANSPORT['engine_source_hashes'],
            'prompt_template_hash': TRANSPORT['prompt_template_hash'],
            'provider': {'mode': 'fixture'},
        }
        self.assertIs(pools._select_producer(item), TRANSPORT)
        for index, implementation in enumerate(SIWC['chatgpt_plan_implementations']):
            for target in implementation['dependency_targets']:
                self.assertIs(pools._select_producer(binding(SIWC, index, target)), SIWC)
            mixed = binding(SIWC, index)
            mixed['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = pools.COMPLETED_ITEMS_SIWC_PROFILE_V1[
                'chatgpt_plan_implementations'
            ][index]['source_sha256']['desktop_chatgpt_provider.py']
            with self.assertRaises(saved_pool.SavedCandidatePoolError):
                pools._select_producer(mixed)

    def test_new_saved_sources_are_readonly_and_consumed_receipts_refused(self):
        from datetime import timedelta
        import sys
        from unittest.mock import patch
        from tests.saved_pool_fixtures import make_chatgpt_source, write_source

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, reference, original, state = make_chatgpt_source(root, producer=SIWC, candidates=1)
            arguments = dict(
                source_campaign_dir=folder,
                source_campaign_ref=reference,
                original_dataset=original,
                original_dataset_ref='SYNTHETIC-explicit-original',
                first_training_timestamp=max(bar.end for bar in original.bars) + timedelta(days=1),
                authoritative_registry_path=root / 'source-registry.sqlite3',
            )
            before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            with patch.dict(sys.modules, {'quantlab.assistant.adapters.chatgpt.auth': None, 'quantlab.assistant.adapters.chatgpt.provider': None}):
                result = pools.admit_saved_campaign_pool(**arguments)
                saved_pool_validation.validate_admission_snapshot(
                    result.admission, result.candidate_pool, profiles=pool_profiles.SUPPORTED_PRODUCERS, audited_producer=pool_profiles.AUDITED_PRODUCER
                )
            self.assertEqual(result.admission['producer'], SIWC)
            self.assertEqual({path: path.read_bytes() for path in root.rglob('*') if path.is_file()}, before)
            state['provider_receipts'][0]['status'] = 'user_confirmed_consumed'
            write_source(folder, state)
            with self.assertRaises(saved_pool.SavedCandidatePoolError) as caught:
                pools.admit_saved_campaign_pool(**arguments)
            self.assertEqual(caught.exception.reason_code, 'source_provider_receipt_invalid')


if __name__ == '__main__':
    unittest.main()
