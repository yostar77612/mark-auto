"""Controlled timeout evidence and owned child cleanup; not native acceptance."""
import json
import errno
import select
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

from quantlab.desktop_runtime import JobManager, RuntimeSafetyError

from tests.smoke_timeout_diagnostics import (WorkerTimings, diagnosed_smoke_worker,
    instrument_walk_forward, output_summary, run_smoke_process)
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
from quantlab.desktop_runtime import _WindowsProcessTree
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
                run_smoke_process([sys.executable, '-c', code, str(report), str(pids), str(writes), worker_code],
                    cwd=root, env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])), report=report, pidfile=pids, writes=writes,
                    process_can_run=process_can_run, artifact_dir=root / 'artifacts', timeout=5)
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
                run_smoke_process([sys.executable, '-c', code, str(pids)], cwd=root,
                    env=os.environ.copy(), report=root / 'report', pidfile=pids,
                    writes=root / 'writes', process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts', timeout=2)
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pids.read_text())))

    def test_non_object_and_malformed_diagnostic_lines_are_ignored(self):
        value = output_summary('\n'.join('SMOKE_DIAGNOSTIC ' + text for text in
            ('[]', 'null', '1', '"text"', '{', '{"stage": [], "operation": {}}')))
        self.assertEqual(value['events'], [])

    def test_windows_admission_failure_does_not_release_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'application-ran'
            code = "from pathlib import Path; Path(__import__('sys').argv[1]).touch()"
            with patch('tests.smoke_timeout_diagnostics.sys.platform', 'win32'), \
                    patch('tests.smoke_timeout_diagnostics._WindowsProcessTree', side_effect=RuntimeSafetyError('Isolation unavailable')):
                with self.assertRaises(RuntimeSafetyError):
                    run_smoke_process([sys.executable, '-c', code, str(marker)], cwd=root,
                        env=os.environ.copy(), report=root / 'report', pidfile=root / 'pids',
                        writes=root / 'writes', process_can_run=process_can_run,
                        artifact_dir=root / 'artifacts', timeout=2)
            self.assertFalse(marker.exists())

    def test_output_drops_raw_paths_messages_and_unrecognized_fields(self):
        result = output_summary('password=DO_NOT_RETAIN\n  File "/private/user/desktop.py", line 770 in main\n')
        self.assertEqual(result['stack_frames'], [{'module': 'desktop.py', 'line': 770, 'function': 'main'}])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))


class WorkerTimingTests(unittest.TestCase):
    def test_active_phase_and_failed_call_are_recorded_without_exception_text(self):
        timings = WorkerTimings()
        with self.assertRaisesRegex(RuntimeError, 'DO_NOT_RETAIN'):
            with timings.measure('worker.body'), timings.measure('wfo.evaluate'):
                observed = timings.snapshot()
                self.assertEqual([row['phase'] for row in observed['active']],
                                 ['worker.body', 'wfo.evaluate'])
                raise RuntimeError('DO_NOT_RETAIN')
        observed = timings.snapshot()
        self.assertEqual(observed['active'], [])
        self.assertEqual({row['phase']: row['calls'] for row in observed['timings']},
                         {'worker.body': 1, 'wfo.evaluate': 1})
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(observed))
        with self.assertRaises(ValueError):
            with timings.measure('/private/not-a-phase'):
                self.fail('Unknown phase accepted')

    def test_worker_waits_for_admission_before_instrumentation(self):
        from unittest.mock import Mock
        gate = Mock(); gate.wait.return_value = False
        with patch('tests.smoke_timeout_diagnostics.instrument_walk_forward') as instrument, \
                patch('tests.smoke_timeout_diagnostics._original_job_worker') as worker:
            diagnosed_smoke_worker(None, gate, 'ui_walk_forward_run', {}, None, None, 'fixture')
        gate.wait.assert_called_once_with(15)
        instrument.assert_not_called(); worker.assert_not_called()

    def test_sqlite_semantics_and_explicit_factories_are_unchanged_and_wrappers_restore(self):
        from quantlab import walk_forward
        original_connect, original_save = sqlite3.connect, walk_forward._save_state
        timings = WorkerTimings()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'fixture.sqlite3'
            with closing(sqlite3.connect(database)) as db:
                expected = [db.execute('PRAGMA ' + name).fetchone()[0]
                            for name in ('journal_mode', 'synchronous')]
            with self.assertRaisesRegex(RuntimeError, 'restore-on-error'):
                with instrument_walk_forward(timings):
                    with closing(sqlite3.connect(database)) as db:
                        self.assertEqual([db.execute('PRAGMA ' + name).fetchone()[0]
                            for name in ('journal_mode', 'synchronous')], expected)
                        db.execute('CREATE TABLE fixture (value TEXT)')
                        db.execute('INSERT INTO fixture VALUES (?)', ('DO_NOT_RETAIN',))
                        db.commit()
                        with self.assertRaises(ValueError):
                            with db:
                                db.execute('INSERT INTO fixture VALUES (?)', ('rollback',))
                                raise ValueError('rollback')
                    for args, kwargs in (((':memory:',), {'factory': sqlite3.Connection}),
                                         ((':memory:', 5.0, 0, '', True, sqlite3.Connection), {})):
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
        raw = {'stage': 'worker_timing', 'operation': 'ui_walk_forward_run',
            'active': [{'phase': 'sqlite.commit', 'elapsed_ms': 3, 'sql': 'DO_NOT_RETAIN'}],
            'timings': [dict(good, path='/private/root', secret='DO_NOT_RETAIN'),
                dict(good, phase='/private/root'), dict(good, phase=[]),
                dict(good, elapsed_ms=-1), dict(good, elapsed_ms=7200001),
                dict(good, elapsed_ms=True), dict(good, calls=True),
                dict(good, calls=1000001), None, 'DO_NOT_RETAIN']}
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
            try: os.killpg(worker.pid, 9)
            except ProcessLookupError: pass
            worker.wait(timeout=6)
            worker.stdout.close()

    def test_liveness_survives_real_process_exit_during_stat_read(self):
        with process_exits_during_proc_read() as (pid, observed):
            self.assertFalse(process_can_run(pid))
        self.assertEqual(observed, [errno.ESRCH])

    def test_group_join_and_liveness_do_not_hide_permission_or_unknown_errors(self):
        for error in (PermissionError(errno.EACCES, 'denied'), OSError(errno.EIO, 'unknown I/O failure')):
            with self.subTest(error=type(error).__name__), \
                    patch('quantlab.desktop_runtime.os.killpg'), \
                    patch('tests.test_desktop_smoke_terminal.os.kill'), \
                    patch.object(Path, 'iterdir', return_value=iter([Path('/proc/123')])), \
                    patch.object(Path, 'read_text', side_effect=error):
                with self.assertRaises(type(error)):
                    JobManager._join_descendants(SimpleNamespace(tree=None, _operation='ui_walk_forward_run'), 123)
                with self.assertRaises(type(error)):
                    process_can_run(123)

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
                        run_smoke_process([sys.executable, '-c', 'import time; time.sleep(60)'],
                            cwd=root, env=os.environ.copy(), report=root / 'report', pidfile=root / 'pids',
                            writes=root / 'writes', process_can_run=process_can_run,
                            artifact_dir=root / 'artifacts', timeout=1)
                artifact, = (root / 'artifacts').glob('smoke-timeout-*.json')
                value = json.loads(artifact.read_text(encoding='utf-8'))
                self.assertFalse(value['cleanup_verified'], value)
                self.assertEqual(value['cleanup_error_type'], type(error).__name__)
