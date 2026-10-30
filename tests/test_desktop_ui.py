"""Native widget and real isolated-worker integration tests; run QT_QPA_PLATFORM=offscreen."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from desktop_app.strings.catalog import ui_text
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'Install pinned desktop requirements to test Qt widgets')
class NativeDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
        from quantlab.research_core.adapters.workspace_backup import BackupManager
        from desktop_app.shell.window import MainWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(
            self.paths,
            self.jobs,
            SettingsStore(self.paths.state / 'settings.json'),
            BackupManager(self.paths, self.jobs),
            services=_c_create_ui_services(_c_create_operation_ports()),
        )
        self.assertEqual(self.window.provider_mode.currentData(), 'chatgpt_plan')
        self.window.provider_mode.setCurrentIndex(self.window.provider_mode.findData('fixture'))
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.jobs.close()
        accepted = self.window.close()
        self.app.processEvents()
        # Closing hides a QWidget but does not destroy its native children or
        # timers. Delete only this successfully closed, quiescent fixture.
        # Refused close/reconciliation must keep the original window alive.
        if accepted and not self.jobs.active:
            from PySide6.QtCore import QCoreApplication, QEvent

            self.window.deleteLater()
            QCoreApplication.sendPostedEvents(self.window, QEvent.Type.DeferredDelete)

    def click(self, name):
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt

        button = self.window.findChild(QPushButton, name)
        self.assertIsNotNone(button, name)
        # Real mouse event even if its page is offscreen: switch its containing page.
        for index in range(self.window.stack.count()):
            if self.window.stack.widget(index).isAncestorOf(button):
                self.window.navigation.setCurrentRow(index)
                break
        if name == 'configure_workspace':
            self.window.settings_page.paths_toggle.setChecked(True)
        if name in ('create_backup', 'restore_backup'):
            self.window.settings_page.backup_toggle.setChecked(True)
        self.app.processEvents()
        from PySide6.QtWidgets import QMessageBox

        if button.property('role') == 'danger':
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        else:
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def wait_job(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.jobs.active and time.monotonic() < deadline:
            self.app.processEvents()
            self.window.poll_jobs()
            time.sleep(0.02)
        self.window.poll_jobs()
        self.assertFalse(self.jobs.active, self.window.status.text())
        self.assertNotIn('失敗', self.window.status.text() + self.window.notification.text())

    def demo(self):
        self.click('create_demo')
        self.wait_job()
        self.assertTrue((self.paths.state / 'dataset.json').exists())

    def test_navigation_empty_and_validation(self):
        self.assertEqual(self.window.navigation.count(), 7)
        self.assertFalse(self.window.run_button.isEnabled())
        for index in range(7):
            self.window.navigation.setCurrentRow(index)
            self.app.processEvents()
            self.assertEqual(self.window.stack.currentIndex(), index)
        self.click('import_data')
        self.assertIn('請選擇資料', self.window.status.text())
        self.click('refresh_data')
        self.assertIn('同意', self.window.status.text())
        self.assertFalse(self.jobs.active)

    def test_import_real_button_and_bad_file_recovery(self):
        self.window.import_path.setText('/missing.csv')
        self.window.calendar_path.setText('/missing.json')
        self.click('import_data')
        deadline = time.monotonic() + 10
        while self.jobs.active and time.monotonic() < deadline:
            self.app.processEvents()
            self.window.poll_jobs()
            time.sleep(0.02)
        self.window.poll_jobs()
        self.assertIn('失敗', self.window.notification.text())
        root = Path(__file__).resolve().parents[1]
        self.window.import_path.setText(str(root / 'examples/synthetic_bars.csv'))
        self.window.calendar_path.setText(str(root / 'examples/synthetic_calendar.json'))
        self.window.import_kind.setCurrentIndex(self.window.import_kind.findData('synthetic_bars'))
        self.click('import_data')
        self.wait_job()
        self.assertIn('合成示範資料', self.window.overview.text())

    def test_backtest_repeat_compare_select_disable(self):
        self.demo()
        self.click('run_backtest')
        self.wait_job()
        first = list((self.paths.state / 'reports').glob('*/result.json'))
        self.assertEqual(len(first), 1)
        self.assertTrue(self.window.plot.values)
        self.click('run_backtest')
        self.wait_job()
        self.assertEqual(list((self.paths.state / 'reports').glob('*/result.json')), first)
        self.window.comparison_list.item(0).setSelected(True)
        self.click('compare_results')
        self.wait_job()
        self.assertIn('result_hash', self.window.comparison.toPlainText())
        self.click('select_strategy')
        self.wait_job()
        selection = json.loads((self.paths.state / 'selection.json').read_text())
        self.assertEqual(selection['scope'], 'research_and_paper_only')
        self.click('disable_strategy')
        self.wait_job()
        self.assertFalse((self.paths.state / 'selection.json').exists())

    def test_batch_dates_parameters_and_error(self):
        self.demo()
        self.window.start_date.setText('2026-01-05')
        self.window.end_date.setText('2026-01-05')
        self.window.batch.setChecked(True)
        self.click('run_backtest')
        self.wait_job()
        self.assertEqual(len(list((self.paths.state / 'reports').glob('*/result.json'))), 5)
        self.window.config.setPlainText('{broken')
        self.click('run_backtest')
        self.assertIn('未完成', self.window.status.text())
        self.assertFalse(self.jobs.active)

    def test_cancel_running_process_and_repeat(self):
        self.demo()
        self.click('run_campaign')
        self.assertTrue(self.jobs.active)
        self.window.navigation.setCurrentRow(5)
        self.app.processEvents()
        self.window.cancel_job()
        self.window.poll_jobs()
        self.assertFalse(self.jobs.active)
        self.assertIn('取消', self.window.status.text())
        self.assertTrue((self.paths.state / 'desktop_safety.json').exists())
        self.click('run_backtest')
        self.wait_job()

    def test_paper_explicit_reconcile_replay_kill(self):
        self.demo()
        self.click('run_backtest')
        self.wait_job()
        self.click('select_strategy')
        self.wait_job()
        self.click('demo_policy')
        self.click('paper_snapshot')
        self.wait_job()
        self.click('paper_reconcile')
        self.wait_job()
        self.click('paper_replay')
        self.assertIn('validation_failed', self.window.status.text())
        self.assertFalse(self.jobs.active)
        self.window.paper_confirm.setChecked(True)
        self.click('paper_replay')
        self.wait_job()
        result = json.loads(self.window.paper_detail.toPlainText())
        self.assertGreater(result['replay']['cursor'], 0)
        self.assertTrue(result['account']['kill_switch'])
        self.assertFalse(self.window.paper_confirm.isChecked())
        with patch('desktop_app.features.paper.paper.stop_dialog') as factory:
            factory.return_value.clickedButton.return_value = factory.return_value.confirm_button
            self.click('paper_kill')
        self.wait_job()
        self.assertIn('kill_switch', self.window.paper_detail.toPlainText())

    def test_settings_backup_restore_confirmation(self):
        self.window.local_notifications.setChecked(False)
        self.click('save_settings')
        self.assertIn('已保存', self.window.status.text())
        self.demo()
        backup = Path(self.tmp.name) / 'backup.zip'
        self.window.backup_path.setText(str(backup))
        self.click('create_backup')
        self.wait_job()
        self.assertTrue(backup.exists())
        self.click('restore_backup')
        self.assertIn('確認', self.window.status.text())
        self.window.restore_confirm.setChecked(True)
        self.click('restore_backup')
        self.wait_job()
        self.assertTrue((self.paths.state / 'desktop_safety.json').exists())

    def test_legacy_provider_settings_remain_inert_and_budget_identity_unchanged(self):
        from quantlab.research_core.application.ui_operations.binding_policy import provider_binding_options

        old = {'mode': 'compatible', 'model': 'example', 'network_opt_in': True}
        self.assertEqual(provider_binding_options(old), provider_binding_options(dict(old, output_mode='json_object')))
        self.assertNotEqual(provider_binding_options(old), provider_binding_options(dict(old, output_mode='registry_json_schema')))
        legacy = {
            'ai_endpoint': 'http://127.0.0.1:18765/v1/chat/completions',
            'ai_model': 'historical-model',
            'output_mode': 'unknown-historical-mode',
            'max_calls': 1,
            'max_spend': '0',
        }
        self.window.settings.save(legacy)
        self.window.load_settings()
        self.click('save_settings')
        saved = self.window.settings.load()
        for key, value in legacy.items():
            self.assertEqual(saved[key], value)
        self.assertFalse(self.jobs.active)
        self.assertFalse(hasattr(self.window, 'ai_endpoint'))
        self.assertFalse(hasattr(self.window, 'output_mode'))

    def test_invalid_policy_cannot_poison_startup(self):
        self.demo()
        self.click('paper_snapshot')
        deadline = time.monotonic() + 10
        while self.jobs.active and time.monotonic() < deadline:
            self.app.processEvents()
            self.window.poll_jobs()
            time.sleep(0.02)
        self.window.poll_jobs()
        self.assertIn('失敗', self.window.notification.text())
        self.assertFalse((self.paths.state / 'paper_policy.json').exists())
        self.window.freeze_paper('startup safety')
        self.click('demo_policy')
        self.click('paper_snapshot')
        self.wait_job()
        self.assertTrue((self.paths.state / 'paper_policy.json').exists())

    def test_chatgpt_entry_uses_shared_primary_flow_on_explicit_click(self):
        with patch.object(self.window.chatgpt_controller, 'request') as request:
            self.click('chatgpt_sign_in_entry')
            request.assert_called_once_with('list')
        self.assertEqual(self.window.provider_mode.currentData(), 'chatgpt_plan')
        self.assertTrue(self.window.stack.currentWidget().isAncestorOf(self.window.chatgpt_panel))
        self.assertFalse(self.jobs.active)
        self.assertFalse(self.window.chatgpt_panel.consent.isChecked())

    def test_product_has_no_custom_endpoint_key_or_local_model_controls(self):
        from PySide6.QtWidgets import QPushButton

        self.assertEqual([self.window.provider_mode.itemData(i) for i in range(self.window.provider_mode.count())], ['chatgpt_plan', 'fixture', 'manual'])
        for name in ('ai_endpoint', 'ai_model', 'api_key', 'use_key', 'ai_opt_in', 'local_ai_panel'):
            self.assertFalse(hasattr(self.window, name), name)
        self.assertIsNone(self.window.findChild(QPushButton, 'save_api_key'))

    def test_retired_model_cache_and_control_evidence_are_never_deleted(self):
        cache = self.paths.root / 'cache' / 'local-ai' / 'historical-profile' / 'model.gguf'
        ledger = self.paths.controls / 'local-ai-v1.sqlite3'
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b'INERT historical user-owned cache sentinel')
        ledger.write_bytes(b'INERT irreversible historical control sentinel')
        before = {path: path.read_bytes() for path in (cache, ledger)}
        self.window.load_settings()
        self.window.save_settings()
        self.window.freeze_paper('test safe stop without retired model workers')
        self.window.close()
        self.app.processEvents()
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_removed_provider_selection_fails_before_worker_or_network(self):
        self.demo()
        for mode in ('compatible', 'local', 'ollama', 'paid_api'):
            self.window.provider_mode.addItem('unsupported test fixture', mode)
            self.window.provider_mode.setCurrentIndex(self.window.provider_mode.count() - 1)
            with patch.object(self.window, 'start_job') as start:
                with self.assertRaises(ValueError):
                    self.window.run_campaign()
                start.assert_not_called()
        self.assertFalse(self.jobs.active)

    def test_remote_free_assumption_and_secret_endpoint_rejected_before_files(self):
        from quantlab.research_core.application.research_operations import campaign_generator

        opts = dict(
            mode='compatible',
            network_opt_in=True,
            endpoint='https://example.invalid/v1',
            model='unverified',
            use_credential=True,
            max_calls=1,
            max_tokens=1000,
            max_spend='0',
            cost_per_token='0',
            tokens_per_call=100,
            timeout_seconds=2,
        )
        with self.assertRaises(ValueError):
            campaign_generator(_c_create_operation_ports(), self.paths, opts)
        opts.update(endpoint='https://key:secret@example.invalid/v1', max_spend='1', cost_per_token='0.001')
        with self.assertRaises(ValueError):
            campaign_generator(_c_create_operation_ports(), self.paths, opts)
        self.assertFalse((self.paths.state / 'provider_budgets').exists())

    def campaign(self, minimum='-100000000'):
        from quantlab.reporting import load_dataset, demo_config
        from quantlab.research import demo_campaign_config
        from quantlab.core import canonical_json

        cfg = demo_campaign_config(load_dataset(self.paths.state / 'dataset.json'), demo_config())
        cfg.update(families=['trend'], max_trials=1, max_improvements=0)
        cfg['ranking']['minimum'] = minimum
        self.window.campaign_config.setPlainText(canonical_json(cfg))
        self.click('run_campaign')
        self.wait_job(60)

    def test_generated_candidate_picker_backtest_selection_and_persistence(self):
        from quantlab.research_core.application.ui_operations.data import candidate_record
        from quantlab.reporting import load_result

        self.demo()
        self.campaign()
        self.assertGreater(self.window.candidate_choice.count(), 0)
        self.window.strategy_form.fields['fast'].setText('7')
        self.window.strategy_form.fields['slow'].setText('31')
        self.click('use_candidate')
        reference = self.window.active_candidate
        self.assertIsNotNone(reference)
        spec, meta = candidate_record(_c_create_operation_ports(), self.paths.state, reference)
        self.assertTrue(meta['paper_qualified'])
        self.assertTrue(self.window.parameters.isReadOnly())
        self.assertFalse(self.window.strategy_form.isEnabled())
        for key, value in spec.parameters.items():
            self.assertEqual(self.window.strategy_form.fields[key].text(), str(value))
        self.click('run_backtest')
        self.wait_job()
        result = load_result(self.window.result_choice.currentData())
        self.assertEqual(result.manifest['strategy']['strategy_id'], spec.strategy_id)
        self.assertEqual(result.manifest['dataset_manifest']['desktop_candidate_reference'], reference)
        self.click('select_strategy')
        self.wait_job()
        selection = json.loads((self.paths.state / 'selection.json').read_text())
        self.assertEqual(selection['strategy_hash'], reference['strategy_hash'])
        self.window.active_candidate = None
        self.window.strategy_form.fields['fast'].setText('9')
        self.window.strategy_form.fields['slow'].setText('43')
        self.window.refresh_views()
        self.assertEqual(self.window.active_candidate, reference)
        for key, value in spec.parameters.items():
            self.assertEqual(self.window.strategy_form.fields[key].text(), str(value))
        self.click('use_builtin')
        self.assertIsNone(self.window.active_candidate)
        self.assertFalse((self.paths.state / 'active_candidate.json').exists())

    def test_generated_unqualified_candidate_research_only(self):
        from desktop_app.connection_composition import execute_ui_operation

        self.demo()
        self.campaign('100000000')
        self.click('use_candidate')
        self.assertIsNotNone(self.window.active_candidate)
        self.click('run_backtest')
        self.wait_job()
        self.assertFalse(self.window.select_button.isEnabled())
        with self.assertRaises(ValueError):
            execute_ui_operation('ui_select', {'result': self.window.result_choice.currentData()}, self.paths)
        self.assertFalse((self.paths.state / 'selection.json').exists())
        self.assertIn('false', self.window.candidate_detail.toPlainText())

    def test_adopted_candidate_form_matches_immutable_parameters(self):
        from quantlab.core import StrategySpec, canonical_json, content_hash, to_dict
        from quantlab.strategies import validate_strategy

        rule = {'op': 'gt', 'left': {'op': 'field', 'name': 'close'}, 'right': {'op': 'const', 'value': '20000'}}
        cases = [
            ('trend', {'fast': 7, 'slow': 31, 'quantity': 2, 'stop_ticks': 12, 'target_ticks': 24}, {}),
            ('trend', {'fast': 9, 'slow': 43}, {'long': rule, 'short': {'op': 'not', 'arg': rule}}),
            ('momentum', {'lookback': 8, 'threshold_bps': '25', 'max_holding_bars': 7}, {}),
            ('mean_reversion', {'lookback': 13, 'entry_bps': '70'}, {}),
            ('channel_breakout', {'lookback': 17}, {}),
            ('volatility_compression', {'lookback': 12, 'max_range_bps': '55'}, {}),
        ]
        provenance = {'paper_qualified': False, 'evaluations': {}, 'source_type': 'synthetic'}
        for index, (family, parameters, rules) in enumerate(cases):
            with self.subTest(family=family, index=index):
                spec = StrategySpec(f'form-sync-{index}', family, parameters, rules)
                validate_strategy(spec)
                original = canonical_json(spec)
                reference = {'campaign_folder': 'a' * 64, 'attempt_id': 'b' * 64, 'strategy_hash': content_hash(spec)}
                self.window.candidate_choice.blockSignals(True)
                self.window.candidate_choice.clear()
                self.window.candidate_choice.addItem('synthetic form-sync fixture', reference)
                self.window.candidate_choice.blockSignals(False)
                with patch.object(self.window.strategy_page.host, 'candidate_record', return_value=(spec, provenance)):
                    self.window.strategy_page.use_candidate()
                self.assertEqual(self.window.active_candidate, reference)
                self.assertFalse(self.window.strategy_form.isEnabled())
                self.assertTrue(self.window.parameters.isReadOnly())
                for key, field in self.window.strategy_form.fields.items():
                    if key != 'family':
                        self.assertEqual(field.text(), str(parameters.get(key, '')), key)
                detail = json.loads(self.window.strategy_detail.toPlainText())
                self.assertEqual(detail['strategy'], to_dict(spec))
                self.assertEqual(canonical_json(spec), original)

    def test_declining_busy_close_preserves_header_and_job_polling(self):
        from unittest.mock import PropertyMock
        from PySide6.QtWidgets import QMessageBox

        self.assertTrue(self.window.app_header.timer.isActive())
        with (
            patch.object(type(self.jobs), 'active', new_callable=PropertyMock, return_value=True),
            patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No),
            patch.object(self.jobs, 'close') as stop,
        ):
            self.assertFalse(self.window.close())
            stop.assert_not_called()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.app_header.timer.isActive())
        self.assertTrue(self.window.timer.isActive())

    def test_update_notifications_logs_and_persistent_preferences(self):
        from PySide6.QtGui import QDesktopServices

        with patch.object(QDesktopServices, 'openUrl', return_value=True) as opened:
            self.click('open_releases')
            self.assertEqual(opened.call_args[0][0].toString(), 'https://github.com/yostar77612/mark-auto/releases')
        self.assertIn('未下載', self.window.status.text())
        self.demo()
        self.assertFalse(self.window.notification.isHidden())
        self.click('read_logs')
        self.assertIn(ui_text('logs.operation.ui_demo'), [self.window.log_view.item(row, 1).text() for row in range(self.window.log_view.rowCount())])
        self.window.local_notifications.setChecked(False)
        self.window.persist_logs.setChecked(False)
        self.click('save_settings')
        self.window.local_notifications.setChecked(True)
        self.window.persist_logs.setChecked(True)
        self.window.load_settings()
        self.assertFalse(self.window.local_notifications.isChecked())
        self.assertFalse(self.window.persist_logs.isChecked())
        self.window.notification.hide()
        self.window.notify_local('test')
        self.assertTrue(self.window.notification.isHidden())

    def test_workspace_change_restart_only(self):
        self.demo()
        old = self.paths.state / 'dataset.json'
        data = old.read_bytes()
        destination = Path(self.tmp.name) / 'next-workspace'
        self.window.workspace_path.setText(str(destination))
        self.click('configure_workspace')
        self.assertIn('下次啟動', self.window.status.text())
        self.assertEqual(old.read_bytes(), data)
        self.assertEqual(self.window.root, self.paths.state)
        self.assertFalse((destination / 'state-v1' / 'dataset.json').exists())

    def test_candidate_edited_export_cannot_change_qualification(self):
        from quantlab.research_core.application.ui_operations.data import candidate_record
        from quantlab.reporting import read_json, write_json

        self.demo()
        self.campaign()
        reference = self.window.candidate_choice.currentData()
        spec, meta = candidate_record(_c_create_operation_ports(), self.paths.state, reference)
        self.assertTrue(meta['paper_qualified'])
        path = self.paths.state / 'campaigns' / reference['campaign_folder'] / 'campaign.json'
        original = read_json(path)
        edited = json.loads(json.dumps(original))
        edited['evaluations']['oos'][0]['metrics']['net_pnl'] = '999999999'
        write_json(path, edited)
        with self.assertRaises(ValueError):
            candidate_record(_c_create_operation_ports(), self.paths.state, reference)
        self.window.inspect_candidate()
        self.assertFalse(self.window.use_candidate_button.isEnabled())
        self.assertEqual(read_json(path), edited)  # Never silently repair an edited export.
        write_json(path, original)
        edited = json.loads(json.dumps(original))
        edited['selected'] = []
        edited['status'] = 'completed'
        write_json(path, edited)
        with self.assertRaises(ValueError):
            candidate_record(_c_create_operation_ports(), self.paths.state, reference)

    def test_freeze_recovers_cancelled_restore_before_any_state_write(self):
        self.demo()
        old = (self.paths.state / 'dataset.json').read_bytes()
        rollback = self.paths.root / 'state-v1.rollback'
        window = self.window

        class InterruptedRestore:
            active = True

            def cancel(inner):
                # Fault injection: worker reached old-state rename, then was joined.
                os.replace(self.paths.state, rollback)
                self.assertFalse(self.paths.state.exists())
                inner.active = False

        window.timer.stop()
        original = window.jobs
        window.jobs = InterruptedRestore()
        try:
            window.freeze_paper('sleep during restore')
            self.assertEqual((self.paths.state / 'dataset.json').read_bytes(), old)
            self.assertTrue((self.paths.state / 'desktop_safety.json').exists())
        finally:
            window.jobs = original

    def test_freeze_refuses_state_write_until_worker_joined(self):
        self.demo()
        rollback = self.paths.root / 'state-v1.rollback'
        os.replace(self.paths.state, rollback)
        window = self.window

        class UnjoinedWorker:
            active = True

            def cancel(inner):
                pass

        window.timer.stop()
        original = window.jobs
        window.jobs = UnjoinedWorker()
        try:
            with self.assertRaises(ValueError):
                window.freeze_paper('worker stuck')
            self.assertFalse(self.paths.state.exists())
            self.assertTrue((rollback / 'dataset.json').exists())
        finally:
            window.jobs = original
            window.backups.recover()

    def test_historical_provider_budget_survives_older_backup_and_workspace_change(self):
        research_controls = _c_create_operation_ports().inputs.research_controls
        from quantlab.research import CompatibleProvider
        from quantlab.provider import HTTPTransport

        def historical_provider(paths, options):
            # Retained ledger semantics tested directly; no product provider path.
            return CompatibleProvider(
                model=options["model"],
                endpoint=options["endpoint"],
                transport=HTTPTransport(allow_network=True),
                budget_path=research_controls(paths) / "provider_budgets" / "historical.sqlite3",
                network_opt_in=True,
                max_calls=options["max_calls"],
                max_tokens=options["max_tokens"],
                max_spend=options["max_spend"],
                cost_per_token=options["cost_per_token"],
                tokens_per_call=options["tokens_per_call"],
                timeout_seconds=options["timeout_seconds"],
            )

        from quantlab.desktop_runtime import AppPaths
        from quantlab.core import canonical_json
        from quantlab.strategies import builtin_strategies

        self.demo()
        archive = Path(self.tmp.name) / 'before-budget.zip'
        self.window.backups.create(archive)
        options = dict(
            mode='compatible',
            network_opt_in=True,
            endpoint='http://127.0.0.1:12345/v1',
            model='inert-fixture',
            use_credential=False,
            max_calls=1,
            max_tokens=10000,
            max_spend='0',
            cost_per_token='0',
            tokens_per_call=100,
            timeout_seconds=2,
        )
        response = {'choices': [{'message': {'content': canonical_json(builtin_strategies()[0])}}]}
        with patch('quantlab.provider.HTTPTransport.__call__', return_value=response) as transport:
            historical_provider(self.paths, options).generate({})
            self.window.backups.restore(archive)
            with self.assertRaises(ValueError):
                historical_provider(self.paths, options).generate({})
            other = AppPaths(Path(self.tmp.name) / 'other-workspace', self.paths.bootstrap or self.paths.root).ensure()
            self.assertEqual(other.controls, self.paths.controls)
            with self.assertRaises(ValueError):
                historical_provider(other, options).generate({})
            self.assertEqual(transport.call_count, 1)
        self.assertFalse((self.paths.state / 'provider_budgets').exists())
        self.assertTrue(list((self.paths.controls / 'provider_budgets').glob('*.sqlite3')))

    def test_consumed_holdout_survives_older_backup_restore(self):
        self.demo()
        archive = Path(self.tmp.name) / 'before-holdout.zip'
        self.window.backups.create(archive)
        self.campaign()
        first = json.loads(self.window.summary.toPlainText())
        self.assertEqual(first['holdout_status'], 'reserved_consumed')
        self.assertTrue((self.paths.controls / 'holdout-registry.sqlite3').exists())
        self.window.backups.restore(archive)
        self.window.refresh_views()
        self.campaign()
        second = json.loads(self.window.summary.toPlainText())
        self.assertEqual(second['status'], 'blocked_previously_consumed_holdout')
        self.assertEqual(second['evaluations']['holdout'], [])
        self.assertFalse((self.paths.state / 'campaigns' / '.holdout_registry.sqlite3').exists())

    def test_legacy_research_ledgers_fail_closed_without_migration(self):
        from quantlab.research_core.application.research_operations import campaign_generator

        for relative in ['provider_budgets/legacy.sqlite3', 'campaigns/.holdout_registry.sqlite3']:
            path = self.paths.state / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'legacy-used-ledger')
            with self.assertRaises(ValueError):
                campaign_generator(_c_create_operation_ports(), self.paths, {'mode': 'fixture'})
            self.assertEqual(path.read_bytes(), b'legacy-used-ledger')
            path.unlink()

    def test_terminal_input_error_is_not_relabelled_as_cancelled(self):
        class SlowErrorExit:
            active = True
            step = 0

            def poll(inner):
                inner.step += 1
                if inner.step == 1:
                    return [{'type': 'error', 'message': '輸入驗證失敗'}]
                inner.active = False
                return []

            def cancel(inner):
                raise AssertionError('An input error must not trigger user cancellation')

        self.window.timer.stop()
        original = self.window.jobs
        self.window.jobs = SlowErrorExit()
        self.window.last_operation = 'ui_import'
        try:
            self.window.poll_jobs()
            self.assertIn('失敗', self.window.notification.text())
            self.window.poll_jobs()
            self.assertIn('失敗', self.window.notification.text())
            self.assertNotIn('取消', self.window.notification.text())
        finally:
            self.window.jobs = original

    def test_service_rejects_unknown_code_and_network_without_consent(self):
        from desktop_app.connection_composition import execute_ui_operation

        for op, payload in [('exec', {'code': '1+1'}), ('ui_refresh', {})]:
            with self.assertRaises(ValueError):
                execute_ui_operation(op, payload, self.paths)
        self.assertFalse((self.paths.state / 'dataset.json').exists())


if __name__ == '__main__':
    unittest.main()
