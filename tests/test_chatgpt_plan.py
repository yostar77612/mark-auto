"""P1–P6 synthetic protocol fixtures only. No live sign-in or inference."""

import json
import pickle
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

import unittest
import tempfile
from pathlib import Path
from desktop_chatgpt_auth import OAuthCredentialReference
from quantlab.core import ValidationError
from desktop_chatgpt_provider import (
    ChatGPTPlanProvider,
    PlanError,
    SSEParser,
    parse_models,
    parse_completed,
    ERROR_STATES,
    RESPONSES_URL,
    PlanHTTPTransport as RealTransport,
    clear_account_pause,
    read_account_status,
    discover_models,
)

CANDIDATE = {'strategy_id': 'mock_trend', 'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'rules': {}}


def terminal(usage=None):
    response = {
        'id': 'resp_fixture',
        'status': 'completed',
        'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(CANDIDATE)}]}],
    }
    if usage is not None:
        response['usage'] = usage
    return {'type': 'response.completed', 'response': response}


def frame(event):
    return ('data: ' + json.dumps(event, ensure_ascii=False) + '\r\n\r\n').encode()


def provider(tmp_path, **kwargs):
    opts = dict(
        model='fixture-model',
        credential_reference=OAuthCredentialReference(str(tmp_path / 'auth'), 'a' * 32),
        budget_path=tmp_path / 'auth' / 'control-v1' / 'plan.sqlite',
        campaign_id='test-campaign',
        network_opt_in=True,
        included_usage_policy_confirmed=True,
        max_calls=2,
    )
    opts.update(kwargs)
    return ChatGPTPlanProvider(**opts)


class MockTransport:
    """In-memory wire fixture, never represents actual model verification."""

    requests = []
    events = None

    def stream(self, reference, request, limits, cancelled):
        self.requests.append((RESPONSES_URL, request))
        yield from (self.events if self.events is not None else [frame(terminal())])

    def models(self, reference, limits, cancelled):
        return {'models': [{'slug': 'fixture-model', 'display_name': 'Fixture', 'visibility': 'list'}]}


def crash_after_reservation(path):
    with patch('desktop_chatgpt_provider.implementation_provenance', return_value={'source_sha256': {'offline_fixture': 'a' * 64}}):
        p = provider(Path(path))
        p._reserve('0' * 64, 100)
    os._exit(0)  # Synthetic worker death, no network or remote operation.


def competing_reservation(path, queue):
    try:
        with patch('desktop_chatgpt_provider.implementation_provenance', return_value={'source_sha256': {'offline_fixture': 'a' * 64}}):
            queue.put(provider(Path(path))._reserve('0' * 64, 100))
    except PlanError:
        queue.put(None)


def competing_distinct_registration(path, registration, filename, queue):
    root = Path(path)
    with patch('desktop_chatgpt_provider.implementation_provenance', return_value={'source_sha256': {'offline_fixture': 'a' * 64}}):
        p = provider(
            root,
            credential_reference=OAuthCredentialReference(str(root / 'auth'), registration),
            budget_path=root / 'auth' / 'control-v1' / filename,
            campaign_id=filename,
        )
        try:
            queue.put(p._reserve('a' * 64, 100))
        except PlanError:
            queue.put(None)


class FakeSocket:
    def settimeout(self, value):
        pass

    def shutdown(self, value):
        pass

    def close(self):
        pass


class FakeResponse:
    status = 200
    headers = {'Content-Type': 'text/event-stream'}
    chunks = []

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        if not self.chunks:
            return b''
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeHTTPS:
    requests = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.sock = FakeSocket()

    def request(self, *args, **kwargs):
        self.requests.append((self.args, args, kwargs))

    def getresponse(self):
        return FakeResponse()

    def close(self):
        pass


SYNTHETIC_PROVENANCE = {'source_sha256': {'offline_fixture': 'a' * 64}}


class PlanTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('desktop_chatgpt_provider.implementation_provenance', return_value=SYNTHETIC_PROVENANCE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp_path = Path(self.temp.name)
        MockTransport.requests = []
        MockTransport.events = None
        patcher = patch('http.client.HTTPSConnection', side_effect=AssertionError('No live HTTP'))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('desktop_chatgpt_provider.PlanHTTPTransport', MockTransport)
        patcher.start()
        self.addCleanup(patcher.stop)

        # P1: exact payload; inert construction and explicit admission.

    def test_p1_golden_request(self):
        tmp_path = self.tmp_path
        p = provider(tmp_path)
        assert not p.path.exists()
        assert p.generate({'family': 'trend'}) == CANDIDATE
        endpoint, request = MockTransport.requests[0]
        assert endpoint == 'https://api.openai.com/v1/responses'
        assert set(request) == {'model', 'instructions', 'input', 'store', 'stream'}
        assert request['store'] is False and request['stream'] is True
        assert request['input'][0]['role'] == 'user'
        assert p.real_model_status == 'not_verified'
        assert b'fixture-model' in pickle.dumps(p)

    def test_p1_admission(self):
        tmp_path = self.tmp_path
        for setting in [{'network_opt_in': False}, {'included_usage_policy_confirmed': False}, {'hard_token_limit': 100}]:
            with self.subTest(setting=setting):
                tmp_path = self.tmp_path / str(len(list(self.tmp_path.iterdir())))
                tmp_path.mkdir()
                with self.assertRaises(ValidationError):
                    provider(tmp_path, **setting).generate({'family': 'trend'})
                assert not (tmp_path / 'auth' / 'control-v1' / 'plan.sqlite').exists()

    # P2b: the pre-inference catalog check uses the catalog cap, never the inference cap.
    def test_p2_campaign_catalog_uses_catalog_limit(self):
        from desktop_chatgpt_provider import MODELS_MAX_RESPONSE_BYTES

        seen = []

        class Capture(MockTransport):
            def models(self, reference, limits, cancelled):
                seen.append(limits['max_response_bytes'])
                return super().models(reference, limits, cancelled)

        with patch('desktop_chatgpt_provider.PlanHTTPTransport', Capture):
            p = provider(self.tmp_path)
            assert p.generate({'family': 'trend'}) == CANDIDATE
        assert seen == [MODELS_MAX_RESPONSE_BYTES]
        assert p.max_response_bytes == 262144

    # P2: catalog shape and ordering, hidden model cannot be selected.
    def test_p2_models(self):
        self.tmp_path
        assert parse_models(
            {
                'models': [
                    {'slug': 'b', 'display_name': 'B', 'visibility': 'list'},
                    {'slug': 'hide', 'display_name': 'H', 'visibility': 'hidden'},
                    {'slug': 'a', 'display_name': 'A', 'visibility': 'list'},
                ]
            }
        ) == [{'slug': 'b', 'display_name': 'B'}, {'slug': 'a', 'display_name': 'A'}]
        for bad in ({'data': []}, {'models': []}, {'models': [{'slug': 'a'}]}, {'models': [{'slug': 'a', 'display_name': 'A', 'visibility': 'list'}] * 2}):
            with self.assertRaises(ValidationError):
                parse_models(bad)

    def test_p2_unavailable(self):
        tmp_path = self.tmp_path
        with self.assertRaises(ValidationError):
            provider(tmp_path, model='missing').generate({'family': 'trend'})
        assert MockTransport.requests == []

    # P3: every byte split, UTF8/comments/CRLF/multiline.
    def test_p3_split_matrix(self):
        self.tmp_path
        raw = b': comment\r\n\r\n' + frame({'type': 'response.output_text.delta', 'delta': '\u4e2d'}) + frame(terminal())
        for split in range(len(raw) + 1):
            p = SSEParser()
            events = p.feed(raw[:split]) + p.feed(raw[split:])
            p.finish()
            assert len(events) == 2
            assert parse_completed(events[-1]['response'], 'trend')[0] == CANDIDATE
        p = SSEParser()
        assert p.feed(b'data: {"type":\r\ndata: "ping"}\r\n\r\n') == [{'type': 'ping'}]

    # P4: incomplete outcomes cannot yield candidates; reservation is irreversible.
    def test_p4_failures(self):
        tmp_path = self.tmp_path
        for events in [
            [],
            [b'data: [DONE]\n\n'],
            [frame({'type': 'response.failed', 'response': {'error': {'code': 'unknown'}}})],
            [frame({'type': 'response.incomplete'})],
            [frame({'type': 'error'})],
            [frame(terminal()) + frame({'type': 'response.failed'})],
            [b'data: {"type":"response.completed","type":"x"}\n\n'],
        ]:
            with self.subTest(events=events):
                tmp_path = self.tmp_path / str(len(list(self.tmp_path.iterdir())))
                tmp_path.mkdir()
                MockTransport.events = events
                p = provider(tmp_path)
                with self.assertRaises(ValidationError):
                    p.generate({'family': 'trend'})
                receipts = p.read_receipts()
                assert len(receipts) == 1 and receipts[0]['status'] != 'completed'
                assert receipts[0]['token_usage'] == 'unknown'

    def test_p4_terminal_rejection(self):
        self.tmp_path
        for change in [
            {'output': [{'type': 'function_call', 'name': 'tool'}]},
            {'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': 'no'}]}]},
            {'status': 'incomplete'},
            {'output': []},
        ]:
            with self.subTest(change=change):
                response = terminal()['response']
                response.update(change)
                with self.assertRaises(ValidationError):
                    parse_completed(response, 'trend')

    def test_p4_bounds(self):
        self.tmp_path
        with self.assertRaises(ValidationError):
            SSEParser(max_bytes=8).feed(b'x' * 9)
        with self.assertRaises(ValidationError):
            SSEParser().feed(b'data: {"x":NaN}\n\n')
        with self.assertRaises(ValidationError):
            SSEParser().feed(b'data: {"x":1e999}\n\n')

    # P5: concurrent processes use the same atomic SQLite contract; restart cannot refund.
    def test_p5_concurrent_reservations(self):
        tmp_path = self.tmp_path
        p = provider(tmp_path, max_calls=3)

        def reserve(_):
            try:
                sequence = p._reserve('0' * 64, 100)
                p._finish(sequence, 'completed')
                return sequence
            except ValidationError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(20)))
        while len(p.read_receipts()) < 3:
            results.append(reserve(None))
        assert sorted(x for x in results if x is not None) == [1, 2, 3]
        assert len(provider(tmp_path, max_calls=3).read_receipts()) == 3
        with self.assertRaises(ValidationError):
            provider(tmp_path, max_calls=4)._reserve('0' * 64, 100)
        assert all(r['token_usage'] == 'unknown' for r in p.read_receipts())

    def test_p5_usage_and_claims(self):
        tmp_path = self.tmp_path
        p = provider(tmp_path)
        p.generate({'family': 'trend'})
        d = p.provider_descriptor()
        assert d['token_upper_bound_enforced'] is False and d['spend_upper_bound_enforced'] is False
        for usage in (None, {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3}, {'total_tokens': -1}):
            _, observed = parse_completed(terminal(usage)['response'], 'trend')
            assert (observed == 'unknown') == (usage is None or usage.get('total_tokens') == -1)

    # P6: all documented error codes stop without retries or alternate billing.
    def test_p6_errors(self):
        tmp_path = self.tmp_path
        for code in list(ERROR_STATES):
            with self.subTest(code=code):
                tmp_path = self.tmp_path / code
                MockTransport.requests = []
                MockTransport.events = [frame({'type': 'response.failed', 'response': {'error': {'code': code}}})]
                p = provider(tmp_path)
                with self.assertRaises(PlanError) as caught:
                    p.generate({'family': 'trend'})
                assert caught.exception.code == ERROR_STATES[code]
                assert len(MockTransport.requests) == 1
                with self.assertRaises(ValidationError):
                    p.generate({'family': 'trend'})
                assert len(MockTransport.requests) == 1

    def test_admission_diagnostics_do_not_interpret_or_retain_detail_text(self):
        from desktop_chatgpt_provider import _remote_error

        for value, status, expected, remote in (
            ({'detail': 'subscription_sharing_user_not_eligible'}, 403, 'grant_blocked', None),
            ({'detail': 'fixture-secret https://example.invalid/?token=secret'}, 503, 'transient_blocked', None),
            (
                {'error': {'code': 'subscription_sharing_usage_limit_exceeded', 'message': 'fixture-secret'}},
                429,
                'quota_paused',
                'subscription_sharing_usage_limit_exceeded',
            ),
            ({'error': {'type': 'subscription_sharing_user_not_eligible'}}, 401, 'credential_diagnosis', None),
            ({'error': {'code': 'unrecognized-secret-code'}}, 400, 'remote_error', None),
        ):
            with self.subTest(status=status, value=value):
                with self.assertRaises(PlanError) as caught:
                    _remote_error(value, http_status=status)
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(caught.exception.remote_code, remote)
                self.assertNotIn('secret', repr(caught.exception))
                self.assertNotIn('secret', repr(vars(caught.exception)))

    def test_model_cannot_change_user_owned_quantity_stops_or_targets(self):
        import copy
        from quantlab.research import validate_dsl

        for key, value in (('quantity', 100), ('stop_ticks', 1), ('target_ticks', 100000)):
            with self.subTest(key=key):
                candidate = copy.deepcopy(CANDIDATE)
                candidate['parameters'][key] = value
                # Manual engine capability is retained; the model boundary rejects.
                validate_dsl(candidate)
                response = terminal()['response']
                response['output'][0]['content'][0]['text'] = json.dumps(candidate)
                with self.assertRaisesRegex(PlanError, 'invalid_output'):
                    parse_completed(response, 'trend')
                MockTransport.events = [frame({'type': 'response.completed', 'response': response})]
                p = provider(self.tmp_path / key)
                with self.assertRaisesRegex(PlanError, 'invalid_output'):
                    p.generate({'family': 'trend'})
                receipts = p.read_receipts()
                self.assertEqual(len(receipts), 1)
                self.assertEqual(receipts[0]['status'], 'invalid_output')
                self.assertIsNone(receipts[0]['response_hash'])
                with self.assertRaises(PlanError):
                    p.generate({'family': 'trend'})

    def test_model_exact_family_parameters_with_optional_exit_still_work(self):
        import copy

        candidate = copy.deepcopy(CANDIDATE)
        node = {'op': 'gt', 'left': {'op': 'const', 'value': 1}, 'right': {'op': 'const', 'value': 0}}
        candidate['rules'] = {'long': node, 'short': {'op': 'not', 'arg': node}, 'exit': node}
        response = terminal()['response']
        response['output'][0]['content'][0]['text'] = json.dumps(candidate)
        actual, _ = parse_completed(response, 'trend')
        self.assertEqual(actual, candidate)

    def test_empty_and_nonjson_admission_responses_keep_safe_status(self):
        import time

        reference = provider(self.tmp_path).credential_reference
        limits = dict(deadline=time.monotonic() + 30, stall_seconds=10, max_request_bytes=65536, max_response_bytes=262144)
        request = {'model': 'fixture-model', 'input': [], 'instructions': 'mock', 'stream': True, 'store': False}
        with patch('http.client.HTTPSConnection', FakeHTTPS), patch.object(OAuthCredentialReference, '__call__', return_value='fixture-oauth-secret'):
            for status, expected in ((401, 'credential_diagnosis'), (403, 'grant_blocked'), (503, 'transient_blocked')):
                for body in (b'', b'not-json fixture-secret'):
                    FakeResponse.status = status
                    FakeResponse.headers = {}
                    FakeResponse.chunks = [body] if body else []
                    with self.subTest(status=status, body=body), self.assertRaises(PlanError) as caught:
                        list(RealTransport().stream(reference, request, limits))
                    self.assertEqual(caught.exception.code, expected)
                    self.assertEqual(caught.exception.http_status, status)
                    self.assertIsNone(caught.exception.remote_code)
                    self.assertNotIn('secret', repr(vars(caught.exception)))

    def test_p5_crash_barrier(self):
        p = provider(self.tmp_path)
        p._reserve('0' * 64, 100)
        restarted = provider(self.tmp_path)
        with self.assertRaises(PlanError):
            restarted._reserve('1' * 64, 100)
        with self.assertRaises(PlanError):
            restarted.generate({'family': 'trend'})
        assert MockTransport.requests == []
        assert restarted.read_receipts()[0]['status'] == 'reserved_unknown'

    def test_p4_cancel_and_absolute_deadline(self):
        p = provider(self.tmp_path)
        with self.assertRaises(PlanError):
            p.generate({'family': 'trend'}, cancelled=lambda: True)
        assert MockTransport.requests == []
        p = provider(self.tmp_path / 'slow')
        import time

        expired = time.monotonic() + p.timeout + 1

        def slow_stream(*args):
            with patch('desktop_chatgpt_provider.time.monotonic', return_value=expired):
                yield frame(terminal())

        with patch.object(MockTransport, 'stream', slow_stream):
            with self.assertRaises(PlanError):
                p.generate({'family': 'trend'})
        assert p.read_receipts()[0]['status'] == 'deadline_exceeded'

    def test_p3_mismatched_response_ids(self):
        MockTransport.events = [frame({'type': 'response.created', 'response': {'id': 'different'}}), frame(terminal())]
        p = provider(self.tmp_path)
        with self.assertRaises(PlanError):
            p.generate({'family': 'trend'})
        assert p.read_receipts()[0]['status'] == 'response_id_mismatch'

    def test_p3_conflicting_identity_fields_cannot_mask_each_other(self):
        for kind in ('response.created', 'response.completed'):
            with self.subTest(kind=kind):
                event = terminal() if kind == 'response.completed' else {'type': kind, 'response': {}}
                event['response_id'] = 'resp_fixture'
                event['response']['id'] = 'different'
                MockTransport.events = [frame({'type': 'response.created', 'response': {'id': 'resp_fixture'}}), frame(event), frame(terminal())]
                p = provider(self.tmp_path / kind)
                with self.assertRaises(PlanError) as caught:
                    p.generate({'family': 'trend'})
                self.assertEqual(caught.exception.code, 'response_id_mismatch')
                receipts = p.read_receipts()
                self.assertEqual(len(receipts), 1)
                self.assertEqual(receipts[0]['status'], 'response_id_mismatch')
                self.assertIsNone(receipts[0]['response_hash'])
                with self.assertRaises(PlanError):
                    p.generate({'family': 'trend'})
                self.assertEqual(len(p.read_receipts()), 1)

    def test_p3_each_present_identity_requires_valid_type_and_length(self):
        for location in ('top', 'nested'):
            for index, bad in enumerate((None, False, 0, '', [], {}, 'x' * 257)):
                with self.subTest(location=location, bad=bad):
                    event = terminal()
                    event['response_id'] = 'resp_fixture'
                    if location == 'top':
                        event['response_id'] = bad
                    else:
                        event['response']['id'] = bad
                    MockTransport.events = [frame(event)]
                    p = provider(self.tmp_path / (location + str(index)))
                    with self.assertRaises(PlanError) as caught:
                        p.generate({'family': 'trend'})
                    self.assertEqual(caught.exception.code, 'invalid_response_id')
                    self.assertEqual(p.read_receipts()[0]['status'], 'invalid_response_id')

    def test_p3_matching_and_omitted_identity_fields_remain_supported(self):
        for location in ('both', 'top', 'nested', 'neither'):
            with self.subTest(location=location):
                event = terminal({'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3})
                if location in ('both', 'top'):
                    event['response_id'] = 'resp_fixture'
                if location in ('top', 'neither'):
                    event['response'].pop('id')
                MockTransport.events = [frame({'type': 'response.output_text.delta', 'delta': 'fixture'}), frame(event)]
                p = provider(self.tmp_path / location)
                self.assertEqual(p.generate({'family': 'trend'}), CANDIDATE)
                receipt = p.read_receipts()[0]
                self.assertEqual(receipt['status'], 'completed')
                self.assertEqual(receipt['token_usage'], {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3})

    def test_p5_actual_worker_death(self):
        process = multiprocessing.get_context('spawn').Process(target=crash_after_reservation, args=(str(self.tmp_path),))
        process.start()
        process.join(10)
        try:
            assert process.exitcode == 0
            p = provider(self.tmp_path)
            with self.assertRaises(PlanError):
                p.generate({'family': 'trend'})
            assert len(p.read_receipts()) == 1
            assert MockTransport.requests == []
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()

    def test_p1_http_wire_and_failures(self):
        import time

        reference = provider(self.tmp_path).credential_reference
        limits = dict(deadline=time.monotonic() + 30, stall_seconds=10, max_request_bytes=65536, max_response_bytes=262144)
        request = {'model': 'fixture-model', 'input': [], 'instructions': 'mock', 'stream': True, 'store': False}
        FakeHTTPS.requests = []
        with patch('http.client.HTTPSConnection', FakeHTTPS), patch.object(OAuthCredentialReference, '__call__', return_value='fixture-oauth-secret'):
            FakeResponse.status = 200
            FakeResponse.headers = {'Content-Type': 'text/event-stream'}
            FakeResponse.chunks = [frame(terminal())]
            assert list(RealTransport().stream(reference, request, limits)) == [frame(terminal())]
            host, args, kwargs = FakeHTTPS.requests[-1]
            assert host == ('api.openai.com', 443)
            assert args == ('POST', '/v1/responses')
            assert kwargs['headers']['Authorization'] == 'Bearer fixture-oauth-secret'
            assert json.loads(kwargs['body']) == request
            for status, headers, chunks in (
                (302, {}, []),
                (200, {'Content-Type': 'application/json'}, []),
                (200, {'Content-Encoding': 'gzip'}, []),
                (200, {'Content-Length': '999999999'}, []),
                (200, {'Content-Type': 'text/event-stream'}, [TimeoutError()]),
                (403, {'Content-Type': 'application/json'}, [b'{"detail":"subscription_sharing_user_not_eligible"}']),
            ):
                with self.subTest(status=status, headers=headers):
                    FakeResponse.status = status
                    FakeResponse.headers = headers
                    FakeResponse.chunks = chunks
                    with self.assertRaises(PlanError):
                        list(RealTransport().stream(reference, request, limits))
            with self.assertRaises(PlanError):
                with RealTransport()._response(reference, 'POST', 'https://attacker.invalid', None, limits, None):
                    pass
        assert b'fixture-oauth-secret' not in pickle.dumps(provider(self.tmp_path))

    def test_p1_missing_stream_content_type_still_requires_a_valid_completed_stream(self):
        # Owner-approved 2026-10-23: the official streamed reply can omit Content-Type entirely.
        import time

        p = provider(self.tmp_path)
        reference = p.credential_reference
        limits = dict(deadline=time.monotonic() + 30, stall_seconds=10, max_request_bytes=65536, max_response_bytes=262144)
        request = {'model': 'fixture-model', 'input': [], 'instructions': 'mock', 'stream': True, 'store': False}
        with patch('http.client.HTTPSConnection', FakeHTTPS), patch.object(OAuthCredentialReference, '__call__', return_value='fixture-oauth-secret'):
            FakeResponse.status = 200
            FakeResponse.headers = {}
            FakeResponse.chunks = [frame(terminal())]
            self.assertEqual(list(RealTransport().stream(reference, request, limits)), [frame(terminal())])

            class RealStream(RealTransport):
                # Only the catalog GET uses the fixture; the streamed POST uses the real wire checks.
                def models(self, reference, limits, cancelled):
                    return MockTransport().models(reference, limits, cancelled)

            with patch('desktop_chatgpt_provider.PlanHTTPTransport', RealStream):
                # The full provider path still parses strictly and records a completed receipt.
                FakeResponse.chunks = [frame(terminal())]
                self.assertEqual(p.generate({'family': 'trend'}), CANDIDATE)
                self.assertEqual([row['status'] for row in p.read_receipts()], ['completed'])
                for name, chunks in (('garbage', [b'<html>not a stream</html>']), ('no_completion', [frame({'type': 'response.created'})])):
                    with self.subTest(body=name):
                        q = provider(self.tmp_path / name)
                        FakeResponse.headers = {}
                        FakeResponse.chunks = list(chunks)
                        with self.assertRaises(PlanError):
                            q.generate({'family': 'trend'})
                        self.assertNotEqual(q.read_receipts()[-1]['status'], 'completed')
            # A present but different (or empty) type is still refused, and GET always needs JSON.
            for headers in (
                {'Content-Type': ''},
                {'Content-Type': 'application/json'},
                {'Content-Type': 'text/html; charset=utf-8'},
                {'Content-Type': 'text/plain'},
            ):
                with self.subTest(headers=headers):
                    FakeResponse.headers = headers
                    FakeResponse.chunks = [frame(terminal())]
                    with self.assertRaises(PlanError) as caught:
                        list(RealTransport().stream(reference, request, limits))
                    self.assertEqual(caught.exception.code, 'invalid_content_type')
            FakeResponse.headers = {}
            FakeResponse.chunks = [b'{"models":[]}']
            with self.assertRaises(PlanError) as caught:
                RealTransport().models(reference, limits, None)
            self.assertEqual(caught.exception.code, 'invalid_content_type')
            FakeResponse.headers = {'Content-Type': 'text/event-stream'}

    def test_p5_multiprocess_atomic_pending_barrier(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        processes = [context.Process(target=competing_reservation, args=(str(self.tmp_path), queue)) for _ in range(6)]
        try:
            for process in processes:
                process.start()
            results = [queue.get(timeout=10) for _ in processes]
            for process in processes:
                process.join(10)
            assert [value for value in results if value is not None] == [1]
            assert len(provider(self.tmp_path).read_receipts()) == 1
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            queue.close()
            queue.join_thread()

    def test_p6_account_pause_cross_campaign_and_explicit_recovery(self):
        p = provider(self.tmp_path)
        MockTransport.events = [frame({'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}})]
        with self.assertRaises(PlanError):
            p.generate({'family': 'trend'})
        other = provider(self.tmp_path, budget_path=p.path.parent / 'other.sqlite', campaign_id='second')
        with self.assertRaises(PlanError):
            other.generate({'family': 'trend'})
        assert len(MockTransport.requests) == 1
        with self.assertRaises(PlanError):
            clear_account_pause(p.credential_reference, p.path.parent)
        clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True)
        MockTransport.events = None
        assert other.generate({'family': 'trend'}) == CANDIDATE
        # Recovery never refunds/resets the failed campaign itself.
        with self.assertRaises(PlanError):
            p.generate({'family': 'trend'})
        assert len(MockTransport.requests) == 2

    def test_p5_account_unknown_cross_campaign(self):
        p = provider(self.tmp_path)
        p._reserve('0' * 64, 100)
        other = provider(self.tmp_path, budget_path=p.path.parent / 'other.sqlite', campaign_id='second')
        with self.assertRaises(PlanError):
            other.generate({'family': 'trend'})
        with self.assertRaises(PlanError):
            other._reserve('1' * 64, 100)
        with self.assertRaises(PlanError):
            clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True)
        assert MockTransport.requests == []

    def test_p5_changed_control_directory_rejected(self):
        p = provider(self.tmp_path)
        p._reserve('0' * 64, 100)
        for path in (self.tmp_path / 'restored' / 'plan.sqlite', self.tmp_path / 'other' / 'plan.sqlite'):
            with self.subTest(path=path):
                with self.assertRaises(PlanError):
                    provider(self.tmp_path, budget_path=path, campaign_id='changed', model='another-model')
        with self.assertRaises(PlanError):
            clear_account_pause(p.credential_reference, self.tmp_path / 'restored', user_confirmed=True)
        assert not (self.tmp_path / 'restored').exists()
        assert MockTransport.requests == []

    def test_p5_noncanonical_control_paths(self):
        for path in ('relative.sqlite', ':memory:', 'file:controls.sqlite?mode=memory'):
            with self.subTest(path=path):
                with self.assertRaises(PlanError):
                    provider(self.tmp_path, budget_path=path)
        p = provider(self.tmp_path)
        with self.assertRaises(PlanError):
            provider(self.tmp_path, budget_path=p.account_path)
        p.path.parent.mkdir(parents=True)
        target = self.tmp_path / 'target.sqlite'
        target.touch()
        try:
            p.path.symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit synthetic symlink creation')
        with self.assertRaises(PlanError):
            provider(self.tmp_path)

    def test_p5_readonly_sanitized_account_status(self):
        p = provider(self.tmp_path)
        assert read_account_status(p.credential_reference, p.path.parent) == {'state': 'ready', 'pending': False}
        assert not p.path.parent.exists()
        p._reserve('0' * 64, 100)
        assert read_account_status(p.credential_reference, p.path.parent) == {'state': 'reserved_unknown', 'pending': True}
        p._finish(1, 'quota_paused')
        assert read_account_status(p.credential_reference, p.path.parent) == {'state': 'quota_paused', 'pending': False}
        with self.assertRaises(PlanError):
            read_account_status(p.credential_reference, self.tmp_path / 'different')

    def test_readonly_identity_without_new_consent(self):
        acknowledged = provider(self.tmp_path)
        readonly = provider(self.tmp_path, network_opt_in=False, included_usage_policy_confirmed=False)
        assert readonly.provider_descriptor() == acknowledged.provider_descriptor()
        assert readonly.provider_descriptor()['included_usage_policy_ack_required'] is True
        with self.assertRaises(PlanError):
            readonly.generate({'family': 'trend'})
        network_only = provider(self.tmp_path, network_opt_in=True, included_usage_policy_confirmed=False)
        with self.assertRaises(PlanError):
            network_only.generate({'family': 'trend'})
        assert MockTransport.requests == [] and not readonly.path.exists()
        acknowledged.generate({'family': 'trend'})
        assert len(readonly.read_receipt_snapshot()['receipts']) == 1

    def test_missing_global_control_database_never_reinitializes(self):
        p = provider(self.tmp_path)
        p._reserve('a' * 64, 100)
        p.account_path.unlink()
        other = provider(self.tmp_path, budget_path=p.path.parent / 'other.sqlite', campaign_id='other')
        with self.assertRaises(PlanError):
            other._reserve('b' * 64, 100)
        with self.assertRaises(PlanError):
            read_account_status(p.credential_reference, p.path.parent)
        with patch.object(MockTransport, 'models') as metadata:
            with self.assertRaises(PlanError):
                other.generate({'family': 'trend'})
            metadata.assert_not_called()
        assert not p.account_path.exists() and not other.path.exists()

    def test_missing_expected_campaign_database_is_not_empty_success(self):
        p = provider(self.tmp_path)
        p._reserve('a' * 64, 100)
        p.path.unlink()
        with self.assertRaises(PlanError):
            p.read_receipt_snapshot()
        with self.assertRaises(PlanError):
            p.read_receipts()
        with self.assertRaises(PlanError):
            p._reserve('b' * 64, 100)
        assert not p.path.exists()

    def test_old_or_reset_campaign_database_rejected(self):
        p = provider(self.tmp_path, max_calls=3)
        p._reserve('a' * 64, 100)
        p._finish(1, 'completed')
        old = p.path.read_bytes()
        p._reserve('b' * 64, 100)
        p._finish(2, 'completed')
        for replacement in (old, b''):
            p.path.write_bytes(replacement)
            with self.assertRaises(PlanError):
                p.read_receipt_snapshot()
            with self.assertRaises(PlanError):
                p._reserve('c' * 64, 100)
            assert p.path.read_bytes() == replacement

    def test_corrupt_global_campaign_and_receipt_fail_closed(self):
        import sqlite3

        for kind in ('global', 'campaign', 'receipt'):
            with self.subTest(kind=kind):
                p = provider(self.tmp_path / kind)
                p._reserve('a' * 64, 100)
                if kind == 'global':
                    p.account_path.write_bytes(b'not a sqlite database')
                elif kind == 'campaign':
                    p.path.write_bytes(b'not a sqlite database')
                else:
                    with closing(sqlite3.connect(p.path)) as db, db:
                        db.execute('UPDATE plan_calls SET usage=?', ('{"api_key":"SECRET_FIXTURE"}',))
                for operation in (p.read_receipt_snapshot, lambda: p._reserve('b' * 64, 100)):
                    with self.assertRaises(PlanError) as caught:
                        operation()
                    assert 'SECRET_FIXTURE' not in str(caught.exception)

    def test_partial_initialization_is_not_silently_retried(self):
        import sqlite3

        p = provider(self.tmp_path)
        with patch('desktop_chatgpt_provider.sqlite3.connect', side_effect=sqlite3.OperationalError('synthetic init crash')):
            with self.assertRaises(PlanError):
                p._reserve('a' * 64, 100)
        marker = Path(p.credential_reference.bootstrap) / 'chatgpt-plan-controls-v1.marker'
        assert marker.exists() and not p.account_path.exists()
        with self.assertRaises(PlanError):
            p._reserve('a' * 64, 100)
        with self.assertRaises(PlanError):
            p.read_receipt_snapshot()
        assert not p.account_path.exists()

    def test_first_use_and_unused_campaign_reads_are_inert(self):
        p = provider(self.tmp_path)
        assert p.read_receipt_snapshot()['receipts'] == []
        assert not p.path.parent.exists()
        p._reserve('a' * 64, 100)
        p._finish(1, 'completed')
        unused = provider(self.tmp_path, budget_path=p.path.parent / 'unused.sqlite', campaign_id='unused')
        assert unused.read_receipt_snapshot()['receipts'] == [] and not unused.path.exists()
        assert p.read_receipt_snapshot()['receipts'][0]['sequence'] == 1

    def test_missing_marker_does_not_adopt_existing_controls(self):
        p = provider(self.tmp_path)
        p._reserve('a' * 64, 100)
        marker = Path(p.credential_reference.bootstrap) / 'chatgpt-plan-controls-v1.marker'
        marker.unlink()
        with self.assertRaises(PlanError):
            p.read_receipt_snapshot()
        with self.assertRaises(PlanError):
            p._reserve('b' * 64, 100)
        assert not marker.exists()

    def test_partial_global_schema_is_not_repaired(self):
        import sqlite3

        p = provider(self.tmp_path)
        original = sqlite3.connect

        class InterruptedInit(sqlite3.Connection):
            def execute(self, statement, *args, **kwargs):
                if statement.startswith('CREATE TABLE plan_ledgers'):
                    raise sqlite3.OperationalError('synthetic interrupted schema')
                return super().execute(statement, *args, **kwargs)

        def connect(*args, **kwargs):
            return original(*args, **kwargs, factory=InterruptedInit)

        with patch('desktop_chatgpt_provider.sqlite3.connect', connect):
            with self.assertRaises(PlanError):
                p._reserve('a' * 64, 100)
        before = p.account_path.read_bytes()
        with self.assertRaises(PlanError):
            p._reserve('a' * 64, 100)
        assert p.account_path.read_bytes() == before

    def test_provider_connections_close_explicitly_on_success_and_rejection(self):
        import sqlite3
        from tests.test_research import tracked_sqlite_connections

        # Retain every connection object so CPython refcounts/GC cannot conceal
        # leaked handles on POSIX while Windows keeps the files locked.
        with tracked_sqlite_connections() as opened:
            p = provider(self.tmp_path)
            p._reserve('a' * 64, 100)
            self.assertEqual(p.read_receipt_snapshot()['receipts'][0]['status'], 'reserved_unknown')
            p._finish(1, 'completed')
            self.assertEqual(len(p.read_receipts()), 1)
            self.assertTrue(opened)
            self.assertTrue(all(db.closed_explicitly for db in opened))
            with self.assertRaises(PlanError):
                provider(self.tmp_path, max_calls=3).read_receipt_snapshot()
            self.assertTrue(all(db.closed_explicitly for db in opened))
            with closing(sqlite3.connect(p.path)) as db, db:
                db.execute('UPDATE plan_calls SET usage=?', ('{"api_key":"SECRET_FIXTURE"}',))
            with self.assertRaises(PlanError):
                p.read_receipt_snapshot()
            self.assertTrue(all(db.closed_explicitly for db in opened))

    def distinct_registration(self, letter='b', filename='b.sqlite', **changes):
        root = self.tmp_path
        return provider(
            root,
            credential_reference=OAuthCredentialReference(str(root / 'auth'), letter * 32),
            budget_path=root / 'auth' / 'control-v1' / filename,
            campaign_id=filename,
            **changes,
        )

    def test_cross_registration_unknown_blocks_reserve_status_discovery_and_generate(self):
        a = provider(self.tmp_path)
        a._reserve('a' * 64, 100)
        b = self.distinct_registration()
        self.assertEqual(read_account_status(b.credential_reference, b.path.parent), {'state': 'reserved_unknown', 'pending': True})
        with self.assertRaises(PlanError):
            b._reserve('b' * 64, 100)
        with patch.object(MockTransport, 'models') as metadata:
            with self.assertRaises(PlanError):
                b.generate({'family': 'trend'})
            with self.assertRaises(PlanError):
                discover_models(b.credential_reference, network_opt_in=True)
            metadata.assert_not_called()
        self.assertEqual(len(a.read_receipt_snapshot()['receipts']), 1)
        self.assertEqual(b.read_receipt_snapshot()['receipts'], [])
        # Reconstructing another opaque grant is an offline signout/re-register
        # simulation, not an actual authentication flow or a same-human claim.
        c = self.distinct_registration('c', 'c.sqlite')
        with self.assertRaises(PlanError):
            c._reserve('c' * 64, 100)
        self.assertTrue(read_account_status(c.credential_reference, c.path.parent)['pending'])

    def test_cross_registration_known_pause_clear_is_selected_explicit_and_no_refund(self):
        a = provider(self.tmp_path)
        a._reserve('a' * 64, 100)
        a._finish(1, 'quota_paused')
        b = self.distinct_registration()
        self.assertEqual(read_account_status(b.credential_reference, b.path.parent), {'state': 'quota_paused', 'pending': False})
        with self.assertRaises(PlanError):
            b._reserve('b' * 64, 100)
        with self.assertRaises(PlanError):
            clear_account_pause(b.credential_reference, b.path.parent, user_confirmed=True)
        with self.assertRaises(PlanError):
            clear_account_pause(a.credential_reference, a.path.parent)
        before = a.read_receipt_snapshot()
        clear_account_pause(a.credential_reference, a.path.parent, user_confirmed=True)
        self.assertEqual(a.read_receipt_snapshot(), before)
        with self.assertRaises(PlanError):
            a._reserve('b' * 64, 100)
        self.assertEqual(b._reserve('b' * 64, 100), 1)
        b._finish(1, 'completed')
        self.assertEqual(len(a.read_receipts()), 1)
        self.assertEqual(len(b.read_receipts()), 1)
        self.assertNotEqual(a.provider_descriptor()['registration'], b.provider_descriptor()['registration'])

    def test_clear_selected_known_pause_refuses_unknown_elsewhere(self):
        b = self.distinct_registration()
        b._reserve('b' * 64, 100)
        a = provider(self.tmp_path)
        # A delayed metadata error may arrive while another call is already
        # reserved; mock the durable error only, never send HTTP.
        a._pause_account('quota_paused')
        with self.assertRaises(PlanError):
            clear_account_pause(a.credential_reference, a.path.parent, user_confirmed=True)
        self.assertEqual(read_account_status(a.credential_reference, a.path.parent), {'state': 'reserved_unknown', 'pending': True})
        b._finish(1, 'completed')
        clear_account_pause(a.credential_reference, a.path.parent, user_confirmed=True)
        self.assertEqual(read_account_status(a.credential_reference, a.path.parent), {'state': 'ready', 'pending': False})
        self.assertEqual(len(b.read_receipts()), 1)

    def test_completed_registration_does_not_reset_owned_call_caps(self):
        a = provider(self.tmp_path, max_calls=1)
        a._reserve('a' * 64, 100)
        a._finish(1, 'completed')
        b = self.distinct_registration(max_calls=1)
        self.assertEqual(b.read_receipts(), [])
        self.assertEqual(b._reserve('b' * 64, 100), 1)
        b._finish(1, 'completed')
        with self.assertRaises(PlanError):
            a._reserve('c' * 64, 100)
        with self.assertRaises(PlanError):
            b._reserve('c' * 64, 100)
        self.assertEqual([row['sequence'] for row in a.read_receipts()], [1])
        self.assertEqual([row['sequence'] for row in b.read_receipts()], [1])

    def test_concurrent_distinct_registration_reservation_is_installation_atomic(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        processes = [
            context.Process(target=competing_distinct_registration, args=(str(self.tmp_path), letter * 32, letter + '.sqlite', queue)) for letter in 'abcdef'
        ]
        try:
            for process in processes:
                process.start()
            results = [queue.get(timeout=10) for _ in processes]
            for process in processes:
                process.join(10)
            self.assertEqual([value for value in results if value is not None], [1])
            for letter in 'abcdef':
                p = self.distinct_registration(letter, letter + '.sqlite')
                self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'reserved_unknown', 'pending': True})
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            queue.close()
            queue.join_thread()

    def test_other_registration_expected_ledger_damage_blocks_all_new_work(self):
        import sqlite3
        from tests.test_research import tracked_sqlite_connections

        for damage in ('missing', 'corrupt', 'reset', 'rollback'):
            with self.subTest(damage=damage), tracked_sqlite_connections() as opened:
                root = self.tmp_path / damage
                a = provider(root, max_calls=3)
                a._reserve('a' * 64, 100)
                a._finish(1, 'completed')
                old = a.path.read_bytes()
                a._reserve('b' * 64, 100)
                a._finish(2, 'completed')
                b = provider(
                    root, credential_reference=OAuthCredentialReference(str(root / 'auth'), 'b' * 32), budget_path=a.path.parent / 'b.sqlite', campaign_id='b'
                )
                if damage == 'missing':
                    a.path.unlink()
                else:
                    a.path.write_bytes({'corrupt': b'corrupt fixture', 'reset': b'', 'rollback': old}[damage])
                with self.assertRaises(PlanError):
                    read_account_status(b.credential_reference, b.path.parent)
                with self.assertRaises(PlanError):
                    b._reserve('c' * 64, 100)
                with self.assertRaises(PlanError):
                    clear_account_pause(b.credential_reference, b.path.parent, user_confirmed=True)
                with patch.object(MockTransport, 'models') as metadata:
                    with self.assertRaises(PlanError):
                        b.generate({'family': 'trend'})
                    with self.assertRaises(PlanError):
                        discover_models(b.credential_reference, network_opt_in=True)
                    metadata.assert_not_called()
                if damage == 'missing':
                    self.assertFalse(a.path.exists())
                with closing(sqlite3.connect(a.account_path)) as db:
                    self.assertEqual(db.execute('SELECT calls FROM plan_ledgers').fetchall(), [(2,)])
                self.assertTrue(opened)
                self.assertTrue(all(db.closed_explicitly for db in opened))

    def test_delayed_metadata_error_cannot_downgrade_unknown_inference(self):
        import threading
        import sqlite3

        entered = threading.Event()
        release = threading.Event()
        errors = []

        class DelayedMetadata(MockTransport):
            def models(self, reference, limits, cancelled):
                if threading.current_thread().name == 'late_metadata':
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError('Fixture synchronization failed')
                    raise PlanError('quota_paused')
                return super().models(reference, limits, cancelled)

            def stream(self, *args, **kwargs):
                raise PlanError('http_transport_failed')

        a = provider(self.tmp_path)
        b = provider(self.tmp_path, budget_path=a.path.parent / 'late.sqlite', campaign_id='late')

        def late_call():
            try:
                b.generate({'family': 'trend'})
            except PlanError as exc:
                errors.append(exc.code)

        with patch('desktop_chatgpt_provider.PlanHTTPTransport', DelayedMetadata):
            thread = threading.Thread(target=late_call, name='late_metadata')
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(PlanError):
                    a.generate({'family': 'trend'})
                release.set()
                thread.join(5)
                self.assertFalse(thread.is_alive())
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(errors, ['quota_paused'])
        with closing(sqlite3.connect(a.account_path)) as db:
            self.assertEqual(db.execute('SELECT state FROM plan_accounts').fetchall(), [('http_transport_failed',)])
        with self.assertRaises(PlanError):
            clear_account_pause(b.credential_reference, b.path.parent, user_confirmed=True)
        c = self.distinct_registration('c', 'new-grant.sqlite')
        with self.assertRaises(PlanError):
            c._reserve('c' * 64, 100)
        self.assertTrue(read_account_status(c.credential_reference, c.path.parent)['pending'])
        self.assertEqual(a.read_receipts()[0]['status'], 'http_transport_failed')

    def test_indexed_ledger_inspection_deadline_is_bounded_and_closes_handles(self):
        from tests.test_research import tracked_sqlite_connections

        a = provider(self.tmp_path)
        a._reserve('a' * 64, 100)
        a._finish(1, 'completed')
        with tracked_sqlite_connections() as opened, patch('desktop_chatgpt_provider.time.monotonic', side_effect=[0, 6]):
            with self.assertRaises(PlanError):
                read_account_status(a.credential_reference, a.path.parent)
            self.assertTrue(opened)
            self.assertTrue(all(db.closed_explicitly for db in opened))

    def test_standalone_discovery_persists_known_pause_without_inference_debit(self):
        import sqlite3

        catalog = {'models': [{'slug': 'fixture-model', 'display_name': 'Fixture', 'visibility': 'list'}]}
        for state in sorted(set(ERROR_STATES.values())):
            with self.subTest(state=state):
                root = self.tmp_path / state
                a = provider(root)
                b = provider(
                    root, credential_reference=OAuthCredentialReference(str(root / 'auth'), 'b' * 32), budget_path=a.path.parent / 'b.sqlite', campaign_id='b'
                )
                with patch.object(MockTransport, 'models', side_effect=[PlanError(state), catalog]) as metadata:
                    with self.assertRaises(PlanError):
                        discover_models(a.credential_reference, network_opt_in=True)
                    self.assertEqual(read_account_status(b.credential_reference, b.path.parent), {'state': state, 'pending': False})
                    with self.assertRaises(PlanError):
                        discover_models(b.credential_reference, network_opt_in=True)
                    self.assertEqual(metadata.call_count, 1)
                    self.assertFalse(a.path.exists())
                    self.assertFalse(b.path.exists())
                    with closing(sqlite3.connect(a.account_path)) as db:
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM plan_ledgers').fetchone()[0], 0)
                    clear_account_pause(a.credential_reference, a.path.parent, user_confirmed=True)
                    self.assertEqual(discover_models(b.credential_reference, network_opt_in=True), [{'slug': 'fixture-model', 'display_name': 'Fixture'}])
                    self.assertEqual(metadata.call_count, 2)
                self.assertEqual(a.read_receipts(), [])
                self.assertEqual(b.read_receipts(), [])


def competing_unknown_resolution(path, ready, release, results):
    """Two fresh workers contend for one synthetic, already-aged receipt."""
    from desktop_chatgpt_provider import ACKNOWLEDGEMENT_VERSION, resolve_unknown_request

    root = Path(path)
    reference = OAuthCredentialReference(str(root / 'auth'), 'a' * 32)
    with (
        patch('desktop_chatgpt_provider.implementation_provenance', return_value=SYNTHETIC_PROVENANCE),
        patch('http.client.HTTPSConnection', side_effect=AssertionError('No live HTTP')),
        patch.object(OAuthCredentialReference, '__call__', side_effect=AssertionError('No credential access')),
    ):
        ready.put(True)
        if not release.wait(10):
            raise AssertionError('Fixture synchronization failed')
        try:
            resolve_unknown_request(reference, root / 'auth' / 'control-v1', user_confirmed=True, acknowledgement_version=ACKNOWLEDGEMENT_VERSION)
        except PlanError as exc:
            results.put(exc.code)
        else:
            results.put('resolved')


class UnknownRequestResolutionTests(unittest.TestCase):
    """R1 offline reconciliation, including durable refusal and tamper checks."""

    def setUp(self):
        import desktop_chatgpt_provider as module

        self.module = module
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp_path = Path(self.temp.name)
        for patcher in (
            patch.dict(os.environ, {'LOCALAPPDATA': str(self.tmp_path / 'local-appdata'), 'APPDATA': str(self.tmp_path / 'appdata')}),
            patch('desktop_chatgpt_provider.implementation_provenance', return_value=SYNTHETIC_PROVENANCE),
            patch('http.client.HTTPSConnection', side_effect=AssertionError('No live HTTP')),
            patch.object(OAuthCredentialReference, '__call__', side_effect=AssertionError('No credential access')),
            patch('desktop_chatgpt_provider.PlanHTTPTransport', MockTransport),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        MockTransport.requests = []
        MockTransport.events = None

    def aged_pending(self, root=None, **kwargs):
        p = provider(root or self.tmp_path, **kwargs)
        p._reserve('a' * 64, 123)
        self.age(p)
        return p

    def age(self, p, seconds=301):
        import time

        stamp = time.time() - seconds
        os.utime(p.path, (stamp, stamp))

    def resolve(self, p, **kwargs):
        options = {'user_confirmed': True, 'acknowledgement_version': self.module.ACKNOWLEDGEMENT_VERSION}
        options.update(kwargs)
        return self.module.resolve_unknown_request(p.credential_reference, p.path.parent, **options)

    def inspect(self, p):
        return self.module.inspect_unknown_request(p.credential_reference, p.path.parent)

    def files(self):
        return {str(path.relative_to(self.tmp_path)): path.read_bytes() for path in self.tmp_path.rglob('*') if path.is_file()}

    def unchanged_refusal(self, operation, code):
        before = self.files()
        with self.assertRaises(PlanError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.files(), before, 'A refused operation must leave every control/ledger byte unchanged')
        self.assertEqual(MockTransport.requests, [])

    def rows(self, path, statement, parameters=()):
        import sqlite3

        with closing(sqlite3.connect(path)) as db:
            return db.execute(statement, parameters).fetchall()

    def mutate(self, path, statement, parameters=()):
        import sqlite3

        with closing(sqlite3.connect(path)) as db, db:
            db.execute(statement, parameters)

    def test_k1_resolution_preserves_receipt_evidence_counts_and_known_pause(self):
        from datetime import datetime
        from quantlab.core import content_hash

        p = self.aged_pending()
        original = p.read_receipts()[0]
        self.assertIsNone(self.resolve(p))
        receipt = p.read_receipts()[0]
        self.assertEqual(receipt, {**original, 'status': 'user_confirmed_consumed'})
        self.assertEqual(self.rows(p.path, 'SELECT calls,blocked FROM plan_budget'), [(1, 'user_confirmed_consumed')])
        self.assertEqual(self.rows(p.account_path, 'SELECT calls FROM plan_ledgers'), [(1,)])
        self.assertEqual(self.rows(p.account_path, 'SELECT state,owner FROM plan_accounts'), [('user_confirmed_consumed', None)])
        self.assertEqual(self.rows(p.account_path, 'SELECT version FROM control_identity'), [(1,)])
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        columns = [row[1] for row in self.rows(p.account_path, 'PRAGMA table_info(plan_resolutions)')]
        audit = dict(zip(columns, self.rows(p.account_path, 'SELECT * FROM plan_resolutions')[0]))
        timestamp = audit.pop('confirmed_at_utc')
        self.assertEqual(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).utcoffset().total_seconds(), 0)
        self.assertEqual(
            audit,
            {
                'id': 1,
                'filename': p.path.name,
                'sequence': 1,
                'request_hash': 'a' * 64,
                'registration': p.credential_reference.registration,
                'previous_status': 'reserved_unknown',
                'new_status': 'user_confirmed_consumed',
                'acknowledgement_version': self.module.ACKNOWLEDGEMENT_VERSION,
                'official_usage_checked': 1,
                'no_refund_acknowledged': 1,
                'no_other_tool_acknowledged': 1,
                'implementation_hash': content_hash(SYNTHETIC_PROVENANCE),
            },
        )
        for path in (p.path, p.account_path):
            self.assertEqual(self.rows(path, 'PRAGMA journal_mode'), [('delete',)])
        with patch.object(MockTransport, 'models') as models:
            self.unchanged_refusal(lambda: p._reserve('b' * 64, 100), 'account_paused')
            self.unchanged_refusal(lambda: p.generate({'family': 'trend'}), 'account_paused')
            self.unchanged_refusal(lambda: discover_models(p.credential_reference, network_opt_in=True), 'account_paused')
            models.assert_not_called()

    def test_two_step_recovery_allows_new_campaign_but_never_refunds_old_one(self):
        p = self.aged_pending()
        self.resolve(p)
        self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent), 'explicit_recovery_confirmation_required')
        other_reference = OAuthCredentialReference(p.credential_reference.bootstrap, 'b' * 32)
        self.unchanged_refusal(lambda: clear_account_pause(other_reference, p.path.parent, user_confirmed=True), 'pause_owned_by_another_registration')
        clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True)
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'ready', 'pending': False})
        self.unchanged_refusal(lambda: p.generate({'family': 'trend'}), 'campaign_paused')
        self.unchanged_refusal(lambda: p._reserve('b' * 64, 100), 'campaign_paused')
        fresh = provider(self.tmp_path, budget_path=p.path.parent / 'new.sqlite', campaign_id='new')
        self.assertEqual(fresh.generate({'family': 'trend'}), CANDIDATE)
        self.assertEqual(len(MockTransport.requests), 1)
        self.assertEqual(self.rows(p.path, 'SELECT calls,blocked FROM plan_budget'), [(1, 'user_confirmed_consumed')])
        self.assertEqual(self.rows(p.account_path, 'SELECT calls FROM plan_ledgers WHERE filename=?', (p.path.name,)), [(1,)])
        self.assertEqual(self.rows(p.account_path, 'SELECT COUNT(*) FROM plan_resolutions'), [(1,)])

    def test_inspection_is_readonly_sanitized_and_never_initializes_controls(self):
        import sqlite3

        unused = provider(self.tmp_path)
        before = self.files()
        self.assertEqual(self.inspect(unused), {'kind': 'none', 'sequence': None, 'calls': None, 'max_age_ok': False})
        self.assertEqual(self.files(), before)
        p = self.aged_pending()
        before = self.files()
        connections = []
        writes = []
        original = sqlite3.connect
        forbidden = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_ALTER_TABLE,
        }

        def authorizer(action, name, column, database, source):
            if action in forbidden:
                writes.append((action, name))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def connect(*args, **kwargs):
            connections.append(args[0])
            db = original(*args, **kwargs)
            db.set_authorizer(authorizer)
            return db

        with patch('desktop_chatgpt_provider.sqlite3.connect', connect):
            self.assertEqual(self.inspect(p), {'kind': 'k1_resolvable', 'sequence': 1, 'calls': 1, 'max_age_ok': True})
            reference = OAuthCredentialReference(p.credential_reference.bootstrap, 'b' * 32)
            result = self.module.inspect_unknown_request(reference, p.path.parent)
            self.assertEqual(result, {'kind': 'k1_other_registration', 'sequence': None, 'calls': None, 'max_age_ok': False})
        self.assertTrue(connections)
        self.assertTrue(all('?mode=ro' in str(path) for path in connections))
        self.assertEqual(writes, [])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.rows(p.account_path, "SELECT name FROM sqlite_master WHERE name='plan_resolutions'"), [])
        self.assertEqual(MockTransport.requests, [])

    def test_inspection_does_not_convert_recent_old_or_restarted_unknown(self):
        p = self.aged_pending()
        self.age(p, 299)
        before = self.files()
        self.assertFalse(self.inspect(p)['max_age_ok'])
        self.age(p, 86400)
        restarted = provider(self.tmp_path)
        self.assertTrue(self.inspect(restarted)['max_age_ok'])
        self.assertEqual(read_account_status(restarted.credential_reference, restarted.path.parent), {'state': 'reserved_unknown', 'pending': True})
        self.assertEqual(self.files(), before)
        self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True), 'active_or_unknown_request')

    def test_confirmation_and_version_are_exact_and_required(self):
        p = self.aged_pending()
        self.assertEqual(self.module.ACKNOWLEDGEMENT_VERSION, 1)
        for options in (
            {},
            {'user_confirmed': True},
            {'acknowledgement_version': 1},
            {'user_confirmed': 1, 'acknowledgement_version': 1},
            {'user_confirmed': 'true', 'acknowledgement_version': 1},
            {'user_confirmed': True, 'acknowledgement_version': True},
            {'user_confirmed': True, 'acknowledgement_version': 1.0},
            {'user_confirmed': True, 'acknowledgement_version': '1'},
            {'user_confirmed': True, 'acknowledgement_version': 2},
        ):
            with self.subTest(options=options):
                self.unchanged_refusal(
                    lambda: self.module.resolve_unknown_request(p.credential_reference, p.path.parent, **options), 'resolution_confirmation_required'
                )

    def test_recent_or_future_ledger_cannot_be_resolved(self):
        p = self.aged_pending()
        for seconds in (299, 0, -600):
            with self.subTest(seconds=seconds):
                self.age(p, seconds)
                self.unchanged_refusal(lambda: self.resolve(p), 'unknown_request_too_recent')

    def test_other_registration_and_k2_cannot_be_resolved(self):
        p = self.aged_pending()
        reference = OAuthCredentialReference(p.credential_reference.bootstrap, 'b' * 32)
        self.unchanged_refusal(
            lambda: self.module.resolve_unknown_request(
                reference, p.path.parent, user_confirmed=True, acknowledgement_version=self.module.ACKNOWLEDGEMENT_VERSION
            ),
            'unknown_request_owned_by_another_registration',
        )
        for status in ('failed_or_interrupted', 'cancelled', 'deadline_exceeded', 'eof_without_completion'):
            with self.subTest(status=status):
                k2 = self.aged_pending(self.tmp_path / status)
                k2._finish(1, status, received_bytes=7, elapsed_seconds=1.0)
                self.age(k2)
                before = self.files()
                self.assertEqual(self.inspect(k2), {'kind': 'k2_unresolvable', 'sequence': None, 'calls': None, 'max_age_ok': False})
                self.assertEqual(self.files(), before)
                self.unchanged_refusal(lambda: self.resolve(k2), 'no_resolvable_unknown_request')
                self.assertTrue(read_account_status(k2.credential_reference, k2.path.parent)['pending'])

    def test_no_unknown_request_is_an_inert_refusal(self):
        p = provider(self.tmp_path)
        self.unchanged_refusal(lambda: self.resolve(p), 'no_resolvable_unknown_request')
        self.assertFalse(p.path.parent.exists())
        p._reserve('a' * 64, 100)
        p._finish(1, 'completed')
        self.unchanged_refusal(lambda: self.resolve(p), 'no_resolvable_unknown_request')

    def test_invalid_reference_and_controls_path_leave_all_bytes_unchanged(self):
        p = self.aged_pending()
        arguments = {'user_confirmed': True, 'acknowledgement_version': self.module.ACKNOWLEDGEMENT_VERSION}
        for reference in (None, 'opaque', object()):
            self.unchanged_refusal(lambda: self.module.resolve_unknown_request(reference, p.path.parent, **arguments), 'oauth_reference_required')
        for path in (self.tmp_path / 'workspace', 'relative', p.account_path, None, 1):
            with self.subTest(path=path):
                self.unchanged_refusal(
                    lambda: self.module.resolve_unknown_request(p.credential_reference, path, **arguments), 'installation_controls_path_required'
                )

    def test_missing_and_inconsistent_ledger_are_not_repaired(self):
        for damage, code in (
            ('missing', 'campaign_controls_missing'),
            ('count', 'campaign_controls_inconsistent'),
            ('sequence', 'campaign_controls_inconsistent'),
            ('binding', 'campaign_controls_inconsistent'),
        ):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                if damage == 'missing':
                    p.path.unlink()
                elif damage == 'count':
                    self.mutate(p.path, 'UPDATE plan_budget SET calls=2')
                elif damage == 'sequence':
                    self.mutate(p.path, 'UPDATE plan_calls SET sequence=2')
                else:
                    self.mutate(p.path, 'UPDATE plan_budget SET binding=?', ('b' * 64,))
                if p.path.exists():
                    self.age(p)
                self.unchanged_refusal(lambda: self.resolve(p), code)

    def test_missing_or_ambiguous_owner_binding_cannot_select_a_ledger(self):
        for damage in ('missing_binding', 'duplicate_binding'):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                if damage == 'missing_binding':
                    self.mutate(p.account_path, 'UPDATE plan_accounts SET owner=?', ('b' * 64,))
                else:
                    (p.path.parent / 'duplicate.sqlite').write_bytes(p.path.read_bytes())
                    self.mutate(p.account_path, "INSERT INTO plan_ledgers SELECT 'duplicate.sqlite',binding,calls FROM plan_ledgers")
                self.unchanged_refusal(lambda: self.resolve(p), 'campaign_controls_inconsistent')

    def test_other_unknown_receipt_or_account_owner_blocks_resolution(self):
        for damage in ('second_ledger', 'prior_unknown', 'other_owner'):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                if damage == 'second_ledger':
                    second = p.path.parent / 'other.sqlite'
                    second.write_bytes(p.path.read_bytes())
                    self.mutate(second, 'UPDATE plan_budget SET binding=?', ('b' * 64,))
                    self.mutate(p.account_path, 'INSERT INTO plan_ledgers VALUES (?,?,?)', ('other.sqlite', 'b' * 64, 1))
                elif damage == 'prior_unknown':
                    self.mutate(
                        p.path,
                        "INSERT INTO plan_calls SELECT 2,request_hash,request_bytes,status,response_hash,usage,received_bytes,elapsed_seconds FROM plan_calls",
                    )
                    self.mutate(p.path, 'UPDATE plan_budget SET calls=2')
                    self.mutate(p.account_path, 'UPDATE plan_ledgers SET calls=2')
                    self.age(p)
                else:
                    self.mutate(p.account_path, 'INSERT INTO plan_accounts VALUES (?,?,?)', ('b' * 32, 'reserved_unknown', 'b' * 64))
                self.unchanged_refusal(lambda: self.resolve(p), 'active_or_unknown_request')

    def test_link_and_windows_reparse_controls_are_rejected_without_skip(self):
        from types import SimpleNamespace

        p = self.aged_pending()
        original_lstat = Path.lstat
        original_is_symlink = Path.is_symlink
        for target in (p.path, p.account_path, p.path.parent):
            for kind in ('symlink', 'reparse'):
                with self.subTest(target=target.name, kind=kind):

                    def is_symlink(path):
                        return (kind == 'symlink' and path == target) or original_is_symlink(path)

                    def lstat(path, *args, **kwargs):
                        if kind == 'reparse' and path == target:
                            return SimpleNamespace(st_file_attributes=0x400, st_mode=original_lstat(path).st_mode)
                        return original_lstat(path, *args, **kwargs)

                    before = self.files()
                    with patch.object(Path, 'is_symlink', is_symlink), patch.object(Path, 'lstat', lstat):
                        with self.assertRaises(PlanError) as caught:
                            self.resolve(p)
                        self.assertEqual(caught.exception.code, 'linked_controls_path_rejected')
                    self.assertEqual(self.files(), before)

    def test_forged_confirmed_receipt_or_account_without_audit_stays_pending(self):
        for damage in ('receipt', 'account', 'both'):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                if damage in ('receipt', 'both'):
                    self.mutate(p.path, "UPDATE plan_calls SET status='user_confirmed_consumed'")
                if damage in ('account', 'both'):
                    self.mutate(p.account_path, "UPDATE plan_accounts SET state='user_confirmed_consumed',owner=NULL")
                before = self.files()
                self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
                self.assertEqual(self.files(), before)
                self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True), 'active_or_unknown_request')

    def test_resolution_audit_update_and_delete_abort_without_mutation(self):
        import sqlite3

        p = self.aged_pending()
        self.resolve(p)
        for statement in ('UPDATE plan_resolutions SET acknowledgement_version=99', 'DELETE FROM plan_resolutions'):
            with self.subTest(statement=statement):
                before = self.files()
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'append_only'):
                    self.mutate(p.account_path, statement)
                self.assertEqual(self.files(), before)
        self.unchanged_refusal(lambda: self.resolve(p), 'no_resolvable_unknown_request')

    def test_audit_must_match_receipt_and_registration(self):
        for damage in ('request_hash', 'filename', 'sequence', 'registration', 'missing_audit'):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                self.resolve(p)
                # Deliberate local tampering bypasses triggers solely to test
                # the read barrier's independent receipt/audit cross-check.
                trigger = self.rows(p.account_path, "SELECT sql FROM sqlite_master WHERE name='plan_resolutions_no_update'")[0][0]
                self.mutate(p.account_path, 'DROP TRIGGER plan_resolutions_no_update')
                if damage == 'missing_audit':
                    self.mutate(p.account_path, 'DROP TABLE plan_resolutions')
                else:
                    value = {'request_hash': 'b' * 64, 'filename': 'other.sqlite', 'sequence': 2, 'registration': 'b' * 32}[damage]
                    self.mutate(p.account_path, 'UPDATE plan_resolutions SET ' + damage + '=?', (value,))
                    self.mutate(p.account_path, trigger)
                before = self.files()
                self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
                self.assertEqual(self.files(), before)
                self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True), 'active_or_unknown_request')

    def test_stale_finish_cannot_overwrite_reconciled_receipt_or_account(self):
        p = self.aged_pending()
        self.resolve(p)
        self.unchanged_refusal(lambda: p._finish(1, 'completed', 'b' * 64, {'total_tokens': 3}, 12, 0.5), 'invalid_receipt_transition')
        self.unchanged_refusal(lambda: p._finish(1, 'failed_or_interrupted'), 'invalid_receipt_transition')
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})

    def test_each_transaction_write_failure_rolls_back_all_attached_databases(self):
        import sqlite3

        original = sqlite3.connect
        for action, table in (
            (sqlite3.SQLITE_UPDATE, 'plan_calls'),
            (sqlite3.SQLITE_UPDATE, 'plan_budget'),
            (sqlite3.SQLITE_UPDATE, 'plan_accounts'),
            (sqlite3.SQLITE_INSERT, 'plan_resolutions'),
        ):
            with self.subTest(table=table):
                p = self.aged_pending(self.tmp_path / table)
                denied = []

                def authorizer(operation, name, column, database, source):
                    if operation == action and name == table:
                        denied.append(name)
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                def connect(*args, **kwargs):
                    db = original(*args, **kwargs)
                    db.set_authorizer(authorizer)
                    return db

                before = self.files()
                with patch('desktop_chatgpt_provider.sqlite3.connect', connect), self.assertRaises(PlanError):
                    self.resolve(p)
                self.assertTrue(denied, 'Fixture must reach the requested write failure')
                self.assertEqual(self.files(), before)
                self.assertEqual(p.read_receipts()[0]['status'], 'reserved_unknown')
                self.assertEqual(self.rows(p.account_path, "SELECT name FROM sqlite_master WHERE name='plan_resolutions'"), [])
                self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])

    def test_restart_registration_and_workspace_changes_cannot_bypass_unknown(self):
        p = self.aged_pending()
        for letter in ('a', 'b', 'c'):
            with self.subTest(registration=letter):
                reference = OAuthCredentialReference(p.credential_reference.bootstrap, letter * 32)
                reconstructed = provider(self.tmp_path, credential_reference=reference)
                self.assertTrue(read_account_status(reference, p.path.parent)['pending'])
                with patch.object(MockTransport, 'models') as models:
                    self.unchanged_refusal(lambda: reconstructed.generate({'family': 'trend'}), 'account_paused')
                    self.unchanged_refusal(lambda: discover_models(reference, network_opt_in=True), 'account_paused')
                    models.assert_not_called()
        for workspace in ('restored-workspace', 'new-workspace'):
            target = self.tmp_path / workspace / p.path.name
            self.unchanged_refusal(lambda: provider(self.tmp_path, budget_path=target), 'installation_controls_path_required')
            self.unchanged_refusal(
                lambda: self.module.resolve_unknown_request(
                    p.credential_reference, target.parent, user_confirmed=True, acknowledgement_version=self.module.ACKNOWLEDGEMENT_VERSION
                ),
                'installation_controls_path_required',
            )

    def test_restored_controls_never_turn_resolved_or_new_unknown_work_ready(self):
        p = provider(self.tmp_path, max_calls=3)
        p._reserve('a' * 64, 100)
        p._finish(1, 'completed')
        old_controls = p.account_path.read_bytes()
        p._reserve('b' * 64, 100)
        self.age(p)
        before_resolution = p.account_path.read_bytes()
        self.resolve(p)
        for restored, code in ((before_resolution, None), (old_controls, 'campaign_controls_inconsistent')):
            with self.subTest(old_count=code is not None):
                p.account_path.write_bytes(restored)
                before = self.files()
                if code:
                    self.unchanged_refusal(lambda: read_account_status(p.credential_reference, p.path.parent), code)
                    self.unchanged_refusal(lambda: self.resolve(p), code)
                else:
                    self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
                    self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True), 'active_or_unknown_request')
                self.assertEqual(self.files(), before)

    def test_multiprocess_simultaneous_resolution_has_exactly_one_commit(self):
        p = self.aged_pending()
        context = multiprocessing.get_context('spawn')
        ready, results, release = context.Queue(), context.Queue(), context.Event()
        processes = [context.Process(target=competing_unknown_resolution, args=(str(self.tmp_path), ready, release, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=10))
            release.set()
            outcomes = [results.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            self.assertCountEqual(outcomes, ['resolved', 'no_resolvable_unknown_request'])
            self.assertEqual(self.rows(p.account_path, 'SELECT COUNT(*) FROM plan_resolutions'), [(1,)])
            self.assertEqual(self.rows(p.account_path, 'SELECT calls FROM plan_ledgers'), [(1,)])
            self.assertEqual(self.rows(p.path, 'SELECT calls,blocked FROM plan_budget'), [(1, 'user_confirmed_consumed')])
            self.assertEqual(p.read_receipts()[0]['status'], 'user_confirmed_consumed')
            self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        finally:
            release.set()
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            for queue in (ready, results):
                queue.close()
                queue.join_thread()

    def test_exact_300_second_boundary_is_eligible_without_automatic_transition(self):
        p = self.aged_pending()
        boundary = p.path.stat().st_mtime + 300
        before = self.files()
        with patch('desktop_chatgpt_provider.time.time', return_value=boundary):
            self.assertTrue(self.inspect(p)['max_age_ok'])
            self.assertEqual(self.files(), before)
            self.resolve(p)
        self.assertEqual(p.read_receipts()[0]['status'], 'user_confirmed_consumed')

    def test_ineligible_target_budget_and_final_receipt_are_inert_refusals(self):
        for damage in ('blocked_budget', 'empty_blocked_budget', 'final_receipt'):
            with self.subTest(damage=damage):
                p = self.aged_pending(self.tmp_path / damage)
                if damage == 'final_receipt':
                    self.mutate(p.path, "UPDATE plan_calls SET status='quota_paused'")
                else:
                    self.mutate(p.path, 'UPDATE plan_budget SET blocked=?', ('' if damage == 'empty_blocked_budget' else 'quota_paused',))
                self.age(p)
                self.unchanged_refusal(lambda: self.resolve(p), 'no_resolvable_unknown_request')

    def test_corrupt_ledger_is_an_inert_refusal(self):
        p = self.aged_pending()
        p.path.write_bytes(b'synthetic invalid sqlite ledger')
        self.age(p)
        self.unchanged_refusal(lambda: self.resolve(p), 'campaign_controls_unavailable')
        self.unchanged_refusal(lambda: self.inspect(p), 'campaign_controls_unavailable')

    def test_inspect_preserves_all_file_modification_timestamps(self):
        p = self.aged_pending()
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.tmp_path.rglob('*') if path.is_file()}
        self.inspect(p)
        reference = OAuthCredentialReference(p.credential_reference.bootstrap, 'b' * 32)
        self.module.inspect_unknown_request(reference, p.path.parent)
        after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.tmp_path.rglob('*') if path.is_file()}
        self.assertEqual(after, before)

    def test_new_implementation_resolves_historical_binding_without_reconstructing_it(self):
        from quantlab.core import content_hash

        p = self.aged_pending()
        original_binding = self.rows(p.account_path, 'SELECT binding FROM plan_ledgers')
        new_provenance = {'source_sha256': {'offline_fixture': 'b' * 64}}
        with patch('desktop_chatgpt_provider.implementation_provenance', return_value=new_provenance):
            self.assertEqual(self.inspect(p)['kind'], 'k1_resolvable')
            self.resolve(p)
            self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        self.assertEqual(self.rows(p.account_path, 'SELECT binding FROM plan_ledgers'), original_binding)
        self.assertEqual(self.rows(p.account_path, 'SELECT implementation_hash FROM plan_resolutions'), [(content_hash(new_provenance),)])
        self.assertEqual(p.read_receipts()[0]['status'], 'user_confirmed_consumed')

    def test_provenance_failure_or_incompatible_audit_schema_cannot_partially_resolve(self):
        p = self.aged_pending()
        with patch('desktop_chatgpt_provider.implementation_provenance', side_effect=PlanError('implementation_provenance_unavailable')):
            self.unchanged_refusal(lambda: self.resolve(p), 'implementation_provenance_unavailable')
        self.mutate(p.account_path, 'CREATE TABLE plan_resolutions (incompatible TEXT)')
        self.unchanged_refusal(lambda: self.resolve(p), 'account_controls_unavailable')

    def test_resolution_writes_use_delete_journals_and_full_synchronization(self):
        import sqlite3

        p = self.aged_pending()
        original = sqlite3.connect
        modes = []

        class RecordWriteModes(sqlite3.Connection):
            def execute(self, statement, *args, **kwargs):
                if statement.startswith('INSERT INTO plan_resolutions'):
                    databases = super().execute('PRAGMA database_list').fetchall()
                    for _, schema, _ in databases:
                        if schema == 'temp':
                            continue
                        modes.append(
                            (
                                super().execute('PRAGMA ' + schema + '.journal_mode').fetchone()[0],
                                super().execute('PRAGMA ' + schema + '.synchronous').fetchone()[0],
                            )
                        )
                return super().execute(statement, *args, **kwargs)

        def connect(*args, **kwargs):
            return original(*args, **kwargs, factory=RecordWriteModes)

        with patch('desktop_chatgpt_provider.sqlite3.connect', connect):
            self.resolve(p)
        self.assertEqual(modes, [('delete', 2), ('delete', 2)])

    def test_unsupported_journal_mode_refusal_does_not_reconfigure_or_write(self):
        for target in ('account', 'ledger'):
            with self.subTest(target=target):
                p = self.aged_pending(self.tmp_path / target)
                path = p.account_path if target == 'account' else p.path
                self.assertEqual(self.rows(path, 'PRAGMA journal_mode=WAL'), [('wal',)])
                self.age(p)
                self.unchanged_refusal(lambda: self.resolve(p), 'unsupported_control_journal_mode')

    def test_delayed_known_metadata_pause_cannot_replace_manual_consumption(self):
        p = self.aged_pending()
        self.resolve(p)
        before = self.files()
        self.module._persist_account_pause(p.credential_reference, 'quota_paused')
        self.assertEqual(self.files(), before)
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        self.unchanged_refusal(lambda: self.module._persist_account_pause(p.credential_reference, 'user_confirmed_consumed'), 'invalid_pause_state')

    def test_missing_or_noop_audit_guards_leave_confirmed_status_pending(self):
        for operation in ('UPDATE', 'DELETE'):
            for damage in ('missing', 'noop'):
                with self.subTest(operation=operation, damage=damage):
                    p = self.aged_pending(self.tmp_path / (operation + damage))
                    self.resolve(p)
                    name = 'plan_resolutions_no_' + operation.lower()
                    self.mutate(p.account_path, 'DROP TRIGGER ' + name)
                    if damage == 'noop':
                        self.mutate(p.account_path, 'CREATE TRIGGER ' + name + ' BEFORE ' + operation + ' ON plan_resolutions BEGIN SELECT 1; END')
                    before = self.files()
                    self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
                    self.assertEqual(self.files(), before)
                    self.unchanged_refusal(lambda: clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True), 'active_or_unknown_request')

    def test_existing_noop_audit_guard_cannot_be_adopted_during_resolution(self):
        p = self.aged_pending()
        self.mutate(p.account_path, 'CREATE TABLE plan_resolutions (id INTEGER)')
        self.mutate(p.account_path, 'CREATE TRIGGER plan_resolutions_no_update BEFORE UPDATE ON plan_resolutions BEGIN SELECT 1; END')
        self.unchanged_refusal(lambda: self.resolve(p), 'account_controls_invalid')

    def test_malformed_or_remote_controls_path_is_rejected_before_filesystem_probe(self):
        p = self.aged_pending()
        original_lstat = Path.lstat
        for supplied in ('\0', r'\\offline-invalid.example\share\controls'):
            with self.subTest(supplied=supplied):
                forbidden = Path(supplied)

                def lstat(path, *args, **kwargs):
                    if path == forbidden or path in forbidden.parents:
                        raise AssertionError('Do not probe an untrusted controls path')
                    return original_lstat(path, *args, **kwargs)

                with patch.object(Path, 'lstat', lstat):
                    self.unchanged_refusal(lambda: self.module.inspect_unknown_request(p.credential_reference, supplied), 'installation_controls_path_required')
                    self.unchanged_refusal(
                        lambda: self.module.resolve_unknown_request(
                            p.credential_reference, supplied, user_confirmed=True, acknowledgement_version=self.module.ACKNOWLEDGEMENT_VERSION
                        ),
                        'installation_controls_path_required',
                    )


