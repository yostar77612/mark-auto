"""Observer parity controls, not native smoke latency or acceptance evidence."""

from contextlib import contextmanager, nullcontext, redirect_stderr
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from quantlab import research, walk_forward
from quantlab.core import Instrument, StrategySpec
from quantlab.paper import PaperBroker, RiskLimits
from quantlab.paper_replay import PaperReplay
from quantlab.reporting import demo_config, synthetic_dataset
from tests import generic_smoke_phase_diagnostics as diagnostics
from tests.smoke_timeout_diagnostics import diagnosed_smoke_worker, output_summary, WORKER_PHASES


class GenericSmokePhaseDiagnosticTests(unittest.TestCase):
    def test_routing_is_limited_to_original_campaign_and_paper_workers(self):
        for operation in diagnostics.OPERATIONS:
            arguments = (object(), object(), operation, {}, 'root', 'bootstrap', 'job', True)
            with patch.object(diagnostics, 'diagnosed_generic_worker', return_value='original') as worker:
                self.assertEqual(diagnosed_smoke_worker(*arguments), 'original')
            worker.assert_called_once_with(*arguments)
        with patch.object(diagnostics, '_original_job_worker', return_value='original') as worker:
            arguments = (None, None, 'ui_demo', {}, None, None, 'job', False)
            self.assertEqual(diagnostics.diagnosed_generic_worker(*arguments), 'original')
        worker.assert_called_once_with(*arguments)

    def test_original_worker_owns_one_gate_wait_and_denial_has_no_instrumentation(self):
        gate = Mock()
        gate.wait.return_value = False

        def original(sender, observed_gate, *args):
            self.assertFalse(observed_gate.wait(15))
            return 'original'

        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original) as worker,
            patch.object(diagnostics, 'instrument_generic_operations') as instrument,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            result = diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job')
        self.assertEqual(result, 'original')
        worker.assert_called_once()
        gate.wait.assert_called_once_with(15)
        instrument.assert_not_called()
        self.assertEqual(stderr.getvalue(), '')

    def test_observer_setup_failure_cannot_retry_or_replace_original_work(self):
        gate = Mock()
        gate.wait.return_value = True
        marker = object()

        @contextmanager
        def broken(timings):
            raise OSError('DO_NOT_RETAIN')
            yield

        def original(sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            return marker

        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original) as worker,
            patch.object(diagnostics, 'instrument_generic_operations', broken),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            result = diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job')
        self.assertIs(result, marker)
        worker.assert_called_once()
        gate.wait.assert_called_once_with(15)
        self.assertNotIn('DO_NOT_RETAIN', stderr.getvalue())
        evidence = output_summary(stderr.getvalue())['events'][-1]
        self.assertFalse(evidence['instrumentation_ready'])
        self.assertTrue(evidence['instrumentation_failed'])

    def test_oversized_or_failed_report_cannot_replace_original_result(self):
        gate = Mock()
        gate.wait.return_value = True

        def original(sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            return 'original'

        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original) as worker,
            patch.object(diagnostics.GenericTimings, 'snapshot', return_value={'unsafe': 'x' * diagnostics.MAX_REPORT_BYTES}),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job'), 'original')
        worker.assert_called_once()
        self.assertEqual(stderr.getvalue(), '')
        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original) as worker,
            patch.object(diagnostics, 'print', side_effect=OSError('DO_NOT_RETAIN'), create=True),
        ):
            self.assertEqual(diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job'), 'original')
        worker.assert_called_once()

    def test_controlled_timeout_retains_ready_phase_and_verified_owned_cleanup(self):
        from tests.smoke_timeout_diagnostics import run_smoke_process, SmokeOutputCapture
        from tests.test_desktop_smoke_terminal import process_can_run

        code = '''import json, sys, threading, time
from contextlib import contextmanager
from quantlab import research
from tests import generic_smoke_phase_diagnostics as diagnostics
original_instrument = diagnostics.instrument_generic_operations
@contextmanager
def capture_timings(timings):
 global observed
 observed = timings
 with original_instrument(timings): yield
diagnostics.instrument_generic_operations = capture_timings
def stalled_campaign(*args, **kwargs):
 print('SMOKE_DIAGNOSTIC ' + json.dumps(observed.snapshot()), file=sys.stderr, flush=True)
 time.sleep(60)
research.run_campaign = stalled_campaign
def original(sender, gate, *args):
 if gate.wait(15): research.run_campaign()
diagnostics._original_job_worker = original
gate = threading.Event(); gate.set()
diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'controlled')
'''
        communicate = SmokeOutputCapture.communicate

        def controlled_timeout(capture, admission=None, *, timeout):
            if admission is None:
                return communicate(capture, timeout=timeout)
            # This is an injected collector timeout after explicit readiness,
            # not a new latency gate or a change to the original smoke's 40s.
            capture.process.stdin.write(admission)
            capture.process.stdin.flush()
            capture.process.stdin.close()
            deadline = time.monotonic() + 10
            ready = False
            while time.monotonic() < deadline:
                events = output_summary(capture.snapshot('stderr')[0])['events']
                ready = any(event.get('instrumentation_ready') and any(row['phase'] == 'campaign.run' for row in event.get('active', [])) for event in events)
                if ready:
                    break
                time.sleep(0.01)
            self.assertTrue(ready, 'Controlled worker did not reach its active phase')
            raise subprocess.TimeoutExpired(capture.process.args, timeout)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(SmokeOutputCapture, 'communicate', controlled_timeout), self.assertRaisesRegex(AssertionError, 'unchanged deadline'):
                run_smoke_process(
                    [sys.executable, '-c', code],
                    cwd=Path(__file__).resolve().parents[1],
                    env=dict(os.environ),
                    report=root / 'report',
                    pidfile=root / 'pids',
                    writes=root / 'writes',
                    process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts',
                    timeout=2,
                )
            (artifact,) = (root / 'artifacts').glob('smoke-timeout-*.json')
            evidence = json.loads(artifact.read_text(encoding='utf-8'))
        self.assertEqual(evidence['timeout_seconds'], 2)
        self.assertTrue(evidence['cleanup_verified'])
        observations = [event for event in evidence['stderr']['events'] if event['stage'] == 'worker_timing']
        self.assertTrue(observations[-1]['instrumentation_ready'])
        self.assertFalse(observations[-1]['instrumentation_failed'])
        self.assertEqual(observations[-1]['operation'], 'ui_campaign')
        self.assertIn('campaign.run', [row['phase'] for row in observations[-1]['active']])

    def test_original_failure_and_all_observed_callables_are_preserved(self):
        targets = [
            (sqlite3, 'connect'),
            (Path, 'write_text'),
            (Path, 'replace'),
            (research, 'run_campaign'),
            (research, 'replace_file'),
            (research, '_run_bounded'),
            (PaperBroker, '_transaction'),
            (PaperReplay, '_db'),
            (walk_forward, '_save_state'),
        ]
        originals = [getattr(owner, name) for owner, name in targets]
        gate = Mock()
        gate.wait.return_value = True
        failure = RuntimeError('original failure')

        def original(sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            raise failure

        with patch.object(diagnostics, '_original_job_worker', side_effect=original), redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as raised:
            diagnostics.diagnosed_generic_worker(None, gate, 'ui_paper_replay', {}, None, None, 'job')
        self.assertIs(raised.exception, failure)
        self.assertEqual([getattr(owner, name) for owner, name in targets], originals)

    def test_inflight_reporter_is_joined_before_original_result_returns(self):
        entered, release, body_returned = threading.Event(), threading.Event(), threading.Event()
        gate = Mock()
        gate.wait.return_value = True
        reports, reporters, results = [], [], []
        original_thread = threading.Thread

        def factory(*args, **kwargs):
            thread = original_thread(*args, **kwargs)
            reporters.append(thread)
            return thread

        def print_report(*args, **kwargs):
            reports.append(None)
            if len(reports) == 2:
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Controlled reporter was not released')

        def original(sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            self.assertTrue(entered.wait(5))
            body_returned.set()
            return 'original'

        def run():
            results.append(diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job'))

        driver = original_thread(target=run)
        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original),
            patch.object(diagnostics.threading, 'Thread', side_effect=factory),
            patch.object(diagnostics, 'print', side_effect=print_report, create=True),
        ):
            driver.start()
            try:
                self.assertTrue(body_returned.wait(5))
                self.assertTrue(driver.is_alive())
                self.assertEqual(results, [])
            finally:
                release.set()
                driver.join(5)
        self.assertFalse(driver.is_alive())
        self.assertEqual(results, ['original'])
        self.assertEqual(len(reporters), 1)
        self.assertFalse(reporters[0].is_alive())

    def test_restoration_failure_still_stops_reporter_and_keeps_original_result(self):
        gate = Mock()
        gate.wait.return_value = True
        stack = Mock()
        stack.close.side_effect = OSError('DO_NOT_RETAIN')

        def original(sender, observed_gate, *args):
            self.assertTrue(observed_gate.wait(15))
            return 'original'

        before = set(threading.enumerate())
        with (
            patch.object(diagnostics, '_original_job_worker', side_effect=original),
            patch.object(diagnostics, 'ExitStack', return_value=stack),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(diagnostics.diagnosed_generic_worker(None, gate, 'ui_campaign', {}, None, None, 'job'), 'original')
        self.assertEqual(set(threading.enumerate()), before)
        self.assertTrue(output_summary(stderr.getvalue())['events'][-1]['instrumentation_failed'])
        self.assertNotIn('DO_NOT_RETAIN', stderr.getvalue())

    def test_bounded_phase_cpu_evidence_survives_sanitization_without_data(self):
        timings = diagnostics.GenericTimings('ui_campaign')
        with timings.measure('campaign.run'), timings.measure('sqlite.commit'):
            snapshot = timings.snapshot()
        complete = timings.snapshot()
        self.assertLessEqual(len(WORKER_PHASES), 32)
        self.assertLessEqual(len(json.dumps(complete).encode('utf-8')), diagnostics.MAX_REPORT_BYTES)
        self.assertEqual(complete['operation'], 'ui_campaign')
        self.assertEqual(complete['active'], [])
        self.assertTrue(all(row['cpu_ms'] >= 0 for row in complete['timings']))
        raw = dict(complete, secret='DO_NOT_RETAIN', payload={'path': '/private/root'})
        clean = output_summary('SMOKE_DIAGNOSTIC ' + json.dumps(raw))['events'][0]
        self.assertEqual(clean['timings'], complete['timings'])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(clean))
        self.assertNotIn('/private/root', json.dumps(clean))
        self.assertEqual([row['phase'] for row in snapshot['active']], ['campaign.run', 'sqlite.commit'])
        for bad in (-1, True, 7200001, 'secret'):
            raw['timings'] = [{'phase': 'sqlite.commit', 'calls': 1, 'elapsed_ms': 1, 'cpu_ms': bad}]
            self.assertEqual(
                output_summary('SMOKE_DIAGNOSTIC ' + json.dumps(raw))['events'][0]['timings'], [{'phase': 'sqlite.commit', 'calls': 1, 'elapsed_ms': 1}]
            )

    def test_campaign_keeps_spawned_evaluations_commits_exports_and_results(self):
        data = synthetic_dataset(120)
        config = research.demo_campaign_config(data, demo_config())
        config.update(families=['trend'], max_trials=1, max_improvements=0, max_runtime_seconds=45, process_start_method='spawn')
        config['ranking']['minimum'] = '-100000000'
        results, traces, calls = [], [], []
        timings = diagnostics.GenericTimings('ui_campaign')
        original_connect = sqlite3.connect
        original_worker = research._run_bounded
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'same'
            for observed in (False, True):
                trace = []

                def connect(*args, **kwargs):
                    db = original_connect(*args, **kwargs)
                    db.set_trace_callback(lambda sql: trace.append(sql.lstrip().split(None, 1)[0]))
                    return db

                with (
                    patch.object(sqlite3, 'connect', connect),
                    patch.object(research, '_run_bounded', wraps=original_worker) as worker,
                    diagnostics.instrument_generic_operations(timings) if observed else nullcontext(),
                ):
                    result = research.run_campaign(
                        data,
                        config=config,
                        generator=research.FixtureGenerator(),
                        output_dir=root / 'campaign',
                        holdout_registry_path=root / 'controls' / 'holdout-registry.sqlite3',
                    )
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['attempts'][0]['status'], 'evaluated')
                self.assertEqual(json.loads((root / 'campaign' / 'campaign.json').read_text()), result)
                result['elapsed_seconds'] = 0
                for attempt in result['attempts']:
                    attempt['elapsed_seconds'] = 0
                results.append(result)
                traces.append(trace)
                calls.append(worker.call_count)
                shutil.rmtree(root)
        self.assertEqual(results[0], results[1])
        self.assertEqual(traces[0], traces[1])
        self.assertEqual(calls[0], calls[1])
        self.assertGreaterEqual(calls[0], 3)
        counts = {row['phase']: row['calls'] for row in timings.snapshot()['timings']}
        self.assertEqual(counts['campaign.worker'], calls[0])
        self.assertEqual(counts['process.start'], calls[0])
        self.assertEqual(counts['export.write'], counts['export.replace'])
        self.assertEqual(counts['sqlite.commit'], counts['export.write'])

    def test_25_bar_paper_replay_keeps_exact_sql_events_and_storage_profiles(self):
        from desktop import _smoke_steps

        policy = _smoke_steps()[4][1]['policy']
        reconcile = _smoke_steps()[4][1]['snapshot']
        data = synthetic_dataset(120)
        timings = diagnostics.GenericTimings('ui_paper_replay')
        original_connect = sqlite3.connect
        results, traces = [], []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'same'
            for observed in (False, True):
                trace = []

                def connect(*args, **kwargs):
                    db = original_connect(*args, **kwargs)
                    db.set_trace_callback(trace.append)
                    return db

                with patch.object(sqlite3, 'connect', connect), diagnostics.instrument_generic_operations(timings) if observed else nullcontext():
                    broker = PaperBroker(
                        root / 'paper.sqlite3',
                        instrument=Instrument(policy['contract_id']),
                        costs=demo_config().costs,
                        limits=RiskLimits(1, 1, Decimal('1000'), 30),
                        risk_sessions=policy['risk_sessions'],
                        margin_schedule=policy['margin_schedule'],
                    )
                    broker.reconcile(reconcile)
                    replay = PaperReplay(
                        root / 'replays' / 'replay.sqlite3',
                        dataset=data,
                        strategy=StrategySpec('trend-v1', 'trend', {'fast': 5, 'slow': 20}, {}),
                        broker=broker,
                        margin_schedule=broker._margin_schedule,
                        storage_profile='wal_full',
                    )
                    replay.start()
                    try:
                        replay.step(max_bars=25)
                    finally:
                        replay.stop()
                    with replay._connection() as db:
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))
                        self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
                    result = {'replay': replay.snapshot(), 'account': broker.snapshot(), 'journal': broker.journal_events()}
                self.assertEqual(result['replay']['cursor'], 25)
                self.assertTrue(result['account']['kill_switch'])
                results.append(result)
                traces.append(trace)
                shutil.rmtree(root)
        self.assertEqual(results[0], results[1])
        self.assertEqual(traces[0], traces[1])
        counts = {row['phase']: row['calls'] for row in timings.snapshot()['timings']}
        self.assertEqual(counts['replay.step'], 1)
        self.assertGreater(counts['broker.transaction'], 0)
        self.assertGreater(counts['sqlite.commit'], 0)
        self.assertGreater(counts['sqlite.transaction_exit'], 0)

    def test_original_generic_terminal_fixture_keeps_both_forty_second_gates(self):
        from tests.test_desktop_smoke_terminal import GenericSmokeTerminalProcessTests

        case = GenericSmokeTerminalProcessTests(methodName='runTest')
        with patch('tests.test_desktop_smoke_terminal.run_smoke_process', side_effect=RuntimeError('wiring only')) as launch:
            with self.assertRaisesRegex(RuntimeError, 'wiring only'):
                case.test_late_directory_cleanup_failure_cannot_leave_pass_or_zero_exit()
        arguments, options = launch.call_args
        self.assertEqual(options['timeout'], 40)
        code = arguments[0][2]
        self.assertIn('job_worker._job_worker = diagnosed_smoke_worker', code)
        self.assertIn('tempfile.TemporaryDirectory.cleanup = fail_final', code)
        source = Path(__file__).with_name('test_desktop_smoke_terminal.py').read_text(encoding='utf-8')
        self.assertIn('self.assertLess(time.monotonic() - started, 40)', source)
