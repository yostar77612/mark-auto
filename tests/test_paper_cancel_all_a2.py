"""Offline cancel-all contracts: snapshot authority, isolation and UI consent."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget

import desktop_ui as ui
from desktop_pages.paper import PaperPage, stop_exposure_text, stop_dialog, cancel_all_dialog
from desktop_pages.job_progress import failure_notice
from desktop_strings import ui_text
from quantlab.core import ValidationError
from quantlab.desktop_feedback import completion_summary
from quantlab.paper import LiveBroker, LiveTradingDisabled
from tests import test_paper as paper_fixtures
from tests.test_paper import NOW
from tests.test_paper_lock_b2 import ScratchDirectory


class CancelAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fixture = paper_fixtures.PaperTests()
        with patch.object(paper_fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.broker = fixture.broker
        fixture.submit('filled')
        self.broker.apply_event(fixture.event('filled'))
        fixture.submit('cancelled')
        self.broker.apply_event(fixture.event('cancelled', typ='cancel'))
        for oid in ('z-buy', 'a-sell'):
            fixture.submit(oid, side='sell' if oid == 'a-sell' else 'buy', order_type='limit', limit_price='20000')
        fixture.submit('terminal', quantity=99)
        self.before = self.broker.snapshot()

    def run_cancel(self, **payload):
        with patch.object(ui, '_prepare_paper_operation', return_value=self.broker):
            return ui._handle_ui_paper_cancel_all({'now': NOW.isoformat(), **payload}, None, self.fixture.path.parent)

    def test_sorted_snapshot_targets_idempotent_preserves_cash_positions_and_lock(self):
        self.broker.set_manual_order_lock(True)
        before = self.broker.snapshot()
        initial = len(self.broker.journal_events())
        with patch.object(self.broker, 'cancel', wraps=self.broker.cancel) as cancel:
            result = self.run_cancel(order_ids=['terminal', 'forged'])
        self.assertEqual([call.args[0] for call in cancel.call_args_list], ['a-sell', 'z-buy'])
        self.assertEqual(result['cancel_all_report'], {'cancelled_order_ids': ['a-sell', 'z-buy'], 'failed_order_ids': [], 'errors': {}})
        for oid in ('z-buy', 'a-sell'):
            self.assertTrue(result['account']['orders'][oid]['cancel_requested'])
            self.assertEqual(result['account']['orders'][oid]['status'], 'cancel_pending')
        self.assertTrue(result['account']['manual_order_lock'])
        for key in ('positions', 'cash', 'fills'):
            self.assertEqual(result['account'][key], before[key])
        events = self.broker.journal_events()
        self.assertEqual(len(events), initial + 2)
        self.assertEqual([e['operation'] for e in events[initial:]], ['cancel_request', 'cancel_request'])
        self.run_cancel()
        self.assertEqual(self.broker.journal_events(), events)
        self.assertIn('2', completion_summary('ui_paper_cancel_all', result))
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()

    def test_one_failure_does_not_abort_others_and_all_fail_returns_report(self):
        original = self.broker.cancel

        def cancel(oid, **kwargs):
            if oid == 'a-sell':
                raise ValidationError('secret C:/private/path')
            return original(oid, **kwargs)

        with patch.object(self.broker, 'cancel', side_effect=cancel):
            result = self.run_cancel()
        report = result['cancel_all_report']
        self.assertEqual(report['cancelled_order_ids'], ['z-buy'])
        self.assertEqual(report['failed_order_ids'], ['a-sell'])
        self.assertEqual(report['errors'], {'a-sell': 'validation_failed'})
        self.assertIn('1', completion_summary('ui_paper_cancel_all', result))
        before = self.broker.snapshot()
        with patch.object(self.broker, 'cancel', side_effect=ValidationError('private')):
            result = self.run_cancel()
        self.assertEqual(result['cancel_all_report']['failed_order_ids'], ['a-sell', 'z-buy'])
        self.assertEqual(result['account'], before)

    def test_stop_confirmation_keeps_real_orders_and_never_requests_cancellation(self):
        page = PaperPage.__new__(PaperPage)
        QWidget.__init__(page)
        self.addCleanup(page.close)
        state = SimpleNamespace(
            root=self.fixture.path.parent,
            status=QLabel(),
            manual_order_lock=False,
            chatgpt_panel=SimpleNamespace(consent=Mock()),
            paper_confirm=Mock(),
            _chatgpt_job_request=None,
            chatgpt_controller=Mock(),
            guard=None,
        )
        page.setup_context(
            SimpleNamespace(state=state, callbacks={'_paper': Mock(return_value=self.broker), '_quiesce_and_recover': Mock(), 'write_json': Mock()})
        )
        page.replay_controls = SimpleNamespace(cancel=Mock())
        page._show_account = Mock()
        page._remember_stop = Mock()
        dialog = SimpleNamespace(confirm_button=object(), observe_button=object(), exec=Mock())
        dialog.clickedButton = Mock(return_value=dialog.confirm_button)
        with (
            patch.object(Path, 'exists', return_value=True),
            patch('quantlab.paper.PaperBroker.read_snapshot', return_value=self.before),
            patch('desktop_pages.paper.stop_dialog', return_value=dialog),
        ):
            page.kill_paper()
        after = self.broker.snapshot()
        for key in ('orders', 'positions', 'cash', 'fills'):
            self.assertEqual(after[key], self.before[key])
        self.assertFalse(any(e['operation'] == 'cancel_request' for e in self.broker.journal_events()))


class CancelAllUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pending_summary_is_pure_masks_quantities_and_ignores_malformed_rows(self):
        account = {
            'positions': {},
            'orders': {
                'private-buy-id': {'status': 'accepted', 'intent': {'side': 'buy', 'quantity': 5}, 'filled_quantity': 2},
                'private-sell-id': {'status': 'accepted', 'intent': {'side': 'sell', 'quantity': 7}},
            },
        }
        before = deepcopy(account)
        self.assertTrue(stop_exposure_text(account).endswith(ui_text('paper.stop.pending_orders').format(2, 3, 7)))
        private = stop_exposure_text(account, True)
        for hidden in ('3', '7', 'private-buy-id', 'private-sell-id'):
            self.assertNotIn(hidden, private)
        self.assertEqual(account, before)
        for row in (None, 'bad', {}, {'intent': None}, {'intent': {'side': 'buy', 'quantity': 'NaN'}}, {'intent': {'side': 'sell', 'quantity': 'bad'}}):
            stop_exposure_text({'orders': {'broken': row}})

    def test_empty_and_terminal_snapshot_bytes_match_fixed_original_text(self):
        expected = '\u76ee\u524d\u6c92\u6709\u672a\u5e73\u5009\u90e8\u4f4d\u3002\n\u7e3d\u66dd\u96aa\uff08\u5404\u90e8\u4f4d\u7d55\u5c0d\u53e3\u6578\u5408\u8a08\uff09\uff1a0\n\u505c\u6b62\u65b0\u59d4\u8a17\u4e0d\u6703\u5e73\u5009\uff1b\u73fe\u6709\u90e8\u4f4d\u4e0d\u6703\u95dc\u9589\u3002'
        for account in ({}, {'orders': None}, {'orders': {}}, {'orders': {s: {'status': s} for s in ('filled', 'cancelled', 'rejected')}}):
            self.assertEqual(stop_exposure_text(account).encode('utf-8'), expected.encode('utf-8'))

    def test_dialogs_plain_text_accessible_default_and_escape_cancel(self):
        for dialog, count in ((stop_dialog(None, '<b>snapshot</b>'), 3), (cancel_all_dialog(None, 2), 2)):
            self.addCleanup(dialog.close)
            self.assertEqual(len(dialog.buttons()), count)
            self.assertEqual(dialog.textFormat(), Qt.TextFormat.PlainText)
            self.assertIs(dialog.defaultButton(), dialog.escapeButton())
            self.assertIsNot(dialog.defaultButton(), dialog.confirm_button)
            for button in dialog.buttons():
                self.assertEqual(button.accessibleName(), button.text())
            dialog.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.assertIs(dialog.clickedButton(), dialog.escapeButton())

    def test_explicit_confirm_only_starts_job_with_policy_and_time_even_while_locked(self):
        page = PaperPage.__new__(PaperPage)
        QWidget.__init__(page)
        self.addCleanup(page.close)
        state = SimpleNamespace(root=Path('/unused-a2'), status=QLabel(), manual_order_lock=True, paper_confirm=Mock(), paper_policy=Mock(), policy_form=Mock())
        start = Mock()
        page.setup_context(SimpleNamespace(state=state, callbacks={'start_job': start, '_payload': Mock(return_value={'policy': 'fixture'})}))
        page.paper_time = Mock(text=Mock(return_value='2026-10-09T01:00:00Z'))
        page._stop_account = {'orders': {'one': {'status': 'accepted'}}}
        dialog = SimpleNamespace(confirm_button=object(), exec=Mock(), clickedButton=Mock(return_value=None))
        with patch.object(Path, 'exists', return_value=False), patch('desktop_pages.paper.cancel_all_dialog', return_value=dialog) as factory:
            page.cancel_all_paper()
            factory.assert_called_once_with(page, 1)
            start.assert_not_called()
            dialog.clickedButton.return_value = dialog.confirm_button
            page.cancel_all_paper()
            start.assert_called_once_with('ui_paper_cancel_all', {'policy': {'policy': 'fixture'}, 'now': '2026-10-09T01:00:00Z'})
            self.assertTrue(state.manual_order_lock)
            start.reset_mock()
            page._stop_account = {}
            page.cancel_all_paper()
            self.assertEqual(state.status.text(), ui_text('paper.cancel_all.empty'))
            start.assert_not_called()

    def test_failure_clears_pending_order_notice(self):
        chart = SimpleNamespace(paper_orders=SimpleNamespace(notice=ui_text('orders.pending')), update=Mock())
        shell = SimpleNamespace(last_operation='ui_paper_cancel_all', market=SimpleNamespace(chart=chart))
        self.assertEqual(failure_notice(shell, {'type': 'error'}), ui_text('orders.failed'))
        chart.update.assert_called_once_with()

    def test_notification_summary_retains_counts_without_ids_or_error_values(self):
        from desktop_pages.notification_log import safe_summary

        result = {
            'cancel_all_report': {
                'cancelled_order_ids': ['secret-id-a', 'secret-id-b'],
                'failed_order_ids': ['private-id'],
                'errors': {'private-id': 'private'},
            }
        }
        text = safe_summary('ui_paper_cancel_all', result)
        self.assertIn('2', text)
        self.assertIn('1', text)
        self.assertNotIn('secret', text)
        self.assertNotIn('private', text)

    def test_real_button_has_danger_role_and_click_uses_confirmation(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QPushButton
        import shiboken6
        from tests.test_t9_onboarding import sandbox_ui
        from tests.test_ui_operations_registry import workspace
        from quantlab.desktop_runtime import JobManager

        with sandbox_ui(), workspace() as paths:
            jobs = JobManager(paths)
            window = ui.MainWindow(paths, jobs)
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                page = window.paper_page
                button = page.findChild(QPushButton, 'paper_cancel_all')
                self.assertIsNotNone(button)
                self.assertEqual(button.text(), ui_text('paper.cancel_all.button'))
                self.assertEqual(button.property('role'), 'danger')
                self.assertFalse(button.isVisible())
                page._stop_account = {'orders': {'pending': {'status': 'accepted'}}}
                dialog = SimpleNamespace(confirm_button=object(), exec=Mock(), clickedButton=Mock(return_value=None))
                with patch('desktop_pages.paper.cancel_all_dialog', return_value=dialog) as factory, patch.object(page, 'start_job') as start:
                    button.click()
                    factory.assert_called_once_with(page, 1)
                    start.assert_not_called()
            finally:
                window.close()
                shiboken6.delete(window)
                jobs.close()
