"""Cheap offline D3 storage, paging, provenance and non-leak regressions."""

import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from quantlab import agent_read_tools as tools
from quantlab.agent_tool_contract import MAX_LIMIT, MAX_RETURN_BYTES
from quantlab.backtest import run_backtest
from quantlab.core import content_hash, to_dict
from quantlab.reporting import demo_config, synthetic_dataset, write_json
from quantlab.strategies import builtin_strategies
from tests.test_agent_harness_d1 import REFUSAL, assert_no_protected_values
from tests import test_paper as paper_fixture


ROOT = Path(__file__).resolve().parents[1]


def bind(payload):
    payload = deepcopy(payload)
    manifest = payload['manifest']
    manifest.pop('run_hash', None)
    manifest.pop('reproducibility_hash', None)
    digest = content_hash(payload)
    manifest.update(run_hash=digest, reproducibility_hash=digest)
    return payload


class AgentReadToolsD3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dataset = synthetic_dataset()
        cls.base = to_dict(run_backtest(dataset, builtin_strategies()[0], demo_config()))

    def setUp(self):
        # mkdir's inherited ACL works in the Windows sandbox; tempfile's 0700
        # private ACL excludes the restricted test token on Python 3.14.
        self.root = ROOT / ('.tmp-d3-' + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        payload = deepcopy(self.base)
        # A result bigger than the page cap, with stable distinguishable rows.
        payload['ledger'] = [{**payload['ledger'][0], 'net_pnl': str(i)} for i in range(123)]
        payload['equity'] = [{**payload['equity'][0], 'equity': str(100000 + i)} for i in range(123)]
        self.payload = bind(payload)
        self.identity = self.save(self.payload)
        other = deepcopy(self.payload)
        other['metrics']['net_pnl'] = '42'
        self.other_payload = bind(other)
        self.other = self.save(self.other_payload)
        self.context = tools.ReadContext(self.root, tuple(self.evidence(p) for p in (self.payload, self.other_payload)))

    def save(self, payload):
        identity = content_hash(payload)
        write_json(self.root / identity / 'result.json', {'kind': 'quantlab_result_v1', 'sha256': identity, 'payload': payload})
        return identity

    def evidence(self, payload, observations=123):
        return tools.TrainingEvidence(content_hash(payload), payload['manifest']['data_hash'], observations)

    def call(self, name, args=None, context=None):
        arguments = {} if name in ('list_saved_results', 'get_paper_positions', 'get_paper_orders') else {'result_id': self.identity}
        if name == 'compare_results':
            arguments['other_id'] = self.other
        arguments.update(args or {})
        return tools.READ_REGISTRY.call(name, json.dumps(arguments), capabilities=('research.read', 'paper.read'), context=context or self.context)

    def test_exact_registry_read_effects_closed_arguments_and_declared_bounds(self):
        self.assertEqual(set(tools.READ_REGISTRY.declarations), set(tools.TOOL_NAMES))
        for name, declaration in tools.READ_REGISTRY.declarations.items():
            self.assertEqual(declaration['effect'], 'read')
            self.assertIn(declaration['capability'], ('research.read', 'paper.read'))
            self.assertFalse(any(word in name for word in ('amend', 'cancel', 'place')))
            self.assertEqual(declaration['maxItems'], MAX_LIMIT)
            self.assertEqual(declaration['pageSizeCap'], MAX_LIMIT)
            self.assertEqual(declaration['maxSerializedBytes'], MAX_RETURN_BYTES)
            for args in ({'limit': 51}, {'cursor': -1}, {'path': '/tmp/secret'}, {'limit': True}):
                self.assertEqual(self.call(name, args), REFUSAL)
        self.assertEqual(sum(d['effect'] == 'mutation' for d in tools.READ_REGISTRY.declarations.values()), 0)
        self.assertEqual(tools.READ_REGISTRY.call('list_saved_results', '{}', context=self.context), REFUSAL)

    def test_paging_concatenates_every_in_sample_row_and_ends_without_truncation(self):
        for name, field, expected in (
            ('get_backtest_trades', 'net_pnl', [str(i) for i in range(123)]),
            ('get_backtest_equity', 'equity', [str(100000 + i) for i in range(123)]),
        ):
            cursor, rows = 0, []
            for _ in range(4):
                page = self.call(name, {'cursor': cursor})
                self.assertTrue(page['ok'], page)
                self.assertLessEqual(len(json.dumps(page).encode()), MAX_RETURN_BYTES)
                rows.extend(page['items'])
                if not page['truncated']:
                    self.assertIsNone(page['next_cursor'])
                    break
                cursor = page['next_cursor']
            self.assertEqual([r['index'] for r in rows], list(range(123)))
            self.assertEqual([r[field] for r in rows], expected)
            self.assertFalse(page['truncated'])
            self.assertEqual(self.call(name, {'cursor': 124}), REFUSAL)

    def test_large_summary_whitelist_compare_two_distinct_ids_and_params(self):
        payload = deepcopy(self.payload)
        payload['metrics']['untrusted_blob'] = 'TOKEN_SENTINEL' * 10000
        payload = bind(payload)
        identity = self.save(payload)
        context = replace(self.context, training=(*self.context.training, self.evidence(payload)))
        summary = self.call('get_backtest_summary', {'result_id': identity}, context)
        self.assertTrue(summary['ok'])
        self.assertLessEqual(len(json.dumps(summary).encode()), MAX_RETURN_BYTES)
        self.assertEqual(set(summary['items'][0]), set(tools.METRICS))
        assert_no_protected_values(self, summary)
        delta = self.call('compare_results')
        self.assertTrue(delta['ok'], delta)
        self.assertEqual(set(delta['items'][0]), set(tools.METRICS))
        self.assertEqual(Decimal(delta['items'][0]['net_pnl']), Decimal('42') - Decimal(self.payload['metrics']['net_pnl']))
        for args in ({'other_id': self.identity}, {'other_id': '0' * 64}, {'other_id': ''}, {'third_id': self.other}):
            self.assertEqual(self.call('compare_results', args), REFUSAL)
        self.assertEqual(tools.READ_REGISTRY.call('compare_results', '{}', capabilities=('research.read',), context=context), REFUSAL)
        params = self.call('get_strategy_params')['items'][0]
        self.assertEqual(set(params), set(tools.PARAMETER_CONTRACTS[self.payload['manifest']['strategy']['family']]))
        self.assertEqual(self.call('get_strategy_params'), self.call('get_strategy_params'))

    def test_bad_identifiers_never_open_files_and_corruption_never_leaks(self):
        with patch.object(Path, 'open', side_effect=AssertionError('outside read')) as read:
            for identity in ('../secret', '/home/SECRET_USERNAME', 'C:\\secret', '..' + 'a' * 62, 'A' * 64):
                self.assertEqual(self.call('get_backtest_summary', {'result_id': identity}), REFUSAL)
            read.assert_not_called()
        with patch.object(Path, 'is_symlink', return_value=True), patch.object(Path, 'open') as read:
            self.assertEqual(self.call('get_backtest_summary'), REFUSAL)
            read.assert_not_called()
        path = self.root / self.identity / 'result.json'
        for raw in ('TOKEN_SENTINEL', '{"payload":', '{"payload":{},"payload":{}}', '{"payload":NaN}'):
            path.write_text(raw, encoding='utf-8')
            output = self.call('get_backtest_summary')
            self.assertEqual(output, REFUSAL)
            assert_no_protected_values(self, output)
        path.write_bytes(b' ' * 1025)
        with patch.object(tools, 'MAX_SAVED_BYTES', 1024):
            self.assertEqual(self.call('list_saved_results'), REFUSAL)
        wrong = replace(self.context, training=(replace(self.context.training[0], data_hash='f' * 64),))
        self.save(self.payload)
        self.assertEqual(self.call('get_backtest_summary', context=wrong), REFUSAL)
        for field, value in (('ledger', {}), ('ledger', [{}]), ('metrics', {}), ('equity', ['TOKEN_SENTINEL'])):
            malformed = bind({**self.payload, field: value})
            identity = self.save(malformed)
            context = replace(self.context, training=(self.evidence(malformed),))
            self.assertEqual(self.call('get_backtest_summary', {'result_id': identity}, context), REFUSAL)

    def test_d11_byte_overflow_and_model_json_refuse_without_partial_items(self):
        with patch('quantlab.agent_tools.MAX_RETURN_BYTES', 100):
            self.assertEqual(self.call('get_backtest_summary'), REFUSAL)
            self.assertEqual(self.call('get_backtest_trades'), REFUSAL)
        for raw in ('{"limit":1,"limit":2}', '{"limit":NaN}', '```json\n{}\n```', '{"code":"import os"}', ' ' * 4097):
            self.assertEqual(tools.READ_REGISTRY.call('list_saved_results', raw, capabilities=('research.read',), context=self.context), REFUSAL)

    def protected_context(self):
        protected = deepcopy(self.payload)
        protected['metrics']['net_pnl'] = '987654.321'
        protected['ledger'][0]['net_pnl'] = '987654.321'
        protected['equity'][0]['equity'] = '987654.321'
        protected['warnings'] = ['OOS_SENTINEL', 'HOLDOUT_SENTINEL', 'CONSUMED_GUARD_SENTINEL']
        protected = bind(protected)
        identity = self.save(protected)
        # OOS/holdout records exist under the same root but NEVER in host grants.
        return identity, self.evidence(protected, observations=31337)

    def test_all_tool_outputs_recursive_oos_holdout_credential_and_path_sentinels(self):
        protected_id, _ = self.protected_context()
        path = self.root / self.identity / 'result.json'
        envelope = json.loads(path.read_text(encoding='utf-8'))
        envelope['oos'] = {'prices': [987654.321], 'rows': 31337, 'marker': 'OOS_SENTINEL'}
        envelope['final_holdout'] = {'marker': 'HOLDOUT_SENTINEL', 'metrics': [987654.321]}
        envelope['raw'] = [
            'TOKEN_SENTINEL',
            'CREDENTIAL_SENTINEL',
            'C:\\Users\\SECRET_USERNAME\\secret.csv',
            '/home/SECRET_USERNAME/secret.csv',
            '\\\\private-server\\SECRET_USERNAME',
            'USER_RAW_FILE_SENTINEL',
            'CONSUMED_GUARD_SENTINEL',
        ]
        write_json(path, envelope)
        with (
            patch('socket.socket', side_effect=AssertionError('network')) as network,
            patch('quantlab.provider.HTTPTransport.__call__', side_effect=AssertionError('provider')) as provider,
        ):
            for name in tools.TOOL_NAMES:
                for cursor in (0, 50, 100, 123):
                    output = self.call(name, {'cursor': cursor})
                    assert_no_protected_values(self, output)
                output = self.call(name, {'result_id': protected_id})
                self.assertEqual(output, REFUSAL)
            quality = self.call('get_data_quality_summary')['items'][0]
            self.assertEqual(quality, {'observations': 123, 'missing': 0, 'duplicates': 0, 'has_gaps': False})
            self.assertEqual(self.call('list_saved_results')['items'], [{'id': identity} for identity in sorted((self.identity, self.other))])
            network.assert_not_called()
            provider.assert_not_called()

    def test_negative_control_removing_provenance_filter_fails_the_recursive_oracle(self):
        protected_id, evidence = self.protected_context()
        approved = tools._approved(self.context)
        with patch.object(tools, '_approved', return_value={**approved, protected_id: evidence}):
            output = self.call('get_backtest_summary', {'result_id': protected_id})
            self.assertTrue(output['ok'])
            with self.assertRaises(AssertionError):
                assert_no_protected_values(self, output)
            with self.assertRaises(AssertionError):
                assert_no_protected_values(self, self.call('get_data_quality_summary', {'result_id': protected_id}))

    def test_paper_reader_never_opens_an_execution_session_or_mutates_journal(self):
        fixture = paper_fixture.PaperTests()
        paper_root = self.root / 'paper'
        paper_root.mkdir()
        with patch.object(tempfile, 'TemporaryDirectory', return_value=SimpleNamespace(name=str(paper_root), cleanup=lambda: None)):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submit()
        fixture.broker.apply_event(fixture.event())
        fixture.submit('pending')
        before = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        context = replace(self.context, paper_journal=fixture.path)
        with ExitStack() as stack:
            spies = [
                stack.enter_context(patch.object(tools.PaperBroker, name, side_effect=AssertionError(name)))
                for name in ('__init__', '_transaction', '_append', 'submit', 'amend', 'cancel', 'apply_event', 'reconcile')
            ]
            for name in ('get_paper_positions', 'get_paper_orders'):
                output = self.call(name, context=context)
                self.assertTrue(output['ok'], output)
                self.assertTrue(output['items'])
                assert_no_protected_values(self, output)
            for spy in spies:
                spy.assert_not_called()
        self.assertEqual(hashlib.sha256(fixture.path.read_bytes()).hexdigest(), before)

    def test_new_module_has_no_dynamic_execution_ui_or_process_imports(self):
        tree = ast.parse((ROOT / 'quantlab/agent_read_tools.py').read_text(encoding='utf-8'))
        prohibited = {'eval', 'exec', 'compile', '__import__', 'pickle', 'subprocess'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, prohibited)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, prohibited)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
                self.assertFalse(any(part.startswith(('PySide6', 'Qt', 'desktop')) or part in prohibited for name in names for part in name.split('.')))
