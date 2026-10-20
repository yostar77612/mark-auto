"""Cheap saved-manifest safety, registry, paging and keyboard regressions."""

import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView

from desktop_pages.assistant import AssistantPanel
from desktop_pages.assistant_manifest import ManifestDetails
from desktop_pages.assistant_runtime import chatgpt_reply
from desktop_strings import ui_text
from quantlab import agent_manifest
from quantlab.agent_read_tools import ReadContext, TOOL_NAMES, READ_REGISTRY, _row_schema
from quantlab.agent_tool_contract import MAX_RETURN_BYTES, validate
from quantlab.assistant_chat import ChatDispatcher
from quantlab.core import content_hash
from tests import test_agent_read_tools_d3 as fixture
from tests.test_agent_harness_d1 import REFUSAL, assert_no_protected_values


ROOT = Path(__file__).resolve().parents[1]
NOT_FOUND = {'ok': False, 'error': {'code': 'agent_reference_not_found', 'params': {}}}


class ManifestD12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        fixture.AgentReadToolsD3Tests.setUpClass()

    def setUp(self):
        self.storage = fixture.AgentReadToolsD3Tests()
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.dispatcher = ChatDispatcher(self.storage.context)

    def call(self, compare=False, **arguments):
        args = {'result_id': self.storage.identity}
        if compare:
            args['other_id'] = self.storage.other
        args.update(arguments)
        return self.dispatcher.call('compare_result_manifests' if compare else 'get_result_manifest', json.dumps(args))

    def save_variant(self, edit):
        payload = deepcopy(self.storage.payload)
        edit(payload['manifest'])
        payload = fixture.bind(payload)
        identity = self.storage.save(payload)
        context = replace(self.storage.context, training=(*self.storage.context.training, self.storage.evidence(payload)))
        self.dispatcher = ChatDispatcher(context)
        return identity

    def test_verbatim_summary_closed_schema_and_exact_additive_surface(self):
        self.assertEqual(TOOL_NAMES[-2:], ('get_result_manifest', 'compare_result_manifests'))
        self.assertEqual(set(self.dispatcher.declarations), set(TOOL_NAMES))
        self.assertTrue(all(d['effect'] == 'read' and d['capability'] in ('research.read', 'paper.read') for d in self.dispatcher.declarations.values()))
        registry = self.dispatcher._ChatDispatcher__registry
        self.assertEqual(registry.register(self.dispatcher.declarations[TOOL_NAMES[-1]], Mock()), REFUSAL)
        page = self.call()
        self.assertTrue(page['ok'], page)
        values = {row['field']: row['value'] for row in page['items']}
        manifest = self.storage.payload['manifest']
        for field in agent_manifest.IDENTITIES:
            self.assertEqual(values[field], manifest[field])
        for field in agent_manifest.COST_FIELDS:
            self.assertEqual(values['costs.' + field], manifest['config']['costs'][field])
        self.assertEqual(list(values), sorted(values))
        for row in page['items']:
            self.assertTrue(validate(row, _row_schema('get_result_manifest')))
            self.assertFalse(validate({**row, 'oos': 1}, _row_schema('get_result_manifest')))
        bad = {'field': 'spec_hash', 'value': 'x' * 64}
        self.assertFalse(validate(bad, agent_manifest.row_schema()))
        self.assertFalse(validate({'field': 'costs.tax_rate', 'value': 'TOKEN_SENTINEL'}, agent_manifest.row_schema()))
        with patch('quantlab.agent_read_tools._read', return_value=[bad]):
            self.assertEqual(self.call(), REFUSAL)

    def test_unknown_and_malformed_hash_and_legacy_fail_closed(self):
        self.assertEqual(self.call(result_id='0' * 64), NOT_FOUND)
        self.assertEqual(self.call(True, other_id='0' * 64), NOT_FOUND)
        with patch.object(Path, 'open', side_effect=AssertionError('schema must reject first')) as read:
            for value in ('g' * 64, 'A' * 64, '../private', 'a' * 63):
                declaration = READ_REGISTRY.declarations['get_result_manifest']
                self.assertFalse(validate({'result_id': value}, declaration['inputSchema']))
                self.assertEqual(self.call(result_id=value), REFUSAL)
            read.assert_not_called()
        legacy = ChatDispatcher(ReadContext(self.storage.root))
        for name in TOOL_NAMES[-2:]:
            args = {'result_id': self.storage.identity, **({'other_id': self.storage.other} if name.startswith('compare') else {})}
            self.assertEqual(legacy.call(name, json.dumps(args)), REFUSAL)

    def test_differences_both_values_and_non_comparable_warnings(self):
        same = self.call(True)
        self.assertTrue(all(row['status'] == 'same' and not row['non_comparable'] for row in same['items']))

        def change(manifest):
            manifest['engine_version'] = 'quantlab-event-v2'
            manifest['config']['costs']['commission_per_side'] = '99.00'
            # Existing validation binds costs to the parsed immutable config.
            from quantlab.__main__ import config_from_json

            config = config_from_json(manifest['config'])
            manifest['config_hash'] = content_hash(config)
            manifest['cost_hash'] = content_hash((config.costs,) + config.cost_schedule)
            dataset = manifest['dataset_manifest']
            dataset['data_hash'] = manifest['data_hash'] = 'd' * 64
            dataset['manifest_hash'] = content_hash({k: v for k, v in dataset.items() if k not in ('manifest_hash', 'imported_at')})
            manifest['dataset_manifest_hash'] = content_hash(dataset)

        identity = self.save_variant(change)
        page = self.call(True, other_id=identity)
        self.assertTrue(page['ok'], page)
        self.assertEqual(page, self.call(True, other_id=identity))
        rows = {row['field']: row for row in page['items']}
        self.assertEqual(list(rows), sorted(rows))
        for field in agent_manifest.NON_COMPARABLE:
            self.assertEqual(rows[field]['status'], 'different')
            self.assertTrue(rows[field]['non_comparable'])
            self.assertNotEqual(rows[field]['left'], rows[field]['right'])
        self.assertEqual(rows['costs.commission_per_side']['right'], '99.00')

    def test_paging_byte_bounds_and_schedule_values(self):
        manifest = deepcopy(self.storage.payload['manifest'])
        manifest['config']['cost_schedule'] = [deepcopy(manifest['config']['costs']) for _ in range(40)]
        # Exercise the bounded serializer independently of immutable config policy.
        rows = agent_manifest.compare(manifest, manifest)
        collected, cursor = [], None
        with patch('quantlab.agent_read_tools._read', return_value=rows):
            for _ in range(20):
                page = self.call(True, **({'cursor': cursor} if cursor else {}))
                self.assertTrue(page['ok'], page)
                self.assertLessEqual(len(json.dumps(page).encode()), MAX_RETURN_BYTES)
                collected.extend(page['items'])
                cursor = page['next_cursor']
                if cursor is None:
                    break
                self.assertTrue(page['truncated'])
                self.assertIn(page['reason'], ('item_limit', 'byte_limit'))
            self.assertEqual(collected, rows)
        first = self.call(limit=2)
        self.assertTrue(first['truncated'])
        self.assertEqual(first['reason'], 'item_limit')
        self.assertEqual(self.call(True, limit=2, cursor=first['next_cursor']), REFUSAL)

    def test_sentinels_and_negative_control_no_operator_or_provider_calls(self):
        def plant(manifest):
            manifest['oos'] = {'prices': [987654.321], 'rows': 31337, 'marker': 'OOS_SENTINEL'}
            manifest['final_holdout'] = 'HOLDOUT_SENTINEL'
            manifest['credentials'] = 'CREDENTIAL_SENTINEL'
            manifest['source_commit'] = '/home/SECRET_USERNAME/TOKEN_SENTINEL'
            manifest['config']['costs']['version'] = 'TOKEN_SENTINEL'
            from quantlab.__main__ import config_from_json

            config = config_from_json(manifest['config'])
            manifest['config_hash'] = content_hash(config)
            manifest['cost_hash'] = content_hash((config.costs,) + config.cost_schedule)

        identity = self.save_variant(plant)
        panel = AssistantPanel(SimpleNamespace(), dispatcher=self.dispatcher, worker=SimpleNamespace(active=False, cancel=Mock()), consent=lambda: False)
        self.addCleanup(panel.deleteLater)
        with ExitStack() as stack:
            spies = [
                stack.enter_context(patch(target, side_effect=AssertionError('forbidden')))
                for target in (
                    'quantlab.backtest.run_backtest',
                    'quantlab.research.run_campaign',
                    'quantlab.walk_forward.run_walk_forward',
                    'quantlab.reporting.save_selection',
                    'desktop_chatgpt_provider.ChatGPTPlanProvider._reserve',
                    'desktop_chatgpt_provider.PlanHTTPTransport.stream',
                    'socket.socket',
                )
            ]
            for compare in (False, True):
                page = self.call(compare, result_id=identity)
                self.assertTrue(page['ok'], page)
                assert_no_protected_values(self, page)
                panel.reply(json.dumps(page))
            self.assertEqual(chatgpt_reply({'consent': False}, None), REFUSAL)
            for spy in spies:
                spy.assert_not_called()
        assert_no_protected_values(self, panel.transcript.toPlainText())
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, {'planted': 'OOS_SENTINEL'})
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, 'TOKEN_SENTINEL')
        panel.reply('<b>literal</b>\n```danger```')
        self.assertIn('<b>literal</b>', panel.transcript.toPlainText())
        for name in ('quantlab/agent_manifest.py', 'desktop_pages/assistant_manifest.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            self.assertFalse({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} & {'eval', 'exec', 'compile'})

    def test_keyboard_read_compare_missing_optional_plain_readonly_and_bare_host(self):
        identity = self.save_variant(lambda manifest: manifest.pop('engine_version'))
        details = ManifestDetails(self.dispatcher)
        self.addCleanup(details.deleteLater)
        QTest.keyClick(details.refresh_button, Qt.Key.Key_Space)
        details.left.setCurrentIndex(details.left.findData(self.storage.identity))
        details.right.setCurrentIndex(details.right.findData(identity))
        QTest.keyClick(details.compare, Qt.Key.Key_Space)
        self.assertEqual(details.table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(details.title.textFormat(), Qt.TextFormat.PlainText)
        texts = [details.table.item(r, c).text() for r in range(details.table.rowCount()) for c in range(5)]
        self.assertIn(ui_text('manifest.not_recorded'), texts)
        self.assertIn(ui_text('manifest.different'), texts)
        self.assertIn(ui_text('manifest.non_comparable'), texts)
        self.assertIn('quantlab-event-v1', texts)
        QTest.keyClick(details.read, Qt.Key.Key_Space)
        self.assertGreater(details.table.rowCount(), 0)
        panel = AssistantPanel(SimpleNamespace(), dispatcher=self.dispatcher, worker=SimpleNamespace(active=False, cancel=Mock()))
        self.addCleanup(panel.deleteLater)
        self.assertIsInstance(panel.manifest, ManifestDetails)

    def test_untrusted_engine_text_is_never_exposed(self):
        for value in ('C:/Users/SECRET_USERNAME/private', '<b>markup</b>', 'TOKEN_SENTINEL'):
            identity = self.save_variant(lambda manifest: manifest.update(engine_version=value))
            self.assertEqual(self.call(result_id=identity), REFUSAL)
