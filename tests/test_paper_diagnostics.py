"""Instrumentation must observe real SQLite semantics without weakening gates."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import subprocess
import time

from tools.diagnose_paper_replay import Timings, _instrument_connect, _write_json, _rollback_connection, _journal_mode_comparison


def _connection_checkpoint_fields(result):
    """Retain bounded numeric evidence, never the raw fixture report or paths."""
    import math

    def number(value):
        return type(value) in (int, float) and 0 <= value <= 7200 and math.isfinite(value)

    milestones = result.get('controller_milestones', {})
    allowed = (
        'owner_file_written',
        'probe_launch_requested',
        'probe_launch_returned',
        'probe_output_first_seen',
        'observer_stop_returned',
        'observer_start_returned',
        'probe_exit_observed',
        'timeout_observed',
        'controller_error_observed',
        'process_cleanup_started',
        'process_cleanup_finished',
        'observer_stop_launch_requested',
        'observer_stop_launch_returned',
        'observer_start_launch_requested',
        'observer_start_launch_returned',
    )
    value = {
        'checkpoint_semantics': ('last completed progress record, not deadline state; blocked native call/report write may leave it stale'),
        'controller_milestone_semantics': 'seconds from controller entry; first output is detection time',
        'controller_milestones': {key: milestones[key] for key in allowed if isinstance(milestones, dict) and number(milestones.get(key))},
        'controller_observation_failed': result.get('controller_observation_failed') is True,
    }
    value['probe_clock_semantics'] = {
        'elapsed_seconds': 'since Timings creation after ownership and path setup',
        'pre_timing_seconds': 'probe function entry through setup before Timings creation',
        'probe_entry_seconds': 'since probe function entry, excluding imports',
        'process_cpu_seconds': 'cumulative process CPU, including startup and imports',
    }
    report = result.get('observation', {})
    if not isinstance(report, dict):
        return value
    value['probe_clocks'] = {
        key: report[key] for key in ('elapsed_seconds', 'pre_timing_seconds', 'probe_entry_seconds', 'process_cpu_seconds') if number(report.get(key))
    }
    phases = {
        'replay.' + name
        for name in (
            'connect',
            'read',
            'pragma',
            'begin',
            'write',
            'cursor_write',
            'plan_write',
            'commit',
            'read_commit',
            'write_commit',
            'rollback',
            'transaction_exit',
            'read_exit',
            'cursor_commit',
            'cursor_rollback',
            'plan_commit',
            'plan_rollback',
            'close',
            'cursor_loop',
            'final_close',
            'external_stop',
            'external_start',
            'rollback_test',
            'verify_reopen',
        )
    }
    timings = report.get('timings', {})
    value['checkpoint_timings'] = {}
    if isinstance(timings, dict):
        for phase in sorted(phases):
            row = timings.get(phase)
            if isinstance(row, dict) and type(row.get('calls')) is int and 0 <= row['calls'] <= 1000000 and number(row.get('seconds')):
                value['checkpoint_timings'][phase] = {key: row[key] for key in ('calls', 'seconds')}
                if number(row.get('max_seconds')) and row['max_seconds'] <= row['seconds']:
                    value['checkpoint_timings'][phase]['max_seconds'] = row['max_seconds']
    last = report.get('last_completed')
    value['checkpoint_last_completed'] = {}
    if (
        isinstance(last, dict)
        and type(last.get('phase')) is str
        and last['phase'] in phases
        and type(last.get('calls')) is int
        and 1 <= last['calls'] <= 1000000
        and number(last.get('seconds'))
        and number(last.get('elapsed_seconds'))
    ):
        value['checkpoint_last_completed'] = {key: last[key] for key in ('phase', 'calls', 'seconds', 'elapsed_seconds')}
    progress = report.get('checkpoint_progress')
    value['checkpoint_progress'] = {}
    if (
        isinstance(progress, dict)
        and progress.get('last_completed_phase')
        in ('setup', 'cursor_iteration', 'cursor_loop', 'external_stop', 'external_start', 'rollback_test', 'verify_reopen')
        and type(progress.get('completed_iterations')) is int
        and 0 <= progress['completed_iterations'] <= 120
        and number(progress.get('sample_elapsed_seconds'))
        and number(progress.get('prior_publication_seconds'))
    ):
        value['checkpoint_progress'] = {
            key: progress[key] for key in ('last_completed_phase', 'completed_iterations', 'sample_elapsed_seconds', 'prior_publication_seconds')
        }
        samples = progress.get('iteration_samples')
        value['checkpoint_progress']['iteration_samples'] = (
            [
                {key: row[key] for key in ('iteration', 'wall_seconds', 'cpu_seconds')}
                for row in samples[:120]
                if isinstance(row, dict)
                and type(row.get('iteration')) is int
                and 1 <= row['iteration'] <= 120
                and number(row.get('wall_seconds'))
                and number(row.get('cpu_seconds'))
            ]
            if isinstance(samples, list)
            else []
        )
    value['iteration_sample_semantics'] = 'total completed iteration wall/CPU costs; excludes checkpoint publication'
    active = report.get('active', [])
    value['checkpoint_active'] = (
        [
            {'phase': row['phase'], 'seconds': row['seconds']}
            for row in active[:32]
            if isinstance(row, dict) and type(row.get('phase')) is str and row['phase'] in phases and number(row.get('seconds'))
        ]
        if isinstance(active, list)
        else []
    )
    return value


def _preserve_connection_failure(diagnostics):
    """Failure-only reuse of the existing atomic bounded writer/upload pattern."""
    try:
        import uuid

        directory = Path(__file__).resolve().parents[1] / 'dist' / 'validation'
        directory.mkdir(parents=True, exist_ok=True)
        _write_json(
            directory / ('smoke-timeout-paper-connection-' + uuid.uuid4().hex + '.json'),
            {'scope': 'original connection diagnostic failure; not product acceptance', 'timeout_seconds': 10, 'commits_required': 120, **diagnostics},
        )
    except Exception:
        pass  # Artifact failure cannot replace the original assertion.


class PaperDiagnosticTests(unittest.TestCase):
    def test_wrapped_sqlite_preserves_full_sync_commit_rollback_and_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'replays' / 'synthetic.sqlite3'
            path.parent.mkdir()
            timings = Timings()
            connect = _instrument_connect(sqlite3.connect, timings)
            db = connect(path)
            try:
                db.execute('PRAGMA synchronous=FULL')
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
                with db:
                    db.execute('CREATE TABLE example (value INTEGER)')
                    db.execute('INSERT INTO example VALUES (?)', (7,))
                with self.assertRaises(RuntimeError):
                    with db:
                        db.execute('UPDATE example SET value=9')
                        raise RuntimeError('rollback')
                self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0], 7)
            finally:
                db.close()
            ordinary = sqlite3.connect(path)
            try:
                self.assertEqual(ordinary.execute('SELECT value FROM example').fetchone()[0], 7)
                self.assertEqual(ordinary.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            finally:
                ordinary.close()
            values = timings.snapshot()
            self.assertEqual(values['timings']['replay.transaction_exit']['calls'], 2)
            self.assertEqual(values['timings']['replay.connect']['calls'], 1)
            self.assertEqual(values['timings']['replay.close']['calls'], 1)
            self.assertEqual(values['active'], [])

    def test_timer_preserves_exception_and_does_not_record_arguments(self):
        timings = Timings()
        with self.assertRaisesRegex(ValueError, 'do not log me'):
            with timings.measure('fixed_phase'):
                raise ValueError('do not log me')
        snapshot = timings.snapshot()
        self.assertNotIn('do not log me', json.dumps(snapshot))
        self.assertEqual(snapshot['timings']['fixed_phase']['calls'], 1)
        self.assertEqual(snapshot['active'], [])

    def test_elapsed_checkpoint_rule_preserves_boundary_and_uses_publication_finish(self):
        from tools.diagnose_paper_replay import _connection_checkpoint_due

        # A slow publication consumes no part of the NEXT observation interval.
        self.assertTrue(_connection_checkpoint_due(30, 5, 5))
        self.assertFalse(_connection_checkpoint_due(31, 5.99, 5))
        self.assertTrue(_connection_checkpoint_due(31, 6, 5))
        self.assertFalse(_connection_checkpoint_due(32, 8.99, 8))
        self.assertTrue(_connection_checkpoint_due(32, 9, 8))

    def test_probe_publishes_only_completed_iterations_and_resets_after_slow_write(self):
        import os
        import sys
        import tools.diagnose_paper_replay as diagnostic

        clock_state = {'now': 100.0, 'consumed': 0}
        snapshots = []
        slow_publication = []

        def clock():
            frame = sys._getframe(1)
            while frame is not None and frame.f_code.co_name != '_connection_probe':
                frame = frame.f_back
            completed = frame.f_locals.get('consumed', 0) if frame is not None else 0
            if completed > clock_state['consumed']:
                clock_state['now'] += (completed - clock_state['consumed']) * 0.25
                clock_state['consumed'] = completed
            return clock_state['now']

        real_write = diagnostic._write_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'replays' / 'probe.sqlite3'
            output = root / 'probe.json'

            def publish(path, value):
                real_write(path, value)
                if path == output:
                    progress = value['checkpoint_progress']
                    if value['phase'] == 'cursor_loop' and progress['completed_iterations']:
                        snapshots.append(dict(progress, iteration_samples=list(progress['iteration_samples'])))
                        if not slow_publication:
                            clock_state['now'] += 3  # Synthetic report cost, no blocking wait.
                            slow_publication.append(progress['completed_iterations'])
                for action in ('stop', 'start'):
                    if path == output.with_suffix('.ready-' + action + '.json'):
                        # A synthetic in-process witness drives the existing SQL
                        # observer. Original native two-process tests stay intact.
                        with patch.object(diagnostic.os, 'getpid', return_value=os.getpid() + 1):
                            diagnostic._connection_observer(output.with_suffix('.' + action + '.json'), 'delete-reopen', root, action)

            with (
                patch.object(diagnostic, '_owned_connection_path', return_value=database),
                patch.object(diagnostic.time, 'perf_counter', side_effect=clock),
                patch.object(diagnostic, '_write_json', side_effect=publish),
            ):
                self.assertEqual(diagnostic._connection_probe(output, 'delete-reopen', root), 0)
        self.assertEqual(slow_publication, [4])
        self.assertEqual([row['completed_iterations'] for row in snapshots[:2]], [4, 8])
        self.assertEqual(snapshots[1]['prior_publication_seconds'], 3)
        self.assertIn(30, [row['completed_iterations'] for row in snapshots])
        for row in snapshots:
            self.assertEqual(row['last_completed_phase'], 'cursor_iteration')
            self.assertEqual(len(row['iteration_samples']), row['completed_iterations'])
            self.assertEqual(row['iteration_samples'][-1]['iteration'], row['completed_iterations'])
            self.assertGreaterEqual(row['sample_elapsed_seconds'], 0)

    def test_phase_cost_and_last_completion_are_numeric_observation_only(self):
        with patch('tools.diagnose_paper_replay.time.perf_counter', side_effect=[100, 101, 103, 104, 105, 106]):
            timings = Timings()
            with timings.measure('replay.cursor_commit'):
                pass
            with timings.measure('replay.cursor_commit'):
                pass
            snapshot = timings.snapshot()
        self.assertEqual(snapshot['timings']['replay.cursor_commit'], {'calls': 2, 'seconds': 3, 'max_seconds': 2})
        self.assertEqual(snapshot['last_completed'], {'phase': 'replay.cursor_commit', 'calls': 2, 'seconds': 1, 'elapsed_seconds': 5})
        self.assertEqual(snapshot['elapsed_seconds'], 6)
        self.assertEqual(snapshot['active'], [])

    def test_diagnostic_output_is_atomic_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            _write_json(path, {'observation_only': True})
            self.assertEqual(json.loads(path.read_text()), {'observation_only': True})
            with self.assertRaises(ValueError):
                _write_json(path, {'oversized': 'x' * (256 * 1024)})
            self.assertEqual(json.loads(path.read_text()), {'observation_only': True})
            self.assertFalse(path.with_suffix('.partial').exists())

    def test_rollback_modes_verify_full_sync_and_keep_real_commit_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('DELETE', 'TRUNCATE', 'PERSIST'):
                with self.subTest(mode=mode):
                    path = Path(directory) / (mode + '.sqlite3')
                    with _rollback_connection(sqlite3.connect, path, mode) as db:
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], mode.lower())
                        self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
                        db.execute('CREATE TABLE replay (cursor INTEGER)')
                        db.execute('INSERT INTO replay VALUES (960)')
                    with self.assertRaises(RuntimeError):
                        with _rollback_connection(sqlite3.connect, path, mode) as db:
                            db.execute('UPDATE replay SET cursor=-1')
                            raise RuntimeError('rollback')
                    db = sqlite3.connect(path)
                    try:
                        self.assertEqual(db.execute('SELECT cursor FROM replay').fetchone()[0], 960)
                        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    finally:
                        db.close()

    def test_unsupported_or_unselected_mode_fails_before_probe_writes(self):
        connect = MagicMock()
        with self.assertRaises(ValueError):
            with _rollback_connection(connect, 'unused', 'WAL'):
                self.fail('WAL must not be used by this comparison')
        connect.assert_not_called()
        db = connect.return_value
        db.execute.return_value.fetchone.return_value = ('delete',)
        with self.assertRaises(RuntimeError):
            with _rollback_connection(connect, 'unused', 'PERSIST'):
                self.fail('Unselected mode must fail closed')
        db.__enter__.assert_not_called()
        db.close.assert_called_once()
        self.assertTrue(all(call.args[0].startswith('PRAGMA ') for call in db.execute.call_args_list))

    def test_journal_timeout_removes_only_controller_owned_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / 'keep.txt'
            sentinel.write_text('keep')
            roots = set()

            def timeout(command, **kwargs):
                root = Path(command[command.index('--journal-root') + 1])
                roots.add(root)
                (root / 'owned.txt').write_text('disposable')
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])

            with patch('subprocess.run', side_effect=timeout):
                results = _journal_mode_comparison(output, time.monotonic() + 10)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(item['timed_out'] and not item['complete'] for item in results))
            self.assertTrue(roots and all(not root.exists() for root in roots))
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_partial_commit_counts_cannot_be_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as directory:

            def partial(command, **kwargs):
                mode = command[command.index('--journal-child') + 1]
                _write_json(
                    Path(command[2]),
                    {
                        'mode': mode,
                        'complete': True,
                        'commits_completed': 959,
                        'rollback_and_reopen_verified': True,
                        'verified_pragmas': {'journal_mode': mode.lower(), 'synchronous': 2},
                        'timings': {'replay.cursor_commit': {'calls': 959}},
                    },
                )
                return subprocess.CompletedProcess(command, 0)

            with patch('subprocess.run', side_effect=partial):
                results = _journal_mode_comparison(Path(directory), time.monotonic() + 10)
            self.assertEqual(len(results), 3)
            self.assertFalse(any(item['complete'] for item in results))


class ConnectionDiagnosticTests(unittest.TestCase):
    def test_fixed_matrix_uses_full_commits_real_external_control_and_owned_cleanup(self):
        import io
        import os
        from tools.diagnose_paper_replay import observe_connections, CONNECTION_PROFILES

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            sentinel = base / 'keep.txt'
            sentinel.write_text('keep')
            output = base / 'comparison.json'
            before = {key: os.environ.get(key) for key in ('TEMP', 'TMP')}
            with (
                patch.dict(os.environ, {'RUNNER_TEMP': str(base)}),
                patch('tempfile.gettempdir', return_value=str(base)),
                patch('sys.stdout', new=io.StringIO()),
            ):
                self.assertEqual(observe_connections(output), 0)
            self.assertEqual({key: os.environ.get(key) for key in ('TEMP', 'TMP')}, before)
            result = json.loads(output.read_text())
            self.assertTrue(result['observation_only'])
            self.assertTrue(result['complete'])
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['same_canonical_root'])
            self.assertTrue(result['same_volume'])
            self.assertEqual(result['acceptance_timeout_unchanged'], 30)
            self.assertEqual(result['acceptance_workload_unchanged'], 960)
            self.assertEqual(result['commits_per_profile'], 240)
            expected = [('os_temp', profile) for profile in CONNECTION_PROFILES] + [('runner_temp', 'delete-reopen')]
            cases = result['comparisons']
            self.assertEqual([(c['location'], c['profile']) for c in cases], expected + list(reversed(expected)))
            for case in cases:
                proof = case['observation']
                self.assertTrue(case['complete'])
                self.assertTrue(case['workers_stopped'])
                self.assertTrue(case['fixture_removed'])
                self.assertFalse(Path(case['fixture_root']).exists())
                self.assertEqual(proof['commits_completed'], 120)
                self.assertEqual(proof['timings']['replay.cursor_commit']['calls'], 120)
                self.assertEqual(proof['timings']['replay.cursor_rollback']['calls'], 1)
                self.assertEqual(proof['verified_pragmas'], {'journal_mode': case['profile'].split('-')[0], 'synchronous': 2, 'locking_mode': 'normal'})
                self.assertTrue(proof['rollback_and_reopen_verified'])
                self.assertTrue(proof['external_control_verified'])
                self.assertEqual(proof['external_stop']['active'], 0)
                self.assertEqual(proof['external_start']['active'], 1)
                self.assertNotEqual(proof['pid'], proof['external_stop']['pid'])
                self.assertNotEqual(proof['pid'], proof['external_start']['pid'])
                self.assertEqual(proof['active'], [])
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_real_deadline_terminates_and_joins_only_owned_child_before_removal(self):
        import sys
        from tools.diagnose_paper_replay import _connection_case

        real_popen = subprocess.Popen
        children = []

        def sleeping_child(command, **kwargs):
            child = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'keep.txt'
            sentinel.write_text('keep')
            with patch('subprocess.Popen', side_effect=sleeping_child):
                result = _connection_case(Path(directory) / 'timeout.json', 'persist-step', directory, time.monotonic() + 0.15)
            self.assertTrue(result['timed_out'])
            self.assertFalse(result['complete'])
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])
            self.assertTrue(children and all(child.poll() is not None for child in children))
            self.assertEqual(result['returncode'], children[0].returncode)
            self.assertIsNotNone(result['returncode'])
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_external_observer_failure_stops_waiting_probe_and_cleans_owned_fixture(self):
        from tools.diagnose_paper_replay import _connection_case
        import sys

        real_popen = subprocess.Popen
        children = []

        def failed_observer(command, **kwargs):
            role = 'probe'
            if '--connection-observer' in command:
                role = 'observer_' + command[command.index('--connection-observer') + 1]
                command = [sys.executable, '-c', 'raise SystemExit(1)']
            child = real_popen(command, **kwargs)
            children.append((role, child))
            return child

        with tempfile.TemporaryDirectory() as directory:
            with patch('subprocess.Popen', side_effect=failed_observer):
                result = _connection_case(Path(directory) / 'observer.json', 'persist-step', directory, time.monotonic() + 10)
            observation = result.get('observation', {})
            diagnostics = {
                key: result.get(key)
                for key in (
                    'returncode',
                    'timed_out',
                    'error_type',
                    'cleanup_error_type',
                    'workers_stopped',
                    'fixture_removed',
                    'seconds',
                    'observer_actions_completed',
                )
            }
            diagnostics.update(
                phase=observation.get('phase'),
                commits_completed=observation.get('commits_completed'),
                cursor_commit_calls=observation.get('timings', {}).get('replay.cursor_commit', {}).get('calls'),
                probe_error_type=observation.get('error_type'),
                probe_seconds=observation.get('elapsed_seconds'),
                child_exits=[{'role': role, 'returncode': child.returncode} for role, child in children],
            )
            self.assertFalse(result['complete'], diagnostics)
            self.assertTrue(result['workers_stopped'], diagnostics)
            self.assertTrue(result['fixture_removed'], diagnostics)
            # A deadline before observer injection is still a failure, and now
            # reports the actual branch instead of hiding it behind KeyError.
            self.assertFalse(result.get('timed_out'), diagnostics)
            self.assertIn('error_type', result, diagnostics)
            self.assertEqual(result['error_type'], 'RuntimeError', diagnostics)
            self.assertEqual([role for role, _ in children], ['probe', 'observer_stop'], diagnostics)
            self.assertEqual(children[-1][1].returncode, 1, diagnostics)
            self.assertTrue(all(child.poll() is not None for _, child in children), diagnostics)
            self.assertEqual(observation.get('commits_completed'), 120, diagnostics)
            self.assertEqual(diagnostics['cursor_commit_calls'], 120, diagnostics)

    def test_wrong_commit_count_cannot_be_certified(self):
        from tools.diagnose_paper_replay import _connection_case

        original_loads = json.loads

        def wrong_count(raw, *args, **kwargs):
            value = original_loads(raw, *args, **kwargs)
            if value.get('phase') == 'complete':
                value['commits_completed'] = 119
            return value

        with tempfile.TemporaryDirectory() as directory:
            with patch('tools.diagnose_paper_replay.json.loads', side_effect=wrong_count):
                result = _connection_case(Path(directory) / 'partial.json', 'delete-reopen', directory, time.monotonic() + 10)
            observation = result.get('observation', {})
            diagnostics = {
                key: result.get(key) for key in ('returncode', 'timed_out', 'error_type', 'cleanup_error_type', 'workers_stopped', 'fixture_removed', 'seconds')
            }
            diagnostics.update(
                phase=observation.get('phase'),
                commits_completed=observation.get('commits_completed'),
                cursor_commit_calls=observation.get('timings', {}).get('replay.cursor_commit', {}).get('calls'),
                probe_error_type=observation.get('error_type'),
                probe_seconds=observation.get('elapsed_seconds'),
            )
            try:
                diagnostics.update(_connection_checkpoint_fields(result))
            except Exception:
                diagnostics['checkpoint_observation_failed'] = True
            try:
                self.assertEqual(result['returncode'], 0, diagnostics)
                self.assertFalse(result.get('timed_out'), diagnostics)
                self.assertNotIn('error_type', result, diagnostics)
                self.assertEqual(observation.get('phase'), 'complete', diagnostics)
                self.assertEqual(observation.get('commits_completed'), 119, diagnostics)
                self.assertEqual(diagnostics['cursor_commit_calls'], 120, diagnostics)
                self.assertFalse(result['complete'], diagnostics)
                self.assertTrue(result['workers_stopped'], diagnostics)
                self.assertTrue(result['fixture_removed'], diagnostics)
            except AssertionError:
                _preserve_connection_failure(diagnostics)
                raise

    def test_late_zero_exit_cannot_certify_timeout_or_controller_error(self):
        from tools.diagnose_paper_replay import _connection_case

        # Synthetic process states isolate certification from disk speed. The
        # existing real-probe tests retain all 120 FULL commits and deadlines.
        for error in (None, subprocess.TimeoutExpired('controlled probe', 0), RuntimeError('controlled controller failure')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'controlled.json'
                _write_json(
                    output,
                    {
                        'profile': 'delete-reopen',
                        'complete': True,
                        'commits_completed': 120,
                        'rollback_and_reopen_verified': True,
                        'external_control_verified': True,
                        'verified_pragmas': {'journal_mode': 'delete', 'synchronous': 2, 'locking_mode': 'normal'},
                        'timings': {'replay.cursor_commit': {'calls': 120}, 'replay.cursor_rollback': {'calls': 1}},
                        'last_completed': {'phase': 'replay.verify_reopen', 'calls': 1, 'seconds': 0.1, 'elapsed_seconds': 0.9},
                        'checkpoint_progress': {
                            'last_completed_phase': 'verify_reopen',
                            'completed_iterations': 120,
                            'sample_elapsed_seconds': 0.9,
                            'prior_publication_seconds': 0.01,
                            'iteration_samples': [],
                        },
                    },
                )
                for action in ('stop', 'start'):
                    _write_json(output.with_suffix('.ready-' + action + '.json'), {'action': action})
                probe = MagicMock(pid=101, returncode=None)
                probe.poll.side_effect = lambda: probe.returncode
                helpers = [MagicMock(pid=pid, returncode=0) for pid in (102, 103)]
                for helper in helpers:
                    helper.poll.return_value = 0

                def exit_before_next_poll(_seconds):
                    probe.returncode = 0
                    if error is not None:
                        raise error

                with patch('subprocess.Popen', side_effect=[probe, *helpers]), patch('time.sleep', side_effect=exit_before_next_poll):
                    result = _connection_case(output, 'delete-reopen', directory, time.monotonic() + 10)
                self.assertEqual(result['returncode'], 0)
                self.assertEqual(result['complete'], error is None)
                self.assertTrue(result['workers_stopped'])
                self.assertTrue(result['fixture_removed'])
                self.assertEqual(result['observer_actions_completed'], ['stop', 'start'])
                self.assertTrue(all(child['returncode'] == 0 for child in result['children']))
                if isinstance(error, subprocess.TimeoutExpired):
                    self.assertTrue(result['timed_out'])
                elif error is not None:
                    self.assertEqual(result['error_type'], type(error).__name__)

    def test_completed_diagnostic_fields_cannot_certify_wrong_or_incomplete_counts(self):
        from tools.diagnose_paper_replay import _connection_case

        # No real workload is replaced: isolate the existing certification seam.
        for complete, commits in ((False, 120), (True, 119), (True, 120)):
            with self.subTest(complete=complete, commits=commits), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'controlled.json'
                _write_json(
                    output,
                    {
                        'profile': 'delete-reopen',
                        'complete': complete,
                        'commits_completed': commits,
                        'rollback_and_reopen_verified': True,
                        'external_control_verified': True,
                        'verified_pragmas': {'journal_mode': 'delete', 'synchronous': 2, 'locking_mode': 'normal'},
                        'timings': {
                            'replay.cursor_commit': {'calls': 120, 'seconds': 1, 'max_seconds': 0.1},
                            'replay.cursor_rollback': {'calls': 1},
                            'replay.external_stop': {'calls': 1, 'seconds': 0.1, 'max_seconds': 0.1},
                            'replay.external_start': {'calls': 1, 'seconds': 0.1, 'max_seconds': 0.1},
                        },
                        'last_completed': {'phase': 'replay.verify_reopen', 'calls': 1, 'seconds': 0.1, 'elapsed_seconds': 1},
                        'completed_cursor_commits': 120,
                        'checkpoint_progress': {
                            'last_completed_phase': 'verify_reopen',
                            'completed_iterations': 120,
                            'sample_elapsed_seconds': 1,
                            'prior_publication_seconds': 0.01,
                            'iteration_samples': [{'iteration': 120, 'wall_seconds': 0.01, 'cpu_seconds': 0.001}],
                        },
                    },
                )
                for action in ('stop', 'start'):
                    _write_json(output.with_suffix('.ready-' + action + '.json'), {'action': action})
                probe = MagicMock(pid=101, returncode=None)
                probe.poll.side_effect = lambda: probe.returncode
                helpers = [MagicMock(pid=pid, returncode=0) for pid in (102, 103)]
                for helper in helpers:
                    helper.poll.return_value = 0

                def finish(_seconds):
                    probe.returncode = 0

                with patch('subprocess.Popen', side_effect=[probe, *helpers]), patch('time.sleep', side_effect=finish):
                    result = _connection_case(output, 'delete-reopen', directory, time.monotonic() + 10)
                self.assertEqual(result['complete'], complete and commits == 120)
                self.assertTrue(result['workers_stopped'])
                self.assertTrue(result['fixture_removed'])
                self.assertEqual(result['observer_actions_completed'], ['stop', 'start'])

    def test_unsupported_profile_or_unaccepted_settings_never_yield_a_connection(self):
        from tools.diagnose_paper_replay import _probe_connection

        connect = MagicMock()
        with self.assertRaises(ValueError):
            _probe_connection(connect, 'unused', 'wal-step')
        connect.assert_not_called()
        db = connect.return_value
        db.execute.return_value.fetchone.return_value = ('delete',)
        with self.assertRaises(RuntimeError):
            _probe_connection(connect, 'unused', 'delete-step')
        db.close.assert_called_once()
        self.assertTrue(all(call.args[0].startswith('PRAGMA ') for call in db.execute.call_args_list))

    def test_missing_runner_temp_is_reported_without_substituting_a_volume(self):
        import io
        import os
        from tools.diagnose_paper_replay import observe_connections

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {}, clear=True),
                patch('sys.stdout', new=io.StringIO()),
                patch('tools.diagnose_paper_replay._connection_case', return_value={'complete': True, 'workers_stopped': True, 'fixture_removed': True}),
            ):
                output = Path(directory) / 'missing.json'
                self.assertEqual(observe_connections(output), 1)
            result = json.loads(output.read_text())
            self.assertFalse(result['complete'])
            self.assertIsNone(result['runner_temp'])
            missing = [case for case in result['comparisons'] if case['location'] == 'runner_temp']
            self.assertEqual(len(missing), 2)
            self.assertTrue(all(case['not_started'] and case['reason'] == 'RUNNER_TEMP unavailable' for case in missing))

    def test_expired_deadline_starts_no_process(self):
        from tools.diagnose_paper_replay import _connection_case

        with patch('subprocess.Popen') as start:
            result = _connection_case(Path('unused'), 'delete-reopen', 'unused', time.monotonic() - 1)
        start.assert_not_called()
        self.assertFalse(result['complete'])
        self.assertTrue(result['not_started'])
        self.assertIsNone(result['returncode'])

    def test_internal_probe_rejects_unowned_root_before_opening_sqlite(self):
        from tools.diagnose_paper_replay import _connection_probe, _connection_observer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('tools.diagnose_paper_replay.sqlite3.connect') as connect:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    _connection_probe(root / 'result.json', 'delete-reopen', root)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    _connection_observer(root / 'result.json', 'delete-reopen', root, 'stop')
            connect.assert_not_called()

    def test_keyboard_interrupt_joins_probe_and_observer_before_removing_fixture(self):
        import sys
        from tools.diagnose_paper_replay import _connection_case

        real_popen = subprocess.Popen
        children = []

        def interrupt_observer(command, **kwargs):
            observer = '--connection-observer' in command
            if observer:
                command = [sys.executable, '-c', 'import time; time.sleep(60)']
            child = real_popen(command, **kwargs)
            children.append(child)
            if observer:
                original_wait = child.wait
                interrupted = False

                def wait(timeout=None):
                    nonlocal interrupted
                    if not interrupted:
                        interrupted = True
                        raise KeyboardInterrupt()
                    return original_wait(timeout=timeout)

                child.wait = wait
            return child

        with tempfile.TemporaryDirectory() as directory:
            with patch('subprocess.Popen', side_effect=interrupt_observer):
                result = _connection_case(Path(directory) / 'interrupted.json', 'persist-step', directory, time.monotonic() + 10)
            self.assertFalse(result['complete'])
            self.assertEqual(result['error_type'], 'KeyboardInterrupt')
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])
            self.assertEqual(len(children), 2)
            self.assertTrue(all(child.returncode is not None for child in children))
            self.assertTrue(all(child['returncode'] is not None for child in result['children']))


class ConnectionFailureEvidenceTests(unittest.TestCase):
    def test_milestone_failure_preserves_certification_and_owned_child_cleanup(self):
        import sys
        import tools.diagnose_paper_replay as diagnostic

        original_clock, original_case = time.perf_counter, diagnostic._connection_case
        observations = []

        def clock():
            if sys._getframe(1).f_code.co_name == 'mark':
                raise OSError('controlled observation failure')
            return original_clock()

        def collect(*args, **kwargs):
            result = original_case(*args, **kwargs)
            observations.append(result)
            return result

        # Reuse the synthetic success/late-exit certification control, with
        # every new milestone clock failing. No real SQL workload is repeated.
        with patch('time.perf_counter', new=clock), patch.object(diagnostic, '_connection_case', side_effect=collect):
            case = ConnectionDiagnosticTests('test_late_zero_exit_cannot_certify_timeout_or_controller_error')
            case.test_late_zero_exit_cannot_certify_timeout_or_controller_error()
        self.assertEqual([result['complete'] for result in observations], [True, False, False])
        self.assertTrue(all(result['controller_observation_failed'] for result in observations))
        child = MagicMock(pid=101, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        child.terminate.side_effect = lambda: setattr(child, 'returncode', 1)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch('time.perf_counter', new=clock),
            patch('subprocess.Popen', return_value=child),
            patch('time.sleep', side_effect=subprocess.TimeoutExpired('controlled probe', 0)),
        ):
            result = original_case(Path(directory) / 'controlled.json', 'delete-reopen', directory, time.monotonic() + 10)
        child.terminate.assert_called_once()
        self.assertTrue(result['timed_out'])
        self.assertTrue(result['controller_observation_failed'])
        self.assertTrue(result['workers_stopped'])
        self.assertTrue(result['fixture_removed'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['children'], [{'pid': 101, 'returncode': 1}])

    def test_checkpoint_evidence_retains_only_bounded_numeric_fields_and_known_labels(self):
        result = {
            'controller_milestones': {
                'probe_launch_returned': 0.2,
                'timeout_observed': 10,
                'private_path': '/DO_NOT_RETAIN',
                'process_cleanup_finished': float('inf'),
            },
            'observation': {
                'elapsed_seconds': 2.7,
                'pre_timing_seconds': 0.01,
                'probe_entry_seconds': 2.71,
                'process_cpu_seconds': 0.3,
                'fixture_root': '/DO_NOT_RETAIN',
                'timings': {
                    'replay.cursor_commit': {'calls': 90, 'seconds': 2.1, 'max_seconds': 0.2, 'sql': 'DO_NOT_RETAIN'},
                    'replay.external_stop': {'calls': 1, 'seconds': 0.3, 'max_seconds': float('nan')},
                    'replay.read': {'calls': True, 'seconds': 1},
                    'replay.close': {'calls': 90, 'seconds': 10**1000},
                    'DO_NOT_RETAIN': {'calls': 1, 'seconds': 1},
                },
                'active': [
                    {'phase': 'replay.cursor_loop', 'seconds': 2.6, 'path': '/DO_NOT_RETAIN'},
                    {'phase': 'DO_NOT_RETAIN', 'seconds': 1},
                    {'phase': [], 'seconds': 1},
                ],
                'last_completed': {'phase': 'replay.cursor_commit', 'calls': 90, 'seconds': 0.1, 'elapsed_seconds': 2.6, 'sql': 'DO_NOT_RETAIN'},
            },
        }
        evidence = _connection_checkpoint_fields(result)
        self.assertEqual(evidence['controller_milestones'], {'probe_launch_returned': 0.2, 'timeout_observed': 10})
        self.assertEqual(
            evidence['checkpoint_timings'],
            {'replay.cursor_commit': {'calls': 90, 'seconds': 2.1, 'max_seconds': 0.2}, 'replay.external_stop': {'calls': 1, 'seconds': 0.3}},
        )
        self.assertEqual(evidence['checkpoint_last_completed'], {'phase': 'replay.cursor_commit', 'calls': 90, 'seconds': 0.1, 'elapsed_seconds': 2.6})
        self.assertEqual(evidence['checkpoint_active'], [{'phase': 'replay.cursor_loop', 'seconds': 2.6}])
        self.assertEqual(evidence['probe_clocks']['pre_timing_seconds'], 0.01)
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(evidence))
        self.assertLess(len(json.dumps(evidence)), 32768)
        self.assertIn('not deadline state', evidence['checkpoint_semantics'])
        self.assertIn('detection time', evidence['controller_milestone_semantics'])

    def test_malformed_last_completion_and_maximum_cannot_escape_evidence_bounds(self):
        malformed = (
            {'phase': 'DO_NOT_RETAIN', 'calls': 1, 'seconds': 1, 'elapsed_seconds': 1},
            {'phase': 'replay.close', 'calls': True, 'seconds': 1, 'elapsed_seconds': 1},
            {'phase': 'replay.close', 'calls': 1, 'seconds': float('inf'), 'elapsed_seconds': 1},
            {'phase': 'replay.close', 'calls': 1, 'seconds': 1, 'elapsed_seconds': -1},
            None,
            [],
        )
        for last in malformed:
            with self.subTest(last=last):
                evidence = _connection_checkpoint_fields(
                    {'observation': {'last_completed': last, 'timings': {'replay.close': {'calls': 1, 'seconds': 0.1, 'max_seconds': True}}}}
                )
                self.assertEqual(evidence.get('checkpoint_last_completed'), {})
                self.assertEqual(evidence['checkpoint_timings'], {'replay.close': {'calls': 1, 'seconds': 0.1}})
                self.assertNotIn('DO_NOT_RETAIN', json.dumps(evidence))

    def test_progress_evidence_is_bounded_and_preserves_stale_checkpoint_meaning(self):
        progress = {
            'last_completed_phase': 'cursor_iteration',
            'completed_iterations': 60,
            'sample_elapsed_seconds': 4.2,
            'prior_publication_seconds': 0.01,
            'iteration_samples': [{'iteration': 1, 'wall_seconds': 0.1, 'cpu_seconds': 0.01, 'sql': 'DO_NOT_RETAIN'}] * 130,
        }
        result = {'observation': {'checkpoint_progress': progress}}
        evidence = _connection_checkpoint_fields(result)
        self.assertEqual(len(evidence['checkpoint_progress']['iteration_samples']), 120)
        self.assertEqual(evidence['checkpoint_progress']['completed_iterations'], 60)
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(evidence))
        self.assertIn('total completed iteration', evidence['iteration_sample_semantics'])
        self.assertIn('not deadline state', evidence['checkpoint_semantics'])
        self.assertLess(len(json.dumps(evidence)), 32768)
        for key, bad in (
            ('last_completed_phase', 'DO_NOT_RETAIN'),
            ('completed_iterations', True),
            ('completed_iterations', 121),
            ('sample_elapsed_seconds', float('nan')),
            ('prior_publication_seconds', -1),
        ):
            with self.subTest(field=key):
                changed = dict(progress, **{key: bad})
                value = _connection_checkpoint_fields({'observation': {'checkpoint_progress': changed}})
                self.assertEqual(value['checkpoint_progress'], {})

    def test_actual_failure_handler_preserves_original_assertion_and_original_deadline(self):
        result = {
            'returncode': 1,
            'timed_out': True,
            'complete': False,
            'workers_stopped': True,
            'fixture_removed': True,
            'seconds': 10.02,
            'controller_milestones': {'timeout_observed': 10},
            'observation': {
                'phase': 'cursor_loop',
                'commits_completed': 90,
                'elapsed_seconds': 2.7,
                'timings': {'replay.cursor_commit': {'calls': 90, 'seconds': 2, 'max_seconds': 0.1}},
                'last_completed': {'phase': 'replay.close', 'calls': 180, 'seconds': 0.01, 'elapsed_seconds': 2.6},
                'checkpoint_progress': {
                    'last_completed_phase': 'cursor_iteration',
                    'completed_iterations': 90,
                    'sample_elapsed_seconds': 2.7,
                    'prior_publication_seconds': 0.001,
                    'iteration_samples': [{'iteration': 90, 'wall_seconds': 0.03, 'cpu_seconds': 0.001, 'sql': 'DO_NOT_RETAIN'}],
                },
            },
        }
        for failed_write in (False, True):
            with self.subTest(failed_write=failed_write):
                case = ConnectionDiagnosticTests('test_wrong_commit_count_cannot_be_certified')
                original = AssertionError('original gate')
                with (
                    patch('tools.diagnose_paper_replay._connection_case', return_value=result) as run,
                    patch.object(case, 'assertEqual', side_effect=original),
                    patch('time.monotonic', return_value=100),
                    patch(__name__ + '._write_json', side_effect=OSError('private failure') if failed_write else None) as write,
                    self.assertRaises(AssertionError) as raised,
                ):
                    case.test_wrong_commit_count_cannot_be_certified()
                self.assertIs(raised.exception, original)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[1], 'delete-reopen')
                self.assertEqual(run.call_args.args[3], 110)
                path, evidence = write.call_args.args
                self.assertTrue(path.name.startswith('smoke-timeout-paper-connection-'))
                self.assertEqual(evidence['timeout_seconds'], 10)
                self.assertEqual(evidence['commits_required'], 120)
                self.assertEqual(evidence['commits_completed'], 90)
                self.assertEqual(evidence['checkpoint_timings']['replay.cursor_commit']['calls'], 90)
                self.assertEqual(evidence['checkpoint_timings']['replay.cursor_commit']['max_seconds'], 0.1)
                self.assertEqual(evidence['checkpoint_progress']['last_completed_phase'], 'cursor_iteration')
                self.assertEqual(evidence['checkpoint_progress']['completed_iterations'], 90)
                self.assertEqual(evidence['checkpoint_progress']['prior_publication_seconds'], 0.001)
                self.assertEqual(evidence['checkpoint_last_completed']['phase'], 'replay.close')
                self.assertNotIn('DO_NOT_RETAIN', json.dumps(evidence))

    def test_evidence_construction_failure_does_not_replace_original_assertion(self):
        case = ConnectionDiagnosticTests('test_wrong_commit_count_cannot_be_certified')
        original = AssertionError('original gate')
        with (
            patch('tools.diagnose_paper_replay._connection_case', return_value={'returncode': 1}),
            patch.object(case, 'assertEqual', side_effect=original),
            patch(__name__ + '._connection_checkpoint_fields', side_effect=ValueError('private failure')),
            patch(__name__ + '._preserve_connection_failure') as record,
            self.assertRaises(AssertionError) as raised,
        ):
            case.test_wrong_commit_count_cannot_be_certified()
        self.assertIs(raised.exception, original)
        self.assertTrue(record.call_args.args[0]['checkpoint_observation_failed'])


class DiagnosticWorkerArgumentsTests(unittest.TestCase):
    def test_passthrough_preserves_new_reconciliation_argument_and_legacy_default(self):
        import tools.diagnose_paper_replay as diagnostic

        args = (object(), object(), 'ui_backtest', object(), 'owned-root', None, 'owned-job')
        marker = object()
        for admitted in (False, True, marker):
            with self.subTest(admitted=admitted), patch.object(diagnostic, '_original_worker') as worker:
                self.assertIs(diagnostic._diagnosed_worker(*args, admitted), worker.return_value)
                self.assertEqual(worker.call_args.args[:7], args)
                self.assertIs(worker.call_args.args[7], admitted)
        with patch.object(diagnostic, '_original_worker') as worker:
            diagnostic._diagnosed_worker(*args)
            self.assertEqual(worker.call_args.args[:7], args)
            self.assertIs(worker.call_args.args[7], False)

    def test_measured_paper_path_forwards_argument_without_changing_sender_or_leaking_hooks(self):
        from contextlib import ExitStack
        import os
        import quantlab.paper as paper
        import quantlab.paper_replay as replay
        import tools.diagnose_paper_replay as diagnostic

        originals = [(paper.PaperBroker, name, getattr(paper.PaperBroker, name)) for name in ('_restore', 'snapshot')]
        originals += [(replay.PaperReplay, name, getattr(replay.PaperReplay, name)) for name in ('__init__', 'snapshot', '_quote_policy', 'step', '_fault')]
        original_connect = sqlite3.connect
        for admitted in (False, True, object()):
            with self.subTest(admitted=admitted), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {'MARKAUTO_DIAGNOSTIC_OUTPUT': directory}))
                stack.enter_context(patch.object(sqlite3, 'connect', original_connect))
                for cls, name, original in originals:
                    stack.enter_context(patch.object(cls, name, original))
                sender, gate, payload = MagicMock(), object(), object()

                def run(measured_sender, *args):
                    measured_sender.send_bytes(b'offline-observation')
                    measured_sender.close()

                worker = stack.enter_context(patch.object(diagnostic, '_original_worker', side_effect=run))
                diagnostic._diagnosed_worker(sender, gate, 'ui_paper_replay', payload, directory, None, 'probe', admitted)
                self.assertEqual(worker.call_args.args[1:7], (gate, 'ui_paper_replay', payload, directory, None, 'probe'))
                self.assertIs(worker.call_args.args[7], admitted)
                sender.send_bytes.assert_called_once_with(b'offline-observation')
                sender.close.assert_called_once()
                report = json.loads((Path(directory) / 'probe.json').read_text())
                self.assertEqual(report['timings']['worker.body']['calls'], 1)
                self.assertEqual(report['timings']['ipc.send']['calls'], 1)
                self.assertEqual(report['active'], [])
            self.assertIs(sqlite3.connect, original_connect)
            for cls, name, original in originals:
                self.assertIs(getattr(cls, name), original)
