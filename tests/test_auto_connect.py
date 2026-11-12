"""Connect-on-startup switch: the preference file, and the window sending the ordinary connect command once."""

import ast
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLineEdit

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.auto_connect import MAX_ATTEMPTS
from desktop_app.features.trading.auto_preflight import REFRESH_SECONDS
from desktop_app.strings.catalog import ui_text
from quantlab.trading.adapters.storage.startup_preferences import FILE_NAME, StartupPreferences
from quantlab.trading.application.contracts import UiAction, UiReceipt
from quantlab.trading.application.preflight import PreflightFacts, build_preflight
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment
from tests import test_trading_ui as support


class StartupPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.preferences = StartupPreferences(self.temp.name)

    def test_default_is_off_and_the_switch_round_trips(self):
        self.assertFalse(self.preferences.auto_connect())
        self.preferences.set_auto_connect(True)
        self.assertTrue(StartupPreferences(self.temp.name).auto_connect())
        self.preferences.set_auto_connect(False)
        self.assertFalse(StartupPreferences(self.temp.name).auto_connect())

    def test_unreadable_or_foreign_files_mean_off(self):
        path = Path(self.temp.name) / FILE_NAME
        for body in (
            '',
            '{',
            '[]',
            '[' * 100000,
            '{"version": 2, "auto_connect": true}',
            '{"version": true, "auto_connect": true}',
            '{"version": 1, "auto_connect": "yes"}',
            '{"version": 1}',
        ):
            path.write_text(body, encoding='utf-8')
            self.assertFalse(self.preferences.auto_connect(), body[:40])

    def test_only_a_bool_is_accepted_and_a_bad_file_is_replaced(self):
        with self.assertRaises(ValueError):
            self.preferences.set_auto_connect(1)
        (Path(self.temp.name) / FILE_NAME).write_text('{', encoding='utf-8')
        self.preferences.set_auto_connect(True)
        self.assertTrue(self.preferences.auto_connect())


class AutoConnectWindowTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    drain = support.TradingUiTests.drain
    tearDown = support.TradingUiTests.tearDown

    def build(self, *, on=True, preferences=True, **view_changes):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.preferences = StartupPreferences(self.temp.name)
        if on:
            self.preferences.set_auto_connect(True)
        self.facade = support.RecordingFacade()
        view = replace(self.facade.state.sinopac_connection, **view_changes)
        self.facade.state = replace(self.facade.state, sinopac_connection=view)
        self.window = TradingWindow(self.facade, self.facade.snapshot(), startup_preferences=self.preferences if preferences else None)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.app.processEvents()

    def connects(self):
        return [command for command in self.facade.commands if command.action is UiAction.SAVE_AND_CONNECT_SINOPAC]

    def tick(self):
        self.window.refresh()
        self.drain()

    def test_it_sends_the_ordinary_connect_command_once_the_window_is_idle(self):
        self.build()
        view = self.facade.state.sinopac_connection

        def execute(command):
            # The real engine publishes CONNECTING while it accepts the command.
            self.facade.commands.append(command)
            self.facade.state = replace(self.facade.state, sinopac_connection=replace(view, phase='CONNECTING'))
            return UiReceipt(True, 'connection_pending', '')

        with patch.object(self.facade, 'execute', side_effect=execute):
            for _ in range(3):
                self.tick()
        (command,) = self.connects()
        self.assertEqual(
            (command.sinopac_settings, command.connection_revision, command.connection_generation), (view.settings, view.revision, view.generation)
        )

    # One window per test: the shared tearDown disposes exactly self.window. A window replaced inside a test
    # would stay visible and, on a real desktop, cover widgets that later tests hover with the mouse.
    def test_nothing_is_sent_without_the_switch(self):
        self.build(on=False)
        self.tick()
        self.assertEqual(self.connects(), [])

    def test_nothing_is_sent_and_the_switch_is_hidden_without_preferences(self):
        self.build(preferences=False)
        self.assertTrue(self.window.broker_panel.auto_connect.isHidden())
        self.tick()
        self.assertEqual(self.connects(), [])

    def test_a_production_target_is_never_connected_automatically(self):
        self.build(settings=SinopacConnectionSettings(environment=Environment.LIVE))
        self.tick()
        self.assertEqual(self.connects(), [])
        self.assertEqual(self.window._last_feedback, ui_text('autoconnect.skipped_live'))

    def test_a_failed_attempt_is_reported_once_and_not_repeated(self):
        # The real engine keeps the attempted environment and sets the error code when the login fails.
        self.build()
        view = self.facade.state.sinopac_connection

        def execute(command):
            self.facade.commands.append(command)
            failed = replace(view, environment=Environment.BROKER_SIMULATION, phase='DISCONNECTED', error_code='market_data_login_failed')
            self.facade.state = replace(self.facade.state, sinopac_connection=failed)
            return UiReceipt(True, 'connection_pending', '')

        with patch.object(self.facade, 'execute', side_effect=execute):
            for _ in range(4):
                self.tick()
        self.assertEqual(len(self.connects()), 1)
        self.assertTrue(self.window._last_feedback.startswith(ui_text('autoconnect.failed').split('{')[0]))

    def test_an_error_left_from_before_any_attempt_blocks_it_quietly(self):
        self.build(error_code='market_data_login_failed')
        self.tick()
        self.tick()
        self.assertEqual(self.connects(), [])

    def test_a_rejected_command_is_retried_a_bounded_number_of_times(self):
        self.build()
        with patch.object(
            self.facade, 'execute', side_effect=lambda command: (self.facade.commands.append(command), UiReceipt(False, 'state_conflict', ''))[1]
        ):
            for _ in range(MAX_ATTEMPTS + 3):
                self.tick()
        self.assertEqual(len(self.connects()), MAX_ATTEMPTS)

    def test_toggling_the_switch_saves_it_but_never_connects(self):
        self.build(on=False)
        box = self.window.broker_panel.auto_connect
        box.setChecked(True)
        self.assertTrue(self.preferences.auto_connect())
        self.tick()
        box.setChecked(False)
        self.assertFalse(self.preferences.auto_connect())
        self.assertEqual(self.connects(), [])

    def test_a_save_failure_puts_the_switch_back_and_says_so(self):
        self.build(on=False)
        box = self.window.broker_panel.auto_connect
        with patch.object(self.preferences, 'set_auto_connect', side_effect=OSError('locked')):
            box.setChecked(True)
        self.assertFalse(box.isChecked())
        self.assertEqual(self.window._last_feedback, ui_text('autoconnect.save_failed'))


