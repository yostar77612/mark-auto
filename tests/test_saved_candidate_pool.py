"""Generated-only source admission and fixed saved-pool walk-forward adversaries."""
import copy
import sys
import shutil
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from quantlab.core import Dataset, ValidationError, canonical_json, content_hash, to_dict
from quantlab.reporting import save_dataset
from quantlab.research import _reserve_holdout, run_campaign, FixtureGenerator, demo_campaign_config
from quantlab.saved_candidate_pool import (AUDITED_PRODUCER, CURRENT_PRODUCER, CURRENT_CHATGPT_PROFILE_V2, MAX_AUDIT_BYTES, SavedCandidatePoolError,
    admit_saved_campaign_pool, load_original_dataset, TRANSPORT_VERIFIER_PRODUCER,
    TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2, SUPPORTED_PRODUCERS)
from quantlab.walk_forward import (build_walk_forward_plan, planned_evaluations,
    read_walk_forward_state, run_walk_forward, walk_forward_plan_from_dict)
from tests.saved_pool_fixtures import make_saved_source, make_chatgpt_source, write_source, shifted_dataset
from tests.test_walk_forward import inputs, fake_worker, alter_prices


class SavedCandidatePoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder, self.ref, self.original, self.state = make_saved_source(self.root / 'campaigns')
        self.data, self.builtin = inputs()
        self.registry = self.folder.parent / 'source-registry.sqlite3'
        self.initial_registry_bytes = self.registry.read_bytes()
        self.output = self.root / 'wfo'
        self.original_path = self.root / 'selected-original.json'
        save_dataset(self.original, self.original_path)

    def tearDown(self):
        self.temp.cleanup()

    def admit(self, **changes):
        values = dict(source_campaign_dir=self.folder, source_campaign_ref=self.ref,
                      original_dataset=self.original, original_dataset_ref=str(self.original_path),
                      first_training_timestamp=self.data.bars[0].timestamp,
                      authoritative_registry_path=(Path(changes['source_campaign_dir']).parent / 'source-registry.sqlite3'
                          if 'source_campaign_dir' in changes else self.registry))
        values.update(changes)
        return admit_saved_campaign_pool(**values)

    def plan(self, admission=None, **changes):
        admission = admission or self.admit()
        options = dict(pool_origin='saved_campaign_pool', candidate_pool=admission.candidate_pool,
                       pool_admission=admission.admission,
                       max_evaluations=len(self.builtin.folds) * (2 * len(admission.candidate_pool) + 1))
        options.update(changes)
        return replace(self.builtin, **options)

    def run_saved(self, *, plan=None, **changes):
        values = dict(plan=plan or self.plan(), output_dir=self.output,
                      holdout_registry_path=self.registry, source_campaign_dir=self.folder,
                      original_dataset=self.original)
        values.update(changes)
        return run_walk_forward(self.data, **values)

    def write(self, state):
        write_source(self.folder, state)

    def test_admits_all_fifteen_in_attempt_order_not_selected_winners(self):
        admission = self.admit()
        self.assertEqual(len(admission.candidate_pool), 15)
        self.assertEqual([content_hash(spec) for spec in admission.candidate_pool],
                         [attempt['strategy_hash'] for attempt in self.state['attempts']])
        self.assertEqual(len(self.state['selected']), 5)
        self.assertEqual(admission.admission['real_model_status'], self.state['real_model_status'])
        self.assertEqual(admission.admission['provider_mode'], 'fixture')
        with self.assertRaises(TypeError):
            admission.admission['attempts'][0]['admitted'] = False
        encoded = canonical_json(admission.admission)
        for private in ('987654321', 'metrics', 'generator_context', 'provider_receipts', 'endpoint', 'source_filename'):
            self.assertNotIn(private, encoded)
        self.assertEqual(canonical_json(load_original_dataset(self.original_path)), canonical_json(self.original))

    def test_unevaluated_attempts_are_visible_exclusions_with_exact_order(self):
        folder, ref, original, state = make_saved_source(self.root / 'excluded', exclude_sequences=(2, 8, 15))
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(len(admission.candidate_pool), 12)
        self.assertEqual(len(admission.admission['attempts']), 15)
        for row in admission.admission['attempts']:
            if row['sequence'] in (2, 8, 15):
                self.assertFalse(row['admitted'])
                self.assertEqual(row['reason'], 'excluded_source_attempt_rejected')
                self.assertNotIn('pool_index', row)
        self.assertEqual([row['sequence'] for row in admission.admission['attempts'] if row['admitted']],
                         [i for i in range(1, 16) if i not in (2, 8, 15)])

    def test_source_endpoint_equal_or_later_rejects_without_io_changes(self):
        before = (self.folder / 'campaign.json').read_bytes()
        endpoint = max(bar.end for bar in self.original.bars)
        for first in (endpoint, endpoint - timedelta(seconds=1)):
            with self.subTest(first=first), self.assertRaises(SavedCandidatePoolError) as error:
                self.admit(first_training_timestamp=first)
            self.assertEqual(error.exception.reason_code, 'source_temporal_overlap')
        self.assertEqual(before, (self.folder / 'campaign.json').read_bytes())
        self.assertEqual(self.registry.read_bytes(), self.initial_registry_bytes)

    def test_temporal_bounds_cover_every_bar_even_outside_named_splits(self):
        # The full original envelope is checked, not its claimed coverage or splits.
        later = self.data.bars[-1]
        bars = self.original.bars + (later,)
        manifest = {**self.original.manifest, 'data_hash': content_hash(bars)}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(self.original.quality))
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(original_dataset=data)
        self.assertEqual(error.exception.reason_code, 'source_temporal_overlap')

    def test_same_claimed_coverage_cannot_substitute_or_omit_original_data(self):
        changed = alter_prices(self.original, 0, 1)
        self.assertEqual(changed.manifest['coverage'], self.original.manifest['coverage'])
        for original in (changed, None):
            with self.subTest(original=type(original)), self.assertRaises(SavedCandidatePoolError):
                self.admit(original_dataset=original)
        self.original_path.unlink()
        with self.assertRaises(SavedCandidatePoolError):
            load_original_dataset(self.original_path)

    def test_journal_export_mismatch_duplicate_json_keys_and_missing_files_reject(self):
        export = self.folder / 'campaign.json'
        changed = copy.deepcopy(self.state); changed['elapsed_seconds'] += 1
        export.write_text(canonical_json(changed), encoding='utf-8')
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit()
        self.assertEqual(error.exception.reason_code, 'source_journal_mismatch')
        export.write_text('{"status":"completed","status":"running"}', encoding='utf-8')
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        export.unlink()
        with self.assertRaises(SavedCandidatePoolError): self.admit()

    def test_nonterminal_future_schema_model_upgrade_unknown_producer_reject(self):
        mutations = [lambda s: s.update(status='running'), lambda s: s.update(status='completed_with_errors'),
                     lambda s: s.update(status='blocked_interrupted'), lambda s: s.update(schema_version=2),
                     lambda s: s.update(real_model_status='verified'),
                     lambda s: s['binding'].update(engine_source_hashes={}),
                     lambda s: s['binding']['engine_source_hashes'].update({'research.py': 'a' * 64}),
                     lambda s: s['binding'].update(prompt_template_hash='a' * 64)]
        for mutation in mutations:
            changed = copy.deepcopy(self.state); mutation(changed); self.write(changed)
            with self.subTest(state=changed.get('status')), self.assertRaises(SavedCandidatePoolError): self.admit()
        self.write(self.state)

    def test_altered_output_spec_hashes_sequence_parent_and_context_reject(self):
        mutations = [lambda a: a['output'].update(strategy_id='altered'),
                     lambda a: a['spec'].update(strategy_id='altered'),
                     lambda a: a.update(output_hash='a' * 64), lambda a: a.update(strategy_hash='a' * 64),
                     lambda a: a.update(sequence=2), lambda a: a.update(parent_id='a' * 64),
                     lambda a: a['generator_context'].update(future_oos={'secret': True}),
                     lambda a: a['generator_context']['training'].update(bar_count=100),
                     lambda a: a.update(metrics={})]
        for mutation in mutations:
            changed = copy.deepcopy(self.state); mutation(changed['attempts'][0]); self.write(changed)
            with self.subTest(mutation=mutation), self.assertRaises(SavedCandidatePoolError): self.admit()

    def test_duplicate_structure_rejects_even_with_new_strategy_id_and_valid_hashes(self):
        changed = copy.deepcopy(self.state)
        attempt, prior = changed['attempts'][-1], changed['attempts'][4]
        output = copy.deepcopy(prior['output']); output['strategy_id'] = 'new_cosmetic_id'
        attempt.update(output=output, output_hash=content_hash(output), spec=output, strategy_hash=content_hash(output))
        self.write(changed)
        with self.assertRaises(SavedCandidatePoolError) as error: self.admit()
        self.assertEqual(error.exception.reason_code, 'source_duplicate_structure')

    def test_more_than_fifteen_and_empty_pool_reject(self):
        changed = copy.deepcopy(self.state); changed['attempts'].append(copy.deepcopy(changed['attempts'][-1])); self.write(changed)
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        folder, ref, original, _ = make_saved_source(self.root / 'none', exclude_sequences=tuple(range(1, 16)))
        with self.assertRaises(SavedCandidatePoolError):
            self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_source_results_revalidate_all_split_manifest_hashes_not_only_train(self):
        mutations = [lambda s: s['attempts'][0]['metrics']['train']['manifest'].update(data_hash='a' * 64),
                     lambda s: s['attempts'][0]['metrics']['validation']['manifest'].update(spec_hash='a' * 64),
                     lambda s: s['evaluations']['oos'][0]['manifest'].update(config_hash='a' * 64),
                     lambda s: s['evaluations']['holdout'][0]['manifest']['source_hashes'].update({'data.py': 'a' * 64}),
                     lambda s: s['evaluations']['holdout'][0]['manifest'].update(cost_hash='a' * 64)]
        for mutation in mutations:
            changed = copy.deepcopy(self.state); mutation(changed); self.write(changed)
            with self.assertRaises(SavedCandidatePoolError): self.admit()

    def test_unknown_provider_callback_rejects_even_with_rebound_campaign(self):
        changed = copy.deepcopy(self.state)
        changed['binding']['provider']['mode'] = 'custom_unverified'
        changed['campaign_id'] = content_hash(changed['binding'])
        self.write(changed)
        with self.assertRaises(SavedCandidatePoolError) as error: self.admit()
        self.assertEqual(error.exception.reason_code, 'source_provider_unsupported')

    def test_raw_original_numeric_exponents_reject_before_hashing(self):
        payload = json.loads(self.original_path.read_text(encoding='utf-8'))
        payload['payload']['bars'][0]['open'] = '1e1000000000'
        self.original_path.write_text(json.dumps(payload), encoding='utf-8')
        with patch('quantlab.saved_candidate_pool.content_hash', side_effect=AssertionError('must bound before hash')):
            with self.assertRaises(SavedCandidatePoolError): load_original_dataset(self.original_path)
        bar = self.original.bars[0]
        object.__setattr__(bar, 'open', Decimal('1e1000000000'))
        with patch('quantlab.saved_candidate_pool.content_hash', side_effect=AssertionError('must bound before hash')):
            with self.assertRaises(SavedCandidatePoolError): self.admit()

    def test_source_json_limits_reject_before_configuration_or_hashing(self):
        changed = copy.deepcopy(self.state)
        changed['binding']['config']['ranking']['minimum'] = '1e1000000000'
        self.write(changed)
        with patch('quantlab.__main__.config_from_json', side_effect=AssertionError('bound before converting')):
            with self.assertRaises(SavedCandidatePoolError): self.admit()
        (self.folder / 'campaign.json').write_bytes(b' ' * (MAX_AUDIT_BYTES + 1))
        with self.assertRaises(SavedCandidatePoolError): self.admit()

    def test_pool_plan_roundtrip_binding_origin_and_budget_formula(self):
        plan = self.plan()
        self.assertEqual(planned_evaluations(plan), 93)
        self.assertEqual(to_dict(plan), to_dict(walk_forward_plan_from_dict(to_dict(plan))))
        for value in (94, 620, 621):
            with self.assertRaises(ValidationError): replace(plan, max_evaluations=value)
        with self.assertRaises(ValidationError): replace(self.builtin, max_evaluations=221)
        with self.assertRaises(ValidationError): replace(self.builtin, pool_admission=plan.pool_admission)
        with self.assertRaises(ValidationError): replace(plan, pool_origin='exact_builtin_pool')
        with self.assertRaises(ValidationError): replace(plan, pool_admission=None)
        full = build_walk_forward_plan(backtest_config=plan.backtest_config, train_bars=2,
            validation_bars=2, oos_bars=2, fold_count=20, final_holdout=(44, 46),
            pool_origin=plan.pool_origin, candidate_pool=plan.candidate_pool, pool_admission=plan.pool_admission)
        self.assertEqual(full.max_evaluations, 620)
        self.assertEqual(planned_evaluations(full), 620)

    def test_saved_execution_evaluates_all_candidates_and_never_calls_model(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker), \
             patch('quantlab.research._generate_candidate', side_effect=AssertionError('no new generation')), \
             patch('quantlab.research.run_campaign', side_effect=AssertionError('no campaign evaluation')):
            state = self.run_saved()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(state['evaluations']), 93)
        self.assertEqual(state['summary']['planned_evaluations_upper_bound'], 93)
        self.assertEqual(state['model_calls'], 0)
        self.assertEqual([len(fold['candidates']) for fold in state['folds']], [15, 15, 15])
        self.assertEqual(state['binding']['protocol'], 'fixed_saved_campaign_walk_forward_v1')
        self.assertEqual(read_walk_forward_state(self.output), state)
        self.assertEqual(state['final_holdout_status'], 'excluded_not_evaluated')
        for section in (state, state['summary']):
            self.assertFalse(section['ranking_eligible']); self.assertFalse(section['paper_eligible'])
            self.assertFalse(section['independent_oos'])

    def test_preview_mutation_missing_source_and_asserted_snapshot_reject_before_reservation(self):
        plan = self.plan()
        changed = copy.deepcopy(self.state); changed['elapsed_seconds'] += 1; self.write(changed)
        with patch('quantlab.walk_forward._reserve_holdout', side_effect=AssertionError('must not reserve')):
            with self.assertRaisesRegex(ValidationError, 'changed'): self.run_saved(plan=plan)
            self.write(self.state)
            with self.assertRaises(ValidationError): self.run_saved(plan=plan, original_dataset=None)
            asserted = to_dict(plan.pool_admission); asserted['source_journal_hash'] = 'a' * 64
            asserted['snapshot_hash'] = content_hash({k: v for k, v in asserted.items() if k != 'snapshot_hash'})
            forged = replace(plan, pool_admission=asserted)
            with self.assertRaisesRegex(ValidationError, 'changed'): self.run_saved(plan=forged)
        self.assertFalse(self.output.exists()); self.assertEqual(self.registry.read_bytes(), self.initial_registry_bytes)

    def test_shared_consumed_range_guard_applies_to_saved_pool_full_planned_window(self):
        _reserve_holdout(Dataset(self.data.bars[:3], {}, {}), registry_path=self.registry,
                         campaign_id='prior', selection_hash='prior', output_dir=self.root / 'prior')
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('consumed range')):
            state = self.run_saved()
        self.assertEqual(state['status'], 'blocked_previously_consumed_range')
        self.assertEqual(state['evaluations'], [])

    def test_lower_budget_cancellation_restart_and_all_risk_gates_preserved(self):
        plan = self.plan(max_evaluations=7)
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker): state = self.run_saved(plan=plan)
        self.assertEqual(state['status'], 'budget_exhausted'); self.assertEqual(len(state['evaluations']), 7)
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('never retry')):
            self.assertEqual(self.run_saved(plan=plan), state)
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('cancelled')):
            cancelled = self.run_saved(output_dir=self.root / 'cancel', cancelled=lambda: True)
        self.assertEqual(cancelled['status'], 'cancelled'); self.assertEqual(cancelled['evaluations'], [])
        def failed_risk(*args, **kwargs):
            result = fake_worker(*args, **kwargs)
            result['value']['metrics']['max_drawdown_pct'] = '0.11'
            return result
        folder, ref, original, _ = make_saved_source(self.root / 'risk-source', data=self.original)
        registry = folder.parent / 'source-registry.sqlite3'
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        with patch('quantlab.walk_forward._run_bounded', side_effect=failed_risk):
            failed = self.run_saved(plan=self.plan(admission), source_campaign_dir=folder,
                output_dir=self.root / 'risk', holdout_registry_path=registry)
        self.assertTrue(all(fold['status'] == 'no_eligible_candidate' for fold in failed['folds']))
        self.assertEqual(len(failed['evaluations']), 90)

    def test_source_oos_metrics_and_new_future_prices_do_not_choose_pool_or_fold(self):
        first = self.admit()
        changed = copy.deepcopy(self.state)
        for role in ('oos', 'holdout'):
            for record in changed['evaluations'][role]: record['metrics']['net_pnl'] = '-999999'
        self.write(changed)
        second = self.admit()
        self.assertEqual(first.candidate_pool, second.candidate_pool)
        self.assertNotEqual(first.admission['source_journal_hash'], second.admission['source_journal_hash'])
        plan = self.plan(second)
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            before = self.run_saved(plan=plan)
            future = alter_prices(self.data, self.builtin.folds[0].oos[0], len(self.data.bars))
            folder, ref, original, _ = make_saved_source(self.root / 'future-source', data=self.original)
            registry = folder.parent / 'source-registry.sqlite3'
            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            after = run_walk_forward(future, plan=self.plan(admission), output_dir=self.root / 'future',
                holdout_registry_path=registry, source_campaign_dir=folder, original_dataset=original)
        self.assertEqual(before['folds'][0]['selection'], after['folds'][0]['selection'])

    def test_audited_chatgpt_lf_and_windows_descriptors_admit_without_loading_auth(self):
        for variant in (0, 1):
            folder, reference, original, state = make_chatgpt_source(self.root / ('plan-' + str(variant)), implementation=variant)
            with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                admission = self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)
            self.assertEqual(len(admission.candidate_pool), 15)
            self.assertEqual(admission.admission['provider_mode'], 'chatgpt_plan')
            self.assertEqual(admission.admission['real_model_status'], 'not_verified')
            serialized = canonical_json(admission.admission)
            for private in ('registration', 'generated-fixture-campaign', 'request_bytes', 'token_usage'):
                self.assertNotIn(private, serialized)

    def test_chatgpt_unknown_mixed_implementation_and_forged_receipts_reject(self):
        folder, reference, original, state = make_chatgpt_source(self.root / 'plan')
        mutations = [lambda s: s['provider_receipts'][0].update(request_hash='f' * 64),
                     lambda s: s['provider_receipts'][0].update(request_bytes=1),
                     lambda s: s['provider_receipts'][0].update(response_hash='f' * 64),
                     lambda s: s['provider_receipts'][0].update(status='reserved_unknown'),
                     lambda s: s['provider_receipts'].pop(),
                     lambda s: s['provider_receipts'][0].update(paid_api_fallback=True),
                     lambda s: s['attempts'][5]['generator_context'].update(task='malicious-future-task')]
        for mutation in mutations:
            changed = copy.deepcopy(state); mutation(changed); write_source(folder, changed)
            with self.assertRaises(SavedCandidatePoolError):
                self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)
        # Construct another explicit schema fixture, never alter real campaign receipts.
        producer = copy.deepcopy(to_dict(CURRENT_PRODUCER))
        producer['chatgpt_plan_implementations'][0]['source_sha256']['desktop_chatgpt_provider.py'] = (
            CURRENT_PRODUCER['chatgpt_plan_implementations'][1]['source_sha256']['desktop_chatgpt_provider.py'])
        folder, reference, original, _ = make_chatgpt_source(self.root / 'mixed', producer=producer)
        with self.assertRaises(SavedCandidatePoolError):
            self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)

    def test_exact_current_windows_result_tuple_accepts_but_mixed_tuple_rejects(self):
        producer = copy.deepcopy(to_dict(CURRENT_PRODUCER))
        producer['result_source_hashes'] = copy.deepcopy(producer['result_source_hash_variants'][1])
        folder, reference, original, _ = make_saved_source(self.root / 'windows-results', producer=producer)
        self.assertEqual(len(self.admit(source_campaign_dir=folder, source_campaign_ref=reference,
                                       original_dataset=original).candidate_pool), 15)
        producer['result_source_hashes']['core.py'] = CURRENT_PRODUCER['result_source_hashes']['core.py']
        folder, reference, original, _ = make_saved_source(self.root / 'mixed-results', producer=producer)
        with self.assertRaises(SavedCandidatePoolError):
            self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)

    def test_current_producer_real_spawn_subprocess_to_admission_roundtrip(self):
        self.original = shifted_dataset(self.original, days=-1)
        source_config = replace(self.builtin.backtest_config, costs=replace(
            self.builtin.backtest_config.costs, effective_from='2025-01-01'))
        config = demo_campaign_config(self.original, source_config)
        config.update(families=['trend'], max_trials=1, max_improvements=0, process_start_method='spawn')
        config['ranking']['minimum'] = '-1000000'
        reference = 'e' * 64
        folder = self.root / 'spawn-campaigns' / reference
        state = run_campaign(self.original, config=config, generator=FixtureGenerator(),
                             output_dir=folder, holdout_registry_path=self.registry)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['attempts'][0]['status'], 'evaluated')
        self.assertEqual(state['binding']['engine_source_hashes'], TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes'])
        before = (folder / 'campaign.json').read_bytes()
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=reference, authoritative_registry_path=self.registry)
        self.assertEqual(len(admission.candidate_pool), 1)
        self.assertEqual((folder / 'campaign.json').read_bytes(), before)

    def test_manual_exchange_and_plan_receipt_rejections_have_safe_distinct_codes(self):
        folder, reference, original, _ = make_saved_source(self.root / 'manual', producer=CURRENT_PRODUCER,
            provider={'mode': 'manual_unverified', 'model': 'fixture-sealed-package-absent', 'endpoint': None})
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_manual_exchange_missing')
        folder, reference, original, state = make_chatgpt_source(self.root / 'receipt-error')
        state['provider_receipts'][0]['request_hash'] = 'f' * 64; write_source(folder, state)
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_provider_receipt_invalid')
        producer = copy.deepcopy(to_dict(CURRENT_PRODUCER))
        producer['chatgpt_plan_implementations'][0]['dependency_manifest_sha256'] = 'f' * 64
        folder, reference, original, _ = make_chatgpt_source(self.root / 'descriptor-error', producer=producer)
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(source_campaign_dir=folder, source_campaign_ref=reference, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_provider_provenance_invalid')

    def test_fixture_and_compatible_receipts_are_strict_and_bounded(self):
        changed = copy.deepcopy(self.state); changed['provider_receipts'] = {'malformed': True}; self.write(changed)
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        provider = {'mode': 'openai_compatible', 'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions', 'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30}}
        for producer in (AUDITED_PRODUCER, CURRENT_PRODUCER):
            folder, ref, original, state = make_saved_source(self.root / producer['protocol'], producer=producer, provider=provider)
            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(len(admission.candidate_pool), 15)
            self.assertNotEqual(state['provider_receipts'][0]['response_hash'], state['attempts'][0]['output_hash'])
            for mutation in (lambda s: s.update(provider_receipts={}), lambda s: s['provider_receipts'].pop(),
                lambda s: s['provider_receipts'][0].update(response_hash='not_hash'),
                lambda s: s['provider_receipts'][0].update(reserved_tokens=-1),
                lambda s: s['provider_receipts'][0].update(reserved_tokens=3000),
                lambda s: s['provider_receipts'][0].update(reserved_spend='-1'),
                lambda s: s['provider_receipts'][0].update(status='made_up')):
                bad = copy.deepcopy(state); mutation(bad); write_source(folder, bad)
                with self.assertRaises(SavedCandidatePoolError):
                    self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_compatible_endpoint_invariants_reject_without_network_or_credentials(self):
        base = {'mode': 'openai_compatible', 'model': 'fixture', 'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30}}
        for index, endpoint in enumerate(('http://example.invalid', 'https://user:secret@example.invalid',
            'https://example.invalid/?token=secret', 'https://example.invalid/#fragment', 'https://bad host/', 'https://example.invalid:0')):
            folder, ref, original, _ = make_saved_source(self.root / ('endpoint-' + str(index)), provider={**base, 'endpoint': endpoint})
            with self.assertRaises(SavedCandidatePoolError) as error:
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(error.exception.reason_code, 'source_provider_unsupported')

    def test_rejected_json_null_generation_remains_explicitly_excluded(self):
        folder, ref, original, state = make_saved_source(self.root / 'returned-null', producer=CURRENT_PRODUCER, exclude_sequences=(15,))
        state['attempts'][-1]['output_hash'] = content_hash(None)
        write_source(folder, state)
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(len(admission.candidate_pool), 14)
        self.assertFalse(admission.admission['attempts'][-1]['admitted'])
        self.assertEqual(admission.admission['attempts'][-1]['reason'], 'excluded_source_attempt_rejected')

    def test_registry_continuity_relocation_and_selected_alias_preserve_original_authority(self):
        first = self.admit()
        before = self.registry.read_bytes()
        folder = self.root / 'relocated' / self.ref
        shutil.copytree(self.folder, folder)
        moved = self.admit(source_campaign_dir=folder, authoritative_registry_path=self.registry)
        self.assertEqual(first.admission, moved.admission)
        alias = self.root / 'registry-alias.sqlite3'
        try:
            alias.symlink_to(self.registry)
        except (OSError, NotImplementedError):
            pass
        else:
            self.assertEqual(first.admission, self.admit(authoritative_registry_path=alias).admission)
            changed = copy.deepcopy(self.state); changed['holdout_registry']['registry_path'] = str(alias); self.write(changed)
            # Untrusted source aliases are never resolved/followed.
            with self.assertRaises(SavedCandidatePoolError): self.admit(authoritative_registry_path=alias)
        self.assertEqual(self.registry.read_bytes(), before)

    def test_registry_missing_empty_changed_or_new_authority_rejects_before_new_reservation(self):
        plan = self.plan()
        fresh = self.root / 'new-authority.sqlite3'
        with self.assertRaises(SavedCandidatePoolError): self.run_saved(plan=plan, holdout_registry_path=fresh)
        self.assertFalse(fresh.exists())
        before = self.registry.read_bytes()
        self.registry.unlink()
        with self.assertRaises(SavedCandidatePoolError): self.run_saved(plan=plan)
        self.assertFalse(self.registry.exists())
        self.registry.write_bytes(b'')
        with self.assertRaises(SavedCandidatePoolError): self.run_saved(plan=plan)
        self.assertEqual(self.registry.read_bytes(), b'')
        for statement in ("UPDATE reservations SET selection_hash='bad'", "UPDATE coverage SET end='2099-01-01T00:00:00.000000Z'"):
            self.registry.write_bytes(before)
            with closing(sqlite3.connect(self.registry)) as db, db: db.execute(statement)
            mutated = self.registry.read_bytes()
            with self.assertRaises(SavedCandidatePoolError): self.run_saved(plan=plan)
            self.assertEqual(self.registry.read_bytes(), mutated)
        self.assertFalse(self.output.exists())

    def test_source_with_no_selected_winner_or_registry_proof_blocks_saved_route(self):
        changed = copy.deepcopy(self.state)
        changed.update(selected=[], evaluations={'oos': [], 'holdout': []}, selection_hash=content_hash([]),
                       holdout_consumed=False, holdout_status='not_accessed')
        changed.pop('holdout_registry'); changed.pop('holdout_selection_hash'); self.write(changed)
        with self.assertRaises(SavedCandidatePoolError) as error: self.admit()
        self.assertEqual(error.exception.reason_code, 'source_registry_mismatch')

    def test_saved_terminal_report_reads_without_sources_and_with_windows_registry_identity(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker): state = self.run_saved()
        shutil.rmtree(self.folder); self.original_path.unlink(); self.registry.unlink()
        self.assertEqual(read_walk_forward_state(self.output), state)
        snapshot = state['binding']['plan']['pool_admission']
        snapshot['source_registry_identity']['resolved_path'] = 'c:\\users\\fixture\\controls\\holdout.sqlite3'
        snapshot['snapshot_hash'] = content_hash({k: v for k, v in snapshot.items() if k != 'snapshot_hash'})
        state['experiment_id'] = content_hash(state['binding'])
        state['state_hash'] = content_hash({k: v for k, v in state.items() if k != 'state_hash'})
        with closing(sqlite3.connect(self.output / 'walk_forward.sqlite3')) as db, db:
            db.execute('UPDATE state SET payload=? WHERE id=1', (canonical_json(state),))
        self.assertEqual(read_walk_forward_state(self.output), state)

    def test_sqlite_views_unexpected_columns_and_triggers_reject_before_source_queries(self):
        original_journal = (self.folder / 'campaign.sqlite3').read_bytes()
        with closing(sqlite3.connect(self.folder / 'campaign.sqlite3')) as db, db:
            db.execute('ALTER TABLE state RENAME TO shadow_state')
            db.execute('CREATE VIEW state AS SELECT id, payload FROM shadow_state')
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        (self.folder / 'campaign.sqlite3').write_bytes(original_journal)
        with closing(sqlite3.connect(self.folder / 'campaign.sqlite3')) as db, db:
            db.execute('ALTER TABLE state ADD COLUMN future_schema TEXT')
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        (self.folder / 'campaign.sqlite3').write_bytes(original_journal)
        original_registry = self.registry.read_bytes()
        with closing(sqlite3.connect(self.registry)) as db, db:
            db.execute('ALTER TABLE coverage RENAME TO shadow_coverage')
            db.execute('CREATE VIEW coverage AS SELECT * FROM shadow_coverage')
        with self.assertRaises(SavedCandidatePoolError): self.admit()
        self.registry.write_bytes(original_registry)
        with closing(sqlite3.connect(self.registry)) as db, db:
            # Harmless, never executed. Audited registry schema contains no triggers.
            db.execute('CREATE TRIGGER unaudited_trigger AFTER INSERT ON reservations BEGIN SELECT 1; END')
        with patch('quantlab.walk_forward._reserve_holdout', side_effect=AssertionError('must not write')):
            with self.assertRaises(SavedCandidatePoolError): self.admit()
        self.assertFalse(self.output.exists())

    def test_nonzero_compatible_rate_is_explicitly_unsupported_without_decimal_context(self):
        provider = {'mode': 'openai_compatible', 'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions', 'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '1000', 'rate': '0.001', 'tokens_per_call': 2048, 'timeout': 30}}
        folder, ref, original, _ = make_saved_source(self.root / 'nonzero-rate', provider=provider)
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_provider_decimal_context_unsupported')

    def test_original_file_regular_symlink_and_fifo_race_guard(self):
        alias = self.root / 'selected-alias.json'
        try:
            alias.symlink_to(self.original_path)
        except (OSError, NotImplementedError):
            pass
        else:
            self.assertEqual(canonical_json(load_original_dataset(alias)), canonical_json(self.original))
        if not hasattr(os, 'mkfifo') or not hasattr(os, 'O_NONBLOCK'):
            return
        fifo = self.root / 'generated-fifo.json'
        os.mkfifo(fifo)
        with self.assertRaises(SavedCandidatePoolError): load_original_dataset(fifo)
        race = self.root / 'generated-race.json'
        race.write_bytes(self.original_path.read_bytes())
        actual_open = os.open
        opened = []
        def swap_to_fifo(path, flags):
            self.assertTrue(flags & os.O_NONBLOCK)
            Path(path).unlink(); os.mkfifo(path)
            descriptor = actual_open(path, flags)
            opened.append(descriptor)
            return descriptor
        with patch('quantlab.saved_candidate_pool.os.open', side_effect=swap_to_fifo):
            with self.assertRaises(SavedCandidatePoolError): load_original_dataset(race)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError): os.fstat(opened[0])

    def test_profile_extension_keeps_both_original_producer_objects_exact(self):
        self.assertEqual(content_hash(AUDITED_PRODUCER), '97ef1ebf0e68ed6d7c5714caa806ece5b53592c984d0058ac8a1d73c06a419a5')
        self.assertEqual(content_hash(CURRENT_PRODUCER), '2c7655ab89a8beaf48e98105c85a2dd5860f1d41418e32d1452e7218ab620f26')
        self.assertEqual(CURRENT_CHATGPT_PROFILE_V2['provider_modes'], ['chatgpt_plan'])
        self.assertEqual(CURRENT_CHATGPT_PROFILE_V2['engine_source_hashes'], CURRENT_PRODUCER['engine_source_hashes'])

    def test_new_descriptor_profile_supports_only_all_explicitly_audited_targets(self):
        expected = [
            {'windows-cp311-amd64', 'windows-cp312-amd64', 'windows-cp313-amd64', 'linux-cp311-x86_64', 'linux-cp312-x86_64'},
            {'windows-cp311-amd64', 'windows-cp312-amd64', 'windows-cp313-amd64'}]
        for index, implementation in enumerate(CURRENT_CHATGPT_PROFILE_V2['chatgpt_plan_implementations']):
            self.assertEqual(set(implementation['dependency_targets']), expected[index])
            for target in implementation['dependency_targets']:
                folder, ref, original, _ = make_chatgpt_source(self.root / f'profile-v2-{index}-{target}',
                    producer=CURRENT_CHATGPT_PROFILE_V2, implementation=index, dependency_target=target)
                with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                    admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                self.assertEqual(admission.admission['producer'], CURRENT_CHATGPT_PROFILE_V2)
                self.assertEqual(admission.admission['real_model_status'], 'not_verified')
                self.assertNotIn('native_runtime_accepted', canonical_json(admission.admission))

    def test_old_chatgpt_profile_and_terminal_snapshot_remain_readable(self):
        folder, ref, original, _ = make_chatgpt_source(self.root / 'prior-descriptor', producer=CURRENT_PRODUCER)
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(admission.admission['producer'], CURRENT_PRODUCER)
        registry = folder.parent / 'source-registry.sqlite3'
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            state = self.run_saved(plan=self.plan(admission), source_campaign_dir=folder,
                                  original_dataset=original, holdout_registry_path=registry)
        shutil.rmtree(folder); registry.unlink()
        with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS',
                   (CURRENT_CHATGPT_PROFILE_V2, CURRENT_PRODUCER, AUDITED_PRODUCER)):
            self.assertEqual(read_walk_forward_state(self.output), state)
        self.assertEqual(state['binding']['plan']['pool_admission']['producer'], to_dict(CURRENT_PRODUCER))

    def test_profile_extension_keeps_fixture_and_compatible_identity_deterministic(self):
        provider = {'mode': 'openai_compatible', 'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions', 'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30}}
        for name, supplied in (('fixture', None), ('compatible', provider)):
            folder, ref, original, _ = make_saved_source(self.root / ('stable-' + name), producer=CURRENT_PRODUCER, provider=supplied)
            before = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS',
                       (CURRENT_CHATGPT_PROFILE_V2, AUDITED_PRODUCER, CURRENT_PRODUCER)):
                after = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(before.admission, after.admission)
            self.assertEqual(before.admission['producer'], CURRENT_PRODUCER)

    def test_descriptor_profile_selection_rejects_ambiguity_without_fallback(self):
        folder, ref, original, _ = make_chatgpt_source(self.root / 'ambiguous-profile', producer=CURRENT_CHATGPT_PROFILE_V2)
        duplicate = copy.deepcopy(to_dict(CURRENT_CHATGPT_PROFILE_V2))
        duplicate['protocol'] = 'generated_ambiguous_profile'
        with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS',
                   (AUDITED_PRODUCER, CURRENT_PRODUCER, CURRENT_CHATGPT_PROFILE_V2, duplicate)):
            with self.assertRaises(SavedCandidatePoolError) as error:
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_provider_provenance_invalid')

    def test_new_descriptor_profiles_reject_unknown_targets_mixed_hashes_and_wrong_versions(self):
        for index, (variant, target) in enumerate(((0, 'windows-cp314-amd64'), (0, 'linux-cp313-x86_64'),
                                                  (1, 'linux-cp311-x86_64'))):
            folder, ref, original, _ = make_chatgpt_source(self.root / f'unknown-target-{index}',
                producer=CURRENT_CHATGPT_PROFILE_V2, implementation=variant, dependency_target=target)
            with self.assertRaises(SavedCandidatePoolError):
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        for index, mutate in enumerate((
            lambda item: item.update(dependency_manifest_sha256=CURRENT_PRODUCER['chatgpt_plan_implementations'][0]['dependency_manifest_sha256']),
            lambda item: item['dependency_versions'].update({'cryptography': '50.0.1'}),
            lambda item: item['source_sha256'].update({'desktop_chatgpt_provider.py': CURRENT_CHATGPT_PROFILE_V2['chatgpt_plan_implementations'][1]['source_sha256']['desktop_chatgpt_provider.py']}))):
            producer = copy.deepcopy(to_dict(CURRENT_CHATGPT_PROFILE_V2)); mutate(producer['chatgpt_plan_implementations'][0])
            folder, ref, original, _ = make_chatgpt_source(self.root / f'unknown-tuple-{index}', producer=producer)
            with self.assertRaises(SavedCandidatePoolError):
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)

    def test_transport_verifier_profiles_preserve_exact_prior_profiles_and_source_scope(self):
        self.assertEqual(content_hash(CURRENT_CHATGPT_PROFILE_V2),
                         'ce3b2af865ea0338575c065b988a64ebcd4974e58617a93779e6edb684ec37de')
        for old, new, expected in (
            (CURRENT_PRODUCER, TRANSPORT_VERIFIER_PRODUCER,
             '346eceee2a55514c22a32ae028402c8a74c9b52ab44befa0f90608ae68e549be'),
            (CURRENT_CHATGPT_PROFILE_V2, TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2,
             'e86f5b691ea3b0c015f0354ca2d6ec0b49c6300c25b62255b4f8a9da13f2b55e')):
            self.assertEqual(content_hash(new), expected)
            prior_shape = to_dict(new)
            prior_shape['protocol'] = old['protocol']
            prior_shape['engine_source_hashes']['provider.py'] = old['engine_source_hashes']['provider.py']
            self.assertEqual(prior_shape, old)
            with self.assertRaises(TypeError):
                new['engine_source_hashes']['provider.py'] = 'f' * 64
        # Read only to verify the literal audit pin. Runtime admission never does this.
        import quantlab.research as research
        actual = {name: content_hash(Path(research.__file__).with_name(name).read_text(encoding='utf-8'))
                  for name in TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes']}
        self.assertEqual(actual, TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes'])
        self.assertEqual(content_hash(research.PROMPT), TRANSPORT_VERIFIER_PRODUCER['prompt_template_hash'])

    def test_transport_verifier_fixture_and_compatible_profiles_are_canonical_without_rewrites(self):
        provider = {'mode': 'openai_compatible', 'model': 'fixture',
            'endpoint': 'https://example.invalid/v1/chat/completions', 'network_opt_in': True,
            'transport_type': 'quantlab.provider.HTTPTransport',
            'limits': {'calls': 15, 'tokens': 1000000, 'spend': '0', 'rate': '0', 'tokens_per_call': 2048, 'timeout': 30}}
        for name, supplied in (('fixture', None), ('compatible', provider)):
            folder, ref, original, _ = make_saved_source(self.root / ('transport-' + name),
                producer=TRANSPORT_VERIFIER_PRODUCER, provider=supplied)
            before = {path.name: path.read_bytes() for path in folder.iterdir()}
            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            with patch('quantlab.saved_candidate_pool.SUPPORTED_PRODUCERS', tuple(reversed(SUPPORTED_PRODUCERS))):
                reordered = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(admission.admission, reordered.admission)
            self.assertEqual(admission.admission['producer'], TRANSPORT_VERIFIER_PRODUCER)
            self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})
            self.assertEqual(walk_forward_plan_from_dict(to_dict(self.plan(admission))), self.plan(admission))

    def test_transport_verifier_chatgpt_profiles_select_only_exact_descriptor_pairs(self):
        for producer in (TRANSPORT_VERIFIER_PRODUCER, TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2):
            for index, implementation in enumerate(producer['chatgpt_plan_implementations']):
                for target in implementation['dependency_targets']:
                    with self.subTest(protocol=producer['protocol'], implementation=index, target=target):
                        folder, ref, original, _ = make_chatgpt_source(
                            self.root / f"transport-chatgpt-{producer['protocol']}-{index}-{target}",
                            producer=producer, implementation=index, dependency_target=target)
                        with patch.dict(sys.modules, {'desktop_chatgpt_auth': None, 'desktop_chatgpt_provider': None}):
                            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref,
                                                   original_dataset=original)
                        self.assertEqual(admission.admission['producer'], producer)
                        self.assertEqual(admission.admission['real_model_status'], 'not_verified')

    def test_transport_verifier_unknown_and_mixed_engine_hashes_remain_unsupported(self):
        producers = []
        for name in TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes']:
            producer = to_dict(TRANSPORT_VERIFIER_PRODUCER)
            producer['engine_source_hashes'][name] = 'f' * 64
            producers.append(producer)
        for name in ('research.py', 'backtest.py'):
            producer = to_dict(TRANSPORT_VERIFIER_PRODUCER)
            producer['engine_source_hashes'][name] = AUDITED_PRODUCER['engine_source_hashes'][name]
            producers.append(producer)
        producer = to_dict(TRANSPORT_VERIFIER_PRODUCER)
        producer['prompt_template_hash'] = 'f' * 64
        producers.append(producer)
        for index, producer in enumerate(producers):
            with self.subTest(index=index):
                folder, ref, original, _ = make_saved_source(self.root / f'transport-unknown-{index}', producer=producer)
                with self.assertRaises(SavedCandidatePoolError) as error:
                    self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
                self.assertEqual(error.exception.reason_code, 'source_producer_unsupported')

    def test_transport_verifier_mixed_chatgpt_descriptors_and_unknown_targets_refuse(self):
        for index, mutate in enumerate((
            lambda item: item.update(dependency_manifest_sha256=TRANSPORT_VERIFIER_PRODUCER[
                'chatgpt_plan_implementations'][0]['dependency_manifest_sha256']),
            lambda item: item['source_sha256'].update({'desktop_chatgpt_auth.py':
                TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2['chatgpt_plan_implementations'][1][
                    'source_sha256']['desktop_chatgpt_auth.py']}),
            lambda item: item['source_sha256'].update({'desktop_chatgpt_provider.py':
                TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2['chatgpt_plan_implementations'][1][
                    'source_sha256']['desktop_chatgpt_provider.py']}),
            lambda item: item['dependency_versions'].update(cryptography='50.0.1'))):
            producer = to_dict(TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2)
            mutate(producer['chatgpt_plan_implementations'][0])
            folder, ref, original, _ = make_chatgpt_source(self.root / f'transport-mixed-chatgpt-{index}', producer=producer)
            with self.assertRaises(SavedCandidatePoolError) as error:
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(error.exception.reason_code, 'source_provider_provenance_invalid')
        for producer in (TRANSPORT_VERIFIER_PRODUCER, TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2):
            folder, ref, original, _ = make_chatgpt_source(self.root / (producer['protocol'] + '-unknown-target'),
                producer=producer, dependency_target='windows-cp314-amd64')
            with self.assertRaises(SavedCandidatePoolError) as error:
                self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
            self.assertEqual(error.exception.reason_code, 'source_provider_provenance_invalid')

    def test_transport_verifier_source_profile_does_not_admit_unknown_literal_mode(self):
        folder, ref, original, _ = make_saved_source(self.root / 'transport-local-ai',
            producer=TRANSPORT_VERIFIER_PRODUCER,
            provider={'mode': 'local_free_ai', 'model': 'fixture', 'endpoint': 'http://127.0.0.1:18974/v1/chat/completions'})
        with self.assertRaises(SavedCandidatePoolError) as error:
            self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(error.exception.reason_code, 'source_provider_unsupported')

    def test_transport_verifier_gui_local_provider_uses_existing_compatible_protocol(self):
        from quantlab.local_ai import provider as local_provider
        from quantlab.research import _provider_identity
        # The descriptor is real, while campaign outputs/receipts are manufactured
        # schema fixtures. No model, owned process, network, or credential is used.
        with patch('quantlab.local_ai.HTTPTransport.__call__', side_effect=AssertionError('no network')):
            provider = _provider_identity(local_provider(self.root / 'local-controls',
                                                        owner={'pid': 123, 'created': 456}))
            self.assertEqual(provider['mode'], 'openai_compatible')
            self.assertEqual(provider['transport_type'], 'quantlab.provider.HTTPTransport')
            self.assertEqual(provider['output_mode'], 'registry_json_schema')
            folder, ref, original, _ = make_saved_source(self.root / 'transport-gui-local-ai',
                producer=TRANSPORT_VERIFIER_PRODUCER, provider=provider)
            admission = self.admit(source_campaign_dir=folder, source_campaign_ref=ref, original_dataset=original)
        self.assertEqual(admission.admission['producer'], TRANSPORT_VERIFIER_PRODUCER)
        self.assertEqual(admission.admission['provider_mode'], 'openai_compatible')
        self.assertEqual(admission.admission['real_model_status'], 'not_verified')

    def produce_current(self, generator=None):
        self.original = shifted_dataset(self.original, days=-1)
        source_config = replace(self.builtin.backtest_config, costs=replace(
            self.builtin.backtest_config.costs, effective_from='2025-01-01'))
        config = demo_campaign_config(self.original, source_config)
        config['ranking']['minimum'] = '-1000000'
        reference = 'c' * 64  # Normal workspace selector differs from campaign_id.
        folder = self.root / 'current-campaigns' / reference
        def inline(function, args, **kwargs):
            return {'value': function(*args), 'memory_limit_enforced': False}
        with patch('quantlab.research._run_bounded', side_effect=inline):
            state = run_campaign(self.original, config=config, generator=generator or FixtureGenerator(),
                                 output_dir=folder, holdout_registry_path=self.registry)
        self.assertEqual(state['status'], 'completed')
        self.assertNotEqual(state['campaign_id'], reference)
        return folder, reference, state

    def test_genuine_current_fixture_campaign_to_saved_walk_forward_no_hash_relabelling(self):
        folder, reference, state = self.produce_current()
        self.assertEqual(state['binding']['engine_source_hashes'], TRANSPORT_VERIFIER_PRODUCER['engine_source_hashes'])
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=reference, authoritative_registry_path=self.registry)
        self.assertEqual(admission.admission['producer']['protocol'], 'mark_auto_0_2_2_campaign_transport_verifier_v1')
        self.assertEqual(admission.admission['source_campaign_ref'], reference)
        self.assertEqual(admission.admission['source_campaign_id'], state['campaign_id'])
        self.assertEqual(len(admission.candidate_pool), 15)
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker), \
             patch('quantlab.research._generate_candidate', side_effect=AssertionError('no new generation')):
            result = self.run_saved(plan=self.plan(admission), source_campaign_dir=folder)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['binding']['plan']['pool_admission']['real_model_status'], 'not_verified')

    def test_current_explicit_duplicate_rejections_remain_visible_never_admitted(self):
        class Duplicates(FixtureGenerator):
            def improve(self, context):
                return self.generate(context)
        folder, reference, state = self.produce_current(Duplicates())
        admission = self.admit(source_campaign_dir=folder, source_campaign_ref=reference, authoritative_registry_path=self.registry)
        self.assertEqual(len(admission.candidate_pool), 5)
        rows = admission.admission['attempts']
        self.assertEqual(len(rows), 15)
        self.assertEqual([row['reason'] for row in rows[5:]], ['source_duplicate_rejected'] * 10)
        self.assertTrue(all(row['admitted'] is False and 'duplicate_of' in row for row in rows[5:]))
        for mutation in (lambda a: a.pop('duplicate_of'), lambda a: a.update(duplicate_of='a' * 64),
                         lambda a: a.update(candidate_fingerprint='a' * 64), lambda a: a.update(warnings=[]),
                         lambda a: a.update(status='evaluated')):
            changed = copy.deepcopy(state); mutation(changed['attempts'][5]); write_source(folder, changed)
            with self.assertRaises(SavedCandidatePoolError):
                self.admit(source_campaign_dir=folder, source_campaign_ref=reference, authoritative_registry_path=self.registry)

    def test_saved_journal_over_builtin_cap_is_readable_with_global_budget_consumed(self):
        admission = self.admit()
        plan = build_walk_forward_plan(backtest_config=self.builtin.backtest_config, train_bars=2,
            validation_bars=2, oos_bars=2, fold_count=20, final_holdout=(44, 240),
            pool_origin='saved_campaign_pool', candidate_pool=admission.candidate_pool,
            pool_admission=admission.admission, max_evaluations=221)
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            result = self.run_saved(plan=plan)
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(len(result['evaluations']), 221)
        self.assertEqual(result['summary']['planned_evaluations_upper_bound'], 620)
        self.assertEqual(read_walk_forward_state(self.output), result)

    def test_legacy_builtin_checkpoint_remains_readable_without_optional_fields(self):
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            state = run_walk_forward(self.data, plan=self.builtin, output_dir=self.output, holdout_registry_path=self.registry)
        del state['binding']['plan']['pool_origin']; del state['binding']['plan']['pool_admission']
        state['experiment_id'] = content_hash(state['binding'])
        state['state_hash'] = content_hash({k: v for k, v in state.items() if k != 'state_hash'})
        encoded = canonical_json(state)
        with closing(sqlite3.connect(self.output / 'walk_forward.sqlite3')) as db, db:
            db.execute('UPDATE state SET payload=? WHERE id=1', (encoded,))
        before = (self.output / 'walk_forward.sqlite3').read_bytes()
        self.assertEqual(read_walk_forward_state(self.output), state)
        self.assertEqual((self.output / 'walk_forward.sqlite3').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
