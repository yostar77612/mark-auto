"""Append-only atomic-promotion source identities; no historical relabelling."""

from quantlab.research_core.domain import saved_pool


import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from quantlab import saved_candidate_pool as pools
from quantlab.core import content_hash, to_dict
from tests.test_subscription_producer_profile import binding
from tests.test_unknown_reconciliation_producer_profile import HISTORICAL_HASHES, NEW_HASHES


class AtomicReplaceProducerProfileTests(unittest.TestCase):
    def test_all_twenty_six_historical_profiles_and_two_exact_new_profiles(self):
        historical = (
            HISTORICAL_HASHES
            + NEW_HASHES
            + [
                '6556b818ab781de47f75d358a928566ca334a745ed2876c9b766d5038b488bf8',
                '1d2c8d049113a97895710e41e180c6ac28f0a2307f45688a1a938508d43465a3',
                '0adfd0b63c351b39e2afba74312edf26fd47b5ab7277141be3068eacbf0e1677',
                '092877b654abacbf244e985a8d5d6a75785a4561be48b4d8cfd5f940cd44857d',
                '9a83126852a5a89a90fe939c930ac91badfaeb16ea239e2ee387ba2904cd7692',
            ]
        )
        self.assertEqual(len(historical), 26)
        self.assertEqual([content_hash(profile) for profile in pools.SUPPORTED_PRODUCERS[:26]], historical)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[26:28], (pools.ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, pools.ATOMIC_REPLACE_SIWC_PROFILE_V1))
        self.assertEqual(
            [content_hash(profile) for profile in pools.SUPPORTED_PRODUCERS[26:28]],
            ['6fed4a54f7ae165d371c8de3f0342250ad2e2ef7ff73f4aa012eb553872340b9', '3695cb133b077a16c71de64f00b3ac1f02b123928d0245c6a64a69404c3b5825'],
        )

    def test_only_protocol_and_research_pin_change_and_match_current_source(self):
        root = Path(__file__).resolve().parents[1]
        for old, new in (
            (pools.LONG_PATH_TRANSPORT_PROFILE_V1, pools.ATOMIC_REPLACE_TRANSPORT_PROFILE_V1),
            (pools.LONG_PATH_SIWC_PROFILE_V1, pools.ATOMIC_REPLACE_SIWC_PROFILE_V1),
        ):
            actual = {name: content_hash((root / 'quantlab' / name).read_text(encoding='utf-8')) for name in new['engine_source_hashes']}
            self.assertEqual(actual, {name: pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'][name] for name in actual})
            self.assertEqual(new['engine_source_hashes']['research.py'], 'c6d3f1b4b13154c1bf90e6be5a664ac390edc20fb5c544dd909485dfe5fe2ae6')
            restored = to_dict(new)
            restored['protocol'] = old['protocol']
            restored['engine_source_hashes']['research.py'] = old['engine_source_hashes']['research.py']
            self.assertEqual(restored, to_dict(old))
            with self.assertRaises(TypeError):
                new['engine_source_hashes']['research.py'] = 'f' * 64

    def test_old_new_exact_identity_selection_mixed_and_ambiguous_rejection(self):
        for profile in (pools.LONG_PATH_TRANSPORT_PROFILE_V1, pools.ATOMIC_REPLACE_TRANSPORT_PROFILE_V1):
            for mode in ('fixture', 'openai_compatible'):
                item = {
                    'engine_source_hashes': to_dict(profile['engine_source_hashes']),
                    'prompt_template_hash': profile['prompt_template_hash'],
                    'provider': {'mode': mode},
                }
                self.assertIs(pools._select_producer(item), profile)
                mixed = copy.deepcopy(item)
                mixed['engine_source_hashes']['core.py'] = 'f' * 64
                with self.assertRaises(saved_pool.SavedCandidatePoolError):
                    pools._select_producer(mixed)
        for profile in (pools.LONG_PATH_SIWC_PROFILE_V1, pools.ATOMIC_REPLACE_SIWC_PROFILE_V1):
            for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    item = binding(profile, index, target)
                    self.assertIs(pools._select_producer(item), profile)
                    mixed = copy.deepcopy(item)
                    mixed['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = 'f' * 64
                    with self.assertRaises(saved_pool.SavedCandidatePoolError):
                        pools._select_producer(mixed)
                with patch.object(pools, 'SUPPORTED_PRODUCERS', pools.SUPPORTED_PRODUCERS + (profile,)):
                    with self.assertRaises(saved_pool.SavedCandidatePoolError):
                        pools._select_producer(binding(profile, index))
