"""Offline validator tests only. These mocks never establish real-model acceptance."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from quantlab.core import ValidationError, content_hash
from quantlab.provider import HTTPTransport
from tools.validate_real_ai import recording_proxy, summarize_evidence, verify_artifacts, FrozenResponseReplay, replay_and_compare, improvement_evidence


class RealAIValidatorTests(unittest.TestCase):
    def improvement_fixture(self, duplicate=False):
        first = {'attempt_id': 'a', 'parent_id': None, 'iteration': 0, 'family': 'trend',
                 'status': 'evaluated', 'output': {'unit-test': 'not a real model'},
                 'candidate_fingerprint': 'first',
                 'metrics': {'train': {'metrics': {'net_pnl': '10'}},
                             'validation': {'metrics': {'net_pnl': '10'}}}}
        second = {'attempt_id': 'b', 'parent_id': 'a', 'iteration': 1, 'family': 'trend',
                  'status': 'rejected' if duplicate else 'evaluated', 'output': {},
                  'candidate_fingerprint': 'first' if duplicate else 'second',
                  'metrics': {} if duplicate else {'validation': {'metrics': {'net_pnl': '5'}}}}
        if duplicate:
            second['duplicate_of'] = 'a'
        previous = {'output': first['output'], 'status': 'evaluated',
                    'metrics': {k: v['metrics'] for k, v in first['metrics'].items()}}
        request = {'messages': [{'role': 'user', 'content': json.dumps({
            'previous': previous, 'task': 'improve_previous_candidate',
            'improvement_instruction': 'unit-test instruction'})}]}
        return {'attempts': [first, second]}, [{'request': {}}, {'request': request}]

    def test_improvement_protocol_pass_does_not_claim_better_performance(self):
        state, records = self.improvement_fixture()
        result = improvement_evidence(state, records)
        self.assertTrue(result['loop_protocol_pass'])
        self.assertTrue(result['distinct_candidate_accepted'])
        self.assertFalse(result['validation_pnl_improved'])
        self.assertFalse(result['market_performance_acceptance'])

    def test_improvement_duplicate_is_reported_as_rejected_not_successful_proposal(self):
        state, records = self.improvement_fixture(duplicate=True)
        result = improvement_evidence(state, records)
        self.assertTrue(result['loop_protocol_pass'])
        self.assertEqual(result['second_outcome'], 'duplicate_rejected')
        self.assertFalse(result['distinct_candidate_accepted'])
        self.assertIsNone(result['validation_pnl_improved'])

    def test_improvement_requires_actual_transported_feedback_and_parent_chain(self):
        state, records = self.improvement_fixture()
        records[1]['request']['messages'][0]['content'] = '{}'
        self.assertFalse(improvement_evidence(state, records)['loop_protocol_pass'])
        state, records = self.improvement_fixture()
        state['attempts'][1]['parent_id'] = 'wrong-parent'
        self.assertFalse(improvement_evidence(state, records)['loop_protocol_pass'])
        self.assertFalse(improvement_evidence(state, records[:1])['loop_protocol_pass'])

    def test_frozen_replay_is_labeled_and_never_repairs_or_improves(self):
        # Inert unit-test candidate, not actual model acceptance.
        payload = {'strategy_id': 'unit_fixture', 'family': 'trend',
                   'parameters': {'fast': 3, 'slow': 8}, 'rules': {}}
        record = {'response': {'choices': [{'message': {'content': json.dumps(payload)}}]}}
        replay = FrozenResponseReplay(record, 'unit-test-mock')
        self.assertEqual(replay.mode, 'frozen_model_output_replay')
        self.assertEqual(replay.generate({'family': 'trend', 'iteration': 0}), payload)
        changed = replay.generate({'family': 'trend', 'iteration': 0})
        changed['parameters']['fast'] = 7
        self.assertEqual(replay.generate({'family': 'trend', 'iteration': 0}), payload)
        with self.assertRaises(ValidationError):
            replay.generate({'family': 'momentum', 'iteration': 0})
        with self.assertRaises(ValidationError):
            replay.improve({'family': 'trend', 'iteration': 1})
        record['response']['choices'][0]['message']['content'] = '{"code":"malicious"}'
        with self.assertRaises(ValidationError):
            FrozenResponseReplay(record, 'unit-test-mock')

    def test_replay_predeclares_all_baselines_before_evaluation(self):
        # This mock tests replay bookkeeping only, never real model acceptance.
        payload = {'strategy_id': 'unit_fixture', 'family': 'trend',
                   'parameters': {'fast': 3, 'slow': 8}, 'rules': {}}
        record = {'response': {'choices': [{'message': {'content': json.dumps(payload)}}]}}
        state = {'attempts': [], 'provider_receipts': [], 'selected': [],
                 'evaluations': {'oos': [], 'holdout': []},
                 'status': 'completed', 'real_model_status': 'not_verified'}
        with tempfile.TemporaryDirectory() as tmp, patch('tools.validate_real_ai.run_campaign', return_value=state):
            with self.assertRaisesRegex(ValidationError, 'did not complete'):
                replay_and_compare(None, {}, record, {'model_id': 'unit-test-mock'}, Path(tmp))
            declared = json.loads((Path(tmp)/'replay-predeclared.json').read_text())
            self.assertEqual(len(declared['baselines']), 5)
            self.assertEqual(declared['new_model_calls'], 0)
            self.assertEqual(declared['model_candidate']['parameters'], payload['parameters'])
            self.assertFalse(declared['multi_ai_candidate_acceptance'])

    def test_rejects_unpinned_model_before_starting_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'model'
            model.write_bytes(b'NOT A REAL MODEL: inert unit-test fixture')
            with self.assertRaisesRegex(ValidationError, 'Model differs'):
                verify_artifacts(model, Path(tmp) / 'absent-server', Path(tmp) / 'absent-archive')

    def test_empty_results_do_not_pass_by_vacuous_truth(self):
        state = {'attempts': [], 'provider_receipts': [], 'selected': [],
                 'evaluations': {'oos': [], 'holdout': []},
                 'status': 'completed', 'real_model_status': 'not_verified'}
        result = summarize_evidence(state, [])
        self.assertFalse(result['multi_strategy_comparison_completed'])
        self.assertFalse(result['train_validation_oos_holdout_completed'])
        self.assertFalse(result['http_receipts_match_recorded_responses'])
        self.assertFalse(result['investment_acceptance'])
        self.assertNotIn('artifact_verified_local_model_process', result)

    def test_recorder_transparently_forwards_mock_bytes_without_fallback(self):
        """A mock server checks recorder behavior only, not AI inference."""
        incoming = []
        response_bytes = b'{"choices":[{"message":{"content":"deliberately invalid DSL"}}],"usage":{"total_tokens":1}}'
        class MockServer(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                incoming.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.send_header('Content-Length', str(len(response_bytes)))
                self.end_headers()
                self.wfile.write(response_bytes)
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), MockServer)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with recording_proxy(upstream.server_port, tmp) as (endpoint, records):
                    request = {'model': 'UNIT-TEST-MOCK-NOT-A-REAL-MODEL', 'messages': []}
                    response = HTTPTransport(allow_network=True)(endpoint, request, 10)
                self.assertEqual(json.loads(incoming[0]), request)
                self.assertEqual(response, json.loads(response_bytes))
                self.assertEqual(records[0]['request'], request)
                self.assertEqual(records[0]['response'], response)
                self.assertTrue((Path(tmp) / 'http-01.json').exists())
                self.assertEqual(response['choices'][0]['message']['content'], 'deliberately invalid DSL')
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)

    def test_receipt_mismatch_is_not_verified(self):
        state = {'attempts': [], 'provider_receipts': [{'response_hash': 'not-the-recorded-hash'}],
                 'selected': [], 'evaluations': {'oos': [], 'holdout': []},
                 'status': 'completed', 'real_model_status': 'not_verified'}
        result = summarize_evidence(state, [{'response': {'mock': True}, 'elapsed_seconds': 0}])
        self.assertFalse(result['http_receipts_match_recorded_responses'])
        self.assertEqual(result['campaign_real_model_status'], 'not_verified')


if __name__ == '__main__':
    unittest.main()
