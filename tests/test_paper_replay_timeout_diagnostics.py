"""Exact-invocation observation preserves gates, privacy and original failures."""

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tests import paper_replay_timeout_diagnostics as diagnostic


class OriginalReplayDiagnosticTests(unittest.TestCase):
    def fixture(self):
        process = SimpleNamespace(is_alive=lambda: True, exitcode=None)
        jobs = SimpleNamespace(process=process, active=True, _terminal=False, _pipe_eof=False, _deferred=[], _pending=[], job_id='a' * 32)
        return SimpleNamespace(jobs=jobs, app=object(), window=SimpleNamespace(status=SimpleNamespace(text=lambda: 'Working')))

    def test_wait_uses_original_default_and_reraises_identical_failure_before_cleanup(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            observation.action = 'paper_replay'
            failure = AssertionError('original gate failure private text')
            calls = []

            def original(instance, timeout=30):
                calls.append((instance, timeout))
                raise failure

            with patch('sys.stderr', new=io.StringIO()), self.assertRaises(AssertionError) as raised:
                observation.wait(original, fixture)
            self.assertIs(raised.exception, failure)
            self.assertEqual(calls, [(fixture, 30)])
            report = json.loads(observation.path.read_text())
            self.assertEqual(report['acceptance_timeout_seconds'], 30)
            self.assertEqual(report['acceptance_bars'], 960)
            self.assertFalse(report['original_test_rerun'])
            failure_state = report['original_wait_failed_before_cleanup']['job']
            self.assertTrue(failure_state['active'])
            self.assertTrue(failure_state['child_alive'])
            self.assertTrue(failure_state['status_is_working'])
            self.assertNotIn('private text', observation.path.read_text())
            self.assertNotIn(directory, observation.path.read_text())

    def test_explicit_wait_arguments_and_return_value_are_forwarded(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            calls = []

            def original(instance, *args, **kwargs):
                calls.append((instance, args, kwargs))
                return 'original return'

            self.assertEqual(observation.wait(original, fixture, 30), 'original return')
            self.assertEqual(calls, [(fixture, (30,), {})])
            self.assertTrue(observation.actions[-1]['returned'])

    def test_only_replay_click_installs_worker_and_environment_restores_on_error(self):
        import quantlab.desktop_runtime as runtime

        fixture = self.fixture()
        original_worker = runtime._job_worker
        original_environment = os.environ.get(diagnostic.ENVIRONMENT)
        failure = RuntimeError('click failed')
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            calls = []

            def clicked(instance, name):
                calls.append(name)
                if name == 'paper_replay':
                    self.assertIs(runtime._job_worker, diagnostic._gate_worker)
                    self.assertTrue(os.environ[diagnostic.ENVIRONMENT].startswith(directory))
                    raise failure
                self.assertIs(runtime._job_worker, original_worker)

            observation.click(clicked, fixture, 'create_demo')
            with self.assertRaises(RuntimeError) as raised:
                observation.click(clicked, fixture, 'paper_replay')
            self.assertIs(raised.exception, failure)
            self.assertEqual(calls, ['create_demo', 'paper_replay'])
        self.assertIs(runtime._job_worker, original_worker)
        self.assertEqual(os.environ.get(diagnostic.ENVIRONMENT), original_environment)

    def test_worker_forwards_gate_packets_and_restores_instrumentation_without_payload_logging(self):
        import sqlite3
        from quantlab.paper_replay import PaperReplay

        original_connect, original_step = sqlite3.connect, PaperReplay.step
        sent, waits, closes = [], [], []
        sender = SimpleNamespace(send_bytes=sent.append, close=lambda: closes.append(True))
        gate = SimpleNamespace(wait=lambda seconds: waits.append(seconds) or True)

        def original(observed_sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            observed_sender.send_bytes(b'{"type":"result","private":"never-log-this-token"}')
            observed_sender.close()
            return 71

        with tempfile.TemporaryDirectory() as directory:
            prefix = str(Path(directory) / 'worker')
            with patch.dict(os.environ, {diagnostic.ENVIRONMENT: prefix}), patch.object(diagnostic, '_original_worker', side_effect=original):
                self.assertEqual(diagnostic._gate_worker(sender, gate, 'ui_paper_replay', {'private': 'never-log-this-token'}, directory, None, 'a' * 32), 71)
            raw = Path(prefix + '-' + 'a' * 32 + '.json').read_text()
            report = json.loads(raw)
            self.assertEqual(report['last_sent_type'], 'result')
            self.assertTrue(report['worker_body_returned'])
            self.assertEqual(report['timings']['worker.start_gate']['calls'], 1)
            self.assertEqual(report['timings']['ipc.send']['calls'], 1)
            self.assertNotIn('never-log-this-token', raw)
            self.assertNotIn(directory, raw)
        self.assertEqual(waits, [15])
        self.assertEqual(closes, [True])
        self.assertEqual(len(sent), 1)
        self.assertIs(sqlite3.connect, original_connect)
        self.assertIs(PaperReplay.step, original_step)

    def test_reporting_failure_never_overwrites_the_original_assertion(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            failure = AssertionError('original')

            def original(instance):
                raise failure

            with (
                patch.object(diagnostic, '_write_json', side_effect=OSError('private path')),
                patch('sys.stderr', new=io.StringIO()),
                self.assertRaises(AssertionError) as raised,
            ):
                observation.wait(original, fixture)
            self.assertIs(raised.exception, failure)

    def test_decorator_calls_original_once_and_preserves_lifo_cleanup(self):
        from tests.test_desktop_ui import NativeDesktopTests

        fixture = unittest.TestCase()
        fixture.app = object()
        calls = []
        failure = AssertionError('original body')
        original_click, original_wait = NativeDesktopTests.click, NativeDesktopTests.wait_job

        @diagnostic.observe_original_replay
        def original(instance):
            calls.append('body')
            instance.addCleanup(calls.append, 'original cleanup')
            raise failure

        with (
            patch.object(diagnostic.OriginalReplayObservation, 'capture', autospec=True, side_effect=lambda self, stage, **kw: calls.append(stage)),
            patch.object(diagnostic, 'qt_resources', return_value={}),
        ):
            with self.assertRaises(AssertionError) as raised:
                original(fixture)
            self.assertIs(raised.exception, failure)
            self.assertEqual(calls.count('body'), 1)
            self.assertNotIn('original cleanup', calls)
            self.assertTrue(fixture.doCleanups())
        self.assertLess(calls.index('original_body_failed_before_cleanup'), calls.index('original cleanup'))
        self.assertLess(calls.index('original cleanup'), calls.index('after_fixture_cleanup'))
        self.assertIs(NativeDesktopTests.click, original_click)
        self.assertIs(NativeDesktopTests.wait_job, original_wait)

    def test_blocked_original_gate_has_no_observer_io_thread_or_sql_installation(self):
        import quantlab.desktop_runtime as runtime

        waits = []
        gate = SimpleNamespace(wait=lambda seconds: waits.append(seconds) or False)
        sender = SimpleNamespace(
            send_bytes=lambda value: self.fail('No packet before admission'), close=lambda: self.fail('Original blocked-gate close semantics changed')
        )
        order = []

        def blocked(seconds):
            order.append('gate')
            waits.append(seconds)
            return False

        gate.wait = blocked
        with (
            patch.object(diagnostic, '_original_worker', runtime._job_worker),
            patch.object(runtime.os, 'setsid', create=True, side_effect=lambda: order.append('setsid')),
            patch.object(diagnostic, '_write_json') as write,
            patch.object(diagnostic.threading, 'Thread') as thread,
            patch.object(diagnostic, '_instrument_connect') as install,
        ):
            self.assertIsNone(diagnostic._gate_worker(sender, gate, 'ui_paper_replay', {}, 'unused', None, 'a' * 32))
        self.assertEqual(waits, [15])
        if sys.platform != 'win32':
            self.assertEqual(order, ['setsid', 'gate'])
        write.assert_not_called()
        thread.assert_not_called()
        install.assert_not_called()

    def test_unwritable_observer_directory_still_clicks_original_once(self):
        import quantlab.desktop_runtime as runtime

        fixture = self.fixture()
        original_worker = runtime._job_worker
        calls = []

        def clicked(instance, name):
            calls.append(name)
            self.assertIs(runtime._job_worker, original_worker)
            return 'unchanged'

        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            with patch.object(Path, 'mkdir', side_effect=OSError('private path')):
                self.assertEqual(observation.click(clicked, fixture, 'paper_replay'), 'unchanged')
            self.assertEqual(calls, ['paper_replay'])
            self.assertEqual(observation.evidence['observer_unavailable_error_type'], 'OSError')

    def test_partial_install_and_thread_start_failures_restore_hooks_and_never_retry_operation(self):
        import sqlite3
        from quantlab.paper_replay import PaperReplay

        original_connect, original_step = sqlite3.connect, PaperReplay.step
        for target in ('sqlite_install', 'thread_start'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                calls = []
                sender = SimpleNamespace(send_bytes=lambda value: None, close=lambda: None)
                gate = SimpleNamespace(wait=lambda seconds: True)

                def original(observed_sender, observed_gate, *args):
                    calls.append('original')
                    self.assertTrue(observed_gate.wait(15))
                    self.assertIs(sqlite3.connect, original_connect)
                    self.assertIs(PaperReplay.step, original_step)
                    calls.append('operation')
                    observed_sender.send_bytes(b'{"type":"result"}')
                    return 19

                injection = (
                    patch.object(diagnostic, '_instrument_connect', side_effect=RuntimeError('private'))
                    if target == 'sqlite_install'
                    else patch.object(diagnostic.threading.Thread, 'start', side_effect=RuntimeError('private'))
                )
                prefix = str(Path(directory) / 'worker')
                with patch.dict(os.environ, {diagnostic.ENVIRONMENT: prefix}), patch.object(diagnostic, '_original_worker', side_effect=original), injection:
                    self.assertEqual(diagnostic._gate_worker(sender, gate, 'ui_paper_replay', {}, directory, None, 'a' * 32), 19)
                self.assertEqual(calls, ['original', 'operation'])
                report = json.loads(Path(prefix + '-' + 'a' * 32 + '.json').read_text())
                self.assertEqual(report['instrumentation_error_type'], 'RuntimeError')
                self.assertEqual(report['last_sent_type'], 'result')
                self.assertTrue(report['worker_body_returned'])
                self.assertIs(sqlite3.connect, original_connect)
                self.assertIs(PaperReplay.step, original_step)

    def test_deadline_worker_snapshot_is_not_replaced_by_later_cleanup_observation(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic, 'qt_resources', return_value={}):
            observation = diagnostic.OriginalReplayObservation(fixture, directory)
            observation.worker_ids = ['a' * 32]
            worker = Path(str(observation.prefix) + '-' + 'a' * 32 + '.json')
            worker.write_text('{"timings":{"replay.cursor_commit":{"calls":500}}}')
            observation.capture('original_wait_failed_before_cleanup')
            worker.write_text('{"timings":{"replay.cursor_commit":{"calls":501}}}')
            observation.capture('after_fixture_cleanup')
            report = json.loads(observation.path.read_text())
            self.assertEqual(report['original_wait_failed_before_cleanup']['workers'][0]['timings']['replay.cursor_commit']['calls'], 500)
            self.assertEqual(report['after_fixture_cleanup']['workers'][0]['timings']['replay.cursor_commit']['calls'], 501)

    def test_storage_samples_distinguish_preinitialization_from_ready_wal_full(self):
        from quantlab.paper_replay import PaperReplay

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'replays').mkdir()
            sender = SimpleNamespace(send_bytes=lambda value: None, close=lambda: None)
            gate = SimpleNamespace(wait=lambda seconds: True)

            def original(observed_sender, observed_gate, *args):
                self.assertTrue(observed_gate.wait(15))
                replay = PaperReplay.__new__(PaperReplay)
                replay.path = root / 'replays' / 'phase.sqlite3'
                replay.storage_profile = 'wal_full'
                replay._wal_ready = False
                with replay._connection() as db:
                    self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
                    self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
                replay._wal_ready = True
                with replay._connection() as db:
                    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))
                    self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))

            prefix = str(root / 'worker')
            with patch.dict(os.environ, {diagnostic.ENVIRONMENT: prefix}), patch.object(diagnostic, '_original_worker', side_effect=original):
                diagnostic._gate_worker(sender, gate, 'ui_paper_replay', {}, directory, None, 'a' * 32)
            report = json.loads(Path(prefix + '-' + 'a' * 32 + '.json').read_text())
            before = report['replay_storage_before_wal_initialization']
            self.assertEqual(before['sample_phase'], 'before_wal_initialization')
            self.assertEqual(before['journal_mode'], 'delete')
            self.assertFalse(before['wal_ready'])
            effective = report['replay_storage']
            self.assertEqual(effective['sample_phase'], 'wal_ready_connection')
            self.assertEqual(effective['journal_mode'], 'wal')
            self.assertTrue(effective['wal_ready'])
            for sample in (before, effective):
                self.assertEqual(sample['requested_profile'], 'wal_full')
                self.assertEqual(sample['synchronous'], 2)
                self.assertEqual(sample['wal_autocheckpoint'], 1000)
