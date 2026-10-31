"""Controlled timeout evidence and owned child cleanup; not native acceptance."""

import json
import errno
import select
import signal
import sqlite3
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from quantlab.research_core.application.job_manager import JobManager
from quantlab.desktop_runtime import RuntimeSafetyError

from tests.smoke_timeout_diagnostics import (
    WorkerTimings,
    diagnosed_smoke_worker,
    SmokeOutputCapture,
    instrument_walk_forward,
    output_summary,
    run_smoke_process,
)
from tests.test_desktop_smoke_terminal import process_can_run


@contextmanager
def process_exits_during_proc_read():
    """Exercise real Linux ESRCH between opening and reading a proc stat file."""
    victim = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    folder = Path('/proc', str(victim.pid))
    original_read, original_iterdir = Path.read_text, Path.iterdir
    observed = []

    def read(path, *args, **kwargs):
        if path == folder / 'stat' and not observed:
            with path.open() as stream:
                victim.kill()
                victim.wait(timeout=6)
                try:
                    return stream.read()
                except ProcessLookupError as error:
                    observed.append(error.errno)
                    raise
        return original_read(path, *args, **kwargs)

    def iterdir(path):
        if path == Path('/proc') and not observed:
            return iter([folder, *(entry for entry in original_iterdir(path) if entry != folder)])
        return original_iterdir(path)

    try:
        with patch.object(Path, 'read_text', read), patch.object(Path, 'iterdir', iterdir):
            yield victim.pid, observed
    finally:
        if victim.poll() is None:
            victim.kill()
        victim.wait(timeout=6)


