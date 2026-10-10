"""Generated-bar desktop routing and typed UI checks; never market evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
from quantlab.core import Dataset, ValidationError, content_hash, to_dict
from quantlab.desktop_runtime import AppPaths
from quantlab.reporting import demo_config, save_dataset
from quantlab.walk_forward import read_walk_forward_state, run_walk_forward
from tests.test_walk_forward import inputs, fake_worker, alter_prices


@unittest.skipUnless(HAS_QT, 'Pinned Qt required by desktop adapters and forms')
class WalkForwardAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'workspace', Path(self.temp.name) / 'bootstrap').ensure()
        self.data, self.plan = inputs(process_start_method='spawn')
        save_dataset(self.data, self.paths.state / 'dataset.json')

    def operation(self, name, payload, **kwargs):
        from desktop_ui import execute_ui_operation
        return execute_ui_operation('ui_walk_forward_' + name, payload, self.paths, **kwargs)

    def preview(self, plan=None):
        return self.operation('preview', {'plan': to_dict(plan or self.plan)})

    def test_preview_is_read_only_exact_bound_and_risk_labeled(self):
        from desktop_walk_forward import preview_text
        p = self.preview()
        self.assertFalse((self.paths.state / 'walk_forward').exists())
        self.assertFalse((self.paths.controls / 'holdout-registry.sqlite3').exists())
        self.assertEqual(p['folds'][0]['train']['start_time'], self.data.bars[0].timestamp.isoformat())
        self.assertEqual(p['folds'][0]['oos']['end_time'], self.data.bars[139].end.isoformat())
        self.assertEqual(len(p['candidate_pool']), 5)
        self.assertEqual(p['ranking']['max_drawdown_pct'], '0.10')
        self.assertEqual(p['ranking']['min_trades'], 1)
        self.assertEqual(p['model_calls'], 0)
        self.assertFalse(p['paper_eligible']); self.assertFalse(p['ranking_eligible'])
        text = preview_text(p)
        for token in ('最終保留集', '未評估', '取消不退還', '10%', '已平倉'):
            self.assertIn(token, text)

    def test_source_config_risk_and_engine_changes_invalidate_preview(self):
        from dataclasses import replace
        p = self.preview(); request = {'plan': to_dict(self.plan), 'preview_identity': p['preview_identity']}
        changed = alter_prices(self.data, 0, 1)
        save_dataset(changed, self.paths.state / 'dataset.json')
        with self.assertRaisesRegex(ValidationError, 'preview again'): self.operation('run', request)
        save_dataset(self.data, self.paths.state / 'dataset.json')
        for plan in (replace(self.plan, ranking={**self.plan.ranking, 'max_drawdown_pct': '0.05'}),
                     replace(self.plan, max_evaluations=32), replace(self.plan, evidence_mode='historical_replay')):
            self.assertNotEqual(p['preview_identity'], self.preview(plan)['preview_identity'])
        import desktop_walk_forward
        original = desktop_walk_forward._binding
        with patch('desktop_walk_forward._binding', side_effect=lambda *a: {**original(*a), 'source_hashes': {'fixture': 'changed'}}):
            with self.assertRaisesRegex(ValidationError, 'preview again'): self.operation('run', request)
        self.assertFalse((self.paths.state / 'walk_forward').exists())

    def relabeled(self, source_type):
        # Prices are generated. This tests route labels only, not actual market data.
        m = {**self.data.manifest, 'source_type': source_type}
        m['manifest_hash'] = content_hash({k: v for k, v in m.items() if k not in ('imported_at', 'manifest_hash')})
        return Dataset(self.data.bars, m, dict(self.data.quality))

    def test_historical_is_explicit_nonqualifying_and_no_fallback(self):
        from dataclasses import replace
        for source in ('official_local', 'proxy'):
            with self.subTest(source=source):
                save_dataset(self.relabeled(source), self.paths.state / 'dataset.json')
                with self.assertRaisesRegex(ValidationError, 'explicitly'): self.preview()
                config = replace(self.plan.backtest_config, instrument_expiries={'TAIFEX:TMF:202601': '2026-01-21'})
                plan = replace(self.plan, evidence_mode='historical_replay', backtest_config=config)
                p = self.preview(plan)
                self.assertEqual(p['exposure_status'], 'unverified')
                self.assertEqual(p['evidence_mode'], 'historical_replay')
                for flag in ('independent_oos', 'ranking_eligible', 'paper_eligible'): self.assertIs(p[flag], False)

    def test_compact_worker_result_reopen_no_retry_or_promotion(self):
        p = self.preview(); payload = {'plan': p['plan'], 'preview_identity': p['preview_identity']}
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as evaluate:
            result = self.operation('run', payload)
        self.assertEqual(evaluate.call_count, 33)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['reference'], p['preview_identity'])
        self.assertNotIn('evaluations', result); self.assertNotIn('binding', result)
        self.assertLess(len(json.dumps(result)), 100000)
        self.assertEqual(result['summary']['evaluations_reserved'], 33)
        self.assertEqual(result['summary']['final_holdout_status'], 'excluded_not_evaluated')
        self.assertEqual(result['summary']['model_calls'], 0)
        for filename in ('selection.json', 'active_candidate.json', 'paper.sqlite3', 'campaigns'):
            self.assertFalse((self.paths.state / filename).exists())
        with patch('desktop_walk_forward.run_walk_forward', side_effect=AssertionError('No rerun')):
            self.assertEqual(self.operation('run', payload), result)
            self.assertEqual(self.operation('read', {'reference': result['reference']}), result)
        from desktop_ui import candidate_record
        with self.assertRaises((ValidationError, FileNotFoundError)):
            candidate_record(self.paths.state, {'walk_forward_reference': result['reference']})
        with self.assertRaises(ValidationError): self.operation('read', {'reference': '../bad'})

    def test_historical_still_blocks_registered_ranges(self):
        from dataclasses import replace
        p = self.preview()
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            self.operation('run', {'plan': p['plan'], 'preview_identity': p['preview_identity']})
        # Same generated bars keep physical range identity while evidence labels change.
        save_dataset(self.relabeled('official_local'), self.paths.state / 'dataset.json')
        plan = replace(self.plan, evidence_mode='historical_replay',
            backtest_config=replace(self.plan.backtest_config, instrument_expiries={'TAIFEX:TMF:202601': '2026-01-21'}))
        p = self.preview(plan)
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('Consumed ranges cannot score')):
            result = self.operation('run', {'plan': p['plan'], 'preview_identity': p['preview_identity']})
        self.assertEqual(result['status'], 'blocked_previously_consumed_range')
        self.assertEqual(result['summary']['evaluations_reserved'], 0)

    def test_read_active_writer_reports_uncertain_running_state_without_recovery(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        entered, release = threading.Event(), threading.Event()
        p = self.preview(); calls = []
        def paused_worker(*args, **kwargs):
            calls.append(args[1][0].manifest['walk_forward_split']['role'])
            entered.set()
            if not release.wait(5): raise AssertionError('Test writer was not released')
            return fake_worker(*args, **kwargs)
        with patch('quantlab.walk_forward._run_bounded', side_effect=paused_worker), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.operation, 'run', {'plan': p['plan'], 'preview_identity': p['preview_identity']})
            try:
                self.assertTrue(entered.wait(5))
                reader = self.operation('read', {'reference': p['preview_identity']})
                self.assertFalse(future.done())
                self.assertEqual(reader['status'], 'running')
                self.assertEqual(reader['display_status'], 'running_or_interrupted_no_stop_proof')
                self.assertEqual(calls, ['train'])
                self.assertEqual(reader['summary']['evaluations_reserved'], 1)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=10)['status'], 'completed')
        self.assertEqual(len(calls), 33)

    def test_unknown_payloads_and_no_fabricated_stop_proof(self):
        p = self.preview()
        for bad in ({'plan': p['plan'], 'provider': {'mode': 'fixture'}},
                    {'plan': p['plan'], 'candidate': {'campaign_folder': 'a' * 64}}):
            with self.assertRaises(ValidationError): self.operation('preview', bad)
        with self.assertRaisesRegex(ValidationError, 'proof'):
            self.operation('reconcile', {'reference': p['preview_identity'], 'stopped_job_id': 'x'})

    def test_running_reopen_is_read_only_and_does_not_claim_proof(self):
        from contextlib import closing
        from quantlab.walk_forward import _save_state
        import sqlite3
        p = self.preview()
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            self.operation('run', {'plan': p['plan'], 'preview_identity': p['preview_identity']})
        folder = self.paths.state / 'walk_forward' / p['preview_identity']
        state = read_walk_forward_state(folder); state['status'] = 'running'
        with closing(sqlite3.connect(folder / 'walk_forward.sqlite3')) as db, db: _save_state(db, folder, state)
        before = (folder / 'walk_forward.sqlite3').read_bytes()
        with patch('desktop_walk_forward.run_walk_forward', side_effect=AssertionError('No retry')):
            result = self.operation('run', {'plan': p['plan'], 'preview_identity': p['preview_identity']})
        self.assertEqual(result['display_status'], 'running_or_interrupted_no_stop_proof')
        self.assertEqual(before, (folder / 'walk_forward.sqlite3').read_bytes())


@unittest.skipUnless(HAS_QT, 'Pinned Qt required by desktop adapters and forms')
class WalkForwardTypedFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_percent_round_trip_and_modes(self):
        from desktop_forms import WalkForwardForm
        form = WalkForwardForm(); self.addCleanup(form.close)
        payload = form.build_payload(to_dict(demo_config()))
        self.assertEqual(payload['evidence_mode'], 'synthetic_validation')
        self.assertEqual(payload['ranking'], {'metric': 'net_pnl', 'minimum': '0', 'min_trades': 1, 'max_drawdown_pct': '0.10'})
        form.from_payload(payload)
        self.assertEqual(form.build_payload(), payload)
        self.assertEqual(form.fields['max_drawdown_percent'].text(), '10.00')
        form.fields['mode'].setCurrentIndex(1)
        form.fields['evidence_mode'].setCurrentIndex(1)
        expanded = form.build_payload()
        self.assertEqual(expanded['evidence_mode'], 'historical_replay')
        self.assertEqual([f['train'][0] for f in expanded['folds']], [0, 0, 0])
        form.from_payload(expanded); self.assertEqual(form.build_payload(), expanded)

    def test_invalid_risk_and_step_inputs_reject(self):
        from desktop_forms import WalkForwardForm
        form = WalkForwardForm(); self.addCleanup(form.close)
        base = form.build_payload(to_dict(demo_config()))
        for key, value in (('min_trades', '0'), ('min_trades', '1.1'), ('max_drawdown_percent', '100.1'),
                           ('max_drawdown_percent', '-1'), ('max_drawdown_percent', 'NaN'),
                           ('step_bars', '119'), ('fold_count', '1')):
            form.from_payload(base); form.fields[key].setText(value)
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError): form.build_payload()
        for cap in ('0', '100', '0.001'):
            form.from_payload(base); form.fields['max_drawdown_percent'].setText(cap)
            self.assertIsNotNone(form.build_payload())

    def test_typed_costs_preserved_and_variable_steps_reject(self):
        from desktop_forms import WalkForwardForm, BacktestForm
        from dataclasses import replace
        from quantlab.walk_forward import WalkForwardFold
        costs = BacktestForm(); self.addCleanup(costs.close)
        costs.fields['commission_per_side'].setText('7.25')
        form = WalkForwardForm(); self.addCleanup(form.close)
        payload = form.build_payload(costs.build_payload()['config'])
        self.assertEqual(payload['backtest_config']['costs']['commission_per_side'], '7.25')
        _, plan = inputs()
        last = plan.folds[-1]
        changed = WalkForwardFold(tuple(x + 1 for x in last.train), tuple(x + 1 for x in last.validation), tuple(x + 1 for x in last.oos))
        plan = replace(plan, folds=(*plan.folds[:-1], changed), final_holdout=(221, 240))
        with self.assertRaisesRegex(ValidationError, '固定步進'): form.from_payload(to_dict(plan))


@unittest.skipUnless(HAS_QT, 'Pinned Qt required by desktop adapters and forms')
class WalkForwardHostTests(unittest.TestCase):
    from tests.test_desktop_ui import NativeDesktopTests as _Support
    setUpClass = _Support.__dict__['setUpClass']
    setUp = _Support.setUp
    cleanup_window = _Support.cleanup_window

    def seed(self):
        from desktop_ui import execute_ui_operation
        execute_ui_operation('ui_demo', {'bars': 240}, self.paths)
        self.window.refresh_views()
        return self.window

    def prepared(self):
        w = self.seed()
        with patch.object(w.jobs, 'start', return_value='preview-job'):
            w.preview_walk_forward()
        from desktop_ui import execute_ui_operation
        result = execute_ui_operation('ui_walk_forward_preview', {'plan': w._walk_forward_input_key()[1]}, self.paths)
        w._walk_forward_event({'type': 'result', 'job_id': 'preview-job', 'result': result})
        return w, result

    def test_preview_has_no_side_effect_and_risk_or_cost_changes_clear_consent(self):
        w, result = self.prepared()
        self.assertIsNotNone(w._wf_preview)
        self.assertNotIn(result['source_identity'], w.walk_forward_preview.toPlainText())
        self.assertIn(result['source_identity'], w.walk_forward_advanced.toPlainText())
        for key, value in (('max_drawdown_percent', '9'), ('min_trades', '2')):
            w.walk_forward_consent.setChecked(True)
            w.walk_forward_form.fields[key].setText(value)
            self.assertIsNone(w._wf_preview); self.assertFalse(w.walk_forward_consent.isChecked())
        w._wf_preview = result; w.walk_forward_consent.setChecked(True)
        w.backtest_form.fields['commission_per_side'].setText('9')
        self.assertIsNone(w._wf_preview); self.assertFalse(w.walk_forward_consent.isChecked())
        self.assertFalse((self.paths.controls / 'holdout-registry.sqlite3').exists())

    def test_stale_preview_response_and_source_replace_cannot_enable_start(self):
        w = self.seed()
        with patch.object(w.jobs, 'start', return_value='old-preview'):
            w.preview_walk_forward()
        from desktop_ui import execute_ui_operation
        result = execute_ui_operation('ui_walk_forward_preview', {'plan': w._walk_forward_input_key()[1]}, self.paths)
        w.walk_forward_form.fields['minimum'].setText('123')
        w._walk_forward_event({'type': 'result', 'job_id': 'old-preview', 'result': result})
        self.assertIsNone(w._wf_preview)
        w._wf_preview = result; w.walk_forward_consent.setChecked(True)
        execute_ui_operation('ui_demo', {'bars': 320}, self.paths)
        with patch.object(w, 'start_job') as start:
            with self.assertRaisesRegex(ValidationError, '重新預覽'): w.run_walk_forward()
        start.assert_not_called()

    def test_explicit_replay_selection_preserved_without_automatic_fallback(self):
        w = self.seed()
        self.assertEqual(w.walk_forward_form.fields['evidence_mode'].currentData(), 'synthetic_validation')
        w.walk_forward_form.fields['evidence_mode'].setCurrentIndex(1)
        with patch.object(w.jobs, 'start', return_value='historical-preview') as start:
            w.preview_walk_forward()
        self.assertEqual(start.call_args.args[1]['plan']['evidence_mode'], 'historical_replay')
        w._walk_forward_event({'type': 'error', 'message': 'fixture rejection'})
        self.assertEqual(w.walk_forward_form.fields['evidence_mode'].currentData(), 'historical_replay')
        self.assertIsNone(w._wf_preview)

    def test_no_start_without_explicit_once_only_consent(self):
        w, _ = self.prepared()
        with patch.object(w, 'start_job') as start:
            with self.assertRaisesRegex(ValidationError, '明確確認'): w.run_walk_forward()
        start.assert_not_called()
        w.walk_forward_consent.setChecked(True)
        with patch.object(w.jobs, 'start', return_value='run-job') as start:
            w.run_walk_forward()
        self.assertEqual(start.call_args.args[0], 'ui_walk_forward_run')
        self.assertFalse(w.walk_forward_consent.isChecked())
        self.assertEqual(w._wf_launch['stopped_job_id'], 'run-job')
        w._wf_launch = None  # Fake job has no process proof and must not reconcile at teardown.

    def test_stale_old_job_result_never_changes_newer_view(self):
        w = self.seed(); w._ui_job_id = 'new-job'; w.last_operation = 'ui_walk_forward_preview'
        w.walk_forward_status.setText('Current view')
        with patch.object(w.jobs, 'poll', return_value=[{'job_id': 'old-job', 'type': 'result', 'result': {}}]):
            w.poll_jobs()
        self.assertEqual(w.walk_forward_status.text(), 'Current view')
        self.assertIsNone(w._wf_preview)

    def test_cancel_event_only_schedules_exact_launch_reconciliation(self):
        w = self.seed(); w.last_operation = 'ui_walk_forward_run'; w._ui_job_id = 'run-job'
        launch = {'reference': 'a' * 64, 'stopped_job_id': 'run-job'}; w._wf_launch = launch
        with patch.object(w.jobs, 'poll', return_value=[{'job_id': 'run-job', 'type': 'cancelled'}]), \
             patch.object(w.jobs, 'start', return_value='reconcile-job') as start:
            w.poll_jobs()
        self.assertEqual(start.call_args.args, ('ui_walk_forward_reconcile', launch))
        self.assertFalse(w._wf_pending_reconcile)
        w._wf_launch = None

    def test_existing_journal_routes_to_read_without_new_evaluation(self):
        w, p = self.prepared(); reference = p['preview_identity']
        folder = self.paths.state / 'walk_forward' / reference; folder.mkdir(parents=True)
        (folder / 'walk_forward.sqlite3').touch()
        w.walk_forward_consent.setChecked(True)
        with patch.object(w.jobs, 'start', return_value='read-job') as start:
            w.run_walk_forward()
        self.assertEqual(start.call_args.args, ('ui_walk_forward_read', {'reference': reference}))
        self.assertIsNone(w._wf_launch)

    def test_completed_results_are_separate_from_ai_and_paper_views(self):
        w = self.seed(); data, plan = inputs()
        save_dataset(data, self.paths.state / 'dataset.json')
        from desktop_ui import execute_ui_operation
        p = execute_ui_operation('ui_walk_forward_preview', {'plan': to_dict(plan)}, self.paths)
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            result = execute_ui_operation('ui_walk_forward_run', {'plan': p['plan'], 'preview_identity': p['preview_identity']}, self.paths)
        old_history = w.history.toPlainText(); old_candidate = w.active_candidate
        w.last_operation = 'ui_walk_forward_run'
        w._walk_forward_event({'type': 'result', 'result': result})
        self.assertEqual(w.history.toPlainText(), old_history); self.assertEqual(w.active_candidate, old_candidate)
        self.assertIn('無紙上資格', w.walk_forward_status.text())
        self.assertEqual(w.walk_forward_results.rowCount(), 15)
        self.assertFalse((self.paths.state / 'selection.json').exists())


class WalkForwardStaticTests(unittest.TestCase):
    def test_adapter_is_scanned_and_core_source_is_packaged(self):
        root = Path(__file__).resolve().parents[1]
        from tools.quality_gate import python_findings, secret_findings
        for name in ('desktop_forms.py', 'desktop_ui.py', 'desktop_walk_forward.py'):
            source = (root / name).read_text(encoding='utf-8')
            self.assertEqual(python_findings(source, name, desktop=True), [])
            self.assertEqual(secret_findings(source, name), [])
        self.assertIn('"desktop_walk_forward.py"', (root / 'tools/quality_gate.py').read_text(encoding='utf-8'))
        self.assertIn("(str(root / 'quantlab' / 'walk_forward.py'), 'quantlab')", (root / 'packaging/markauto.spec').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
