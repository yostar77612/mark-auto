"""Connect-on-startup switch: the preference file, and the window sending the ordinary connect command once."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.auto_connect import MAX_ATTEMPTS
from desktop_app.strings.catalog import ui_text
from quantlab.trading.adapters.storage.startup_preferences import FILE_NAME, StartupPreferences
from quantlab.trading.application.contracts import UiAction, UiReceipt
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


if __name__ == '__main__':
    unittest.main()
