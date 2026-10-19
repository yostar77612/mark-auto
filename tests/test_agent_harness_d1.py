"""Offline contract, default-deny and non-leak oracles for TASK A1-D1."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from quantlab import agent_tool_contract as contract
from quantlab import agent_tools
from quantlab.errors import ERROR_TABLE
from tests.test_repo_layout import AGENT_TOOL_SCHEMA


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = agent_tools.PRODUCTION_REGISTRY
NAME = 'research.list_training_status'
GRANTS = ('research.read',)
REFUSAL = {'ok': False, 'error': {'code': 'agent_tool_refused', 'params': {}}}
SECRETS = (
    987654.321,
    31337,
    'OOS_SENTINEL',
    'HOLDOUT_SENTINEL',
    'C:\\Users\\SECRET_USERNAME\\secret.csv',
    '/home/SECRET_USERNAME/secret.csv',
    '\\\\private-server\\SECRET_USERNAME',
    'SECRET_USERNAME',
    'CREDENTIAL_SENTINEL',
    'TOKEN_SENTINEL',
    'USER_RAW_FILE_SENTINEL',
    'CONSUMED_GUARD_SENTINEL',
)


def sentinel_context():
    raw = {
        'completed': True,
        'observations': 31337,
        'prices': [987654.321],
        'returns': [987654.321],
        'metrics': {'profit': 987654.321, 'rows': 31337},
        'trades': [{'marker': 'OOS_SENTINEL'}],
        'equity': [987654.321],
        'consumed_guard': 'CONSUMED_GUARD_SENTINEL',
        'raw_file': 'USER_RAW_FILE_SENTINEL',
        'credential': 'CREDENTIAL_SENTINEL',
        'token': 'TOKEN_SENTINEL',
        'absolute_paths': list(SECRETS[4:8]),
    }
    return [
        {'partition': 'training', **raw, 'completed': False, 'observations': 12},
        {'partition': 'oos', **raw},
        {'partition': 'final_holdout', **raw, 'marker': 'HOLDOUT_SENTINEL'},
        {'partition': 'unknown', **raw},
        {**raw},
        {'partition': 'training', **raw, 'observations': 24},
    ]


def assert_no_protected_values(case, value):
    """Walk keys and every scalar in the entire envelope, not just items."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert_no_protected_values(case, key)
            assert_no_protected_values(case, item)
    elif isinstance(value, list):
        for item in value:
            assert_no_protected_values(case, item)
    else:
        for secret in SECRETS:
            case.assertNotEqual(value, secret)
            if isinstance(value, str):
                case.assertNotIn(str(secret), value)
        if isinstance(value, str):
            case.assertNotRegex(value, r'(?i)(?:[a-z]:[\\/]|^/|^\\\\|users[\\/])')


def declaration(**overrides):
    result = deepcopy(REGISTRY.declarations[NAME])
    result.update(overrides)
    return result


