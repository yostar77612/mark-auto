"""Instrumentation must observe real SQLite semantics without weakening gates."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import subprocess
import time

from tools.diagnose_paper_replay import (Timings, _instrument_connect, _write_json,
                                         _rollback_connection, _journal_mode_comparison)


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
                _write_json(Path(command[2]), {'mode': mode, 'complete': True,
                    'commits_completed': 959, 'rollback_and_reopen_verified': True,
                    'verified_pragmas': {'journal_mode': mode.lower(), 'synchronous': 2},
                    'timings': {'replay.cursor_commit': {'calls': 959}}})
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
            with patch.dict(os.environ, {'RUNNER_TEMP': str(base)}), \
                    patch('tempfile.gettempdir', return_value=str(base)), patch('sys.stdout', new=io.StringIO()):
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
                self.assertEqual(proof['verified_pragmas'], {'journal_mode': case['profile'].split('-')[0],
                                                           'synchronous': 2, 'locking_mode': 'normal'})
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
                result = _connection_case(Path(directory) / 'timeout.json', 'persist-step', directory,
                                          time.monotonic() + .15)
            self.assertTrue(result['timed_out'])
            self.assertFalse(result['complete'])
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])
            self.assertTrue(children and all(child.poll() is not None for child in children))
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_external_observer_failure_stops_waiting_probe_and_cleans_owned_fixture(self):
        from tools.diagnose_paper_replay import _connection_case
        import sys
        real_popen = subprocess.Popen
        def failed_observer(command, **kwargs):
            if '--connection-observer' in command:
                command = [sys.executable, '-c', 'raise SystemExit(1)']
            return real_popen(command, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            with patch('subprocess.Popen', side_effect=failed_observer):
                result = _connection_case(Path(directory) / 'observer.json', 'persist-step', directory,
                                          time.monotonic() + 10)
            self.assertFalse(result['complete'])
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])
            self.assertEqual(result['error_type'], 'RuntimeError')

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
                result = _connection_case(Path(directory) / 'partial.json', 'delete-reopen', directory,
                                          time.monotonic() + 10)
            self.assertEqual(result['returncode'], 0)
            self.assertFalse(result['complete'])
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])

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
            with patch.dict(os.environ, {}, clear=True), patch('sys.stdout', new=io.StringIO()), \
                    patch('tools.diagnose_paper_replay._connection_case', return_value={
                        'complete': True, 'workers_stopped': True, 'fixture_removed': True}):
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
                result = _connection_case(Path(directory) / 'interrupted.json', 'persist-step', directory,
                                          time.monotonic() + 10)
            self.assertFalse(result['complete'])
            self.assertEqual(result['error_type'], 'KeyboardInterrupt')
            self.assertTrue(result['workers_stopped'])
            self.assertTrue(result['fixture_removed'])
            self.assertEqual(len(children), 2)
            self.assertTrue(all(child.returncode is not None for child in children))
            self.assertTrue(all(child['returncode'] is not None for child in result['children']))
