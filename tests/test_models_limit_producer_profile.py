"""Exact model-catalog-limit producer identity; offline fixtures, never real OAuth."""

import hashlib
from pathlib import Path
import unittest

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.test_subscription_producer_profile import binding


PROFILE = pools.MODELS_LIMIT_SIWC_ANALYSIS_PROFILE_V1
PREVIOUS = pools.TLS_ANCHOR_SIWC_ANALYSIS_PROFILE_V1
ROOT = Path(__file__).resolve().parents[1]


class ModelsLimitProducerProfileTests(unittest.TestCase):
    def test_previous_profile_identity_is_kept_and_new_one_is_last(self):
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 19)
        self.assertEqual(content_hash(PREVIOUS), 'e1262b61e647d3b716ce6451c184921f4d2b3b797317af152de0a2b460ccd492')
        self.assertEqual(pools.SUPPORTED_PRODUCERS[16], PREVIOUS)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[17], PROFILE)
        self.assertEqual(content_hash(PROFILE), '797b5bcfcf94f111144eda6cb6cc01a0c9cc6b24ec9aa2d9d9dec3b34d78c729')
        self.assertNotEqual(content_hash(PROFILE), content_hash(PREVIOUS))

    def test_only_protocol_and_provider_pins_differ(self):
        restored = to_dict(PROFILE)
        restored['protocol'] = PREVIOUS['protocol']
        for new, old in zip(restored['chatgpt_plan_implementations'], PREVIOUS['chatgpt_plan_implementations']):
            new['source_sha256']['desktop_chatgpt_provider.py'] = old['source_sha256']['desktop_chatgpt_provider.py']
        self.assertEqual(restored, PREVIOUS)

    def test_pins_match_reviewed_lf_and_crlf_bytes(self):
        for index, implementation in enumerate(PROFILE['chatgpt_plan_implementations']):
            for name, digest in implementation['source_sha256'].items():
                if name == 'desktop_chatgpt_provider.py':
                    # Provider bytes changed later (campaign catalog limit); pin stays historical.
                    continue
                raw = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                if index:
                    raw = raw.replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, name)

    def test_exact_tuples_select_their_own_identity_and_mixed_ones_reject(self):
        for profile in (PREVIOUS, PROFILE):
            for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    self.assertIs(pools._select_producer(binding(profile, index, target)), profile)
        for index in (0, 1):
            other = PROFILE['chatgpt_plan_implementations'][1 - index]['source_sha256']['desktop_chatgpt_provider.py']
            for digest in ('f' * 64, other):
                item = binding(PROFILE, index)
                item['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = digest
                with self.assertRaises(pools.SavedCandidatePoolError):
                    pools._select_producer(item)


if __name__ == '__main__':
    unittest.main()
