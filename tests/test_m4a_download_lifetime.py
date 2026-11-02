"""Deterministic download ownership checks while its receiving window closes."""

from datetime import datetime, timezone
import os
from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
import shiboken6

from desktop_app.features.settings.maintenance import (
    DownloadResult,
    MaintenancePanel,
    _cancel_download,
    _download_in_background,
)
from quantlab.update_check import ReleaseInfo


class DownloadLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scope = TemporaryDirectory(prefix='m4a-lifetime-')
        self.addCleanup(self.scope.cleanup)
        self.root = Path(self.scope.name)
        directory = self.root / 'download'
        directory.mkdir()
        self.path = directory / 'MarkAuto-setup.exe'
        self.path.write_bytes(b'complete verified download')
        self.cancel = Event()
        self.queue = SimpleQueue()
        self.lock = Lock()

    def test_close_during_download_cleans_file_before_worker_exits(self):
        ready, resume = Event(), Event()

        def download(release, cancel):
            ready.set()
            if not resume.wait(2):
                raise AssertionError('fixture was not resumed')
            return self.path

        worker = Thread(target=_download_in_background, args=(self.queue, None, self.cancel, download, self.lock), daemon=False)
        worker.start()
        self.assertTrue(ready.wait(2))
        _cancel_download(self.queue, self.cancel, self.lock)
        resume.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(self.queue.get_nowait().error_code, 'update_download_cancelled')

    def test_close_after_download_publication_drains_completed_file(self):
        _download_in_background(self.queue, None, self.cancel, lambda release, cancel: self.path, self.lock)
        _cancel_download(self.queue, self.cancel, self.lock)
        self.assertFalse(self.path.parent.exists())
        self.assertTrue(self.queue.empty())

    def test_close_cannot_race_between_worker_cancel_check_and_publication(self):
        publishing, publish, closing = Event(), Event(), Event()

        class PausedQueue(SimpleQueue):
            def put(inner_self, result):
                if result.path is not None:
                    publishing.set()
                    if not publish.wait(2):
                        raise AssertionError('fixture publication was not resumed')
                super().put(result)

        queue = PausedQueue()
        worker = Thread(target=_download_in_background, args=(queue, None, self.cancel, lambda release, cancel: self.path, self.lock))
        worker.start()
        self.assertTrue(publishing.wait(2))

        def close_receiver():
            closing.set()
            _cancel_download(queue, self.cancel, self.lock)

        closer = Thread(target=close_receiver)
        closer.start()
        self.assertTrue(closing.wait(2))
        publish.set()
        worker.join(2)
        closer.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertFalse(self.path.parent.exists())
        self.assertTrue(queue.empty())

    def test_panel_destruction_cleans_a_success_not_yet_polled(self):
        panel = MaintenancePanel()
        cancel = panel.download_cancel
        panel.downloads.put(DownloadResult(self.path))
        shiboken6.delete(panel)
        self.assertTrue(cancel.is_set())
        self.assertFalse(self.path.parent.exists())

    def test_application_quit_cleans_a_success_not_yet_polled(self):
        panel = MaintenancePanel()
        self.addCleanup(shiboken6.delete, panel)
        panel.downloads.put(DownloadResult(self.path))
        self.app.aboutToQuit.emit()
        self.assertTrue(panel.download_cancel.is_set())
        self.assertFalse(self.path.parent.exists())

    def test_download_worker_keeps_cleanup_alive_after_qt_exit(self):
        panel = MaintenancePanel()
        self.addCleanup(shiboken6.delete, panel)
        panel.release = ReleaseInfo(
            '9.0',
            'a' * 40,
            datetime(2026, 11, 2, tzinfo=timezone.utc),
            'https://github.com/yostar77612/mark-auto/releases/download/test/MarkAuto.exe',
            'b' * 64,
        )
        self.app.setProperty('maintenanceCanInstall', Mock(return_value=True))
        self.app.setProperty('maintenanceDownload', Mock())
        self.addCleanup(self.app.setProperty, 'maintenanceCanInstall', None)
        self.addCleanup(self.app.setProperty, 'maintenanceDownload', None)
        with (
            patch('desktop_app.features.settings.maintenance.QMessageBox.question', return_value=QMessageBox.Yes),
            patch('desktop_app.features.settings.maintenance.Thread') as thread,
        ):
            panel.install_update()
        self.assertIs(thread.call_args.kwargs['daemon'], False)
        thread.return_value.start.assert_called_once()
        panel.download_timer.stop()
