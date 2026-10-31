"""Offline preview and command-palette boundaries using actual desktop widgets."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from desktop_app.shell.palette_commands import page_index
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError
from quantlab.research_core.application.job_manager import JobManager
from tools.ui_redesign_preview import build_window, isolate


class PreviewBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='rp-')
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.root = Path(self.directory.name)
        isolate(self.root)
        self.window, self.jobs = build_window(self.root, populated=False)
        self.addCleanup(self.jobs.close)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()

    def test_profile_workspace_and_credentials_paths_stay_in_the_preview(self):
        for name, folder in (('LOCALAPPDATA', 'local'), ('APPDATA', 'roaming'), ('TEMP', 'temp'), ('TMP', 'temp')):
            self.assertEqual(Path(os.environ[name]), self.root / folder)
        self.assertEqual(self.window.paths.root, self.root / 'workspace')
        self.assertTrue(self.window.paths.credentials.is_relative_to(self.root))
        self.assertEqual(Path(os.environ['MARKAUTO_WORKSPACE']), self.window.paths.root)
        self.assertFalse((self.window.root / 'dataset.json').exists())

    def test_preview_rejects_network_jobs_before_creating_a_worker(self):
        with patch.object(JobManager, 'start') as start:
            for operation, payload in (
                ('ui_chatgpt_auth', {}),
                ('ui_refresh', {'network_opt_in': True}),
                ('ui_idea_research', {}),
                ('ui_analysis_run', {}),
                ('ui_campaign', {'provider': {'mode': 'chatgpt_plan'}}),
                ('ui_market_refresh', {'network_opt_in': True}),
            ):
                with self.subTest(operation=operation), self.assertRaises(ValidationError):
                    self.jobs.start(operation, payload)
            start.assert_not_called()

    def test_preview_update_button_and_direct_handler_never_create_a_thread_or_request(self):
        panel = self.window.settings_page.maintenance_panel
        release = self.window.findChild(QPushButton, 'open_releases')
        self.assertFalse(panel.update_button.isEnabled())
        self.assertFalse(release.isEnabled())
        self.assertEqual(panel.update_button.toolTip(), ui_text('redesign.preview.network_disabled'))
        self.assertEqual(release.toolTip(), ui_text('redesign.preview.network_disabled'))
        with (
            patch('desktop_app.features.settings.maintenance.Thread') as thread,
            patch('desktop_app.features.settings.maintenance.check_for_update') as fetch,
            patch('socket.create_connection') as connect,
            patch('urllib.request.OpenerDirector.open') as request,
        ):
            panel.update_button.click()
            panel.check_updates()
            panel.update_button.setEnabled(True)
            panel.check_updates()
            self.app.processEvents()
            thread.assert_not_called()
            fetch.assert_not_called()
            connect.assert_not_called()
            request.assert_not_called()

    def test_import_command_reveals_the_local_source_then_focuses_the_visible_action(self):
        window = self.window
        window.data_page.sources.setCurrentIndex(3)
        window.navigation.setCurrentRow(page_index(window, 'strategy'))
        window.palette_shortcut.activated.emit()
        QTest.keyClicks(window.command_palette.filter, 'import data')
        self.assertEqual(window.command_palette.results.count(), 1)
        QTest.keyClick(window.command_palette.filter, Qt.Key.Key_Return)
        self.app.processEvents()
        button = window.findChild(QPushButton, 'import_data')
        self.assertEqual(window.navigation.currentRow(), page_index(window, 'data'))
        self.assertEqual(window.data_page.sources.currentIndex(), 0)
        self.assertTrue(button.isVisibleTo(window.data_page))
        self.assertIs(window.focusWidget(), button)
        # The offscreen platform leaves the closed popup as the active window.
        window.activateWindow()
        self.app.processEvents()
        self.assertTrue(button.hasFocus())
        self.assertFalse(self.jobs.active)

    def test_backtest_command_reveals_loaded_result_setup_without_starting_a_job(self):
        self.window.close()
        window, jobs = build_window(self.root / 'loaded', populated=True)
        self.addCleanup(jobs.close)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.backtest_page.setup_toggle.isChecked())
        window.palette_shortcut.activated.emit()
        QTest.keyClicks(window.command_palette.filter, 'start backtest')
        self.assertEqual(window.command_palette.results.count(), 1)
        QTest.keyClick(window.command_palette.filter, Qt.Key.Key_Return)
        self.app.processEvents()
        button = window.backtest_page.run_button
        self.assertEqual(window.navigation.currentRow(), page_index(window, 'backtest'))
        self.assertTrue(window.backtest_page.setup_toggle.isChecked())
        self.assertTrue(button.isVisibleTo(window.backtest_page))
        self.assertIs(window.focusWidget(), button)
        self.assertFalse(jobs.active)


if __name__ == '__main__':
    unittest.main()
