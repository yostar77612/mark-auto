"""Terminal-omitted completed items exercise the real offline plan path."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_chatgpt_provider import PlanError
from tests.test_chatgpt_plan import CANDIDATE, MockTransport, frame, provider
from tests.test_response_output import events


class CompletedPlanOutputTests(unittest.TestCase):
    def generate(self, value):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch('desktop_chatgpt_provider.implementation_provenance', return_value={'offline_fixture': True}),
                patch('desktop_chatgpt_provider.PlanHTTPTransport', MockTransport),
                patch.object(MockTransport, 'events', [frame(event) for event in value]),
                patch('http.client.HTTPSConnection', side_effect=AssertionError('No live HTTP')),
            ):
                return provider(Path(temporary)).generate({'family': 'trend'})

    def test_completed_item_is_validated_by_the_original_candidate_contract(self):
        value = events()
        value[1]['item']['content'][0]['text'] = json.dumps(CANDIDATE)
        self.assertEqual(self.generate(value), CANDIDATE)

    def test_unsafe_completed_items_still_fail_closed(self):
        for change in ('delta', 'identity', 'gap', 'duplicate', 'incomplete', 'tool', 'role', 'risk'):
            value = events()
            value[1]['item']['content'][0]['text'] = json.dumps(CANDIDATE)
            if change == 'delta':
                value[1] = {'type': 'response.output_text.delta', 'delta': json.dumps(CANDIDATE)}
            elif change == 'identity':
                value[-1]['response']['id'] = 'resp_other'
            elif change == 'gap':
                value[1]['output_index'] = 1
            elif change == 'duplicate':
                value.insert(2, copy.deepcopy(value[1]))
            elif change == 'incomplete':
                value[1]['item']['status'] = 'in_progress'
            elif change == 'tool':
                value[1]['item']['type'] = 'function_call'
            elif change == 'role':
                value[1]['item']['role'] = 'user'
            else:
                candidate = copy.deepcopy(CANDIDATE)
                candidate['parameters']['quantity'] = 1
                value[1]['item']['content'][0]['text'] = json.dumps(candidate)
            with self.subTest(change=change), self.assertRaises(PlanError):
                self.generate(value)
