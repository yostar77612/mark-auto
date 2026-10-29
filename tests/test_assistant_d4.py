"""Cheap offline D4 safety, consent, presentation and lifecycle regressions."""

import ast
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QHideEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_app.features.assistant import worker as adapter
from desktop_app.features.assistant.assistant import AssistantPanel
from desktop_app.strings.catalog import ui_text
from quantlab.agent_read_tools import TOOL_NAMES
from quantlab.agent_tool_contract import MAX_RETURN_BYTES
from quantlab.assistant_chat import ChatDispatcher
from tests.test_agent_harness_d1 import REFUSAL, assert_no_protected_values
from tests import test_agent_read_tools_d3 as d3_fixture


ROOT = Path(__file__).resolve().parents[1]


class AssistantD4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        d3_fixture.AgentReadToolsD3Tests.setUpClass()

    def setUp(self):
        self.storage = d3_fixture.AgentReadToolsD3Tests()
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.protected_id, self.protected_evidence = self.storage.protected_context()
        path = self.storage.root / self.storage.identity / 'result.json'
        envelope = json.loads(path.read_text(encoding='utf-8'))
        envelope['oos'] = {'marker': 'OOS_SENTINEL', 'prices': [987654.321], 'rows': 31337}
        envelope['final_holdout'] = {'marker': 'HOLDOUT_SENTINEL', 'metrics': [987654.321]}
        envelope['credentials'] = ['CREDENTIAL_SENTINEL', 'TOKEN_SENTINEL']
        path.write_text(json.dumps(envelope), encoding='utf-8')
        self.dispatcher = ChatDispatcher(self.storage.context)
        self.worker = SimpleNamespace(active=False, cancel=Mock(), start=Mock(), poll=Mock(return_value=None))
        # D10 requires current discovery even in the consent/keyboard fixture.
        host = SimpleNamespace(chatgpt_controller=SimpleNamespace(models=('fixture-model',), model_labels=()))
        self.panel = AssistantPanel(host, dispatcher=self.dispatcher, worker=self.worker, consent=lambda: False)
        self.addCleanup(self.panel.deleteLater)

    def test_exact_frozen_read_surface_and_unknown_names_never_dispatch(self):
        self.assertEqual(set(self.dispatcher.declarations), set(TOOL_NAMES))
        self.assertTrue(all(d['effect'] == 'read' for d in self.dispatcher.declarations.values()))
        with patch('quantlab.agent_tools.Registry.call') as handler:
            for name in (
                'research.list_training_status',
                'run_backtest',
                'start_campaign',
                'run_walk_forward',
                'save_candidate',
                'consume_quota',
                'place_order',
                'eval',
                'save',
                'run',
                None,
            ):
                self.assertEqual(self.dispatcher.call(name, '{}'), REFUSAL)
            handler.assert_not_called()
        declaration = self.dispatcher.declarations['list_saved_results']
        declaration['effect'] = 'mutation'
        self.assertEqual(self.dispatcher.declarations['list_saved_results']['effect'], 'read')
        with patch('quantlab.agent_tools.Registry.register', wraps=Mock()) as register:
            self.dispatcher.call('list_saved_results', '{}')
            register.assert_not_called()
        registry = self.dispatcher._ChatDispatcher__registry
        self.assertEqual(registry.register(declaration, Mock()), REFUSAL)

    def test_fixture_golden_no_provider_and_disclaimer_on_every_reply(self):
        with patch('desktop_app.features.assistant.worker.chatgpt_reply') as provider, patch('socket.socket') as network:
            self.panel.input.setText('help')
            self.panel.submit()
            expected = (
                ui_text('assistant.user')
                + '\nhelp\n'
                + ui_text('assistant.fixture')
                + '\n'
                + '這是固定離線示範，不是真實 AI。只能讀取九項已授權工具；不會啟動回測、研究、Walk-forward 或保存候選。使用 /tool list_saved_results {} 查閱有訓練證據的結果。'
                + '\nAI 解讀可能有誤；不會自動套用任何變更或下單。'
            )
            self.assertEqual(self.panel.transcript.toPlainText(), expected)
            self.panel.input.setText('anything')
            self.panel.submit()
            self.panel.error_reply()
            self.panel.reply('<b>x</b><script>```danger```', chatgpt=True)
            provider.assert_not_called()
            network.assert_not_called()
        transcript = self.panel.transcript.toPlainText()
        self.assertEqual(transcript.count(ui_text('assistant.disclaimer')), 4)
        self.assertIn('<b>x</b><script>```danger```', transcript)
        self.assertIn(ui_text('assistant.chatgpt'), transcript)
        self.assertFalse(self.panel.transcript.document().isEmpty())
        self.assertEqual(self.panel.title.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.panel.transcript.isReadOnly())

    def test_cancel_consent_has_no_outgoing_request_or_transcript(self):
        self.panel.mode.setCurrentIndex(1)
        consent = Mock(return_value=False)
        self.panel.ask_consent = consent
        self.panel.input.setText('hello')
        self.panel.submit()
        consent.assert_called_once()
        self.worker.start.assert_not_called()
        self.assertEqual(self.panel.transcript.toPlainText(), '')
        self.assertEqual(self.panel.input.text(), 'hello')
        with patch('quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport') as provider:
            self.assertEqual(adapter.chatgpt_reply({'consent': False}, None), REFUSAL)
            provider.assert_not_called()

    def test_consent_each_call_errors_and_keyboard_accessibility(self):
        self.panel.mode.setCurrentIndex(1)
        self.panel.ask_consent = Mock(return_value=True)
        self.panel.input.setText('first')
        QTest.keyClick(self.panel.input, Qt.Key.Key_Return)
        self.worker.start.assert_called_once()
        self.worker.poll.return_value = REFUSAL
        self.panel.poll()
        self.panel.input.setText('second')
        self.panel.send.click()
        self.assertEqual(self.panel.ask_consent.call_count, 2)
        self.panel.poll()
        self.assertEqual(self.panel.transcript.toPlainText().count(ui_text('assistant.disclaimer')), 2)
        self.assertTrue(self.panel.input.accessibleName())
        self.assertTrue(self.panel.send.accessibleName())
        self.assertIs(self.panel.input.nextInFocusChain(), self.panel.send)
        self.assertEqual(self.panel.shortcut.key().toString(), 'Ctrl+Return')

    def test_tool_returns_bounded_and_evidence_cannot_be_claimed(self):
        identity = self.storage.identity
        context = replace(self.storage.context, training=())
        legacy = ChatDispatcher(context)
        self.assertEqual(legacy.call('get_backtest_summary', json.dumps({'result_id': identity})), REFUSAL)
        for claims in ({'dataset': 'training'}, {'partition': 'training'}, {'training': [identity]}, {'context': {'training': True}}):
            self.assertEqual(legacy.call('get_backtest_summary', json.dumps({'result_id': identity, **claims})), REFUSAL)
        self.assertEqual(legacy.call('list_saved_results', '{}')['items'], [])
        raw = self.dispatcher.render_tool('get_backtest_trades', json.dumps({'result_id': identity}))
        self.assertLessEqual(len(raw.encode()), MAX_RETURN_BYTES)
        self.assertTrue(json.loads(raw)['truncated'])
        self.assertLess(len(json.loads(raw)['items']), len(self.storage.payload['ledger']))
        self.assertIsNotNone(json.loads(raw)['next_cursor'])
        # Real central byte overflow still pages and never displays the whole list.
        with patch('quantlab.agent_read_tools._read', return_value=[{'id': str(i).zfill(64)} for i in range(300)]):
            raw = self.dispatcher.render_tool('list_saved_results', '{"limit":50}')
            self.assertTrue(json.loads(raw)['truncated'])
            self.assertLessEqual(len(raw.encode()), MAX_RETURN_BYTES)
        number = '1.' + '2' * 64
        rows = [dict(index=i, quantity=number, entry_price=number, exit_price=number, net_pnl=number) for i in range(50)]
        self.assertGreater(len(json.dumps(rows).encode()), MAX_RETURN_BYTES)
        with patch('quantlab.agent_read_tools._read', return_value=rows):
            raw = self.dispatcher.render_tool('get_backtest_trades', json.dumps({'result_id': identity}))
        self.assertEqual(json.loads(raw)['reason'], 'byte_limit')
        self.assertLessEqual(len(raw.encode()), MAX_RETURN_BYTES)

    def test_all_d3_payloads_and_transcript_exclude_protected_values(self):
        for name in TOOL_NAMES:
            arguments = {} if name.startswith('get_paper_') or name == 'list_saved_results' else {'result_id': self.storage.identity}
            if name in ('compare_results', 'compare_result_manifests'):
                arguments['other_id'] = self.storage.other
            raw = self.dispatcher.render_tool(name, json.dumps(arguments))
            assert_no_protected_values(self, json.loads(raw))
            self.panel.reply(raw)
        assert_no_protected_values(self, self.panel.transcript.toPlainText())
        self.assertEqual(self.dispatcher.call('get_backtest_summary', json.dumps({'result_id': self.protected_id})), REFUSAL)
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, {'planted': 'TOKEN_SENTINEL'})
        # A deliberately broken provenance filter must fail the same oracle.
        from quantlab.agent_read_tools import _approved

        with patch('quantlab.agent_read_tools._approved', return_value={**_approved(self.storage.context), self.protected_id: self.protected_evidence}):
            leaked = self.dispatcher.call('get_backtest_summary', json.dumps({'result_id': self.protected_id}))
            self.assertTrue(leaked['ok'])
            with self.assertRaises(AssertionError):
                assert_no_protected_values(self, leaked)
        # No assistant module contains transcript persistence or dynamic execution.
        for filename in ('desktop_app/features/assistant/worker.py', 'desktop_app/features/assistant/assistant.py', 'quantlab/assistant_chat.py'):
            tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
            calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            self.assertFalse(set(calls) & {'eval', 'exec', 'compile', 'open'})
            attributes = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            self.assertFalse(set(attributes) & {'write_text', 'write_bytes', 'save', 'run_backtest', 'run_campaign', 'run_walk_forward', '_reserve'})

    def test_operator_and_quota_entry_points_unreachable(self):
        with ExitStack() as stack:
            sentinels = [
                stack.enter_context(patch(target, side_effect=AssertionError('operator called')))
                for target in (
                    'quantlab.backtest.run_backtest',
                    'quantlab.research.run_campaign',
                    'quantlab.walk_forward.run_walk_forward',
                    'quantlab.reporting.save_selection',
                    'quantlab.assistant.adapters.chatgpt.provider.ChatGPTPlanProvider._reserve',
                )
            ]
            for name in ('run_backtest', 'run_campaign', 'run_walk_forward', 'save_candidate', 'consume_quota'):
                self.panel.input.setText('/tool ' + name + ' {}')
                self.panel.submit()
            for sentinel in sentinels:
                sentinel.assert_not_called()

    def test_hide_close_pending_cancel_no_thread(self):
        self.worker.active = True
        self.panel.hideEvent(QHideEvent())
        self.worker.cancel.assert_called_once()
        self.worker.cancel.reset_mock()
        self.panel.closeEvent(QCloseEvent())
        self.worker.cancel.assert_called_once()
        self.assertFalse(self.panel.timer.isActive())
        self.assertTrue(self.panel.send.isEnabled())
        worker = adapter.ReplyProcess(None, clock=lambda: 31)
        process = Mock(pid=42)
        process.is_alive.side_effect = [True, False, False]
        worker.process = process
        worker.receiver = Mock()
        worker.receiver.poll.return_value = False
        worker.deadline = 30
        self.assertEqual(worker.poll(), REFUSAL)
        self.assertFalse(worker.active)
        process.terminate.assert_called_once()
        process.join.assert_called()
        process.close.assert_called_once()

    def test_network_payload_single_prompt_no_history_and_secret_scan(self):
        secret = 'DPAPI_SECRET_SENTINEL'
        prompt = 'Interpret training metrics'
        request = {'consent': True, 'prompt': prompt, 'model': 'fixture-model', 'registration': 'opaque'}
        terminal = {
            'type': 'response.completed',
            'response': {
                'status': 'completed',
                'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '<b>x</b><script>'}]}],
            },
        }
        transport = Mock()
        reference = Mock(return_value=secret)

        # The adapter owns closing streams, just like the existing provider.
        def stream(*args):
            yield b'data: ' + json.dumps(terminal).encode() + b'\n\n'

        transport.stream.side_effect = stream
        result = adapter.chatgpt_reply(request, None, transport=transport, reference_factory=lambda *args: reference)
        self.assertTrue(result['ok'])
        payload = transport.stream.call_args.args[1]
        self.assertEqual(payload['input'], [{'role': 'user', 'content': prompt}])
        self.assertFalse(payload['store'])
        self.assertNotIn('tools', payload)
        reference.assert_not_called()
        self.panel.reply(result['text'], chatgpt=True)
        combined = json.dumps(payload) + self.panel.transcript.toPlainText()
        self.assertNotIn(secret, combined)
        assert_no_protected_values(self, combined)
        self.assertEqual(self.panel.transcript.toPlainText().count(ui_text('assistant.disclaimer')), 1)

    def test_provider_errors_no_secrets_or_persistence(self):
        sender = Mock()
        gate = Mock()
        gate.wait.return_value = True
        with patch('desktop_app.features.assistant.worker.chatgpt_reply', side_effect=RuntimeError('DPAPI_SECRET_SENTINEL')):
            adapter._worker(sender, gate, {}, None)
        self.assertEqual(json.loads(sender.send_bytes.call_args.args[0]), REFUSAL)
        sender.close.assert_called_once()
        with patch.object(Path, 'write_text') as write_text, patch.object(Path, 'write_bytes') as write_bytes:
            self.panel.reply('session only')
            self.panel.input.setText('help')
            self.panel.submit()
            write_text.assert_not_called()
            write_bytes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
