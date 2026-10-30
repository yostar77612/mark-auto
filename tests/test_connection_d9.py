"""Cheap offline connection-probe regression tests; no subprocess or network."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_app.features.assistant.connection import ConnectionController, ChatGPTConnectionPanel, ConnectionRequest, ConnectionEvent, run_connection_request
from desktop_app.features.assistant import connection_test as probe
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.application.ui_operations.assistant import connection_event_from_payload
from quantlab.desktop_errors import error_message
from quantlab.assistant.adapters.chatgpt.provider import PlanError

REF = 'a' * 32
OTHER = 'b' * 32
ROOT = Path(__file__).resolve().parents[1]


class Transport:
    def __init__(self, event=None, failure=None):
        self.event = event or {
            'type': 'response.completed',
            'response': {'status': 'completed', 'usage': {'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3}, 'output': '<script>OOS_SENTINEL</script>'},
        }
        self.failure = failure
        self.calls = []
        self.closed = False

    def stream(self, reference, payload, limits, cancelled):
        self.calls.append((reference, payload, limits))
        try:
            if self.failure:
                raise self.failure
            yield ('data: ' + json.dumps(self.event) + '\n\n').encode()
        finally:
            self.closed = True


class ConnectionD9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.c = ConnectionController()
        self.panel = ChatGPTConnectionPanel(self.c)
        self.addCleanup(self.panel.deleteLater)
        self.ready = Mock()
        self.c.request_ready.connect(self.ready)

    def enable(self):
        c = self.c
        c.host_available = True
        c.active_registration = REF
        c.registrations = ((REF, 'plan_ready'), (OTHER, 'plan_ready'))
        c.state = 'plan_ready'
        c.models = ('model-a', 'model-b')
        c.set_account_status(REF, {'state': 'ready', 'pending': False})

    def run_probe(self, transport=None, request=None, **kwargs):
        return probe.run_probe(
            request or ConnectionRequest(1, 'test', REF, 30, True, 'model-a'),
            '/fixture',
            kwargs.pop('cancelled', lambda: False),
            transport=transport or Transport(),
            reference_factory=lambda *args: SimpleNamespace(registration=REF),
            status_reader=kwargs.pop('status_reader', lambda *args: {'state': 'ready', 'pending': False}),
            **kwargs,
        )

    def finish(self, event):
        request = self.c._request
        self.c.acknowledge_quiescence(request.request_id, joined=True)
        self.c.apply_event(event)
        self.assertTrue(self.c.busy)
        self.c.worker_joined(request.request_id, joined=True)

    def test_disabled_prerequisites_and_every_pause_reason(self):
        button = self.panel.connection_test.button
        self.assertFalse(button.isEnabled())
        self.enable()
        self.assertTrue(button.isEnabled())
        self.c.models = ()
        self.c.changed.emit()
        self.assertFalse(button.isEnabled())
        self.enable()
        for state in ('quota_paused', 'eligibility_blocked', 'transient_blocked', 'blocked'):
            self.c.set_account_status(REF, {'state': state, 'pending': False})
            self.assertFalse(button.isEnabled())
            self.assertIn(error_message(state), button.toolTip())
            with self.assertRaises(ValueError):
                self.c.request('test', REF, confirmed=True, model='model-a')
        self.c.set_account_status(REF, {'state': 'ready', 'pending': True})
        self.assertFalse(button.isEnabled())
        self.c.set_usage(REF, [{'sequence': 1, 'status': 'reserved_unknown'}], account_status={'state': 'ready', 'pending': False})
        self.assertFalse(button.isEnabled())
        self.assertIn(error_message('active_or_unknown_request'), button.toolTip())

    def test_each_keyboard_press_requires_dialog_and_deny_has_zero_provider_calls(self):
        self.enable()
        transport = Transport()
        with (
            patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel) as consent,
            patch('quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport', return_value=transport),
        ):
            for _ in range(2):
                QTest.keyClick(self.panel.connection_test.button, Qt.Key.Key_Space)
            self.assertEqual(consent.call_count, 2)
            self.ready.assert_not_called()
            self.assertFalse(self.c.busy)
            denied = SimpleNamespace(user_confirmed=False, request_id=1)
            self.assertEqual(self.run_probe(transport, denied).error_code, 'network_disabled')
        self.assertEqual(transport.calls, [])
        self.assertTrue(self.panel.connection_test.button.accessibleName())
        disclosure = self.panel.connection_test.button.toolTip()
        self.assertIn('unverified', disclosure)
        self.assertEqual(disclosure.split('\n')[0], ui_text('connection_test.disclosure'))

    def test_accept_is_quiesced_worker_request_and_usage_is_displayed(self):
        self.enable()
        self.c.usage_known, self.c.reserved_count, self.c.unknown_count = True, 7, 0
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Ok):
            self.panel.connection_test.button.click()
        request = self.c._request
        self.assertEqual((request.action, request.model, request.max_runtime_seconds), ('test', 'model-a', 30))
        self.ready.assert_not_called()
        transport = Transport()
        event = self.run_probe(transport, request)
        wire = connection_event_from_payload(_c_create_operation_ports(), json.loads(json.dumps(asdict(event))))
        self.finish(wire)
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(transport.closed)
        self.assertIn(ui_text('connection_test.responded'), self.panel.connection_test.status.text())
        self.assertIn(ui_text('connection_test.usage').format(2, 1, 3), self.panel.connection_test.status.text())
        self.assertEqual((self.c.usage_known, self.c.reserved_count, self.c.unknown_count), (True, 7, 0))
        self.c.invalidate_campaign_usage()
        self.assertEqual((self.c.usage_known, self.c.reserved_count, self.c.unknown_count), (False, None, None))
        with patch('desktop_app.features.assistant.connection_test.run_probe', return_value=event) as worker:
            self.assertIs(run_connection_request(request, bootstrap='/fixture', emit=Mock(), cancelled=lambda: False), event)
            worker.assert_called_once()

    def test_model_account_signout_reset_previous_success(self):
        self.enable()
        for change in ('model', 'account', 'signout'):
            self.c.test_message = self.c.message = ui_text('connection_test.responded')
            self.c.changed.emit()
            if change == 'model':
                self.panel.model.setCurrentIndex(1)
            elif change == 'account':
                self.panel.account.setCurrentIndex(1)
            else:
                self.c.active_registration = None
                self.c.registrations = ()
                self.c.changed.emit()
            self.assertEqual(self.panel.connection_test.status.text(), ui_text('connection_test.untested'))
            self.assertNotIn('connection responded', self.panel.status.text())
        self.enable()
        self.c.test_message = ui_text('connection_test.responded')
        self.c.request('sign_out', REF, confirmed=True)
        self.assertEqual(self.c.test_message, ui_text('connection_test.untested'))

    def test_fixed_payload_protected_negative_control_no_reply_or_exception_text(self):
        transport = Transport()
        result = self.run_probe(transport)
        payload = transport.calls[0][1]
        self.assertEqual(payload['input'], [{'role': 'user', 'content': probe.PROMPT}])
        self.assertEqual(set(payload), {'model', 'input', 'instructions', 'store', 'stream'})
        sentinels = ('OOS_SENTINEL', 'HOLDOUT_SENTINEL', 'CREDENTIAL_SENTINEL')

        def scan(value):
            return any(secret in json.dumps(value) for secret in sentinels)

        self.assertFalse(scan(payload))
        self.assertFalse(scan(asdict(result)))
        self.assertTrue(scan({**payload, 'planted': sentinels}))
        self.assertNotIn('<script>', repr(result))
        self.assertLessEqual(transport.calls[0][2]['max_response_bytes'], 32768)
        for error, code in ((RuntimeError('CREDENTIAL_SENTINEL'), 'operation_failed'), (PlanError('quota_paused'), 'quota_paused')):
            failing = Transport(failure=error)
            event = self.run_probe(failing)
            self.assertEqual(event.error_code, code)
            self.assertEqual(len(failing.calls), 1)
            self.enable()
            request = self.c.request('test', REF, confirmed=True, model='model-a')
            self.finish(ConnectionEvent(request.request_id, 'error', error_code=code))
            self.assertIn(error_message(code), self.panel.connection_test.status.text())
            self.assertNotIn('CREDENTIAL_SENTINEL', self.panel.status.text())
            self.assertIn(ui_text('connection_test.usage_unknown'), self.panel.connection_test.status.text())

    def test_cancel_deadline_failed_response_and_worker_barrier(self):
        transport = Transport()
        self.assertEqual(self.run_probe(transport, cancelled=lambda: True).kind, 'error')
        self.assertEqual(transport.calls, [])
        self.assertEqual(self.run_probe(transport, status_reader=lambda *args: {'state': 'quota_paused', 'pending': False}).error_code, 'account_paused')
        self.assertEqual(transport.calls, [])
        clock = iter((0, 31))
        self.assertEqual(self.run_probe(transport, clock=lambda: next(clock)).kind, 'error')
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(transport.closed)
        failing = Transport(
            {'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded', 'message': 'CREDENTIAL_SENTINEL'}}}
        )
        self.assertEqual(self.run_probe(failing).error_code, 'quota_paused')
        self.assertEqual(len(failing.calls), 1)
        self.enable()
        request = self.c.request('test', REF, confirmed=True, model='model-a')
        cancelled = Mock()
        self.c.cancel_requested.connect(cancelled)
        self.c.cancel()
        cancelled.assert_called_once_with(request.request_id)
        self.assertFalse(self.c.apply_event(ConnectionEvent(request.request_id, 'result')))
        self.assertFalse(self.c.worker_joined(request.request_id, joined=False))
        self.c.worker_joined(request.request_id, joined=True, terminal_received=False)
        self.assertFalse(self.c.busy)
        self.assertIn(ui_text('connection_test.untested'), self.c.test_message)
        self.assertIn(ui_text('connection_test.usage_unknown'), self.c.test_message)
