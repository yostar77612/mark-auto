"""Synthetic-only fixed-pool walk-forward acceptance. No network, model or broker."""
import copy
import json
import multiprocessing
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext, Inexact
from pathlib import Path
from unittest.mock import patch

from quantlab.core import Bar, Dataset, StrategySpec, ValidationError, content_hash, to_dict
from quantlab.reporting import demo_config, synthetic_dataset
from quantlab.research import _reserve_holdout, ResourceTimeout
from quantlab.walk_forward import (WalkForwardFold, WalkForwardPlan,
    build_walk_forward_plan, walk_forward_plan_from_dict, run_walk_forward,
    read_walk_forward_state, reconcile_interrupted_walk_forward)


def inputs(**options):
    dataset = synthetic_dataset(240)
    cycle = (-120, -80, -40, 0, 40, 80, 120, 80, 40, 0, -40, -80)
    bars = []
    for index, bar in enumerate(dataset.bars):
        price = Decimal(20000 + cycle[index % len(cycle)])
        bars.append(replace(bar, open=price, high=price + 2, low=price - 2, close=price))
    manifest = {**dataset.manifest, 'source_hash': content_hash(tuple(bars)), 'data_hash': content_hash(tuple(bars))}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    dataset = Dataset(tuple(bars), manifest, dict(dataset.quality))
    options.setdefault('ranking', {'metric': 'net_pnl', 'minimum': '-1000000', 'min_trades': 1, 'max_drawdown_pct': '0.10'})
    if 'fork' in multiprocessing.get_all_start_methods():
        options.setdefault('process_start_method', 'fork')
    plan = build_walk_forward_plan(backtest_config=demo_config(), train_bars=60,
        validation_bars=40, oos_bars=40, fold_count=3, final_holdout=(220, 240), **options)
    return dataset, plan


def fake_worker(function, args, **kwargs):
    dataset, spec, _ = args
    part = dataset.manifest['walk_forward_split']
    fold, role = part['fold'], part['role']
    # A predetermined scoring fixture makes the selected family visibly change.
    winning_family = ('trend', 'momentum', 'mean_reversion')[fold % 3]
    score = '100' if spec.family == winning_family else '0'
    value = {'metrics': {'net_pnl': score, 'trade_count': 1, 'max_drawdown_pct': '0.01'}, 'warnings': [],
             'result_hash': content_hash([dataset.bars, spec, role]), 'manifest': {}}
    return {'status': 'ok', 'value': value, 'memory_limit_enforced': False}


def alter_prices(dataset, start, end):
    bars = list(dataset.bars)
    for index in range(start, end):
        b = bars[index]
        bars[index] = Bar(b.timestamp, b.end, b.trade_date, b.session, b.contract_id,
            b.open + 500, b.high + 500, b.low + 500, b.close + 500, b.volume, b.source_id)
    manifest = {**dataset.manifest, 'data_hash': content_hash(tuple(bars))}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    return Dataset(tuple(bars), manifest, dict(dataset.quality))


class WalkForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / 'run'
        self.registry = self.root / 'controls' / 'holdout.sqlite3'
        self.data, self.plan = inputs()

    def tearDown(self):
        self.temp.cleanup()

    def run_plan(self, *, dataset=None, plan=None, output=None, registry=None, **kwargs):
        return run_walk_forward(dataset or self.data, plan=plan or self.plan,
            output_dir=output or self.output, holdout_registry_path=registry or self.registry, **kwargs)

    def test_typed_plan_round_trip_and_immutable_aliases(self):
        value = to_dict(self.plan)
        plan = walk_forward_plan_from_dict(value)
        self.assertEqual(to_dict(plan), value)
        value['ranking']['minimum'] = '9999'
        value['folds'][0]['train'][0] = 10
        self.assertEqual(plan.ranking['minimum'], '-1000000')
        self.assertEqual(plan.folds[0].train, (0, 60))
        with self.assertRaises(TypeError):
            plan.ranking['minimum'] = '1'

    def test_rolling_and_expanding_have_genuine_forward_windows(self):
        self.assertEqual(self.plan.folds[1], WalkForwardFold((40, 100), (100, 140), (140, 180)))
        _, plan = inputs(mode='expanding')
        self.assertEqual(plan.folds[1].train, (0, 100))
        self.assertEqual(plan.folds[2].train, (0, 140))
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            result = self.run_plan(plan=plan)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([f['selection']['spec']['family'] for f in result['folds']], ['trend', 'momentum', 'mean_reversion'])

    def test_invalid_windows_and_types_reject_before_io(self):
        changes = [dict(mode='purge'), dict(folds=self.plan.folds[:1]), dict(max_evaluations=True),
                   dict(max_evaluations=221), dict(max_runtime_seconds=0), dict(max_bars=True),
                   dict(final_holdout=(200, 240)), dict(gap_bars=1),
                   dict(folds=(self.plan.folds[0], self.plan.folds[0])),
                   dict(folds=(self.plan.folds[0], WalkForwardFold((30, 90), (90, 130), (130, 170))))]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                replace(self.plan, **change)
        with self.assertRaises(ValidationError):
            WalkForwardFold((False, 60), (60, 100), (100, 140))
        with self.assertRaises(ValidationError):
            build_walk_forward_plan(backtest_config=demo_config(), train_bars=60,
                validation_bars=40, oos_bars=40, step_bars=39, fold_count=3, final_holdout=(220, 240))
        self.assertFalse(self.output.exists())

    def test_explicit_gaps_preserved_in_plan_and_excluded_from_splits(self):
        plan = build_walk_forward_plan(backtest_config=demo_config(), train_bars=50,
            validation_bars=30, oos_bars=30, fold_count=3, gap_bars=5, final_holdout=(200, 240))
        seen = []
        def spy(function, args, **kwargs):
            seen.append(args[0].manifest['walk_forward_split'])
            return fake_worker(function, args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=spy):
            result = self.run_plan(plan=plan)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(plan.folds[0], WalkForwardFold((0, 50), (55, 85), (90, 120)))
        self.assertTrue(all(part['role'] != 'holdout' for part in seen))
        self.assertTrue(all(part['end'] <= 180 for part in seen))

    def test_non_synthetic_or_unknown_exposure_refuses_without_registry_or_output(self):
        for source in ('official_local', 'proxy'):
            data = self.labelled_fixture(source)
            with self.subTest(source=source), self.assertRaisesRegex(ValidationError, 'exposure provenance'):
                self.run_plan(dataset=data)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.registry.exists())

    def labelled_fixture(self, source_type):
        # Generated bars, not official observations; only classification routing is tested.
        manifest = {**self.data.manifest, 'source_type': source_type}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        return Dataset(self.data.bars, manifest, dict(self.data.quality))

    def test_explicit_historical_replay_is_never_independent_rankable_or_paper_eligible(self):
        plan = replace(self.plan, evidence_mode='historical_replay', backtest_config=replace(
            self.plan.backtest_config, instrument_expiries={'TAIFEX:TMF:202601': '2026-01-21'}))
        for source in ('official_local', 'proxy'):
            with self.subTest(source=source):
                result = self.run_plan(dataset=self.labelled_fixture(source), plan=plan,
                    output=self.root / source, registry=self.root / (source + '.sqlite3'))
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['scope'], 'historical_replay_exposure_unverified')
                self.assertEqual(result['exposure_status'], 'unverified')
                for section in (result, result['summary']):
                    self.assertEqual(section['evidence_mode'], 'historical_replay')
                    self.assertFalse(section['independent_oos'])
                    self.assertFalse(section['ranking_eligible'])
                    self.assertFalse(section['paper_eligible'])
                self.assertEqual(result['final_holdout_status'], 'excluded_not_evaluated')

    def test_historical_replay_requires_expiry_and_never_bypasses_consumed_ranges(self):
        data = self.labelled_fixture('official_local')
        plan = replace(self.plan, evidence_mode='historical_replay')
        with self.assertRaisesRegex(ValidationError, 'expiries'):
            self.run_plan(dataset=data, plan=plan)
        self.assertFalse(self.registry.exists())
        plan = replace(plan, backtest_config=replace(plan.backtest_config,
            instrument_expiries={'TAIFEX:TMF:202601': '2026-01-21'}))
        _reserve_holdout(Dataset(data.bars[:30], {}, {}), registry_path=self.registry,
            campaign_id='consumed', selection_hash='consumed', output_dir=self.root / 'old')
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('cannot bypass')):
            result = self.run_plan(dataset=data, plan=plan)
        self.assertEqual(result['status'], 'blocked_previously_consumed_range')
        self.assertEqual(result['evaluations'], [])

    def test_evidence_mode_is_explicit_bound_and_cannot_claim_formal_unseen(self):
        with self.assertRaises(ValidationError):
            replace(self.plan, evidence_mode='formal_unseen')
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            first = self.run_plan()
        self.assertEqual(first['evidence_mode'], 'synthetic_validation')
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            self.run_plan(plan=replace(self.plan, evidence_mode='historical_replay'))

    def test_hash_quality_event_overlap_and_bar_budget_reject(self):
        invalid = [Dataset(self.data.bars, {**self.data.manifest, 'data_hash': '0' * 64}, dict(self.data.quality)),
                   Dataset(self.data.bars, dict(self.data.manifest), {'valid': True, 'missing_intervals': 1})]
        for data in invalid:
            with self.assertRaises(ValidationError):
                self.run_plan(dataset=data)
        with self.assertRaises(ValidationError):
            self.run_plan(plan=replace(self.plan, max_bars=239))
        with self.assertRaises(ValidationError):
            self.run_plan(plan=replace(self.plan, final_holdout=(220, 239)))
        bars = list(self.data.bars)
        bars[1] = replace(bars[1], timestamp=bars[0].timestamp)
        with self.assertRaises(ValidationError):
            self.run_plan(dataset=Dataset(tuple(bars), {**self.data.manifest, 'data_hash': content_hash(tuple(bars))}, dict(self.data.quality)))

    def test_custom_renamed_subset_or_future_trained_pool_cannot_claim_builtin_origin(self):
        pool = list(self.plan.candidate_pool)
        pool[0] = StrategySpec('trained_in_future', 'trend', {'fast': 2, 'slow': 8}, {})
        for value in (tuple(pool), self.plan.candidate_pool[:-1], self.plan.candidate_pool[::-1]):
            with self.assertRaisesRegex(ValidationError, 'exact five'):
                replace(self.plan, candidate_pool=value)
        payload = to_dict(self.plan)
        payload['candidate_provenance'] = {'origin': 'verified', 'trained_through': '1900-01-01'}
        with self.assertRaises(ValidationError):
            walk_forward_plan_from_dict(payload)

    def test_each_fold_freezes_selection_before_oos_and_never_calls_campaign_or_generator(self):
        calls = []
        def spy(function, args, **kwargs):
            split = args[0].manifest['walk_forward_split']
            calls.append((split['fold'], split['role']))
            if split['role'] == 'oos':
                saved = read_walk_forward_state(self.output)
                fold = saved['folds'][split['fold']]
                self.assertEqual(fold['status'], 'selection_frozen')
                self.assertEqual(fold['selection_hash'], content_hash(fold['selection']))
                self.assertEqual(saved['evaluations'][-1]['status'], 'running')
                self.assertEqual(saved['registry_reservation']['status'], 'reserved_consumed')
            return fake_worker(function, args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=spy), \
             patch('quantlab.research.run_campaign', side_effect=AssertionError('not a fold wrapper')), \
             patch('quantlab.research._generate_candidate', side_effect=AssertionError('no model')):
            result = self.run_plan()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(calls), 33)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['summary']['evaluations_reserved'], 33)
        self.assertEqual(result['final_holdout_status'], 'excluded_not_evaluated')
        self.assertEqual(result['summary']['strategy_qualification'], 'not_assessed')
        self.assertIsNone(result['summary']['portfolio_return'])
        self.assertEqual(len({f['selection']['strategy_hash'] for f in result['folds']}), 3)
        with closing(sqlite3.connect(self.registry)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_actual_core_backtests_multiple_folds_deterministically(self):
        first = self.run_plan()
        second = self.run_plan(output=self.root / 'independent', registry=self.root / 'independent-controls.sqlite3')
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(first['summary']['evaluated_oos_folds'], 3)
        self.assertEqual(first['folds'], second['folds'])
        self.assertEqual(first['evaluations'], second['evaluations'])
        self.assertNotEqual(first['experiment_id'], second['experiment_id'])

    def test_actual_oos_price_mutation_cannot_change_that_folds_selection(self):
        first = self.run_plan()
        changed = alter_prices(self.data, 100, 140)
        second = self.run_plan(dataset=changed, output=self.root / 'changed', registry=self.root / 'changed-controls.sqlite3')
        self.assertEqual(first['folds'][0]['selection'], second['folds'][0]['selection'])
        self.assertEqual(first['folds'][0]['selection_hash'], second['folds'][0]['selection_hash'])
        self.assertEqual(first['folds'][0]['candidates'], second['folds'][0]['candidates'])

    def test_actual_final_holdout_mutation_changes_no_fold_result(self):
        first = self.run_plan()
        second = self.run_plan(dataset=alter_prices(self.data, 220, 240), output=self.root / 'changed', registry=self.root / 'changed-controls.sqlite3')
        self.assertNotEqual(first['binding']['source_data_hash'], second['binding']['source_data_hash'])
        self.assertEqual(first['folds'], second['folds'])
        self.assertEqual(first['evaluations'], second['evaluations'])

    def test_global_budget_does_not_reset_each_fold(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as worker:
            result = self.run_plan(plan=replace(self.plan, max_evaluations=12))
            reopened = self.run_plan(plan=replace(self.plan, max_evaluations=12))
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(result['summary']['evaluations_reserved'], 12)
        self.assertEqual(result['summary']['evaluated_oos_folds'], 1)
        self.assertEqual(worker.call_count, 12)
        self.assertEqual(result, reopened)
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            self.run_plan(plan=replace(self.plan, max_evaluations=13))

    def test_worker_failure_is_recorded_consumes_slot_and_is_not_retried(self):
        count = 0
        def flaky(function, args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError('private fixture text must not be persisted')
            return fake_worker(function, args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=flaky):
            result = self.run_plan()
        self.assertEqual(result['status'], 'completed_with_errors')
        self.assertEqual(result['evaluations'][0]['status'], 'failed')
        self.assertEqual(count, 33)
        self.assertNotIn('private fixture', json.dumps(result))

    def test_runtime_timeout_stops_all_folds_and_retains_reservation(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=ResourceTimeout('fixture')) as worker:
            result = self.run_plan()
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(result['evaluations'][0]['status'], 'timed_out')
        self.assertEqual(result['registry_reservation']['status'], 'reserved_consumed')
        self.assertEqual(result['summary']['evaluations_reserved'], 1)

    def test_cancellation_retains_slots_and_ranges_and_reopen_does_not_replay(self):
        calls = 0
        def worker(function, args, **kwargs):
            nonlocal calls
            calls += 1
            return fake_worker(function, args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=worker):
            result = self.run_plan(cancelled=lambda: calls >= 3)
            reopened = self.run_plan()
            renamed = self.run_plan(output=self.root / 'renamed')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['summary']['evaluations_reserved'], 3)
        self.assertEqual(result, reopened)
        self.assertEqual(renamed['status'], 'blocked_previously_consumed_range')
        self.assertEqual(renamed['evaluations'], [])
        self.assertEqual(calls, 3)

    def test_crash_reconcile_requires_quiescence_and_cannot_replay(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=KeyboardInterrupt('inert crash')):
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan()
        before = read_walk_forward_state(self.output)
        self.assertEqual(before['status'], 'running')
        self.assertEqual(before['evaluations'][0]['status'], 'running')
        with self.assertRaisesRegex(ValidationError, 'descendants'):
            reconcile_interrupted_walk_forward(output_dir=self.output)
        result = reconcile_interrupted_walk_forward(output_dir=self.output, descendants_stopped=True)
        self.assertEqual(result['status'], 'blocked_interrupted')
        self.assertEqual(result['evaluations'][0]['status'], 'interrupted')
        self.assertEqual(result['registry_reservation']['status'], 'reserved_consumed')
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('cannot retry')):
            self.assertEqual(result, self.run_plan())
        self.assertEqual(result, reconcile_interrupted_walk_forward(output_dir=self.output, descendants_stopped=True))

    def test_crash_reopen_is_terminal_even_without_explicit_reconcile(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=SystemExit('inert crash')):
            with self.assertRaises(SystemExit):
                self.run_plan()
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('cannot retry')):
            result = self.run_plan()
        self.assertEqual(result['status'], 'blocked_interrupted')
        self.assertEqual(result['evaluations'][0]['status'], 'interrupted')

    def test_prior_consumed_ranges_reject_train_validation_oos_and_final_holdout(self):
        for name, bounds in [('train', (0, 40)), ('validation', (60, 80)), ('oos', (120, 140)), ('holdout', (225, 235))]:
            with self.subTest(name=name):
                registry = self.root / (name + '.sqlite3')
                source = Dataset(self.data.bars[bounds[0]:bounds[1]], {}, {})
                _reserve_holdout(source, registry_path=registry, campaign_id='old', selection_hash='old', output_dir=self.root / 'old')
                with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('must block before scoring')):
                    result = self.run_plan(output=self.root / name, registry=registry)
                self.assertEqual(result['status'], 'blocked_previously_consumed_range')
                self.assertEqual(result['evaluations'], [])

    def test_default_holdout_callers_cannot_reconsume_new_walk_forward_oos(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            self.run_plan()
        source = Dataset(self.data.bars[110:130], {}, {})
        reservation = _reserve_holdout(source, registry_path=self.registry,
            campaign_id='legacy-new-campaign', selection_hash='legacy', output_dir=self.root / 'legacy')
        self.assertEqual(reservation['status'], 'previously_consumed')
        # Final holdout was checked for conflicts, never reserved or evaluated.
        excluded = Dataset(self.data.bars[220:240], {}, {})
        reservation = _reserve_holdout(excluded, registry_path=self.registry,
            campaign_id='later', selection_hash='later', output_dir=self.root / 'later')
        self.assertEqual(reservation['status'], 'reserved_consumed')

    def test_changed_source_config_or_name_cannot_reset_range_consumption(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as worker:
            first = self.run_plan()
            for index, (dataset, plan) in enumerate([(alter_prices(self.data, 100, 140), self.plan),
                    (self.data, replace(self.plan, ranking={'metric': 'net_pnl', 'minimum': '-999999', 'min_trades': 1, 'max_drawdown_pct': '0.10'}))]):
                result = self.run_plan(dataset=dataset, plan=plan, output=self.root / str(index))
                self.assertEqual(result['status'], 'blocked_previously_consumed_range')
            self.assertEqual(worker.call_count, 33)
        self.assertEqual(first, read_walk_forward_state(self.output))

    def test_completed_reopen_returns_exact_persisted_state_and_old_files_unchanged(self):
        old = self.root / 'old-campaign.sqlite3'
        old.write_bytes(b'inert immutable old evidence')
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as worker:
            first = self.run_plan()
            bytes_before = (self.output / 'walk_forward.json').read_bytes()
            second = self.run_plan()
        self.assertEqual(first, second)
        self.assertEqual(bytes_before, (self.output / 'walk_forward.json').read_bytes())
        self.assertEqual(old.read_bytes(), b'inert immutable old evidence')
        self.assertEqual(worker.call_count, 33)
        self.assertNotEqual(first['binding']['source_hashes']['walk_forward.py'], '')
        self.assertEqual(first['binding']['registry_identity']['resolved_path'], str(self.registry.resolve()))
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            self.run_plan(registry=self.root / 'different.sqlite3')
        with self.assertRaisesRegex(ValidationError, 'outside'):
            self.run_plan(output=self.root / 'bad', registry=self.root / 'bad' / 'registry.sqlite3')

    def test_concurrent_same_output_does_not_duplicate_work(self):
        entered, release = threading.Event(), threading.Event()
        def worker(function, args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test barrier timed out')
            return fake_worker(function, args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=worker) as mocked, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.run_plan)
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaisesRegex(ValidationError, 'already running'):
                    self.run_plan()
            finally:
                release.set()
            result = future.result(timeout=20)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(mocked.call_count, 33)

    def test_concurrent_different_names_reserve_shared_ranges_once(self):
        barrier = threading.Barrier(2)
        def runner(index):
            barrier.wait(timeout=5)
            return self.run_plan(output=self.root / str(index))
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(runner, (1, 2)))
        self.assertEqual(sorted(r['status'] for r in results), ['blocked_previously_consumed_range', 'completed'])
        self.assertEqual(sum(len(r['evaluations']) for r in results), 33)
        with closing(sqlite3.connect(self.registry)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_validation_risk_and_trade_gates_precede_profit_ordering(self):
        cases = [('0.20', 1, 'mean_reversion'), ('0.10', 1, 'trend'),
                 ('0.01', 0, 'mean_reversion'), (None, 1, 'mean_reversion'),
                 ('NaN', 1, 'mean_reversion'), ('-0.01', 1, 'mean_reversion')]
        for index, (drawdown, trades, expected) in enumerate(cases):
            def worker(function, args, **kwargs):
                result = fake_worker(function, args, **kwargs)
                result['value']['metrics'].update(net_pnl='100' if args[1].family == 'trend' else '0',
                                                 trade_count=trades if args[1].family == 'trend' else 1,
                                                 max_drawdown_pct=drawdown if args[1].family == 'trend' else '0.01')
                return result
            with self.subTest(drawdown=drawdown, trades=trades), patch('quantlab.walk_forward._run_bounded', side_effect=worker):
                result = self.run_plan(output=self.root / str(index), registry=self.root / (str(index) + '.sqlite3'))
            self.assertEqual(result['folds'][0]['selection']['spec']['family'], expected)
            self.assertIn('max_drawdown_pct', result['folds'][0]['candidates'][0]['train']['result']['metrics'])

    def test_risk_defaults_and_invalid_thresholds_are_explicit_and_immutable(self):
        plan = build_walk_forward_plan(backtest_config=demo_config(), train_bars=60,
            validation_bars=40, oos_bars=40, fold_count=3, final_holdout=(220, 240))
        self.assertEqual(plan.ranking['max_drawdown_pct'], '0.10')
        self.assertEqual(plan.ranking['min_trades'], 1)
        for cap in ('-0.01', '1.01', 'NaN', 'Infinity', True, '1e-1000000'):
            with self.subTest(cap=cap), self.assertRaises(ValidationError):
                replace(self.plan, ranking={**self.plan.ranking, 'max_drawdown_pct': cap})
        with self.assertRaises(ValidationError):
            replace(self.plan, ranking={**self.plan.ranking, 'min_trades': 0})
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            self.run_plan()
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            self.run_plan(plan=replace(self.plan, ranking={**self.plan.ranking, 'max_drawdown_pct': '0.20'}))

    def test_selection_is_independent_of_decimal_precision_and_inexact_traps(self):
        def worker(function, args, **kwargs):
            result = fake_worker(function, args, **kwargs)
            result['value']['metrics']['net_pnl'] = '123.457' if args[1].family == 'mean_reversion' else '123.456'
            return result
        with patch('quantlab.walk_forward._run_bounded', side_effect=worker), localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            low = self.run_plan()
        with patch('quantlab.walk_forward._run_bounded', side_effect=worker):
            high = self.run_plan(output=self.root / 'high', registry=self.root / 'high.sqlite3')
        self.assertEqual(low['folds'], high['folds'])
        self.assertTrue(all(f['selection']['spec']['family'] == 'mean_reversion' for f in low['folds']))

    def test_numeric_resource_bounds_precede_conversion_and_hashing(self):
        payload = to_dict(self.plan)
        payload['backtest_config']['initial_cash'] = '1e-1000000'
        with patch('quantlab.__main__.config_from_json', side_effect=AssertionError('conversion must not run')):
            with self.assertRaises(ValidationError):
                walk_forward_plan_from_dict(payload)
        config = replace(self.plan.backtest_config, initial_cash=Decimal('1e-1000000'))
        with self.assertRaises(ValidationError):
            replace(self.plan, backtest_config=config)
        huge = Decimal('1e1000000000')
        bars = list(self.data.bars)
        bars[0] = replace(bars[0], open=huge, high=huge, low=huge, close=huge)
        data = Dataset(tuple(bars), dict(self.data.manifest), dict(self.data.quality))
        with patch('quantlab.walk_forward.validate_dataset', side_effect=AssertionError('must reject before serialization')):
            with self.assertRaises(ValidationError):
                self.run_plan(dataset=data)
        oversized = to_dict(self.plan)
        oversized['backtest_config']['source_commit'] = 'x' * 16385
        with self.assertRaises(ValidationError):
            walk_forward_plan_from_dict(oversized)

    def test_unsupported_cross_split_event_config_rejects_before_io(self):
        for config in (replace(self.plan.backtest_config, roll_events=({'fixture': 'event'},)),
                       replace(self.plan.backtest_config, settlement_events=({'fixture': 'event'},)),
                       replace(self.plan.backtest_config, settlement_mode='daily_mtm')):
            with self.assertRaisesRegex(ValidationError, 'split-scoped'):
                replace(self.plan, backtest_config=config)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.registry.exists())

    def test_completed_journal_tampering_fails_even_with_recomputed_checksum(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            original = self.run_plan()
        def wrong_selection(state):
            state['folds'][0]['selection']['spec']['strategy_id'] = 'forged'
            state['folds'][0]['selection_hash'] = content_hash(state['folds'][0]['selection'])
        mutations = [wrong_selection,
            lambda s: s.update(model_calls=99),
            lambda s: s.update(exposure_status='verified'),
            lambda s: s.update(scope='independent_verified_oos'),
            lambda s: s['summary'].update(evaluations_reserved=1),
            lambda s: s['evaluations'].__setitem__(0, {**s['evaluations'][0], 'status': 'running'}),
            lambda s: s.update(evaluations=s['evaluations'][:1])]
        for index, mutate in enumerate(mutations):
            altered = copy.deepcopy(original)
            mutate(altered)
            altered['state_hash'] = content_hash({k: v for k, v in altered.items() if k != 'state_hash'})
            raw = json.dumps(altered)
            with closing(sqlite3.connect(self.output / 'walk_forward.sqlite3')) as db, db:
                db.execute('UPDATE state SET payload=? WHERE id=1', (raw,))
            with self.subTest(index=index), self.assertRaises(ValidationError):
                read_walk_forward_state(self.output)

    def test_registry_lock_cannot_overrun_deadline_or_reserve_after_it(self):
        first = self.data.bars[0]
        past = replace(first, timestamp=first.timestamp - timedelta(days=1), end=first.end - timedelta(days=1))
        _reserve_holdout(Dataset((past,), {}, {}), registry_path=self.registry,
            campaign_id='past', selection_hash='past', output_dir=self.root / 'past')
        with closing(sqlite3.connect(self.registry)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(self.run_plan, plan=replace(self.plan, max_runtime_seconds=1)).result(timeout=2.5)
            elapsed = time.monotonic() - started
            blocker.rollback()
        self.assertLess(elapsed, 2)
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(result['evaluations'], [])
        self.assertIsNone(result['registry_reservation'])
        with closing(sqlite3.connect(self.registry)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_no_eligible_candidate_is_explicit_not_a_profitable_pass(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            result = self.run_plan(plan=replace(self.plan, ranking={'metric': 'net_pnl', 'minimum': '1000', 'min_trades': 1, 'max_drawdown_pct': '0.10'}))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['summary']['evaluated_oos_folds'], 0)
        self.assertEqual(result['summary']['evaluations_reserved'], 30)
        self.assertTrue(all(f['status'] == 'no_eligible_candidate' and f['selection'] is None for f in result['folds']))
        self.assertEqual(result['summary']['strategy_qualification'], 'not_assessed')


if __name__ == '__main__':
    unittest.main()
