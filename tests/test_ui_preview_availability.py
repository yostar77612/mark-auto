"""Offline preview capabilities survive queued readiness and result callbacks."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from desktop_app.features.settings.maintenance import MaintenancePanel
from desktop_app.features.settings.settings import SettingsPage
from desktop_app.strings.catalog import ui_text
from quantlab.update_check import UpdateResult
from tools.ui_redesign_preview import build_window, isolate


_APP = QApplication.instance() or QApplication([])


class PreviewAvailabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='preview-availability-')
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {})
        environment.start()
        self.addCleanup(environment.stop)
        self.root = Path(directory.name)
        isolate(self.root)
        self.window, self.jobs = build_window(self.root, populated=False)
        self.addCleanup(self.jobs.close)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def test_queued_readiness_and_results_cannot_reenable_preview_network_actions(self):
        panel = self.window.settings_page.maintenance_panel
        release = self.window.findChild(QPushButton, 'open_releases')
        with (
            patch('desktop_app.features.settings.maintenance.Thread') as thread,
            patch('desktop_app.features.settings.maintenance.check_for_update') as fetch,
            patch('desktop_app.features.settings.settings.QDesktopServices.openUrl') as browser,
            patch('socket.create_connection') as connect,
            patch('urllib.request.OpenerDirector.open') as request,
        ):
            QTimer.singleShot(0, self.window, lambda: self.window._busy(False))
            _APP.processEvents()
            self.assertFalse(release.isEnabled())
            self.assertFalse(panel.update_button.isEnabled())
            panel.results.put(UpdateResult('up_to_date', '0.2.2'))
            QTimer.singleShot(0, self.window, panel.poll_update)
            _APP.processEvents()
            for button in (release, panel.update_button):
                button.setEnabled(True)
                self.assertFalse(button.isEnabled())
                self.assertEqual(button.toolTip(), ui_text('redesign.preview.network_disabled'))
                button.clicked.emit()
            self.window.settings_page.open_releases()
            panel.check_updates()
            _APP.processEvents()
            for call in (thread, fetch, browser, connect, request):
                call.assert_not_called()

    def test_normal_maintenance_and_release_handlers_retain_explicit_user_actions(self):
        panel = MaintenancePanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.timer.stop)
        with patch('desktop_app.features.settings.maintenance.Thread') as thread:
            panel.check_updates()
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()
        panel.results.put(UpdateResult('up_to_date', '0.2.2'))
        panel.poll_update()
        self.assertTrue(panel.update_button.isEnabled())
        normal_page = QWidget()
        normal_page.status = QLabel()
        self.addCleanup(normal_page.deleteLater)
        with patch('desktop_app.features.settings.settings.QDesktopServices.openUrl', return_value=True) as browser:
            SettingsPage.open_releases(normal_page)
            browser.assert_called_once()


if __name__ == '__main__':
    unittest.main()
