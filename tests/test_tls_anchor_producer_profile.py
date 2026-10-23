"""Exact TLS trust-anchor producer identity; offline fixtures, never real OAuth."""

import hashlib
from pathlib import Path
import unittest

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.test_subscription_producer_profile import binding


PROFILE = pools.TLS_ANCHOR_SIWC_ANALYSIS_PROFILE_V1
PREVIOUS = pools.TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1
ROOT = Path(__file__).resolve().parents[1]


class TlsAnchorProducerProfileTests(unittest.TestCase):
    def test_previous_profile_identity_is_kept_and_new_one_is_last(self):
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 24)
        self.assertEqual(content_hash(PREVIOUS), 'ae17850d264a810ba51e499a50e28c72cc4f907a9f43c92ca07c282d1f11c632')
        self.assertEqual(pools.SUPPORTED_PRODUCERS[15], PREVIOUS)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[16], PROFILE)
        self.assertEqual(content_hash(PROFILE), 'e1262b61e647d3b716ce6451c184921f4d2b3b797317af152de0a2b460ccd492')
        self.assertNotEqual(content_hash(PROFILE), content_hash(PREVIOUS))

    def test_only_protocol_and_auth_provider_pins_differ(self):
        restored = to_dict(PROFILE)
        restored['protocol'] = PREVIOUS['protocol']
        for new, old in zip(restored['chatgpt_plan_implementations'], PREVIOUS['chatgpt_plan_implementations']):
            new['source_sha256'] = to_dict(old['source_sha256'])
        self.assertEqual(restored, PREVIOUS)

    def test_pins_match_reviewed_lf_and_crlf_bytes(self):
        for index, implementation in enumerate(PROFILE['chatgpt_plan_implementations']):
            for name, digest in implementation['source_sha256'].items():
                if name == 'desktop_chatgpt_provider.py':
                    # Provider bytes changed later (models limit); pin stays historical.
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
            item = binding(PROFILE, index)
            item['provider']['descriptor']['source_sha256']['desktop_chatgpt_auth.py'] = PREVIOUS['chatgpt_plan_implementations'][index]['source_sha256'][
                'desktop_chatgpt_auth.py'
            ]
            with self.assertRaises(pools.SavedCandidatePoolError):
                pools._select_producer(item)


if __name__ == '__main__':
    unittest.main()
