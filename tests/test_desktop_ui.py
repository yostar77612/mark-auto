"""Native widget and real isolated-worker integration tests; run QT_QPA_PLATFORM=offscreen."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
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
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
        from desktop_ui import MainWindow
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(self.paths, self.jobs, SettingsStore(self.paths.state/'settings.json'), BackupManager(self.paths, self.jobs))
        self.window.show(); self.app.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.jobs.close(); self.window.close(); self.app.processEvents()

    def click(self, name):
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        button = self.window.findChild(QPushButton, name)
        self.assertIsNotNone(button, name)
        # Real mouse event even if its page is offscreen: switch its containing page.
        for index in range(self.window.stack.count()):
            if self.window.stack.widget(index).isAncestorOf(button):
                self.window.navigation.setCurrentRow(index); break
        self.app.processEvents()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def wait_job(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.jobs.active and time.monotonic() < deadline:
            self.app.processEvents(); self.window.poll_jobs(); time.sleep(.02)
        self.window.poll_jobs()
        self.assertFalse(self.jobs.active, self.window.status.text())
        self.assertNotIn('失敗', self.window.status.text(), self.window.status.text())

    def demo(self):
        self.click('create_demo'); self.wait_job()
        self.assertTrue((self.paths.state/'dataset.json').exists())

    def test_navigation_empty_and_validation(self):
        self.assertEqual(self.window.navigation.count(), 7)
        self.assertFalse(self.window.run_button.isEnabled())
        for index in range(7):
            self.window.navigation.setCurrentRow(index); self.app.processEvents()
            self.assertEqual(self.window.stack.currentIndex(), index)
        self.click('import_data'); self.assertIn('請選擇資料', self.window.status.text())
        self.click('refresh_data'); self.assertIn('同意', self.window.status.text())
        self.assertFalse(self.jobs.active)

    def test_import_real_button_and_bad_file_recovery(self):
        self.window.import_path.setText('/missing.csv'); self.window.calendar_path.setText('/missing.json')
        self.click('import_data')
        deadline=time.monotonic()+10
        while self.jobs.active and time.monotonic()<deadline:
            self.app.processEvents(); self.window.poll_jobs(); time.sleep(.02)
        self.window.poll_jobs(); self.assertIn('失敗', self.window.status.text())
        root=Path(__file__).resolve().parents[1]
        self.window.import_path.setText(str(root/'examples/synthetic_bars.csv'))
        self.window.calendar_path.setText(str(root/'examples/synthetic_calendar.json'))
        self.window.import_kind.setCurrentText('synthetic_bars')
        self.click('import_data'); self.wait_job()
        self.assertIn('SYNTHETIC', self.window.overview.text())

    def test_backtest_repeat_compare_select_disable(self):
        self.demo(); self.click('run_backtest'); self.wait_job()
        first=list((self.paths.state/'reports').glob('*/result.json')); self.assertEqual(len(first),1)
        self.assertTrue(self.window.plot.values)
        self.click('run_backtest'); self.wait_job()
        self.assertEqual(list((self.paths.state/'reports').glob('*/result.json')),first)
        self.window.comparison_list.item(0).setSelected(True)
        self.click('compare_results'); self.wait_job(); self.assertIn('result_hash', self.window.comparison.toPlainText())
        self.click('select_strategy'); self.wait_job()
        selection=json.loads((self.paths.state/'selection.json').read_text()); self.assertEqual(selection['scope'],'research_and_paper_only')
        self.click('disable_strategy'); self.wait_job(); self.assertFalse((self.paths.state/'selection.json').exists())

    def test_batch_dates_parameters_and_error(self):
        self.demo(); self.window.start_date.setText('2026-01-05'); self.window.end_date.setText('2026-01-05')
        self.window.batch.setChecked(True); self.click('run_backtest'); self.wait_job()
        self.assertEqual(len(list((self.paths.state/'reports').glob('*/result.json'))),5)
        self.window.config.setPlainText('{broken'); self.click('run_backtest'); self.assertIn('未完成',self.window.status.text())
        self.assertFalse(self.jobs.active)

    def test_cancel_running_process_and_repeat(self):
        self.demo(); self.click('run_campaign'); self.assertTrue(self.jobs.active)
        self.window.navigation.setCurrentRow(0); self.app.processEvents()
        self.window.cancel_job(); self.window.poll_jobs()
        self.assertFalse(self.jobs.active); self.assertIn('取消', self.window.status.text())
        self.assertTrue((self.paths.state/'desktop_safety.json').exists())
        self.click('run_backtest'); self.wait_job()

    def test_paper_explicit_reconcile_replay_kill(self):
        self.demo(); self.click('run_backtest'); self.wait_job(); self.click('select_strategy'); self.wait_job()
        self.click('demo_policy'); self.click('paper_snapshot'); self.wait_job()
        self.click('paper_reconcile'); self.wait_job()
        self.click('paper_replay'); self.assertIn('明確勾選', self.window.status.text()); self.assertFalse(self.jobs.active)
        self.window.paper_confirm.setChecked(True); self.click('paper_replay'); self.wait_job()
        result=json.loads(self.window.paper_detail.toPlainText()); self.assertGreater(result['replay']['cursor'],0)
        self.assertTrue(result['account']['kill_switch'])
        self.assertFalse(self.window.paper_confirm.isChecked())
        self.click('paper_kill'); self.wait_job(); self.assertIn('kill_switch',self.window.paper_detail.toPlainText())

    def test_settings_backup_restore_confirmation(self):
        self.window.ai_endpoint.setText('https://example.invalid/v1'); self.window.ai_model.setText('unverified')
        self.click('save_settings'); self.assertIn('已保存',self.window.status.text())
        self.demo(); backup=Path(self.tmp.name)/'backup.zip'; self.window.backup_path.setText(str(backup))
        self.click('create_backup'); self.wait_job(); self.assertTrue(backup.exists())
        self.click('restore_backup'); self.assertIn('確認',self.window.status.text())
        self.window.restore_confirm.setChecked(True); self.click('restore_backup'); self.wait_job()
        self.assertTrue((self.paths.state/'desktop_safety.json').exists())

    def test_invalid_policy_cannot_poison_startup(self):
        self.demo(); self.click('paper_snapshot')
        deadline=time.monotonic()+10
        while self.jobs.active and time.monotonic()<deadline:
            self.app.processEvents(); self.window.poll_jobs(); time.sleep(.02)
        self.window.poll_jobs(); self.assertIn('失敗',self.window.status.text())
        self.assertFalse((self.paths.state/'paper_policy.json').exists())
        self.window.freeze_paper('startup safety')
        self.click('demo_policy'); self.click('paper_snapshot'); self.wait_job()
        self.assertTrue((self.paths.state/'paper_policy.json').exists())

    def test_endpoint_rejects_embedded_secrets(self):
        for endpoint in ['https://user:pass@example.invalid/v1', 'https://example.invalid/v1?key=secret', 'https://example.invalid/#secret']:
            self.window.ai_endpoint.setText(endpoint); self.click('save_settings')
            self.assertIn('不得包含',self.window.status.text())
        self.assertFalse((self.paths.state/'settings.json').exists())

    def test_model_paid_opt_in_and_local_transport_button(self):
        import threading
        from http.server import ThreadingHTTPServer
        from tests.test_provider import Handler
        from quantlab.reporting import load_dataset, demo_config
        from quantlab.research import demo_campaign_config
        from quantlab.core import canonical_json
        self.demo()
        self.window.provider_mode.setCurrentIndex(1)
        self.click('run_campaign'); self.assertIn('本次網路',self.window.status.text()); self.assertFalse(self.jobs.active)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            self.window.ai_endpoint.setText(f'http://127.0.0.1:{server.server_port}/good')
            self.window.ai_model.setText('inert-local-fixture')
            self.window.use_key.setChecked(False); self.window.ai_opt_in.setChecked(True)
            data=load_dataset(self.paths.state/'dataset.json'); cfg=demo_campaign_config(data,demo_config())
            cfg.update(families=['trend'],max_trials=1,max_improvements=0)
            self.window.campaign_config.setPlainText(canonical_json(cfg))
            before=len(Handler.seen)
            self.click('run_campaign'); self.wait_job(60)
            self.assertEqual(len(Handler.seen),before+1)
            self.assertFalse(self.window.ai_opt_in.isChecked())
            state=json.loads(self.window.summary.toPlainText())
            self.assertEqual(state['real_model_status'],'not_verified')
            self.assertEqual(state['attempts'][0]['status'],'evaluated')
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_vault_key_button_never_persists_plaintext(self):
        secret='inert-credential-widget-test-only'
        self.window.api_key.setText(secret)
        with patch('quantlab.desktop_runtime.CredentialVault.save') as save:
            self.click('save_api_key')
            save.assert_called_once_with('model_api_key',secret)
        self.assertEqual(self.window.api_key.text(),'')
        self.assertNotIn(secret,self.window.status.text())
        self.click('save_settings')
        for path in self.paths.state.rglob('*'):
            if path.is_file(): self.assertNotIn(secret.encode(),path.read_bytes())

    def test_remote_free_assumption_and_secret_endpoint_rejected_before_files(self):
        from desktop_ui import campaign_generator
        opts=dict(mode='compatible',network_opt_in=True,endpoint='https://example.invalid/v1',model='unverified',
                  use_credential=True,max_calls=1,max_tokens=1000,max_spend='0',cost_per_token='0',tokens_per_call=100,timeout_seconds=2)
        with self.assertRaises(ValueError): campaign_generator(self.paths,opts)
        opts.update(endpoint='https://key:secret@example.invalid/v1',max_spend='1',cost_per_token='0.001')
        with self.assertRaises(ValueError): campaign_generator(self.paths,opts)
        self.assertFalse((self.paths.state/'provider_budgets').exists())

    def test_service_rejects_unknown_code_and_network_without_consent(self):
        from desktop_ui import execute_ui_operation
        for op,payload in [('exec',{'code':'1+1'}),('ui_refresh',{})]:
            with self.assertRaises(ValueError): execute_ui_operation(op,payload,self.paths)
        self.assertFalse((self.paths.state/'dataset.json').exists())


if __name__ == '__main__': unittest.main()
