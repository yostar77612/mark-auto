"""Offline terminal-attempt reporting; no real OAuth, vault, browser or network."""
import unittest
from unittest.mock import patch

from desktop_chatgpt_ui import ConnectionRequest, run_connection_request
from tests.test_desktop_chatgpt_ui import authorization_url

REF = 'a' * 32


class AttemptSession:
    def __init__(self, terminal='authorization_failed', existing=False):
        self.state = 'disconnected'
        self.terminal = terminal
        self.active_registration = REF if existing else None
        self.saved_state = 'identity_only' if existing else 'disconnected'
        self.rows = [{'registration': REF, 'state': 'identity_only'}] if existing else []
        self.calls = []

    def begin(self, registration=None):
        self.calls.append('begin')
        self.state = 'authorizing'
        return authorization_url()

    def poll(self, timeout):
        self.calls.append('poll')
        self.state = self.terminal

    def cancel(self):
        self.calls.append('cancel')
        self.state = 'cancelled'

    def status_summary(self):
        return {'state': self.saved_state, 'active_registration': self.active_registration,
                'registrations': self.rows}


class TerminalAttemptReportingTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('offline fixture only'))
            guard.start()
            self.addCleanup(guard.stop)

    def run_attempt(self, session, **kwargs):
        self.events = []
        return run_connection_request(ConnectionRequest(1, 'begin', user_confirmed=True),
                                      bootstrap='/fixture', emit=self.events.append,
                                      session_factory=lambda: session,
                                      cancelled=kwargs.pop('cancelled', lambda: False), **kwargs)

    def test_failed_attempt_without_saved_account_is_an_explicit_safe_error(self):
        session = AttemptSession()
        result = self.run_attempt(session)
        self.assertEqual(result.state, 'authorization_failed')
        self.assertEqual(result.kind, 'error')
        self.assertEqual(result.error_code, 'authorization_failed')
        self.assertEqual(result.registrations, ())
        self.assertIsNone(result.active_registration)
        self.assertIsNone(result.authorization_url)
        self.assertEqual(session.calls, ['begin', 'poll'])


    def test_failed_attempt_preserves_existing_account_without_reporting_it_as_success(self):
        session = AttemptSession(existing=True)
        session.saved_state = 'plan_ready'
        session.rows = [{'registration': REF, 'state': 'plan_ready'}]
        result = self.run_attempt(session)
        self.assertEqual((result.kind, result.state, result.error_code),
                         ('error', 'authorization_failed', 'authorization_failed'))
        self.assertEqual(result.active_registration, REF)
        self.assertEqual(result.registrations, ((REF, 'plan_ready'),))
        self.assertEqual(session.rows, [{'registration': REF, 'state': 'plan_ready'}])
        self.assertEqual(session.calls, ['begin', 'poll'])

    def test_provider_denial_preserves_cancelled_attempt_and_saved_account(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                session = AttemptSession(terminal='cancelled', existing=existing)
                result = self.run_attempt(session)
                self.assertEqual((result.kind, result.state, result.error_code), ('result', 'cancelled', ''))
                self.assertEqual(result.active_registration, REF if existing else None)
                self.assertEqual(result.registrations, ((REF, 'identity_only'),) if existing else ())
                self.assertEqual(session.calls, ['begin', 'poll'])

    def test_listener_timeout_status_is_not_replaced_by_persisted_account(self):
        session = AttemptSession(terminal='timeout', existing=True)
        result = self.run_attempt(session)
        self.assertEqual(result.state, 'timeout')
        self.assertEqual(result.active_registration, REF)
        self.assertEqual(result.registrations, ((REF, 'identity_only'),))

    def test_worker_deadline_remains_bounded_without_poll_or_retry(self):
        session = AttemptSession(existing=True)
        times = iter((0, 121))
        result = self.run_attempt(session, clock=lambda: next(times))
        self.assertEqual((result.kind, result.state, result.error_code), ('error', 'timeout', 'authorization_timeout'))
        self.assertEqual(session.calls, ['begin', 'cancel'])
        self.assertEqual(session.rows, [{'registration': REF, 'state': 'identity_only'}])

    def test_explicit_cancellation_retains_attempt_status_and_account(self):
        session = AttemptSession(existing=True)
        checks = iter((False, True))
        result = self.run_attempt(session, cancelled=lambda: next(checks))
        self.assertEqual((result.kind, result.state, result.error_code), ('result', 'cancelled', ''))
        self.assertEqual(result.active_registration, REF)
        self.assertEqual(result.registrations, ((REF, 'identity_only'),))
        self.assertEqual(session.calls, ['begin', 'cancel'])

    def test_success_retains_verified_summary_and_transient_url_boundary(self):
        class Success(AttemptSession):
            def poll(self, timeout):
                super().poll(timeout)
                self.active_registration = REF
                self.saved_state = 'plan_ready'
                self.rows = [{'registration': REF, 'state': 'plan_ready'}]
        session = Success(terminal='plan_ready')
        result = self.run_attempt(session)
        self.assertEqual((result.kind, result.state, result.error_code), ('result', 'plan_ready', ''))
        self.assertEqual(result.active_registration, REF)
        self.assertIsNone(result.authorization_url)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].kind, 'authorization')
        self.assertEqual(session.calls, ['begin', 'poll'])

    def test_unknown_attempt_status_cannot_cross_the_sanitized_event_boundary(self):
        marker = 'FIXTURE_PRIVATE_ATTEMPT_VALUE'
        result = self.run_attempt(AttemptSession(terminal=marker))
        self.assertEqual((result.kind, result.state, result.error_code), ('error', 'unknown', 'operation_failed'))
        self.assertNotIn(marker, repr(result))
        self.assertIsNone(result.authorization_url)

    def test_failure_is_visible_and_controls_stay_locked_until_worker_join(self):
        from desktop_chatgpt_ui import ConnectionController, ERROR_LABELS
        controller = ConnectionController()
        controller.set_host_available(True)
        request = controller.request('begin', confirmed=True)
        controller.acknowledge_quiescence(request.request_id, joined=True)
        result = self.run_attempt(AttemptSession())
        self.assertTrue(controller.apply_event(result))
        self.assertEqual(controller.state, 'authorization_failed')
        self.assertIn(ERROR_LABELS['authorization_failed'], controller.message)
        self.assertTrue(controller.busy)
        self.assertTrue(controller.worker_joined(request.request_id, joined=True))
        self.assertFalse(controller.busy)
        self.assertEqual(controller.state, 'authorization_failed')

    def test_unrelated_invalid_request_keeps_real_listener_waiting_until_explicit_cancel(self):
        from unittest.mock import MagicMock
        from desktop_chatgpt_auth import AuthSession, LoopbackListener
        from tests.test_chatgpt_auth import FakeVault
        listeners = []

        class NoTransport:
            def request(self, *args, **kwargs):
                raise AssertionError('Unrelated request must never exchange credentials')

        def listener_factory(callback):
            listener = LoopbackListener.__new__(LoopbackListener)
            listener.callback = callback
            listener.port = 1455
            listener.socket = MagicMock()
            connection = MagicMock()
            connection.recv.return_value = b'GET /unrelated HTTP/1.1\r\nHost: 127.0.0.1:1455\r\n\r\n'
            listener.socket.accept.return_value = (connection, ('127.0.0.1', 12345))
            listeners.append(listener)
            return listener

        session = AuthSession(FakeVault(), NoTransport(), listener_factory=listener_factory)
        session.initialize_host()
        checks = []

        def cancelled():
            checks.append(True)
            if len(checks) == 3:
                self.assertEqual(session.state, 'authorizing')
                listeners[0].socket.close.assert_not_called()
                return True
            return False

        result = self.run_attempt(session, cancelled=cancelled)
        self.assertEqual(result.state, 'cancelled')
        listeners[0].socket.close.assert_called_once()

if __name__ == '__main__':
    unittest.main()
