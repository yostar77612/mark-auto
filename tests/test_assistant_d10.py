"""Cheap offline discovered-model, effort and reported-context contracts."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from quantlab.assistant.adapters.chatgpt.provider import parse_models
from desktop_app.features.assistant.connection import ConnectionController, ChatGPTConnectionPanel
from desktop_app.features.assistant.assistant import AssistantPanel
from desktop_app.features.assistant.assistant_models import context_usage
from desktop_app.features.assistant.worker import chatgpt_reply
from desktop_app.strings.catalog import ui_text
from quantlab.errors import ERROR_TABLE


class AssistantD10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, *, models=('discovered-a', 'discovered-b'), metadata=None, settings=None, controller=None, connection=None):
        controller = controller or SimpleNamespace(
            models=models, model_labels=tuple((m, 'Label ' + m) for m in models), model_metadata=metadata or {}, active_registration='opaque'
        )
        self.controller = controller
        self.worker = SimpleNamespace(active=False, start=Mock(), poll=Mock(return_value=None), cancel=Mock())
        host = SimpleNamespace(chatgpt_controller=controller, chatgpt_panel=connection, settings=settings)
        panel = AssistantPanel(host, worker=self.worker, consent=Mock(return_value=True))
        self.addCleanup(panel.deleteLater)
        self.panel = panel
        return panel

    def test_only_discovered_models_and_missing_effort_usage_no_network(self):
        rows = parse_models({'models': [{'slug': 'found', 'display_name': 'Found', 'visibility': 'list', 'reasoning_efforts': ['invented']}]})
        with patch('socket.socket') as network:
            p = self.make_panel(models=tuple(r['slug'] for r in rows))
            self.assertEqual([p.model.itemData(i) for i in range(p.model.count())], ['found'])
            self.assertEqual(p.effort.currentText(), ui_text('assistant.not_provided'))
            self.assertFalse(p.effort.isEnabled())
            self.assertIn('not provided', p.models.usage.text())
            self.assertNotIn('0%', p.models.usage.text())
            self.assertIn('provider-reported, unverified', p.models.usage.text())
            p.models.refresh()
            network.assert_not_called()
            self.worker.start.assert_not_called()

    def test_advertised_effort_only_keyboard_and_reset(self):
        p = self.make_panel(metadata={'discovered-a': {'reasoning_efforts': ['low', 'high']}, 'discovered-b': {'reasoning_efforts': ['minimal']}})
        self.assertEqual([p.effort.itemData(i) for i in range(p.effort.count())], [None, 'low', 'high'])
        self.assertFalse(p.model.isEditable())
        self.assertFalse(p.effort.isEditable())
        QTest.keyClick(p.effort, Qt.Key.Key_End)
        self.assertEqual(p.effort.currentData(), 'high')
        QTest.keyClick(p.model, Qt.Key.Key_Down)
        self.assertEqual(p.model.currentData(), 'discovered-b')
        self.assertIsNone(p.effort.currentData())
        self.assertEqual(p.effort.findData('high'), -1)
        for combo in (p.model, p.effort):
            self.assertTrue(combo.accessibleName())
            self.assertTrue(combo.focusPolicy() & Qt.FocusPolicy.TabFocus)

    def test_send_revalidates_stale_invalid_slug_and_effort_b1(self):
        p = self.make_panel(metadata={'discovered-a': {'reasoning_efforts': ['low']}})
        p.mode.setCurrentIndex(1)
        p.input.setText('Training interpretation')
        self.controller.models = ('discovered-b',)
        p.submit()
        self.worker.start.assert_not_called()
        self.assertIn(ERROR_TABLE['agent_tool_refused'].explanation, p.transcript.toPlainText())
        self.controller.models = ('discovered-a',)
        p.effort.setCurrentIndex(1)
        self.controller.model_metadata = {}
        p.submit()
        self.worker.start.assert_not_called()
        p.model.setItemData(0, 'invalid/model')
        self.controller.models = ('invalid/model',)
        p.submit()
        self.worker.start.assert_not_called()

    def test_empty_catalog_remote_send_disabled_and_bare_host_safe(self):
        p = self.make_panel(models=())
        self.assertFalse(p.send.isEnabled())
        p.mode.setCurrentIndex(1)
        self.assertFalse(p.send.isEnabled())
        self.assertFalse(p.models.empty.isHidden())
        p.input.setText('hello')
        p.submit()
        self.worker.start.assert_not_called()
        bare = AssistantPanel(SimpleNamespace(), worker=self.worker)
        self.addCleanup(bare.deleteLater)
        self.assertFalse(bare.send.isEnabled())
        bare.mode.setCurrentIndex(1)
        self.assertFalse(bare.send.isEnabled())

    def test_preferences_missing_corrupt_and_supported_only(self):
        for pref in ({'model': 'removed', 'effort': 'high'}, {'model': 'discovered-a', 'effort': 'invented'}, None):
            settings = SimpleNamespace(load=Mock(return_value={'assistant_model_preference': pref}), save=Mock())
            p = self.make_panel(settings=settings)
            self.assertEqual(p.model.currentData(), 'discovered-a')
            self.assertIsNone(p.effort.currentData())
        settings.load.return_value = {'assistant_model_preference': {'model': 'discovered-b', 'effort': 'high'}}
        p = self.make_panel(settings=settings, metadata={'discovered-b': {'reasoning_efforts': ['high']}})
        self.assertEqual(p.models.validate(), ('discovered-b', 'high'))
        p.model.setCurrentIndex(0)
        self.assertEqual(settings.save.call_args.args[0]['assistant_model_preference'], {'model': 'discovered-a', 'effort': None})

    def test_context_rounding_clamping_missing_and_unverified(self):
        p = self.make_panel()
        for used, limit, percent in ((1, 8, 13), (1, 6, 17), (0, 100, 0), (-1, 100, 0), (101, 100, 100)):
            self.assertEqual(context_usage({'used': used, 'limit': limit}), (used, limit, percent))
            p.models.set_usage({'used': used, 'limit': limit})
            self.assertIn(f'{used}/{limit} ({percent}%)', p.models.usage.text())
            self.assertIn('provider-reported, unverified', p.models.usage.text())
        for usage in (None, {}, {'used': True, 'limit': 100}, {'used': 4, 'limit': 0}, {'total_tokens': 99}):
            p.models.set_usage(usage)
            self.assertNotIn('0%', p.models.usage.text())
            self.assertIn('not provided', p.models.usage.text())
        p.models.set_usage({'used': 3, 'limit': 100})
        p.model.setCurrentIndex(1)
        self.assertIn('not provided', p.models.usage.text())

    def test_missing_provider_context_and_changed_model_discard_usage(self):
        p = self.make_panel()
        p.mode.setCurrentIndex(1)
        p.input.setText('training summary')
        p.submit()
        self.worker.poll.return_value = {'ok': True, 'text': 'unverified', 'usage': {'total_tokens': 100}}
        p.poll()
        self.assertIn('not provided', p.models.usage.text())
        self.assertNotIn('0%', p.models.usage.text())
        p.input.setText('second training summary')
        p.submit()
        p.model.setCurrentIndex(1)
        self.worker.poll.return_value = {'ok': True, 'text': 'unverified', 'context_usage': {'used': 1, 'limit': 8}}
        p.poll()
        self.assertIn('not provided', p.models.usage.text())

    def test_malformed_capabilities_fail_closed_and_late_discovery_restores_safely(self):
        settings = SimpleNamespace(load=Mock(return_value={'assistant_model_preference': {'model': 'removed', 'effort': 'high'}}), save=Mock())
        p = self.make_panel(models=(), settings=settings)
        self.controller.models = ('late-discovered',)
        self.controller.model_metadata = {'late-discovered': {'reasoning_efforts': ['low', '<script>']}}
        p.models.refresh()
        self.assertEqual(p.model.currentData(), 'late-discovered')
        self.assertFalse(p.effort.isEnabled())
        self.assertIsNone(p.effort.currentData())
        self.assertEqual(p.models.validate(), ('late-discovered', None))

    def test_public_transport_effort_usage_and_denied_consent(self):
        p = self.make_panel(metadata={'discovered-a': {'reasoning_efforts': ['low']}})
        p.mode.setCurrentIndex(1)
        p.effort.setCurrentIndex(1)
        p.input.setText('training summary')
        p.ask_consent.return_value = False
        p.submit()
        self.worker.start.assert_not_called()
        self.assertEqual(p.transcript.toPlainText(), '')
        p.ask_consent.return_value = True
        p.submit()
        request = self.worker.start.call_args.args[0]
        response = {
            'type': 'response.completed',
            'response': {
                'status': 'completed',
                'context_usage': {'used': 1, 'limit': 8},
                'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '<b>literal</b> ```code```'}]}],
            },
        }
        payloads = []

        class Transport:
            def stream(self, reference, payload, limits):
                payloads.append(payload)
                yield ('data: ' + json.dumps(response) + '\n\n').encode()

        reference = Mock(return_value='DPAPI_SECRET_SENTINEL')
        result = chatgpt_reply(request, '.', transport=Transport(), reference_factory=lambda *_: reference)
        reference.assert_not_called()
        self.assertEqual(payloads[0]['reasoning'], {'effort': 'low'})
        self.assertEqual(payloads[0]['input'], [{'role': 'user', 'content': 'training summary'}])
        self.assertEqual(result['context_usage'], {'used': 1, 'limit': 8})
        self.worker.poll.return_value = result
        p.poll()
        self.assertIn('<b>literal</b>', p.transcript.toPlainText())
        self.assertIn('13%', p.models.usage.text())
        for sentinel in ('DPAPI_SECRET_SENTINEL', 'OOS_SENTINEL', 'HOLDOUT_SENTINEL'):
            self.assertNotIn(sentinel, json.dumps(payloads) + p.transcript.toPlainText())
            with self.assertRaises(AssertionError):
                self.assertNotIn(sentinel, 'negative control ' + sentinel)
        request['consent'] = False
        self.assertFalse(chatgpt_reply(request, '.', transport=Transport())['ok'])
        self.assertEqual(len(payloads), 1)

    def test_d9_and_campaign_invalidation_uses_existing_signals(self):
        controller = ConnectionController()
        controller.models = ('discovered-a', 'discovered-b')
        connection = ChatGPTConnectionPanel(controller)
        self.addCleanup(connection.deleteLater)
        p = self.make_panel(controller=controller, connection=connection)
        controller.test_message = 'previous test'
        controller.usage_known = True
        p.model.setCurrentIndex(1)
        self.assertEqual(connection.model.currentData(), 'discovered-b')
        self.assertEqual(controller.test_message, ui_text('connection_test.untested'))
        self.assertFalse(controller.usage_known)

    def test_new_source_no_dynamic_execution_or_operator(self):
        source = Path('desktop_app/features/assistant/assistant_models.py').read_text(encoding='utf-8')
        calls = [node.func.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertFalse(set(calls) & {'eval', 'exec', 'compile'})


if __name__ == '__main__':
    unittest.main()
