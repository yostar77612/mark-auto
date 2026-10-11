"""Contracts for observation tooling, not product timing acceptance."""
import json
import os
from pathlib import Path
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
        self.assertEqual(len(diagnostic.TESTS), 2)
        self.assertTrue(diagnostic.TESTS[0].endswith('test_saved_execution_evaluates_all_candidates_and_never_calls_model'))
        self.assertTrue(diagnostic.TESTS[1].endswith('test_saved_terminal_report_reads_without_sources_and_with_windows_registry_identity'))
        self.assertIn('quantlab/walk_forward.py', identity['source_sha256'])

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
            args = SimpleNamespace(report=Path(temporary) / 'report.json',
                                   runtime_root=Path(temporary), library_sha256=None, seconds=10)
            self.assertEqual(diagnostic.supervise(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(report['acceptance'], 'NOT_ESTABLISHED')
            self.assertTrue(report['owned_cleanup_confirmed'])

    def test_owned_process_tree_cleanup_after_gated_launch(self):
        # Real owned child and grandchild; bounded readiness, no global sweep.
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'ready'
            command = [sys.executable, '-c',
                       'import subprocess,sys,time; from pathlib import Path; sys.stdin.buffer.read(1); '
                       'subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                       'Path(sys.argv[1]).touch(); time.sleep(60)', str(ready)]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       start_new_session=os.name != 'nt')
            job = None
            try:
                if os.name == 'nt':
                    from quantlab.analysis_recovery_windows import _OriginalJob, _kernel
                    job = _OriginalJob(_kernel(), process._handle)
                process.stdin.write(b'1'); process.stdin.close()
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(.02)
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

    def test_unknown_cleanup_retains_partial_directory(self):
        original_stop = diagnostic.stop_owned
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(report=Path(temporary) / 'report.json',
                                   runtime_root=Path(temporary), library_sha256=None, seconds=10)
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
            args = SimpleNamespace(report=Path(temporary) / 'report.json',
                                   runtime_root=Path(temporary), library_sha256=None, seconds=1)
            def launch(command, **kwargs):
                report_path = command[command.index('--report') + 1]
                script = ('import json,sys,time; from pathlib import Path; '
                          'sys.stdin.buffer.read(1); '
                          'Path(sys.argv[1]).write_text(json.dumps({"status":"INCOMPLETE",'
                          '"observation_only":True,"acceptance":"NOT_ESTABLISHED",'
                          '"cases":[{"status":"INCOMPLETE","phases":{"operation":{"completed":7}}}]})); '
                          'time.sleep(60)')
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
