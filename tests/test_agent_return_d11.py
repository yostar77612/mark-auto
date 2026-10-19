"""Deterministic D11 boundaries, registry routing and whole-envelope leak oracles."""

import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch

from quantlab import agent_read_tools, agent_tools
from quantlab.agent_return import MAX_FIELD_CHARS, bounded_return
from quantlab.agent_tool_contract import MAX_LIMIT, MAX_RETURN_BYTES
from quantlab.errors import ERROR_TABLE
from tests.test_agent_harness_d1 import GRANTS, NAME, REFUSAL, assert_no_protected_values, sentinel_context


ROOT = Path(__file__).resolve().parents[1]


class AgentReturnD11Tests(unittest.TestCase):
    def test_item_boundaries_and_no_silent_truncation_property(self):
        for limit in (1, 7, MAX_LIMIT):
            for size in sorted({*range(151), limit - 1, limit, limit + 1}):
                rows = [{'value': index} for index in range(size)]
                page = bounded_return(rows, limit=limit)
                self.assertEqual(page['items'], rows[:limit])
                self.assertEqual(page['count'], min(size, limit))
                self.assertEqual(page['total'], size)
                self.assertEqual(page['truncated'], size > limit)
                self.assertEqual(page['reason'], 'item_limit' if size > limit else None)
                self.assertEqual(page['next_cursor'] is not None, size > limit)
                if len(page['items']) < len(rows):
                    self.assertTrue(page['truncated'])
                if not page['truncated']:
                    self.assertEqual(page['items'], rows)

    def test_cjk_byte_cap_preserves_whole_items_and_round_trips(self):
        rows = [{'index': i, 'text': '\u6f22\u5b57' * 100} for i in range(53)]
        original = deepcopy(rows)
        cursor, output = None, []
        for _ in range(len(rows)):
            page = bounded_return(rows, cursor=cursor)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode('utf-8')), MAX_RETURN_BYTES)
            self.assertLessEqual(len(json.dumps(page).encode('utf-8')), MAX_RETURN_BYTES)
            self.assertEqual(page['items'], rows[len(output) : len(output) + page['count']])
            output.extend(page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                break
            self.assertTrue(page['truncated'])
            self.assertEqual(page['reason'], 'byte_limit')
            self.assertGreater(page['count'], 0)
            self.assertLess(page['count'], MAX_LIMIT)
        else:
            self.fail('cursor failed to progress')
        self.assertEqual(output, rows)
        self.assertEqual(rows, original)

    def test_field_caps_explicit_markers_and_unchanged_input(self):
        rows = [{'nested': [{'text': '\u6f22' * (MAX_FIELD_CHARS + 1)}], 'short': 'safe'}]
        before = deepcopy(rows)
        page = bounded_return(rows)
        self.assertEqual(page['items'][0]['nested'][0]['text'], '\u6f22' * MAX_FIELD_CHARS)
        self.assertEqual(page['field_truncations'], [{'item': 0, 'field': ['nested', 0, 'text'], 'truncated': True}])
        self.assertTrue(page['truncated'])
        self.assertEqual(page['reason'], 'field_limit')
        self.assertIsNone(page['next_cursor'])
        self.assertEqual(rows, before)
        self.assertFalse(bounded_return([{'text': 'a' * MAX_FIELD_CHARS}])['truncated'])

    def test_cursors_refuse_tampering_staleness_and_cross_tool_scope(self):
        rows = [{'index': i} for i in range(12)]
        cursor = bounded_return(rows, limit=3, scope='tool-a')['next_cursor']
        for bad in (0, True, 3, '', cursor + '0', '4:' + cursor.split(':')[1], cursor.replace(':', ':0', 1)):
            with self.subTest(cursor=bad), self.assertRaises(ValueError):
                bounded_return(rows, cursor=bad, scope='tool-a')
        for changed, scope in ((rows + [{}], 'tool-a'), (rows, 'tool-b'), ([{'index': -1}, *rows[1:]], 'tool-a')):
            with self.assertRaises(ValueError):
                bounded_return(changed, cursor=cursor, scope=scope)
        registry = agent_tools.PRODUCTION_REGISTRY
        context = [{'partition': 'training', 'completed': True, 'observations': i} for i in range(4)]
        first = registry.call(NAME, '{"limit":1}', capabilities=GRANTS, context=context)
        for bad, source in ((first['next_cursor'] + '0', context), (first['next_cursor'], context[:-1])):
            output = registry.call(NAME, json.dumps({'cursor': bad}), capabilities=GRANTS, context=source)
            self.assertEqual(output, REFUSAL)
            self.assertIn(output['error']['code'], ERROR_TABLE)

    def test_strict_limits_json_types_and_determinism(self):
        for limit in (0, -1, True, False, 1.0, '1', None, float('nan'), MAX_LIMIT + 1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                bounded_return([], limit=limit)
        for value in (float('nan'), float('inf'), -float('inf'), b'bytes', Path('file'), (1,), {1: 'bad'}, '\ud800'):
            with self.subTest(value=repr(value)), self.assertRaises((ValueError, UnicodeError)):
                bounded_return([{'value': value}])
        rows = [{'index': i, 'text': '\u6f22\u5b57'} for i in range(51)]
        self.assertEqual(json.dumps(bounded_return(rows)), json.dumps(bounded_return(deepcopy(rows))))
        # One indivisible row cannot fit: refuse, never return an empty looping page.
        with self.assertRaises(ValueError):
            bounded_return([{'values': ['x' * MAX_FIELD_CHARS] * 100}])

    def test_all_registered_handlers_use_the_single_helper(self):
        registries = (agent_tools.PRODUCTION_REGISTRY, agent_read_tools.READ_REGISTRY)
        for registry in registries:
            for name, declaration in registry.declarations.items():
                self.assertEqual(declaration['effect'], 'read')
                self.assertFalse(any(word in name for word in ('amend', 'cancel', 'place')))
                handler = registry._entries[name].handler
                tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
                returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
                self.assertTrue(returns)
                for node in returns:
                    self.assertIsInstance(node.value, ast.Call)
                    self.assertEqual(node.value.func.id, 'bounded_return')
                module = agent_tools if name == NAME else agent_read_tools
                args = '{}' if name == NAME else json.dumps({'result_id': 'a' * 64, **({'other_id': 'b' * 64} if name == 'compare_results' else {})})
                if name in ('list_saved_results', 'get_paper_positions', 'get_paper_orders'):
                    args = '{}'
                with patch.object(module, 'bounded_return', wraps=bounded_return) as helper, patch.object(agent_read_tools, '_read', return_value=[]):
                    output = registry.call(name, args, capabilities=('research.read', 'paper.read'), context=sentinel_context())
                    self.assertTrue(output['ok'], output)
                    helper.assert_called_once()
                    assert_no_protected_values(self, output)
        self.assertEqual(sum(d['effect'] == 'mutation' for r in registries for d in r.declarations.values()), 0)

    def test_d3_byte_truncation_end_to_end(self):
        number = '9' * 29 + '.' + '1' * 60
        rows = [dict(index=i, quantity=number, entry_price=number, exit_price=number, net_pnl=number) for i in range(51)]
        with patch.object(agent_read_tools, '_read', return_value=rows):
            output = agent_read_tools.READ_REGISTRY.call('get_backtest_trades', json.dumps({'result_id': 'a' * 64}), capabilities=GRANTS)
        self.assertTrue(output['ok'], output)
        self.assertTrue(output['truncated'])
        self.assertEqual(output['reason'], 'byte_limit')
        self.assertLess(output['count'], MAX_LIMIT)
        self.assertEqual(output['total'], len(rows))
        self.assertIsNotNone(output['next_cursor'])

    def test_oos_total_count_negative_control(self):
        # All observations are safe: only the envelope total can leak 31337.
        context = [{'partition': 'training', 'completed': True, 'observations': 7}]
        context += [{'partition': 'oos', 'completed': True, 'observations': 7}] * 31336
        output = agent_tools.PRODUCTION_REGISTRY.call(NAME, '{}', capabilities=GRANTS, context=context)
        self.assertEqual((output['total'], output['count']), (1, 1))
        assert_no_protected_values(self, output)
        with patch.object(agent_tools, '_training_records', side_effect=list):
            leaked = agent_tools.PRODUCTION_REGISTRY.call(NAME, '{}', capabilities=GRANTS, context=context)
            self.assertTrue(leaked['ok'])
            self.assertEqual(leaked['total'], 31337)
            with self.assertRaises(AssertionError):
                assert_no_protected_values(self, leaked)

    def test_pure_module_has_no_io_dynamic_execution_or_ui(self):
        tree = ast.parse((ROOT / 'quantlab/agent_return.py').read_text(encoding='utf-8'))
        prohibited = {'eval', 'exec', 'compile', '__import__', 'pickle', 'subprocess', 'open', 'read_text', 'write_text', 'time', 'random', 'os', 'socket'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, prohibited)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, prohibited)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
                for name in names:
                    self.assertFalse(prohibited.intersection(name.split('.')))
                    self.assertFalse(any(part.startswith(('desktop', 'PySide6', 'Qt')) for part in name.split('.')))


if __name__ == '__main__':
    unittest.main()