class SmokeTimeoutDiagnosticTests(unittest.TestCase):
    def test_timeout_preserves_only_sanitized_evidence_and_stops_real_subtree(self):
        self.assert_timeout_cleanup()

    def assert_timeout_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, pids, writes = (root / name for name in ('report.json', 'pids.json', 'writes.jsonl'))
            worker_code = '''import json, subprocess, sys, time
from pathlib import Path
from quantlab.research_core.adapters.job_process import _WindowsProcessTree
grandchild = subprocess.Popen([sys.executable, '-c', 'import sys,time; sys.stdin.read(1); time.sleep(60)'], stdin=subprocess.PIPE, text=True)
inner_tree = _WindowsProcessTree(grandchild.pid) if sys.platform == 'win32' else None
grandchild.stdin.write('x'); grandchild.stdin.flush(); grandchild.stdin.close()
target = Path(sys.argv[1]); staging = target.with_suffix('.tmp')
staging.write_text(json.dumps(grandchild.pid), encoding='utf-8'); staging.replace(target)
time.sleep(60)
'''
            code = '''import json, os, subprocess, sys, time
from pathlib import Path
nested_pid = Path(sys.argv[2]).with_name('grandchild.json')
child = subprocess.Popen([sys.executable, '-c', sys.argv[4], str(nested_pid)], start_new_session=sys.platform != 'win32')
Path(sys.argv[2]).write_text(json.dumps([child.pid]), encoding='utf-8')
while not nested_pid.exists(): time.sleep(.01)
Path(sys.argv[2]).write_text(json.dumps([child.pid, json.loads(nested_pid.read_text())]), encoding='utf-8')
value = {'status': 'failed', 'worker_cleanup': {'verified': False}, 'secret': 'DO_NOT_RETAIN', 'data_dir': 'private/user/root'}
Path(sys.argv[1]).write_text(json.dumps(value), encoding='utf-8')
Path(sys.argv[3]).write_text(json.dumps(value)+'\\n', encoding='utf-8')
print('DO_NOT_RETAIN', flush=True)
print('SMOKE_DIAGNOSTIC ' + json.dumps({'stage':'started', 'operation':'ui_campaign', 'pid':child.pid, 'secret':'DO_NOT_RETAIN'}), file=sys.stderr, flush=True)
time.sleep(60)
'''
            with self.assertRaisesRegex(AssertionError, 'unchanged deadline') as error:
                run_smoke_process(
                    [sys.executable, '-c', code, str(report), str(pids), str(writes), worker_code],
                    cwd=root,
                    env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                    report=report,
                    pidfile=pids,
                    writes=writes,
                    process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts',
                    timeout=5,
                )
            artifacts = list((root / 'artifacts').glob('smoke-timeout-*.json'))
            self.assertEqual(len(artifacts), 1)
            raw = artifacts[0].read_text(encoding='utf-8')
            self.assertNotIn('DO_NOT_RETAIN', raw + str(error.exception))
            self.assertNotIn('private/user/root', raw)
            value = json.loads(raw)
            self.assertEqual(value['timeout_seconds'], 5)
            self.assertTrue(value['cleanup_verified'], json.dumps(value, sort_keys=True))
            self.assertEqual(value['report']['status'], 'failed')
            self.assertEqual(len(value['report_writes']), 1)
            self.assertEqual(len(value['worker_alive_before']), 2)
            self.assertTrue(all(value['worker_alive_before'].values()))
            self.assertFalse(any(value['worker_alive_after'].values()))
            if sys.platform.startswith('linux'):
                self.assertEqual(set(value['worker_linux_state_before']), set(value['worker_alive_before']))
                self.assertEqual(set(value['worker_linux_state_after']), set(value['worker_alive_after']))
                self.assertTrue(set(value['worker_linux_state_after'].values()) <= {'Z', 'X', 'x', '-'})
            self.assertEqual(value['stderr']['events'][0]['operation'], 'ui_campaign')
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pids.read_text())))

    def test_normal_exit_cannot_hide_a_live_worker_and_still_cleans_it_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pids = root / 'pids.json'
            code = """import json, subprocess, sys
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=sys.platform != 'win32')
Path(sys.argv[1]).write_text(json.dumps([child.pid]), encoding='utf-8')
"""
            with self.assertRaisesRegex(AssertionError, 'live recorded worker'):
                run_smoke_process(
                    [sys.executable, '-c', code, str(pids)],
                    cwd=root,
                    env=os.environ.copy(),
                    report=root / 'report',
                    pidfile=pids,
                    writes=root / 'writes',
                    process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts',
                    timeout=2,
                )
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pids.read_text())))

    def test_unrecorded_inherited_writer_cannot_turn_launcher_exit_into_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'descendant.json'
            code = """import json, subprocess, sys
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps(child.pid))
print('SMOKE_DIAGNOSTIC {"stage":"main_return","status":0}', file=sys.stderr, flush=True)
"""
            with self.assertRaisesRegex(AssertionError, 'unchanged deadline'):
                run_smoke_process(
                    [sys.executable, '-c', code, str(marker)],
                    cwd=root,
                    env=os.environ.copy(),
                    report=root / 'report',
                    pidfile=root / 'missing-pids',
                    writes=root / 'writes',
                    process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts',
                    timeout=1,
                )
            value = json.loads(next((root / 'artifacts').glob('smoke-timeout-*.json')).read_text())
            self.assertEqual(value['worker_alive_before'], {})
            self.assertEqual(value['stderr']['events'], [{'stage': 'main_return', 'status': 0}])
            self.assertTrue(value['cleanup_verified'])
            self.assertFalse(process_can_run(json.loads(marker.read_text())))

    def test_cleanup_communicate_timeout_retains_flushed_sanitized_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = SmokeOutputCapture.communicate
            captures, calls = [], []

            def communicate(capture, *args, **kwargs):
                calls.append(None)
                captures.append(capture)
                if len(calls) == 2:
                    raise subprocess.TimeoutExpired(capture.process.args, kwargs['timeout'])
                return original(capture, *args, **kwargs)

            code = """import sys, time
print('DO_NOT_RETAIN', flush=True)
print('SMOKE_DIAGNOSTIC {"stage":"started","operation":"ui_walk_forward_run","secret":"DO_NOT_RETAIN"}', file=sys.stderr, flush=True)
time.sleep(60)
"""
            with patch.object(SmokeOutputCapture, 'communicate', communicate):
                with self.assertRaisesRegex(AssertionError, 'unchanged deadline') as error:
                    run_smoke_process(
                        [sys.executable, '-c', code],
                        cwd=root,
                        env=os.environ.copy(),
                        report=root / 'report',
                        pidfile=root / 'pids',
                        writes=root / 'writes',
                        process_can_run=process_can_run,
                        artifact_dir=root / 'artifacts',
                        timeout=1,
                    )
            raw = next((root / 'artifacts').glob('smoke-timeout-*.json')).read_text()
            value = json.loads(raw)
            self.assertEqual(len(calls), 2)
            self.assertEqual(value['cleanup_error_type'], 'TimeoutExpired')
            self.assertFalse(value['cleanup_verified'])
            self.assertGreater(value['stdout']['characters'], 0)
            self.assertEqual(value['stderr']['events'], [{'stage': 'started', 'operation': 'ui_walk_forward_run'}])
            self.assertFalse(value['stderr_truncated'])
            self.assertNotIn('DO_NOT_RETAIN', raw + str(error.exception))
            for thread in captures[0].threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())

    def test_incremental_capture_bounds_memory_and_keeps_complete_tail_lines(self):
        code = r"""import sys
sys.stderr.write('x' * 4096 + '\n')
sys.stderr.write('SMOKE_DIAGNOSTIC {"stage":"cleanup_start"}\n')
sys.stderr.flush()
"""
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with patch.object(SmokeOutputCapture, 'LIMIT', 128):
                capture = SmokeOutputCapture(process)
                stdout, stderr = capture.communicate('x', timeout=5)
            self.assertEqual(stdout, '')
            self.assertTrue(capture.snapshot('stderr')[1])
            self.assertLessEqual(len(capture.buffers['stderr']), 128)
            self.assertEqual(output_summary(stderr)['events'], [{'stage': 'cleanup_start'}])
            self.assertTrue(all(not thread.is_alive() for thread in capture.threads))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=6)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_capture_cancellation_stops_readers_but_never_counts_as_eof(self):
        process = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            capture = SmokeOutputCapture(process)
            capture.close()
            self.assertTrue(all(not thread.is_alive() for thread in capture.threads))
            self.assertFalse(any(capture.eof.values()))
            with self.assertRaisesRegex(RuntimeError, 'before EOF'):
                capture.communicate(timeout=1)
            self.assertIsNone(process.poll(), 'Reader cancellation must not claim or stop the live writer')
        finally:
            process.kill()
            process.wait(timeout=6)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_failed_tree_cleanup_stops_readers_without_claiming_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pids = root / 'pids'
            captures = []

            def factory(process):
                capture = SmokeOutputCapture(process)
                captures.append(capture)
                return capture

            code = """import json, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=sys.platform != 'win32')
Path(sys.argv[1]).write_text(json.dumps([child.pid]))
print('SMOKE_DIAGNOSTIC {"stage":"cleanup_start"}', file=sys.stderr, flush=True)
time.sleep(60)
"""
            try:
                with (
                    patch('tests.smoke_timeout_diagnostics.SmokeOutputCapture', factory),
                    patch.object(JobManager, '_join_descendants', side_effect=RuntimeSafetyError('DO_NOT_RETAIN')),
                    patch('tests.smoke_timeout_diagnostics._WindowsProcessTree.stop_and_join', side_effect=RuntimeSafetyError('DO_NOT_RETAIN')),
                ):
                    with self.assertRaisesRegex(AssertionError, 'unchanged deadline'):
                        run_smoke_process(
                            [sys.executable, '-c', code, str(pids)],
                            cwd=root,
                            env=os.environ.copy(),
                            report=root / 'report',
                            pidfile=pids,
                            writes=root / 'writes',
                            process_can_run=process_can_run,
                            artifact_dir=root / 'artifacts',
                            timeout=1,
                        )
                value = json.loads(next((root / 'artifacts').glob('smoke-timeout-*.json')).read_text())
                self.assertFalse(value['cleanup_verified'])
                self.assertEqual(value['cleanup_error_type'], 'RuntimeSafetyError')
                self.assertTrue(all(not thread.is_alive() for thread in captures[0].threads))
                self.assertEqual(value['stderr']['events'], [{'stage': 'cleanup_start'}])
                self.assertNotIn('DO_NOT_RETAIN', json.dumps(value))
            finally:
                for pid in json.loads(pids.read_text()) if pids.exists() else []:
                    if process_can_run(pid):
                        os.kill(pid, signal.SIGTERM)

    def test_non_object_and_malformed_diagnostic_lines_are_ignored(self):
        value = output_summary('\n'.join('SMOKE_DIAGNOSTIC ' + text for text in ('[]', 'null', '1', '"text"', '{', '{"stage": [], "operation": {}}')))
        self.assertEqual(value['events'], [])

    def test_windows_admission_failure_does_not_release_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'application-ran'
            code = "from pathlib import Path; Path(__import__('sys').argv[1]).touch()"
            with (
                patch('tests.smoke_timeout_diagnostics.sys.platform', 'win32'),
                patch('tests.smoke_timeout_diagnostics._WindowsProcessTree', side_effect=RuntimeSafetyError('Isolation unavailable')),
                patch('tests.smoke_timeout_diagnostics.SmokeOutputCapture') as capture,
            ):
                with self.assertRaises(RuntimeSafetyError):
                    run_smoke_process(
                        [sys.executable, '-c', code, str(marker)],
                        cwd=root,
                        env=os.environ.copy(),
                        report=root / 'report',
                        pidfile=root / 'pids',
                        writes=root / 'writes',
                        process_can_run=process_can_run,
                        artifact_dir=root / 'artifacts',
                        timeout=2,
                    )
            self.assertFalse(marker.exists())
            capture.assert_not_called()

    def test_output_drops_raw_paths_messages_and_unrecognized_fields(self):
        result = output_summary('password=DO_NOT_RETAIN\n  File "/private/user/desktop.py", line 770 in main\n')
        self.assertEqual(result['stack_frames'], [{'module': 'desktop.py', 'line': 770, 'function': 'main'}])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))

    def test_terminal_join_phases_retain_only_allowlisted_metadata(self):
        stages = ('join_start', 'join_end', 'join_error', 'poll_error', 'report_write')
        lines = [
            dict(
                stage=stage,
                operation='ui_walk_forward_run',
                pid=123,
                elapsed_ms=17,
                message='DO_NOT_RETAIN',
                path='/private/user/root',
                exception='private exception join failure',
            )
            for stage in stages
        ]
        lines.append(dict(stage='/private/unknown-stage', message='DO_NOT_RETAIN'))
        result = output_summary('\n'.join('SMOKE_DIAGNOSTIC ' + json.dumps(row) for row in lines))
        self.assertEqual(result['events'], [dict(stage=stage, operation='ui_walk_forward_run', pid=123, elapsed_ms=17) for stage in stages])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))
        self.assertNotIn('exception', json.dumps(result))

    def test_walk_forward_terminal_uses_original_gate_and_owned_capture(self):
        # Wiring only. Stop before launch rather than fabricate smoke success.
        from tests.test_desktop_walk_forward_terminal import TerminalSmokeProcessTests

        case = TerminalSmokeProcessTests(methodName='runTest')
        with patch('tests.test_desktop_walk_forward_terminal.run_smoke_process', side_effect=RuntimeError('wiring only')) as launch:
            with self.assertRaisesRegex(RuntimeError, 'wiring only'):
                case.smoke('# injected fixture marker', retained=True, cleanup_verified=False)
        args, kwargs = launch.call_args
        self.assertEqual(kwargs['timeout'], 40)
        self.assertEqual(kwargs['artifact_dir'], kwargs['cwd'] / 'dist/validation')
        self.assertIs(kwargs['process_can_run'], process_can_run)
        command = args[0]
        self.assertEqual(command[:2], [sys.executable, '-c'])
        self.assertEqual(command[3:], [str(kwargs[key]) for key in ('report', 'pidfile', 'writes')])
        code = command[2]
        compile(code, '<synthetic terminal smoke>', 'exec')
        self.assertIn('job_worker._job_worker = diagnosed_smoke_worker', code)
        self.assertIn('faulthandler.dump_traceback_later(35)', code)
        self.assertIn('faulthandler.cancel_dump_traceback_later()', code)
        self.assertLess(code.index('JobManager._join_descendants = tracked_join'), code.index('# injected fixture marker'))
        self.assertNotIn('operation.startswith', code)  # Every launched PID is recorded.
        self.assertEqual(kwargs['env']['QT_QPA_PLATFORM'], 'offscreen')

    def test_post_join_injected_failure_cannot_grant_original_owner_proof(self):
        # Protocol test, not native Windows or smoke acceptance. Match the real
        # terminal injection: stop succeeds, then its proof operation raises.
        from desktop import _close_smoke_worker
        from tests.test_desktop_walk_forward_runtime import WalkForwardRuntimeTests, REFERENCE

        fixture = WalkForwardRuntimeTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job_id = fixture.start_fake()
        owner = fixture.manager._walk_forward_owner_path(REFERENCE)
        owner_bytes = owner.read_bytes()
        fixture.frame(result={'reference': REFERENCE, 'status': 'completed'})
        fixture.alive = False
        original = JobManager._join_descendants

        def unverified(manager, pid):
            original(manager, pid)
            raise RuntimeSafetyError('private exception join failure')

        with patch.object(JobManager, '_join_descendants', unverified):
            with self.assertRaises(RuntimeSafetyError):
                fixture.manager.poll()
            self.assertEqual(fixture.tree.stop_and_join.call_count, 1)
            for _ in range(2):  # Callback failure cleanup, then final cleanup.
                self.assertEqual(_close_smoke_worker(fixture.manager), {'verified': False, 'error_type': 'RuntimeSafetyError'})
                self.assertTrue(fixture.manager.active)
                self.assertFalse(fixture.manager._tree_quiesced)
                self.assertIsNone(fixture.manager._quiesced_walk_forward)
                self.assertEqual(owner.read_bytes(), owner_bytes)
                fixture.process.close.assert_not_called()
                fixture.tree.close.assert_not_called()
            self.assertEqual(fixture.tree.stop_and_join.call_count, 5)
        self.assertEqual(_close_smoke_worker(fixture.manager), {'verified': True, 'error_type': None})
        self.assertEqual(fixture.manager._quiesced_walk_forward, (job_id, REFERENCE))


