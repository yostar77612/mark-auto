"""Synthetic-only atomic campaign exposure and historical admission compatibility."""

import ast
import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from quantlab import research
from quantlab import saved_candidate_pool as pools
from quantlab.core import Dataset, content_hash
from quantlab.research_core.domain.saved_pool import SavedCandidatePoolError
from tests.saved_pool_fixtures import make_saved_source
from tests.test_research import inputs


class CampaignExposureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = self.root / 'authority.sqlite3'
        self.data, self.config = inputs()
        manifest = dict(self.data.manifest)
        manifest['manifest_hash'] = content_hash(manifest)
        self.data = Dataset(self.data.bars, manifest, self.data.quality)
        self.config.update(families=['trend'], max_trials=1, max_improvements=0)
        self.config['ranking']['minimum'] = '-1000000'
        self.splits = research._campaign_config(self.data, self.config)
        self.protected = Dataset(self.splits['oos'].bars + self.splits['holdout'].bars, {}, {})
        self.folder = self.root / ('a' * 64)

    def reserve(self, data, campaign='prior'):
        return research._reserve_holdout(
            data,
            registry_path=self.registry,
            campaign_id=campaign,
            selection_hash='b' * 64,
            output_dir=self.root / campaign,
        )

    def inline(self, function, args, **kwargs):
        return {'value': function(*args), 'memory_limit_enforced': False}

    def run_campaign(self, *, worker=None, folder=None):
        with patch('quantlab.research._run_bounded', side_effect=worker or self.inline):
            return research.run_campaign(
                self.data,
                config=self.config,
                generator=research.FixtureGenerator(),
                output_dir=folder or self.folder,
                holdout_registry_path=self.registry,
            )

    def admit(self, state, folder=None, original=None):
        original = original or self.data
        folder = folder or self.folder
        return pools.admit_saved_campaign_pool(
            source_campaign_dir=folder,
            source_campaign_ref=folder.name,
            original_dataset=original,
            original_dataset_ref='synthetic-original',
            first_training_timestamp=original.bars[-1].end + timedelta(days=1),
            authoritative_registry_path=self.registry,
        )

    def test_union_is_committed_before_first_protected_evaluation(self):
        observed = []

        def worker(function, args, **kwargs):
            if function is research._evaluate_split and args[0].manifest['research_split']['name'] in ('oos', 'holdout'):
                for split in ('oos', 'holdout'):
                    observed.append(self.reserve(self.splits[split])['status'])
            return self.inline(function, args, **kwargs)

        state = self.run_campaign(worker=worker)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(observed, ['previously_consumed'] * 4)
        self.assertEqual(state['holdout_registry']['holdout_hash'], content_hash(self.protected.bars))
        self.assertEqual(self.admit(state).admission['producer'], pools.E1_EXPOSURE_PROFILE_V1)
        with closing(sqlite3.connect(self.registry)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_oos_only_overlap_blocks_both_without_partial_reservation(self):
        self.reserve(self.splits['oos'])
        state = self.run_campaign()
        self.assertEqual(state['status'], 'blocked_previously_consumed_holdout')
        self.assertEqual(state['evaluations'], {'oos': [], 'holdout': []})
        # Atomic rejection did not consume the otherwise fresh holdout.
        self.assertEqual(self.reserve(self.splits['holdout'])['status'], 'reserved_consumed')

    def test_holdout_only_overlap_does_not_partially_consume_oos(self):
        self.reserve(self.splits['holdout'])
        state = self.run_campaign()
        self.assertEqual(state['status'], 'blocked_previously_consumed_holdout')
        self.assertEqual(state['evaluations'], {'oos': [], 'holdout': []})
        self.assertEqual(self.reserve(self.splits['oos'])['status'], 'reserved_consumed')

    def test_evaluation_failure_never_refunds_or_retries_either_split(self):
        def fail(function, args, **kwargs):
            if function is research._evaluate_split and args[0].manifest['research_split']['name'] in ('oos', 'holdout'):
                raise RuntimeError('synthetic evaluation failure')
            return self.inline(function, args, **kwargs)

        state = self.run_campaign(worker=fail)
        self.assertTrue(state['holdout_consumed'])
        self.assertTrue(all(row['status'] == 'failed' for rows in state['evaluations'].values() for row in rows))
        self.assertEqual(self.run_campaign(worker=lambda *a, **k: self.fail('no retry')), state)
        other = self.run_campaign(folder=self.root / ('b' * 64))
        self.assertEqual(other['status'], 'blocked_previously_consumed_holdout')
        for split in ('oos', 'holdout'):
            self.assertEqual(self.reserve(self.splits[split])['status'], 'previously_consumed')

    def test_concurrent_union_reservations_have_only_one_winner(self):
        barrier = Barrier(2)

        def reserve(campaign):
            barrier.wait(timeout=5)
            return self.reserve(self.protected, campaign)['status']

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(reserve, ('first', 'second')))
        self.assertCountEqual(statuses, ['reserved_consumed', 'previously_consumed'])
        with closing(sqlite3.connect(self.registry)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM coverage').fetchone()[0], 1)

    def test_campaign_passes_its_deadline_into_shared_reservation(self):
        with patch('quantlab.research._reserve_holdout', wraps=research._reserve_holdout) as reserve:
            self.run_campaign()
        self.assertEqual(reserve.call_count, 1)
        self.assertIsInstance(reserve.call_args.kwargs['deadline'], float)
        self.assertEqual(reserve.call_args.args[0].bars, self.protected.bars)

    def test_new_profile_rejects_holdout_only_reservation_even_if_internally_consistent(self):
        folder, _, original, state = make_saved_source(
            self.root / 'forged',
            producer=pools.E1_EXPOSURE_PROFILE_V1,
            registry_path=self.registry,
            candidates=1,
        )
        with self.assertRaises(SavedCandidatePoolError):
            self.admit(state, folder, original)

    def test_historical_holdout_only_profile_admits_without_retroactive_oos_claim(self):
        folder, _, original, state = make_saved_source(
            self.root / 'historical',
            producer=pools.CORE_SPLIT_SIWC_PROFILE_V1,
            registry_path=self.registry,
            candidates=1,
        )
        before = self.registry.read_bytes()
        self.assertEqual(self.admit(state, folder, original).admission['producer'], pools.CORE_SPLIT_SIWC_PROFILE_V1)
        self.assertEqual(self.registry.read_bytes(), before)
        from quantlab.configuration import config_from_json

        config = dict(state['binding']['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        splits = research._campaign_config(original, config)
        self.assertEqual(self.reserve(splits['oos'])['status'], 'reserved_consumed')

    def test_missing_union_coverage_fails_admission(self):
        state = self.run_campaign()
        with closing(sqlite3.connect(self.registry)) as db, db:
            db.execute('UPDATE coverage SET start=?', (self.splits['holdout'].bars[0].timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),))
        with self.assertRaises(SavedCandidatePoolError):
            self.admit(state)

    def test_all_thirty_historical_profile_blocks_are_unchanged(self):
        raw = Path(pools.__file__).read_bytes().replace(b'\r\n', b'\n')
        lines = raw.splitlines(keepends=True)
        blocks = [
            b''.join(lines[node.lineno - 1 : node.end_lineno])
            for node in ast.parse(raw).body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'freeze'
        ]
        self.assertEqual(len(blocks), 31)
        self.assertEqual(hashlib.sha256(b''.join(blocks[:30])).hexdigest(), 'ee8714e467ca21e8840158757bc9ea85d7502551c746f4b20270bf45a244c8f9')
        profile = pools.E1_EXPOSURE_PROFILE_V1
        self.assertEqual(content_hash(profile), '77997c24313d2a0e6ed1c111ffa17411d85b5f3b02b8b83e3b334895dc63115c')
        expected = dict(pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'])
        expected['research.py'] = content_hash(Path(research.__file__).read_text(encoding='utf-8'))
        self.assertEqual(profile['engine_source_hashes'], expected)
        self.assertEqual(profile['result_source_hash_variants'], pools.CORE_SPLIT_SIWC_PROFILE_V1['result_source_hash_variants'])
        self.assertIs(pools.SUPPORTED_PRODUCERS[30], profile)


if __name__ == '__main__':
    unittest.main()
