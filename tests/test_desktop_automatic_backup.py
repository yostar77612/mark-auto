import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt required')
class AutomaticBackupPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        from quantlab.desktop_runtime import AppPaths, JobManager
        from desktop_automatic_backup import AutomaticBackupPanel
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.window = QWidget(); w = self.window
        w.paths = AppPaths(Path(self.tmp.name)/'workspace').ensure()
        w.jobs = JobManager(w.paths)
        w.start_job = lambda operation, payload: w.jobs.start(operation, payload)
        w.local_ai_panel = SimpleNamespace(server=SimpleNamespace(active=False), task=SimpleNamespace(active=False))
        w.chatgpt_controller = SimpleNamespace(busy=False)
        w._wf_pending_reconcile = w._pending_plan_reconcile = w._pending_usage_refresh = False
        self.panel = AutomaticBackupPanel(w); self.panel.timer.stop()
        self.addCleanup(w.deleteLater); self.addCleanup(w.jobs.close)
        self.panel.enabled.setChecked(True)
        self.panel.directory.setText(str(Path(self.tmp.name)/'archives'))
        self.panel.save()

    def wait(self):
        deadline = time.monotonic()+20
        while self.window.jobs.active and time.monotonic() < deadline:
            for event in self.window.jobs.poll(): self.panel.handle_job_event(event)
            self.app.processEvents(); time.sleep(.01)
        self.assertFalse(self.window.jobs.active)

    def test_real_nonblocking_archive_and_result(self):
        self.panel.tick()
        self.assertTrue(self.window.jobs.active)
        self.assertIsNotNone(self.panel.archive)
        self.wait()
        settings = self.panel.scheduler.load()
        self.assertEqual(settings['last_status'], 'success')
        self.assertTrue(Path(settings['last_archive']).is_file())
        self.assertIsNone(self.panel.archive)
        self.panel.tick(); self.assertFalse(self.window.jobs.active)

    def test_all_manager_busy_and_reconciliation_defer(self):
        w = self.window
        for item, attribute in ((w.local_ai_panel.server,'active'), (w.local_ai_panel.task,'active'),
                                (w.chatgpt_controller,'busy'), (w,'_wf_pending_reconcile'),
                                (w,'_pending_plan_reconcile'), (w,'_pending_usage_refresh'), (w,'_closing')):
            setattr(item, attribute, True); self.panel.tick()
            self.assertIsNone(self.panel.scheduler.load()['last_attempt_day'])
            self.assertFalse(w.jobs.active)
            setattr(item, attribute, False)

    def test_primary_worker_busy_does_not_claim(self):
        self.window.jobs.start('ui_demo', {})
        self.panel.tick()
        self.assertIsNone(self.panel.scheduler.load()['last_attempt_day'])
        self.window.jobs.cancel()

    def test_launch_failure_is_visible_and_not_retried(self):
        def fail(operation, payload): raise OSError('launch failed')
        self.window.start_job = fail
        self.panel.tick()
        self.assertTrue(self.panel.paused)
        self.assertEqual(self.panel.scheduler.load()['last_status'], 'error')
        self.assertIsNone(self.panel.archive)
        self.assertIn('launch failed', self.panel.status.text())
        self.panel.tick()
        self.assertFalse(self.window.jobs.active)

    def test_cancel_no_daily_retry(self):
        self.panel.tick(); self.window.jobs.cancel()
        for event in self.window.jobs.poll(): self.panel.handle_job_event(event)
        self.assertEqual(self.panel.scheduler.load()['last_status'], 'cancelled')
        self.panel.tick(); self.assertFalse(self.window.jobs.active)

    def test_ui_can_disable_with_unchanged_unavailable_folder(self):
        from quantlab.desktop_runtime import RuntimeSafetyError
        old_directory = self.panel.directory.text()
        self.panel.enabled.setChecked(False)
        with patch.object(self.panel.scheduler, 'destination_directory', side_effect=RuntimeSafetyError('offline')) as check:
            self.panel.save()
            check.assert_not_called()
        self.assertFalse(self.panel.paused)
        settings = self.panel.scheduler.load()
        self.assertFalse(settings['enabled'])
        self.assertEqual(settings['directory'], old_directory)
        self.assertIn('已關閉', self.panel.status.text())

    def test_error_visible_paused_until_settings_saved(self):
        self.panel.directory.setText(str(self.window.paths.state)); self.panel.save()
        self.assertTrue(self.panel.paused)
        self.assertIn('設定未保存', self.panel.status.text())
        self.panel.tick(); self.assertFalse(self.window.jobs.active)
        self.panel.directory.setText(str(Path(self.tmp.name)/'archives')); self.panel.save()
        self.assertFalse(self.panel.paused)


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt required')
class IntegratedAutomaticBackupTests(unittest.TestCase):
    def test_main_window_defers_all_real_managers_then_archives(self):
        from PySide6.QtWidgets import QApplication
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
        from desktop_ui import MainWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths(Path(temp)/'workspace').ensure()
            jobs = JobManager(paths)
            window = MainWindow(paths, jobs, SettingsStore(paths.state/'settings.json'), BackupManager(paths, jobs))
            try:
                panel = window.automatic_backup_panel
                panel.timer.stop(); window.local_ai_panel.timer.stop(); window.timer.stop()
                panel.enabled.setChecked(True); panel.directory.setText(str(Path(temp)/'archives')); panel.save()
                for manager in (jobs, window.local_ai_panel.server, window.local_ai_panel.task):
                    manager.start('ui_demo', {})
                    panel.tick()
                    self.assertIsNone(panel.scheduler.load()['last_attempt_day'])
                    self.assertIsNone(panel.archive)
                    manager.cancel(); manager.poll()
                panel.tick()
                self.assertTrue(jobs.active)
                self.assertTrue(window.cancel_button.isEnabled())
                deadline = time.monotonic()+20
                while jobs.active and time.monotonic() < deadline:
                    window.poll_jobs(); app.processEvents(); time.sleep(.01)
                window.poll_jobs()
                self.assertFalse(jobs.active)
                self.assertEqual(panel.scheduler.load()['last_status'], 'success')
                self.assertIsNone(panel.archive)
            finally:
                jobs.close(); window.close(); app.processEvents()


if __name__ == '__main__': unittest.main()