class AutoPreflightTests(unittest.TestCase):
    """The pre-open checklist fills itself in with a read-only preview; it never records anything on its own."""

    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    drain = support.TradingUiTests.drain
    tearDown = support.TradingUiTests.tearDown

    def build(self, *, facts=PreflightFacts(True, True, True, True, True, True, True), recorded=None, **state_changes):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = support.RecordingFacade()
        self.facade.state = replace(self.facade.state, **state_changes)
        if recorded is not None:
            state = self.facade.state
            row = build_preflight(state.account_ref, date.fromisoformat(state.trading_day), datetime.now(timezone.utc), state.environment, recorded)
            self.facade.state = replace(state, preflight=(row,))
        self.facts = facts
        self.answer(self.facade.execute)
        self.window = TradingWindow(self.facade, self.facade.snapshot(), auto_preflight=True)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.now = [1000.0]
        self.window.auto_preflight.clock = lambda: self.now[0]
        self.window.show()
        self.app.processEvents()

    def answer(self, inner):
        """Like the engine: a preview carries the checklist in its receipt and changes nothing."""

        def execute(command):
            receipt = inner(command)
            if command.action is UiAction.PREVIEW_PREFLIGHT:
                state = self.facade.state
                view = build_preflight(state.account_ref, date.fromisoformat(state.trading_day), datetime.now(timezone.utc), state.environment, self.facts)
                return UiReceipt(True, 'completed', '', '', view)
            return receipt

        patcher = patch.object(self.facade, 'execute', side_effect=execute)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self, action):
        return [command for command in self.facade.commands if command.action is action]

    def tick(self, times=1):
        for _ in range(times):
            self.window.refresh()
            self.drain()

    def row(self, key):
        return self.window.automatic_controls.checks[key].text()

    def test_the_first_poll_previews_and_never_records(self):
        self.build()
        self.tick(4)
        (command,) = self.sent(UiAction.PREVIEW_PREFLIGHT)
        self.assertEqual(command.account_ref, self.facade.state.account_ref)
        # Recording belongs to the owner click and the daily admission, never to the window on its own.
        self.assertEqual(self.sent(UiAction.CHECK_PREFLIGHT), [])

    def test_the_checklist_shows_the_preview_and_says_it_is_only_a_preview(self):
        self.build(facts=PreflightFacts(False, True, True, True, True, True, True))
        self.assertEqual(self.row('connection'), ui_text('u4.not_checked'))
        self.tick(2)
        self.assertNotEqual(self.row('connection'), ui_text('u4.not_checked'))
        self.assertEqual(self.row('account'), ui_text('u4.passed'))
        self.assertTrue(self.window.automatic_controls.preview_note.isVisibleTo(self.window))
        self.assertEqual(self.window.automatic_controls.preview_note.text(), ui_text('preflight.preview_note'))

    def test_a_recorded_checklist_is_never_replaced_by_a_preview(self):
        self.build(recorded=PreflightFacts(False, True, True, True, True, True, True))
        self.tick(3)
        self.assertEqual(self.sent(UiAction.PREVIEW_PREFLIGHT), [])
        self.assertFalse(self.window.automatic_controls.preview_note.isVisibleTo(self.window))
        self.assertNotEqual(self.row('connection'), ui_text('u4.passed'))

    def test_it_asks_again_when_the_situation_changes_or_after_the_refresh_interval_only(self):
        self.build()
        self.tick(3)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 1)
        self.now[0] += REFRESH_SECONDS - 1
        self.tick(2)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 1)
        self.now[0] += 2
        self.tick(2)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 2)
        connected = replace(self.facade.state.sinopac_connection, phase='CONNECTED')
        self.facade.state = replace(self.facade.state, sinopac_connection=connected)
        self.tick(3)  # the first poll adopts the new state, the next one sees the change at once
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 3)
        self.facade.state = replace(self.facade.state, trading_day='2099-01-04')
        self.tick(3)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 4)

    def test_a_refused_preview_leaves_the_checklist_alone_and_waits_for_the_next_turn(self):
        self.build()
        refuse = lambda command: self.facade.commands.append(command) or UiReceipt(False, 'capability_missing', '')  # noqa: E731
        with patch.object(self.facade, 'execute', side_effect=refuse):
            self.tick(6)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 1)
        self.assertEqual(self.row('connection'), ui_text('u4.not_checked'))
        self.assertFalse(self.window.automatic_controls.preview_note.isVisibleTo(self.window))

    def test_nothing_is_sent_without_an_account_or_while_a_command_is_running(self):
        self.build(account_ref='')
        self.tick(2)
        self.assertEqual(self.sent(UiAction.PREVIEW_PREFLIGHT), [])
        self.window.state = replace(self.window.state, account_ref='local-stock')
        self.window._operation = SimpleNamespace(command=None)
        self.assertFalse(self.window.auto_preflight.step(self.window))
        self.window._operation = None
        self.window._priority_operation = SimpleNamespace(command=None)
        self.assertFalse(self.window.auto_preflight.step(self.window))
        self.window._priority_operation = None
        self.window._engine_reachable = False
        self.assertFalse(self.window.auto_preflight.step(self.window))
        self.window._engine_reachable = True
        self.assertEqual(self.sent(UiAction.PREVIEW_PREFLIGHT), [])

    def test_it_waits_while_the_user_is_typing_in_a_field(self):
        self.build()
        field = self.window.broker_panel.auto_connect.parent().findChild(QLineEdit)
        field.setFocus()
        self.app.processEvents()
        self.assertTrue(field.hasFocus())
        self.tick(2)
        self.assertEqual(self.sent(UiAction.PREVIEW_PREFLIGHT), [])
        field.clearFocus()
        self.window.setFocus()
        self.app.processEvents()
        self.tick(2)
        self.assertEqual(len(self.sent(UiAction.PREVIEW_PREFLIGHT)), 1)

    def test_the_message_line_is_left_alone_and_the_next_user_command_is_not_silenced(self):
        self.build()
        self.window._feedback('keep me')
        self.tick(2)
        self.assertEqual(self.window._last_feedback, 'keep me')
        self.assertFalse(self.window._quiet_next)
        self.window.command(UiAction.CHECK_PREFLIGHT, account_ref=self.window.state.account_ref)
        self.drain()
        self.assertNotEqual(self.window._last_feedback, 'keep me')

    def test_windows_built_by_tests_never_act_on_their_own_and_the_real_runtime_turns_it_on(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = support.RecordingFacade()
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.assertIsNone(self.window.auto_preflight)
        self.window.refresh()
        self.drain()
        self.assertEqual(self.sent(UiAction.PREVIEW_PREFLIGHT), [])
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'trading_runtime.py').read_text(encoding='utf-8'))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'TradingWindow']
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(item.arg == 'auto_preflight' and isinstance(item.value, ast.Constant) and item.value.value is True for item in calls[0].keywords))


if __name__ == '__main__':
    unittest.main()
