"""Generated-fixture saved-pool desktop boundaries, no model/network/market data."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
from quantlab.core import ValidationError, to_dict
from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError, validate_walk_forward_request
from quantlab.reporting import demo_config, save_dataset
from tests.test_walk_forward import inputs


def pending_saved_plan():
    _, plan = inputs(process_start_method='spawn')
    payload = to_dict(plan)
    payload.pop('candidate_pool'); payload.pop('pool_admission', None)
    payload.update(pool_origin='saved_campaign_pool')
    return payload


def local_source(path):
    return {'campaign_reference': 'a' * 64,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(path)}}


class SavedPoolDesktopGrammarTests(unittest.TestCase):
    def test_pending_request_has_no_dsl_and_budget_is_never_replaced(self):
        payload = pending_saved_plan(); payload['max_evaluations'] = 620
        before = copy.deepcopy(payload)
        source = local_source(Path('/tmp') / 'explicit-original.json')
        chronology = validate_walk_forward_request(payload, source)
        self.assertEqual(payload, before)
        self.assertEqual(chronology.max_runtime_seconds, payload['max_runtime_seconds'])
        for key, value in (('candidate_pool', []), ('pool_admission', {})):
            with self.assertRaises(ValidationError): validate_walk_forward_request({**payload, key: value}, source)
        for budget in (True, 0, 621, '33', 1.5):
            with self.assertRaises(ValidationError): validate_walk_forward_request({**payload, 'max_evaluations': budget}, source)

    def test_explicit_local_reference_rejects_provider_paths_and_mixed_pools(self):
        payload = pending_saved_plan()
        source = local_source(Path('/tmp') / 'explicit-original.json')
        for path in ('https://provider.example/data.json', 'file:///tmp/data.json', '../data.json',
                     '//remote/share/data.json', '/tmp/../other.json', '/tmp/bad\x00.json'):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                validate_walk_forward_request(payload, local_source(path))
        for bad in (None, {'campaign_reference': '../x', 'original_dataset': source['original_dataset']},
                    {**source, 'source_manifest': {}}, {**source, 'original_dataset': {'path': '/tmp/x'}}):
            with self.assertRaises(ValidationError): validate_walk_forward_request(payload, bad)
        _, builtin = inputs()
        with self.assertRaises(ValidationError): validate_walk_forward_request(to_dict(builtin), source)

    def test_runtime_rejects_mixed_or_forged_requests_before_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary) / 'app').ensure(); manager = JobManager(paths)
            _, builtin = inputs(); saved = pending_saved_plan(); source = local_source(Path(temporary) / 'original.json')
            invalid = [
                {'plan': to_dict(builtin), 'saved_source': source},
                {'plan': to_dict(builtin), 'saved_source': None},
                {'plan': saved},
                {'plan': {**saved, 'candidate_pool': to_dict(builtin)['candidate_pool']}, 'saved_source': source},
                {'plan': saved, 'saved_source': source, 'provider': {'mode': 'fixture'}},
            ]
            with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
                for payload in invalid:
                    with self.assertRaises(RuntimeSafetyError): manager.start('ui_walk_forward_preview', payload)
            spawn.assert_not_called()
            self.assertFalse((paths.state / 'walk_forward').exists())


@unittest.skipUnless(HAS_QT, 'Pinned Qt required')
class SavedPoolAdapterTests(unittest.TestCase):
    def setUp(self):
        from tests.saved_pool_fixtures import make_saved_source
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace', Path(self.tmp.name) / 'bootstrap').ensure()
        self.data, _ = inputs(process_start_method='spawn')
        save_dataset(self.data, self.paths.state / 'dataset.json')
        self.registry = self.paths.controls / 'holdout-registry.sqlite3'
        self.folder, reference, self.original, self.state = make_saved_source(self.paths.state / 'campaigns', registry_path=self.registry)
        self.registry_before = self.registry.read_bytes()
        self.original_path = Path(self.tmp.name) / 'user-selected-original.json'
        save_dataset(self.original, self.original_path)
        self.source = {'campaign_reference': reference,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(self.original_path)}}
        self.plan = pending_saved_plan(); self.plan['max_evaluations'] = 93
        self.payload = {'plan': self.plan, 'saved_source': self.source}

    def operation(self, name, payload=None):
        from desktop_ui import execute_ui_operation
        return execute_ui_operation('ui_walk_forward_' + name, payload or self.payload, self.paths)

    def test_every_candidate_and_attempt_preserved_without_scores_or_model_calls(self):
        from desktop_walk_forward import preview_text, result_rows
        from quantlab.core import canonical_json
        from tests.test_walk_forward import fake_worker
        before = {name: (self.folder / name).read_bytes() for name in ('campaign.json', 'campaign.sqlite3')}
        original_bytes = self.original_path.read_bytes()
        with patch('quantlab.research.FixtureGenerator.generate', side_effect=AssertionError('No generation')), \
             patch('quantlab.research.CompatibleProvider.generate', side_effect=AssertionError('No model call')):
            preview = self.operation('preview')
            self.assertEqual(preview['candidate_count'], 15)
            self.assertEqual(preview['planned_evaluations_upper_bound'], 93)
            self.assertEqual(preview['pool_admission']['real_model_status'], self.state['real_model_status'])
            self.assertEqual([a['sequence'] for a in preview['pool_admission']['attempts']], list(range(1, 16)))
            self.assertEqual([s['strategy_id'] for s in preview['candidate_pool']], [a['spec']['strategy_id'] for a in self.state['attempts']])
            self.assertNotIn('987654321', canonical_json(preview))
            self.assertNotIn('metrics', canonical_json(preview['pool_admission']))
            self.assertIn('來源舊分數不參與', preview_text(preview))
            self.assertIn('固定示範產生器', preview_text(preview))
            self.assertIn('來源模型狀態：尚未驗證', preview_text(preview))
            for raw in ('not_verified', 'synthetic_validation', 'evaluated_validated_candidate', 'generated_source_'):
                self.assertNotIn(raw, preview_text(preview))
                self.assertIn(raw, preview_text(preview, advanced=True))
            self.assertEqual(self.registry.read_bytes(), self.registry_before)
            with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as evaluation:
                result = self.operation('run', {**self.payload, 'preview_identity': preview['preview_identity']})
            self.assertEqual(result['status'], 'completed'); self.assertEqual(evaluation.call_count, 93)
            self.assertEqual(result['pool_admission'], preview['pool_admission'])
            self.assertEqual(result['summary']['model_calls'], 0)
            self.assertFalse(result['summary']['ranking_eligible']); self.assertFalse(result['summary']['paper_eligible'])
            displayed = result_rows(result)
            for row in displayed:
                self.assertEqual(row['狀態'], '已評估')
                self.assertEqual(row['訓練狀態'], '已評估')
                self.assertNotIn('net_pnl', str(row)); self.assertNotIn('generated_source_', str(row))
            self.assertIn('前推 淨損益 TWD', displayed[0])
            self.assertIn('completed', preview_text(result, advanced=True))
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['folds'][0]['candidates'][0]['train']['status'], 'evaluated')
            with patch('desktop_walk_forward.run_walk_forward', side_effect=AssertionError('No rerun')):
                self.assertEqual(self.operation('read', {'reference': result['reference']}), result)
                self.assertEqual(self.operation('run', {**self.payload, 'preview_identity': preview['preview_identity']}), result)
        self.assertEqual(self.original_path.read_bytes(), original_bytes)
        for name, content in before.items(): self.assertEqual((self.folder / name).read_bytes(), content)

    def test_explicit_budget_over_exact_bound_is_nonlaunchable_and_not_clamped(self):
        from desktop_walk_forward import preview_text
        self.plan['max_evaluations'] = 620
        preview = self.operation('preview')
        self.assertEqual(preview['admission_status'], 'rejected')
        self.assertEqual(preview['reason_code'], 'evaluation_budget_exceeds_pool_bound')
        self.assertEqual(preview['evaluation_limit'], 620)
        self.assertEqual(preview['planned_evaluations_upper_bound'], 93)
        self.assertNotIn('preview_identity', preview)
        self.assertIn('1–93', preview_text(preview)); self.assertEqual(self.plan['max_evaluations'], 620)
        with patch('quantlab.walk_forward._reserve_holdout') as reserve, self.assertRaises(ValidationError):
            self.operation('run', {**self.payload, 'preview_identity': 'a' * 64})
        reserve.assert_not_called()
        self.assertFalse((self.paths.state / 'walk_forward').exists())

    def test_changed_journal_or_original_dataset_invalidates_before_reservation(self):
        from tests.saved_pool_fixtures import write_source
        from tests.test_walk_forward import alter_prices
        preview = self.operation('preview')
        self.state['warnings'].append('Changed generated fixture review text')
        write_source(self.folder, self.state)
        with patch('quantlab.walk_forward._reserve_holdout') as reserve, self.assertRaisesRegex(ValidationError, 'preview again'):
            self.operation('run', {**self.payload, 'preview_identity': preview['preview_identity']})
        reserve.assert_not_called()
        save_dataset(alter_prices(self.original, 0, 1), self.original_path)
        changed = self.operation('preview')
        self.assertEqual(changed['admission_status'], 'rejected')
        self.assertEqual(changed['reason_code'], 'source_dataset_mismatch')
        self.assertEqual(self.registry.read_bytes(), self.registry_before)
        self.assertFalse((self.paths.state / 'walk_forward').exists())

    def test_relocated_workspace_cannot_silently_switch_to_fresh_registry(self):
        from desktop_ui import execute_ui_operation
        from desktop_walk_forward import preview_text
        other = AppPaths(self.paths.root, Path(self.tmp.name) / 'different-bootstrap').ensure()
        preview = execute_ui_operation('ui_walk_forward_preview', self.payload, other)
        self.assertEqual(preview['admission_status'], 'rejected')
        self.assertEqual(preview['reason_code'], 'source_registry_mismatch')
        self.assertIn('共用登錄', preview_text(preview))
        self.assertFalse((other.controls / 'holdout-registry.sqlite3').exists())
        self.assertEqual(self.registry.read_bytes(), self.registry_before)
        self.assertFalse((other.state / 'walk_forward').exists())

    def test_deleted_original_registry_is_not_recreated_at_preview_or_launch(self):
        preview = self.operation('preview')
        self.registry.unlink()
        rejected = self.operation('preview')
        self.assertEqual(rejected['admission_status'], 'rejected')
        self.assertEqual(rejected['reason_code'], 'source_registry_mismatch')
        with patch('quantlab.walk_forward._reserve_holdout') as reserve, self.assertRaises(ValidationError):
            self.operation('run', {**self.payload, 'preview_identity': preview['preview_identity']})
        reserve.assert_not_called(); self.assertFalse(self.registry.exists())
        self.assertFalse((self.paths.state / 'walk_forward').exists())

    def test_missing_selected_original_has_explicit_reason_without_path_fallback(self):
        from desktop_walk_forward import preview_text
        self.original_path.unlink()
        preview = self.operation('preview')
        self.assertEqual(preview['admission_status'], 'rejected')
        self.assertEqual(preview['reason_code'], 'source_missing_evidence')
        self.assertIn('來源', preview_text(preview)); self.assertNotIn(str(self.original_path), preview_text(preview))
        self.assertFalse((self.paths.state / 'walk_forward').exists())

    def test_source_rejected_attempt_is_visible_and_never_silently_replaced(self):
        from tests.saved_pool_fixtures import write_source
        from desktop_walk_forward import preview_text
        attempt = self.state['attempts'][-1]
        attempt.update(status='rejected', output=None, output_hash=None, strategy_hash=None, metrics={}, warnings=['ValidationError'])
        attempt.pop('spec')
        write_source(self.folder, self.state)
        self.plan['max_evaluations'] = 87
        preview = self.operation('preview')
        self.assertEqual(preview['candidate_count'], 14)
        attempts = preview['pool_admission']['attempts']
        self.assertEqual(len(attempts), 15); self.assertFalse(attempts[-1]['admitted'])
        self.assertEqual(attempts[-1]['reason'], 'excluded_source_attempt_rejected')
        self.assertIn('第 15 次', preview_text(preview)); self.assertIn('未通過結構驗證', preview_text(preview))

    def test_same_cosmetic_name_preserves_distinct_candidates_and_exact_oos_attribution(self):
        from desktop_walk_forward import result_rows
        from quantlab.core import content_hash
        from quantlab.__main__ import config_from_json
        from quantlab.research import _campaign_config, validate_dsl
        from tests.saved_pool_fixtures import source_summary, write_source
        from tests.test_walk_forward import fake_worker
        first, second = self.state['attempts'][0], self.state['attempts'][5]
        second['output']['strategy_id'] = first['spec']['strategy_id']
        second['spec'] = copy.deepcopy(second['output'])
        second['output_hash'] = content_hash(second['output'])
        second['strategy_hash'] = content_hash(second['spec'])
        config = copy.deepcopy(self.state['binding']['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        splits = _campaign_config(self.original, config)
        for role in ('train', 'validation'):
            second['metrics'][role] = source_summary(splits[role], validate_dsl(second['spec']), config['backtest_config'])
        self.state['attempts'][10]['generator_context']['previous']['output'] = copy.deepcopy(second['output'])
        write_source(self.folder, self.state)
        preview = self.operation('preview')
        self.assertEqual(preview['candidate_count'], 15)
        self.assertEqual(preview['candidate_pool'][0]['strategy_id'], preview['candidate_pool'][5]['strategy_id'])
        self.assertNotEqual(preview['candidate_pool'][0]['parameters'], preview['candidate_pool'][5]['parameters'])
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
            result = self.operation('run', {**self.payload, 'preview_identity': preview['preview_identity']})
        first_fold = result['folds'][0]
        self.assertEqual(first_fold['winner_pool_index'], 0)
        self.assertNotEqual(first_fold['candidates'][0]['strategy_hash'], first_fold['candidates'][5]['strategy_hash'])
        rows = [row for row in result_rows(result) if row['折次'] == 1]
        chosen = [row for row in rows if row.get('前推狀態') == '已評估']
        self.assertEqual(len(chosen), 1); self.assertEqual(chosen[0]['候選序號'], 1)
        self.assertEqual(rows[5]['候選序號'], 6); self.assertNotIn('前推狀態', rows[5])
        self.assertIn('第 1 個', rows[5]['贏家'])
        self.assertEqual(rows[0]['候選'], rows[5]['候選'])

    def test_known_duplicate_trials_and_provider_failures_have_specific_plain_labels(self):
        from desktop_walk_forward import preview_text
        preview = self.operation('preview')
        # Renderer-only generated view: the core independently verifies these
        # reason codes, snapshot hashes, and exclusion semantics before display.
        preview['candidate_pool'] = preview['candidate_pool'][:5]
        preview['candidate_count'] = 5
        for attempt in preview['pool_admission']['attempts'][5:]:
            attempt.update(admitted=False, source_status='rejected', reason='source_duplicate_rejected')
        text = preview_text(preview)
        self.assertEqual(text.count('保留已用嘗試，不納入'), 10)
        self.assertIn('第 15 次', text)
        for code, words in (('source_manual_exchange_missing', '交換套件'),
                            ('source_provider_receipt_invalid', '請求或回應憑證'),
                            ('source_provider_provenance_invalid', '相依元件'),
                            ('source_provider_decimal_context_unsupported', '小數計算環境'),
                            ('source_provider_unsupported', '紀錄格式'),
                            ('source_registry_mismatch', '共用登錄')):
            rejection = {'admission_status': 'rejected', 'reason_code': code, 'model_calls': 0}
            normal = preview_text(rejection)
            self.assertIn(words, normal); self.assertNotIn(code, normal)
            self.assertIn(code, preview_text(rejection, advanced=True))

    def test_duplicate_rejection_is_plain_and_does_not_repeat_untrusted_text(self):
        from desktop_walk_forward import preview_text
        from quantlab.saved_candidate_pool import SavedCandidatePoolError
        with patch('quantlab.saved_candidate_pool.admit_saved_campaign_pool', side_effect=SavedCandidatePoolError('untrusted body', 'source_duplicate_structure')):
            preview = self.operation('preview')
        self.assertEqual(preview['reason_code'], 'source_duplicate_structure')
        self.assertIn('重複策略結構', preview_text(preview))
        self.assertNotIn('untrusted body', str(preview))
        self.assertEqual(self.registry.read_bytes(), self.registry_before)


@unittest.skipUnless(HAS_QT, 'Pinned Qt required')
class SavedPoolTypedFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_exclusive_origin_and_explicit_budget_without_auto_increase(self):
        from desktop_forms import WalkForwardForm
        form = WalkForwardForm(); self.addCleanup(form.close)
        self.assertEqual(form.fields['minimum'].text(), '0')
        for key in ('mode', 'evidence_mode', 'pool_origin'):
            field = form.fields[key]
            for index in range(field.count()):
                self.assertNotIn(str(field.itemData(index)), field.itemText(index))
        self.assertEqual(form.fields['pool_origin'].currentData(), 'exact_builtin_pool')
        self.assertEqual(form.fields['max_evaluations'].text(), '33')
        form.fields['max_evaluations'].setText('221')
        with self.assertRaises(ValidationError): form.build_payload(to_dict(demo_config()))
        form.fields['pool_origin'].setCurrentIndex(1)
        self.assertEqual(form.fields['max_evaluations'].text(), '221')
        self.assertIn('620', form.fields['max_evaluations'].accessibleName())
        form.defaults_for_bars(960)
        self.assertEqual(form.fields['max_evaluations'].text(), '221')
        payload = form.build_payload(to_dict(demo_config()))
        self.assertEqual(payload['max_evaluations'], 221)
        self.assertNotIn('candidate_pool', payload); self.assertNotIn('pool_admission', payload)
        form.fields['pool_origin'].setCurrentIndex(0)
        self.assertEqual(form.fields['max_evaluations'].text(), '221')
        with self.assertRaises(ValidationError): form.build_payload(to_dict(demo_config()))


@unittest.skipUnless(HAS_QT, 'Pinned Qt required')
class SavedPoolHostTests(unittest.TestCase):
    from tests.test_desktop_ui import NativeDesktopTests as _Support
    setUpClass = _Support.__dict__['setUpClass']
    setUp = _Support.setUp
    cleanup_window = _Support.cleanup_window

    def prepare_source(self):
        data, plan = inputs(process_start_method='spawn')
        save_dataset(data, self.paths.state / 'dataset.json')
        source = Path(self.tmp.name) / 'explicit-original.json'
        save_dataset(data, source)
        folder = self.paths.state / 'campaigns' / ('a' * 64); folder.mkdir(parents=True)
        (folder / 'campaign.json').write_text('{}', encoding='utf-8')
        (folder / 'campaign.sqlite3').touch()
        self.window._refresh_walk_forward_references()
        self.window.walk_forward_form.from_payload(to_dict(plan))
        return self.window, source

    def test_source_picker_is_explicit_read_only_and_cancel_preserves_choice(self):
        w, source = self.prepare_source()
        self.assertTrue(w.walk_forward_original.isReadOnly())
        self.assertIsNone(w.walk_forward_campaign.currentData())
        self.assertFalse(w.walk_forward_saved_controls.isEnabled())
        before = (self.paths.state / 'dataset.json').read_bytes()
        w.walk_forward_form.fields['pool_origin'].setCurrentIndex(1)
        self.assertTrue(w.walk_forward_saved_controls.isEnabled())
        with self.assertRaises(ValidationError): w._walk_forward_input_key()
        w.walk_forward_campaign.setCurrentIndex(1)
        with self.assertRaises(ValidationError): w._walk_forward_input_key()
        with patch('desktop_ui.QFileDialog.getOpenFileName', return_value=(str(source), '')):
            w.pick_walk_forward_original()
        self.assertEqual(w.walk_forward_original.text(), str(source.resolve()))
        with patch('desktop_ui.QFileDialog.getOpenFileName', return_value=('', '')):
            w.pick_walk_forward_original()
        self.assertEqual(w.walk_forward_original.text(), str(source.resolve()))
        self.assertEqual((self.paths.state / 'dataset.json').read_bytes(), before)
        with patch.object(w.jobs, 'start', return_value='preview-job') as start:
            w.preview_walk_forward()
        payload = start.call_args.args[1]
        self.assertEqual(payload['saved_source'], local_source(source))
        self.assertNotIn('candidate_pool', payload['plan']); self.assertNotIn('pool_admission', payload['plan'])
        w._wf_preview = {'preview_identity': 'b' * 64}; w.walk_forward_consent.setChecked(True)
        w.walk_forward_form.fields['pool_origin'].setCurrentIndex(0)
        self.assertIsNone(w._wf_preview); self.assertFalse(w.walk_forward_consent.isChecked())
        self.assertIsNone(w._walk_forward_saved_source())

    def test_changed_saved_file_discards_async_preview(self):
        w, source = self.prepare_source()
        w.walk_forward_form.fields['pool_origin'].setCurrentIndex(1)
        w.walk_forward_campaign.setCurrentIndex(1); w.walk_forward_original.setText(str(source))
        with patch.object(w.jobs, 'start', return_value='preview-job'): w.preview_walk_forward()
        source.write_text('{}', encoding='utf-8')
        w._walk_forward_event({'type': 'result', 'result': {'not': 'used'}})
        self.assertIsNone(w._wf_preview); self.assertFalse(w.walk_forward_consent.isChecked())
        self.assertIn('預覽已失效', w.walk_forward_status.text())

    def test_preview_local_status_and_rows_follow_pending_ready_rejected_and_stale(self):
        from desktop_ui import execute_ui_operation
        w, _ = self.prepare_source()
        w.walk_forward_results.set_rows([{'先前結果': '只屬於先前計畫'}])
        self.assertEqual(w.walk_forward_results.rowCount(), 1)
        with patch.object(w.jobs, 'start', return_value='preview-job'): w.preview_walk_forward()
        self.assertEqual(w.walk_forward_results.rowCount(), 0)
        self.assertIn('預覽核對中', w.walk_forward_status.text())
        self.assertFalse(w.walk_forward_start.isEnabled())
        preview = execute_ui_operation('ui_walk_forward_preview', {'plan': w._walk_forward_input_key()[1]}, self.paths)
        w._walk_forward_event({'type': 'result', 'result': preview})
        self.assertIn('預覽已就緒', w.walk_forward_status.text())
        self.assertNotIn('尚未預覽', w.walk_forward_status.text())
        self.assertIs(w._wf_preview, preview)
        self.assertFalse(w.walk_forward_consent.isChecked())
        w.walk_forward_form.fields['minimum'].setText('0')
        self.assertIn('預覽已失效', w.walk_forward_status.text())
        self.assertIsNone(w._wf_preview)
        self.assertFalse(w.walk_forward_start.isEnabled())
        with patch.object(w.jobs, 'start', return_value='preview-job'): w.preview_walk_forward()
        rejected = {'admission_status': 'rejected', 'reason_code': 'source_registry_mismatch'}
        w._walk_forward_event({'type': 'result', 'result': rejected})
        self.assertIn('預覽未通過', w.walk_forward_status.text())
        self.assertIsNone(w._wf_preview)
        self.assertFalse(w.walk_forward_start.isEnabled())
        self.assertFalse(w.walk_forward_consent.isChecked())
        with patch.object(w.jobs, 'start', return_value='preview-job'): w.preview_walk_forward()
        w._walk_forward_event({'type': 'cancelled'})
        self.assertIn('預覽未完成', w.walk_forward_status.text())
        self.assertEqual(w.walk_forward_results.rowCount(), 0)

    def test_normal_result_status_is_chinese_and_exact_values_remain_advanced(self):
        w, _ = self.prepare_source()
        result = {'reference': 'b' * 64, 'status': 'completed', 'display_status': 'completed',
            'source_identity': 'c' * 64, 'folds': [], 'pool_admission': {'real_model_status': 'not_verified'},
            'summary': {'evidence_mode': 'synthetic_validation', 'exposure_status': 'synthetic_not_market_evidence',
                'evaluations_reserved': 33, 'evaluation_limit': 33, 'evaluated_oos_folds': 3}}
        w.last_operation = 'ui_walk_forward_read'
        w._walk_forward_event({'type': 'result', 'result': result})
        normal = w.walk_forward_status.text(); advanced = w.walk_forward_advanced.toPlainText()
        for raw in ('completed', 'synthetic_validation', 'synthetic_not_market_evidence', 'not_verified', 'b' * 64, 'c' * 64):
            self.assertNotIn(raw, normal); self.assertIn(raw, advanced)
        for label in ('已完成', '僅合成驗證', '合成資料，非市場證據', '來源模型狀態：尚未驗證', '識別碼：' + 'b' * 12):
            self.assertIn(label, normal)
        self.assertEqual(result['pool_admission']['real_model_status'], 'not_verified')

    def test_default_preview_hides_internal_binding_until_advanced_opened(self):
        from desktop_ui import execute_ui_operation
        w, _ = self.prepare_source()
        with patch.object(w.jobs, 'start', return_value='preview-job'): w.preview_walk_forward()
        preview = execute_ui_operation('ui_walk_forward_preview', {'plan': w._walk_forward_input_key()[1]}, self.paths)
        w._walk_forward_event({'type': 'result', 'result': preview})
        normal, advanced = w.walk_forward_preview.toPlainText(), w.walk_forward_advanced.toPlainText()
        self.assertFalse(w.walk_forward_advanced_group.isChecked())
        self.assertTrue(w.walk_forward_advanced.isHidden())
        for text in (preview['source_identity'], preview['preview_identity'], preview['registry_identity']['resolved_path']):
            self.assertNotIn(text, normal); self.assertIn(text, advanced)
        self.assertNotIn('source_hashes', normal)
        self.assertNotIn('滑價點數', normal)
        self.assertIn('slippage_ticks', advanced)
        for text in ('[0, 60)', '取消不退還', '3 折 ×（2 × 5', '最大回撤', '單邊手續費', '滑價跳數'):
            self.assertIn(text, normal)
        w.walk_forward_advanced_group.setChecked(True)
        self.assertFalse(w.walk_forward_advanced.isHidden())


@unittest.skipUnless(HAS_QT, 'Pinned Qt required')
class SavedPoolSpawnSmokeTests(unittest.TestCase):
    from tests.test_desktop_walk_forward_runtime import WalkForwardSpawnSmokeTests as _Support
    finish = _Support.finish

    def test_typed_saved_request_survives_spawn_preview_run_and_read(self):
        from tests.saved_pool_fixtures import make_saved_source
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(root / 'app').ensure(); self.manager = JobManager(paths)
            self.addCleanup(self.manager.close)
            data, _ = inputs(process_start_method='spawn')
            save_dataset(data, paths.state / 'dataset.json')
            _, reference, original, _ = make_saved_source(paths.state / 'campaigns', candidates=1, registry_path=paths.controls / 'holdout-registry.sqlite3')
            original_path = root / 'chosen-original.json'; save_dataset(original, original_path)
            source = local_source(original_path); source['campaign_reference'] = reference
            plan = pending_saved_plan(); plan.update(max_evaluations=9, max_runtime_seconds=60)
            payload = {'plan': plan, 'saved_source': source}
            self.manager.start('ui_walk_forward_preview', payload)
            preview = self.finish()
            self.assertEqual(preview['candidate_count'], 1)
            self.assertEqual(preview['evaluation_limit'], 9)
            self.assertEqual(preview['model_calls'], 0)
            self.assertFalse((paths.state / 'walk_forward').exists())
            self.manager.start('ui_walk_forward_run', {**payload, 'preview_identity': preview['preview_identity']})
            result = self.finish()
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['pool_origin'], 'saved_campaign_pool')
            self.assertEqual(result['summary']['model_calls'], 0)
            self.manager.start('ui_walk_forward_read', {'reference': result['reference']})
            self.assertEqual(self.finish(), result)


class SavedPoolDesktopStaticTests(unittest.TestCase):
    def test_legacy_compact_report_defaults_missing_pool_fields(self):
        from desktop_walk_forward import compact_walk_forward, result_rows
        from quantlab.walk_forward import run_walk_forward
        from tests.test_walk_forward import fake_worker
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data, plan = inputs()
            with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
                state = run_walk_forward(data, plan=plan, output_dir=root / 'run', holdout_registry_path=root / 'registry.sqlite3')
            state['binding']['plan'].pop('pool_origin'); state['binding']['plan'].pop('pool_admission')
            compact = compact_walk_forward(state, state['experiment_id'])
            self.assertEqual(compact['pool_origin'], 'exact_builtin_pool')
            self.assertIsNone(compact['pool_admission'])
            self.assertEqual(len(result_rows(compact)), 15)

    def test_packaging_includes_admission_source_and_scans_unchanged_criteria(self):
        root = Path(__file__).resolve().parents[1]
        from tools.quality_gate import python_findings, secret_findings
        for name in ('desktop_forms.py', 'desktop_ui.py', 'desktop_walk_forward.py', 'quantlab/desktop_runtime.py'):
            source = (root / name).read_text(encoding='utf-8')
            self.assertEqual(python_findings(source, name, research=name.startswith('quantlab/'), desktop=not name.startswith('quantlab/')), [])
            self.assertEqual(secret_findings(source, name), [])
        self.assertIn("(str(root / 'quantlab' / 'saved_candidate_pool.py'), 'quantlab')", (root / 'packaging/markauto.spec').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
