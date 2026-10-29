"""Offline main-window lifetime tests for explicit shared primary sign-in."""

import json
import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from tests import test_desktop_ui as support


@unittest.skipUnless(support.HAS_QT, 'Pinned Qt needed')
class PrimarySignInHostTests(unittest.TestCase):
    setUpClass = support.NativeDesktopTests.__dict__['setUpClass']
    setUp = support.NativeDesktopTests.setUp
    cleanup_window = support.NativeDesktopTests.cleanup_window

    def queue_after_local_list(self, launch):
        from desktop_app.features.assistant.connection import ConnectionEvent

        w = self.window
        c = w.chatgpt_controller
        p = w.chatgpt_panel
        w.timer.stop()
        w.automatic_backup_panel.timer.stop()
        w.show_chatgpt_sign_in()
        self.assertEqual(launch.call_count, 1)
        request = c._request
        self.assertEqual(request.action, 'list')
        event = ConnectionEvent(request.request_id, 'result', 'disconnected')
        w._chatgpt_event({'job_id': 'fixture-list', 'type': 'result', 'result': {'auth_event': json.loads(json.dumps(asdict(event)))}})
        self.assertFalse(c.busy)
        self.assertIsNotNone(p._primary_flow)
        self.assertEqual(p._primary_flow['phase'], 'list')
        return p._primary_flow

    def test_parent_close_in_post_join_gap_cannot_launch_or_open_browser(self):
        w = self.window
        with patch.object(self.jobs, 'start', return_value='fixture-list') as launch, patch('PySide6.QtGui.QDesktopServices.openUrl') as browser:
            self.queue_after_local_list(launch)
            event = Mock()
            w.closeEvent(event)
            event.accept.assert_called_once()
            self.app.processEvents()
            self.assertEqual(launch.call_count, 1)
            browser.assert_not_called()
        self.assertIsNone(w.chatgpt_panel._primary_flow)
        self.assertFalse(w.chatgpt_controller.host_available)

    def test_failed_close_reenables_host_without_resuming_abandoned_login(self):
        w = self.window
        with patch.object(self.jobs, 'start', return_value='fixture-list') as launch, patch('PySide6.QtGui.QDesktopServices.openUrl') as browser:
            self.queue_after_local_list(launch)
            event = Mock()
            with patch.object(self.jobs, 'close', side_effect=RuntimeError('inert close failure')):
                w.closeEvent(event)
            event.ignore.assert_called_once()
            event.accept.assert_not_called()
            self.assertTrue(w.chatgpt_controller.host_available)
            self.app.processEvents()
            self.assertEqual(launch.call_count, 1)
            browser.assert_not_called()
            self.assertIsNone(w.chatgpt_panel._primary_flow)

    def test_deferred_close_blocks_new_signin_and_browser_until_reconciliation(self):
        from tests.test_desktop_chatgpt_ui import authorization_url

        w = self.window
        w._subscription_campaign = True
        w._plan_launch = {'config': {}, 'provider': {'mode': 'chatgpt_plan'}, 'binding': 'inert', 'stopped_job_id': 'old'}
        event = Mock()
        with patch.object(w, 'start_job', return_value='local-reconcile') as start, patch('PySide6.QtGui.QDesktopServices.openUrl') as browser:
            w.closeEvent(event)
            event.ignore.assert_called_once()
            event.accept.assert_not_called()
            self.assertFalse(w.chatgpt_controller.host_available)
            self.assertFalse(w.chatgpt_panel.primary_sign_in.isEnabled())
            w._chatgpt_open_browser(authorization_url())
            browser.assert_not_called()
            self.assertEqual(start.call_count, 1)
        w._close_after_reconcile = False

    def test_user_cancel_freeze_and_quiesce_in_gap_abandon_next_login_step(self):
        for action in ('cancel', 'freeze', 'quiesce', 'restore', 'workspace'):
            with (
                self.subTest(action=action),
                patch.object(self.jobs, 'start', return_value='fixture-list') as launch,
                patch('PySide6.QtGui.QDesktopServices.openUrl') as browser,
            ):
                self.queue_after_local_list(launch)
                if action == 'cancel':
                    self.window.cancel_job()
                elif action == 'freeze':
                    self.window.freeze_paper('offline suspend fixture')
                elif action == 'quiesce':
                    self.window._quiesce_and_recover()
                elif action == 'restore':
                    with self.assertRaises(ValueError):
                        self.window.backup(True)
                else:
                    with patch('quantlab.desktop_runtime.WorkspaceLocator.configure', return_value=self.paths.root):
                        self.window.configure_workspace()
                self.app.processEvents()
                self.assertEqual(launch.call_count, 1)
                browser.assert_not_called()
                self.assertIsNone(self.window.chatgpt_panel._primary_flow)

    def test_unrelated_job_or_tab_hide_cannot_leave_queued_login(self):
        for action in ('job', 'tab'):
            with (
                self.subTest(action=action),
                patch.object(self.jobs, 'start', return_value='fixture-list') as launch,
                patch('PySide6.QtGui.QDesktopServices.openUrl') as browser,
            ):
                self.queue_after_local_list(launch)
                if action == 'job':
                    self.window.start_job('ui_demo', {})
                else:
                    self.window.navigation.setCurrentRow(5)
                self.app.processEvents()
                self.assertEqual(launch.call_count, 2 if action == 'job' else 1)
                if action == 'job':
                    self.assertEqual(launch.call_args.args, ('ui_demo', {}))
                browser.assert_not_called()
                self.assertIsNone(self.window.chatgpt_panel._primary_flow)

    def test_automatic_backup_defers_during_joined_list_gap(self):
        panel = self.window.automatic_backup_panel
        panel.enabled.setChecked(True)
        panel.directory.setText(str(self.paths.root.parent / 'archives'))
        panel.save()
        with patch.object(self.jobs, 'start', return_value='fixture-list') as launch:
            self.queue_after_local_list(launch)
            self.assertTrue(self.window.chatgpt_panel.primary_sign_in_pending)
            panel.tick()
            self.assertIsNone(panel.scheduler.load()['last_attempt_day'])
            self.assertIsNone(panel.archive)
            self.assertEqual(launch.call_count, 1)
            self.window.chatgpt_panel.abandon_primary_sign_in()
            self.app.processEvents()

    def test_intended_auth_quiescence_keeps_same_flow_and_dispatches_once(self):
        from desktop_app.features.assistant.connection import ConnectionEvent
        from tests.test_desktop_chatgpt_ui import authorization_url

        w = self.window
        c = w.chatgpt_controller
        p = w.chatgpt_panel
        with (
            patch.object(self.jobs, 'start', return_value='fixture-list') as launch,
            patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=True) as browser,
        ):
            flow = self.queue_after_local_list(launch)
            self.app.processEvents()
            self.assertEqual(launch.call_count, 2)
            self.assertIs(p._primary_flow, flow)
            self.assertEqual(c._request.action, 'begin')
            self.assertTrue(c._request.user_confirmed)
            request = c._request
            w._chatgpt_event(
                {
                    'job_id': 'fixture-list',
                    'type': 'auth_progress',
                    'auth_event': json.loads(
                        json.dumps(asdict(ConnectionEvent(request.request_id, 'authorization', 'authorizing', authorization_url=authorization_url())))
                    ),
                }
            )
            self.app.processEvents()
            self.app.processEvents()
            browser.assert_called_once()
            self.assertEqual(browser.call_args.args[0].host(), 'auth.openai.com')
            w._chatgpt_cancel(request.request_id)
            self.assertIsNone(p._primary_flow)

    def test_cancel_after_url_queued_prevents_browser_open(self):
        from desktop_app.features.assistant.connection import ConnectionEvent
        from tests.test_desktop_chatgpt_ui import authorization_url

        w = self.window
        c = w.chatgpt_controller
        with patch.object(self.jobs, 'start', return_value='fixture-list') as launch, patch('PySide6.QtGui.QDesktopServices.openUrl') as browser:
            self.queue_after_local_list(launch)
            self.app.processEvents()
            request = c._request
            w._chatgpt_event(
                {
                    'job_id': 'fixture-list',
                    'type': 'auth_progress',
                    'auth_event': asdict(ConnectionEvent(request.request_id, 'authorization', 'authorizing', authorization_url=authorization_url())),
                }
            )
            w.cancel_job()
            self.app.processEvents()
            browser.assert_not_called()
            self.assertIsNone(w.chatgpt_panel._primary_flow)


if __name__ == '__main__':
    unittest.main()
