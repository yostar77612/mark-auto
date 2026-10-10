"""Offline, deterministic evidence and mock-wire analysis tests; no owner grant."""
import copy
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import Dataset, ValidationError, canonical_json, content_hash, to_dict
from quantlab.reporting import demo_config, synthetic_dataset
from quantlab.research import _campaign_config, _dataset_identity, _evaluate_split, demo_campaign_config, PROMPT
from quantlab.strategies import builtin_strategies
from quantlab import research_analysis as a
from desktop_chatgpt_auth import OAuthCredentialReference
import desktop_chatgpt_provider as p
from tests.test_chatgpt_plan import MockTransport, frame, provider as campaign_provider, CANDIDATE

PROVENANCE = {'source_sha256': {'offline_fixture': 'a' * 64}}


def write_source(folder, state):
    folder.mkdir(parents=True, exist_ok=True)
    text = canonical_json(state)
    with closing(sqlite3.connect(folder / 'campaign.sqlite3')) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (text,))
    (folder / 'campaign.json').write_text(text)


def source(root, data=None):
    data = data or synthetic_dataset(240)
    config = demo_campaign_config(data, demo_config())
    config.update(families=['trend'], max_trials=2, max_improvements=1)
    splits = _campaign_config(data, config)
    binding = {'config': to_dict(config), 'data_hash': _dataset_identity(data),
               'split_hashes': {name: _dataset_identity(value) for name, value in splits.items()},
               'provider': {'mode': 'fixture', 'model': None, 'endpoint': None},
               'prompt_template_hash': content_hash(PROMPT), 'engine_source_hashes': {}}
    campaign_id = content_hash(binding)
    state = {'campaign_id': campaign_id, 'binding': binding, 'status': 'completed',
             'source_manifest': to_dict(data.manifest), 'attempts': [],
             'evaluations': {'oos': [{'secret': 'DO_NOT_SEND_OOS'}], 'holdout': [{'secret': 'DO_NOT_SEND_HOLDOUT'}]}}
    for index, fast in enumerate((5, 6), 1):
        spec = replace(builtin_strategies()[0], strategy_id='offline_fixture_' + str(index), parameters={'fast': fast, 'slow': 20})
        row = {'attempt_id': content_hash([campaign_id, index]), 'status': 'evaluated',
               'parent_id': state['attempts'][-1]['attempt_id'] if state['attempts'] else None,
               'strategy_hash': content_hash(spec), 'spec': to_dict(spec), 'output': to_dict(spec),
               'output_hash': content_hash(spec),
               'metrics': {role: _evaluate_split(splits[role], spec, config['backtest_config']) for role in ('train', 'validation')}}
        state['attempts'].append(row)
    folder = root / campaign_id
    write_source(folder, state)
    return data, state, folder


def prepare(folder, data, state, compare=False):
    # Most grammar cases use actual deterministic calculation without spawning;
    # the explicit subprocess test below exercises the production worker path.
    with patch.object(a, '_run_bounded', side_effect=lambda function, args, **kw: {'value': function(*args)}):
        return a.build_analysis_packet(source_campaign_dir=folder, original_dataset=data,
            attempt_ids=[row['attempt_id'] for row in state['attempts'][:2 if compare else 1]],
            task='compare' if compare else 'critique')


def response(context):
    targets = [row['strategy_hash'] for row in context['strategies']]
    market = {'evidence_id': context['training']['evidence_id'], 'field': 'ohlcv'}
    refs = [{'evidence_id': row['evidence_id'], 'field': 'net_pnl'} for row in context['evidence']]
    kinds = ('comparison', 'risk') if context['task'] == 'compare' else ('market', 'entry_exit', 'backtest', 'weakness', 'risk', 'improvement')
    rows = []
    for kind in kinds:
        row = {'kind': kind, 'strategy_hashes': targets,
               'evidence_refs': [market] if kind == 'market' else refs,
               'text': 'This is qualitative fixture interpretation with limited historical evidence.'}
        if kind == 'improvement': row['signal_parameter'] = 'fast'
        rows.append(row)
    return {'schema_version': 1, 'task': context['task'], 'findings': rows}


