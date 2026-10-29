"""Cheap offline timeline, privacy, folding and clipboard regressions."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

import desktop_app.components.privacy as privacy
from desktop_app.features.assistant.assistant_details import MAX_ROWS, MAX_SUMMARY_CHARS, TextFold, ToolTimeline, parameter_summary, redacted
from desktop_app.features.assistant import worker as runtime
from desktop_app.strings.catalog import ui_text
from quantlab.errors import ERROR_TABLE
from tests import test_assistant_d4 as d4
from tests.test_agent_harness_d1 import REFUSAL, assert_no_protected_values


ROOT = Path(__file__).resolve().parents[1]


def widget_text(widget):
    parts = []
    for child in [widget, *widget.findChildren(QWidget)]:
        parts.extend((child.accessibleName(), child.accessibleDescription(), child.toolTip()))
        if isinstance(child, QPlainTextEdit):
            parts.append(child.toPlainText())
        elif hasattr(child, 'text'):
            parts.append(child.text())
        parts.extend(str(child.__dict__.get(key, '')) for key in ('_privacy_raw', '_privacy_preview_raw'))
    return '\n'.join(parts)


class AssistantD5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d4.AssistantD4Tests.setUpClass()
        cls.app = QApplication.instance()

    def setUp(self):
        # Reuse the actual D4/D3 protected saved fixtures and their host evidence.
        self.fixture = d4.AssistantD4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.panel = self.fixture.panel
        self.dispatcher = self.fixture.dispatcher

    def test_every_tool_appends_safe_timed_row_and_refusals_use_b1(self):
        ticks = iter((5.0, 5.125, 7.0, 7.5))
        self.panel.timeline.clock = lambda: next(ticks)
        self.panel.input.setText('/tool list_saved_results {}')
        self.panel.submit()
        row = self.panel.timeline.rows[-1]
        self.assertIn('list_saved_results', row.toggle.text())
        self.assertIn('0.125', row.toggle.text())
        self.assertFalse(row.toggle.isChecked())
        self.assertTrue(row.body.isHidden())
        self.assertNotIn(row.source, row.toggle.text())
        with patch.object(self.dispatcher, 'render_tool', side_effect=RuntimeError('TOKEN_SENTINEL traceback')):
            self.panel.input.setText('/tool list_saved_results {"token":"CREDENTIAL_SENTINEL"}')
            self.panel.submit()
        row = self.panel.timeline.rows[-1]
        self.assertIn('agent_tool_refused', row.toggle.text())
        self.assertIn(ERROR_TABLE['agent_tool_refused'].explanation, row.toggle.text())
        self.assertIn('0.500', row.toggle.text())
        assert_no_protected_values(self, widget_text(self.panel))

    def test_long_results_fold_click_and_keyboard_never_full_summary(self):
        arguments = json.dumps({'result_id': self.fixture.storage.identity})
        self.panel.timeline.call(self.dispatcher, 'get_backtest_trades', arguments)
        row = self.panel.timeline.rows[-1]
        self.assertGreater(len(row.body.toPlainText()), MAX_SUMMARY_CHARS)
        self.assertNotIn(row.body.toPlainText(), row.toggle.text())
        self.assertTrue(row.body.isHidden())
        row.toggle.click()
        self.assertFalse(row.body.isHidden())
        QTest.keyClick(row.toggle, Qt.Key.Key_Space)
        self.assertFalse(row.toggle.isChecked())
        self.assertTrue(row.body.isHidden())
        self.assertNotIn(row.source, self.panel.transcript.toPlainText())

    def test_parameter_projection_is_bounded_plain_and_never_echoes_credentials(self):
        arguments = json.dumps({'result_id': 'a' * 64, 'other_id': 'b' * 64, 'token': 'TOKEN_SENTINEL', 'unknown': '<script>OOS_SENTINEL</script>'})
        summary = parameter_summary(arguments)
        self.assertLessEqual(len(summary), MAX_SUMMARY_CHARS)
        self.assertIn('a' * 64, summary)
        assert_no_protected_values(self, summary)
        self.assertNotIn('<script>', summary)
        self.assertNotIn('TOKEN_SENTINEL', json.dumps(redacted({'token': 'TOKEN_SENTINEL'}, False)))
        self.assertLessEqual(len(parameter_summary('x' * 10000)), MAX_SUMMARY_CHARS)
        self.panel.timeline.call(self.dispatcher, 'OOS_SENTINEL', arguments)
        self.assertEqual(self.panel.timeline.rows[-1].findChild(QLabel).textFormat(), Qt.TextFormat.PlainText)
        assert_no_protected_values(self, widget_text(self.panel))

    def test_b11_toggle_masks_parameters_details_and_raw_widget_caches(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        layout = QVBoxLayout(host)
        host.settings = None
        banner = QLabel()
        layout.addWidget(banner)
        layout.addWidget(self.panel)
        host.privacy = privacy.PrivacyState(host, layout, banner)
        arguments = {'account_id': 'ACCOUNT12345678', 'cash': '7654321.25', 'path': 'C:/Users/PrivatePerson/result.json', 'token': 'TOKEN_SENTINEL'}
        result = {'ok': True, 'items': [{'net_pnl': '7654321.25'}], 'truncated': False}
        dispatcher = SimpleNamespace(render_tool=lambda *args: json.dumps(result))
        self.panel.timeline.call(dispatcher, 'list_saved_results', json.dumps(arguments))
        self.panel.reply('```python\nprice = 7654321.25\n```', thinking='<b>7654321.25</b>')
        host.privacy.attach_previews()
        clear = widget_text(self.panel)
        for value in ('ACCOUNT12345678', '7654321.25', 'PrivatePerson'):
            self.assertIn(value, clear)
        self.assertNotIn('TOKEN_SENTINEL', clear)
        host.privacy.set_enabled(True)
        masked = widget_text(self.panel)
        for value in ('ACCOUNT12345678', '7654321.25', 'PrivatePerson', 'TOKEN_SENTINEL'):
            self.assertNotIn(value, masked)
        self.assertIn(privacy.mask_money(None), masked)
        self.assertIn(privacy.mask_account_id('ACCOUNT12345678'), masked)
        host.privacy.set_enabled(False)
        for value in ('ACCOUNT12345678', '7654321.25', 'PrivatePerson'):
            self.assertIn(value, widget_text(self.panel))

    def test_thinking_and_replies_are_literal_unverified_and_copy_is_exact(self):
        block = '  print("<b>literal</b>")\n\n# no execution\n'
        self.panel.reply('<script>alert(1)</script>\n```python\n' + block + '```\n', chatgpt=True, thinking='<b>model summary</b>')
        self.assertIn('<script>alert(1)</script>', self.panel.transcript.toPlainText())
        thinking = self.panel.thinking
        self.assertEqual(thinking.body.toPlainText(), '<b>model summary</b>')
        self.assertTrue(thinking.body.isHidden())
        self.assertEqual(thinking.toggle.text(), ui_text('assistant.thinking'))
        self.assertIn(ui_text('assistant.chatgpt'), widget_text(self.panel))
        fold = self.panel.code_folds[-1]
        self.assertTrue(fold.copy_button.accessibleName())
        self.assertEqual(fold.copy_button.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        QTest.keyClick(fold.copy_button, Qt.Key.Key_Space)
        self.assertEqual(self.app.clipboard().text(), block)
        # Literal markup remains literal even in structured parameters.
        fold.toggle.click()
        self.assertEqual(fold.body.toPlainText(), block)
        crlf = '  literal <html>\r\n\r\n'
        self.panel.reply('```text\r\n' + crlf + '```\r\n')
        self.panel.code_folds[-1].copy_button.click()
        self.assertEqual(self.app.clipboard().text(), crlf)

    def test_reasoning_summary_adapter_only_and_consent_denial_zero_transport(self):
        request = {'consent': True, 'prompt': 'training only', 'model': 'fixture', 'registration': 'opaque'}
        response = {
            'status': 'completed',
            'output': [
                {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': '<b>unverified</b>'}], 'encrypted_content': 'TOKEN_SENTINEL'},
                {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'research'}]},
            ],
        }
        transport = Mock()

        def stream(*args):
            yield b'data: ' + json.dumps({'type': 'response.completed', 'response': response}).encode() + b'\n\n'

        transport.stream.side_effect = stream
        result = runtime.chatgpt_reply(request, None, transport=transport, reference_factory=lambda *args: Mock())
        self.assertEqual(result, {'ok': True, 'text': 'research', 'thinking': '<b>unverified</b>'})
        self.panel.worker.poll.return_value = result
        self.panel.poll()
        self.assertEqual(self.panel.thinking.body.toPlainText(), result['thinking'])
        transport.reset_mock()
        self.assertEqual(runtime.chatgpt_reply({**request, 'consent': False}, None, transport=transport), REFUSAL)
        transport.stream.assert_not_called()
        assert_no_protected_values(self, widget_text(self.panel))

    def test_rows_and_code_widgets_keep_only_newest_fixed_count(self):
        timeline = ToolTimeline(clock=lambda: 1)
        self.addCleanup(timeline.deleteLater)
        for index in range(MAX_ROWS + 5):
            timeline.call(self.dispatcher, 'list_saved_results', json.dumps({'limit': index % 50 + 1}))
        self.assertEqual(len(timeline.rows), MAX_ROWS)
        self.assertEqual(len(timeline.findChildren(TextFold)), MAX_ROWS)
        self.assertIn('"limit": 6', timeline.rows[0].findChild(QLabel).text())
        self.assertEqual(timeline.layout().count(), MAX_ROWS + 1)
        for index in range(MAX_ROWS + 2):
            self.panel.reply('```text\n' + str(index) + '\n```')
        self.assertEqual(len(self.panel.code_folds), MAX_ROWS)
        self.assertEqual(self.panel.code_folds[0].body.toPlainText(), '2\n')
        self.assertEqual(len(self.panel._transcript_entries), MAX_ROWS)

    def test_all_actual_tools_and_timeline_exclude_protected_fixtures_negative_control(self):
        for name in self.dispatcher.declarations:
            arguments = {} if name.startswith('get_paper_') or name == 'list_saved_results' else {'result_id': self.fixture.storage.identity}
            if name in ('compare_results', 'compare_result_manifests'):
                arguments['other_id'] = self.fixture.storage.other
            self.panel.input.setText('/tool ' + name + ' ' + json.dumps(arguments))
            self.panel.submit()
        assert_no_protected_values(self, widget_text(self.panel))
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, widget_text(self.panel) + ' OOS_SENTINEL')
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, widget_text(self.panel) + ' TOKEN_SENTINEL')

    def test_new_module_has_no_dynamic_execution_operator_or_persistence(self):
        source = (ROOT / 'desktop_app/features/assistant/assistant_details.py').read_text(encoding='utf-8')
        calls = [node.func for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
        self.assertFalse({node.id for node in calls if isinstance(node, ast.Name)} & {'eval', 'exec', 'compile', 'open'})
        self.assertFalse(
            {node.attr for node in calls if isinstance(node, ast.Attribute)}
            & {
                'save',
                'run_backtest',
                'run_campaign',
                'run_walk_forward',
                '_reserve',
                'write_text',
                'write_bytes',
                'start',
            }
        )


if __name__ == '__main__':
    unittest.main()
