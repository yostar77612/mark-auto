from pathlib import Path
import time

PROMPT = "Reply with OK."


def run_probe(request, bootstrap, cancelled, *, transport=None, reference_factory=None, status_reader=None, clock=time.monotonic):
    """Worker only. One bounded public transport call, no retry or model text IPC."""
    from quantlab.assistant.application.connection_contracts import TestConnectionEvent as ConnectionEvent
    from quantlab.assistant.adapters.chatgpt.connection_worker import _safe_error_code
    from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
    from quantlab.assistant.adapters.chatgpt.transport import PlanHTTPTransport
    from quantlab.assistant.adapters.chatgpt.response_stream import SSEParser
    from quantlab.assistant.adapters.chatgpt.provider import read_account_status
    from quantlab.assistant.domain.plan_protocol import ERROR_STATES, PlanError

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
                            values = tuple((observed.get(k) for k in ('input_tokens', 'output_tokens', 'total_tokens')))
                            if all((type(v) is int and 0 <= v <= 2**53 for v in values)) and values[0] + values[1] == values[2]:
                                usage = values
            parser.finish()
            if not completed:
                raise PlanError('operation_failed')
        finally:
            stream.close()
        return ConnectionEvent(request.request_id, 'result', test_usage=usage)
    except Exception as exc:
        return ConnectionEvent(request.request_id, 'error', error_code=_safe_error_code(exc), test_usage=usage)
