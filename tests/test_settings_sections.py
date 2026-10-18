"""T10 settings disclosures use a confined, credential-free desktop fixture."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QToolButton, QGroupBox
from desktop_strings import ui_text
from tests.test_t9_onboarding import sandbox_ui


class SettingsSectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from desktop_ui import MainWindow
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
        self.context = sandbox_ui(); self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory(prefix='t10-settings-')
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths); self.addCleanup(self.jobs.close)
        settings = SettingsStore(self.paths.state / 'settings.json')
        self.window = MainWindow(self.paths, self.jobs, settings)
        for timer in self.window.findChildren(QTimer): timer.stop()
        self.addCleanup(self.window.deleteLater); self.addCleanup(self.window.close)
        self.window.navigation.setCurrentRow(6)
        self.window.show(); self.app.processEvents()
        self.page = self.window.settings_page

    def test_sections_order_paths_and_button_budget(self):
        page = self.page
        page.backup_path.setText(str(Path(self.temp.name) / 'private-backup.zip'))
        page.automatic_backup_panel.directory.setText(str(Path(self.temp.name) / 'private-backups'))
        self.assertEqual([group.title() for group in page.settings_sections],
                         [ui_text('settings.' + key) for key in ('general', 'connection', 'backup', 'about')])
        top_groups = [page.layout().itemAt(i).widget() for i in range(page.layout().count())]
        self.assertEqual([group for group in top_groups if isinstance(group, QGroupBox)], page.settings_sections)
        visible = [widget for widget in page.findChildren(QLabel) + page.findChildren(QLineEdit)
                   if widget.isVisibleTo(page)]
        for widget in visible:
            self.assertNotRegex(widget.text(), r'[A-Za-z]:[\\/]|\\\\')
        buttons = [button for button in page.findChildren(QPushButton) + page.findChildren(QToolButton)
                   if button.isVisibleTo(page)]
        self.assertLessEqual(len(buttons), 8)
        self.assertTrue(page.paths_advanced.isHidden())
        self.assertTrue(page.backup_advanced.isHidden())
        page.paths_toggle.setChecked(True); page.backup_toggle.setChecked(True)
        self.assertTrue(page.workspace_path.isVisibleTo(page))
        self.assertTrue(page.backup_path.isVisibleTo(page))
        self.assertTrue(page.automatic_backup_panel.directory.isVisibleTo(page))
        self.assertEqual(page.workspace_path.text(), str(self.paths.root))
        labels = '\n'.join(label.text() for label in page.paths_advanced.findChildren(QLabel))
        self.assertIn(str(self.paths.logs), labels)
        with patch('desktop_pages.settings_layout.QDesktopServices.openUrl', return_value=True) as opened:
            button = next(button for button in page.findChildren(QPushButton)
                          if button.text() == ui_text('settings.open_workspace'))
            button.click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.paths.root)

    def test_chatgpt_single_official_home_and_navigation(self):
        from desktop_chatgpt_ui import ChatGPTConnectionPanel
        panels = self.window.findChildren(ChatGPTConnectionPanel)
        self.assertEqual(panels, [self.window.chatgpt_panel])
        self.assertTrue(self.page.settings_sections[1].isAncestorOf(panels[0]))
        self.assertFalse(panels[0].isVisibleTo(self.page))
        with patch.object(panels[0].primary_sign_in, 'click') as clicked:
            self.window.strategy_page.chatgpt_sign_in_entry.click()
            self.assertTrue(panels[0].isVisibleTo(self.page))
            self.assertEqual(self.window.navigation.currentRow(), 6)
            clicked.assert_called_once()
        self.window.chatgpt_controller.message = ui_text('logs.event.error')
        self.window.chatgpt_controller.changed.emit()
        self.assertEqual(self.window.strategy_page.connection_status.text(), ui_text('logs.event.error'))

    def test_log_controls_read_filter_and_export_existing_reader(self):
        from quantlab.desktop_runtime import RedactedEventLog
        log = RedactedEventLog(self.paths.logs / 'desktop-events.jsonl')
        with patch('quantlab.desktop_runtime.time.time', return_value=1704067200):
            log.append('ui_demo', 'result'); log.append('ui_import', 'error')
        self.window.findChild(QPushButton, 'read_logs').click()
        self.assertEqual(self.page.log_view.rowCount(), 2)
        self.page.errors_only.setChecked(True)
        self.assertEqual(self.page.log_view.rowCount(), 1)
        destination = Path(self.temp.name) / 'report.csv'
        with patch('desktop_pages.log_table.choose_log_export', return_value=str(destination)):
            next(button for button in self.page.findChildren(QPushButton)
                 if button.text() == ui_text('logs.export')).click()
        self.assertIn(ui_text('logs.operation.ui_import'), destination.read_text(encoding='utf-8-sig'))
        self.assertNotIn(ui_text('logs.operation.ui_demo'), destination.read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
