"""T16 fixed-code presentation and progress with in-memory workers only."""

from quantlab.research_core.adapters.workspace_store import AppPaths

from quantlab.research_core.adapters import job_worker

from desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

from contextlib import nullcontext
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import re
import unittest
from unittest.mock import Mock, patch
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from desktop_app.features.assistant.states import outcome_state, outcome_presentation, outcome_message, campaign_outcome
from desktop_app.features.assistant.connection import ConnectionController, ChatGPTConnectionPanel
from quantlab.assistant.application.connection_contracts import ConnectionEvent
from desktop_app.components.job_progress import JobProgress, JobFeedback
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.window import MainWindow
from quantlab import desktop_runtime as runtime
from quantlab.desktop_errors import ERROR_TABLE
from quantlab.job_stages import JOB_STAGES
from tests.test_t9_onboarding import sandbox_ui

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'private-token /secret/path ' + 'abcdef0123456789' * 4


# Fixed P0-05 labels legitimately name the product and input formats.
FIXED_TERMS = re.compile(r'ChatGPT|TLS|CSV|RPT|YYYY-MM-DD|YYYYMMDD|YYYYMM')


class FixedCodeTests(unittest.TestCase):
    def test_every_p0_error_is_total_and_never_echoes_input(self):
        states = {'success', 'auth_expired', 'quota_exhausted', 'generic_failure'}
        for code in (*ERROR_TABLE, 'completed', SECRET, None, [], {}, 42):
            with self.subTest(code=code):
                self.assertIn(outcome_state(code), states)
                title, body, action = outcome_presentation(code)
                self.assertTrue(title and body)
                self.assertEqual(action, 'reauthorize' if outcome_state(code) == 'auth_expired' else None)
                text = outcome_message(code)
                self.assertNotIn(SECRET, text)
                # Fixed P0-05 labels legitimately name the product and input formats.
                visible = FIXED_TERMS.sub('', text)
                self.assertNotRegex(visible, r'[A-Z_]{3,}|[a-f0-9]{16,}|private|/secret')
        self.assertEqual(outcome_state(SECRET), 'generic_failure')
        self.assertEqual(outcome_state('quota_paused'), 'quota_exhausted')
        self.assertEqual(outcome_state('credential_diagnosis'), 'auth_expired')
        self.assertEqual(outcome_state('completed'), 'success')

    def test_durable_receipts_classify_failed_success_packets(self):
        for code in ('quota_paused', 'credential_diagnosis', 'completed', SECRET):
            result = {'status': 'completed', 'provider_receipts': [{'status': code, 'raw': SECRET}]}
            self.assertEqual(outcome_state(campaign_outcome(result)), outcome_state(code))
        self.assertEqual(outcome_state(campaign_outcome({'status': 'blocked_provider_audit'})), 'generic_failure')
        self.assertEqual(outcome_state(campaign_outcome({'status': 'completed'})), 'generic_failure')
        self.assertEqual(outcome_state(campaign_outcome(None)), 'generic_failure')

    def test_worker_failure_metadata_uses_only_fixed_exception_code(self):
        class ProviderFailure(Exception):
            code = 'quota_paused'

        for exc, expected in ((ProviderFailure(SECRET), 'quota_paused'), (RuntimeError(SECRET), 'operation_failed')):
            packets = []
            sender = SimpleNamespace(send_bytes=lambda raw: packets.append(json.loads(raw)), close=Mock())
            with (
                patch.object(runtime.sys, 'platform', 'win32'),
                patch('quantlab.research_core.adapters.job_worker._worker_recovery_guard', return_value=nullcontext()),
                patch('quantlab.research_core.adapters.job_worker._worker_operation_executor', return_value=Mock(side_effect=exc)),
            ):
                job_worker._job_worker(sender, SimpleNamespace(wait=lambda seconds: True), 'ui_campaign', {}, '.', None, 'fake')
            self.assertEqual(packets[-1]['error_code'], expected)
            self.assertNotIn(SECRET, json.dumps(packets))
            sender.close.assert_called_once()

    def test_size_limits_and_python_311(self):
        paths = [
            ROOT / name for name in ('desktop_app/shell/main_window.py', 'desktop_app/features/assistant/states.py', 'desktop_app/components/job_progress.py')
        ]
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), feature_version=(3, 11))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 400)


class PresentationWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.network = patch('socket.socket', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def widget(self, cls, *args):
        widget = cls(*args)
        self.addCleanup(widget.deleteLater)
        return widget

    def host(self, operation):
        progress = self.widget(JobProgress, Mock())
        feedback = JobFeedback(progress)
        feedback.begin('fake')
        controller = ConnectionController()
        host = SimpleNamespace(
            jobs=SimpleNamespace(poll=Mock(return_value=[]), active=True),
            _ui_job_id='fake',
            job_progress=progress,
            job_feedback=feedback,
            automatic_backup_panel=SimpleNamespace(handle_job_event=Mock()),
            _walk_forward_event=lambda event: operation == 'ui_walk_forward_run',
            _analysis_event=lambda event: False,
            _chatgpt_event=lambda event: False,
            _subscription_campaign=False,
            _plan_launch=None,
            chatgpt_controller=controller,
            last_operation=operation,
            record_event=Mock(),
            status=self.widget(QLabel),
            notify_local=Mock(),
            views_page=SimpleNamespace(render_result=lambda event: event.get('result', {})),
            freeze_paper=Mock(),
            _safe=lambda call: call(),
        )
        return host

    def poll(self, host, *events):
        host.jobs.poll.return_value = list(events)
        _c_JobPresenter(host).poll_jobs()

    def test_all_stages_and_unknown_are_catalog_only(self):
        widget = self.widget(JobProgress, Mock())
        for stage in JOB_STAGES:
            widget.update_event({'stage': stage, 'message': SECRET})
            self.assertEqual(widget.stage.text(), ui_text('job.stage.' + stage))
        for stage in (SECRET, {}, [], None, 3):
            widget.update_event({'stage': stage})
            self.assertEqual(widget.stage.text(), ui_text('job.stage.unknown'))
            self.assertNotIn(SECRET, widget.stage.text())

    def test_real_window_mount_preserves_names_and_uses_shared_progress_for_all_jobs(self):
        with sandbox_ui(), tempfile.TemporaryDirectory(prefix='t16-host-') as temp:
            paths = AppPaths(Path(temp) / 'workspace').ensure()
            jobs = SimpleNamespace(active=False, poll=lambda: [], start=Mock(), close=Mock())
            window = MainWindow(paths, jobs, services=_c_create_ui_services(_c_create_operation_ports()))
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                actual = sorted({w.objectName() for w in [window, *window.findChildren(QWidget)] if w.objectName()})
                expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
                self.assertEqual(actual, expected)
                self.assertIs(window.progress, window.job_progress.bar)
                self.assertIs(window.cancel_button, window.job_progress.cancel_button)
                with patch('quantlab.analysis_recovery.require_operation'):
                    for operation in ('ui_backtest', 'ui_campaign', 'ui_walk_forward_run', 'ui_refresh'):
                        jobs.start.return_value = operation
                        self.assertEqual(window.start_job(operation, {}), operation)
                        self.assertTrue(window.cancel_button.isEnabled())
                        self.assertEqual(window.progress.maximum(), 0)
                        window.job_feedback.accept(window, {'job_id': operation, 'type': 'progress', 'stage': 'load_data', 'progress': 42})
                        self.assertEqual(window.progress.value(), 42)
                        window._busy(False)
                        self.assertFalse(window.cancel_button.isEnabled())
            finally:
                window.close()
                window.deleteLater()

    def test_all_four_jobs_switch_numeric_and_indeterminate_modes(self):
        for operation in ('ui_backtest', 'ui_campaign', 'ui_walk_forward_run', 'ui_refresh'):
            with self.subTest(operation=operation):
                host = self.host(operation)
                widget = host.job_progress
                self.assertTrue(widget.cancel_button.isEnabled())
                for value, expected in ((0, 0), (35.4, 35), (-7, 0), (130, 100), (10**400, 100)):
                    self.poll(host, {'job_id': 'fake', 'type': 'progress', 'stage': 'load_data', 'progress': value, 'message': SECRET})
                    self.assertEqual((widget.bar.minimum(), widget.bar.maximum(), widget.bar.value()), (0, 100, expected))
                for value in (None, '12', True, float('nan'), float('inf'), {}, []):
                    self.poll(host, {'type': 'progress', 'progress': value})
                    self.assertEqual((widget.bar.minimum(), widget.bar.maximum()), (0, 0))
                self.poll(host, {'type': 'progress', 'message': SECRET, 'stage': SECRET})
                self.assertEqual(widget.stage.text(), ui_text('job.stage.unknown'))
                if operation != 'ui_walk_forward_run':
                    self.assertEqual(host.status.text(), ui_text('job.stage.unknown'))
                self.assertFalse(host.notify_local.called)

    def test_each_job_notifies_once_and_cancel_after_complete_is_noop(self):
        for operation in ('ui_backtest', 'ui_campaign', 'ui_walk_forward_run', 'ui_refresh'):
            for terminal in ('result', 'error', 'cancelled'):
                with self.subTest(operation=operation, terminal=terminal):
                    host = self.host(operation)
                    event = {'job_id': 'fake', 'type': terminal, 'stage': 'run_operation', 'result': {}}
                    self.poll(host, event, event, {'type': 'cancelled'}, {'type': 'result', 'result': {}})
                    host.notify_local.assert_called_once()
                    self.assertFalse(host.job_progress.cancel_button.isEnabled())
                    if terminal == 'cancelled' and operation != 'ui_walk_forward_run':
                        host.freeze_paper.assert_called_once_with(ui_text('ui.poll_jobs.cancelled_title'))
                    else:
                        host.freeze_paper.assert_not_called()
                    host.freeze_paper.reset_mock()
                    _c_JobPresenter(host).cancel_job()
                    host.freeze_paper.assert_not_called()

    def test_double_cancel_uses_existing_freeze_path_and_waits_for_terminal(self):
        host = self.host('ui_backtest')
        host.job_progress.request_cancel(lambda: _c_JobPresenter(host).cancel_job())
        host.job_progress.request_cancel(lambda: _c_JobPresenter(host).cancel_job())
        host.freeze_paper.assert_called_once_with(ui_text('ui.cancel_and_recover.user_cancel'))
        self.assertEqual(host.status.text(), ui_text('job.cancel_notice'))
        self.assertFalse(host.job_progress.cancel_button.isEnabled())
        host.notify_local.assert_not_called()
        self.poll(host, {'type': 'cancelled'}, {'type': 'result', 'result': {}})
        host.notify_local.assert_called_once_with(ui_text('job.cancelled'), completion=True)
        host.job_feedback.begin('next')
        self.assertTrue(host.job_progress.cancel_button.isEnabled())
        self.assertTrue(host.job_feedback.accept(host, {'job_id': 'next', 'type': 'progress', 'progress': 51}))
        self.assertFalse(host.job_feedback.accept(host, {'job_id': 'fake', 'type': 'cancelled'}))
        self.assertEqual(host.job_progress.bar.value(), 51)

    def test_cancel_then_authoritative_finish_notifies_completion_once(self):
        host = self.host('ui_backtest')
        host.job_progress.request_cancel(lambda: _c_JobPresenter(host).cancel_job())
        host.notify_local.assert_not_called()
        self.poll(host, {'type': 'result', 'result': {}}, {'type': 'cancelled'}, {'type': 'result', 'result': {}})
        host.notify_local.assert_called_once()
        self.assertNotEqual(host.notify_local.call_args.args[0], ui_text('job.cancelled'))
        self.assertFalse(host.job_progress.cancel_button.isEnabled())

    def test_cancel_in_idle_primary_signin_gap_preserves_abandonment_path(self):
        host = self.host('ui_chatgpt_auth')
        host.jobs.active = False
        host.job_feedback.terminal = True
        host.chatgpt_panel = SimpleNamespace(primary_sign_in_pending=True)
        _c_JobPresenter(host).cancel_job()
        host.freeze_paper.assert_called_once_with(ui_text('ui.cancel_and_recover.user_cancel'))

    def test_fixed_import_progress_notice_is_preserved_beside_stage(self):
        host = self.host('ui_market_refresh')
        message = ui_text('ui.execute_ui_operation.importing_local_history')
        self.poll(host, {'type': 'progress', 'stage': 'load_data', 'message': message})
        self.assertEqual(host.status.text(), message)
        self.assertEqual(host.job_progress.stage.text(), ui_text('job.stage.load_data'))

    def test_campaign_result_and_failure_render_four_states_without_leaks(self):
        for code in ('completed', 'quota_paused', 'credential_diagnosis', SECRET):
            for kind in ('result', 'error'):
                if kind == 'error' and code == 'completed':
                    continue
                with self.subTest(code=code, kind=kind):
                    host = self.host('ui_campaign')
                    panel = self.widget(ChatGPTConnectionPanel, host.chatgpt_controller)
                    host._subscription_campaign = True
                    result = {'status': 'completed', 'provider_receipts': [{'status': code}]}
                    event = {'type': kind, 'result': result, 'error_code': code, 'message': SECRET}
                    self.poll(host, event)
                    self.assertEqual(host.chatgpt_controller.outcome, outcome_state(code))
                    self.assertEqual(panel.status.text(), outcome_message(code))
                    self.assertEqual(host.notify_local.call_args.args[0], outcome_message(code))
                    self.assertNotRegex(FIXED_TERMS.sub('', panel.status.text()), r'[A-Z_]{3,}|[a-f0-9]{16,}|private|/secret')
                    self.assertEqual(
                        panel.primary_sign_in.text(),
                        ui_text('outcome.auth_expired.action') if code == 'credential_diagnosis' else ui_text('chatgpt_ui.init.primary_sign_in'),
                    )

    def test_refresh_worker_results_all_p0_codes_and_reauthorization_action(self):
        ref = 'a' * 32
        controller = ConnectionController()
        controller.set_host_available(True)
        panel = self.widget(ChatGPTConnectionPanel, controller)
        for code in ERROR_TABLE:
            request = controller.request('refresh', ref, confirmed=True)
            controller.acknowledge_quiescence(request.request_id, joined=True)
            event = ConnectionEvent(request.request_id, 'error', 'unknown', error_code=code)
            self.assertTrue(controller.apply_event(event))
            self.assertEqual(controller.outcome, outcome_state(code))
            self.assertIn(outcome_message(code), panel.status.text())
            self.assertNotIn(code, panel.status.text())
            self.assertNotRegex(FIXED_TERMS.sub('', panel.status.text()), r'[A-Z_]{3,}|[a-f0-9]{16,}|private')
            controller.worker_joined(request.request_id, joined=True)
        request = controller.request('refresh', ref, confirmed=True)
        controller.acknowledge_quiescence(request.request_id, joined=True)
        controller.apply_event(ConnectionEvent(request.request_id, 'result', 'plan_ready', ((ref, 'plan_ready'),), ref))
        controller.worker_joined(request.request_id, joined=True)
        self.assertEqual(panel.status.text(), outcome_message('plan_ready'))
        controller.show_outcome('credential_diagnosis')
        self.assertFalse(panel.primary_sign_in.isHidden())
        with patch.object(panel, '_start_primary_sign_in') as sign_in:
            panel.primary_sign_in.click()
        sign_in.assert_called_once()
        panel.primary_sign_in.click()
        request = controller._request
        self.assertEqual(request.action, 'list')
        with patch('desktop_app.features.assistant.connection.QTimer.singleShot'):
            controller.apply_event(ConnectionEvent(request.request_id, 'result', 'plan_ready', ((ref, 'plan_ready'),), ref))
            controller.worker_joined(request.request_id, joined=True)
        panel._continue_primary(request.request_id)
        self.assertEqual(controller._request.action, 'begin')
        self.assertEqual(controller._request.registration, ref)
        self.assertTrue(controller._request.user_confirmed)

    def test_panel_local_provider_failure_never_uses_exception_prose(self):
        panel = self.widget(ChatGPTConnectionPanel)

        class Failure(Exception):
            code = 'credential_diagnosis'

        panel._safe(Mock(side_effect=Failure(SECRET)))
        self.assertEqual(panel.status.text(), outcome_message('credential_diagnosis'))
        rendered = '\n'.join(label.text() for label in panel.findChildren(QLabel))
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn('credential_diagnosis', rendered)
