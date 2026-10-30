"""Cheap stop confirmation evidence: automation claims only not broken."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from desktop_app.features.paper.paper import PaperPage, stop_dialog, stop_exposure_text
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError


class StopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PaperPage.__new__(PaperPage)
        QWidget.__init__(self.page)
        self.state = SimpleNamespace(root=Path('/unused-u6'), status=QLabel(), manual_order_lock=False)
        self.freeze = Mock()
        self.broker = Mock()
        self.host = SimpleNamespace(state=self.state, callbacks={'freeze_paper': self.freeze, '_paper': Mock(return_value=self.broker)})
        self.page.setup_context(self.host)
        self.page.freeze_paper = self.freeze
        self.page.replay_controls = SimpleNamespace(cancel=Mock())
        self.account = {'positions': {'TMF:202611': 17, 'TMF:202612': -9, 'ZERO': 0}, 'cash': '912345'}
        self.page._stop_account = deepcopy(self.account)
        self.dialog = SimpleNamespace(confirm_button=object(), observe_button=object(), exec=Mock(), clickedButton=Mock(return_value=None))
        self.factory = patch('desktop_app.features.paper.paper.stop_dialog', return_value=self.dialog)
        self.make_dialog = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.exists = patch.object(Path, 'exists', return_value=False)
        self.exists.start()
        self.addCleanup(self.exists.stop)
        self.addCleanup(self.page.close)

    def test_cancel_changes_nothing_and_zero_positions_still_prompts(self):
        self.page._stop_account = {'positions': {}}
        self.page.kill_paper()
        self.assertIn(ui_text('paper.stop.empty'), self.make_dialog.call_args.args[1])
        self.freeze.assert_not_called()
        self.page.replay_controls.cancel.assert_not_called()
        self.assertFalse(self.state.manual_order_lock)
        self.assertTrue(self.page.isEnabled())
        self.assertEqual(self.state.status.text(), '')
        self.dialog.exec.assert_called_once_with()

    def test_confirm_without_policy_uses_original_reason_status_and_never_constructs_broker(self):
        self.dialog.clickedButton.return_value = self.dialog.confirm_button
        self.dialog.exec.side_effect = lambda: self.freeze.assert_not_called()
        self.page.kill_paper()
        self.freeze.assert_called_once_with(ui_text('ui.kill_paper.user_emergency_stop'))
        self.page.replay_controls.cancel.assert_called_once_with()
        self.assertEqual(self.state.status.text(), ui_text('ui.kill_paper.stopped_frozen'))
        self.assertEqual(self.page._stop_account, self.account)
        self.assertEqual(self.broker.mock_calls, [])
        self.assertFalse(self.state.manual_order_lock)

    def test_real_freeze_then_confirm_locks_and_preserves_quantities(self):
        self.page.freeze_paper = lambda reason: PaperPage.freeze_paper(self.page, reason)
        self.page._show_account = Mock()
        self.page._remember_stop = Mock()
        self.state.chatgpt_panel = SimpleNamespace(consent=Mock())
        self.state.paper_confirm = Mock()
        self.state._chatgpt_job_request = None
        self.state.chatgpt_controller = Mock()
        self.state.guard = None
        self.host.callbacks.update(_quiesce_and_recover=Mock(), write_json=Mock())
        self.broker.snapshot.return_value = self.account
        self.dialog.clickedButton.return_value = self.dialog.confirm_button
        before = deepcopy(self.account['positions'])
        with patch.object(Path, 'exists', side_effect=[False, True, True]):
            self.page.kill_paper()
        self.broker.set_kill_switch.assert_called_once_with(True)
        self.broker.set_manual_order_lock.assert_called_once_with(True)
        self.assertEqual([call[0] for call in self.broker.mock_calls], ['set_kill_switch', 'snapshot', 'snapshot', 'set_manual_order_lock', 'snapshot'])
        self.assertEqual(self.account['positions'], before)
        self.state.paper_confirm.setChecked.assert_called_once_with(False)

    def test_observe_locks_existing_mechanism_without_consent_or_job(self):
        self.dialog.clickedButton.return_value = self.dialog.observe_button
        self.page.kill_paper()
        self.assertTrue(self.state.manual_order_lock)
        self.assertTrue(self.page.isEnabled())
        self.freeze.assert_not_called()
        self.page.replay_controls.cancel.assert_called_once_with()
        for op in ('submit', 'replay', 'cancel', 'reconcile', 'kill'):
            with self.assertRaises(ValidationError) as caught:
                self.page.paper_job(op)
            self.assertEqual(str(caught.exception), ui_text('paper.lock.rejected'))
        self.assertEqual(self.page._stop_account, self.account)

    def test_observe_sets_persistent_manual_lock_without_starting_job(self):
        self.dialog.clickedButton.return_value = self.dialog.observe_button
        with patch.object(Path, 'exists', side_effect=[False, True]):
            self.page.kill_paper()
        self.broker.set_manual_order_lock.assert_called_once_with(True)
        self.assertEqual(len(self.broker.mock_calls), 1)
        self.freeze.assert_not_called()

    def test_bare_state_keeps_existing_order_consent_required(self):
        del self.state.manual_order_lock
        self.state.paper_confirm = Mock()
        self.state.paper_confirm.isChecked.return_value = False
        for op in ('submit', 'replay'):
            with self.assertRaises(ValidationError):
                self.page.paper_job(op)
        self.state.paper_confirm.setChecked.assert_not_called()

    def test_confirm_does_not_grant_consent_or_enable_controls(self):
        self.page.setEnabled(False)
        self.state.paper_confirm = Mock()
        self.dialog.clickedButton.return_value = self.dialog.confirm_button
        self.page.kill_paper()
        self.state.paper_confirm.setChecked.assert_not_called()
        self.assertFalse(self.page.isEnabled())

    def test_snapshot_is_read_only_authority_and_privacy_masks_amounts(self):
        self.page.privacy = SimpleNamespace(enabled=True)
        with patch.object(Path, 'exists', return_value=True), patch('quantlab.paper.PaperBroker.read_snapshot', return_value=self.account) as read:
            self.page.kill_paper()
        read.assert_called_once_with(self.state.root / 'paper.sqlite3')
        text = self.make_dialog.call_args.args[1]
        self.assertIn('TMF:202611', text)
        for secret in ('17', '9', '912345'):
            self.assertNotIn(secret, text)
        self.assertNotIn(ui_text('paper.stop.exposure').format('26'), text)
        self.freeze.assert_not_called()

    def test_plain_text_default_cancel_accessible_buttons(self):
        dialog = stop_dialog(self.page, stop_exposure_text(self.account))
        self.addCleanup(dialog.close)
        self.assertEqual(len(dialog.buttons()), 3)
        self.assertNotEqual(dialog.defaultButton(), dialog.confirm_button)
        self.assertEqual(dialog.defaultButton(), dialog.escapeButton())
        self.assertTrue(all(button.accessibleName() == button.text() for button in dialog.buttons()))

    def test_pure_format_has_every_position_side_quantity_and_gross_exposure(self):
        before = deepcopy(self.account)
        text = stop_exposure_text(self.account)
        self.assertIn(ui_text('paper.stop.position').format('TMF:202611', ui_text('paper.stop.long'), '17'), text)
        self.assertIn(ui_text('paper.stop.position').format('TMF:202612', ui_text('paper.stop.short'), '9'), text)
        self.assertIn(ui_text('paper.stop.exposure').format('26'), text)
        self.assertIn(ui_text('paper.stop.not_closed'), text)
        self.assertNotIn('ZERO', text)
        self.assertEqual(self.account, before)

    def test_host_callback_routes_to_same_confirmation_without_consent(self):
        # Load startup helpers only for the real host dispatch regression.
        from PySide6.QtCore import QTimer
        from desktop_app.shell.main_window import MainWindow
        from quantlab.desktop_runtime import AppPaths, JobManager
        from tests.test_desktop_ui_polish_b import disposable_directory
        from tests.test_t9_onboarding import sandbox_ui

        with disposable_directory() as folder, sandbox_ui():
            paths = AppPaths(Path(folder) / 'workspace', Path(folder) / 'bootstrap').ensure()
            window = MainWindow(paths, JobManager(paths))
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                window.paper_confirm.setChecked(False)
                with patch.object(window.paper_page, 'freeze_paper') as freeze:
                    window.page_host.callbacks['kill_paper']()
                    self.make_dialog.assert_called_once()
                    freeze.assert_not_called()
                self.assertFalse(window.paper_confirm.isChecked())
                self.assertFalse(window.jobs.active)
                self.dialog.clickedButton.return_value = self.dialog.observe_button
                window.paper_page.kill_paper()
                window._busy(False)
                self.assertTrue(window.paper_page.isEnabled())
                from PySide6.QtWidgets import QPushButton

                for name in ('paper_submit', 'paper_replay', 'paper_cancel', 'paper_reconcile', 'paper_manual_unlock'):
                    button = window.paper_page.findChild(QPushButton, name)
                    self.assertIsNotNone(button, name)
                    self.assertEqual(button.isEnabled(), name in ('paper_reconcile', 'paper_manual_unlock'), name)
                    self.assertTrue(button.accessibleName())
                self.assertEqual(window.paper_page.findChild(QPushButton, 'paper_manual_unlock').text(), ui_text('paper.manual_unlock'))
                window._safe(lambda: window.paper_page.paper_job('submit'))
                self.assertIn(ui_text('paper.lock.rejected'), window.status.text())
            finally:
                window.close()


class UnreadableJournalStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.test_desktop_ui_polish_b import disposable_directory
        from quantlab.reporting import write_json

        self.folder = disposable_directory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.journal = self.root / 'paper.sqlite3'
        self.journal.write_bytes(b'not a SQLite database')
        self.page = PaperPage.__new__(PaperPage)
        QWidget.__init__(self.page)
        self.addCleanup(self.page.close)
        self.state = SimpleNamespace(
            root=self.root,
            status=QLabel(),
            manual_order_lock=False,
            chatgpt_panel=SimpleNamespace(consent=Mock()),
            paper_confirm=Mock(),
            _chatgpt_job_request=None,
            chatgpt_controller=Mock(),
            guard=SimpleNamespace(reconciliation_required=False),
        )
        self.host = SimpleNamespace(state=self.state, callbacks={'_quiesce_and_recover': Mock(), 'write_json': write_json, '_paper': Mock()})
        self.page.setup_context(self.host)
        self.page.replay_controls = SimpleNamespace(cancel=Mock())
        self.dialog = SimpleNamespace(confirm_button=object(), observe_button=object(), exec=Mock(), clickedButton=Mock(return_value=None))
        factory = patch('desktop_app.features.paper.paper.stop_dialog', return_value=self.dialog)
        self.make_dialog = factory.start()
        self.addCleanup(factory.stop)

    def test_unreadable_journal_still_prompts_and_confirm_freezes_cancel_preserves_state(self):
        import sqlite3
        from contextlib import nullcontext
        from quantlab.reporting import read_json

        for patched in (False, True):
            for confirm in (False, True):
                with self.subTest(patched=patched, confirm=confirm):
                    marker = self.root / 'desktop_safety.json'
                    marker.unlink(missing_ok=True)
                    self.state.guard.reconciliation_required = False
                    self.state.status.setText('')
                    self.state.paper_confirm.reset_mock()
                    self.state.chatgpt_panel.consent.reset_mock()
                    self.page.replay_controls.cancel.reset_mock()
                    self.host.callbacks['_quiesce_and_recover'].reset_mock()
                    self.make_dialog.reset_mock()
                    self.page.privacy = SimpleNamespace(enabled=True)
                    self.dialog.clickedButton.return_value = self.dialog.confirm_button if confirm else None
                    self.dialog.exec.side_effect = lambda: self.assertFalse(marker.exists())
                    reader = patch('quantlab.paper.PaperBroker.read_snapshot', side_effect=sqlite3.DatabaseError('private journal failure'))
                    with reader if patched else nullcontext():
                        self.page.kill_paper()
                    self.make_dialog.assert_called_once()
                    text = self.make_dialog.call_args.args[1]
                    self.assertIn(ui_text('paper.stop.unknown'), text)
                    self.assertIn(ui_text('paper.stop.not_closed'), text)
                    self.assertNotIn(ui_text('paper.stop.empty'), text)
                    self.assertNotIn('private journal failure', text)
                    self.assertFalse(self.state.manual_order_lock)
                    self.assertTrue(self.page.isEnabled())
                    self.host.callbacks['_paper'].assert_not_called()
                    self.assertEqual(self.journal.read_bytes(), b'not a SQLite database')
                    if confirm:
                        self.assertEqual(read_json(marker), {'reconciliation_required': True, 'reason': ui_text('ui.kill_paper.user_emergency_stop')})
                        self.assertTrue(self.state.guard.reconciliation_required)
                        self.assertTrue(self.page.replay_controls.cancel.called)
                        self.host.callbacks['_quiesce_and_recover'].assert_called_once_with()
                        self.state.paper_confirm.setChecked.assert_called_once_with(False)
                        self.state.chatgpt_panel.consent.setChecked.assert_called_once_with(False)
                        self.assertEqual(self.state.status.text(), ui_text('ui.kill_paper.stopped_frozen'))
                    else:
                        self.assertFalse(marker.exists())
                        self.assertFalse(self.state.guard.reconciliation_required)
                        self.page.replay_controls.cancel.assert_not_called()
                        self.host.callbacks['_quiesce_and_recover'].assert_not_called()
                        self.state.paper_confirm.setChecked.assert_not_called()
                        self.state.chatgpt_panel.consent.setChecked.assert_not_called()
                        self.assertEqual(self.state.status.text(), '')

    def test_unreadable_journal_uses_cached_snapshot_and_masks_it(self):
        self.page._stop_account = {'positions': {'TMF:202611': 17}}
        for private in (False, True):
            with self.subTest(private=private):
                self.page.privacy = SimpleNamespace(enabled=private)
                self.page.kill_paper()
                text = self.make_dialog.call_args.args[1]
                self.assertEqual(text, stop_exposure_text(self.page._stop_account, private))
                if private:
                    self.assertNotIn('17', text)
        self.page.replay_controls.cancel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
