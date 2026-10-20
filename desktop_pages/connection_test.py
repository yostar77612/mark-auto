"""Explicit, fixed-payload connection probe; no research or assistant tools."""

from pathlib import Path
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QMessageBox

from desktop_strings import ui_text
from quantlab.desktop_errors import error_message

PROMPT = 'Reply with OK.'


class ConnectionTest:
    def __init__(self, panel):
        self.panel = panel
        self.binding = None
        self.button = QPushButton(ui_text('connection_test.button'), panel)
        self.button.setObjectName('chatgpt_test')
        self.button.setAccessibleName(ui_text('connection_test.button'))
        self.button.setToolTip(ui_text('connection_test.disclosure'))
        self.status = QLabel(panel)
        self.status.setObjectName('chatgpt_test_status')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        panel.layout().addWidget(self.button)
        panel.layout().addWidget(self.status)
        self.button.clicked.connect(self.submit)
        panel.controller.changed.connect(self.render)
        panel.account.currentIndexChanged.connect(self.render)
        panel.model.currentIndexChanged.connect(self.render)
        self.render()

    def render(self, *_):
        p = self.panel
        c = p.controller
        binding = (c.active_registration, p.account.currentData(), p.model.currentData())
        if binding != self.binding:
            self.binding = binding
            if c.message == c.test_message:
                c.message = ui_text('connection_test.untested')
                p.status.setText(c.message)
            c.test_message = ui_text('connection_test.untested')
        eligible = (
            c.host_available
            and not c.busy
            and c.state == 'plan_ready'
            and p.account.currentData() == c.active_registration
            and c.active_registration is not None
            and p.model.currentData() in c.models
            and c.account_status_known
            and not c.account_paused
            and not c.account_pending
            and not c.unknown_count
        )
        self.button.setEnabled(bool(eligible))
        reason = ''
        if c.account_status_known and (c.account_paused or c.account_pending or c.unknown_count):
            reason = error_message('active_or_unknown_request' if c.account_pending or c.unknown_count else c.account_state)
        self.button.setToolTip(ui_text('connection_test.disclosure') + '\n' + reason)
        self.status.setText(c.test_message + ('\n' + reason if reason else ''))

    def submit(self):
        if not self.button.isEnabled():
            return
        p = self.panel
        answer = QMessageBox.question(
            p,
            ui_text('assistant.consent_title'),
            ui_text('connection_test.disclosure'),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        p._safe(lambda: p.controller.request('test', p.account.currentData(), confirmed=True, model=p.model.currentData()))


def run_probe(request, bootstrap, cancelled, *, transport=None, reference_factory=None, status_reader=None, clock=time.monotonic):
    """Worker only. One bounded public transport call, no retry or model text IPC."""
    # Resolve the event seam lazily to avoid a panel/worker import cycle.
    from desktop_chatgpt_ui import TestConnectionEvent as ConnectionEvent, _safe_error_code

    # Load the pinned credential reference only in the explicitly requested worker.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Keep optional provider initialization out of desktop startup.
    from desktop_chatgpt_provider import PlanHTTPTransport, SSEParser, read_account_status, ERROR_STATES, PlanError

    usage = None
    try:
        if request.user_confirmed is not True:
            raise PlanError('network_disabled')
        if cancelled():
            raise PlanError('cancelled')
        reference = (reference_factory or OAuthCredentialReference)(str(bootstrap), request.registration)
        status = (status_reader or read_account_status)(reference, Path(bootstrap) / 'control-v1')
        if status != {'state': 'ready', 'pending': False}:
            raise PlanError('account_paused')
        payload = {
            'model': request.model,
            'instructions': 'Read-only connection probe. Inference remains unverified.',
            'input': [{'role': 'user', 'content': PROMPT}],
            'store': False,
            'stream': True,
        }
        limits = {'deadline': clock() + min(30, request.max_runtime_seconds), 'stall_seconds': 10, 'max_request_bytes': 8192, 'max_response_bytes': 32768}
        parser = SSEParser(max_bytes=32768)
        completed = False
        stream = (transport or PlanHTTPTransport()).stream(reference, payload, limits, cancelled)
        try:
            for chunk in stream:
                if cancelled():
                    raise PlanError('cancelled')
                if clock() >= limits['deadline']:
                    raise PlanError('http_transport_failed')
                for event in parser.feed(chunk):
                    if event.get('type') in ('response.failed', 'response.incomplete', 'error'):
                        error = event.get('error') or (event.get('response') or {}).get('error') or {}
                        code = error.get('code') if type(error) is dict else None
                        raise PlanError(ERROR_STATES.get(code, 'operation_failed'))
                    if event.get('type') == 'response.completed':
                        response = event.get('response')
                        if (
                            completed
                            or type(response) is not dict
                            or response.get('status') != 'completed'
                            or response.get('error')
                            or response.get('incomplete_details')
                        ):
                            raise PlanError('operation_failed')
                        completed = True
                        observed = response.get('usage')
                        if type(observed) is dict:
                            values = tuple(observed.get(k) for k in ('input_tokens', 'output_tokens', 'total_tokens'))
                            if all(type(v) is int and 0 <= v <= 2**53 for v in values) and values[0] + values[1] == values[2]:
                                usage = values
            parser.finish()
            if not completed:
                raise PlanError('operation_failed')
        finally:
            stream.close()
        return ConnectionEvent(request.request_id, 'result', test_usage=usage)
    except Exception as exc:
        return ConnectionEvent(request.request_id, 'error', error_code=_safe_error_code(exc), test_usage=usage)
