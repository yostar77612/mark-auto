"""Cheap header contracts: fixed clocks, existing state, no shown windows."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget
from desktop_app.shell.app_header import AppHeader
from desktop_app.components.job_progress import JobFeedback, JobProgress
from desktop_app.components.privacy import enabled
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.theme import apply_theme, install_appearance_controls, load_appearance
from desktop_app.shell.main_window import MainWindow, paper_risk_limits
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore


NOW = datetime(2026, 10, 20, 3, 4, 5, tzinfo=timezone.utc)


class HeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def header(self, host=None, **kwargs):
        header = AppHeader(host or SimpleNamespace(), clock=lambda: NOW, **kwargs)
        self.addCleanup(header.deleteLater)
        self.addCleanup(header.close)
        return header

    def test_bare_host_fixed_clock_and_close(self):
        header = self.header()
        header.refresh()
        self.assertEqual(header.time.text(), '03:04:05')
        self.assertEqual(header.source.text(), ui_text('header.no_data'))
        self.assertEqual(header.job.text(), ui_text('header.idle'))
        self.assertTrue(header.timer.isActive())
        header.close()
        self.assertFalse(header.timer.isActive())

    def test_rejected_host_close_preserves_header_timer_state(self):
        class RefusingHost(QWidget):
            def closeEvent(self, event):
                event.ignore()

        for initially_active in (True, False):
            with self.subTest(initially_active=initially_active):
                host = RefusingHost()
                self.addCleanup(host.deleteLater)
                self.addCleanup(host.hide)
                layout = QVBoxLayout(host)
                header = self.header(host, parent=host)
                layout.addWidget(header)
                host.show()
                self.app.processEvents()
                if not initially_active:
                    header.timer.stop()
                self.assertFalse(host.close())
                self.app.processEvents()
                self.assertTrue(host.isVisible())
                self.assertEqual(header.timer.isActive(), initially_active)
                if initially_active:
                    header.clock = lambda: NOW + timedelta(seconds=3)
                    header.timer.timeout.emit()
                    self.assertEqual(header.time.text(), '03:04:08')

    def test_existing_quote_state_boundary_cache_future_and_dataset(self):
        limit = paper_risk_limits().max_quote_age_seconds
        provenance = SimpleNamespace(received_at=NOW - timedelta(seconds=limit), as_of='2026-10-20', attribution='official')
        item = SimpleNamespace(provenance=provenance, instrument=SimpleNamespace(exchange='TAIFEX'))
        market = SimpleNamespace(_quote_series={'test': item}, _quote_stale=False)
        host = SimpleNamespace(market=market)
        header = self.header(host, quote_age_seconds=limit)
        self.assertIn(ui_text('header.snapshot'), header.source.text())
        self.assertIn('TAIFEX', header.source.text())
        provenance.received_at -= timedelta(microseconds=1)
        header.refresh()
        self.assertIn(ui_text('header.stale'), header.source.text())
        provenance.received_at = NOW
        market._quote_stale = True
        header.refresh()
        self.assertIn(ui_text('header.stale'), header.source.text())
        market._quote_stale = False
        provenance.received_at = NOW + timedelta(seconds=1)
        header.refresh()
        self.assertIn(ui_text('header.stale'), header.source.text())
        host.market = None
        host._dataset_ready = True
        header.refresh()
        self.assertEqual(header.source.text(), ui_text('header.dataset'))

    def test_job_projection_without_second_state(self):
        progress = JobProgress(lambda: None)
        self.addCleanup(progress.deleteLater)
        feedback = JobFeedback(progress)
        notice = QLabel()
        self.addCleanup(notice.deleteLater)
        host = SimpleNamespace(job_progress=progress, job_feedback=feedback, notification=notice, last_operation=None)
        header = self.header(host)
        self.assertEqual(header.job.text(), ui_text('header.idle'))
        feedback.begin('one')
        header.refresh()
        self.assertEqual(header.job.text(), ui_text('header.running'))
        feedback.accept(host, {'job_id': 'one', 'type': 'completed'})
        notice.setProperty('status', 'neutral')
        header.refresh()
        self.assertEqual(header.job.text(), ui_text('header.done'))
        feedback.begin('two')
        feedback.accept(host, {'job_id': 'two', 'type': 'failed'})
        notice.setProperty('status', 'danger')
        header.refresh()
        self.assertEqual(header.job.text(), ui_text('header.failed'))
        self.assertFalse(hasattr(header, 'job_state'))

    def test_shared_preferences_compact_height_names_and_safety(self):
        with disposable_directory() as folder:
            host = QWidget()
            self.addCleanup(host.deleteLater)
            self.addCleanup(host.close)
            host.settings = SettingsStore(Path(folder) / 'settings.json')
            outer = QVBoxLayout(host)
            header = self.header(host, parent=host)
            outer.addWidget(header)
            details = QWidget(host)
            outer.addWidget(details)
            controls = install_appearance_controls(details, QVBoxLayout(details), host.settings)
            header.bind_controls()
            self.assertIs(header.theme, controls[0])
            host.resize(1366, 768)
            for theme in ('dark', 'light'):
                header.theme.setCurrentIndex(header.theme.findData(theme))
                apply_theme(host)
                host.ensurePolished()
                outer.activate()
                header.refresh()
                self.assertEqual(load_appearance(host.settings)[0], theme)
                self.assertLessEqual(header.sizeHint().height(), 48)
                self.assertLessEqual(header.maximumHeight(), 48)
                self.assertLessEqual(sum(label.sizeHint().width() for label in header.findChildren(QLabel)), 1366)
                self.assertLessEqual(header.sizeHint().width(), 1366 - 22)
                self.assertEqual(header.badge.text(), ui_text('header.live_disabled'))
                self.assertEqual(header.badge.text(), ui_text('ui.init.research_mode_banner'))
                self.assertFalse(header.badge.isHidden())
            header.privacy_toggle.setChecked(True)
            self.assertTrue(host.privacy.enabled)
            self.assertTrue(enabled(header))
            self.assertTrue(host.settings.load()['privacy_mode'])
            host.privacy.set_enabled(False)
            header.refresh()
            self.assertFalse(header.privacy_toggle.isChecked())
            self.assertEqual(header.findChildren(QPushButton), [header.connection])
            self.assertTrue(header.time.isHidden())
            self.assertIs(header.theme.parentWidget(), details)
            self.assertEqual({x.objectName() for x in header.findChildren(QCheckBox)}, {'research_mode_status', 'privacy_toggle'})
            self.assertEqual(host.privacy.notice.text(), ui_text('privacy.exports_raw'))
            for control in (header.privacy_toggle, header.disclosure, header.theme):
                self.assertTrue(control.accessibleName())
            for control in (header.privacy_toggle, header.disclosure, header.theme, header.connection):
                self.assertTrue(control.focusPolicy() & Qt.FocusPolicy.TabFocus)
            host.close()
            self.assertFalse(header.timer.isActive())

    def test_real_mount_preserves_disclosure_and_top_position(self):
        with disposable_directory() as folder, sandbox_ui(), patch('desktop_app.shell.app_header.datetime', wraps=datetime) as fake_datetime:
            fake_datetime.now.return_value = NOW
            paths = AppPaths(Path(folder) / 'workspace').ensure()
            jobs = JobManager(paths)
            self.addCleanup(jobs.close)
            window = MainWindow(paths, jobs)
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                header = window.app_header
                self.assertIs(window.centralWidget().layout().itemAt(0).widget(), header)
                self.assertIs(window.findChild(QCheckBox, 'research_mode_status'), header.disclosure)
                header.disclosure.setChecked(True)
                self.assertFalse(header.explanation.isHidden())
                self.assertEqual(header.explanation.text(), ui_text('ui.init.research_only_disclaimer'))
                self.assertEqual(window.status.text(), ui_text('ui.init.ready'))
                self.assertIs(window.status.parentWidget(), window.centralWidget())
                self.assertTrue(window.settings_page.isAncestorOf(header.privacy_toggle))
                self.assertTrue(window.settings_page.isAncestorOf(header.theme))
                self.assertTrue(window.settings_page.isAncestorOf(window.privacy.notice))
                self.assertEqual(window.privacy.notice.text(), ui_text('privacy.exports_raw'))
                self.assertTrue(header.time.isHidden())
                header.connection.click()
                self.assertTrue(window.settings_page.connection_toggle.isChecked())
                self.assertLessEqual(header.sizeHint().height(), 48)
                expected = json.loads((Path(__file__).parent / 'fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
                self.assertEqual(sorted({w.objectName() for w in window.findChildren(QWidget) if w.objectName()}), expected)
                self.assertFalse(any(label.wordWrap() for label in header.findChildren(QLabel) if label.isVisibleTo(header)))
            finally:
                window.close()
                window.deleteLater()