class AgentHarnessD1Tests(unittest.TestCase):
    def test_schema_json_exactly_matches_runtime_and_enums_both_directions(self):
        schema = json.loads((ROOT / AGENT_TOOL_SCHEMA).read_text(encoding='utf-8'))
        self.assertEqual(schema, contract.DOCUMENT_SCHEMA)
        self.assertEqual(set(schema['properties']['capability']['enum']), contract.CAPABILITIES)
        self.assertEqual(contract.CAPABILITIES, {'research.read', 'paper.read', 'ui.navigate', 'research.run'})
        self.assertEqual(set(schema['properties']['effect']['enum']), contract.EFFECTS)
        self.assertEqual(contract.EFFECTS, {'read', 'mutation'})
        self.assertIs(schema['additionalProperties'], False)
        self.assertTrue(contract.validate(declaration(), schema))
        self.assertFalse(contract.validate(declaration(unknown='rejected'), schema))
        envelope = schema['$defs']['boundedReturn']
        self.assertEqual(set(envelope['required']), {'ok', 'items', 'truncated', 'limit', 'next_cursor'})
        self.assertEqual(set(envelope['properties']), set(envelope['required']))
        self.assertIs(envelope['additionalProperties'], False)
        self.assertEqual(envelope['properties']['items']['maxItems'], contract.MAX_LIMIT)

    def test_invalid_registration_leaves_registry_unchanged(self):
        missing_effect = declaration()
        del missing_effect['effect']
        cases = [missing_effect, declaration(effect='execute'), declaration(capability='trade.execute'), declaration(extra=True)]
        missing_required_property = declaration()
        missing_required_property['inputSchema']['required'] = ['absent']
        cases.append(missing_required_property)
        for value in cases:
            with self.subTest(declaration=value):
                registry = agent_tools.Registry()
                handler = Mock()
                before = dict(registry.declarations)
                self.assertEqual(registry.register(value, handler), REFUSAL)
                self.assertEqual(dict(registry.declarations), before)
                handler.assert_not_called()

    def test_test_only_mutation_requires_nonempty_idempotency_key_but_never_executes(self):
        registry = agent_tools.Registry()
        handler = Mock()
        fake = declaration(name='research.test_only', effect='mutation', capability='research.run')
        self.assertEqual(registry.register(fake, handler), REFUSAL)
        self.assertEqual(dict(registry.declarations), {})
        fake['inputSchema']['properties']['idempotency_key'] = {'type': 'string', 'minLength': 1, 'maxLength': 128}
        self.assertEqual(registry.register(fake, handler), REFUSAL)
        fake['inputSchema']['required'].append('idempotency_key')
        self.assertTrue(contract.validate(fake, contract.TOOL_SCHEMA))
        self.assertEqual(registry.register(fake, handler), {'ok': True})
        self.assertEqual(registry.call(fake['name'], '{"idempotency_key":"abc"}', capabilities=contract.CAPABILITIES), REFUSAL)
        handler.assert_not_called()
        for rule in ({'type': 'integer'}, {'type': 'string'}, {'type': 'string', 'minLength': 0}):
            invalid = deepcopy(fake)
            invalid['inputSchema']['properties']['idempotency_key'] = rule
            self.assertEqual(agent_tools.Registry().register(invalid, handler), REFUSAL)
        self.assertNotIn(fake['name'], REGISTRY.declarations)

    def test_default_deny_resolve_and_call_never_execute(self):
        registry = agent_tools.Registry()
        handler = Mock()
        self.assertEqual(registry.register(declaration(), handler), {'ok': True})
        for name, grants in ((NAME, ()), ('unknown', GRANTS), (NAME, ('unknown',)), (NAME, (*GRANTS, 'unknown')), ([], GRANTS)):
            self.assertEqual(registry.resolve(name, grants), REFUSAL)
            self.assertEqual(registry.call(name, '{}', capabilities=grants), REFUSAL)
        for capability in ('ui.navigate', 'research.run'):
            value = declaration(name=capability + '_fake', capability=capability)
            self.assertEqual(registry.register(value, handler), {'ok': True})
            self.assertEqual(registry.resolve(value['name'], [capability]), REFUSAL)
            self.assertEqual(registry.call(value['name'], '{}', capabilities=[capability]), REFUSAL)
        handler.assert_not_called()
        self.assertIn(REFUSAL['error']['code'], ERROR_TABLE)

    def test_production_read_only_frozen_registry_and_copied_declarations(self):
        self.assertTrue(REGISTRY.declarations)
        self.assertEqual(sum(tool['effect'] == 'mutation' for tool in REGISTRY.declarations.values()), 0)
        for name, tool in REGISTRY.declarations.items():
            self.assertEqual(tool['effect'], 'read')
            self.assertNotIn(tool['capability'], ('ui.navigate', 'research.run'))
            self.assertFalse(any(fragment in name for fragment in ('trade', 'order', 'amend', 'cancel', 'place')))
        before = dict(REGISTRY.declarations)
        self.assertEqual(REGISTRY.register(declaration(name='new'), Mock()), REFUSAL)
        copied = REGISTRY.declarations[NAME]
        copied['effect'] = 'mutation'
        self.assertEqual(dict(REGISTRY.declarations), before)
        resolved = REGISTRY.resolve(NAME, GRANTS)
        self.assertEqual(set(resolved), {'ok', 'tool'})
        resolved['tool']['inputSchema']['properties'].clear()
        self.assertEqual(dict(REGISTRY.declarations), before)

    def test_every_registered_read_tool_and_all_pages_are_sentinel_safe(self):
        dirty = sentinel_context()
        clean = [{'partition': 'training', 'completed': False, 'observations': 12}, {'partition': 'training', 'completed': True, 'observations': 24}]
        for name, tool in REGISTRY.declarations.items():
            if tool['effect'] != 'read':
                continue
            with self.subTest(tool=name):
                cursor = 0
                for _page in range(4):
                    args = json.dumps({'limit': 1, 'cursor': cursor})
                    output = REGISTRY.call(name, args, capabilities=[tool['capability']], context=dirty)
                    assert_no_protected_values(self, output)
                    self.assertTrue(output['ok'])
                    self.assertEqual(output, REGISTRY.call(name, args, capabilities=[tool['capability']], context=clean))
                    if not output['truncated']:
                        self.assertIsNone(output['next_cursor'])
                        break
                    self.assertGreater(output['next_cursor'], cursor)
                    cursor = output['next_cursor']
                else:
                    self.fail('pagination did not exhaust the visible fixture')
                for context in ([], dirty[1:5]):
                    output = REGISTRY.call(name, '{}', capabilities=[tool['capability']], context=context)
                    assert_no_protected_values(self, output)
                    self.assertEqual(output['items'], [])
                    self.assertFalse(output['truncated'])
                    self.assertIsNone(output['next_cursor'])

    def test_sentinel_oracle_fails_when_partition_filter_is_removed(self):
        # Mutation negative control: production handler + real registry + same
        # recursive oracle; only partition filtering is removed temporarily.
        with patch('quantlab.agent_tools._training_records', side_effect=lambda context: list(context)):
            output = REGISTRY.call(NAME, '{}', capabilities=GRANTS, context=sentinel_context())
            self.assertTrue(output['ok'])
            self.assertIn(31337, [item['observations'] for item in output['items']])
            with self.assertRaises(AssertionError):
                assert_no_protected_values(self, output)

    def test_bounded_envelope_default_maximum_and_exact_boundary(self):
        context = [{'partition': 'training', 'completed': True, 'observations': number} for number in range(51)]
        first = REGISTRY.call(NAME, '{}', capabilities=GRANTS, context=context)
        self.assertEqual((len(first['items']), first['limit'], first['truncated'], first['next_cursor']), (50, 50, True, 50))
        last = REGISTRY.call(NAME, '{"cursor":50}', capabilities=GRANTS, context=context)
        self.assertEqual((len(last['items']), last['truncated'], last['next_cursor']), (1, False, None))
        exact = REGISTRY.call(NAME, '{}', capabilities=GRANTS, context=context[:50])
        self.assertEqual((len(exact['items']), exact['truncated'], exact['next_cursor']), (50, False, None))
        self.assertLessEqual(len(json.dumps(first).encode()), contract.MAX_RETURN_BYTES)
        self.assertEqual(REGISTRY.call(NAME, '{"cursor":52}', capabilities=GRANTS, context=context), REFUSAL)

    def test_model_output_only_strict_bounded_json_and_schema_no_handler_call(self):
        registry = agent_tools.Registry()
        handler = Mock()
        registry.register(declaration(), handler)
        for raw in (
            '[]',
            'null',
            '{} trailing',
            '```json\n{}\n```',
            '{"limit":1,"limit":2}',
            '{"limit":NaN}',
            '{"cursor":Infinity}',
            '{"limit":true}',
            '{"limit":1.0}',
            '{"limit":"1"}',
            '{"limit":0}',
            '{"limit":51}',
            '{"cursor":-1}',
            '{"path":"/home/SECRET_USERNAME"}',
            '{"code":"__import__(42)"}',
            '{"x":{"a":1,"a":2}}',
            ' ' * 4097,
            '\ud800',
        ):
            with self.subTest(raw=ascii(raw)):
                self.assertEqual(registry.call(NAME, raw, capabilities=GRANTS), REFUSAL)
        handler.assert_not_called()

    def test_invalid_return_and_exception_do_not_echo_raw_content(self):
        registry = agent_tools.Registry()
        handler = Mock()
        registry.register(declaration(), handler)
        good = REGISTRY.call(NAME, '{}', capabilities=GRANTS)
        invalids = [
            sentinel_context()[0],
            {**good, 'raw': 'USER_RAW_FILE_SENTINEL'},
            {**good, 'items': [{'completed': True, 'observations': 'TOKEN_SENTINEL'}]},
        ]
        invalids.extend(({**good, 'truncated': True}, {**good, 'next_cursor': 31337}, {**good, 'limit': 1}))
        for invalid in invalids:
            handler.return_value = invalid
            output = registry.call(NAME, '{}', capabilities=GRANTS)
            self.assertEqual(output, REFUSAL)
            assert_no_protected_values(self, output)
        handler.side_effect = ValueError('TOKEN_SENTINEL C:\\Users\\SECRET_USERNAME')
        self.assertEqual(registry.call(NAME, '{}', capabilities=GRANTS), REFUSAL)
        with patch('quantlab.agent_tools.MAX_RETURN_BYTES', 1):
            self.assertEqual(REGISTRY.call(NAME, '{}', capabilities=GRANTS), REFUSAL)

    def test_new_core_modules_have_no_dynamic_execution_or_ui_imports(self):
        prohibited = {'eval', 'exec', 'compile', '__import__', 'pickle', 'subprocess'}
        for name in ('agent_tools.py', 'agent_tool_contract.py'):
            tree = ast.parse((ROOT / 'quantlab' / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, prohibited)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, prohibited)
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or '']
                else:
                    imports = []
                for module in imports:
                    self.assertFalse(prohibited.intersection(module.split('.')))
                    self.assertFalse(any(part.startswith(('desktop', 'PySide6', 'Qt')) for part in module.split('.')))


if __name__ == '__main__':
    unittest.main()
