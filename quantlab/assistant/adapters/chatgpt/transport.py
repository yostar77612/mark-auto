"""Transport responsibility; original guards and ordering preserved."""

from __future__ import annotations

from contextlib import contextmanager
from quantlab.assistant.adapters.chatgpt.identity import official_tls_context
from quantlab.assistant.domain.plan_protocol import MODELS_URL
from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.plan_protocol import RESPONSES_URL
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.assistant.domain.plan_protocol import _json
from quantlab.assistant.domain.plan_protocol import _remote_error
from quantlab.core import canonical_json
import http.client
import socket
import threading
import time


def _check(deadline, cancelled):
    if cancelled is not None and cancelled():
        _fail('cancelled')
    if time.monotonic() >= deadline:
        _fail('deadline_exceeded')


class PlanHTTPTransport:
    """Fixed HTTPS origins, verified TLS, no redirects/proxies/cookies/retries."""

    @contextmanager
    def _response(self, reference, method, url, body, limits, cancelled):
        if (method, url) not in (('GET', MODELS_URL), ('POST', RESPONSES_URL)):
            _fail('invalid_endpoint')
        deadline = limits['deadline']
        _check(deadline, cancelled)
        token = reference()  # scope and expiry checked, no implicit refresh
        if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            _fail('invalid_credential')
        headers = {
            'Authorization': 'Bearer ' + token,
            'Accept': 'text/event-stream' if method == 'POST' else 'application/json',
            'Accept-Encoding': 'identity',
            'Content-Type': 'application/json',
        }
        connection = http.client.HTTPSConnection(
            'api.openai.com', 443, context=official_tls_context(), timeout=min(limits['stall_seconds'], max(0.001, deadline - time.monotonic()))
        )
        active = [None]
        stop = threading.Event()

        def watchdog():
            while not stop.wait(0.05):
                if time.monotonic() >= deadline or (cancelled is not None and cancelled()):
                    sock = active[0] or connection.sock
                    if sock is not None:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        sock.close()
                    return

        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        try:
            _check(deadline, cancelled)
            connection.request(method, '/v1/models' if method == 'GET' else '/v1/responses', body=body, headers=headers)
            active[0] = connection.sock
            _check(deadline, cancelled)
            response = connection.getresponse()
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                _fail('compressed_response')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > limits['max_response_bytes']):
                _fail('stream_byte_limit')

            def chunks():
                total = 0
                while True:
                    _check(deadline, cancelled)
                    if active[0] is not None:
                        active[0].settimeout(min(limits['stall_seconds'], max(0.001, deadline - time.monotonic())))
                    raw = response.read1(min(8192, limits['max_response_bytes'] + 1 - total))
                    _check(deadline, cancelled)
                    if not raw:
                        break
                    total += len(raw)
                    if total > limits['max_response_bytes']:
                        _fail('stream_byte_limit')
                    yield raw

            if not 200 <= response.status < 300:
                if 300 <= response.status < 400:
                    _fail('redirect_rejected')
                raw = b''.join(chunks())
                try:
                    value = _json(raw)
                except PlanError:
                    value = {}
                _remote_error(value, http_status=response.status)
            expected = 'text/event-stream' if method == 'POST' else 'application/json'
            # Owner-approved (2026-10-23): the official streamed Responses reply can omit the
            # header entirely. Only a POST with no Content-Type header at all is read as a
            # stream; any present but different type is still refused, and the consumer's
            # strict SSE parsing and response.completed requirement remain the gate.
            content_type = response.getheader('Content-Type')  # None only when the header is absent
            if not (method == 'POST' and content_type is None) and ((content_type or '').split(';', 1)[0].strip().lower() != expected):
                _fail('invalid_content_type')
            yield chunks()
        except (OSError, http.client.HTTPException):
            _check(deadline, cancelled)
            _fail('http_transport_failed')
        finally:
            stop.set()
            connection.close()
            watcher.join(timeout=0.1)

    def stream(self, reference, request, limits, cancelled=None):
        body = canonical_json(request).encode('utf-8')
        if len(body) > limits['max_request_bytes']:
            _fail('request_byte_limit')
        with self._response(reference, 'POST', RESPONSES_URL, body, limits, cancelled) as chunks:
            yield from chunks

    def models(self, reference, limits, cancelled=None):
        with self._response(reference, 'GET', MODELS_URL, None, limits, cancelled) as chunks:
            return _json(b''.join(chunks))
