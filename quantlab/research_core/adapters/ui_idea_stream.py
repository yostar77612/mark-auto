"""Bounded subscription event-stream adapter."""


def _idea_event_caller(reference, transport):
    """Stream one Responses call through the shared transport; yield parsed SSE events."""
    from quantlab.assistant.adapters.chatgpt.provider import PlanError, SSEParser
    from quantlab.assistant.adapters.chatgpt.auth import AuthError
    from quantlab.idea_search import RemoteFailure

    def call(request, limits, cancelled):
        parser = SSEParser(max_bytes=limits['max_response_bytes'], max_event_bytes=1048576, max_events=8192)
        stream = transport.stream(reference, request, limits, cancelled)
        try:
            for chunk in stream:
                for event in parser.feed(chunk):
                    kind = event.get('type')
                    response = event.get('response') or {}
                    error = event.get('error') if kind == 'error' else response.get('error')
                    if kind == 'error' and (not isinstance(error, dict)):
                        error = event
                    if kind in ('response.failed', 'response.incomplete', 'error') and (not (isinstance(error, dict) and error.get('code'))):
                        codes = {
                            'response.failed': 'idea_stream_failed_uncoded',
                            'response.incomplete': 'idea_stream_incomplete',
                            'error': 'idea_stream_error_uncoded',
                        }
                        raise RemoteFailure(codes[kind])
                    yield event
            parser.finish()
        except AuthError as exc:
            code = 'idea_auth_refresh_required' if exc.args == ('refresh_required',) else 'idea_auth_unavailable'
            raise RemoteFailure(code) from None
        except PlanError as exc:
            codes = {
                408: 'idea_http_timeout',
                429: 'idea_http_rate_limited',
                500: 'idea_http_server_error',
                502: 'idea_http_bad_gateway',
                504: 'idea_http_gateway_timeout',
            }
            if exc.code == 'remote_error' and exc.http_status in codes:
                raise RemoteFailure(codes[exc.http_status]) from None
            raise
        finally:
            stream.close()

    return call
