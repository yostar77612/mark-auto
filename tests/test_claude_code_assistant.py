"""The assistant's Claude Code source: locked-down headless call, strict request/response, panel wiring."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from desktop_app import claude_code_composition as composition
from desktop_app.features.assistant import worker as adapter
from desktop_app.features.assistant.assistant import AssistantPanel
from desktop_app.strings.catalog import ui_text
from quantlab.agent_read_tools import ReadContext
from quantlab.assistant.adapters.claude_code import reply as claude
from quantlab.assistant.ports import reply as ports
from quantlab.assistant_chat import ChatDispatcher
from tests.test_agent_harness_d1 import REFUSAL

REQUEST = {'consent': True, 'prompt': '請解釋最大回落', 'provider': 'claude_code', 'model': 'haiku'}


def completed(result='好的', **changes):
    body = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': result}
    body.update(changes)
    return SimpleNamespace(returncode=0, stdout=json.dumps(body, ensure_ascii=False), stderr='')


class Runner:
    """Records the one process launch and what the working directory looked like at that moment."""

    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response or completed(), error, []

    def __call__(self, args, **kwargs):
        kwargs['cwd_listing'] = sorted(os.listdir(kwargs['cwd'])) if Path(kwargs['cwd']).is_dir() else None
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def reply(request=REQUEST, runner=None, which=lambda name: __file__):
    runner = runner or Runner()
    return claude.claude_code_reply(request, runner=runner, which=which), runner


class ClaudeCodeReplyTests(unittest.TestCase):
    def test_the_process_is_locked_down_and_the_prompt_never_touches_the_command_line(self):
        result, runner = reply()
        self.assertEqual(result, {'ok': True, 'text': '好的'})
        ((args, kwargs),) = runner.calls
        self.assertEqual(args[1:3], ['-p', '--output-format'])
        self.assertEqual(args[args.index('--tools') + 1], '')  # not a single tool
        for flag in ('--no-session-persistence', '--disable-slash-commands'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('--setting-sources') + 1], 'project')
        self.assertEqual(args[args.index('--model') + 1], 'haiku')
        self.assertNotIn(REQUEST['prompt'], ' '.join(args))
        self.assertEqual(kwargs['input'], REQUEST['prompt'])
        self.assertIs(kwargs['shell'], False)
        self.assertEqual(kwargs['timeout'], claude.TIMEOUT_SECONDS)
        self.assertEqual(kwargs['cwd_listing'], [])  # an empty private directory: nothing to read
        self.assertFalse(Path(kwargs['cwd']).exists())  # removed afterwards

    def test_every_model_alias_is_accepted_and_others_are_not(self):
        for alias in ('haiku', 'sonnet', 'opus'):
            self.assertTrue(reply({**REQUEST, 'model': alias})[0]['ok'])
        for model in ('gpt-5', 'claude-fable-5-1', '--help', ''):
            result, runner = reply({**REQUEST, 'model': model})
            self.assertEqual((result, runner.calls), (REFUSAL, []))

    def test_malformed_requests_never_start_a_process(self):
        bad = (
            {**REQUEST, 'consent': False},
            {**REQUEST, 'provider': 'chatgpt'},
            {**REQUEST, 'prompt': ''},
            {**REQUEST, 'prompt': 'x' * 4097},
            {**REQUEST, 'extra': 1},
            {k: v for k, v in REQUEST.items() if k != 'model'},
            ['not', 'a', 'dict'],
        )
        for request in bad:
            with self.subTest(str(request)[:40]):
                result, runner = reply(request)
                self.assertEqual((result, runner.calls), (REFUSAL, []))

    def test_missing_claude_code_is_reported_specifically_without_running_anything(self):
        result, runner = reply(which=lambda name: None)
        self.assertEqual((result, runner.calls), (claude.UNAVAILABLE, []))

    def test_unexpected_or_failed_output_is_refused_without_leaking_details(self):
        cases = {
            'not json': SimpleNamespace(returncode=0, stdout='boom', stderr=''),
            'is_error': completed(is_error=True),
            'not success': completed(subtype='error_max_turns'),
            'empty': completed('   '),
            'too long': completed('字' * 3000),
            'result not text': completed(result=['x']),
            'failed exit, no output': SimpleNamespace(returncode=1, stdout='', stderr='secret path C:/x'),
        }
        for name, response in cases.items():
            with self.subTest(name):
                self.assertEqual(reply(runner=Runner(response))[0], REFUSAL)

    def test_a_signed_out_claude_code_asks_the_user_to_log_in(self):
        signed_out = completed('Not logged in · Please run /login', is_error=True)
        self.assertEqual(reply(runner=Runner(signed_out))[0], claude.LOGIN_REQUIRED)

    def test_timeouts_and_launch_failures_are_refused(self):
        for error in (subprocess.TimeoutExpired('claude', 90), OSError('no such file')):
            self.assertEqual(reply(runner=Runner(error=error))[0], REFUSAL)

    @unittest.skipUnless(os.environ.get('MARKAUTO_REAL_CLAUDE') == '1', 'uses the real, signed-in Claude Code')
    def test_real_claude_code_answers_one_question(self):
        result = claude.claude_code_reply({**REQUEST, 'prompt': '只回答一個字：好'})
        self.assertTrue(result['ok'], result)


class ClaudeCodeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(ports._providers.clear)
        ports._providers.clear()

    def start(self, request):
        process = adapter.ReplyProcess(None, clock=lambda: 1000.0)
        context = Mock()
        context.Pipe.return_value = (Mock(), Mock())
        context.Process.return_value = Mock(pid=None)  # nothing real is spawned or tracked
        with patch.object(adapter.mp, 'get_context', return_value=context), patch.object(adapter, '_WindowsProcessTree'):
            process.start(request)
        return process, context

    def test_the_composition_root_registers_the_provider_the_worker_then_uses(self):
        composition.configure()
        self.assertEqual(ports.reply_provider('claude_code'), (composition.claude_reply_worker, composition.DEADLINE_SECONDS))
        process, context = self.start(REQUEST)
        self.assertIs(context.Process.call_args.kwargs['target'], composition.claude_reply_worker)
        self.assertEqual(process.deadline, 1000.0 + 100)
        process.cancel()

    def test_the_chatgpt_route_keeps_its_own_entry_point_and_deadline(self):
        composition.configure()
        process, context = self.start({'consent': True, 'prompt': 'x'})
        self.assertIs(context.Process.call_args.kwargs['target'], adapter._worker)
        self.assertEqual(process.deadline, 1000.0 + 30)
        process.cancel()

    def test_an_unconfigured_provider_never_spawns_anything(self):
        process = adapter.ReplyProcess(None)
        with patch.object(adapter.mp, 'get_context') as get_context, self.assertRaises(ValueError):
            process.start(REQUEST)
        get_context.assert_not_called()
        self.assertFalse(process.active)

    def test_the_child_entry_point_sends_exactly_the_adapter_result(self):
        sender, gate = Mock(), Mock()
        gate.wait.return_value = True
        with patch.object(composition, 'claude_code_reply', return_value={'ok': True, 'text': 'claude'}) as code:
            composition.claude_reply_worker(sender, gate, REQUEST, 'bootstrap')
        code.assert_called_once_with(REQUEST)
        self.assertEqual(json.loads(sender.send_bytes.call_args[0][0]), {'ok': True, 'text': 'claude'})
        sender.close.assert_called_once()

    def test_the_child_entry_point_refuses_when_the_adapter_raises_or_the_gate_never_opens(self):
        sender, gate = Mock(), Mock()
        gate.wait.return_value = True
        with patch.object(composition, 'claude_code_reply', side_effect=RuntimeError('secret detail')):
            composition.claude_reply_worker(sender, gate, REQUEST, None)
        self.assertEqual(json.loads(sender.send_bytes.call_args[0][0]), REFUSAL)
        silent, closed = Mock(), Mock()
        closed.wait.return_value = False
        composition.claude_reply_worker(silent, closed, REQUEST, None)
        silent.send_bytes.assert_not_called()
        silent.close.assert_called_once()


class ClaudeCodePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worker = SimpleNamespace(active=False, cancel=Mock(), start=Mock(), poll=Mock(return_value=None))
        host = SimpleNamespace(chatgpt_controller=SimpleNamespace(models=(), model_labels=()))  # no ChatGPT connection at all
        self.panel = AssistantPanel(host, dispatcher=ChatDispatcher(ReadContext(Path(self.temp.name))), worker=self.worker, consent=lambda: True)
        self.addCleanup(self.panel.deleteLater)
        self.claude_index = self.panel.mode.findData('claude_code')

    def test_it_is_a_third_source_after_the_existing_two(self):
        self.assertEqual([self.panel.mode.itemData(i) for i in range(self.panel.mode.count())], ['fixture', 'chatgpt', 'claude_code'])

    def test_it_works_without_any_chatgpt_connection_and_shows_only_its_own_model_choice(self):
        self.panel.mode.setCurrentIndex(self.panel.mode.findData('chatgpt'))
        self.assertFalse(self.panel.send.isEnabled())  # ChatGPT needs a discovered model
        self.assertTrue(self.panel.models.model.isVisibleTo(self.panel))
        self.panel.mode.setCurrentIndex(self.claude_index)
        self.assertTrue(self.panel.send.isEnabled())
        self.assertTrue(self.panel.claude_model.isVisibleTo(self.panel))
        self.assertFalse(self.panel.models.model.isVisibleTo(self.panel))
        self.assertEqual([self.panel.claude_model.itemData(i) for i in range(3)], ['haiku', 'sonnet', 'opus'])

    def test_submit_sends_one_exact_request_with_no_chatgpt_fields(self):
        self.panel.mode.setCurrentIndex(self.claude_index)
        self.panel.claude_model.setCurrentIndex(1)
        self.panel.input.setText('解釋夏普值')
        self.panel.submit()
        self.worker.start.assert_called_once_with({'consent': True, 'prompt': '解釋夏普值', 'provider': 'claude_code', 'model': 'sonnet'})

    def test_declining_consent_sends_nothing_and_the_dialog_names_claude_code(self):
        self.panel.mode.setCurrentIndex(self.claude_index)
        self.panel.ask_consent = Mock(return_value=False)
        self.panel.input.setText('hello')
        self.panel.submit()
        self.worker.start.assert_not_called()
        self.assertEqual(self.panel.transcript.toPlainText(), '')
        with patch('desktop_app.features.assistant.assistant.QMessageBox.question') as question:
            question.return_value = 0
            self.panel._consent()
        self.assertEqual(question.call_args[0][1:3], (ui_text('assistant.claude_consent_title'), ui_text('assistant.claude_consent_body')))

    def test_answers_and_specific_errors_are_labelled_as_claude_code(self):
        self.panel.mode.setCurrentIndex(self.claude_index)
        for result, shown in (
            ({'ok': True, 'text': '最大回落是…'}, '最大回落是…'),
            ({'ok': False, 'code': 'claude_unavailable'}, ui_text('assistant.claude_unavailable')),
            ({'ok': False, 'code': 'claude_login_required'}, ui_text('assistant.claude_login_required')),
        ):
            with self.subTest(shown):
                self.panel.input.setText('q')
                self.panel.submit()
                self.worker.poll.return_value = result
                self.panel.poll()
                transcript = self.panel.transcript.toPlainText()
                self.assertIn(ui_text('assistant.claude_code') + '\n' + shown, transcript)
        self.assertEqual(transcript.count(ui_text('assistant.disclaimer')), 3)
        self.assertNotIn(ui_text('assistant.chatgpt'), transcript)


if __name__ == '__main__':
    unittest.main()
