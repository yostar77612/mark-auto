"""Phase 1 search request and stream handling with scripted SSE (T2-T4, T15)."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from desktop_chatgpt_provider import PlanError
from quantlab.idea_research import new_task
from quantlab.idea_search import (
    AccountPaused,
    SearchSession,
    SearchUnavailable,
    build_search_request,
    run_search,
    select_urls,
)
from tests.idea_fixtures import FakeTransport, caller, search_call, search_response, sse

A, B, C = 'https://alpha.example.org/a', 'https://beta.example.org/b', 'https://gamma.example.org/c'


def task(**direction):
    return new_task(
        {
            'instrument': 'TMF',
            'timeframe': '1d',
            'direction': {'family_hint': 'channel_breakout', 'text': '開盤區間突破', **direction},
            'discovery': 'web_search',
            'consent': {'network': True, 'plan_usage': True},
        }
    )


class RequestTests(unittest.TestCase):
    def test_t15_request_shape_and_no_local_or_account_data(self):
        request = build_search_request('gpt-fixture', task())
        self.assertEqual((request['store'], request['stream']), (False, True))
        self.assertEqual(request['include'], ['web_search_call.action.sources'])
        (tool,) = request['tools']
        self.assertEqual(tool['type'], 'web_search')
        self.assertLessEqual(len(tool['filters']['blocked_domains']), 100)
        self.assertIn('yuanta.com.tw', tool['filters']['blocked_domains'])
        self.assertTrue(all('://' not in d for d in tool['filters']['blocked_domains']))
        self.assertEqual(tool['user_location'], {'type': 'approximate', 'country': 'TW', 'timezone': 'Asia/Taipei'})
        for unsupported in ('max_tool_calls', 'temperature', 'max_output_tokens', 'top_p', 'metadata', 'background', 'user', 'truncation'):
            self.assertNotIn(unsupported, request)
        self.assertFalse(any(t.get('type') == 'function' for t in request['tools']))
        self.assertTrue(all(message.get('role') == 'user' for message in request['input']))
        encoded = json.dumps(request, ensure_ascii=False)
        for private in (str(Path.home()), json.dumps(str(Path.home()))[1:-1], os.environ.get('USERNAME') or 'no-user', 'registration', 'dataset.json'):
            self.assertNotIn(private, encoded)
        for private in ('account', 'position', 'cash', 'paper', 'C:\\'):
            self.assertNotIn(private, request['input'][0]['content'])
        self.assertEqual(set(json.loads(request['input'][0]['content'])), {'market', 'timeframe', 'strategy_family_hint', 'direction'})


class StreamTests(unittest.TestCase):
    def run_search(self, *responses, clock=None):
        transport = FakeTransport(*responses)
        logged = []
        kwargs = {'clock': clock} if clock else {}
        session = run_search(caller(transport), build_search_request('m', task()), deadline=1e18, on_search=logged.append, **kwargs)
        return session, transport, logged

    def test_t1_search_log_comes_from_web_search_call_events(self):
        session, transport, logged = self.run_search(search_response([('台指期 通道突破 策略', [A, B]), ('channel breakout rules', [C])], [A, B, C]))
        self.assertEqual(
            [(s['search_id'], s['query'], s['sources_returned']) for s in session.log()],
            [('q1', '台指期 通道突破 策略', 2), ('q2', 'channel breakout rules', 1)],
        )
        self.assertEqual(session.sources, [A, B, C])
        self.assertIsNone(session.stop_reason)
        self.assertEqual([row['url'] for row in select_urls(session) if row['accepted']], [A, B, C])
        self.assertEqual(len(transport.requests), 1)

    def test_t2_fabricated_url_is_not_fetched(self):
        session, _, _ = self.run_search(search_response([('q', [A])], [A, 'https://invented.example.net/x', 'https://169.254.169.254/latest']))
        rows = {row['url']: row for row in select_urls(session)}
        self.assertTrue(rows[A]['accepted'])
        self.assertEqual(rows['https://invented.example.net/x']['reject_reason'], 'not_in_search_results')
        self.assertEqual(rows['https://169.254.169.254/latest']['reject_reason'], 'not_in_search_results')
        self.assertFalse(rows['https://invented.example.net/x']['accepted'])

    def test_citation_counts_as_search_result(self):
        session, _, _ = self.run_search(search_response([('q', [A])], [A, B], citations=[B]))
        rows = {row['url']: row for row in select_urls(session)}
        self.assertTrue(rows[B]['accepted'])
        self.assertEqual(rows[B]['origin'], ['url_citation'])

    def test_t3_seventh_search_stops_stream_and_keeps_first_six(self):
        searches = [('q%d' % i, ['https://site%d.example.org/p' % i]) for i in range(1, 8)]
        session, transport, logged = self.run_search(search_response(searches, []))
        self.assertEqual(session.stop_reason, 'search_limit')
        self.assertEqual(len(session.log()), 6)
        self.assertEqual(session.sources, ['https://site%d.example.org/p' % i for i in range(1, 7)])
        self.assertNotIn('https://site7.example.org/p', session.sources)
        self.assertEqual(transport.closed, 1)
        self.assertLess(transport.consumed[0], len(search_response(searches, [])))
        self.assertIsNone(session.model_urls)
        accepted = [row['url'] for row in select_urls(session) if row['accepted']]
        self.assertEqual(accepted, ['https://site%d.example.org/p' % i for i in range(1, 7)])

    def test_search_phase_time_limit_stops_stream(self):
        ticks = iter([0, 0, 1, 2, 95, 96, 97, 98, 99, 100, 101, 102])
        session, transport, _ = self.run_search(search_response([('q1', [A]), ('q2', [B])], [A, B]), clock=lambda: next(ticks))
        self.assertEqual(session.stop_reason, 'search_timeout')
        self.assertEqual(transport.closed, 1)

    def test_t4_unsupported_capability_or_tool_rejection(self):
        failures = (
            PlanError('invalid_request', http_status=400, remote_code='subscription_sharing_unsupported_capability'),
            PlanError('remote_error', http_status=400),
            sse({'type': 'error', 'code': 'unsupported_tool', 'message': 'web_search not allowed'}),
            sse({'type': 'response.failed', 'response': {'status': 'failed', 'error': {'code': 'subscription_sharing_unsupported_capability'}}}),
        )
        for failure in failures:
            with self.subTest(failure=failure), self.assertRaises(SearchUnavailable):
                self.run_search(failure)

    def test_t5_usage_limit_pauses(self):
        for failure in (
            PlanError('quota_paused', http_status=429, remote_code='subscription_sharing_usage_limit_exceeded'),
            sse({'type': 'error', 'code': 'subscription_sharing_usage_limit_exceeded'}),
        ):
            with self.subTest(failure=failure), self.assertRaises(AccountPaused):
                self.run_search(failure)

    def test_per_domain_and_page_limits(self):
        urls = ['https://alpha.example.org/%d' % i for i in range(3)] + ['https://www.s%d.example.org/' % i for i in range(9)]
        session = SearchSession()
        session.sources = list(urls)
        session.model_urls = [{'url': u, 'reason': 'r'} for u in urls]
        rows = select_urls(session)
        reasons = [row['reject_reason'] for row in rows]
        self.assertEqual(reasons[:3], [None, None, 'per_domain_limit'])
        self.assertEqual(sum(row['accepted'] for row in rows), 8)
        self.assertIn('page_limit', reasons)

    def test_open_page_actions_are_logged_without_query(self):
        events = search_call('ws_1', 'q', [A])
        events[1]['item']['action'] = {'type': 'open_page', 'url': B}
        session, _, logged = self.run_search(sse(*events, {'type': 'response.completed', 'response': {'status': 'completed', 'output': []}}))
        self.assertEqual(session.log()[0]['action'], 'open_page')
        self.assertIn(B, session.sources)


if __name__ == '__main__':
    unittest.main()


class ValidateToolTests(unittest.TestCase):
    def test_refuses_without_consent_and_sends_nothing(self):
        # Import the developer tool only in the tests that exercise it.
        import contextlib

        # Import the developer tool only in the tests that exercise it.
        import io

        # Import the developer tool only in the tests that exercise it.
        from tools import validate_web_search as tool

        out = io.StringIO()
        with patch.object(tool, 'run', side_effect=AssertionError('must not run')), contextlib.redirect_stdout(out):
            self.assertEqual(tool.main(['--model', 'gpt-fixture']), 2)
        self.assertEqual(json.loads(out.getvalue())['sent_requests'], 0)

    def test_summary_has_counts_only(self):
        # Import the developer tool only in the tests that exercise it.
        from tools import validate_web_search as tool

        secret_query = 'very private query text'
        transport = FakeTransport(search_response([(secret_query, [A, B])], [A], citations=[A]))
        result = tool.run('gpt-fixture', transport=transport, reference=object())
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual((result['status'], result['searches'], result['sources'], result['citations']), ('ok', 1, 2, 1))
        self.assertEqual(result['parameters_accepted']['include.web_search_call.action.sources'], 'yes')
        encoded = json.dumps(result)
        for secret in (secret_query, A, 'Bearer', 'token', 'registration'):
            self.assertNotIn(secret, encoded)
        transport = FakeTransport(PlanError('invalid_request', http_status=400, remote_code='subscription_sharing_unsupported_capability'))
        result = tool.run('gpt-fixture', transport=transport, reference=object())
        self.assertEqual((result['status'], result['error_code'], result['http_status']), ('error', 'subscription_sharing_unsupported_capability', 400))
        self.assertEqual(result['parameters_accepted']['filters.blocked_domains'], 'no_or_unknown')
