"""Contracts for observation tooling, not product timing acceptance."""

import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, closing
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import diagnose_research_phases as diagnostic


class ResearchPhaseDiagnosticTests(unittest.TestCase):
    def test_fixed_cases_and_actual_default_temp_identity(self):
        identity = diagnostic.identity()
        self.assertEqual(identity['tempfile_gettempdir'], tempfile.gettempdir())
        self.assertEqual(identity['environment_temp']['RUNNER_TEMP'], os.environ.get('RUNNER_TEMP'))
        self.assertEqual(len(diagnostic.TESTS), 3)
        self.assertTrue(diagnostic.TESTS[0].endswith('test_saved_execution_evaluates_all_candidates_and_never_calls_model'))
        self.assertTrue(diagnostic.TESTS[1].endswith('test_saved_terminal_report_reads_without_sources_and_with_windows_registry_identity'))
        self.assertEqual(diagnostic.TESTS[2], 'tests.test_walk_forward.WalkForwardTests.test_registry_lock_cannot_overrun_deadline_or_reserve_after_it')
        self.assertIn('quantlab/walk_forward.py', identity['source_sha256'])
        windows_root = PureWindowsPath('C:/work/mark-auto')
        self.assertEqual(diagnostic.source_key(windows_root / 'quantlab/walk_forward.py', windows_root), 'quantlab/walk_forward.py')

    def test_real_sql_commit_json_bytes_and_profile_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = {'status': 'INCOMPLETE'}
            observer = diagnostic.Observer(report, root / 'report.json')
            original = sqlite3.connect
            with ExitStack() as stack:
                observer.instrument(stack)
                with closing(sqlite3.connect(root / 'state.db')) as db:
                    db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, payload TEXT)')
                    db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', ('é',))
                    db.commit()
                    with db:
                        db.execute('UPDATE state SET payload=? WHERE id=1', ('unchanged',))
                source = root / 'state.json.tmp'
                source.write_text('é', encoding='utf-8')
                source.replace(root / 'state.json')
            self.assertIs(sqlite3.connect, original)
            with closing(sqlite3.connect(root / 'state.db')) as db:
                self.assertEqual(db.execute('SELECT payload FROM state').fetchone(), ('unchanged',))
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone(), (2,))
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('delete',))
            self.assertEqual((root / 'state.json').read_bytes(), 'é'.encode())
            self.assertEqual(observer.phases['sqlite.commit']['completed'], 1)
            self.assertEqual(observer.phases['sqlite.context_commit']['completed'], 1)
            self.assertEqual(observer.phases['sqlite.execute']['payload_bytes'], 11)
            self.assertEqual(observer.phases['json.write_text']['payload_bytes'], 2)
            self.assertEqual(observer.phases['json.replace']['completed'], 1)
            self.assertEqual(report['sqlite_profiles'][0]['synchronous'], 2)
            observer.checkpoint()
            self.assertEqual(json.loads((root / 'report.json').read_text())['status'], 'INCOMPLETE')

    def test_state_initial_terminal_and_registry_subphases_preserve_boundaries(self):
        from quantlab import walk_forward as wf
        from quantlab.reporting import synthetic_dataset
        from tests.test_walk_forward_snapshot_serialization import state_with

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observer = diagnostic.Observer({}, root / 'report.json')
            state = state_with('phase fixture')
            state['status'] = 'running'
            with ExitStack() as stack:
                observer.instrument(stack)
                with closing(sqlite3.connect(root / 'walk_forward.sqlite3')) as db:
                    db.execute('BEGIN')
                    db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, payload TEXT)')
                    wf._save_state(db, root, state)
                    state['status'] = 'budget_exhausted'
                    wf._save_state(db, root, state)
                wf._reserve_holdout(
                    synthetic_dataset(10), registry_path=root / 'holdout.sqlite3', campaign_id='fixture', selection_hash='fixture', output_dir=root
                )
            for phase, count in {
                'wfo.initial_save': 1,
                'wfo.terminal_save': 1,
                'wfo._save_state': 2,
                'wfo._reserve_holdout': 1,
                'sqlite.state.execute.create': 1,
                'sqlite.state.execute.begin': 1,
                'sqlite.state.commit': 2,
                'sqlite.commit': 2,
                'sqlite.state.close': 1,
                'sqlite.registry.close': 1,
                'sqlite.registry.execute.begin': 1,
                'sqlite.registry.context_commit': 1,
                'json.replace': 2,
            }.items():
                with self.subTest(phase=phase):
                    self.assertEqual(observer.phases[phase]['completed'], count)
                    self.assertEqual(observer.phases[phase]['errors'], 0)
            self.assertNotIn('wfo.later_save', observer.phases)
            self.assertTrue(all(p['synchronous'] == 2 and p['journal_mode'] == 'delete' for p in observer.report['sqlite_profiles']))
            with closing(sqlite3.connect(root / 'walk_forward.sqlite3')) as db:
                payload = db.execute('SELECT payload FROM state').fetchone()[0]
            self.assertEqual((root / 'walk_forward.json').read_bytes(), payload.encode('utf-8'))

    def test_initial_and_close_profiles_record_wal_transition_and_full(self):
        with tempfile.TemporaryDirectory() as temporary:
            observer = diagnostic.Observer({}, Path(temporary) / 'report.json')
            with ExitStack() as stack:
                observer.instrument(stack)
                with closing(sqlite3.connect(Path(temporary) / 'walk_forward.sqlite3')) as db:
                    self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
                    db.execute('PRAGMA synchronous=FULL')
                    db.execute('CREATE TABLE state (payload TEXT)')
                    db.execute('INSERT INTO state VALUES (?)', ('durable',))
                    db.commit()
            profile = observer.report['sqlite_profiles'][0]
            self.assertEqual(profile['profile_observed_at'], 'initial_connect_before_product_configuration')
            self.assertEqual((profile['journal_mode'], profile['synchronous']), ('delete', 2))
            self.assertEqual(profile['close_profile'], {'journal_mode': 'wal', 'synchronous': 2, 'locking_mode': 'normal'})
            self.assertEqual(observer.phases['sqlite.commit']['completed'], 1)
            self.assertEqual(observer.phases['sqlite.close']['completed'], 1)

    def test_close_profile_failure_still_closes_real_retained_connection(self):
        class RefuseProfile(dict):
            def __setitem__(self, key, value):
                raise OSError('profile failed')

        with tempfile.TemporaryDirectory() as temporary:
            observer = diagnostic.Observer({}, Path(temporary) / 'report.json')
            with ExitStack() as stack:
                observer.instrument(stack)
                db = sqlite3.connect(Path(temporary) / 'walk_forward.sqlite3')
                db.observed_profile = RefuseProfile()
                with self.assertRaisesRegex(OSError, 'profile failed'):
                    db.close()
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            self.assertEqual(observer.phases['sqlite.close']['errors'], 1)

    def test_instrumentation_preserves_exception_and_incomplete_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = {'status': 'INCOMPLETE'}
            observer = diagnostic.Observer(report, Path(temporary) / 'report.json')

            def fail():
                raise OSError('fixture error')

            with self.assertRaisesRegex(OSError, 'fixture error'):
                observer.call('operation', fail)
            self.assertEqual(observer.phases['operation']['completed'], 0)
            self.assertEqual(observer.phases['operation']['errors'], 1)
            observer.checkpoint()
            self.assertNotEqual(json.loads(observer.path.read_text())['status'], 'COMPLETE')

    def test_unverified_runtime_cannot_produce_complete_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(report=Path(temporary) / 'report.json', runtime_root=Path(temporary), library_sha256=None, seconds=10)
            self.assertEqual(diagnostic.supervise(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(report['acceptance'], 'NOT_ESTABLISHED')
            self.assertTrue(report['owned_cleanup_confirmed'])

    def test_owned_process_tree_cleanup_after_gated_launch(self):
        # Real owned child and grandchild; bounded readiness, no global sweep.
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'ready'
            command = [
                sys.executable,
                '-c',
                'import subprocess,sys,time; from pathlib import Path; sys.stdin.buffer.read(1); '
                'subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                'Path(sys.argv[1]).touch(); time.sleep(60)',
                str(ready),
            ]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, start_new_session=os.name != 'nt')
            job = None
            try:
                if os.name == 'nt':
                    from quantlab.analysis_recovery_windows import _OriginalJob, _kernel

                    job = _OriginalJob(_kernel(), process._handle)
                process.stdin.write(b'1')
                process.stdin.close()
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'Owned child did not signal readiness')
                self.assertTrue(diagnostic.stop_owned(process, job))
                job = None
                self.assertIsNotNone(process.poll())
            finally:
                if process.poll() is None:
                    diagnostic.stop_owned(process, job)

    def test_connection_profile_failure_closes_original_connection(self):
        from unittest.mock import Mock

        connection = Mock()
        with tempfile.TemporaryDirectory() as temporary, patch.object(sqlite3, 'connect', return_value=connection):
            observer = diagnostic.Observer({}, Path(temporary) / 'report.json')
            with ExitStack() as stack:
                observer.instrument(stack)
                with self.assertRaises(TypeError):
                    sqlite3.connect(':memory:')
            connection.close.assert_called_once_with()

    def test_successful_connect_checkpoint_failure_closes_retained_connection(self):
        original_connect = sqlite3.connect
        retained = []

        def connect(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            retained.append(db)
            return db

        with tempfile.TemporaryDirectory() as temporary:
            observer = diagnostic.Observer({}, Path(temporary) / 'report.json')
            observer.last = float('-inf')
            with patch.object(sqlite3, 'connect', side_effect=connect), ExitStack() as stack:
                observer.instrument(stack)
                with patch.object(observer, 'checkpoint', side_effect=OSError('report failed')):
                    with self.assertRaisesRegex(OSError, 'report failed'):
                        sqlite3.connect(Path(temporary) / 'opened.sqlite3')
            self.assertEqual(len(retained), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                retained[0].execute('SELECT 1')

    def test_unknown_cleanup_retains_partial_directory(self):
        original_stop = diagnostic.stop_owned
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(report=Path(temporary) / 'report.json', runtime_root=Path(temporary), library_sha256=None, seconds=10)

            def unconfirmed(process, job):
                original_stop(process, job)
                return False

            with patch.object(diagnostic, 'stop_owned', side_effect=unconfirmed):
                self.assertEqual(diagnostic.supervise(args), 2)
            report = json.loads(args.report.read_text())
            retained = Path(report['retained_partial_directory'])
            try:
                self.assertEqual(report['status'], 'INCOMPLETE')
                self.assertFalse(report['owned_cleanup_confirmed'])
                self.assertTrue(retained.is_dir())
            finally:
                shutil.rmtree(retained)

    def test_timeout_retains_partial_evidence_and_nonzero_status(self):
        original_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(report=Path(temporary) / 'report.json', runtime_root=Path(temporary), library_sha256=None, seconds=1)

            def launch(command, **kwargs):
                report_path = command[command.index('--report') + 1]
                script = (
                    'import json,sys,time; from pathlib import Path; '
                    'sys.stdin.buffer.read(1); '
                    'Path(sys.argv[1]).write_text(json.dumps({"status":"INCOMPLETE",'
                    '"observation_only":True,"acceptance":"NOT_ESTABLISHED",'
                    '"cases":[{"status":"INCOMPLETE","phases":{"operation":{"completed":7}}}]})); '
                    'time.sleep(60)'
                )
                return original_popen([sys.executable, '-c', script, report_path], **kwargs)

            with patch.object(diagnostic.subprocess, 'Popen', side_effect=launch):
                self.assertEqual(diagnostic.supervise(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(report['reason'], 'diagnostic_deadline')
            self.assertEqual(report['cases'][0]['phases']['operation']['completed'], 7)
            self.assertTrue(report['owned_cleanup_confirmed'])
            self.assertTrue(report['partial_operation_counts_unknown'])

    def test_invalid_cap_is_rejected(self):
        with patch.object(sys, 'argv', ['diagnostic', '--report', 'unused', '--runtime-root', '.', '--seconds', '151']):
            with self.assertRaises(SystemExit) as error:
                diagnostic.main()
        self.assertEqual(error.exception.code, 2)
