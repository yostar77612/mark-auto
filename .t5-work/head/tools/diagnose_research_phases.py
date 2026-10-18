"""Bounded observation of three unchanged synthetic cases; never an acceptance gate."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.diagnose_wfo_storage import write_report

TESTS = tuple('tests.test_saved_candidate_pool.SavedCandidatePoolTests.' + name for name in (
    'test_saved_execution_evaluates_all_candidates_and_never_calls_model',
    'test_saved_terminal_report_reads_without_sources_and_with_windows_registry_identity')) + (
    'tests.test_walk_forward.WalkForwardTests.test_registry_lock_cannot_overrun_deadline_or_reserve_after_it',)


def source_key(path, root):
    """Stable report keys on Windows and POSIX; physical paths stay unchanged."""
    return path.relative_to(root).as_posix()


def identity():
    paths = sorted((ROOT / 'quantlab').glob('*.py')) + [
        ROOT / 'tests/test_saved_candidate_pool.py', ROOT / 'tests/test_walk_forward.py',
        ROOT / 'tests/saved_pool_fixtures.py', Path(__file__).resolve(),
        ROOT / 'packaging/sqlite-runtime.json', ROOT / 'tools/diagnose_wfo_storage.py']
    return {'head_sha': os.environ.get('GITHUB_SHA'), 'python': sys.version,
            'executable': sys.executable, 'platform': platform.platform(),
            'tempfile_gettempdir': tempfile.gettempdir(),
            'environment_temp': {k: os.environ.get(k) for k in ('TEMP', 'TMP', 'RUNNER_TEMP')},
            'source_sha256': {source_key(p, ROOT): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}


class Observer:
    """Inclusive counters: nested phase totals must not be added together.

    CPU is process_time of the test parent, excluding any evaluation children.
    Checkpoints occur at completed operations at most once per second, so a
    blocked operation remains absent from the last snapshot and is incomplete.
    """
    def __init__(self, report, path):
        self.report, self.path = report, path
        self.phases = report['phases'] = {}
        self.last = time.monotonic()
        self.publishing = False
        self.save_calls = 0

    def call(self, name, function, *args, payload_bytes=0, **kwargs):
        value = self.phases.setdefault(name, {'calls': 0, 'completed': 0, 'errors': 0,
                                             'wall_seconds': 0.0, 'cpu_seconds': 0.0, 'payload_bytes': 0})
        value['calls'] += 1
        wall, cpu = time.monotonic(), time.process_time()
        try:
            result = function(*args, **kwargs)
            value['completed'] += 1
            value['payload_bytes'] += payload_bytes
            return result
        except BaseException:
            value['errors'] += 1
            raise
        finally:
            value['wall_seconds'] += time.monotonic() - wall
            value['cpu_seconds'] += time.process_time() - cpu
            if not self.publishing and time.monotonic() - self.last >= 1:
                self.checkpoint()

    def checkpoint(self):
        self.publishing = True
        try:
            self.report['snapshot_monotonic'] = time.monotonic()
            write_report(self.path, self.report)
            self.last = time.monotonic()
        finally:
            self.publishing = False

    def instrument(self, stack):
        from quantlab import walk_forward
        for name in ('_save_state', '_read_state', '_validate_state', '_reserve_holdout'):
            original = getattr(walk_forward, name)
            def wrapped(*args, _name=name, _original=original, **kwargs):
                if _name == '_save_state':
                    phase = ('initial_save' if self.save_calls == 0 else
                             'terminal_save' if args[2]['status'] != 'running' else 'later_save')
                    self.save_calls += 1
                    return self.call('wfo.' + _name, lambda: self.call('wfo.' + phase, _original, *args, **kwargs))
                return self.call('wfo.' + _name, _original, *args, **kwargs)
            stack.enter_context(patch.object(walk_forward, name, wrapped))
        observer = self
        original_connect = sqlite3.connect

        class Connection(sqlite3.Connection):
            def __init__(self, database, *args, **kwargs):
                super().__init__(database, *args, **kwargs)
                name = str(database).replace('\\', '/').rsplit('/', 1)[-1].split('?', 1)[0]
                self.phase_kind = ('state' if name == 'walk_forward.sqlite3' else
                                   'registry' if name in ('holdout.sqlite3', 'source-registry.sqlite3') else 'other')

            def execute(self, sql, parameters=(), /):
                payload = sum(len(v.encode('utf-8')) for v in parameters if isinstance(v, str)) if sql.upper().startswith(('INSERT OR REPLACE INTO STATE', 'UPDATE STATE')) else 0
                operation = sql.lstrip().split()[0].lower()
                execute = super().execute
                return observer.call('sqlite.execute', lambda: observer.call(
                    'sqlite.' + self.phase_kind + '.execute.' + operation,
                    execute, sql, parameters, payload_bytes=payload), payload_bytes=payload)

            def executemany(self, sql, parameters, /):
                return observer.call('sqlite.executemany', super().executemany, sql, parameters)

            def commit(self):
                commit = super().commit
                return observer.call('sqlite.commit', lambda: observer.call('sqlite.' + self.phase_kind + '.commit', commit))

            def close(self):
                def close_with_profile():
                    try:
                        profile = getattr(self, 'observed_profile', None)
                        if profile is not None and 'close_profile' not in profile:
                            profile['close_profile'] = {
                                key: sqlite3.Connection.execute(self, 'PRAGMA ' + key).fetchone()[0]
                                for key in ('journal_mode', 'synchronous', 'locking_mode')}
                    finally:
                        # Profile/report failure must never defer owned closure.
                        sqlite3.Connection.close(self)
                return observer.call('sqlite.close', lambda: observer.call(
                    'sqlite.' + self.phase_kind + '.close', close_with_profile))

            def __exit__(self, *args):
                # sqlite3's C context manager commits without calling commit().
                phase = 'sqlite.context_commit' if self.in_transaction and args[0] is None else 'sqlite.context_exit_other'
                exit_context = super().__exit__
                return observer.call(phase, lambda: observer.call(
                    'sqlite.' + self.phase_kind + '.' + phase.split('.', 1)[1], exit_context, *args))

        def connect(*args, **kwargs):
            if len(args) > 5 or 'factory' in kwargs:
                raise RuntimeError('Unexpected connection factory in fixed diagnostic workload')
            opened = None
            def open_connection():
                nonlocal opened
                opened = original_connect(*args, **kwargs, factory=Connection)
                return opened
            try:
                db = observer.call('sqlite.connect', open_connection)
            except BaseException:
                if opened is not None:
                    # A report checkpoint can fail after connect succeeds. Close
                    # directly, without another failing observer checkpoint.
                    sqlite3.Connection.close(opened)
                raise
            # Read only; never set PRAGMAs or relocate the original test data.
            try:
                profile = {key: sqlite3.Connection.execute(db, 'PRAGMA ' + key).fetchone()[0]
                           for key in ('journal_mode', 'synchronous', 'locking_mode')}
            except BaseException:
                db.close()
                raise
            profile['database'] = str(args[0] if args else kwargs.get('database'))
            profile['profile_observed_at'] = 'initial_connect_before_product_configuration'
            db.observed_profile = profile
            self.report.setdefault('sqlite_profiles', []).append(profile)
            return db
        stack.enter_context(patch.object(sqlite3, 'connect', connect))
        original_write, original_replace = Path.write_text, Path.replace

        def write(path, data, *args, **kwargs):
            if path.name.endswith(('.json', '.json.tmp')):
                return self.call('json.write_text', original_write, path, data, *args,
                                 payload_bytes=len(data.encode(kwargs.get('encoding') or 'utf-8')), **kwargs)
            return original_write(path, data, *args, **kwargs)

        def replace(path, target):
            if path.name.endswith(('.json', '.json.tmp')):
                return self.call('json.replace', original_replace, path, target)
            return original_replace(path, target)
        stack.enter_context(patch.object(Path, 'write_text', write))
        stack.enter_context(patch.object(Path, 'replace', replace))


def run_cases(path, runtime):
    report = {'status': 'INCOMPLETE', 'observation_only': True, 'acceptance': 'NOT_ESTABLISHED',
              'identity': identity(), 'runtime': runtime, 'selected_tests': list(TESTS), 'cases': [],
              'counter_semantics': 'inclusive nested counters, never sum; initial_save is first save in case; test-parent process CPU only; completed-operation checkpoint; no timing threshold'}
    write_report(path, report)
    for test_id in TESTS:
        case = {'test_id': test_id, 'status': 'INCOMPLETE'}
        report['cases'].append(case)
        observer = Observer(case, path)
        # Observer publishes the entire report, with counters still held in case.
        observer.report = report
        wall, cpu = time.monotonic(), time.process_time()
        with ExitStack() as stack:
            observer.instrument(stack)
            suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
            result = unittest.TestResult()
            suite.run(result)
        case.update(status='COMPLETE' if result.wasSuccessful() and result.testsRun == 1 and not result.skipped else 'ERROR',
                    tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), failure_details=[text[-8000:] for _, text in result.failures + result.errors],
                    wall_seconds=time.monotonic() - wall,
                    cpu_seconds=time.process_time() - cpu)
        write_report(path, report)
        if case['status'] != 'COMPLETE':
            report['status'] = 'ERROR'
            write_report(path, report)
            return 2
    report['status'] = 'COMPLETE'
    write_report(path, report)
    return 0


def posix_group_quiescent(group):
    if sys.platform.startswith('linux'):
        # Zombies cannot execute; PID 1 in containers may reap them late.
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == group and fields[0] not in ('Z', 'X'):
                    return False
            except FileNotFoundError:
                continue
        return True
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    return False


def stop_owned(process, job):
    """Only the retained original handle/job or our new POSIX session is owned."""
    confirmed = True
    try:
        if job is not None:
            job.stop_and_join()  # existing helper has a six-second bound
        elif os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()  # gate was never released if job attachment failed
        deadline = time.monotonic() + 4
        process.wait(timeout=4)
        if os.name != 'nt':
            while not posix_group_quiescent(process.pid):
                if time.monotonic() >= deadline:
                    confirmed = False
                    break
                time.sleep(.02)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        confirmed = False
    finally:
        if job is not None:
            job.close()  # kill-on-close remains active on every path
    return confirmed


@contextmanager
def evidence_directory():
    state = {'path': tempfile.mkdtemp(prefix='research-phase-report-'), 'cleanup_confirmed': False}
    try:
        yield state
    finally:
        if state['cleanup_confirmed']:
            shutil.rmtree(state['path'])


def supervise(args):
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'INCOMPLETE', 'observation_only': True, 'acceptance': 'NOT_ESTABLISHED',
              'identity': identity(), 'selected_tests': list(TESTS), 'cases': []}
    write_report(args.report, report)
    with evidence_directory() as evidence:
        partial = Path(evidence['path']) / 'partial.json'
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--report', str(partial),
                   '--runtime-root', str(args.runtime_root)]
        if args.library_sha256:
            command += ['--library-sha256', args.library_sha256]
        process = None; job = None; code = None; reason = None
        started = time.monotonic()
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=os.name != 'nt')
            if os.name == 'nt':
                from quantlab.analysis_recovery_windows import _OriginalJob, _kernel
                job = _OriginalJob(_kernel(), process._handle)
            # Worker cannot import/run fixtures or spawn descendants before this.
            process.stdin.write(b'1'); process.stdin.close()
            code = process.wait(timeout=max(.001, args.seconds - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            reason = 'diagnostic_deadline'
        except BaseException as exc:
            reason = type(exc).__name__
        finally:
            confirmed = stop_owned(process, job) if process is not None else True
        evidence['cleanup_confirmed'] = confirmed
        if partial.exists():
            try:
                report = json.loads(partial.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                reason = reason or 'invalid_partial_report'
        if reason or code != 0 or not confirmed:
            report.update(status='INCOMPLETE', reason=reason or 'worker_or_cleanup_failed',
                          partial_operation_counts_unknown=True)
        if not confirmed:
            report['retained_partial_directory'] = evidence['path']
        report.update(deadline_seconds=args.seconds, worker_exit_code=code,
                      owned_cleanup_confirmed=confirmed, supervisor_wall_seconds=time.monotonic() - started)
        write_report(args.report, report)
    return 0 if report['status'] == 'COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--library-sha256')
    parser.add_argument('--seconds', type=int, default=150)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 150:
        parser.error('Deadline must be between 1 and 150 seconds')
    if args.worker:
        if sys.stdin.buffer.read(1) != b'1':
            return 2
        from quantlab.sqlite_runtime import verify
        runtime = verify(ROOT / 'packaging/sqlite-runtime.json', args.runtime_root, args.library_sha256)
        return run_cases(args.report, runtime)
    return supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
