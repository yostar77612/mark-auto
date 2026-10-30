"""Cheap in-process worker/UI diagnostics; no subprocesses, disk or real data."""

from contextlib import nullcontext
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktop_app.components.job_messages import stage_error_message
from quantlab import desktop_runtime as runtime
from quantlab.job_stages import JOB_STAGES, normalize_stage, stage_from_traceback


class JobStageTests(unittest.TestCase):
    def test_every_code_has_a_distinct_catalog_message(self):
        messages = [stage_error_message(stage) for stage in JOB_STAGES]
        self.assertEqual(len(set(messages)), len(JOB_STAGES))
        self.assertTrue(all(messages))
        for value in ('private-token C:/private/path', None, [], {}, 9):
            self.assertEqual(normalize_stage(value), 'unknown')
            self.assertEqual(stage_error_message(value), stage_error_message('unknown'))

    def run_worker(self, executor, *, guard=None):
        packets = []
        sender = SimpleNamespace(send_bytes=lambda raw: packets.append(json.loads(raw)), close=Mock())
        with (
            patch.object(runtime.sys, 'platform', 'win32'),
            patch.object(runtime, '_worker_recovery_guard', side_effect=guard or (lambda *args: nullcontext())),
            patch.object(runtime, '_worker_operation_executor', return_value=executor),
        ):
            runtime._job_worker(sender, SimpleNamespace(wait=lambda seconds: True), 'ui_campaign', {}, '.', None, 'offline-job')
        sender.close.assert_called_once_with()
        return packets

    def test_worker_emits_only_allowed_stages_and_never_exception_text(self):
        for stage in (*sorted(JOB_STAGES), 'private-stage C:/secret'):

            def fail(*args, emit, **kwargs):
                emit('progress', stage=stage)
                raise ValueError('private-token C:/private/path')

            with self.subTest(stage=stage):
                packets = self.run_worker(fail)
                event = packets[-1]
                self.assertEqual(event['type'], 'error')
                self.assertEqual(event['stage'], normalize_stage(stage))
                self.assertEqual(event['error_type'], 'ValueError')
                self.assertNotIn('private', json.dumps(packets))

    def test_guard_and_unannotated_executor_have_coarse_stages(self):
        def fail(*args, **kwargs):
            raise RuntimeError('private-token')

        self.assertEqual(self.run_worker(fail)[-1]['stage'], 'run_operation')
        self.assertEqual(self.run_worker(Mock(), guard=fail)[-1]['stage'], 'prepare_operation')

    def test_serialization_failure_is_write_result(self):
        packets = self.run_worker(lambda *args, **kwargs: {'bad': object()})
        self.assertEqual(packets[-1]['type'], 'error')
        self.assertEqual(packets[-1]['stage'], 'write_result')

    def test_traceback_frames_map_to_stages_and_innermost_wins(self):
        def named(name, inner=None):
            namespace = {}
            body = 'def %s(*args, **kwargs):\n    %s\n' % (name, 'return inner()' if inner else "raise ValueError('private-token C:/private')")
            exec(body, {'inner': inner}, namespace)
            return namespace[name]

        for frame, stage in (
            ('_dataset', 'load_data'),
            ('config_from_json', 'build_candidates'),
            ('campaign_generator', 'build_candidates'),
            ('run_backtest', 'run_backtest'),
            ('run_campaign', 'run_campaign'),
            ('_json_bytes', 'write_result'),
        ):
            with self.subTest(frame=frame):
                packets = self.run_worker(lambda *a, _f=named(frame), **k: _f())
                self.assertEqual(packets[-1]['stage'], stage)
                self.assertNotIn('private', json.dumps(packets))
        nested = named('run_campaign', named('_dataset'))
        self.assertEqual(self.run_worker(lambda *a, **k: nested())[-1]['stage'], 'load_data')
        self.assertEqual(stage_from_traceback(None, 'private-token'), 'unknown')

    def test_ui_error_display_uses_stage_and_ignores_raw_event_text(self):
        from desktop_app.shell.main_window import MainWindow

        # Exercise the real polling branch using an in-memory host; no workspace.
        for stage in (*sorted(JOB_STAGES), 'private-token C:/private/path', None):
            event = {'type': 'error', 'stage': stage, 'message': 'private-token', 'error_type': 'C:/private/path'}
            host = SimpleNamespace(
                jobs=SimpleNamespace(poll=lambda: [event], active=True),
                _ui_job_id=None,
                job_feedback=SimpleNamespace(accept=Mock(return_value=True), campaign_code=None),
                automatic_backup_panel=SimpleNamespace(handle_job_event=Mock()),
                _walk_forward_event=lambda event: False,
                _analysis_event=lambda event: False,
                _chatgpt_event=lambda event: False,
                _subscription_campaign=False,
                last_operation='ui_campaign',
                record_event=Mock(),
                status=SimpleNamespace(clear=Mock(), setText=Mock()),
                notify_local=Mock(),
            )
            MainWindow.poll_jobs(host)
            host.notify_local.assert_called_once_with(stage_error_message(stage), error=True, completion=True)
            self.assertNotIn('private', host.notify_local.call_args.args[0])
