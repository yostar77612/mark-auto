"""Offline desktop critique integration. No grant, model service or held-out evaluation."""

import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from quantlab.core import content_hash
from quantlab.reporting import save_dataset, synthetic_dataset
from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError
from tests import test_desktop_ui as ui_support
from tests.test_research_analysis import source, PROVENANCE, AnalysisWire
import quantlab.research_analysis as analysis
import quantlab.assistant.adapters.chatgpt.provider as provider

REF = 'a' * 32


def _offline_analysis_job_worker(*args):
    """Spawn-safe wrapper around the real worker; no provider can be constructed."""
    from quantlab.research_core.adapters.job_worker import _job_worker

    with (
        patch('desktop_app.shell.main_window.analysis_provider_for', side_effect=AssertionError('No analysis provider in cancellation fixture')),
        patch('quantlab.assistant.adapters.chatgpt.provider.ChatGPTPlanProvider.__init__', side_effect=AssertionError('No provider controls')),
        patch('quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport', side_effect=AssertionError('No provider transport')),
        patch('http.client.HTTPSConnection', side_effect=AssertionError('No network')),
    ):
        _job_worker(*args)


def request_for(paths, data, state, folder, compare=False):
    file = paths.root / 'original.json'
    save_dataset(data, file)
    return {
        'campaign_reference': folder.name,
        'original_dataset': {'kind': 'local_dataset_file', 'path': str(file)},
        'attempt_ids': [row['attempt_id'] for row in state['attempts'][: 2 if compare else 1]],
        'task': 'compare' if compare else 'critique',
        'registration': REF,
        'model': 'fixture-model',
        'timeout_seconds': 30,
    }


class AnalysisRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.addCleanup(self.jobs.close)
        self.request = {
            'campaign_reference': 'b' * 64,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(self.paths.root / 'original.json')},
            'attempt_ids': ['c' * 64],
            'task': 'critique',
            'registration': REF,
            'model': 'fixture-model',
            'timeout_seconds': 30,
        }

    def test_runtime_and_ui_operation_sets_match(self):
        from desktop_app.shell.main_window import UI_OPERATIONS
        from quantlab.desktop_runtime import UI_OPERATIONS as runtime

        self.assertEqual(UI_OPERATIONS, runtime)

    def test_closed_grammar_rejects_tokens_context_paths_and_unknown_budgets_before_spawn(self):
        mutations = [
            lambda r: r.update(token='SECRET'),
            lambda r: r.update(context={'holdout': 'SECRET'}),
            lambda r: r.update(max_calls=2),
            lambda r: r.update(timeout_seconds=True),
            lambda r: r['original_dataset'].update(path='https://example.test/dataset'),
            lambda r: r['original_dataset'].update(path='//server/share'),
            lambda r: r.update(attempt_ids=['c' * 64, 'c' * 64], task='compare'),
            lambda r: r.update(task='compare'),
        ]
        for mutate in mutations:
            request = copy.deepcopy(self.request)
            mutate(request)
            with self.subTest(request=request), patch('quantlab.research_core.adapters.job_process.mp.get_context') as spawn:
                with self.assertRaises(RuntimeSafetyError):
                    self.jobs.start('ui_analysis_preview', {'request': request})
                spawn.assert_not_called()

    def test_run_requires_all_explicit_consents_before_spawn(self):
        payload = {
            'request': self.request,
            'expected_analysis_id': 'd' * 64,
            'expected_plan_hash': 'e' * 64,
            'user_confirmed': True,
            'network_opt_in': True,
            'included_usage_policy_confirmed': True,
        }
        for field in ('user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'):
            with self.subTest(field=field), patch('quantlab.research_core.adapters.job_process.mp.get_context') as spawn:
                with self.assertRaises(RuntimeSafetyError):
                    self.jobs.start('ui_analysis_run', {**payload, field: False})
                spawn.assert_not_called()

    def test_reconcile_requires_same_manager_job_analysis_and_registration(self):
        good = {'analysis_id': 'd' * 64, 'registration': REF, 'stopped_job_id': 'real-owned-job'}
        for proof in (None, ('other-job', 'd' * 64, REF), ('real-owned-job', 'e' * 64, REF), ('real-owned-job', 'd' * 64, 'f' * 32)):
            self.jobs._quiesced_analysis = proof
            with patch('quantlab.research_core.adapters.job_process.mp.get_context') as spawn:
                with self.assertRaises(RuntimeSafetyError):
                    self.jobs.start('ui_analysis_reconcile', good)
                spawn.assert_not_called()

    def test_release_cannot_mint_analysis_stop_proof_without_tree_join(self):
        self.jobs.job_id = 'original'
        self.jobs._analysis_job_identity = ('d' * 64, REF)
        self.jobs._tree_quiesced = False
        self.jobs._release()
        self.assertIsNone(self.jobs._quiesced_analysis)
        self.jobs._tree_quiesced = True
        self.jobs._release()
        self.assertEqual(self.jobs._quiesced_analysis, ('original', 'd' * 64, REF))

    def test_analysis_without_pid_or_windows_tree_never_claims_stop_proof(self):
        self.jobs._operation = 'ui_analysis_run'
        with patch('quantlab.desktop_runtime.sys.platform', 'win32'):
            with self.assertRaises(RuntimeSafetyError):
                self.jobs._join_descendants(123)
        with self.assertRaises(RuntimeSafetyError):
            self.jobs._join_descendants(None)
        self.assertFalse(self.jobs._tree_quiesced)
        self.assertIsNone(self.jobs._quiesced_analysis)

    def test_packaging_keeps_exact_analysis_and_indicator_source_bytes(self):
        spec = (Path(__file__).resolve().parents[1] / 'packaging/markauto.spec').read_text()
        for file in ('research_analysis.py', 'indicators.py'):
            self.assertIn("(str(root / 'quantlab' / '" + file + "'), 'quantlab')", spec)