class AnalysisWire:
    """Synthetic wire, explicitly not subscription evidence."""
    requests = []
    failure = None
    mutate = None

    def models(self, reference, limits, cancelled):
        return {'models': [{'slug': 'fixture-model', 'display_name': 'Fixture', 'visibility': 'list'}]}

    def stream(self, reference, request, limits, cancelled):
        self.requests.append(copy.deepcopy(request))
        if self.failure:
            yield frame({'type': 'response.failed', 'response': {'error': {'code': self.failure}}})
            return
        context = json.loads(request['input'][0]['content'])
        value = response(context)
        if self.mutate: self.mutate(value)
        yield frame({'type': 'response.completed', 'response': {'id': 'offline-fixture', 'status': 'completed',
                     'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}})


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data, self.state, self.folder = source(self.root / 'campaigns')
        self.packet = prepare(self.folder, self.data, self.state)
        self.plan = a.make_analysis_plan(self.packet, model='fixture-model', registration='a' * 32,
                                        provider_implementation=PROVENANCE)
        self.provenance = patch.object(p, 'implementation_provenance', return_value=PROVENANCE)
        self.provenance.start(); self.addCleanup(self.provenance.stop)
        self.no_http = patch('http.client.HTTPSConnection', side_effect=AssertionError('No live inference allowed'))
        self.no_http.start(); self.addCleanup(self.no_http.stop)
        self.wire = patch.object(p, 'PlanHTTPTransport', AnalysisWire)
        self.wire.start(); self.addCleanup(self.wire.stop)
        AnalysisWire.requests = []; AnalysisWire.failure = None; AnalysisWire.mutate = None
        self.provider = self.make_provider()

    def make_provider(self, plan=None, consent=True):
        return p.analysis_provider(plan or self.plan, OAuthCredentialReference(str(self.root / 'auth'), 'a' * 32),
                                   network_opt_in=consent, included_usage_policy_confirmed=consent)

    def run_analysis(self, **options):
        arguments = dict(output_root=self.root / 'analyses', plan=self.plan, provider=self.provider,
                         expected_analysis_id=self.plan['analysis_id'], user_confirmed=True)
        arguments.update(options)
        return a.run_analysis(**arguments)

    def test_exact_training_window_and_evidence(self):
        context = self.packet['context']
        self.assertIn('Traditional Chinese', a.ANALYSIS_PROMPT)
        self.assertEqual(context['training']['window_count'], 64)
        self.assertEqual(context['training']['bars'][0]['timestamp'], self.data.bars[56].timestamp.isoformat())
        self.assertEqual({row['split'] for row in context['evidence']}, {'train', 'validation'})
        self.assertNotIn('DO_NOT_SEND', canonical_json(context))
        self.assertNotIn(self.state['campaign_id'], canonical_json(context))
        self.assertEqual(self.packet['provenance']['verification'], 'selected_train_validation_recomputed')
        self.assertTrue(all(link['recomputed_result_hash'] for link in self.packet['provenance']['result_links']))

    def test_real_bounded_subprocess_preparation(self):
        packet = a.build_analysis_packet(source_campaign_dir=self.folder, original_dataset=self.data,
            attempt_ids=[self.state['attempts'][0]['attempt_id']], max_runtime_seconds=30)
        self.assertEqual(packet, self.packet)

    def test_heldout_changes_never_change_transmission_context(self):
        bars = list(self.data.bars)
        for i in range(self.state['binding']['config']['splits']['oos'][0], len(bars)):
            bar = bars[i]
            bars[i] = replace(bar, open=bar.open + 500, high=bar.high + 500, low=bar.low + 500, close=bar.close + 500)
        manifest = dict(self.data.manifest); manifest['data_hash'] = content_hash(tuple(bars))
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('manifest_hash', 'imported_at')})
        data = Dataset(tuple(bars), manifest, dict(self.data.quality))
        data, state, folder = source(self.root / 'other', data)
        packet = prepare(folder, data, state)
        self.assertEqual(packet['context'], self.packet['context'])
        self.assertNotEqual(packet['packet_hash'], self.packet['packet_hash'])

    def test_wrong_original_and_tampered_metrics_reject_before_call(self):
        with self.assertRaises(ValidationError): prepare(self.folder, synthetic_dataset(241), self.state)
        self.state['attempts'][0]['metrics']['train']['metrics']['net_pnl'] = '999999'
        write_source(self.folder, self.state)
        with self.assertRaises(ValidationError): prepare(self.folder, self.data, self.state)
        self.assertEqual(AnalysisWire.requests, [])

    def test_compare_is_selected_distinct_candidates_only(self):
        packet = prepare(self.folder, self.data, self.state, True)
        self.assertEqual(len(packet['context']['strategies']), 2)
        a.validate_analysis_response(response(packet['context']), packet['context'])
        with self.assertRaises(ValidationError):
            a.build_analysis_packet(source_campaign_dir=self.folder, original_dataset=self.data,
                attempt_ids=[self.state['attempts'][0]['attempt_id']] * 2, task='compare')

    def test_closed_response_rejects_invented_metrics_references_and_risk(self):
        good = response(self.packet['context'])
        mutations = [lambda value: value.update(metrics={'net_pnl': 100}),
                     lambda value: value['findings'][0]['evidence_refs'][0].update(evidence_id='f' * 64),
                     lambda value: value['findings'][1]['evidence_refs'][0].update(field='invented_ratio'),
                     lambda value: value['findings'][-1].update(signal_parameter='quantity'),
                     lambda value: value['findings'][-1].update(signal_parameter='stop_ticks'),
                     lambda value: value['findings'][-1].update(signal_parameter='target_ticks'),
                     lambda value: value['findings'][0].update(text='Profit is 999'),
                     lambda value: value['findings'][0].update(strategy_hashes=['f' * 64]),
                     lambda value: value.update(code='execute_order()')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(good); mutation(value)
                with self.assertRaises(ValidationError): a.validate_analysis_response(value, self.packet['context'])
        for key in ('oos', 'holdout', 'full_manifest'):
            context = copy.deepcopy(self.packet['context']); context[key] = {}
            with self.assertRaises(ValidationError): a.validate_analysis_context(context)

    def test_one_call_saved_reopened_without_network_or_consent(self):
        source_bytes = (self.folder / 'campaign.sqlite3').read_bytes()
        first = self.run_analysis()
        self.assertFalse(first['cache_hit']); self.assertEqual(len(AnalysisWire.requests), 1)
        self.assertEqual(first['record']['status'], 'completed')
        self.assertEqual(first['record']['real_model_status'], 'not_verified')
        self.assertEqual(len(first['record']['receipt_snapshot']['receipts']), 1)
        second = self.run_analysis(provider=self.make_provider(consent=False), user_confirmed=False)
        self.assertTrue(second['cache_hit']); self.assertEqual(first['record'], second['record'])
        self.assertEqual(a.read_analysis(self.root / 'analyses', self.plan['analysis_id']), first['record'])
        self.assertEqual(source_bytes, (self.folder / 'campaign.sqlite3').read_bytes())
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_missing_output_or_old_workspace_restore_never_repeats_call(self):
        first = self.run_analysis()
        shutil.rmtree(self.root / 'analyses')
        with self.assertRaisesRegex(ValidationError, 'consumed reservation'): self.run_analysis()
        self.assertEqual(len(AnalysisWire.requests), 1)
        self.assertEqual(len(self.provider.read_receipts()), 1)
        self.assertEqual(first['record']['receipt_snapshot']['receipts'][0]['status'], 'completed')

    def test_changed_timeout_does_not_mint_new_analysis_budget(self):
        self.run_analysis()
        altered = a.make_analysis_plan(self.packet, model='fixture-model', registration='a' * 32,
                    provider_implementation=PROVENANCE, timeout_seconds=60)
        self.assertEqual(altered['analysis_id'], self.plan['analysis_id'])
        with self.assertRaises(ValidationError): self.run_analysis(plan=altered, provider=self.make_provider(altered))
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_no_implicit_authorization_or_stale_preview(self):
        for options in ({'user_confirmed': False}, {'provider': self.make_provider(consent=False)},
                        {'expected_analysis_id': 'f' * 64}, {'cancelled': lambda: True}):
            with self.subTest(options=options), self.assertRaises(ValidationError): self.run_analysis(**options)
        self.assertEqual(AnalysisWire.requests, [])
        self.assertEqual(self.provider.read_receipts(), [])

    def test_quota_failure_is_saved_and_never_retried(self):
        AnalysisWire.failure = 'subscription_sharing_usage_limit_exceeded'
        with self.assertRaises(p.PlanError): self.run_analysis()
        saved = a.read_analysis(self.root / 'analyses', self.plan['analysis_id'])
        self.assertEqual(saved['status'], 'blocked')
        self.assertEqual(saved['receipt_snapshot']['receipts'][0]['status'], 'quota_paused')
        with self.assertRaises(ValidationError): self.run_analysis()
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_invalid_analysis_output_consumes_and_blocks_shared_controls(self):
        AnalysisWire.mutate = staticmethod(lambda value: value.update(metrics={'profit': 'invention'}))
        with self.assertRaises(p.PlanError): self.run_analysis()
        saved = a.read_analysis(self.root / 'analyses', self.plan['analysis_id'])
        self.assertIsNone(saved['response']); self.assertEqual(saved['status'], 'blocked')
        self.assertEqual(saved['receipt_snapshot']['receipts'][0]['status'], 'invalid_output')
        campaign = campaign_provider(self.root)
        with self.assertRaises(p.PlanError): campaign.generate({'family': 'trend'})
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_campaign_pending_blocks_analysis_without_new_inference(self):
        campaign = campaign_provider(self.root)
        campaign._reserve('a' * 64, 100)
        with self.assertRaises(p.PlanError): self.run_analysis()
        self.assertEqual(AnalysisWire.requests, [])
        self.assertEqual(self.provider.read_receipts(), [])
        self.assertEqual(campaign.read_receipts()[0]['status'], 'reserved_unknown')

    def test_analysis_pending_blocks_generation_and_requires_stop_proof(self):
        self.provider._reserve(content_hash(a.analysis_request(self.plan)), len(canonical_json(a.analysis_request(self.plan)).encode()))
        campaign = campaign_provider(self.root)
        with self.assertRaises(p.PlanError): campaign.generate({'family': 'trend'})
        with self.assertRaises(ValidationError): a.reconcile_analysis(output_root=self.root / 'analyses',
            analysis_id=self.plan['analysis_id'], provider=self.provider)
        self.assertEqual(AnalysisWire.requests, [])

    def test_local_cancel_and_deadline_do_not_write_holdout_or_controls(self):
        before = {path: path.read_bytes() for path in self.folder.iterdir()}
        with self.assertRaisesRegex(ValidationError, 'cancelled'):
            a.build_analysis_packet(source_campaign_dir=self.folder, original_dataset=self.data,
                attempt_ids=[self.state['attempts'][0]['attempt_id']], cancelled=lambda: True)
        with patch.object(a, '_run_bounded', side_effect=ValidationError('total deadline')):
            with self.assertRaisesRegex(ValidationError, 'total deadline'):
                a.build_analysis_packet(source_campaign_dir=self.folder, original_dataset=self.data,
                    attempt_ids=[self.state['attempts'][0]['attempt_id']])
        self.assertEqual(before, {path: path.read_bytes() for path in self.folder.iterdir()})
        self.assertFalse((self.root / 'auth').exists())
        self.assertEqual(AnalysisWire.requests, [])

    def test_optional_schema_version_output_is_admitted_without_rewriting_source(self):
        row = self.state['attempts'][0]
        row['output'].pop('schema_version')
        row['output_hash'] = content_hash(row['output'])
        write_source(self.folder, self.state)
        packet = prepare(self.folder, self.data, self.state)
        self.assertEqual(packet['context'], self.packet['context'])

    def test_invalid_context_and_plan_primitives_fail_closed(self):
        for key in ('schema_version', 'max_calls'):
            plan = copy.deepcopy(self.plan); plan['binding'][key] = True
            with self.assertRaises(ValidationError): a.validate_analysis_plan(plan)
        value = response(self.packet['context'])
        value['findings'][0]['evidence_refs'][0]['field'] = []
        with self.assertRaises(ValidationError): a.validate_analysis_response(value, self.packet['context'])
        value = response(self.packet['context']); value['findings'][0]['strategy_hashes'] = [{}]
        with self.assertRaises(ValidationError): a.validate_analysis_response(value, self.packet['context'])

    def test_success_then_local_save_failure_never_repeats_remote_call(self):
        original = a._save
        def save(folder, record):
            if record['status'] == 'completed': raise OSError('offline simulated crash window')
            return original(folder, record)
        with patch.object(a, '_save', side_effect=save):
            with self.assertRaises(OSError): self.run_analysis()
        saved = a.read_analysis(self.root / 'analyses', self.plan['analysis_id'])
        self.assertEqual(saved['status'], 'blocked'); self.assertIsNone(saved['response'])
        self.assertEqual(saved['receipt_snapshot']['receipts'][0]['status'], 'completed')
        with self.assertRaises(ValidationError): self.run_analysis()
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_pending_record_reconciliation_requires_same_provider_and_no_network(self):
        descriptor = self.provider.provider_descriptor()
        folder = self.root / 'analyses' / self.plan['analysis_id']; folder.mkdir(parents=True)
        with closing(sqlite3.connect(folder / 'analysis.lock.sqlite3')): pass
        record = {'schema_version': 1, 'plan': self.plan, 'provider_descriptor': descriptor,
                  'status': 'running', 'response': None, 'response_hash': None,
                  'receipt_snapshot': self.provider.read_receipt_snapshot(), 'real_model_status': 'not_verified'}
        a._save(folder, record)
        request = a.analysis_request(self.plan)
        self.provider._reserve(content_hash(request), len(canonical_json(request).encode()))
        with self.assertRaises(ValidationError): self.run_analysis()
        saved = a.reconcile_analysis(output_root=self.root / 'analyses', analysis_id=self.plan['analysis_id'],
            provider=self.make_provider(consent=False), descendants_stopped=True)
        self.assertEqual(saved['status'], 'blocked')
        self.assertEqual(saved['receipt_snapshot']['receipts'][0]['status'], 'reserved_unknown')
        self.assertEqual(AnalysisWire.requests, [])
        with self.assertRaises(ValidationError): self.run_analysis()

    def test_concurrent_duplicate_click_has_one_reserved_call(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        class BlockingWire(AnalysisWire):
            def stream(wire, reference, request, limits, cancelled):
                entered.set()
                if not release.wait(5): raise AssertionError('fixture gate timed out')
                yield from super().stream(reference, request, limits, cancelled)
        with patch.object(p, 'PlanHTTPTransport', BlockingWire), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.run_analysis)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ValidationError, 'already running'): self.run_analysis()
            finally: release.set()
            self.assertEqual(first.result(5)['record']['status'], 'completed')
        self.assertEqual(len(AnalysisWire.requests), 1)
        self.assertEqual(len(self.provider.read_receipts()), 1)

    def test_tampered_saved_output_is_not_cache_success(self):
        self.run_analysis()
        path = self.root / 'analyses' / self.plan['analysis_id'] / 'analysis.json'
        saved = json.loads(path.read_text()); saved['response']['findings'][0]['text'] = 'tampered'
        path.write_text(canonical_json(saved))
        with self.assertRaises(ValidationError): self.run_analysis()
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_offline_read_rejects_forged_descriptor_plan_binding(self):
        record = self.run_analysis()['record']
        folder = self.root / 'analyses' / self.plan['analysis_id']
        mutations = {'registration': 'b' * 32, 'campaign_id': 'unrelated-campaign',
                     'endpoint': 'https://example.invalid/v1', 'billing_route': 'paid_api',
                     'paid_api_fallback': True, 'max_calls': 2, 'max_response_bytes': 1048576,
                     'timeout_seconds': 120, 'source_sha256': {'offline_fixture': 'f' * 64}}
        for key, value in mutations.items():
            forged = copy.deepcopy(record); forged['provider_descriptor'][key] = value
            forged['receipt_snapshot']['provider_descriptor_hash'] = content_hash(forged['provider_descriptor'])
            text = canonical_json(forged)
            with closing(sqlite3.connect(folder / 'analysis.sqlite3')) as db, db:
                db.execute('UPDATE state SET payload=? WHERE id=1', (text,))
            (folder / 'analysis.json').write_text(text)
            with self.subTest(field=key), self.assertRaises(ValidationError):
                a.read_analysis(self.root / 'analyses', self.plan['analysis_id'])
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_archived_hash_is_explicitly_unverified_reference_only(self):
        self.state['attempts'][0]['metrics']['train']['result_hash'] = 'f' * 64
        write_source(self.folder, self.state)
        packet = prepare(self.folder, self.data, self.state)
        self.assertEqual(packet['provenance']['archived_result_status'], 'reference_only_unverified')
        train = packet['provenance']['result_links'][0]
        self.assertEqual(train['stored_result_hash'], 'f' * 64)
        self.assertNotEqual(train['stored_result_hash'], train['recomputed_result_hash'])
        self.assertEqual(packet['context'], self.packet['context'])
        self.assertNotIn('verified_result_hash', canonical_json(packet))

    def test_analysis_adapter_rejects_wrong_purpose_before_any_side_effect(self):
        analysis_id = self.plan['analysis_id']
        invalid = [
            ('test-campaign', 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + analysis_id.upper(), 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + 'a' * 63, 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + 'a' * 65, 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + 'g' * 64, 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + analysis_id, 'plan.sqlite', 1, 'analysis_purpose_required'),
            ('analysis-' + analysis_id, 'chatgpt-analysis-' + 'f' * 64 + '.sqlite3', 1,
             'analysis_purpose_required'),
            ('analysis-' + analysis_id, 'chatgpt-analysis-' + analysis_id + '.sqlite3', 2,
             'invalid_limit'),
        ]
        for campaign_id, filename, max_calls, code in invalid:
            adapter = campaign_provider(self.root, campaign_id=campaign_id, max_calls=max_calls,
                budget_path=self.root / 'auth' / 'control-v1' / filename)
            before = adapter.read_receipt_snapshot()
            for operation in ('analysis_preflight', 'analyze'):
                with self.subTest(campaign=campaign_id, filename=filename, operation=operation), \
                     patch.object(p, 'PlanHTTPTransport') as transport, \
                     patch.object(adapter, '_preflight') as preflight, \
                     patch.object(adapter, '_reserve') as reserve:
                    with self.assertRaisesRegex(p.PlanError, '^' + code + '$'):
                        if operation == 'analyze': adapter.analyze(self.packet['context'])
                        else: adapter.analysis_preflight()
                    transport.assert_not_called(); preflight.assert_not_called(); reserve.assert_not_called()
                self.assertEqual(adapter.read_receipt_snapshot(), before)
                self.assertFalse(adapter.path.exists())
                self.assertFalse(adapter.account_path.exists())
        self.assertEqual(AnalysisWire.requests, [])

    def test_analysis_adapter_preserves_existing_generation_receipt(self):
        campaign = campaign_provider(self.root, max_calls=1)
        with patch.object(p, 'PlanHTTPTransport', MockTransport):
            MockTransport.requests = []; MockTransport.events = None
            campaign.generate({'family': 'trend', 'iteration': 0})
        before = {path.name: path.read_bytes() for path in campaign.path.parent.iterdir()}
        snapshot = campaign.read_receipt_snapshot()
        with patch.object(p, 'PlanHTTPTransport') as transport, patch.object(campaign, '_reserve') as reserve:
            with self.assertRaisesRegex(p.PlanError, '^analysis_purpose_required$'):
                campaign.analysis_preflight()
            with self.assertRaisesRegex(p.PlanError, '^analysis_purpose_required$'):
                campaign.analyze(self.packet['context'])
            transport.assert_not_called(); reserve.assert_not_called()
        self.assertEqual(campaign.read_receipt_snapshot(), snapshot)
        self.assertEqual({path.name: path.read_bytes() for path in campaign.path.parent.iterdir()}, before)

    def test_generation_request_wire_and_improvement_are_unchanged(self):
        context = {'family': 'trend', 'iteration': 0}
        campaign = campaign_provider(self.root)
        with patch.object(p, 'PlanHTTPTransport', MockTransport):
            MockTransport.requests = []; MockTransport.events = None
            self.assertEqual(campaign.generate(context), CANDIDATE)
            self.assertEqual(campaign.improve(context), CANDIDATE)
        expected = {'model': 'fixture-model', 'instructions': PROMPT,
                    'input': [{'role': 'user', 'content': canonical_json(context)}], 'store': False, 'stream': True}
        self.assertEqual(MockTransport.requests[0][1], expected)
        improved = dict(context, task='improve_previous_candidate', improvement_instruction=
                        'Propose a distinct candidate in the same family using training and validation feedback only. Keep risk controls unchanged.')
        self.assertEqual(MockTransport.requests[1][1], {**expected, 'input': [{'role': 'user', 'content': canonical_json(improved)}]})
        self.assertEqual(len(campaign.read_receipts()), 2)


if __name__ == '__main__': unittest.main()
