"""M4a explicit consent, presentation and close-handoff guards."""

from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from desktop_app.features.settings.maintenance import DownloadResult, MaintenancePanel
from desktop_app.strings.catalog import ui_text
from quantlab.update_check import ReleaseInfo, UpdateResult


class UpdatePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.release = ReleaseInfo(
            '9.0',
            'a' * 40,
            datetime(2026, 11, 2, 6, tzinfo=timezone.utc),
            'https://github.com/yostar77612/mark-auto/releases/download/desktop-v9/MarkAuto.exe',
            'b' * 64,
        )
        self.panel = MaintenancePanel()
        self.addCleanup(self.panel.deleteLater)
        self.can = Mock(return_value=True)
        self.queued = Mock()
        self.cancel = Mock()
        for key, value in [
            ('maintenanceCanInstall', self.can),
            ('maintenanceDownload', Mock()),
            ('maintenanceQueueInstall', self.queued),
            ('maintenanceCancelInstall', self.cancel),
        ]:
            self.app.setProperty(key, value)
            self.addCleanup(self.app.setProperty, key, None)
        self.panel.results.put(UpdateResult('update_available', 'update_available', '9.0', self.release))
        self.panel.poll_update()

    def complete(self):
        scope = TemporaryDirectory(prefix='m4a-ui-')
        self.addCleanup(scope.cleanup)
        directory = Path(scope.name) / 'download'
        directory.mkdir()
        path = directory / 'MarkAuto-setup.exe'
        path.write_bytes(b'fake-complete')
        self.panel.downloads.put(DownloadResult(path))
        return path

    def test_release_metadata_is_plain_text_taipei_and_primary(self):
        self.assertEqual(self.panel.latest_label.text(), ui_text('update.latest').format('9.0'))
        self.assertIn('2026/11/02 14:00', self.panel.published_label.text())
        self.assertEqual(self.panel.install_button.property('role'), 'primary')
        self.assertFalse(self.panel.install_button.isHidden())
        self.panel.results.put(UpdateResult('up_to_date', 'up_to_date', '9.0', self.release))
        self.panel.poll_update()
        self.assertTrue(self.panel.install_button.isHidden())
        self.assertIn(ui_text('maintenance.current').format('9.0'), self.panel.status.text())

    def test_cancel_default_names_source_version_digest_and_stop_notice(self):
        with (
            patch('desktop_app.features.settings.maintenance.QMessageBox.question', return_value=QMessageBox.Cancel) as question,
            patch('desktop_app.features.settings.maintenance.Thread') as thread,
        ):
            self.panel.install_update()
        args = question.call_args.args
        self.assertEqual(args[-1], QMessageBox.Cancel)
        for required in (self.release.installer_url, '9.0', self.release.installer_sha256[:12], '關閉本程式', '自動交易會停止', '手動恢復', '尚未簽章'):
            self.assertIn(required, args[2])
        self.assertNotIn(self.release.installer_sha256, args[2])
        thread.assert_not_called()
        self.queued.assert_not_called()

    def test_only_yes_starts_download_and_disables_duplicate_action(self):
        with (
            patch('desktop_app.features.settings.maintenance.QMessageBox.question', return_value=QMessageBox.Yes),
            patch('desktop_app.features.settings.maintenance.Thread') as thread,
        ):
            self.panel.install_update()
            self.panel.install_update()
            thread.return_value.start.assert_called_once()
        self.assertFalse(self.panel.update_button.isEnabled())
        self.assertFalse(self.panel.install_button.isEnabled())
        self.panel.cancel_button.click()
        self.assertTrue(self.panel.download_cancel.is_set())
        self.panel.download_timer.stop()

    def test_source_run_and_missing_metadata_never_download(self):
        with patch('desktop_app.features.settings.maintenance.QMessageBox.question') as question:
            self.can.return_value = False
            self.panel.install_update()
            self.assertIn('update_not_installed', self.panel.status.text())
            self.panel.release = None
            self.panel.install_update()
            self.assertIn('update_metadata_missing', self.panel.status.text())
            question.assert_not_called()
        self.queued.assert_not_called()

    def test_preview_never_confirms_or_installs(self):
        self.panel.setProperty('offlinePreview', True)
        with patch('desktop_app.features.settings.maintenance.QMessageBox.question') as question:
            self.panel.install_update()
            question.assert_not_called()
        path = self.complete()
        self.panel.poll_download()
        self.assertFalse(path.exists())
        self.queued.assert_not_called()

    def test_download_errors_show_specific_error_and_never_close(self):
        for code in ('update_hash_mismatch', 'update_source_rejected', 'update_download_timeout', 'update_download_failed', 'update_too_large'):
            with self.subTest(code=code), patch.object(self.panel, 'close') as close:
                self.panel.downloads.put(DownloadResult(error_code=code))
                self.panel.poll_download()
                self.assertIn(code, self.panel.status.text())
                close.assert_not_called()
                self.queued.assert_not_called()

    def test_late_cancel_deletes_verified_file_and_never_queues(self):
        path = self.complete()
        self.panel.download_cancel.set()
        self.panel.poll_download()
        self.assertFalse(path.parent.exists())
        self.queued.assert_not_called()

    def test_refused_normal_close_cancels_pending_install(self):
        path = self.complete()
        with patch.object(self.panel, 'close', return_value=False) as close:
            self.panel.poll_download()
        self.assertEqual(self.queued.call_args.args[:2], (path, self.release.installer_sha256))
        self.assertIn('{0}', self.queued.call_args.args[2]['update_installer_failed'])
        close.assert_called_once()
        self.cancel.assert_called_once()
        self.assertIn('update_shutdown_failed', self.panel.status.text())

    def test_accepted_close_leaves_install_owned_by_runtime(self):
        self.complete()
        with patch.object(self.panel, 'close', return_value=True) as close:
            self.panel.poll_download()
        self.queued.assert_called_once()
        close.assert_called_once()
        self.cancel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
