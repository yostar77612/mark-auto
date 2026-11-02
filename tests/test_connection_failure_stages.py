"""Sanitized failure stages preserve existing login, cleanup and readonly behavior."""

import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.validation import DomainError
from desktop_app.features.trading.sinopac_panel_text import reason_text
from desktop_app.strings.catalog import ui_text
from tests import test_sinopac_connection as connection
from tests import test_market_session as market
from tests import test_market_terminal_ui as terminal
from quantlab.trading.runtime.market_connection import MarketConnection
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.application.contracts import UiCommand


class StandaloneConnectionStages(unittest.TestCase):
    def test_post_connect_initialization_failure_keeps_cleanup_and_stage(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            calls = []
            fake = SimpleNamespace(connected=False)

            def connect():
                calls.append('connect')
                fake.connected = True

            def disconnect():
                calls.append('disconnect')
                fake.connected = False

            def initialize(session):
                calls.append('initialize')
                raise ValueError('SECRET')

            fake.connect, fake.disconnect = connect, disconnect
            controller = MarketConnection(Path(folder), lambda *args: fake)
            controller.on_connected = initialize
            controller.execute(UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 0, market_data_settings=MarketDataSettings(enabled=True)))
            controller.execute(UiCommand(UiAction.CONNECT_MARKET_DATA, 0))
            controller.worker.join(1)
            self.assertFalse(controller.worker.is_alive())
            self.assertEqual(controller.connection_status(), 'DISCONNECTED')
            self.assertEqual(controller.error, 'broker_initialization_failed')
            self.assertIsNone(controller.session)
            self.assertEqual(calls, ['connect', 'initialize', 'disconnect'])

    def test_failed_standalone_connect_retains_login_error(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            calls = []

            def connect():
                calls.append('connect')
                raise RuntimeError('SECRET')

            fake = SimpleNamespace(connected=False, connect=connect, disconnect=lambda: calls.append('disconnect'))
            controller = MarketConnection(Path(folder), lambda *args: fake)
            controller.execute(UiCommand(UiAction.SAVE_MARKET_DATA_SETTINGS, 0, market_data_settings=MarketDataSettings(enabled=True)))
            controller.execute(UiCommand(UiAction.CONNECT_MARKET_DATA, 0))
            controller.worker.join(1)
            self.assertFalse(controller.worker.is_alive())
            self.assertEqual(controller.error, 'market_data_login_failed')
            self.assertEqual(calls, ['connect', 'disconnect'])


class LoginFailureStages(unittest.TestCase):
    setUp = connection.UnifiedConnectionTests.setUp
    command = connection.UnifiedConnectionTests.command

    def dispatch(self):
        self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings()))
        self.owner.worker.join(2)
        self.assertFalse(self.owner.worker.is_alive())
        self.assertEqual(self.owner.snapshot().phase, 'DISCONNECTED')
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 1)
        self.assertNotIn('PRIVATE_PERSON', repr(self.owner.snapshot()))
        self.assertNotIn('SECRET', repr(self.owner.snapshot()))

    def test_login_failure_keeps_key_environment_guidance(self):
        self.api.fail_login = True
        self.dispatch()
        self.assertEqual(self.owner.snapshot().error_code, 'broker_login_failed')
        self.assertEqual(reason_text('broker_login_failed'), ui_text('m2.connection.login_failed'))
        self.assertIn('金鑰', ERROR_TABLE['broker_login_failed'].action)

    def test_after_login_failure_is_initialization_with_same_cleanup(self):
        self.owner.on_connected = lambda session: (_ for _ in ()).throw(ValueError('PRIVATE_PERSON SECRET'))
        self.dispatch()
        self.assertEqual(self.owner.snapshot().error_code, 'broker_initialization_failed')
        self.assertEqual(reason_text('broker_initialization_failed'), ui_text('connection.failure.initialization'))
        self.assertIn('登入成功', ERROR_TABLE['broker_initialization_failed'].explanation)
        self.assertIn('診斷', ERROR_TABLE['broker_initialization_failed'].action)

    def test_post_login_specific_permission_classification_is_retained(self):
        class AuthError(Exception):
            pass

        self.owner.on_connected = lambda session: (_ for _ in ()).throw(AuthError('SECRET'))
        self.dispatch()
        self.assertEqual(self.owner.snapshot().error_code, 'broker_permission_missing')


