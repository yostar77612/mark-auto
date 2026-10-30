"""Content-free diagnostics preserve the extraction admission boundary."""

import json
import unittest
from unittest.mock import Mock

from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.auth_protocol import AuthError
from desktop_app.shell.main_window import _idea_event_caller

from quantlab.idea_research import _extraction_output, run_extraction
from quantlab.idea_search import RemoteFailure


def response(*texts):
    return {
        'status': 'completed',
        'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text} for text in texts]}],
    }


class ExtractionOutputTests(unittest.TestCase):
    def test_authentication_failures_use_fixed_codes_without_exception_text(self):
        for reason, expected in (('refresh_required', 'idea_auth_refresh_required'), ('private', 'idea_auth_unavailable')):

            def stream(*args):
                raise AuthError(reason)
                yield b''

            with self.subTest(reason=reason), self.assertRaises(RemoteFailure) as caught:
                list(_idea_event_caller(None, Mock(stream=stream))({}, {'max_response_bytes': 1024}, None))
            self.assertEqual(str(caught.exception), expected)

    def test_top_level_stream_quota_code_is_preserved(self):
        event = {'type': 'error', 'code': 'subscription_sharing_usage_limit_exceeded'}
        transport = Mock(stream=lambda *args: (raw for raw in [b'data: ' + json.dumps(event).encode() + b'\n\n']))
        self.assertEqual(list(_idea_event_caller(None, transport)({}, {'max_response_bytes': 1024}, None)), [event])

    def test_uncoded_stream_failures_emit_only_fixed_diagnostics(self):
        for kind, expected in (
            ('response.failed', 'idea_stream_failed_uncoded'),
            ('response.incomplete', 'idea_stream_incomplete'),
            ('error', 'idea_stream_error_uncoded'),
        ):
            event = {'type': kind, 'response': {'error': {'message': 'private'}}, 'error': {'message': 'private'}}
            transport = Mock(stream=lambda *args: (raw for raw in [b'data: ' + json.dumps(event).encode() + b'\n\n']))
            call = _idea_event_caller(None, transport)
            with self.subTest(kind=kind), self.assertRaises(RemoteFailure) as caught:
                list(call({}, {'max_response_bytes': 1024}, None))
            self.assertEqual(str(caught.exception), expected)

    def test_transport_status_diagnostics_preserve_pause_and_other_codes(self):
        for code, status, expected in (
            ('remote_error', 429, 'idea_http_rate_limited'),
            ('remote_error', 500, 'idea_http_server_error'),
            ('quota_paused', 429, 'quota_paused'),
            ('grant_blocked', 403, 'grant_blocked'),
        ):

            def stream(*args):
                raise PlanError(code, http_status=status)
                yield b''

            call = _idea_event_caller(None, Mock(stream=stream))
            with self.subTest(code=code, status=status), self.assertRaises((RemoteFailure, PlanError)) as caught:
                list(call({}, {'max_response_bytes': 1024}, None))
            self.assertEqual(caught.exception.code, expected)

    def test_text_events_with_empty_terminal_are_diagnosed_without_acceptance(self):
        events = [
            {'type': 'response.output_text.delta', 'delta': 'private'},
            {'type': 'response.completed', 'response': {'status': 'completed', 'output': []}},
        ]
        with self.assertRaises(RemoteFailure) as caught:
            run_extraction(lambda *args: iter(events), {}, deadline=100)
        self.assertEqual(str(caught.exception), 'extraction_terminal_missing_event_text')

    def test_single_json_is_accepted(self):
        self.assertEqual(_extraction_output(response('{"candidates":[]}')), {'candidates': []})

    def test_rejections_identify_shape_without_exposing_content(self):
        for payload, code in (
            (response(), 'extraction_output_missing'),
            (response('private-one', 'private-two'), 'extraction_output_multiple'),
            (response('x' * 262145), 'extraction_output_too_large'),
        ):
            with self.subTest(code=code), self.assertRaises(RemoteFailure) as caught:
                _extraction_output(payload)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(str(caught.exception), code)

    def test_byte_limit_is_utf8_not_character_count(self):
        with self.assertRaises(RemoteFailure) as caught:
            _extraction_output(response('中' * 87382))
        self.assertEqual(caught.exception.code, 'extraction_output_too_large')

    def test_tools_and_invalid_json_stay_rejected(self):
        with self.assertRaises(RemoteFailure) as caught:
            _extraction_output({'status': 'completed', 'output': [{'type': 'function_call'}]})
        self.assertEqual(caught.exception.code, 'tools_or_unknown_output')
        with self.assertRaises(RemoteFailure) as caught:
            _extraction_output(response('not-json'))
        self.assertEqual(caught.exception.code, 'invalid_json')
