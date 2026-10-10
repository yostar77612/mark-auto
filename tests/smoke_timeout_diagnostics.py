"""Failure-only synthetic smoke evidence; never copy raw output or user state."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace

from quantlab.desktop_runtime import JobManager, _WindowsProcessTree, _job_worker as _original_job_worker

PREFIX = 'SMOKE_DIAGNOSTIC '
STATUSES = {'passed', 'failed', 'completed', 'running', 'cancelled'}
# Fixed labels only: no paths, SQL, arguments, result data, or exception text.
WORKER_PHASES = frozenset({
    'worker.body', 'wfo.run', 'wfo.reserve', 'wfo.evaluate', 'wfo.save',
    'wfo.hash', 'wfo.serialize', 'sqlite.connect', 'sqlite.execute',
    'sqlite.commit', 'sqlite.transaction_exit', 'sqlite.close',
    'process.start', 'process.join', 'ipc.poll', 'ipc.receive',
})


class WorkerTimings:
    """Inclusive, overlapping timings for the original synthetic worker only."""
    def __init__(self):
        self.started = time.perf_counter()
        self.lock = threading.RLock()
        self.active = []
        self.timings = {}

    @contextmanager
    def measure(self, phase):
        if phase not in WORKER_PHASES:
            raise ValueError('Unrecognized smoke diagnostic phase')
        started = time.perf_counter()
        with self.lock:
            self.active.append((phase, started))
        try:
            yield
        finally:
            with self.lock:
                self.active.pop()
                calls, seconds = self.timings.get(phase, (0, 0.0))
                self.timings[phase] = (calls + 1, seconds + time.perf_counter() - started)

    def snapshot(self):
        with self.lock:
            now = time.perf_counter()
            return {'stage': 'worker_timing', 'operation': 'ui_walk_forward_run',
                'pid': os.getpid(), 'elapsed_ms': int((now - self.started) * 1000),
                'active': [{'phase': name, 'elapsed_ms': int((now - started) * 1000)}
                           for name, started in self.active],
                'timings': [{'phase': name, 'calls': calls, 'elapsed_ms': int(seconds * 1000)}
                            for name, (calls, seconds) in sorted(self.timings.items())]}


@contextmanager
def instrument_walk_forward(timings):
    """Observe unchanged calls; never alter SQL, isolation, budgets or durability."""
    import multiprocessing.connection
    from multiprocessing.process import BaseProcess
    import sqlite3
    from quantlab import walk_forward
    restores = []

    def replace(owner, name, value):
        restores.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def wrap(owner, name, phase):
        original = getattr(owner, name)
        def measured(*args, **kwargs):
            with timings.measure(phase):
                return original(*args, **kwargs)
        replace(owner, name, measured)

    class TimedConnection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            with timings.measure('sqlite.execute'):
                return super().execute(*args, **kwargs)

        def commit(self):
            with timings.measure('sqlite.commit'):
                return super().commit()

        def __exit__(self, *args):
            with timings.measure('sqlite.transaction_exit'):
                return super().__exit__(*args)

        def close(self):
            with timings.measure('sqlite.close'):
                return super().close()

    original_connect = sqlite3.connect
    def connect(*args, **kwargs):
        # Leave any explicit caller factory untouched, including positional use.
        if len(args) < 6 and 'factory' not in kwargs:
            kwargs['factory'] = TimedConnection
        with timings.measure('sqlite.connect'):
            return original_connect(*args, **kwargs)

    try:
        replace(sqlite3, 'connect', connect)
        for name, phase in (('run_walk_forward', 'wfo.run'), ('_reserve_holdout', 'wfo.reserve'),
                            ('_run_bounded', 'wfo.evaluate'), ('_save_state', 'wfo.save'),
                            ('content_hash', 'wfo.hash'), ('canonical_json', 'wfo.serialize')):
            wrap(walk_forward, name, phase)
        wrap(BaseProcess, 'start', 'process.start')
        wrap(BaseProcess, 'join', 'process.join')
        wrap(multiprocessing.connection._ConnectionBase, 'poll', 'ipc.poll')
        wrap(multiprocessing.connection._ConnectionBase, 'recv_bytes', 'ipc.receive')
        yield
    finally:
        for owner, name, original in reversed(restores):
            setattr(owner, name, original)


def diagnosed_smoke_worker(sender, gate, operation, payload, root, bootstrap, job_id,
                            reconciliation_admitted=False):
    """Spawnable test-only observer; no changes to the real worker or its jobs."""
    if operation != 'ui_walk_forward_run':
        return _original_job_worker(sender, gate, operation, payload, root, bootstrap,
                                    job_id, reconciliation_admitted)
    # Preserve Job Object admission before importing or instrumenting work.
    if not gate.wait(15):
        return
    timings = WorkerTimings()
    stop = threading.Event()
    def report():
        print(PREFIX + json.dumps(timings.snapshot()), file=sys.stderr, flush=True)
    def periodic():
        while not stop.wait(1):
            report()
    report()
    reporter = threading.Thread(target=periodic, daemon=True)
    reporter.start()
    try:
        with timings.measure('worker.body'), instrument_walk_forward(timings):
            return _original_job_worker(sender, gate, operation, payload, root, bootstrap,
                                        job_id, reconciliation_admitted)
    finally:
        stop.set()
        reporter.join()
        report()


def timing_rows(value, *, active=False):
    if type(value) is not list:
        return []
    rows = []
    for item in value[:32]:
        if (type(item) is not dict or type(item.get('phase')) is not str
                or item['phase'] not in WORKER_PHASES
                or type(item.get('elapsed_ms')) is not int or not 0 <= item['elapsed_ms'] <= 7200000):
            continue
        row = {'phase': item['phase'], 'elapsed_ms': item['elapsed_ms']}
        if not active:
            if type(item.get('calls')) is not int or not 0 <= item['calls'] <= 1000000:
                continue
            row['calls'] = item['calls']
        rows.append(row)
    return rows


def read_json(path):
    try:
        if path.stat().st_size > 262144:
            return None
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def report_summary(value):
    if not isinstance(value, dict):
        return {'available': False}
    result = {'available': True}
    if type(value.get('status')) is str and value['status'] in STATUSES:
        result['status'] = value['status']
    for key in ('timed_out', 'worker_completed', 'backtest_completed', 'campaign_completed', 'paper_completed'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    cleanup = value.get('worker_cleanup', {})
    if isinstance(cleanup, dict) and type(cleanup.get('verified')) is bool:
        result['worker_cleanup_verified'] = cleanup['verified']
    for key in ('steps', 'walk_forward_smoke', 'market_smoke', 'history_smoke'):
        item = value.get(key)
        if isinstance(item, list):
            result[key + '_count'] = len(item)
        elif isinstance(item, dict):
            result[key] = report_summary(item)
    return result


def output_summary(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='replace')
    raw = raw or ''
    events, stacks = [], []
    for line in raw.splitlines():
        if line.startswith(PREFIX):
            try:
                value = json.loads(line[len(PREFIX):])
            except ValueError:
                continue
            if not isinstance(value, dict):
                continue
            event = {}
            if type(value.get('stage')) is str and value['stage'] in {'start_requested', 'started', 'terminal', 'cleanup_start', 'cleanup_end', 'main_return', 'worker_timing'}:
                event['stage'] = value['stage']
            for name in ('pid', 'elapsed_ms', 'status'):
                if type(value.get(name)) is int:
                    event[name] = value[name]
            if type(value.get('operation')) is str and value['operation'] in {'ui_demo', 'ui_backtest', 'ui_select', 'ui_campaign', 'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill', 'ui_market_refresh', 'ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read'}:
                event['operation'] = value['operation']
            if type(value.get('event')) is str and value['event'] in {'result', 'error', 'cancelled'}:
                event['event'] = value['event']
            if type(value.get('verified')) is bool:
                event['verified'] = value['verified']
            if event.get('stage') == 'worker_timing':
                event['active'] = timing_rows(value.get('active'), active=True)
                event['timings'] = timing_rows(value.get('timings'))
            if 'stage' in event:
                events.append(event)
        match = re.match(r'\s*File "[^"\n]*[/\\]([A-Za-z_][A-Za-z_0-9]*\.py)", line (\d+) in ([A-Za-z_][A-Za-z_0-9]*)$', line)
        if match:
            stacks.append({'module': match[1], 'line': int(match[2]), 'function': match[3]})
    return {'characters': len(raw), 'events': events[-100:], 'stack_frames': stacks[-30:]}


class SmokeOutputCapture:
    """Incremental bounded pipe capture; EOF remains part of completion proof.

    Windows Popen.communicate stores fh.read() only after EOF, and supplies no
    partial output on TimeoutExpired. Keep the same EOF requirement, but retain
    flushed bytes as they arrive so failed cleanup cannot erase diagnostics.
    """
    LIMIT = 1048576

    def __init__(self, process):
        self.process = process
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self.truncated = {'stdout': False, 'stderr': False}
        self.errors = []
        self.eof = {'stdout': False, 'stderr': False}
        self.threads = []
        try:
            for name in self.buffers:
                thread = threading.Thread(target=self._read, args=(name,), daemon=True)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            self.close()
            raise

    def _read(self, name):
        try:
            stream = getattr(self.process, name)
            if sys.platform == 'win32':
                import ctypes
                import msvcrt
                from ctypes import wintypes as w
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.PeekNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD,
                    ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
                kernel.PeekNamedPipe.restype = w.BOOL
                handle = msvcrt.get_osfhandle(stream.fileno())
            else:
                import select
            while not self.stop.is_set():
                if sys.platform == 'win32':
                    available = w.DWORD()
                    if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                        if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE: all writers closed.
                            with self.lock:
                                self.eof[name] = True
                            return
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not available.value:
                        self.stop.wait(.01)
                        continue
                    count = min(available.value, 65536)
                else:
                    if not select.select([stream], [], [], .05)[0]:
                        continue
                    count = 65536
                # There is exactly one reader. Read only bytes known available,
                # so surviving writers cannot strand a thread during cleanup.
                raw = os.read(stream.fileno(), count)
                if not raw:
                    with self.lock:
                        self.eof[name] = True
                    return
                with self.lock:
                    buffer = self.buffers[name]
                    buffer.extend(raw)
                    if len(buffer) > self.LIMIT:
                        del buffer[:-self.LIMIT]
                        self.truncated[name] = True
        except (OSError, ValueError):
            with self.lock:
                self.errors.append(name)

    def close(self):
        self.stop.set()
        deadline = time.monotonic() + 1
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError('Smoke output reader did not stop')

    def snapshot(self, name):
        with self.lock:
            raw = bytes(self.buffers[name])
            truncated = self.truncated[name]
        if truncated:
            raw = raw.partition(b'\n')[2]  # Discard a possibly partial first line.
        return raw.decode('utf-8', errors='replace'), truncated

    def communicate(self, admission=None, *, timeout):
        deadline = time.monotonic() + timeout
        if admission is not None:
            try:
                self.process.stdin.write(admission)
                self.process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    pass
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():
                raise subprocess.TimeoutExpired(self.process.args, timeout)
        with self.lock:
            if self.errors or not all(self.eof.values()):
                raise RuntimeError('Smoke output capture failed or stopped before EOF')
        self.process.wait(timeout=max(0, deadline - time.monotonic()))
        return self.snapshot('stdout')[0], self.snapshot('stderr')[0]


def run_smoke_process(command, *, cwd, env, report, pidfile, writes, process_can_run,
                      artifact_dir, timeout=40):
    """Retain the original gate; kill/join owned processes before timeout evidence."""
    command = list(command)
    # No application code can spawn before Windows Job Object admission.
    command[2] = 'import sys; sys.stdin.read(1)\n' + command[2]
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=sys.platform != 'win32')
    tree = None
    capture = None
    try:
        if sys.platform == 'win32':
            tree = _WindowsProcessTree(process.pid)
        capture = SmokeOutputCapture(process)
        try:
            stdout, stderr = capture.communicate('x', timeout=timeout)
            # Check before closing the outer kill-on-close handle: containment
            # must not turn leaked workers into a false successful smoke.
            completed_pids = read_json(pidfile)
            if isinstance(completed_pids, list):
                if any(process_can_run(pid) for pid in completed_pids
                       if type(pid) is int and pid > 0):
                    if tree is not None:
                        tree.stop_and_join()
                    else:
                        owner = SimpleNamespace(tree=None, _operation='ui_walk_forward_run')
                        for pid in completed_pids:
                            if type(pid) is int and pid > 0:
                                JobManager._join_descendants(owner, pid)
                    raise AssertionError('Smoke exited with a live recorded worker')
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            if sys.platform != 'win32':
                try: os.killpg(process.pid, signal.SIGSTOP)
                except ProcessLookupError: pass
            pids = read_json(pidfile)
            pids = [pid for pid in pids if type(pid) is int and pid > 0] if isinstance(pids, list) else []
            def liveness(pid, states):
                try: return process_can_run(pid, linux_states=states)
                except (OSError, AssertionError): return None
            before_states, after_states = {}, {}
            before = {str(pid): liveness(pid, before_states) for pid in pids}
            cleanup_error = None
            try:
                if tree is not None:
                    tree.stop_and_join()
                else:
                    # Each recorded JobManager worker owns its own process group.
                    # Freeze the launcher before snapshotting/killing those groups.
                    owned = set(pids)
                    if sys.platform.startswith('linux'):
                        for entry in Path('/proc').iterdir():
                            if not entry.name.isdigit(): continue
                            try: fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                            except (FileNotFoundError, ProcessLookupError): continue
                            if int(fields[1]) == process.pid: owned.add(int(entry.name))
                    owner = SimpleNamespace(tree=None, _operation='ui_walk_forward_run')
                    for pid in owned:
                        JobManager._join_descendants(owner, pid)
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                stdout, stderr = capture.communicate(timeout=6)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_error = type(error).__name__
            stdout, stdout_truncated = capture.snapshot('stdout')
            stderr, stderr_truncated = capture.snapshot('stderr')
            after = {str(pid): liveness(pid, after_states) for pid in pids}
            audited = []
            try:
                if writes.stat().st_size <= 262144:
                    audited = [report_summary(json.loads(line)) for line in writes.read_text(encoding='utf-8').splitlines()]
            except (OSError, ValueError):
                pass
            evidence = {'scope': 'synthetic smoke timeout diagnostic; not acceptance',
                'timeout_seconds': timeout, 'report': report_summary(read_json(report)),
                'report_writes': audited, 'worker_alive_before': before, 'worker_alive_after': after,
                'worker_linux_state_before': before_states, 'worker_linux_state_after': after_states,
                'cleanup_verified': cleanup_error is None and process.poll() is not None and all(value is False for value in after.values()),
                'cleanup_error_type': cleanup_error, 'stdout': output_summary(stdout), 'stderr': output_summary(stderr),
                'stdout_truncated': stdout_truncated, 'stderr_truncated': stderr_truncated}
            artifact_dir.mkdir(parents=True, exist_ok=True)
            target = artifact_dir / ('smoke-timeout-' + uuid.uuid4().hex + '.json')
            target.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
            raise AssertionError('Smoke exceeded unchanged deadline; sanitized evidence: ' + json.dumps(evidence)) from None
    finally:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=6)
        finally:
            try:
                if tree is not None:
                    tree.close()
            finally:
                try:
                    if capture is not None:
                        capture.close()
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
