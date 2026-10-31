"""One confined window per test class, without workers, network or real profiles."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

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
        from desktop_app.shell.window import MainWindow
        from quantlab.research_core.adapters.workspace_store import AppPaths
        from desktop_app.research_bootstrap import create_job_manager
        from quantlab.research_core.adapters.settings_store import SettingsStore

        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)
        cls.folder = tempfile.TemporaryDirectory(prefix='t10-keyboard-')
        cls.addClassCleanup(cls.folder.cleanup)
        paths = AppPaths(Path(cls.folder.name) / 'workspace').ensure()
        cls.jobs = create_job_manager(paths)
        cls.addClassCleanup(cls.jobs.close)
        cls.window = MainWindow(paths, cls.jobs, SettingsStore(paths.state / 'settings.json'), services=_c_create_ui_services(_c_create_operation_ports()))
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
