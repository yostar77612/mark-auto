"""Audit real desktop dispatch sites against the existing C8 notification ingress."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QWidget

from desktop_app.features.settings.automatic_backup import AutomaticBackupPanel
from desktop_app.shell import notifications
from desktop_app.shell.notification_log import safe_summary
from desktop_app.shell.notifications import NotificationCenter
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.main_window import MainWindow
from quantlab.desktop_feedback import OPERATION_LABELS
from quantlab.errors import ERROR_TABLE
from tests.layered_source_fixtures import physical_path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = 'PRIVATE_ACCOUNT_AMOUNT_HASH_97351'
EVALUATION = 'PRIVATE_EVALUATION_82469'


def dispatch_operations():
    """Resolve literal, conditional and paper dispatcher operations; reject new opaque sites."""
    paths = sorted(
        [
            *ROOT.glob('desktop*.py'),
            *(
                ROOT / relative
                for relative in (
                    'quantlab/assistant/adapters/chatgpt/auth.py',
                    'quantlab/assistant/adapters/chatgpt/provider.py',
                    'quantlab/research_core/adapters/market_layout.py',
                )
            ),
        ]
    ) + sorted((ROOT / physical_path('desktop_pages')).rglob('*.py'))
    trees = [(path, ast.parse(path.read_text(encoding='utf-8-sig'))) for path in paths]
    paper = set()
    for _, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'paper_job' and node.args:
                if isinstance(node.args[0], ast.Starred):
                    continue
                if not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    raise AssertionError('New nonliteral paper dispatcher needs an audit resolver')
                paper.add('ui_paper_' + node.args[0].value)

    def resolve(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return resolve(node.body) | resolve(node.orelse)
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
            and isinstance(node.left, ast.Constant)
            and node.left.value == 'ui_paper_'
            and isinstance(node.right, ast.Name)
            and node.right.id == 'op'
        ):
            return paper
        raise AssertionError('New unresolved start_job operation: ' + ast.dump(node))

    operations = set()
    for path, tree in trees:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'start_job'):
                continue
            # PageHost's forwarding adapters preserve their caller's operation.
            if not node.args and any(keyword.arg is None for keyword in node.keywords):
                continue
            if node.args and isinstance(node.args[0], ast.Starred):
                continue
            if not node.args:
                raise AssertionError(f'Unresolved dispatch at {path.name}:{node.lineno}')
            operations.update(resolve(node.args[0]))
    return operations


class NotificationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def center(self, **values):
        host = SimpleNamespace(last_operation='ui_demo', start_job=Mock(side_effect=AssertionError('dispatch')), **values)
        center = NotificationCenter(host, toast_limit=2)
        host.notification_center = center
        self.addCleanup(center.shutdown)
        return host, center

    def terminal(self, host, event):
        notifications.begin_event(host)
        try:
            entry = notifications.record_event(host, event)
            host.notification_center.notify_local(PRIVATE, error=True, completion=True)
            return entry
        finally:
            notifications.end_event(host)

    def test_every_start_job_operation_success_failure_and_cancellation(self):
        operations = dispatch_operations()
        self.assertEqual(operations, {'ui_' + op for op in OPERATION_LABELS})
        for required in ('ui_market_refresh', 'ui_backup_create', 'ui_backup_restore', 'ui_campaign', 'ui_compare'):
            self.assertIn(required, operations)
        for operation in sorted(operations):
            for terminal, severity in (('result', 'info'), ('error', 'error'), ('cancelled', 'info')):
                with self.subTest(operation=operation, terminal=terminal):
                    host, center = self.center()
                    host.last_operation = operation
                    event = {'type': terminal, 'job_id': 42, 'error_code': PRIVATE, 'exception': PRIVATE, 'result': {}}
                    self.terminal(host, event)
                    self.terminal(host, dict(event))
                    self.assertFalse(center.in_event)
                    self.assertEqual(len(center.log.entries), 1)
                    entry = center.log.entries[0]
                    self.assertEqual(entry.operation, operation)
                    self.assertEqual(entry.severity, severity)
                    self.assertNotIn(PRIVATE, entry.message)
                    if terminal == 'error':
                        self.assertIn(entry.error_code, ERROR_TABLE)
                        self.assertEqual(entry.error_code, 'operation_failed')
                    elif terminal == 'cancelled':
                        self.assertEqual(entry.message, ui_text('job.cancelled'))
                        self.assertIsNone(entry.error_code)
                    else:
                        self.assertEqual(entry.message, safe_summary(operation, {}))
                    self.assertEqual(center.log.unread_count, 1)
                    self.assertEqual(center.toasts[0].entry, entry)
                    self.assertFalse(center.toasts[0].isHidden())
                    self.assertFalse(center.toasts[0].timer.isActive())
                    host.start_job.assert_not_called()

    def test_market_provider_partial_failure_and_privacy_projection(self):
        payload = {
            'providers': {'private-provider': {'bars': 7}, 'other': {'bars': 3}},
            'bars': 10,
            'rows': [{PRIVATE: EVALUATION}],
            'reports': [{PRIVATE: EVALUATION}],
            'account': {'account_id': PRIVATE, 'cash': PRIVATE},
            'strategy_hash': PRIVATE,
            'metrics': {'net_pnl': EVALUATION},
            'summary': {'evaluated_oos_folds': EVALUATION},
            'oos': EVALUATION,
            'holdout': EVALUATION,
            'analysis_id': PRIVATE,
            'replay': {'cursor': EVALUATION},
        }
        for private in (False, True):
            for operation in sorted(dispatch_operations()):
                with self.subTest(private=private, operation=operation):
                    host, center = self.center(privacy=SimpleNamespace(enabled=private))
                    host.last_operation = operation
                    self.terminal(host, {'type': 'result', 'job_id': 1, 'result': payload})
                    center.rebuild()
                    text = repr(center.log.entries) + center.rows.item(0).text()
                    text += ''.join(toast.text() + toast.accessibleName() + toast.toolTip() for toast in center.toasts)
                    self.assertNotIn(PRIVATE, text)
                    self.assertNotIn(EVALUATION, text)
                    self.assertNotIn('private-provider', text)
                    self.assertEqual(center.log.entries[0].message, safe_summary(operation, payload))
        host, center = self.center()
        host.last_operation = 'ui_market_refresh'
        payload['providers']['other']['error'] = PRIVATE
        self.terminal(host, {'type': 'result', 'job_id': 'partial', 'result': payload})
        self.assertEqual(center.log.entries[0].severity, 'error')
        self.assertEqual(center.log.entries[0].error_code, 'operation_failed')
        self.assertEqual(center.toasts[0].entry, center.log.entries[0])

    def poll_host(self, operation, event):
        host, center = self.center()
        host.last_operation = operation
        host.jobs = SimpleNamespace(poll=lambda: [event], active=True)
        host._ui_job_id = event['job_id']
        host.job_feedback = SimpleNamespace(accept=lambda *_: True, campaign_code=None, result_failed=lambda _: False)
        host._walk_forward_event = host._analysis_event = host._chatgpt_event = lambda _: False
        host._subscription_campaign = False
        host.record_event = Mock()
        host.status = Mock()
        host.views_page = SimpleNamespace(render_result=lambda _: event.get('result', {}))
        host.notify_local = center.notify_local
        host.freeze_paper = Mock()
        host._market_outcomes = {}
        return host, center

    def test_automatic_backup_outcomes_flow_through_real_poll_ingress(self):
        for kind, status in (('result', 'success'), ('error', 'error'), ('cancelled', 'cancelled')):
            with self.subTest(kind=kind):
                event = {'type': kind, 'job_id': 17, 'error_code': 'validation_failed', 'result': {}}
                host, center = self.poll_host('ui_backup_create', event)
                panel = SimpleNamespace(archive=PRIVATE, job_id=17, scheduler=Mock(), status=Mock(), paused=False)
                panel.handle_job_event = lambda packet: AutomaticBackupPanel.handle_job_event(panel, packet)
                host.automatic_backup_panel = panel
                MainWindow.poll_jobs(host)
                panel.scheduler.complete.assert_called_once_with(archive=PRIVATE, status=status)
                self.assertIsNone(panel.archive)
                self.assertIsNone(panel.job_id)
                self.assertEqual(len(center.log.entries), 1)
                self.assertEqual(center.toasts[0].entry, center.log.entries[0])
                self.assertEqual(center.log.entries[0].severity, 'error' if kind == 'error' else 'info')
                self.assertFalse(center.in_event)

    def test_other_current_page_navigation_is_read_only(self):
        for operation, page in (
            ('ui_market_refresh', 0),
            ('ui_backup_create', 6),
            ('ui_backup_restore', 6),
            ('ui_walk_forward_run', 1),
            ('ui_analysis_run', 1),
            ('ui_campaign', 1),
            ('ui_compare', 3),
            ('ui_paper_submit', 4),
        ):
            with self.subTest(operation=operation):
                host, center = self.center()
                host.last_operation = operation
                host.navigation = SimpleNamespace(setCurrentRow=Mock())
                host.stack = SimpleNamespace(currentIndex=lambda: 5, widget=lambda _: SimpleNamespace(widget=lambda: None, ensureWidgetVisible=Mock()))
                host.paper_card = object()
                host._notification_link = lambda link: MainWindow._notification_link(host, link)
                self.terminal(host, {'type': 'result', 'job_id': 1, 'result': {}})
                self.assertEqual(host.stack.currentIndex(), 5)
                self.assertFalse(center.toasts[0].isHidden())
                center.rebuild()
                center.open_selected()
                host.navigation.setCurrentRow.assert_called_once_with(page)
                host.start_job.assert_not_called()

    def test_bounds_badge_toggle_unknown_nonmodal_and_shutdown(self):
        toggle = QCheckBox()
        host, center = self.center(local_notifications=toggle)
        with patch.object(QDialog, 'exec', side_effect=AssertionError('modal')):
            center.notify_local(ui_text('job.cancelled'))
            self.assertTrue(all(toast.isHidden() for toast in center.toasts))
            center.notify_local(ui_text('job.cancelled'), completion=True)
            center.notify_local(PRIVATE, error=True)
            self.assertEqual(sum(not toast.isHidden() for toast in center.toasts), 2)
            host.last_operation = PRIVATE
            for job_id in range(130):
                self.terminal(host, {'type': 'result', 'job_id': job_id, 'result': {}})
        self.assertEqual(len(center.log.entries), 100)
        self.assertEqual(center.log.entries.maxlen, 100)
        self.assertEqual(center.log.entries[-1].kind, 'job')
        self.assertEqual(center.log.entries[-1].operation, '')
        self.assertEqual(center.log.unread_count, 100)
        self.assertEqual(center.button.text(), ui_text('notifications.badge').format(100))
        center.log.mark_viewed()
        center.update_badge()
        self.assertEqual(center.button.text(), ui_text('notifications.badge').format(0))
        for toast in center.toasts:
            self.assertEqual(toast.focusPolicy(), Qt.FocusPolicy.NoFocus)
            self.assertFalse(toast.timer.isActive())
            toast.hideEvent(QHideEvent())
            self.assertFalse(toast.timer.isActive())
            toast.close()
            self.assertFalse(toast.timer.isActive())
        center.shutdown()
        window = QWidget()
        owned = NotificationCenter(window, window)
        self.addCleanup(window.close)
        owned.record_event({'type': 'result', 'job_id': 1, 'result': {}})
        window.close()
        self.assertTrue(owned.isHidden())
        self.assertTrue(all(toast.isHidden() and not toast.timer.isActive() for toast in owned.toasts))
