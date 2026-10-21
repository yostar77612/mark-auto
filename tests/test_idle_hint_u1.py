"""Idle/cancel presentation evidence claims only not broken, without shown windows."""

from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from desktop_pages.app_header import AppHeader
from desktop_pages.command_palette import CommandPalette
from desktop_pages.job_progress import JobFeedback, JobProgress
from desktop_strings import ui_text
from desktop_ui import MainWindow
from desktop_ui_polish import DisabledHint
from quantlab.desktop_runtime import AppPaths, JobManager
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui


class IdleHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bare_host_and_cancel_hint_do_not_require_job_attributes(self):
        host = SimpleNamespace()
        header = AppHeader(host)
        button = QPushButton()
        label = QLabel()
        try:
            button.setObjectName('cancel_job')
            button.setEnabled(False)
            hint = DisabledHint(button, label, ui_text('ui_polish.install_polish.cancellable_job_prerequisite'))
            self.assertEqual(header.job.text(), ui_text('header.idle'))
            self.assertEqual(label.text(), ui_text('job.idle_hint'))
            self.assertEqual(button.toolTip(), label.text())
            hint.update()
            self.assertFalse(hasattr(host, 'job_progress'))
            self.assertFalse(hasattr(host, 'job_feedback'))
        finally:
            header.close()
            button.close()
            label.close()

    def test_running_terminal_and_cancel_transitions(self):
        host = QWidget()
        cancel = Mock()
        progress = JobProgress(cancel, host)
        host.job_progress = progress
        host.job_feedback = JobFeedback(progress)
        host.notification = QLabel(host)
        host.last_operation = None
        header = AppHeader(host, parent=host)
        label = QLabel(progress)
        hint = DisabledHint(progress.cancel_button, label, ui_text('job.idle_hint'))
        try:
            self.assertFalse(progress.cancel_button.isEnabled())
            for terminal, expected in (('completed', 'header.done'), ('failed', 'header.failed')):
                host.job_feedback.begin(terminal)
                host.job_feedback.accept(host, {'job_id': terminal, 'type': 'progress', 'stage': 'prepare_operation', 'progress': 37})
                header.refresh()
                self.assertEqual(header.job.text(), ui_text('header.running'))
                self.assertEqual(progress.stage.text(), ui_text('job.stage.prepare_operation'))
                self.assertEqual(progress.bar.value(), 37)
                self.assertTrue(progress.cancel_button.isEnabled())
                self.assertEqual(label.text(), '')
                progress.cancel_button.click()
                hint.update()
                self.assertFalse(progress.cancel_button.isEnabled())
                self.assertEqual(label.text(), ui_text('job.cancel_notice'))
                progress.cancel_button.click()
                self.assertEqual(cancel.call_count, 1 if terminal == 'completed' else 2)
                host.job_feedback.accept(host, {'job_id': terminal, 'type': terminal, 'error_code': 'operation_failed'})
                host.notification.setProperty('status', 'danger' if terminal == 'failed' else 'neutral')
                header.refresh()
                hint.update()
                self.assertEqual(header.job.text(), ui_text(expected))
                self.assertEqual(label.text(), ui_text('job.idle_hint'))
                self.assertFalse(progress.cancel_button.isEnabled())
        finally:
            header.close()
            host.close()

    def test_other_buttons_keep_prerequisite_wording(self):
        window = QWidget()
        window.jobs = SimpleNamespace(active=False)
        button = QPushButton(window)
        label = QLabel(window)
        button.setObjectName('run_backtest')
        button.setEnabled(False)
        prerequisite = ui_text('ui_polish.install_polish.import_prerequisite')
        hint = DisabledHint(button, label, prerequisite)
        try:
            self.assertEqual(label.text(), ui_text('ui_polish.update.prerequisite_required').format(prerequisite))
            window.jobs.active = True
            hint.update()
            self.assertEqual(label.text(), ui_text('ui_polish.update.prerequisite_required').format(ui_text('ui_polish.update.job_busy')))
        finally:
            window.close()

    def test_main_window_idle_labels_accessibility_palette_and_privacy(self):
        with disposable_directory() as folder, sandbox_ui():
            paths = AppPaths(Path(folder) / 'workspace', Path(folder) / 'bootstrap').ensure()
            jobs = JobManager(paths)
            window = MainWindow(paths, jobs)
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                hint = next(hint for hint in window._disabled_hints if hint.button.objectName() == 'cancel_job')
                for private in (False, True):
                    window.privacy.set_enabled(private)
                    window.app_header.refresh()
                    hint.update()
                    self.assertEqual(hint.prerequisite, ui_text('job.idle_hint'))
                    self.assertEqual(hint.label.text(), ui_text('job.idle_hint'))
                    self.assertEqual(window.app_header.job.text(), ui_text('header.idle'))
                    self.assertEqual(window.status.text(), ui_text('ui.init.ready'))
                    self.assertFalse(hint.button.isEnabled())
                    self.assertTrue(hint.button.accessibleName())
                    self.assertTrue(hint.button.toolTip())
                    labels = [*window.app_header.findChildren(QLabel), window.status, hint.label]
                    text = '\n'.join(label.text() for label in labels if not label.isHidden())
                    self.assertIn(ui_text('ui.init.ready'), text)
                    prefix = ui_text('ui_polish.update.prerequisite_required').split('{0}')[0]
                    self.assertNotIn(prefix, text)
                    self.assertNotIn(ui_text('ui_polish.install_polish.cancellable_job_prerequisite'), text)
                palette = CommandPalette(window)
                command = next(command for command in palette.commands() if command.id == 'cancel_job')
                self.assertFalse(palette.available(command))
                rows = [palette.results.item(i) for i in range(palette.results.count())]
                row = next(row for row in rows if row.data(Qt.ItemDataRole.UserRole).id == 'cancel_job')
                self.assertEqual(row.text(), ui_text('palette.unavailable').format(ui_text('keyboard.cancel')))
                palette.close()
            finally:
                window.close()
                jobs.close()