@unittest.skipUnless(ui_support.HAS_QT, 'Pinned Qt needed')
class AnalysisWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.data, self.state, self.folder = source(self.paths.state / 'campaigns')
        self.request = request_for(self.paths, self.data, self.state, self.folder)
        for patcher in (
            patch.object(analysis, '_run_bounded', side_effect=lambda f, args, **kw: {'value': f(*args)}),
            patch.object(provider, 'implementation_provenance', return_value=PROVENANCE),
            patch.object(provider, 'PlanHTTPTransport', AnalysisWire),
            patch('http.client.HTTPSConnection', side_effect=AssertionError('No live network')),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        AnalysisWire.requests = []
        AnalysisWire.failure = None
        AnalysisWire.mutate = None

    def call(self, operation, payload, **kw):
        from desktop_app.connection_composition import execute_ui_operation

        return execute_ui_operation(operation, payload, self.paths, **kw)

    def preview(self):
        return self.call('ui_analysis_preview', {'request': self.request})

    def run_payload(self, preview):
        return {
            'request': self.request,
            'expected_analysis_id': preview['analysis_id'],
            'expected_plan_hash': content_hash(preview['plan']),
            'user_confirmed': True,
            'network_opt_in': True,
            'included_usage_policy_confirmed': True,
        }

    def test_preview_recomputes_only_training_validation_and_never_calls(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        preview = self.preview()
        self.assertEqual(preview['receipt_snapshot']['receipts'], [])
        self.assertEqual(AnalysisWire.requests, [])
        context = preview['plan']['binding']['packet']['context']
        self.assertNotIn('DO_NOT_SEND', json.dumps(context))
        self.assertEqual({r['split'] for r in context['evidence']}, {'train', 'validation'})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})
        self.assertFalse((self.paths.state / 'analyses').exists())

    def test_original_loader_rejects_duplicate_keys_before_preparation(self):
        file = Path(self.request['original_dataset']['path'])
        raw = file.read_text()
        file.write_text(raw.replace('{', '{"bars":[],', 1))
        with patch.object(analysis, 'build_analysis_packet') as build:
            with self.assertRaises(ValueError):
                self.preview()
        build.assert_not_called()
        self.assertEqual(AnalysisWire.requests, [])

    def test_changed_dataset_after_preview_rejects_before_provider(self):
        preview = self.preview()
        save_dataset(synthetic_dataset(241), Path(self.request['original_dataset']['path']))
        with self.assertRaises(ValueError):
            self.call('ui_analysis_run', self.run_payload(preview))
        self.assertEqual(AnalysisWire.requests, [])

    def test_changed_model_after_preview_does_not_mint_calls(self):
        preview = self.preview()
        self.request['model'] = 'different-model'
        with self.assertRaises(ValueError):
            self.call('ui_analysis_run', self.run_payload(preview))
        self.assertEqual(AnalysisWire.requests, [])

    def test_changed_timeout_after_preview_refuses_even_though_call_identity_is_stable(self):
        preview = self.preview()
        self.request['timeout_seconds'] = 60
        with self.assertRaises(ValueError):
            self.call('ui_analysis_run', self.run_payload(preview))
        self.assertEqual(AnalysisWire.requests, [])

    def test_repeated_run_is_cache_and_read_has_no_auth_dependency(self):
        preview = self.preview()
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        first = self.call('ui_analysis_run', self.run_payload(preview))
        self.assertFalse(first['cache_hit'])
        second = self.call('ui_analysis_run', self.run_payload(preview))
        self.assertTrue(second['cache_hit'])
        self.assertEqual(len(AnalysisWire.requests), 1)
        with patch('desktop_app.shell.main_window.analysis_provider_for', side_effect=AssertionError('Saved read cannot touch grant')):
            loaded = self.call('ui_analysis_read', {'analysis_id': preview['analysis_id']})
        self.assertEqual(loaded['record'], first['record'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_reconcile_needs_tree_proof_and_retains_original_registration(self):
        preview = self.preview()
        self.call('ui_analysis_run', self.run_payload(preview))
        request = {'analysis_id': preview['analysis_id'], 'registration': REF, 'stopped_job_id': 'owned'}
        with self.assertRaises(ValueError):
            self.call('ui_analysis_reconcile', request)
        with self.assertRaises(ValueError):
            self.call('ui_analysis_reconcile', {**request, 'registration': 'f' * 32}, descendants_stopped=True)
        self.call('ui_analysis_reconcile', request, descendants_stopped=True)
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_reconcile_routes_missing_projection_through_validated_journal(self):
        preview = self.preview()
        result = self.call('ui_analysis_run', self.run_payload(preview))
        projection = self.paths.state / 'analyses' / preview['analysis_id'] / 'analysis.json'
        projection.unlink()
        with self.assertRaises(ValueError):
            self.call('ui_analysis_read', {'analysis_id': preview['analysis_id']})
        request = {'analysis_id': preview['analysis_id'], 'registration': REF, 'stopped_job_id': 'owned'}
        with self.assertRaises(ValueError):
            self.call('ui_analysis_reconcile', request)
        with self.assertRaises(ValueError):
            self.call('ui_analysis_reconcile', {**request, 'registration': 'f' * 32}, descendants_stopped=True)
        self.assertFalse(projection.exists())
        recovered = self.call('ui_analysis_reconcile', request, descendants_stopped=True)
        self.assertEqual(recovered['record'], result['record'])
        self.assertEqual(self.call('ui_analysis_read', {'analysis_id': preview['analysis_id']})['record'], result['record'])
        self.assertEqual(len(AnalysisWire.requests), 1)

    def test_plain_text_findings_use_local_values_and_do_not_apply_suggestions(self):
        from desktop_app.shell.main_window import analysis_record_text

        preview = self.preview()
        result = self.call('ui_analysis_run', self.run_payload(preview))
        text = analysis_record_text(result['record'])
        self.assertIn('未驗證的 AI 解讀', text)
        self.assertIn('舊結果僅作來源索引', text)
        number = preview['plan']['binding']['packet']['context']['evidence'][0]['metrics']['net_pnl']
        self.assertIn(str(number), text)
        self.assertIn('（不套用）', text)
        self.assertFalse((self.paths.state / 'selection.json').exists())

    def test_comparison_values_identify_each_candidate_and_exact_split(self):
        from desktop_app.shell.main_window import analysis_record_text, ANALYSIS_METRICS

        self.request = request_for(self.paths, self.data, self.state, self.folder, compare=True)
        preview = self.preview()
        result = self.call('ui_analysis_run', self.run_payload(preview))
        text = analysis_record_text(result['record'])
        evidence = preview['plan']['binding']['packet']['context']['evidence']
        self.assertEqual(len({row['strategy_hash'] for row in evidence}), 2)
        self.assertEqual({row['split'] for row in evidence}, {'train', 'validation'})
        for row in evidence:
            split = ('訓練' if row['split'] == 'train' else '驗證') + '（' + row['split'] + '）'
            expected = '候選 ' + row['strategy_hash'][:16] + ' · 本機' + split + ' ' + ANALYSIS_METRICS['net_pnl'] + '：' + str(row['metrics']['net_pnl'])
            self.assertIn(expected, text)
        # A shared candidate header does not establish which candidate owns a
        # numeric row; no anonymous train/validation result line may survive.
        self.assertNotRegex(text, r'(?m)^本機(?:訓練|驗證)\b')


@unittest.skipUnless(ui_support.HAS_QT, 'Pinned Qt needed')
class SpawnedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.addCleanup(self.jobs.close)
        data, state, folder = source(self.paths.state / 'campaigns')
        self.request = request_for(self.paths, data, state, folder)

    def test_real_spawned_preview_is_local_and_preserves_source(self):
        before = {str(p.relative_to(self.paths.root)): p.read_bytes() for p in self.paths.root.rglob('*') if p.is_file()}
        self.jobs.start('ui_analysis_preview', {'request': self.request})
        events = []
        deadline = time.monotonic() + 30
        while self.jobs.active and time.monotonic() < deadline:
            events.extend(self.jobs.poll())
            time.sleep(0.01)
        events.extend(self.jobs.poll())
        self.assertFalse(self.jobs.active)
        errors = [event for event in events if event['type'] == 'error']
        self.assertEqual(errors, [])
        result = next(event['result'] for event in events if event['type'] == 'result')
        self.assertEqual(result['receipt_snapshot']['receipts'], [])
        for name, raw in before.items():
            self.assertEqual((self.paths.root / name).read_bytes(), raw, name)
        self.assertFalse((self.paths.state / 'analyses').exists())
        self.assertFalse(list(self.paths.controls.glob('chatgpt-analysis-*')))

    def test_cancelled_spawned_run_has_exact_process_local_stop_proof(self):
        # Windows durable admission now requires the exact approved plan, before
        # spawning. Deny provider construction inside the real spawned worker so
        # even delayed cancellation cannot create a request or provider ledger.
        from desktop_app.shell.main_window import analysis_plan

        plan = analysis_plan(self.paths, self.request)
        payload = {
            'request': self.request,
            'expected_analysis_id': plan['analysis_id'],
            'expected_plan_hash': content_hash(plan),
            'approved_plan': plan,
            'user_confirmed': True,
            'network_opt_in': True,
            'included_usage_policy_confirmed': True,
        }
        with patch('quantlab.research_core.adapters.job_worker._job_worker', _offline_analysis_job_worker):
            job_id = self.jobs.start('ui_analysis_run', payload)
            self.jobs.cancel()
        self.assertFalse(self.jobs.active)
        self.assertEqual(self.jobs._quiesced_analysis, (job_id, plan['analysis_id'], REF))
        other = JobManager(self.paths)
        self.addCleanup(other.close)
        with self.assertRaises(RuntimeSafetyError):
            other.start('ui_analysis_reconcile', {'analysis_id': plan['analysis_id'], 'registration': REF, 'stopped_job_id': job_id})
        self.assertFalse((self.paths.state / 'analyses').exists())
        self.assertFalse(list(self.paths.controls.glob('chatgpt-analysis-*')))


@unittest.skipUnless(ui_support.HAS_QT, 'Pinned Qt needed')
class AnalysisWidgetTests(unittest.TestCase):
    setUpClass = ui_support.NativeDesktopTests.__dict__['setUpClass']
    setUp = ui_support.NativeDesktopTests.setUp
    cleanup_window = ui_support.NativeDesktopTests.cleanup_window

    def prepare(self, compare=False):
        w = self.window
        c = w.chatgpt_controller
        w.chatgpt_panel
        data, state, folder = source(self.paths.state / 'campaigns')
        request = request_for(self.paths, data, state, folder, compare)
        c.state = 'plan_ready'
        c.active_registration = REF
        c.registrations = ((REF, 'plan_ready'),)
        c.models = ('fixture-model',)
        c.changed.emit()
        w.refresh_views()
        w.analysis_original.setText(request['original_dataset']['path'])
        for i in range(2 if compare else 1):
            w.analysis_candidates.item(i).setSelected(True)
        with (
            patch.object(provider, 'implementation_provenance', return_value=PROVENANCE),
            patch.object(analysis, '_run_bounded', side_effect=lambda f, args, **kw: {'value': f(*args)}),
        ):
            from desktop_app.connection_composition import execute_ui_operation

            preview = execute_ui_operation('ui_analysis_preview', {'request': request}, self.paths)
        w._analysis_request_key = content_hash(w._analysis_request(request['task']))
        w.last_operation = 'ui_analysis_preview'
        w._analysis_event({'type': 'result', 'result': preview})
        return request, preview

    def test_startup_inert_and_no_duplicate_login_or_provider_controls(self):
        w = self.window
        self.assertFalse(self.jobs.active)
        self.assertFalse(w.analysis_start.isEnabled())
        self.assertFalse(w.analysis_consent.isChecked())
        self.assertFalse(w.chatgpt_panel.consent.isChecked())
        self.assertEqual(w.analysis_findings.toPlainText(), '')
        self.assertIsNone(w._analysis_launch)

    def test_selected_candidates_must_share_campaign_and_counts(self):
        from PySide6.QtCore import Qt

        w = self.window
        request, preview = self.prepare(True)
        with self.assertRaises(ValueError):
            w._analysis_request('critique')
        ref = w.analysis_candidates.item(1).data(Qt.ItemDataRole.UserRole)
        ref = {**ref, 'campaign_folder': 'f' * 64}
        w.analysis_candidates.item(1).setData(Qt.ItemDataRole.UserRole, ref)
        with self.assertRaises(ValueError):
            w._analysis_request('compare')

    def test_preview_is_readable_separate_from_campaign_usage(self):
        w = self.window
        request, preview = self.prepare()
        self.assertIn('本次重新計算', w.analysis_preview.toPlainText())
        self.assertIn('不可退還', w.analysis_preview.toPlainText())
        self.assertIn('open', json.loads(w.analysis_evidence.toPlainText())['training']['bars'][0])
        self.assertFalse(w.chatgpt_controller.usage_known)
        self.assertFalse(w.analysis_consent.isChecked())

    def test_one_call_and_existing_account_usage_consent_both_required(self):
        w = self.window
        request, preview = self.prepare()
        p = w.chatgpt_panel
        with patch.object(w, 'start_job', return_value='analysis-owned') as start:
            with self.assertRaises(ValueError):
                w.run_analysis()
            w.analysis_consent.setChecked(True)
            with self.assertRaises(ValueError):
                w.run_analysis()
            p.consent.setChecked(True)
            p.included_usage_only.setChecked(True)
            original = p.max_calls.value()
            w.run_analysis()
        self.assertEqual(start.call_args.args[0], 'ui_analysis_run')
        self.assertTrue(start.call_args.args[1]['user_confirmed'])
        self.assertEqual(p.max_calls.value(), original)
        self.assertFalse(p.consent.isChecked())
        self.assertFalse(p.included_usage_only.isChecked())
        self.assertFalse(w.analysis_consent.isChecked())
        self.assertEqual(w._analysis_launch['stopped_job_id'], 'analysis-owned')
        self.assertFalse(w.chatgpt_controller.usage_known)
        w._analysis_running = False
        w._analysis_launch = None

    def test_selection_or_model_change_invalidates_one_call_consent(self):
        w = self.window
        self.prepare()
        w.analysis_consent.setChecked(True)
        w.analysis_candidates.clearSelection()
        self.assertIsNone(w._analysis_preview)
        self.assertFalse(w.analysis_consent.isChecked())
        self.prepare()
        w.analysis_consent.setChecked(True)
        w.chatgpt_panel.timeout.setValue(w.chatgpt_panel.timeout.value() + 1)
        self.assertIsNone(w._analysis_preview)
        self.assertFalse(w.analysis_consent.isChecked())

    def test_completed_or_unknown_receipt_never_enables_resubmit(self):
        w = self.window
        request, preview = self.prepare()
        preview = copy.deepcopy(preview)
        preview['receipt_snapshot']['receipts'] = [{'sequence': 1, 'status': 'reserved_unknown'}]
        w.last_operation = 'ui_analysis_preview'
        w._analysis_event({'type': 'result', 'result': preview})
        self.assertFalse(w.analysis_start.isEnabled())
        w.analysis_consent.setChecked(True)
        with patch.object(w, 'start_job') as start:
            with self.assertRaises(ValueError):
                w.run_analysis()
        start.assert_not_called()

    def test_cached_read_clears_prior_send_consent_and_does_not_require_account(self):
        w = self.window
        self.prepare()
        w.analysis_consent.setChecked(True)
        w.analysis_saved.addItem('saved', 'd' * 64)
        w.chatgpt_controller.state = 'unknown'
        with patch.object(w, 'start_job') as start:
            w.read_analysis()
        self.assertEqual(start.call_args.args, ('ui_analysis_read', {'analysis_id': 'd' * 64}))
        self.assertIsNone(w._analysis_preview)
        self.assertFalse(w.analysis_consent.isChecked())

    def test_close_joins_before_local_reconcile_without_new_auth_or_inference(self):
        from PySide6.QtGui import QCloseEvent

        w = self.window
        w._analysis_running = True
        w._analysis_launch = {'analysis_id': 'd' * 64, 'registration': REF, 'stopped_job_id': 'owned'}
        trace = []
        event = QCloseEvent()
        with (
            patch.object(self.jobs, 'close', side_effect=lambda: trace.append('join')),
            patch.object(w, '_quiesce_and_recover', side_effect=lambda: trace.append('quiesce')),
            patch.object(w, 'start_job', side_effect=lambda operation, payload: trace.append(operation)),
        ):
            w.closeEvent(event)
        self.assertEqual(trace, ['join', 'quiesce', 'ui_analysis_reconcile'])
        self.assertFalse(event.isAccepted())
        self.assertFalse(w._analysis_running)
        self.assertTrue(w._close_after_reconcile)
        w._analysis_launch = None
        w._close_after_reconcile = False
        w._closing = False

    def test_primary_login_list_collision_clears_pending_flow_without_auth_dispatch(self):
        from unittest.mock import PropertyMock

        w = self.window
        c = w.chatgpt_controller
        browsers = []
        c.browser_requested.connect(browsers.append)
        with (
            patch.object(w, '_quiesce_and_recover'),
            patch.object(w, 'poll_jobs'),
            patch.object(type(self.jobs), 'active', new_callable=PropertyMock, return_value=True),
            patch.object(w, 'start_job') as start,
        ):
            w.last_operation = 'ui_analysis_reconcile'
            w.chatgpt_panel.primary_sign_in.click()
            self.app.processEvents()
        start.assert_not_called()
        self.assertFalse(c.busy)
        self.assertFalse(c._awaiting_join)
        self.assertFalse(w.chatgpt_panel.primary_sign_in_pending)
        self.assertIsNone(w._chatgpt_job_request)
        self.assertIsNone(w._chatgpt_job_id)
        self.assertIn('本次登入未執行', w.status.text())
        w._analysis_event({'type': 'error', 'message': 'fixture reconciliation blocked'})
        self.app.processEvents()
        w.poll_jobs()
        self.assertEqual(browsers, [])

    def test_auth_waiting_on_analysis_reconcile_fails_explicitly_without_later_dispatch(self):
        w = self.window
        c = w.chatgpt_controller
        c.active_registration = REF
        c.registrations = ((REF, 'plan_ready'),)
        c.state = 'plan_ready'
        c.changed.emit()
        dispatched = []
        browsers = []
        c.request_ready.connect(dispatched.append)
        c.browser_requested.connect(browsers.append)
        w.chatgpt_panel._primary_flow = {'phase': 'list', 'request_id': c._counter + 1}
        # Controlled owner lifecycle: cancellation joined the analysis, then
        # poll_jobs launched its separate, local-only reconciliation worker.
        from unittest.mock import PropertyMock

        with (
            patch.object(w, '_quiesce_and_recover'),
            patch.object(w, 'poll_jobs'),
            patch.object(type(self.jobs), 'active', new_callable=PropertyMock, return_value=True),
            patch.object(w, '_chatgpt_dispatch') as dispatch,
        ):
            w.last_operation = 'ui_analysis_reconcile'
            request = c.request('sign_out', REF, confirmed=True)
        self.assertFalse(c.busy)
        self.assertFalse(c._awaiting_join)
        self.assertIsNone(c._request)
        self.assertIn('未執行', w.status.text())
        dispatch.assert_not_called()
        self.assertFalse(c.acknowledge_quiescence(request.request_id, joined=True))
        self.assertFalse(w.chatgpt_panel.primary_sign_in_pending)
        w._analysis_event({'type': 'error', 'message': 'fixture reconciliation remains blocked'})
        self.app.processEvents()
        w.poll_jobs()
        self.assertEqual(dispatched, [])
        self.assertEqual(browsers, [])

    def test_cancel_terminal_queues_only_local_reconcile_and_marks_usage_unknown(self):
        w = self.window
        w.last_operation = 'ui_analysis_run'
        w._analysis_running = True
        w._analysis_launch = {'analysis_id': 'a' * 64, 'registration': REF, 'stopped_job_id': 'owned'}
        w._analysis_event({'type': 'cancelled', 'message': 'fixture'})
        self.assertTrue(w._pending_analysis_reconcile)
        self.assertFalse(w._analysis_running)
        self.assertFalse(w.chatgpt_controller.account_status_known)
        with patch.object(w, 'start_job') as start:
            w.poll_jobs()
        self.assertEqual(start.call_args.args, ('ui_analysis_reconcile', w._analysis_launch))
        w._analysis_launch = None
