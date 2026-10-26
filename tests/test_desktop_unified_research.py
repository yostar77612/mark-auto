"""One-window original research behavior, session preservation and failure gates.

Offline synthetic fixtures; no subscription, credential store or brokerage use.
"""

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_research_runtime import ResearchSession, ResearchUnavailable, UnifiedResearch
from desktop_strings import ui_text
from desktop_trading import TradingWindow
from quantlab.desktop_runtime import WorkspaceLocator
from tests.test_trading_ui import RecordingFacade


class UnifiedResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bootstrap = Path(self.tmp.name) / 'original-bootstrap'
        self.session = ResearchSession(bootstrap=self.bootstrap, restore_login=False)
        self.facade = RecordingFacade()
        self.outer = TradingWindow(self.facade, self.facade.snapshot())
        self.outer.poll.stop()
        self.outer.setProperty('allow_close_for_tests', True)
        self.integration = UnifiedResearch(self.outer, session=self.session)
        self.outer.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.session.state is not None and self.session.state.jobs is not None:
            self.session.state.jobs.close()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            accepted = self.outer.close()
        self.app.processEvents()
        if accepted:
            self.outer.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_job(self, timeout=30):
        jobs = self.session.state.jobs
        deadline = time.monotonic() + timeout
        while jobs.active and time.monotonic() < deadline:
            self.app.processEvents()
            self.session.window.poll_jobs()
            time.sleep(0.02)
        self.session.window.poll_jobs()
        self.assertFalse(jobs.active, 'original research worker exceeded unchanged job bound')

    def test_one_window_routes_every_original_page_with_same_session(self):
        self.assertIsNotNone(self.session.window)
        original = self.session.window
        self.assertFalse(original.isWindow())
        self.assertTrue(self.outer.isAncestorOf(original))
        self.assertEqual(self.outer.navigation.count(), 6)
        self.assertFalse(original.navigation.isVisible())
        from desktop_pages.palette_commands import page_index

        with patch('subprocess.Popen', side_effect=AssertionError('navigation must not launch a second desktop')):
            for route, (workspace, page) in self.integration.panel.ROUTES.items():
                self.integration.show(route)
                self.app.processEvents()
                self.assertEqual(self.outer.navigation.currentRow(), workspace)
                self.assertIs(self.outer.pages.currentWidget(), self.integration.panel)
                self.assertEqual(original.navigation.currentRow(), page_index(original, page))
                self.assertIs(self.session.open(), original)
        self.assertEqual(self.facade.commands, [])

    def test_existing_cross_page_actions_stay_in_the_integrated_workspace(self):
        self.integration.show('strategy')
        from desktop_pages.palette_commands import page_index

        self.session.window.navigation.setCurrentRow(page_index(self.session.window, 'data'))
        self.assertEqual(self.outer.navigation.currentRow(), 2)
        self.assertEqual(self.integration.panel.choice.currentData(), 'data')
        self.integration.panel.back.click()
        self.assertEqual(self.outer.pages.currentIndex(), 2)

    def test_clicking_current_workspace_exits_its_embedded_research_tool(self):
        self.integration.show('connection')
        self.app.processEvents()
        item = self.outer.navigation.item(5)
        self.assertEqual(self.outer.navigation.currentRow(), 5)
        QTest.mouseClick(self.outer.navigation.viewport(), Qt.MouseButton.LeftButton, pos=self.outer.navigation.visualItemRect(item).center())
        self.app.processEvents()
        self.assertEqual(self.outer.pages.currentIndex(), 5)

    def test_login_entry_uses_same_controller_and_updates_connection_status(self):
        host = self.session.window
        self.outer.chatgpt_button.click()
        self.assertEqual(self.integration.panel.choice.currentData(), 'connection')
        self.assertTrue(host.settings_page.connection_toggle.isChecked())
        self.assertFalse(host.chatgpt_panel.consent.isChecked())
        host.chatgpt_controller.state = 'plan_ready'
        host.chatgpt_controller.changed.emit()
        self.assertEqual(self.outer.chatgpt_button.text(), ui_text('redesign.header.connected'))
        self.assertEqual(self.outer.chatgpt_button.accessibleName(), ui_text('redesign.header.connected'))
        host.chatgpt_controller.state = 'unknown'
        host.chatgpt_controller.changed.emit()
        self.assertEqual(self.outer.chatgpt_button.text(), ui_text('redesign.header.connection'))
        self.assertFalse(self.session.state.jobs.active)

    def test_real_original_worker_demo_backtest_and_settings_survive_routes(self):
        host = self.session.window
        self.integration.show('data')
        host.start_job('ui_demo', {})
        self.wait_job()
        dataset = host.paths.state / 'dataset.json'
        self.assertTrue(dataset.is_file())
        before = dataset.read_bytes()
        self.integration.show('strategy')
        host.provider_mode.setCurrentIndex(host.provider_mode.findData('fixture'))
        self.integration.show('backtest')
        host.run_button.click()
        self.wait_job()
        self.assertTrue((host.paths.state / 'active_result.json').exists())
        self.assertEqual(dataset.read_bytes(), before)
        self.integration.show('settings')
        self.assertIs(host.settings, self.session.state.settings)
        self.assertEqual(self.facade.commands, [])

    def test_existing_workspace_pointer_settings_and_credential_reference_are_not_migrated(self):
        # Fixture-only opaque credential bytes: never a real credential lookup.
        host = self.session.window
        marker = self.bootstrap / 'credentials' / 'fixture-opaque'
        marker.parent.mkdir(exist_ok=True)
        marker.write_bytes(b'opaque preservation fixture')
        pointer = WorkspaceLocator(self.bootstrap).pointer
        prior = pointer.read_bytes() if pointer.exists() else None
        settings = host.settings.path if hasattr(host.settings, 'path') else host.paths.state / 'settings.json'
        host.settings.save({'fixture_unknown_preference': 'preserve'})
        original_settings = settings.read_bytes()
        for page in self.integration.panel.ROUTES:
            self.integration.show(page)
        self.assertEqual(marker.read_bytes(), b'opaque preservation fixture')
        self.assertEqual(settings.read_bytes(), original_settings)
        self.assertEqual(pointer.read_bytes() if pointer.exists() else None, prior)

    def test_original_single_writer_lock_refuses_duplicate_and_release_allows_reopen(self):
        other = ResearchSession(bootstrap=self.bootstrap, restore_login=False)
        with self.assertRaises(ResearchUnavailable):
            other.open()
        self.assertFalse(other._released)
        self.assertTrue(self.session.request_close())
        host = other.open()
        self.assertEqual(host.paths.root, self.session.state.paths.root)
        self.assertTrue(other.request_close())
        host.deleteLater()

    def test_embedded_resize_and_close_preserve_original_window_settings_and_business_preferences(self):
        from quantlab.desktop_runtime import SettingsStore

        host = self.session.window
        original = SettingsStore(host.paths.state / 'settings.json')
        geometry = {'x': 73, 'y': 41, 'width': 1366, 'height': 768}
        original.save({'window': geometry, 'fixture_business_preference': 'preserve'})
        host.resize(700, 400)
        host.save_market_preferences()
        self.assertEqual(original.load()['window'], geometry)
        self.assertEqual(original.load()['fixture_business_preference'], 'preserve')
        host.settings.save({**original.load(), 'fixture_business_preference': 'explicit user update'})
        self.assertEqual(original.load()['window'], geometry)
        self.assertEqual(original.load()['fixture_business_preference'], 'explicit user update')
        self.assertTrue(self.session.request_close())
        self.assertEqual(original.load()['window'], geometry)

    def test_original_refused_close_keeps_outer_timer_and_lock_alive(self):
        with patch.object(self.session.window, 'close', return_value=False):
            self.assertFalse(self.outer.close())
        self.assertFalse(self.session._released)
        contender = QLockFile(str(WorkspaceLocator(self.bootstrap).lock_path))
        contender.setStaleLockTime(0)
        self.assertFalse(contender.tryLock(0))
        self.assertTrue(self.outer.isVisible())

    def test_global_research_cancel_uses_original_pending_gate_and_never_sends_trade_commands(self):
        import json

        host = self.session.window
        host.chatgpt_controller.busy = True
        host.job_progress.begin()
        self.integration.refresh_connection()
        self.assertTrue(self.outer.cancel_research_button.isEnabled())
        self.outer.cancel_research_button.click()
        safety = json.loads((host.paths.state / 'desktop_safety.json').read_text(encoding='utf-8'))
        self.assertTrue(safety['reconciliation_required'])
        self.assertEqual(safety['reason'], ui_text('ui.cancel_and_recover.user_cancel'))
        self.assertEqual(host.status.text(), ui_text('job.cancel_notice'))
        self.assertFalse(self.outer.cancel_research_button.isEnabled())
        self.assertTrue(host.job_progress.cancel_pending)
        host.status.setText('post-cancellation status')
        host.chatgpt_controller.busy = True
        self.integration.cancel_research()
        self.assertEqual(host.status.text(), 'post-cancellation status')
        self.assertEqual(self.facade.commands, [])
        host.chatgpt_controller.busy = False

    def test_assistant_is_directly_reachable_and_original_readonly_fixture_reply_works(self):
        self.outer.ai_assistant_button.click()
        self.app.processEvents()
        assistant = self.session.window.settings_page.assistant_panel
        self.assertEqual(self.integration.panel.choice.currentData(), 'assistant')
        self.assertTrue(self.session.window.settings_page.maintenance_toggle.isChecked())
        self.assertTrue(assistant.isVisible())
        # The original assistant requires a discovered model even in fixture
        # mode. Supply explicit offline fixture discovery; never bypass its gate.
        self.session.window.chatgpt_controller.models = ('offline-fixture',)
        self.session.window.chatgpt_controller.changed.emit()
        assistant.mode.setCurrentIndex(assistant.mode.findData('fixture'))
        self.assertTrue(assistant.send.isEnabled())
        assistant.input.setText('Explain the available training research status')
        assistant.send.click()
        self.assertTrue(assistant.transcript.toPlainText())
        self.assertFalse(assistant.worker.active)
        self.assertEqual(self.facade.commands, [])

    def test_unjoined_assistant_refuses_outer_close_and_retains_writer_lock(self):
        assistant = self.session.window.settings_page.assistant_panel
        with patch.object(assistant, 'cancel', side_effect=RuntimeError('controlled unjoined worker')):
            self.assertFalse(self.outer.close())
        self.assertFalse(self.session._released)
        self.assertEqual(self.session.window.status.text(), ui_text('ui.close_event.stop_unconfirmed'))
        self.assertTrue(self.outer.isVisible())

    def test_loading_failure_is_visible_and_keeps_multimarket_usable(self):
        self.integration._host = None
        with patch.object(self.session, 'open', side_effect=OSError('private path never display')):
            self.integration.show('strategy')
        self.assertIn(ui_text('unified.research_unavailable'), self.integration.panel.error.text())
        self.assertNotIn('private path', self.integration.panel.error.text())
        self.integration.back()
        self.assertEqual(self.outer.pages.currentIndex(), 1)
        self.assertEqual(self.facade.commands, [])

    def test_async_original_reconciliation_must_finish_before_outer_closes(self):
        host = self.session.window
        host._close_after_reconcile = True
        with patch.object(self.session, 'request_close', return_value=False):
            self.assertFalse(self.outer.close())
        self.assertTrue(self.integration._pending_close)
        self.assertTrue(self.outer.isVisible())
        with patch.object(self.outer, 'close') as retry:
            self.session.released.emit()
            self.app.processEvents()
            retry.assert_called_once_with()
        host._close_after_reconcile = False

    def test_normal_and_existing_multi_market_entry_use_same_unified_composition(self):
        import desktop

        with patch('trading_runtime.run_window', return_value=23) as launch, patch.object(desktop, 'run_gui') as legacy:
            self.assertEqual(desktop.launch([]), 23)
            self.assertEqual(desktop.launch(['--platform-v2']), 23)
            self.assertEqual(launch.call_count, 2)
            legacy.assert_not_called()

    def test_original_workspace_close_disables_research_before_outer_close(self):
        host = self.session.window
        with patch.object(self.outer, 'close') as close_outer:
            self.assertTrue(host.close())
            self.assertFalse(host.isEnabled())
            self.assertTrue(self.session._released)
            self.assertFalse(host.automatic_backup_panel.timer.isActive())
            self.assertFalse(host.timer.isActive())
            self.assertFalse(self.integration.ensure_open())
            self.app.processEvents()
            close_outer.assert_called_once_with()

    def test_explicit_isolated_bootstrap_is_not_accepted_for_legacy_smoke(self):
        import desktop
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            desktop.parse_args(['--research-bootstrap', str(self.bootstrap)])
        parsed = desktop.parse_args(['--platform-v2', '--research-bootstrap', str(self.bootstrap)])
        self.assertEqual(parsed.research_bootstrap, self.bootstrap)


if __name__ == '__main__':
    unittest.main()