class FinishedRequestResolutionTests(unittest.TestCase):
    """R2 offline reconciliation of a uniquely mapped finished-unknown (K2) receipt."""

    files = UnknownRequestResolutionTests.files
    rows = UnknownRequestResolutionTests.rows
    mutate = UnknownRequestResolutionTests.mutate
    age = UnknownRequestResolutionTests.age

    def setUp(self):
        UnknownRequestResolutionTests.setUp(self)

    def k2(self, root=None, status='invalid_content_type', **kwargs):
        p = provider(root or self.tmp_path, **kwargs)
        p._reserve('a' * 64, 123)
        p._finish(1, status, received_bytes=0, elapsed_seconds=3.1)
        self.age(p)
        return p

    def inspect(self, p, reference=None):
        return self.module.inspect_finished_unknown_request(reference or p.credential_reference, p.path.parent)

    def resolve(self, p, reference=None, **kwargs):
        options = {
            'user_confirmed': True,
            'acknowledgement_version': self.module.FINISHED_ACKNOWLEDGEMENT_VERSION,
            'expected_sequence': 1,
            'expected_calls': 1,
            'expected_outcome': 'invalid_content_type',
        }
        options.update(kwargs)
        return self.module.resolve_finished_unknown_request(reference or p.credential_reference, p.path.parent, **options)

    def unchanged_refusal(self, operation, code):
        before = self.files()
        with self.assertRaises(PlanError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.files(), before, 'A refused operation must leave every control/ledger byte unchanged')
        self.assertEqual(MockTransport.requests, [])

    def unresolvable(self, p, code='finished_request_unmappable'):
        before = self.files()
        self.assertEqual(self.inspect(p)['kind'], 'k2_unresolvable')
        self.assertEqual(self.files(), before)
        self.unchanged_refusal(lambda: self.resolve(p), code)
        self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])

    def r1_registration(self, p):
        import sqlite3

        with closing(sqlite3.connect(p.account_path)) as db:
            return self.module._resolution_registration(db, 'main', p.path.name, self.rows(p.path, 'SELECT * FROM plan_calls')[0])

    def add_r1_audit(self, p):
        import sqlite3

        with closing(sqlite3.connect(p.account_path)) as db, db:
            self.module._create_resolution_audit(db)
            db.execute(
                'INSERT INTO plan_resolutions (filename,sequence,request_hash,registration,previous_status,new_status,'
                'acknowledgement_version,official_usage_checked,no_refund_acknowledged,no_other_tool_acknowledged,confirmed_at_utc,'
                "implementation_hash) VALUES (?,1,?,?,'reserved_unknown','user_confirmed_consumed',1,1,1,1,'2026-10-23T00:00:00+00:00',?)",
                (p.path.name, 'a' * 64, 'a' * 32, 'c' * 64),
            )

    def test_owner_shape_is_inspected_read_only_and_r1_still_refuses(self):
        p = self.k2()
        before = self.files()
        self.assertEqual(self.inspect(p), {'kind': 'k2_resolvable', 'sequence': 1, 'calls': 1, 'max_age_ok': True, 'outcome': 'invalid_content_type'})
        self.assertEqual(self.files(), before)
        self.assertEqual(
            self.module.inspect_unknown_request(p.credential_reference, p.path.parent),
            {'kind': 'k2_unresolvable', 'sequence': None, 'calls': None, 'max_age_ok': False},
        )
        self.assertEqual(self.rows(p.account_path, "SELECT name FROM sqlite_master WHERE name LIKE 'plan_%resolutions'"), [])

    def test_resolution_preserves_evidence_and_requires_the_existing_clear_pause(self):
        from datetime import datetime
        from quantlab.core import content_hash

        p = self.k2()
        original = p.read_receipts()[0]
        raw = self.rows(p.path, 'SELECT * FROM plan_calls')[0]
        self.assertIsNone(self.resolve(p))
        self.assertEqual(p.read_receipts()[0], {**original, 'status': 'user_confirmed_consumed'})
        self.assertEqual(self.rows(p.path, 'SELECT calls,blocked FROM plan_budget'), [(1, 'invalid_content_type')])
        self.assertEqual(self.rows(p.account_path, 'SELECT calls FROM plan_ledgers'), [(1,)])
        self.assertEqual(self.rows(p.account_path, 'SELECT state,owner FROM plan_accounts'), [('user_confirmed_consumed', None)])
        self.assertEqual(self.rows(p.account_path, "SELECT name FROM sqlite_master WHERE name='plan_resolutions'"), [])
        columns = [row[1] for row in self.rows(p.account_path, 'PRAGMA table_info(plan_finished_resolutions)')]
        audit = dict(zip(columns, self.rows(p.account_path, 'SELECT * FROM plan_finished_resolutions')[0]))
        timestamp = audit.pop('confirmed_at_utc')
        self.assertEqual(datetime.fromisoformat(timestamp).utcoffset().total_seconds(), 0)
        self.assertEqual(
            audit,
            {
                'id': 1,
                'filename': p.path.name,
                'sequence': 1,
                'request_hash': 'a' * 64,
                'receipt_hash': content_hash(list(raw)),
                'registration': p.credential_reference.registration,
                'previous_status': 'invalid_content_type',
                'new_status': 'user_confirmed_consumed',
                'acknowledgement_version': 1,
                'official_usage_checked': 1,
                'no_refund_acknowledged': 1,
                'other_usage_acknowledged': 1,
                'implementation_hash': content_hash(SYNTHETIC_PROVENANCE),
            },
        )
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        fresh = provider(self.tmp_path, budget_path=p.path.parent / 'fresh.sqlite3', campaign_id='fresh')
        with self.assertRaises(PlanError) as caught:
            fresh._reserve('b' * 64, 10)
        self.assertEqual(caught.exception.code, 'account_paused')
        self.assertEqual(self.inspect(p)['kind'], 'none')
        clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True)
        self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'ready', 'pending': False})
        with self.assertRaises(PlanError) as caught:
            p._preflight()
        self.assertEqual(caught.exception.code, 'campaign_paused')
        # The barrier also runs inside _reserve, where the controls are attached as account_controls.
        self.assertEqual(fresh._reserve('b' * 64, 10), 1)
        self.assertEqual(MockTransport.requests, [])

    def test_literal_statuses_equal_the_research_allowlist_minus_known_outcomes(self):
        import ast

        source = (Path(__file__).resolve().parents[1] / 'quantlab/research.py').read_text(encoding='utf-8')
        sets = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'statuses' and isinstance(node.value, ast.Set)
        ]
        self.assertEqual(len(sets), 1)
        allowed = {element.value for element in sets[0].elts}
        expected = allowed - {'completed', 'reserved_unknown', 'user_confirmed_consumed'} - set(ERROR_STATES.values())
        self.assertEqual(set(self.module._FINISHED_UNKNOWN_STATUSES), expected)
        self.assertEqual(len(expected), 40)

    def test_every_finished_unknown_code_is_resolvable_when_uniquely_mapped(self):
        for status in sorted(self.module._FINISHED_UNKNOWN_STATUSES):
            with self.subTest(status=status):
                p = self.k2(self.tmp_path / status, status=status)
                self.assertEqual(self.inspect(p)['outcome'], status)
                self.resolve(p, expected_outcome=status)
                self.assertEqual(read_account_status(p.credential_reference, p.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})

    def test_confirmation_and_expected_target_must_match_exactly(self):
        p = self.k2()
        for change in (
            {'user_confirmed': False},
            {'user_confirmed': 1},
            {'acknowledgement_version': True},
            {'acknowledgement_version': 1.0},
            {'acknowledgement_version': '1'},
            {'acknowledgement_version': 2},
            {'expected_sequence': None},
            {'expected_sequence': 0},
            {'expected_calls': True},
            {'expected_outcome': None},
            {'expected_outcome': 'completed'},
            {'expected_outcome': 'quota_paused'},
        ):
            with self.subTest(change=change):
                self.unchanged_refusal(lambda: self.resolve(p, **change), 'resolution_confirmation_required')
        for change in ({'expected_sequence': 2}, {'expected_calls': 2}, {'expected_outcome': 'cancelled'}):
            with self.subTest(change=change):
                self.unchanged_refusal(lambda: self.resolve(p, **change), 'no_resolvable_unknown_request')

    def test_recent_other_registration_and_missing_controls_are_refused(self):
        p = self.k2()
        for seconds in (299, 0, -600):
            with self.subTest(seconds=seconds):
                self.age(p, seconds)
                self.assertFalse(self.inspect(p)['max_age_ok'])
                self.unchanged_refusal(lambda: self.resolve(p), 'unknown_request_too_recent')
        self.age(p)
        other = OAuthCredentialReference(p.credential_reference.bootstrap, 'b' * 32)
        self.assertEqual(self.inspect(p, other), {'kind': 'k2_other_registration', 'sequence': None, 'calls': None, 'max_age_ok': False, 'outcome': None})
        self.unchanged_refusal(lambda: self.resolve(p, other), 'unknown_request_owned_by_another_registration')
        empty = provider(self.tmp_path / 'empty')
        self.assertEqual(self.inspect(empty)['kind'], 'none')
        self.unchanged_refusal(lambda: self.resolve(empty), 'no_resolvable_unknown_request')
        self.assertFalse(empty.path.parent.exists())

    def test_ambiguous_shapes_stay_blocked(self):
        cases = {
            'blocked_mismatch': lambda p: self.mutate(p.path, "UPDATE plan_budget SET blocked='cancelled'"),
            'usage_shape': lambda p: self.mutate(p.path, 'UPDATE plan_calls SET usage=?', ('{"input_tokens":1,"output_tokens":1,"total_tokens":2}',)),
            'response_hash': lambda p: self.mutate(p.path, 'UPDATE plan_calls SET response_hash=?', ('c' * 64,)),
            'account_code_mismatch': lambda p: self.mutate(p.account_path, "UPDATE plan_accounts SET state='cancelled'"),
            'no_account_row': lambda p: self.mutate(p.account_path, 'DELETE FROM plan_accounts'),
            'overwritten_known_pause': lambda p: self.mutate(p.account_path, "UPDATE plan_accounts SET state='quota_paused'"),
            'cleared_row': lambda p: self.mutate(p.account_path, 'UPDATE plan_accounts SET state=NULL'),
            'second_k2_account': lambda p: self.mutate(p.account_path, 'INSERT INTO plan_accounts VALUES (?,?,NULL)', ('b' * 32, 'invalid_content_type')),
            'k1_present': lambda p: self.mutate(p.account_path, 'INSERT INTO plan_accounts VALUES (?,?,?)', ('b' * 32, 'reserved_unknown', 'b' * 64)),
            'unaudited_consumed_account': lambda p: self.mutate(
                p.account_path, 'INSERT INTO plan_accounts VALUES (?,?,NULL)', ('b' * 32, 'user_confirmed_consumed')
            ),
        }
        for name, damage in cases.items():
            with self.subTest(case=name):
                p = self.k2(self.tmp_path / name)
                damage(p)
                self.age(p)
                self.unresolvable(p)

    def hide_k2(self, p):
        # Simulate f985f91-era admission, which ignored other ledgers and overwritable rows.
        self.mutate(p.path, "UPDATE plan_calls SET status='completed'")
        self.mutate(p.path, 'UPDATE plan_budget SET blocked=NULL')
        self.mutate(p.account_path, 'UPDATE plan_accounts SET state=NULL')

    def restore_k2(self, p):
        self.mutate(p.path, "UPDATE plan_calls SET status='invalid_content_type'")
        self.mutate(p.path, "UPDATE plan_budget SET blocked='invalid_content_type'")
        self.mutate(p.account_path, "UPDATE plan_accounts SET state='invalid_content_type' WHERE registration=?", ('a' * 32,))

    def test_two_finished_unknown_ledgers_are_ambiguous(self):
        p = self.k2()
        self.hide_k2(p)
        second = provider(self.tmp_path, budget_path=p.path.parent / 'second.sqlite3', campaign_id='second')
        second._reserve('b' * 64, 5)
        second._finish(1, 'invalid_content_type', received_bytes=0, elapsed_seconds=1.0)
        self.restore_k2(p)
        self.age(second)
        self.age(p)
        self.unresolvable(p)

    def test_k2_with_k1_on_another_registration_is_refused_by_both_entry_points(self):
        p = self.k2()
        self.hide_k2(p)
        other = provider(
            self.tmp_path,
            credential_reference=OAuthCredentialReference(str(self.tmp_path / 'auth'), 'b' * 32),
            budget_path=p.path.parent / 'other.sqlite3',
            campaign_id='other',
        )
        other._reserve('b' * 64, 5)
        self.restore_k2(p)
        self.age(other)
        self.age(p)
        self.unresolvable(p)
        before = self.files()
        with self.assertRaises(PlanError):
            self.module.resolve_unknown_request(
                other.credential_reference, p.path.parent, user_confirmed=True, acknowledgement_version=self.module.ACKNOWLEDGEMENT_VERSION
            )
        self.assertEqual(self.files(), before)

    def test_unaudited_partial_and_tampered_resolutions_stay_pending(self):
        p = self.k2(self.tmp_path / 'receipt_only')
        self.mutate(p.path, "UPDATE plan_calls SET status='user_confirmed_consumed'")
        self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
        self.assertEqual(self.inspect(p)['kind'], 'k2_unresolvable')
        # Torn commit: audit and account row written, receipt still at its outcome code.
        p = self.k2(self.tmp_path / 'torn')
        self.resolve(p)
        self.mutate(p.path, "UPDATE plan_calls SET status='invalid_content_type'")
        self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])
        self.assertEqual(self.inspect(p)['kind'], 'k2_unresolvable')
        for name, tamper in (
            ('received_bytes', lambda p: self.mutate(p.path, 'UPDATE plan_calls SET received_bytes=99')),
            ('elapsed', lambda p: self.mutate(p.path, 'UPDATE plan_calls SET elapsed_seconds=4.0')),
            ('blocked', lambda p: self.mutate(p.path, "UPDATE plan_budget SET blocked='cancelled'")),
            ('no_trigger', lambda p: self.mutate(p.account_path, 'DROP TRIGGER plan_finished_resolutions_no_update')),
            ('duplicate_r1_row', self.add_r1_audit),
        ):
            with self.subTest(tamper=name):
                p = self.k2(self.tmp_path / name)
                self.resolve(p)
                tamper(p)
                self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])

    def test_r1_shaped_audit_cannot_finalize_a_finished_unknown_receipt(self):
        p = self.k2()
        self.mutate(p.path, "UPDATE plan_calls SET status='user_confirmed_consumed'")
        self.mutate(p.account_path, "UPDATE plan_accounts SET state='user_confirmed_consumed'")
        self.add_r1_audit(p)
        # The R1 verifier alone would accept this row; R2 also requires blocked=user_confirmed_consumed.
        self.assertEqual(self.r1_registration(p), 'a' * 32)
        self.assertTrue(read_account_status(p.credential_reference, p.path.parent)['pending'])

    def test_permissive_precreated_table_is_not_adopted_and_audit_is_append_only(self):
        import sqlite3

        p = self.k2(self.tmp_path / 'permissive')
        self.mutate(p.account_path, 'CREATE TABLE plan_finished_resolutions (id INTEGER PRIMARY KEY, filename TEXT, sequence INTEGER)')
        self.unchanged_refusal(lambda: self.resolve(p), 'account_controls_invalid')
        p = self.k2(self.tmp_path / 'append_only')
        self.resolve(p)
        for statement in ('UPDATE plan_finished_resolutions SET sequence=2', 'DELETE FROM plan_finished_resolutions'):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError) as caught:
                    self.mutate(p.account_path, statement)
                self.assertIn('append_only', str(caught.exception))
        before = self.files()
        with self.assertRaises(PlanError):
            self.resolve(p)
        self.assertEqual(self.files(), before)

    def test_failed_first_write_rolls_back_every_database_including_the_new_table(self):
        import sqlite3

        p = self.k2()
        before = self.files()
        with patch('desktop_chatgpt_provider.implementation_provenance', side_effect=OSError('private')):
            with self.assertRaises(PlanError):
                self.resolve(p)
        self.assertEqual(self.files(), before)
        original = self.module._create_finished_resolution_audit

        def create_then_fail(db):
            original(db)
            raise sqlite3.OperationalError('private')

        with patch('desktop_chatgpt_provider._create_finished_resolution_audit', create_then_fail):
            with self.assertRaises(PlanError) as caught:
                self.resolve(p)
        self.assertEqual(caught.exception.code, 'account_controls_unavailable')
        self.assertEqual(self.files(), before)
        self.assertEqual(self.rows(p.account_path, "SELECT name FROM sqlite_master WHERE name='plan_finished_resolutions'"), [])

    def test_wal_journals_are_refused_without_reconfiguration(self):
        for target in ('account', 'ledger'):
            with self.subTest(target=target):
                p = self.k2(self.tmp_path / target)
                path = p.account_path if target == 'account' else p.path
                self.assertEqual(self.rows(path, 'PRAGMA journal_mode=WAL'), [('wal',)])
                self.age(p)
                self.unchanged_refusal(lambda: self.resolve(p), 'unsupported_control_journal_mode')

    def test_finish_never_persists_an_outcome_outside_the_research_allowlist(self):
        for status in ('campaign_controls_unavailable', 'unsupported_control_journal_mode', 'not_a_code'):
            with self.subTest(status=status):
                p = provider(self.tmp_path / status)
                p._reserve('a' * 64, 123)
                p._finish(1, status)
                self.assertEqual(p.read_receipts()[0]['status'], 'failed_or_interrupted')
                self.assertEqual(self.rows(p.path, 'SELECT blocked FROM plan_budget'), [('failed_or_interrupted',)])
                self.assertEqual(self.rows(p.account_path, 'SELECT state,owner FROM plan_accounts'), [('failed_or_interrupted', None)])
        for status in ('invalid_content_type', 'quota_paused'):
            with self.subTest(status=status):
                p = provider(self.tmp_path / status)
                p._reserve('a' * 64, 123)
                p._finish(1, status)
                self.assertEqual(p.read_receipts()[0]['status'], status)

    def test_k1_resolution_still_works_after_a_finished_unknown_resolution(self):
        p = self.k2()
        self.resolve(p)
        clear_account_pause(p.credential_reference, p.path.parent, user_confirmed=True)
        k1 = provider(self.tmp_path, budget_path=p.path.parent / 'k1.sqlite3', campaign_id='k1')
        k1._reserve('d' * 64, 7)
        self.age(k1)
        self.assertEqual(self.module.inspect_unknown_request(k1.credential_reference, k1.path.parent)['kind'], 'k1_resolvable')
        self.module.resolve_unknown_request(
            k1.credential_reference, k1.path.parent, user_confirmed=True, acknowledgement_version=self.module.ACKNOWLEDGEMENT_VERSION
        )
        self.assertEqual(read_account_status(k1.credential_reference, k1.path.parent), {'state': 'user_confirmed_consumed', 'pending': False})
        # An R1-only verifier finds no R1 audit for the K2 receipt, so older builds fail closed.
        self.assertIsNone(self.r1_registration(p))