class WindowsSmokeWorkerWaitTests(unittest.TestCase):
    """Owned-handle completion protocol; no PID-based termination or gate changes."""

    def kernel(self, *, member=True, child_created=20, waits=(0,)):
        import ctypes
        from ctypes import wintypes as w
        from unittest.mock import Mock

        kernel = SimpleNamespace(
            OpenProcess=Mock(return_value=200),
            CloseHandle=Mock(),
            IsProcessInJob=Mock(),
            GetProcessTimes=Mock(),
            WaitForSingleObject=Mock(side_effect=list(waits)),
        )

        def belongs(process, job, result):
            ctypes.cast(result, ctypes.POINTER(w.BOOL)).contents.value = member
            return True

        def times(handle, created, exited, user, system):
            value = ctypes.cast(created, ctypes.POINTER(w.FILETIME)).contents
            value.dwHighDateTime = 0
            value.dwLowDateTime = 10 if handle == 100 else child_created
            return True

        kernel.IsProcessInJob.side_effect = belongs
        kernel.GetProcessTimes.side_effect = times
        return kernel

    def test_retained_member_is_waited_and_closed_using_remaining_reserve(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel()
        workers = _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        try:
            with patch('tests.smoke_timeout_diagnostics.time.monotonic', return_value=103):
                workers.wait(106)
            kernel.OpenProcess.assert_called_once_with(0x1000 | 0x100000, False, 123)
            kernel.IsProcessInJob.assert_called_once()
            kernel.WaitForSingleObject.assert_called_once_with(200, 3000)
            self.assertFalse(hasattr(kernel, 'TerminateProcess'))
        finally:
            workers.close()
        kernel.CloseHandle.assert_called_once_with(200)

    def test_unrelated_or_older_process_identity_is_refused_without_termination(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        for member, created in ((False, 20), (True, 9)):
            with self.subTest(member=member, created=created):
                kernel = self.kernel(member=member, child_created=created)
                with self.assertRaisesRegex(RuntimeSafetyError, 'ownership is not proven'):
                    _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
                kernel.CloseHandle.assert_called_once_with(200)
                kernel.WaitForSingleObject.assert_not_called()

    def test_inaccessible_recorded_process_is_not_adopted_as_exited(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel()
        kernel.OpenProcess.return_value = None
        with self.assertRaisesRegex(RuntimeSafetyError, 'Cannot retain'):
            _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        kernel.IsProcessInJob.assert_not_called()
        kernel.WaitForSingleObject.assert_not_called()

    def test_exhausted_reserve_only_polls_and_cannot_extend_cleanup(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel(waits=(0x102,))
        workers = _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        try:
            with patch('tests.smoke_timeout_diagnostics.time.monotonic', return_value=107):
                with self.assertRaisesRegex(RuntimeSafetyError, 'unchanged cleanup deadline'):
                    workers.wait(106)
            kernel.WaitForSingleObject.assert_called_once_with(200, 0)
        finally:
            workers.close()

    def test_failed_native_wait_never_grants_completion(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel(waits=(0xFFFFFFFF,))
        workers = _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        try:
            with patch('tests.smoke_timeout_diagnostics.time.monotonic', return_value=103):
                with self.assertRaisesRegex(RuntimeSafetyError, 'Cannot verify'):
                    workers.wait(106)
        finally:
            workers.close()

    def test_null_zero_and_invalid_job_handles_fail_before_membership(self):
        import ctypes
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        for value in (None, 0, -1, ctypes.c_void_p(-1).value):
            with self.subTest(handle=value):
                kernel = self.kernel()
                with self.assertRaisesRegex(RuntimeSafetyError, 'valid private'):
                    _WindowsSmokeWorkers(SimpleNamespace(handle=value), SimpleNamespace(_handle=100), [123], kernel)
                kernel.OpenProcess.assert_not_called()
                kernel.IsProcessInJob.assert_not_called()

    def test_close_false_attempts_all_and_reports_only_safe_counts(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel()
        workers = _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        workers.handles = [200, 201, 202]
        kernel.CloseHandle.side_effect = [False, True, False]
        with self.assertRaisesRegex(RuntimeSafetyError, 'cleanup could not be verified') as failure:
            workers.close()
        self.assertEqual([call.args[0] for call in kernel.CloseHandle.call_args_list], [200, 201, 202])
        self.assertEqual(failure.exception.cleanup_failures, {'native_false': 2, 'raised_close': 0})
        self.assertEqual(workers.handles, [200, 202])

    def test_close_exception_attempts_remaining_handles_and_redacts_payload(self):
        from tests.smoke_timeout_diagnostics import _WindowsSmokeWorkers

        kernel = self.kernel()
        workers = _WindowsSmokeWorkers(SimpleNamespace(handle=300), SimpleNamespace(_handle=100), [123], kernel)
        workers.handles = [200, 201, 202]
        kernel.CloseHandle.side_effect = [RuntimeError('DO_NOT_RETAIN'), False, True]
        with self.assertRaisesRegex(RuntimeSafetyError, 'cleanup could not be verified') as failure:
            workers.close()
        self.assertEqual([call.args[0] for call in kernel.CloseHandle.call_args_list], [200, 201, 202])
        self.assertEqual(failure.exception.cleanup_failures, {'native_false': 1, 'raised_close': 1})
        self.assertNotIn('DO_NOT_RETAIN', str(failure.exception))
        self.assertEqual(workers.handles, [200, 201])

    def accounting_kernel(self, clock, *, metadata_step=0, terminate_step=0, query_step=0, wait_step=0):
        from unittest.mock import Mock

        kernel = self.kernel()
        kernel.TerminateJobObject = Mock()
        kernel.QueryInformationJobObject = Mock()
        original_times = kernel.GetProcessTimes.side_effect

        def times(*args):
            value = original_times(*args)
            clock[0] += metadata_step
            return value

        def terminate(*args):
            clock[0] += terminate_step
            return True

        def query(handle, kind, pointer, *args):
            pointer._obj.ActiveProcesses = 0
            clock[0] += query_step
            return True

        def wait(*args):
            clock[0] += wait_step
            return 0

        kernel.GetProcessTimes.side_effect = times
        kernel.TerminateJobObject.side_effect = terminate
        kernel.QueryInformationJobObject.side_effect = query
        kernel.WaitForSingleObject.side_effect = wait
        return kernel

    def test_entire_retention_job_and_wait_sequence_shares_one_six_second_deadline(self):
        from tests.smoke_timeout_diagnostics import _stop_windows_smoke_workers
        from quantlab.research_core.adapters.job_process import _WindowsProcessTree

        clock = [100.0]
        kernel = self.accounting_kernel(clock, metadata_step=2, terminate_step=0.5, query_step=0.5, wait_step=0.5)
        tree = object.__new__(_WindowsProcessTree)
        tree.handle = 300
        tree.kernel = kernel
        with (
            patch('tests.smoke_timeout_diagnostics.time.monotonic', side_effect=lambda: clock[0]),
            patch('quantlab.research_core.application.job_manager.time.monotonic', side_effect=lambda: clock[0]),
        ):
            _stop_windows_smoke_workers(tree, SimpleNamespace(_handle=100), [123], kernel=kernel)
        kernel.TerminateJobObject.assert_called_once_with(300, 1)
        self.assertEqual(kernel.QueryInformationJobObject.call_count, 1)
        milliseconds = kernel.WaitForSingleObject.call_args.args[1]
        self.assertLessEqual(milliseconds, 1000)
        self.assertGreaterEqual(milliseconds, 0)
        self.assertEqual(clock[0], 105.5)
        kernel.CloseHandle.assert_called_once_with(200)

    def test_slow_retention_still_drains_job_without_resetting_reserve(self):
        from tests.smoke_timeout_diagnostics import _stop_windows_smoke_workers
        from quantlab.research_core.adapters.job_process import _WindowsProcessTree

        clock = [100.0]
        kernel = self.accounting_kernel(clock, metadata_step=4)
        tree = object.__new__(_WindowsProcessTree)
        tree.handle = 300
        tree.kernel = kernel
        with (
            patch('tests.smoke_timeout_diagnostics.time.monotonic', side_effect=lambda: clock[0]),
            patch('quantlab.research_core.application.job_manager.time.monotonic', side_effect=lambda: clock[0]),
        ):
            with self.assertRaisesRegex(RuntimeSafetyError, 'unchanged reserve') as failure:
                _stop_windows_smoke_workers(tree, SimpleNamespace(_handle=100), [123], kernel=kernel)
        kernel.TerminateJobObject.assert_called_once_with(300, 1)
        self.assertEqual(kernel.QueryInformationJobObject.call_count, 1)
        kernel.WaitForSingleObject.assert_not_called()
        self.assertIn('retention', failure.exception.cleanup_failures)
        self.assertIn('job_drain', failure.exception.cleanup_failures)
        kernel.CloseHandle.assert_called_once_with(200)

    def test_retention_refusal_attempts_owned_job_drain_and_reports_failure(self):
        from tests.smoke_timeout_diagnostics import _stop_windows_smoke_workers
        from quantlab.research_core.adapters.job_process import _WindowsProcessTree

        clock = [100.0]
        kernel = self.accounting_kernel(clock)
        kernel.OpenProcess.return_value = None
        tree = object.__new__(_WindowsProcessTree)
        tree.handle = 300
        tree.kernel = kernel
        with (
            patch('tests.smoke_timeout_diagnostics.time.monotonic', side_effect=lambda: clock[0]),
            patch('quantlab.research_core.application.job_manager.time.monotonic', side_effect=lambda: clock[0]),
        ):
            with self.assertRaisesRegex(RuntimeSafetyError, 'unchanged reserve') as failure:
                _stop_windows_smoke_workers(tree, SimpleNamespace(_handle=100), [123], kernel=kernel)
        self.assertEqual(failure.exception.cleanup_failures, {'retention': 1})
        kernel.TerminateJobObject.assert_called_once_with(300, 1)
        kernel.QueryInformationJobObject.assert_called_once()
        kernel.WaitForSingleObject.assert_not_called()

    def test_coordinator_propagates_aggregate_close_failure(self):
        from tests.smoke_timeout_diagnostics import _stop_windows_smoke_workers
        from quantlab.research_core.adapters.job_process import _WindowsProcessTree

        clock = [100.0]
        kernel = self.accounting_kernel(clock)
        kernel.CloseHandle.return_value = False
        tree = object.__new__(_WindowsProcessTree)
        tree.handle = 300
        tree.kernel = kernel
        with (
            patch('tests.smoke_timeout_diagnostics.time.monotonic', side_effect=lambda: clock[0]),
            patch('quantlab.research_core.application.job_manager.time.monotonic', side_effect=lambda: clock[0]),
        ):
            with self.assertRaisesRegex(RuntimeSafetyError, 'unchanged reserve') as failure:
                _stop_windows_smoke_workers(tree, SimpleNamespace(_handle=100), [123], kernel=kernel)
        self.assertEqual(failure.exception.cleanup_failures, {'close_native_false': 1})

    def test_native_tree_cannot_extend_deadline_when_caller_passes_future_budget(self):
        from quantlab.research_core.adapters.job_process import _WindowsProcessTree

        clock = [100.0]
        kernel = self.accounting_kernel(clock, terminate_step=7)
        tree = object.__new__(_WindowsProcessTree)
        tree.handle = 300
        tree.kernel = kernel
        with patch('quantlab.research_core.application.job_manager.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeSafetyError, 'unchanged deadline'):
                tree.stop_and_join(deadline=10000)
        kernel.TerminateJobObject.assert_called_once_with(300, 1)


class WorkerTimingTests(unittest.TestCase):
    def test_active_phase_and_failed_call_are_recorded_without_exception_text(self):
        timings = WorkerTimings()
        with self.assertRaisesRegex(RuntimeError, 'DO_NOT_RETAIN'):
            with timings.measure('worker.body'), timings.measure('wfo.evaluate'):
                observed = timings.snapshot()
                self.assertEqual([row['phase'] for row in observed['active']], ['worker.body', 'wfo.evaluate'])
                raise RuntimeError('DO_NOT_RETAIN')
        observed = timings.snapshot()
        self.assertEqual(observed['active'], [])
        self.assertEqual({row['phase']: row['calls'] for row in observed['timings']}, {'worker.body': 1, 'wfo.evaluate': 1})
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(observed))
        with self.assertRaises(ValueError):
            with timings.measure('/private/not-a-phase'):
                self.fail('Unknown phase accepted')

    def test_worker_waits_for_admission_before_instrumentation(self):
        from unittest.mock import Mock

        gate = Mock()
        gate.wait.return_value = False
        with (
            patch('tests.smoke_timeout_diagnostics.instrument_walk_forward') as instrument,
            patch('tests.smoke_timeout_diagnostics._original_job_worker') as worker,
        ):
            diagnosed_smoke_worker(None, gate, 'ui_walk_forward_run', {}, None, None, 'fixture')
        gate.wait.assert_called_once_with(15)
        instrument.assert_not_called()
        worker.assert_not_called()

    def test_sqlite_semantics_and_explicit_factories_are_unchanged_and_wrappers_restore(self):
        from quantlab import walk_forward

        original_connect, original_save = sqlite3.connect, walk_forward._save_state
        timings = WorkerTimings()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'fixture.sqlite3'
            with closing(sqlite3.connect(database)) as db:
                expected = [db.execute('PRAGMA ' + name).fetchone()[0] for name in ('journal_mode', 'synchronous')]
            with self.assertRaisesRegex(RuntimeError, 'restore-on-error'):
                with instrument_walk_forward(timings):
                    with closing(sqlite3.connect(database)) as db:
                        self.assertEqual([db.execute('PRAGMA ' + name).fetchone()[0] for name in ('journal_mode', 'synchronous')], expected)
                        db.execute('CREATE TABLE fixture (value TEXT)')
                        db.execute('INSERT INTO fixture VALUES (?)', ('DO_NOT_RETAIN',))
                        db.commit()
                        with self.assertRaises(ValueError):
                            with db:
                                db.execute('INSERT INTO fixture VALUES (?)', ('rollback',))
                                raise ValueError('rollback')
                    for args, kwargs in (((':memory:',), {'factory': sqlite3.Connection}), ((':memory:', 5.0, 0, '', True, sqlite3.Connection), {})):
                        with closing(sqlite3.connect(*args, **kwargs)) as db:
                            self.assertIs(type(db), sqlite3.Connection)
                    raise RuntimeError('restore-on-error')
            self.assertIs(sqlite3.connect, original_connect)
            self.assertIs(walk_forward._save_state, original_save)
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT value FROM fixture').fetchall(), [('DO_NOT_RETAIN',)])
        encoded = json.dumps(timings.snapshot())
        self.assertNotIn('DO_NOT_RETAIN', encoded)
        self.assertNotIn(str(database), encoded)
        self.assertNotIn('SELECT', encoded)
        calls = {row['phase']: row['calls'] for row in timings.snapshot()['timings']}
        self.assertEqual(calls['sqlite.commit'], 1)
        self.assertEqual(calls['sqlite.transaction_exit'], 1)

    def test_timing_sanitizer_rejects_unknown_labels_fields_and_unbounded_numbers(self):
        good = {'phase': 'wfo.evaluate', 'elapsed_ms': 123, 'calls': 2}
        raw = {
            'stage': 'worker_timing',
            'operation': 'ui_walk_forward_run',
            'active': [{'phase': 'sqlite.commit', 'elapsed_ms': 3, 'sql': 'DO_NOT_RETAIN'}],
            'timings': [
                dict(good, path='/private/root', secret='DO_NOT_RETAIN'),
                dict(good, phase='/private/root'),
                dict(good, phase=[]),
                dict(good, elapsed_ms=-1),
                dict(good, elapsed_ms=7200001),
                dict(good, elapsed_ms=True),
                dict(good, calls=True),
                dict(good, calls=1000001),
                None,
                'DO_NOT_RETAIN',
            ],
        }
        result = output_summary('SMOKE_DIAGNOSTIC ' + json.dumps(raw))['events'][0]
        self.assertEqual(result['timings'], [good])
        self.assertEqual(result['active'], [{'phase': 'sqlite.commit', 'elapsed_ms': 3}])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))
        for field in ('active', 'timings'):
            raw[field] = {'unexpected': 'DO_NOT_RETAIN'}
        result = output_summary('SMOKE_DIAGNOSTIC ' + json.dumps(raw))['events'][0]
        self.assertEqual(result['active'], [])
        self.assertEqual(result['timings'], [])


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux /proc disappearance semantics')
class ProcDisappearanceTests(unittest.TestCase):
    def test_liveness_classifies_kernel_dead_states_and_retains_unknowns(self):
        from tests.test_desktop_walk_forward_terminal import process_can_run as walk_forward_can_run

        for state in ('R', 'S', 'D', 'T', 't', 'K', 'W', 'P', 'I', 'Z', 'X', 'x', '-', '?', 'DO_NOT_RETAIN'):
            with (
                self.subTest(state=state),
                patch('tests.test_desktop_smoke_terminal.os.kill') as probe,
                patch.object(Path, 'read_text', return_value=f'123 (private command) {state} 1 123'),
            ):
                observed = {}
                self.assertEqual(process_can_run(123, linux_states=observed), state not in {'Z', 'X', 'x'})
                probe.assert_called_once_with(123, 0)
                self.assertEqual(walk_forward_can_run(123), state not in {'Z', 'X', 'x'})
                self.assertEqual(observed, {'123': '?' if state in {'-', '?', 'DO_NOT_RETAIN'} else state})
                self.assertNotIn('private', json.dumps(observed))
                self.assertNotIn('DO_NOT_RETAIN', json.dumps(observed))

    def test_owned_stopped_process_is_live_until_killed_zombie_and_reaped(self):
        worker = subprocess.Popen([sys.executable, '-c', 'import time; print("ready", flush=True); time.sleep(60)'], stdout=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([worker.stdout], [], [], 6)[0], 'Owned worker did not start')
            self.assertEqual(worker.stdout.readline().strip(), 'ready')
            self.assertTrue(process_can_run(worker.pid))
            os.kill(worker.pid, signal.SIGSTOP)
            os.waitid(os.P_PID, worker.pid, os.WSTOPPED)
            observed = {}
            self.assertTrue(process_can_run(worker.pid, linux_states=observed))
            self.assertEqual(observed, {str(worker.pid): 'T'})
            worker.kill()
            os.waitid(os.P_PID, worker.pid, os.WEXITED | os.WNOWAIT)
            self.assertFalse(process_can_run(worker.pid, linux_states=observed))
            self.assertEqual(observed, {str(worker.pid): 'Z'})
            worker.wait(timeout=6)
            self.assertFalse(process_can_run(worker.pid, linux_states=observed))
            self.assertEqual(observed, {str(worker.pid): '-'})
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=6)
            worker.stdout.close()

    def test_timeout_cleanup_survives_real_unrelated_proc_exit_during_scan(self):
        with process_exits_during_proc_read() as (_, observed):
            SmokeTimeoutDiagnosticTests().assert_timeout_cleanup()
        self.assertEqual(observed, [errno.ESRCH])  # ESRCH, not ENOENT.

    def test_group_join_survives_real_unrelated_proc_exit_during_scan(self):
        code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(child.pid,flush=True); time.sleep(60)"
        worker = subprocess.Popen([sys.executable, '-c', code], start_new_session=True, stdout=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([worker.stdout], [], [], 6)[0], 'Nested worker did not start')
            grandchild_pid = int(worker.stdout.readline())
            self.assertTrue(process_can_run(grandchild_pid))
            with process_exits_during_proc_read() as (_, observed):
                JobManager._join_descendants(SimpleNamespace(tree=None, _operation='ui_walk_forward_run'), worker.pid)
            self.assertEqual(observed, [errno.ESRCH])
            self.assertFalse(process_can_run(worker.pid))
            self.assertFalse(process_can_run(grandchild_pid))
        finally:
            try:
                os.killpg(worker.pid, 9)
            except ProcessLookupError:
                pass
            worker.wait(timeout=6)
            worker.stdout.close()

    def test_liveness_survives_real_process_exit_during_stat_read(self):
        from tests.test_desktop_walk_forward_terminal import process_can_run as walk_forward_can_run

        with process_exits_during_proc_read() as (pid, observed):
            self.assertFalse(process_can_run(pid))
        self.assertEqual(observed, [errno.ESRCH])
        with process_exits_during_proc_read() as (pid, observed):
            self.assertFalse(walk_forward_can_run(pid))
        self.assertEqual(observed, [errno.ESRCH])

    def test_group_join_and_liveness_do_not_hide_permission_or_unknown_errors(self):
        from tests.test_desktop_walk_forward_terminal import process_can_run as walk_forward_can_run

        for error in (PermissionError(errno.EACCES, 'denied'), OSError(errno.EIO, 'unknown I/O failure')):
            with (
                self.subTest(error=type(error).__name__),
                patch('quantlab.research_core.adapters.job_process.os.killpg'),
                patch('tests.test_desktop_smoke_terminal.os.kill'),
                patch.object(Path, 'iterdir', return_value=iter([Path('/proc/123')])),
                patch.object(Path, 'read_text', side_effect=error),
            ):
                with self.assertRaises(type(error)):
                    JobManager._join_descendants(SimpleNamespace(tree=None, _operation='ui_walk_forward_run'), 123)
                with self.assertRaises(type(error)):
                    process_can_run(123)
                with self.assertRaises(type(error)):
                    walk_forward_can_run(123)

    def test_timeout_scan_permission_and_unknown_errors_keep_cleanup_unverified(self):
        for error in (PermissionError(errno.EACCES, 'denied'), OSError(errno.EIO, 'unknown I/O failure')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original_read, original_iterdir = Path.read_text, Path.iterdir
                denied = Path('/proc/123/stat')

                def read(path, *args, **kwargs):
                    if path == denied:
                        raise error
                    return original_read(path, *args, **kwargs)

                def iterdir(path):
                    return iter([denied.parent]) if path == Path('/proc') else original_iterdir(path)

                with patch.object(Path, 'read_text', read), patch.object(Path, 'iterdir', iterdir):
                    with self.assertRaisesRegex(AssertionError, 'unchanged deadline'):
                        run_smoke_process(
                            [sys.executable, '-c', 'import time; time.sleep(60)'],
                            cwd=root,
                            env=os.environ.copy(),
                            report=root / 'report',
                            pidfile=root / 'pids',
                            writes=root / 'writes',
                            process_can_run=process_can_run,
                            artifact_dir=root / 'artifacts',
                            timeout=1,
                        )
                (artifact,) = (root / 'artifacts').glob('smoke-timeout-*.json')
                value = json.loads(artifact.read_text(encoding='utf-8'))
                self.assertFalse(value['cleanup_verified'], value)
                self.assertEqual(value['cleanup_error_type'], type(error).__name__)
