"""Cheap synthetic/offscreen evidence for the display-only U2-C8 boundary."""

from desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import ast
from dataclasses import replace
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel, QVBoxLayout, QWidget

from desktop_app.components.async_status import AsyncStatus
from desktop_app.shell.notification_log import NotificationLog
from desktop_app.shell.notifications import NotificationCenter, install_notifications
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_feedback import OPERATION_LABELS, completion_summary, stop_presentation
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui
from tests.test_no_hardcoded_ui_text import UI_PACKAGE_MODULES
from tests.test_import_graph import TOUCHED
from desktop_app.shell.window import MainWindow
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
# Source scans below use current physical paths.


ROOT = Path(__file__).resolve().parents[1]
SECRET = 'SENTINEL_C8_CREDENTIAL_92719'
OOS = 'SENTINEL_C8_EVALUATION_68143'


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def center(self, host=None):
        host = host or SimpleNamespace(last_operation='ui_demo', cancel_job=Mock(), jobs=SimpleNamespace(active=True))
        center = NotificationCenter(host)
        self.addCleanup(center.shutdown)
        return center

    def test_bound_eviction_monotonic_and_clear(self):
        log = NotificationLog(100, clock=lambda: datetime(2026, 1, 1, 2, 3, 4))
        for _ in range(150):
            log.append(operation='ui_import')
        self.assertEqual(log.entries.maxlen, 100)
        self.assertEqual(len(log.entries), 100)
        self.assertEqual(log.entries[0].sequence, 51)
        self.assertEqual(log.entries[-1].id, 150)
        self.assertEqual(log.entries[0].time, '02:03:04')
        self.assertEqual(log.unread_count, 100)
        log.mark_viewed()
        self.assertEqual(log.unread_count, 0)
        log.clear()
        self.assertFalse(log.entries)
        self.assertEqual(log.append().sequence, 151)

    def test_same_ingress_covers_all_operations_and_deduplicates(self):
        center = self.center()
        for index, operation in enumerate(OPERATION_LABELS):
            center.host.last_operation = 'ui_' + operation
            event = {'type': 'result', 'job_id': index, 'result': {}}
            before = len(center.log.entries)
            entry = center.record_event(event)
            self.assertEqual(len(center.log.entries), before + 1)
            self.assertIsNone(center.record_event(dict(event)))
            center.notify_local(SECRET, completion=True)
            self.assertEqual(len(center.log.entries), before + 1)
            expected = (
                'paper'
                if operation in ('paper_submit', 'paper_cancel', 'paper_cancel_all')
                else 'data'
                if operation in ('market_refresh', 'refresh', 'import')
                else 'job'
            )
            self.assertEqual(entry.kind, expected)
            if expected == 'paper':
                self.assertIn(ui_text('notifications.paper_summary').split(':')[0], entry.message)

    def test_toast_cap_nonmodal_focus_dismiss_and_error_retention(self):
        center = self.center()
        with patch.object(QDialog, 'exec', side_effect=AssertionError('modal')):
            for index in range(10):
                center.record_event({'type': 'result', 'job_id': index, 'result': {}})
        self.assertEqual(sum(not t.isHidden() for t in center.toasts), 3)
        for toast in center.toasts:
            self.assertEqual(toast.focusPolicy(), Qt.FocusPolicy.NoFocus)
            self.assertTrue(toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            toast.linkActivated.emit('close')
            self.assertTrue(toast.isHidden())
            self.assertFalse(toast.timer.isActive())
        center.in_event = False
        center.notify_local(Exception(SECRET), error=True)
        toast = center.toasts[0]
        self.assertFalse(toast.isHidden())
        toast.expire()
        self.assertFalse(toast.isHidden())
        center.dismiss_toasts()
        center.host.cancel_job.assert_not_called()
        self.assertEqual(len(center.log.entries), 11)
        self.assertTrue(center.log.entries[-1].unread)

    def test_expiry_visibility_parent_and_close(self):
        center = self.center()
        center.notify_local(ui_text('job.cancelled'), completion=True)
        toast = center.toasts[0]
        self.assertIs(toast.timer.parent(), toast)
        self.assertEqual(toast.timer.interval(), 5000)
        self.assertFalse(toast.timer.isActive())  # no visible window
        toast.timer.timeout.emit()
        self.assertTrue(toast.isHidden())
        self.assertEqual(len(center.log.entries), 1)
        toast.present(center.log.entries[0])
        toast.timer.start()
        toast.close()
        self.assertFalse(toast.timer.isActive())

    def test_keyboard_center_badge_navigation_dismiss_clear(self):
        center = self.center()
        center.host._notification_link = Mock()
        for index, operation in enumerate(('ui_import', 'ui_backtest', 'ui_paper_cancel')):
            center.host.last_operation = operation
            center.record_event({'type': 'result', 'job_id': index, 'result': {}})
        self.assertEqual(center.button.accessibleName(), ui_text('notifications.badge').format(3))
        QTest.keyClick(center.button, Qt.Key.Key_Space)
        self.assertEqual(center.log.unread_count, 0)
        self.assertEqual(center.rows.currentRow(), 0)
        QTest.keyClick(center.rows, Qt.Key.Key_Down)
        QTest.keyClick(center.rows, Qt.Key.Key_Return)
        self.assertEqual(center.host._notification_operation, 'ui_backtest')
        center.host._notification_link.assert_called_once_with('result')
        QTest.keyClick(center.rows, Qt.Key.Key_Up)
        QTest.keyClick(center.rows, Qt.Key.Key_Delete)
        self.assertEqual(len(center.log.entries), 2)
        QTest.keyClick(center.rows, Qt.Key.Key_Escape)
        self.assertTrue(center.isHidden())
        with patch('pathlib.Path.unlink', side_effect=AssertionError('file deletion')):
            center.clear_all()
        self.assertFalse(center.log.entries)

    def test_payload_exception_privacy_and_negative_control(self):
        center = self.center()
        payload = {
            'account': {'account_id': SECRET, 'cash': SECRET},
            'metrics': {'net_pnl': OOS},
            'summary': {'evaluated_oos_folds': OOS},
            'analysis_id': SECRET,
            'bars': SECRET,
            'error': Exception(SECRET),
            'strategy_hash': SECRET,
            'providers': {'private': {'bars': SECRET, 'error': SECRET}},
            'replay': {'cursor': OOS},
            'holdout': OOS,
            'token': SECRET,
        }
        for index, operation in enumerate(OPERATION_LABELS):
            center.host.last_operation = 'ui_' + operation
            center.record_event({'type': 'result', 'job_id': index, 'result': payload})
        center.in_event = False
        center.notify_local(Exception(SECRET), error=True)
        center.notify_local(SECRET, completion=True)
        center.rebuild()
        text = repr(center.log.entries) + center.button.accessibleName()
        text += ''.join(center.rows.item(i).text() for i in range(center.rows.count()))
        text += ''.join(t.text() + t.accessibleName() + t.toolTip() for t in center.toasts)

        def sentinel_scan(value):
            return [sentinel for sentinel in (SECRET, OOS) if sentinel in value]

        self.assertEqual(sentinel_scan(text), [])
        self.assertEqual(sentinel_scan(text + SECRET + OOS), [SECRET, OOS])
        before = [entry.message for entry in center.log.entries]
        center.host.privacy = SimpleNamespace(enabled=True)
        center.rebuild()
        self.assertEqual(before, [entry.message for entry in center.log.entries])
        self.assertNotIn('guaranteed', text.casefold())

    def test_b1_same_code_no_retry_and_market_failure(self):
        center = self.center()
        retry = Mock()
        code = 'validation_failed'
        center.host.job_feedback = SimpleNamespace(terminal=True)
        status = AsyncStatus(host=center.host)
        self.addCleanup(status.close)
        status.read_job(error_code=code, retry=retry)
        entry = center.record_event({'type': 'failed', 'job_id': 'b1', 'error_code': code, 'exception': Exception(SECRET)})
        self.assertEqual(entry.error_code, code)
        self.assertIn(code, status.label.text())
        self.assertIn(code, entry.message)
        retry.assert_not_called()
        center.host.last_operation = 'ui_market_refresh'
        entry = center.record_event({'type': 'result', 'job_id': 'market', 'result': {'providers': {'x': {'error': SECRET}}}})
        self.assertEqual(entry.severity, 'error')

    def test_compatibility_toggle_and_literal_html(self):
        host = SimpleNamespace(last_operation='ui_demo', local_notifications=QCheckBox())
        center = self.center(host)
        center.notify_local(SECRET)
        self.assertTrue(all(t.isHidden() for t in center.toasts))
        self.assertEqual(len(center.log.entries), 1)
        center.notify_local(completion_summary('ui_demo', {'bars': 960}), completion=True)
        self.assertIn('960', center.toasts[0].text())
        entry = replace(center.log.entries[-1], message='<script>x</script><b>y</b>')
        center.toasts[0].present(entry)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;&lt;b&gt;y&lt;/b&gt;', center.toasts[0].text())
        self.assertNotIn('<script>', center.toasts[0].text())
        center.log.entries.append(entry)
        center.rebuild()
        self.assertIn(entry.message, center.rows.item(0).text())

    def test_thousand_events_bounded_center_work(self):
        center = self.center()
        for index in range(1000):
            center.record_event({'type': 'result', 'job_id': index, 'result': {}})
        center.rebuild()
        self.assertEqual(len(center.log.entries), center.log.entries.maxlen)
        self.assertEqual(center.rebuild_count, center.log.entries.maxlen)
        self.assertLessEqual(len(center.log._seen), center.log.entries.maxlen)

    def test_lifetime_layout_and_ast_boundaries(self):
        host = QWidget()
        host.app_header = QWidget(host)
        QVBoxLayout(host.app_header)
        layout = QVBoxLayout(host)
        layout.addWidget(host.app_header)
        host.last_operation = 'ui_import'
        install_notifications(host, layout)
        center = host.notification_center
        wrappers = tuple(center.toasts)
        for index in range(3):
            center.record_event({'type': 'result', 'job_id': index, 'result': {}})
        for toast in wrappers:
            self.assertGreater(layout.indexOf(toast), layout.indexOf(host.app_header))
            toast.timer.start()
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            host.close()
        finally:
            qInstallMessageHandler(previous)
        self.assertEqual(warnings, [])
        self.assertTrue(all(not t.timer.isActive() for t in wrappers))
        self.assertTrue(all(t.isHidden() for t in wrappers))
        for name in ('desktop_app/shell/notifications.py', 'desktop_app/shell/notification_log.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
            self.assertFalse({'deleteLater', 'findChildren', 'installEventFilter', 'exec', 'submit', 'cancel', 'amend', 'kill'} & set(calls))
        imports = [
            node.module
            for node in ast.walk(ast.parse((ROOT / 'desktop_app/shell/notification_log.py').read_text(encoding='utf-8')))
            if isinstance(node, ast.ImportFrom)
        ]
        self.assertFalse(any(name.startswith('PySide') for name in imports))

    def test_catalog_and_golden_fixture(self):
        fixture = json.loads((ROOT / 'tests/fixtures/notification_feedback_c8.json').read_text(encoding='utf-8'))
        for operation, expected in fixture['completion'].items():
            self.assertEqual(completion_summary(operation, fixture['result']), expected)
        for account, reason, expected in fixture['stop']:
            self.assertEqual(list(stop_presentation(account, reason)), expected)

        for module in ('desktop_app/shell/notifications.py', 'desktop_app/shell/notification_log.py'):
            self.assertIn(module, UI_PACKAGE_MODULES)
            self.assertIn(module, TOUCHED)

    def test_bare_host_notify_keeps_legacy_attributes_and_original_text(self):
        _c_JobPresenter(SimpleNamespace()).notify_local(Exception(SECRET), error=True)
        host = SimpleNamespace(
            notification=QLabel(),
            notification_timer=QTimer(),
            notification_fade=Mock(),
            notification_opacity=Mock(),
            local_notifications=QCheckBox(),
            last_operation='ui_import',
        )
        self.addCleanup(host.notification.close)
        host.local_notifications.setChecked(True)
        message = ui_text('notifications.error') + '<script>x</script><b>y</b>'
        _c_JobPresenter(host).notify_local(message, error=True, completion=True)
        self.assertEqual(host.notification.text(), ui_text('ui.notify_local.result_close_links').format(escape(message)))
        self.assertEqual(host.notification.property('status'), 'danger')
        self.assertFalse(host.notification_timer.isActive())
        self.assertEqual(host._notification_operation, 'ui_import')
        _c_JobPresenter(host).notify_local(ui_text('job.cancelled'), completion=True)
        self.assertEqual(host.notification.property('status'), 'neutral')
        self.assertEqual(host.notification_timer.interval(), 5000)
        _c_JobPresenter(host)._notification_link('close')
        self.assertTrue(host.notification.isHidden())
        self.assertFalse(host.notification_timer.isActive())
        host.notification_fade.stop.assert_called()

    def test_center_is_additive_to_legacy_banner(self):
        host = QWidget()
        host.app_header = QWidget(host)
        QVBoxLayout(host.app_header)
        layout = QVBoxLayout(host)
        host.last_operation = 'ui_import'
        install_notifications(host, layout)
        self.addCleanup(host.close)
        center = host.notification_center
        host.local_notifications = QCheckBox()
        host.local_notifications.setChecked(True)
        message = ui_text('ui.poll_jobs.restore_incomplete')
        _c_JobPresenter(host).notify_local(message, error=True, completion=True)
        self.assertEqual(host.notification.text(), ui_text('ui.notify_local.result_close_links').format(message))
        self.assertIsNot(host.notification, center.toasts[0])
        self.assertIs(host.notification_fade.targetObject(), host.notification_opacity)
        self.assertEqual(len(center.log.entries), 1)
        for index in range(10):
            center.record_event({'type': 'result', 'job_id': index, 'result': {}})
        self.assertLessEqual(sum(not toast.isHidden() for toast in center.toasts) + int(not host.notification.isHidden()), 3)
        center.dismiss_toasts()
        self.assertTrue(host.notification.isHidden())
        self.assertFalse(host.notification_timer.isActive())

    def test_real_window_mock_poll_routes_and_duplicates(self):

        with disposable_directory() as folder, sandbox_ui():
            paths = AppPaths(Path(folder) / 'workspace', Path(folder) / 'bootstrap').ensure()
            jobs = JobManager(paths)
            window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'), None, services=_c_create_ui_services(_c_create_operation_ports()))
            window.timer.stop()
            try:
                window._pending_chatgpt_restore = False
                window.last_operation = 'ui_demo'
                event = {'type': 'result', 'job_id': 'demo-test', 'result': {'bars': 960}}
                with (
                    patch.object(jobs, 'poll', return_value=[event, dict(event)]),
                    patch.object(window.views_page, 'render_result', return_value={'bars': 960}),
                ):
                    window.poll_jobs()
                self.assertEqual(len(window.notification_center.log.entries), 1)
                self.assertIn('960', window.notification.text())
                for operation, page in (
                    ('ui_paper_submit', 4),
                    ('ui_backtest', 2),
                    ('ui_compare', 3),
                    ('ui_analysis_read', 1),
                    ('ui_backup_create', 6),
                    ('ui_import', 0),
                ):
                    window.notify_local(ui_text('job.cancelled'), completion=True)
                    entry = replace(window.notification_center.log.entries[-1], operation=operation)
                    window.notification_center.navigate(entry)
                    self.assertEqual(window.navigation.currentRow(), page)
                    window.notification_center.toasts[0].entry = entry
                    window.notification_center.toasts[0].follow_link('result')
                    self.assertEqual(window.navigation.currentRow(), page)
            finally:
                jobs.close()
                window.close()
