"""Reproduce terminal-omitted output without account calls or remote content."""

import copy
import unittest

from quantlab.idea_research import run_extraction
from quantlab.idea_search import RemoteFailure


def events():
    return [
        {'type': 'response.created', 'response': {'id': 'resp_fixture'}},
        {
            'type': 'response.output_item.done',
            'output_index': 0,
            'item': {
                'id': 'msg_fixture',
                'type': 'message',
                'role': 'assistant',
                'status': 'completed',
                'content': [{'type': 'output_text', 'text': '{"candidates":[]}'}],
            },
        },
        {'type': 'response.completed', 'response': {'id': 'resp_fixture', 'status': 'completed', 'output': []}},
    ]


def extract(value):
    return run_extraction(lambda *args: iter(value), {}, deadline=100)


class CompletedOutputTests(unittest.TestCase):
    def test_completed_items_supply_terminal_omitted_output(self):
        self.assertEqual(extract(events()), {'candidates': []})

    def test_delta_only_never_supplies_output(self):
        value = events()
        value[1] = {'type': 'response.output_text.delta', 'delta': '{"candidates":[]}'}
        with self.assertRaises(RemoteFailure):
            extract(value)

    def test_identity_gaps_duplicates_incomplete_and_tools_fail_closed(self):
        for field, replacement in (
            ('id', None),
            ('status', 'in_progress'),
            ('type', 'function_call'),
            ('role', 'user'),
        ):
            value = events()
            value[1]['item'][field] = replacement
            with self.subTest(field=field), self.assertRaises(RemoteFailure):
                extract(value)
        for change in ('response_id', 'index_gap', 'duplicate', 'incomplete', 'terminal_conflict'):
            value = events()
            if change == 'response_id':
                value[-1]['response']['id'] = 'resp_other'
            elif change == 'index_gap':
                value[1]['output_index'] = 1
            elif change == 'duplicate':
                value.insert(2, copy.deepcopy(value[1]))
            elif change == 'incomplete':
                value[-1]['response']['status'] = 'incomplete'
            else:
                value[-1]['response']['output'] = [{'type': 'function_call'}]
            with self.subTest(change=change), self.assertRaises(RemoteFailure):
                extract(value)

    def test_no_terminal_never_accepts_done_item(self):
        with self.assertRaises(RemoteFailure):
            extract(events()[:-1])
