"""Delete only an accepted, quiescent native fixture; preserve unsafe closes."""
import importlib.util
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for native fixture lifetime')
class NativeFixtureCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self, action='accept', jobs=None):
        from PySide6.QtWidgets import QWidget
        from PySide6.QtCore import QTimer
        class Window(QWidget):
            def closeEvent(self, event):
                if action == 'ignore': event.ignore()
                elif action == 'reconcile':
                    jobs.active = True
                    event.ignore()
                else: event.accept()
        window = Window()
        timer = QTimer(window); timer.start(60000)
        window.show(); self.app.processEvents()
        self.addCleanup(self.delete_if_valid, window)
        return window

    def delete_if_valid(self, window):
        from shiboken6 import isValid
        from PySide6.QtCore import QCoreApplication, QEvent
        if isValid(window):
            window.deleteLater()
            QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)

    def clean(self, window, jobs, app=None):
        from tests.test_desktop_ui import NativeDesktopTests
        NativeDesktopTests.cleanup_window(SimpleNamespace(window=window, jobs=jobs, app=app or self.app))

    def test_accepted_inactive_fixture_and_child_timer_deleted_unrelated_window_survives(self):
        from shiboken6 import isValid
        from PySide6.QtCore import QTimer
        window, unrelated = self.window(), self.window()
        child = window.findChild(QTimer)
        jobs = SimpleNamespace(active=False, close=lambda: None)
        self.clean(window, jobs)
        self.assertFalse(isValid(window)); self.assertFalse(isValid(child))
        self.assertTrue(isValid(unrelated)); self.assertTrue(unrelated.isVisible())
        self.assertTrue(unrelated.findChild(QTimer).isActive())

    def test_refused_close_and_started_reconciliation_are_not_deleted(self):
        from shiboken6 import isValid
        for action in ('ignore', 'reconcile'):
            jobs = SimpleNamespace(active=False, close=lambda: None)
            window = self.window(action, jobs)
            self.clean(window, jobs)
            self.assertTrue(isValid(window)); self.assertTrue(window.isVisible())
            self.assertEqual(jobs.active, action == 'reconcile')

    def test_job_activated_during_existing_event_processing_prevents_deletion(self):
        from shiboken6 import isValid
        jobs = SimpleNamespace(active=False, close=lambda: None)
        window = self.window()
        def events():
            self.app.processEvents(); jobs.active = True
        self.clean(window, jobs, SimpleNamespace(processEvents=events))
        self.assertTrue(isValid(window))
        self.assertTrue(jobs.active)

    def test_jobs_close_error_preserves_original_exception_and_window(self):
        from shiboken6 import isValid
        window = self.window()
        failure = RuntimeError('stop not confirmed')
        def close(): raise failure
        jobs = SimpleNamespace(active=True, close=close)
        with self.assertRaises(RuntimeError) as raised: self.clean(window, jobs)
        self.assertIs(raised.exception, failure)
        self.assertTrue(isValid(window)); self.assertTrue(window.isVisible())

    def test_deleted_fixture_status_does_not_lose_cleanup_evidence(self):
        from tests.paper_replay_timeout_diagnostics import job_state, qt_resources
        from PySide6.QtWidgets import QLabel
        window = self.window()
        window.status = QLabel('Working', window)
        jobs = SimpleNamespace(active=False, process=None, _terminal=True,
                               _pipe_eof=False, _deferred=[], _pending=[], close=lambda: None)
        self.clean(window, jobs)
        result = job_state(SimpleNamespace(window=window, jobs=jobs))
        self.assertFalse(result['active'])
        self.assertTrue(result['window_status_unavailable'])
        self.assertIsInstance(qt_resources(self.app)['widgets'], int)

    def test_window_close_error_is_not_converted_into_deletion_or_success(self):
        from unittest.mock import Mock
        failure = RuntimeError('close rejected')
        window = Mock()
        window.close.side_effect = failure
        jobs = SimpleNamespace(active=False, close=lambda: None)
        app = Mock()
        with self.assertRaises(RuntimeError) as raised: self.clean(window, jobs, app)
        self.assertIs(raised.exception, failure)
        window.deleteLater.assert_not_called()
        app.processEvents.assert_not_called()
