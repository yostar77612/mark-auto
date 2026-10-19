"""Cheap display contracts: no shown windows, clocks, work or style switching."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from desktop_pages.async_status import AsyncStatus
from desktop_pages.job_progress import JobProgress, JobFeedback
from desktop_pages.log_table import LogTable
from desktop_pages.maintenance import MaintenancePanel
from desktop_strings import ui_text
from desktop_theme import build_app_stylesheet
from quantlab.errors import ERROR_TABLE
from quantlab.update_check import UpdateResult
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
from desktop_ui import MainWindow
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui


class AsyncStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def widget(self, *args):
        widget = AsyncStatus(*args)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_four_states_and_accessibility_in_both_themes(self):
        for theme in ('dark', 'light'):
            widget = self.widget(SimpleNamespace())
            stylesheet = build_app_stylesheet(theme)
            self.assertNotIn('@', stylesheet)
            widget.setStyleSheet(stylesheet)
            texts = set()
            for state in ('loading', 'empty', 'error', 'stale'):
                widget.set_state(state)
                self.assertEqual(widget.property('state'), state)
                self.assertTrue(widget.accessibleName())
                self.assertTrue(widget.label.accessibleName())
                self.assertTrue(widget.action.accessibleName())
                texts.add(widget.label.text())
            self.assertEqual(len(texts), 4)
            self.assertEqual(widget.findChildren(QTimer), [])
            for invalid in ('idle', '', None, [], 1):
                with self.assertRaises(ValueError):
                    widget.set_state(invalid)

    def test_actions_replace_without_duplicate_connections(self):
        widget = self.widget()
        action, retry, refresh = Mock(), Mock(), Mock()
        for _ in range(3):
            widget.set_state('empty', message=ui_text('onboarding.empty.market'), action_text=ui_text('onboarding.next.market'), action=action)
        self.assertEqual(widget.action.text(), ui_text('onboarding.next.market'))
        widget.action.click()
        action.assert_called_once_with()
        widget.set_state('error', error_code='operation_failed', retry=retry)
        retry.assert_not_called()
        widget.action.click()
        retry.assert_called_once_with()
        widget.set_state('stale', age='37 s', refresh=refresh)
        self.assertEqual(widget.label.text(), ui_text('async.stale_age').format('37 s'))
        widget.action.click()
        refresh.assert_called_once_with()
        action.assert_called_once_with()
        widget.set_state('empty')
        self.assertTrue(widget.action.isHidden())
        widget.action.click()
        refresh.assert_called_once_with()
        widget.set_state('stale')
        self.assertEqual(widget.label.text(), ui_text('async.stale'))

    def test_every_b1_code_and_unknown_exception_are_safe(self):
        widget = self.widget()
        displayed = set()
        for code, entry in ERROR_TABLE.items():
            widget.set_state('error', error_code=code, exception=Exception('SECRET-DETAIL'), message='SECRET-DETAIL', retry=Mock())
            self.assertIn(entry.explanation, widget.label.text())
            self.assertIn(entry.action, widget.label.text())
            displayed.add(widget.label.text().splitlines()[0])
        self.assertEqual(displayed, set(ERROR_TABLE))
        for unknown in ('SECRET-DETAIL', None, [], Exception('SECRET-DETAIL')):
            widget.set_state('error', error_code=unknown, exception=Exception('SECRET-DETAIL'))
            self.assertEqual(widget.label.text(), ui_text('async.error_unknown'))
            for child in [widget, *widget.findChildren(QLabel), *widget.findChildren(QPushButton)]:
                self.assertNotIn('SECRET-DETAIL', child.toolTip() + child.accessibleDescription() + child.accessibleName())
                if isinstance(child, QLabel):
                    self.assertNotIn('SECRET-DETAIL', child.text())

    def test_job_projection_reads_existing_state_without_starting_work(self):
        progress = JobProgress(Mock())
        self.addCleanup(progress.deleteLater)
        feedback = JobFeedback(progress)
        host = SimpleNamespace(job_progress=progress, job_feedback=feedback)
        widget = self.widget(host)
        widget.read_job()
        self.assertEqual(widget.property('state'), 'empty')
        progress.begin()
        widget.read_job()
        self.assertEqual(widget.property('state'), 'loading')
        progress.set_running(False)
        feedback.terminal = True
        retry = Mock()
        widget.read_job(error_code='operation_failed', retry=retry)
        self.assertEqual(widget.property('state'), 'error')
        retry.assert_not_called()
        self.assertTrue(feedback.terminal)
        self.widget(SimpleNamespace()).read_job()

    def test_log_and_maintenance_empty_and_error_states(self):
        table = LogTable()
        panel = MaintenancePanel()
        self.addCleanup(table.deleteLater)
        self.addCleanup(panel.deleteLater)
        table.load([])
        self.assertIsInstance(table.empty_status, AsyncStatus)
        self.assertFalse(table.empty_status.isHidden())
        self.assertTrue(table.empty_status.action.isHidden())
        with (
            patch('desktop_pages.maintenance.installed_payload_root', return_value=Path('unused')),
            patch('desktop_pages.maintenance.plan_payload_cleanup', return_value=SimpleNamespace(reason=None, candidates=())),
        ):
            panel.check_payloads()
        self.assertEqual(panel.async_status.property('state'), 'empty')
        self.assertEqual(panel.status.text(), ui_text('maintenance.nothing'))
        panel.results.put(UpdateResult('error', 'check_failed'))
        panel.poll_update()
        self.assertEqual(panel.async_status.property('state'), 'error')
        self.assertFalse(panel.async_status.action.isHidden())

    def test_onboarding_and_result_use_shared_component(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'desktop_pages/onboarding.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        install = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'install_onboarding')
        loop = next(node for node in ast.walk(install) if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple) and len(node.target.elts) == 3)
        calls = [node.func.id for node in ast.walk(loop) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn('AsyncStatus', calls)
        self.assertNotIn('QLabel', calls)
        self.assertNotIn('QPushButton', calls)
        result = (root / 'desktop_pages/backtest.py').read_text(encoding='utf-8')
        self.assertIn('self.result_empty = AsyncStatus()', result)

    def test_real_pages_keep_names_guidance_and_use_shared_empty_states(self):
        with sandbox_ui(), disposable_directory() as folder:
            paths = AppPaths(Path(folder) / 'workspace').ensure()
            jobs = JobManager(paths)
            window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'))
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                for key in ('market', 'strategy', 'backtest', 'compare', 'paper'):
                    status = window.findChild(AsyncStatus, 'empty_' + key)
                    self.assertIsNotNone(status)
                    self.assertEqual(status.property('state'), 'empty')
                    self.assertEqual(status.action.objectName(), 'empty_' + key + '_action')
                    self.assertEqual(status.action.property('role'), 'primary')
                self.assertEqual(window.findChild(AsyncStatus, 'empty_market').label.text(), ui_text('onboarding.empty.market'))
                self.assertEqual(window.findChild(AsyncStatus, 'empty_paper').action.text(), ui_text('onboarding.next.paper'))
                self.assertIsInstance(window.backtest_page.result_empty, AsyncStatus)
                actual = sorted({widget.objectName() for widget in [window, *window.findChildren(QWidget)] if widget.objectName()})
                fixture = Path(__file__).parent / 'fixtures/desktop_widget_names.json'
                self.assertEqual(actual, json.loads(fixture.read_text(encoding='utf-8')))
            finally:
                jobs.close()
                window.close()
                window.deleteLater()
