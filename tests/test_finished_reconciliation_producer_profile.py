"""Frozen R2 producer addition, preserving all historical source identities."""

import hashlib
from pathlib import Path
import unittest

from quantlab.core import content_hash, to_dict
from quantlab import saved_candidate_pool as pools
from tests.test_subscription_producer_profile import binding
from tests.test_unknown_reconciliation_producer_profile import HISTORICAL_HASHES, NEW_HASHES as R1_HASHES

ROOT = Path(__file__).resolve().parents[1]
R1_SIWC = pools.UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1
SIWC = pools.FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1
NEW_HASH = content_hash(SIWC)


class FinishedReconciliationProducerProfileTests(unittest.TestCase):
    def test_all_twenty_one_earlier_profiles_keep_exact_identity(self):
        self.assertEqual([content_hash(p) for p in pools.SUPPORTED_PRODUCERS[:21]], HISTORICAL_HASHES + R1_HASHES)
        self.assertEqual(pools.SUPPORTED_PRODUCERS[21:22], (SIWC,))
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 24)
        with self.assertRaises(TypeError):
            SIWC['protocol'] = 'rewritten'

    def test_only_the_protocol_and_provider_source_pins_change(self):
        restored = to_dict(SIWC)
        restored['protocol'] = R1_SIWC['protocol']
        for new, old in zip(restored['chatgpt_plan_implementations'], R1_SIWC['chatgpt_plan_implementations']):
            self.assertNotEqual(new['source_sha256']['desktop_chatgpt_provider.py'], old['source_sha256']['desktop_chatgpt_provider.py'])
            new['source_sha256']['desktop_chatgpt_provider.py'] = old['source_sha256']['desktop_chatgpt_provider.py']
        self.assertEqual(restored, to_dict(R1_SIWC))

    def test_new_literal_sources_match_current_engine_and_lf_crlf_provider(self):
        self.assertEqual(
            {name: content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')) for name in SIWC['engine_source_hashes']},
            SIWC['engine_source_hashes'],
        )
        # Headerless-stream re-pin: current provider bytes now match the newest profile; this
        # profile's own literals stay pinned by test_stream_content_type_producer_profile.
        latest = pools.COMPLETED_ITEMS_SIWC_PROFILE_V1
        for index, implementation in enumerate(latest['chatgpt_plan_implementations']):
            for name, digest in implementation['source_sha256'].items():
                raw = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                if index:
                    raw = raw.replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)

    def test_new_and_previous_exact_tuples_select_only_their_own_profile(self):
        for profile in (R1_SIWC, SIWC):
            for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    self.assertIs(pools._select_producer(binding(profile, index, target)), profile)

    def test_mixed_previous_new_or_unknown_provider_tuples_are_rejected(self):
        for index in (0, 1):
            for value in (
                SIWC['chatgpt_plan_implementations'][1 - index]['source_sha256']['desktop_chatgpt_provider.py'],
                'f' * 64,
            ):
                item = binding(SIWC, index)
                item['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = value
                with self.subTest(index=index, value=value[:8]), self.assertRaises(pools.SavedCandidatePoolError):
                    pools._select_producer(item)
            item = binding(SIWC, index)
            item['engine_source_hashes']['research.py'] = 'f' * 64
            with self.assertRaises(pools.SavedCandidatePoolError):
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


if __name__ == '__main__':
    unittest.main()
