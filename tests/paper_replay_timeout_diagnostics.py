"""Observe the original typed replay invocation; never rerun or relax its gate.

Test-only clocks/heartbeat add overhead. A later pass is not a root-cause finding.
Only fixed labels, counters and current-process resources are recorded, never
payloads, SQL, stack locals, environment values, raw paths or exception messages.
"""
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid
from unittest.mock import patch

from tools.diagnose_paper_replay import Timings, _instrument_connect, _write_json
from quantlab.desktop_runtime import _job_worker as _original_worker

ACTIONS = frozenset({'create_demo', 'run_backtest', 'select_strategy', 'demo_policy',
                     'paper_snapshot', 'paper_reconcile', 'paper_replay'})
STACK_MODULES = frozenset({'paper_replay_timeout_diagnostics.py', 'paper.py',
    'paper_replay.py', 'desktop_runtime.py', 'desktop_ui.py', 'core.py',
    'reporting.py', 'connection.py', 'synchronize.py', 'threading.py',
    'contextlib.py', '_bootstrap.py', '_bootstrap_external.py', 'strategies.py'})
ENVIRONMENT = 'MARKAUTO_PAPER_GATE_REPORT_PREFIX'


def current_resources():
    """Inspect only this process, never a supplied PID or another user's process."""
    result = {'cpu_seconds': time.process_time(), 'python_threads': threading.active_count()}
    try:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = w.HANDLE
            handle = kernel.GetCurrentProcess()  # Borrowed pseudo-handle; never closed.
            kernel.GetProcessHandleCount.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
            handles = w.DWORD()
            if kernel.GetProcessHandleCount(handle, ctypes.byref(handles)):
                result['handles'] = handles.value
            class Memory(ctypes.Structure):
                _fields_ = [('cb', w.DWORD), ('PageFaultCount', w.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
            memory = Memory(); memory.cb = ctypes.sizeof(memory)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                result.update(resident_bytes=memory.WorkingSetSize, private_bytes=memory.PrivateUsage)
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.GetGuiResources.argtypes = [w.HANDLE, w.DWORD]
            user.GetGuiResources.restype = w.DWORD
            result.update(gdi_objects=user.GetGuiResources(handle, 0),
                          user_objects=user.GetGuiResources(handle, 1))
        elif sys.platform.startswith('linux'):
            for row in Path('/proc/self/status').read_text().splitlines():
                key, _, value = row.partition(':')
                if key in ('VmRSS', 'VmHWM'):
                    result[{'VmRSS': 'resident_bytes', 'VmHWM': 'peak_resident_bytes'}[key]] = int(value.split()[0]) * 1024
            result['file_descriptors'] = len(list(Path('/proc/self/fd').iterdir()))
    except Exception as error:
        result['resource_error_type'] = type(error).__name__
    return result


def main_stack(ident):
    frames = []
    frame = sys._current_frames().get(ident)
    try:
        for _ in range(80):
            if frame is None or len(frames) >= 24:
                break
            module, function = Path(frame.f_code.co_filename).name, frame.f_code.co_name
            if module in STACK_MODULES and re.fullmatch('[A-Za-z_][A-Za-z_0-9]{0,95}', function):
                frames.append({'module': module, 'function': function, 'line': frame.f_lineno})
            frame = frame.f_back
    finally:
        del frame
    return frames


def qt_resources(app):
    from PySide6.QtCore import QTimer
    widgets = app.allWidgets()
    top = app.topLevelWidgets()
    windows = [widget for widget in top if type(widget).__name__ == 'MainWindow']
    timers = [timer for window in windows for timer in window.findChildren(QTimer)]
    return {'widgets': len(widgets), 'top_level_widgets': len(top),
            'main_windows': len(windows), 'visible_main_windows': sum(w.isVisible() for w in windows),
            'main_window_timers': len(timers), 'active_main_window_timers': sum(t.isActive() for t in timers)}


def job_state(fixture):
    jobs = getattr(fixture, 'jobs', None)
    if jobs is None:
        return {'fixture_ready': False}
    process = jobs.process
    # Access only the original JobManager's own process handle. No PID lookup.
    value = {'fixture_ready': True, 'active': bool(jobs.active),
             'terminal_received': jobs._terminal, 'pipe_eof': jobs._pipe_eof,
             'deferred_packets': len(jobs._deferred), 'pending_packets': len(jobs._pending),
             'child_handle_present': process is not None}
    if process is not None:
        value.update(child_alive=process.is_alive(), child_exitcode=process.exitcode)
    window = getattr(fixture, 'window', None)
    if window is not None:
        try:
            value['status_is_working'] = window.status.text() == 'Working'
        except RuntimeError:
            value['window_status_unavailable'] = True  # Fixture may now be deleted.
    return value


def _gate_worker(sender, gate, operation, payload, root, bootstrap, job_id,
                 reconciliation_admitted=False, helper_nonce=None):
    """Observe only after the real worker's original ownership gate succeeds."""
    if operation != 'ui_paper_replay':
        return _original_worker(sender, gate, operation, payload, root, bootstrap,
                                job_id, reconciliation_admitted, helper_nonce)
    timings = Timings()
    stop = threading.Event()
    report_lock = threading.Lock()
    main_ident = threading.get_ident()
    metadata = {'scope': 'original typed replay worker; test-only observation',
                'operation': operation, 'worker_entered': True}
    report_errors = []
    restorations = []
    writer = None
    target = None
    initialized = False
    def report():
        # A slow filesystem must not cause concurrent fixed-.partial writers or
        # block the original worker waiting for diagnostic I/O.
        if target is None or not report_lock.acquire(blocking=False):
            return
        try:
            _write_json(target, {**metadata, **timings.snapshot(),
                        'resources': current_resources(), 'main_stack': main_stack(main_ident),
                        'report_error_types': list(report_errors)})
        except Exception as error:
            if len(report_errors) < 4:
                report_errors.append(type(error).__name__)
        finally:
            report_lock.release()
    def periodic():
        while not stop.wait(1):
            report()
    def restore():
        for owner, name, original in reversed(restorations):
            setattr(owner, name, original)
        restorations.clear()
    def replace(owner, name, replacement):
        restorations.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)
    def measure(owner, name, phase):
        original = getattr(owner, name)
        @wraps(original)
        def wrapped(*args, **kwargs):
            with timings.measure(phase):
                return original(*args, **kwargs)
        replace(owner, name, wrapped)
    def initialize():
        nonlocal target, writer, initialized
        # Called only inside the one successful original gate.wait(). The real
        # _job_worker has already performed its original POSIX setsid first.
        target = Path(os.environ[ENVIRONMENT] + '-' + job_id + '.json')
        initialized = True
        report()
        with timings.measure('worker.instrumentation_imports'):
            import sqlite3
            from quantlab.paper import PaperBroker
            from quantlab.paper_replay import PaperReplay
        metadata['sqlite_version'] = sqlite3.sqlite_version
        replace(sqlite3, 'connect', _instrument_connect(sqlite3.connect, timings))
        original_connection = PaperReplay._connection
        @contextmanager
        def connection(self):
            with original_connection(self) as db:
                if 'replay_storage' not in metadata:
                    metadata['replay_storage'] = {
                        'requested_profile': self.storage_profile,
                        'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                        'synchronous': db.execute('PRAGMA synchronous').fetchone()[0],
                        'wal_autocheckpoint': db.execute('PRAGMA wal_autocheckpoint').fetchone()[0]}
                yield db
        replace(PaperReplay, '_connection', connection)
        for cls, name, label in ((PaperBroker, '_restore', 'broker.restore'),
            (PaperBroker, 'snapshot', 'broker.snapshot'),
            (PaperReplay, '__init__', 'replay.initialize_and_preflight'),
            (PaperReplay, 'snapshot', 'replay.snapshot'),
            (PaperReplay, '_quote_policy', 'replay.policy'),
            (PaperReplay, 'step', 'replay.step')):
            measure(cls, name, label)
        fault = PaperReplay._fault
        def boundary(self, point):
            fault(self, point)
            if point in ('after_empty_cursor', 'after_fill_before_cursor',
                         'after_plan_before_submit', 'after_submit_before_fill'):
                with timings.lock:
                    timings.boundaries[point] = timings.boundaries.get(point, 0) + 1
        replace(PaperReplay, '_fault', boundary)
        writer = threading.Thread(target=periodic, daemon=True)
        writer.start()
    class Gate:
        def wait(self, *args, **kwargs):
            with timings.measure('worker.start_gate'):
                admitted = gate.wait(*args, **kwargs)
            if admitted:
                try:
                    initialize()
                except Exception as error:
                    # Observer setup cannot prevent or retry the authorized
                    # original operation. Restore any partially installed hooks.
                    restore()
                    metadata['instrumentation_error_type'] = type(error).__name__
            return admitted
    class Sender:
        def send_bytes(self, value):
            with timings.measure('ipc.send'):
                sender.send_bytes(value)
            try:
                kind = json.loads(value).get('type')
                if kind in ('progress', 'result', 'error'):
                    metadata['last_sent_type'] = kind
                    metadata['last_sent_seconds'] = time.perf_counter() - timings.started
            except (ValueError, AttributeError):
                pass
        def close(self):
            return sender.close()
    try:
        with timings.measure('worker.body'):
            result = _original_worker(Sender(), Gate(), operation, payload, root,
                                      bootstrap, job_id, reconciliation_admitted, helper_nonce)
        metadata['worker_body_returned'] = True
        return result
    finally:
        restore()
        if initialized:
            stop.set()
            if writer is not None and writer.ident is not None:
                writer.join(timeout=1)
            metadata.setdefault('worker_body_returned', False)
            report()


class OriginalReplayObservation:
    def __init__(self, fixture, directory):
        self.fixture = fixture
        self.started = time.monotonic()
        self.prefix = Path(directory) / ('smoke-timeout-paper-native-' + uuid.uuid4().hex)
        self.path = self.prefix.with_suffix('.json')
        self.actions = []
        self.worker_ids = []
        self.action = None
        self.evidence = {'scope': 'exact original typed replay test; observation adds overhead',
                         'acceptance_timeout_seconds': 30, 'acceptance_bars': 960,
                         'acceptance_margin': '120000', 'original_test_rerun': False,
                         'parent_entry_resources': current_resources()}
        try:
            self.evidence['parent_entry_qt'] = qt_resources(fixture.app)
        except Exception as error:
            self.evidence['qt_error_type'] = type(error).__name__

    def capture(self, stage, failure=False):
        """Best effort only: diagnostics never swallow or replace the original error."""
        try:
            record = {'stage': stage, 'seconds': time.monotonic() - self.started,
                      'resources': current_resources(), 'job': job_state(self.fixture)}
            if failure or stage in ('body_finished', 'after_fixture_cleanup'):
                record['qt'] = qt_resources(self.fixture.app)
            self.evidence[stage] = record
            workers = []
            for job_id in self.worker_ids:
                path = Path(str(self.prefix) + '-' + job_id + '.json')
                if path.is_file() and path.stat().st_size <= 256 * 1024:
                    try:
                        workers.append(json.loads(path.read_text(encoding='utf-8')))
                    except (ValueError, OSError):
                        workers.append({'heartbeat_unavailable': True})
                else:
                    workers.append({'heartbeat_unavailable': True})
            # Preserve the heartbeat read at this exact failure/cleanup stage;
            # later snapshots must not overwrite the deadline-time evidence.
            record['workers'] = workers
            self.evidence.update(actions=list(self.actions), workers=workers)
            if failure:
                print('PAPER_NATIVE_TIMEOUT_DIAGNOSTIC ' + json.dumps(self.evidence),
                      file=sys.stderr, flush=True)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(self.path, self.evidence)
        except Exception as error:
            try:
                print('PAPER_NATIVE_DIAGNOSTIC_ERROR ' + type(error).__name__, file=sys.stderr, flush=True)
            except Exception:
                pass

    def click(self, original, fixture, name):
        self.action = name if name in ACTIONS else 'other'
        began = time.monotonic()
        # Patch only the spawn triggered by the original paper_replay click.
        # All other UI jobs and the existing startup/cleanup stay untouched.
        if name == 'paper_replay':
            import quantlab.desktop_runtime as runtime
            try:
                self.prefix.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self.evidence['observer_unavailable_error_type'] = type(error).__name__
                return original(fixture, name)
            with patch.dict(os.environ, {ENVIRONMENT: str(self.prefix)}), \
                    patch.object(runtime, '_job_worker', _gate_worker):
                result = original(fixture, name)
            if fixture.jobs.job_id is not None:
                self.worker_ids.append(fixture.jobs.job_id)
        else:
            result = original(fixture, name)
        self.actions.append({'action': self.action, 'phase': 'click',
                             'seconds': time.monotonic() - began})
        return result

    def wait(self, original, fixture, *args, **kwargs):
        began = time.monotonic()
        try:
            # Forward verbatim: retain wait_job's own default 30s and assertions.
            result = original(fixture, *args, **kwargs)
        except BaseException:
            self.actions.append({'action': self.action, 'phase': 'wait',
                                 'seconds': time.monotonic() - began, 'returned': False})
            self.capture('original_wait_failed_before_cleanup', failure=True)
            raise
        self.actions.append({'action': self.action, 'phase': 'wait',
                             'seconds': time.monotonic() - began, 'returned': True})
        return result


def observe_original_replay(function):
    @wraps(function)
    def wrapped(fixture, *args, **kwargs):
        from tests.test_desktop_ui import NativeDesktopTests
        observation = OriginalReplayObservation(fixture, Path('dist/validation'))
        # Registered before existing setup: runs after its unchanged LIFO cleanup.
        fixture.addCleanup(observation.capture, 'after_fixture_cleanup')
        click, wait = NativeDesktopTests.click, NativeDesktopTests.wait_job
        def clicked(instance, name):
            return observation.click(click, instance, name)
        def waited(instance, *values, **options):
            return observation.wait(wait, instance, *values, **options)
        with patch.object(NativeDesktopTests, 'click', clicked), \
                patch.object(NativeDesktopTests, 'wait_job', waited):
            try:
                return function(fixture, *args, **kwargs)
            except BaseException:
                observation.capture('original_body_failed_before_cleanup',
                    failure='original_wait_failed_before_cleanup' not in observation.evidence)
                raise
            finally:
                observation.capture('body_finished')
    return wrapped