class MarketFailureStages(unittest.TestCase):
    setUp = market.MarketSessionTests.setUp

    def test_standalone_post_login_initialization_is_not_login_failure(self):
        with patch.object(self.session, '_start_quotes', side_effect=ValueError('SECRET')):
            with self.assertRaises(DomainError) as caught:
                self.session.connect()
        self.assertEqual(caught.exception.code, 'broker_initialization_failed')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertIsNone(self.session.facade)
        self.assertEqual(sum(call[0] == 'login' for call in self.api.calls), 1)
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 1)

    def test_connected_subscription_error_does_not_disconnect_or_retry(self):
        self.session.connect()
        self.addCleanup(self.session.disconnect)
        with patch.object(self.session.facade, 'market_subscribe', side_effect=ValueError('SECRET')) as subscribe:
            with self.assertRaises(DomainError) as caught:
                self.session.subscribe(market.STOCK)
        self.assertEqual(caught.exception.code, 'market_data_subscription_failed')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertTrue(self.session.connected)
        self.assertEqual(self.session.subscriptions, {})
        subscribe.assert_called_once()
        self.assertEqual(sum(call[0] == 'login' for call in self.api.calls), 1)
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 0)

    def test_lost_connection_keeps_disconnected_error(self):
        self.session.connect()
        self.addCleanup(self.session.disconnect)
        self.session._session_down()
        with self.assertRaises(DomainError) as caught:
            self.session.subscribe(market.STOCK)
        self.assertEqual(caught.exception.code, 'market_data_not_connected')
        self.assertFalse(self.session.connected)


class TerminalFailureStages(unittest.TestCase):
    setUpClass = classmethod(terminal.TerminalTests.setUpClass.__func__)
    setUp = terminal.TerminalTests.setUp
    tearDown = terminal.TerminalTests.tearDown
    wait_for = terminal.TerminalTests.wait_for

    def test_failed_subscription_keeps_history_and_connected_feedback(self):
        with patch.object(self.facade, 'select_market_instrument', side_effect=DomainError('market_data_subscription_failed', 'SECRET')) as select:
            self.widget.select_instrument(terminal.STOCK.instrument_id)
            self.wait_for(lambda: not self.widget._requests)
        select.assert_called_once()
        self.assertTrue(self.widget._history_only)
        self.assertEqual(self.widget.freshness.text(), '● ' + ui_text('connection.failure.history_only'))
        self.assertEqual(self.widget.chart.status_label, ui_text('connection.failure.history_only'))
        self.assertEqual(self.widget.message.text(), ui_text('connection.failure.subscription'))
        self.assertNotIn('SECRET', self.widget.message.text())
        self.assertTrue(any(query.instrument_id == terminal.STOCK.instrument_id for query in self.facade.queries))
        self.assertEqual(self.facade.commands, [])

    def test_disconnected_status_does_not_claim_connection_survived(self):
        original = self.facade.market_status

        def status():
            result = original()
            result.connected = False
            return result

        self.facade.market_status = status
        with patch.object(self.facade, 'select_market_instrument', side_effect=DomainError('market_data_subscription_failed')):
            self.widget.select_instrument(terminal.STOCK.instrument_id)
            self.wait_for(lambda: not self.widget._requests)
        self.assertFalse(self.widget._history_only)
        self.assertEqual(self.widget.message.text(), ui_text('watch.disconnected'))
        self.assertEqual(self.facade.commands, [])
