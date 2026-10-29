"""Offline UI hierarchy checks preserve paper gates and the existing settings state."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QComboBox, QPushButton

from desktop_app.strings.catalog import ui_text
from tests import test_settings_sections as support


class PaperSettingsRedesignTests(unittest.TestCase):
    setUpClass = support.SettingsSectionsTests.__dict__['setUpClass']
    setUp = support.SettingsSectionsTests.setUp

    def paper(self):
        page = self.window.paper_page
        for index in range(self.window.stack.count()):
            if self.window.stack.widget(index).isAncestorOf(page):
                self.window.navigation.setCurrentRow(index)
                break
        self.app.processEvents()
        return page

    def test_preparation_stays_honest_and_recovery_actions_remain_reachable(self):
        from desktop_app.features.paper.paper_readiness import refresh_readiness

        page = self.paper()
        self.assertEqual(page.readiness_selection.text(), ui_text('redesign.paper.no_selection'))
        self.assertEqual(page.readiness_next.text(), ui_text('redesign.paper.next_empty'))
        self.assertFalse(page.paper_risk_summary.isVisibleTo(page))
        self.assertFalse(page.policy_form.isVisibleTo(page))
        self.assertFalse(page.intent_form.isVisibleTo(page))
        self.assertTrue(page.account_tabs.isVisibleTo(page))
        for name in ('paper_snapshot', 'paper_reconcile', 'paper_manual_unlock', 'paper_replay', 'paper_kill'):
            self.assertTrue(page.findChild(QPushButton, name).isVisibleTo(page), name)
        page.page_state.manual_order_lock = True
        page._apply_order_lock()
        self.assertEqual(page.readiness_next.text(), ui_text('redesign.paper.next_locked'))
        self.assertFalse(page.findChild(QPushButton, 'paper_replay').isEnabled())
        self.assertTrue(page.findChild(QPushButton, 'paper_manual_unlock').isEnabled())
        for name in ('paper_submit', 'paper_replay', 'paper_cancel'):
            button = page.findChild(QPushButton, name)
            self.assertIn(ui_text('paper.lock.rejected'), button.property('disabled_hint'), name)
            self.assertEqual(button.toolTip(), button.property('disabled_hint'), name)
            self.assertNotIn(ui_text('ui_polish.install_polish.idle_prerequisite'), button.toolTip(), name)
        with patch.object(self.window, 'jobs', SimpleNamespace(active=True)):
            for hint in self.window._disabled_hints:
                if hint.button.objectName() in ('paper_submit', 'paper_replay', 'paper_cancel'):
                    hint.update()
                    self.assertIn(ui_text('paper.lock.rejected'), hint.button.toolTip())
        page.page_state.manual_order_lock = False
        page._apply_order_lock()
        self.assertEqual(page.findChild(QPushButton, 'paper_replay').property('disabled_hint'), '')
        refresh_readiness(page)
        self.assertEqual(page.readiness_next.text(), ui_text('redesign.paper.next_empty'))

    def test_paced_replay_controls_are_in_the_visible_session(self):
        page = self.paper()
        replay = page.replay_controls
        self.assertTrue(replay.speed.isVisibleTo(page))
        replay._show_session(True)
        self.app.processEvents()
        for widget in (replay.button, replay.stop_button, replay.label):
            self.assertTrue(widget.isVisibleTo(page))
        replay.cancel()
        self.assertFalse(replay.button.isVisibleTo(page))
        self.assertFalse(replay.stop_button.isVisibleTo(page))

    def test_readiness_tracks_active_and_paused_work_without_inviting_another_start(self):
        from desktop_app.features.paper.paper_readiness import refresh_readiness

        page = self.paper()
        with patch.object(page.page_state, 'jobs', SimpleNamespace(active=True)):
            refresh_readiness(page)
            self.assertEqual(page.readiness_next.text(), ui_text('ui.start_job.running'))
            page.replay_controls.running = True
            page.replay_controls.paused = False
            refresh_readiness(page)
            self.assertEqual(page.readiness_next.text(), ui_text('replay.running'))
            page.replay_controls.paused = True
            refresh_readiness(page)
            self.assertEqual(page.readiness_next.text(), ui_text('replay.paused'))
        page.replay_controls.cancel()
        self.assertEqual(page.readiness_next.text(), ui_text('redesign.paper.next_empty'))

    def test_reopened_journal_keeps_manual_lock_and_shows_reconciliation_next_step(self):
        from quantlab.paper import PaperBroker
        from tests import test_paper as fixtures
        from tests.test_paper_lock_b2 import ScratchDirectory

        fixture = fixtures.PaperTests()
        with patch.object(fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        broker = fixture.broker
        broker.set_manual_order_lock(True)
        fresh = PaperBroker(broker.path, **fixture.kw)
        page = self.paper()
        page._show_account(fresh.snapshot())
        self.assertEqual(page.readiness_next.text(), ui_text('redesign.paper.next_locked'))
        self.assertEqual(page.readiness_account.text(), ui_text('redesign.paper.account_pending'))
        self.assertFalse(page.findChild(QPushButton, 'paper_replay').isEnabled())
        self.assertTrue(page.findChild(QPushButton, 'paper_manual_unlock').isEnabled())
        self.assertIn(ui_text('paper.lock.rejected'), page.findChild(QPushButton, 'paper_replay').property('disabled_hint'))

    def test_known_risk_halt_overrides_the_start_prompt(self):
        from desktop_app.features.paper.paper_readiness import refresh_readiness
        from quantlab.desktop_feedback import stop_presentation

        page = self.paper()
        for account in ({'consecutive_loss_halt': True}, {'quarantined': {'event': 'unresolved'}}):
            page._stop_account = account
            refresh_readiness(page)
            self.assertEqual(page.readiness_next.text(), stop_presentation(account)[0])
            self.assertNotEqual(page.readiness_next.text(), ui_text('redesign.paper.next_ready'))

    def test_common_preferences_visible_and_logs_open_only_on_request(self):
        page = self.page
        self.assertTrue(page.local_notifications.isVisibleTo(page))
        for name in ('appearance_theme', 'appearance_convention', 'privacy_toggle'):
            self.assertTrue(self.window.findChild(QComboBox if name != 'privacy_toggle' else type(page.local_notifications), name).isVisibleTo(page), name)
        self.assertFalse(page.log_view.isVisibleTo(page))
        self.assertFalse(page.persist_logs.isVisibleTo(page))
        self.assertFalse(page.workspace_path.isVisibleTo(page))
        self.assertTrue(page.findChild(QPushButton, 'create_backup').isVisibleTo(page))
        page.logs_toggle.setChecked(True)
        self.assertTrue(page.log_view.isVisibleTo(page))
        page.logs_toggle.setChecked(False)
        self.assertFalse(page.log_view.isVisibleTo(page))

    def test_backup_destination_cancel_never_schedules_a_job(self):
        from desktop_app.features.settings.settings_layout import choose_backup

        page = self.page
        with patch.object(page.host, 'save_file', return_value=('', '')), patch.object(page, 'backup') as backup:
            choose_backup(page)
        backup.assert_not_called()
        page.backup_path.setText('isolated-review.zip')
        with patch.object(page.host, 'save_file') as chooser, patch.object(page, 'backup') as backup:
            choose_backup(page)
        chooser.assert_not_called()
        backup.assert_called_once_with(False)


if __name__ == '__main__':
    unittest.main()
