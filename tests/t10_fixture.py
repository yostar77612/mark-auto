"""One confined window per test class, without workers, network or real profiles."""

import os
import tempfile
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tests.test_t9_onboarding import sandbox_ui


class WindowFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from desktop_app.shell.main_window import MainWindow
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore

        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)
        cls.folder = tempfile.TemporaryDirectory(prefix='t10-keyboard-')
        cls.addClassCleanup(cls.folder.cleanup)
        paths = AppPaths(Path(cls.folder.name) / 'workspace').ensure()
        cls.jobs = JobManager(paths)
        cls.addClassCleanup(cls.jobs.close)
        cls.window = MainWindow(paths, cls.jobs, SettingsStore(paths.state / 'settings.json'))
        cls.addClassCleanup(cls.window.deleteLater)
        cls.addClassCleanup(cls.window.close)
        for timer in cls.window.findChildren(QTimer):
            timer.stop()
        cls.window.show()
        cls.settle()

    @classmethod
    def settle(cls):
        for _ in range(4):
            cls.app.processEvents()
