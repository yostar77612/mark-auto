"""Failure-only observation of original TEST_ONLY children; never authority.

No new process, retry, pipe, wait, durable write or success-path file is added.
Only fixed labels, integer error codes and allowlisted source locations leave
this observer. Exception text, locals, paths, command lines and tokens do not.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

ROLES = ('gui', 'helper', 'worker', 'grandchild')
SCENARIOS = frozenset({'normal', 'helper_before_gui', 'helper_after_gui'})
PHASES = frozenset({
    'entry', 'kernel', 'gui.launch.commit', 'gui.launch.signal', 'idle',
    'worker.gate.wait', 'worker.launch.read', 'worker.grandchild.start',
    'worker.handle.publish', 'worker.ack.wait', 'worker.ready.signal',
    'worker.monitor', 'worker.cleanup', 'helper.runtime.import',
    'helper.admission', 'helper.job.create', 'helper.protocol.open', 'helper.gui_commit.wait',
    'helper.gate.open', 'helper.worker_ready.wait', 'helper.ready.signal',
    'helper.gui_death.wait', 'helper.gui_death.signal', 'helper.quiescence.wait',
    'helper.job.stop', 'helper.quiescence.signal', 'helper.receipt.wait',
    'helper.receipt.publish', 'helper.receipt.signal', 'helper.cleanup',
})
WAIT_LABELS = frozenset({'helper readiness', 'GUI death', 'zero active',
    'durable receipt', 'helper clean exit', 'kill-on-close cleanup'})
BARRIERS = (
    'gui-launch-committed.json', 'worker-go.json', 'grandchild.handle.json',
    'grandchild-ack.json', 'worker-ready.json', 'helper-ready.json',
    'gui-death-observed.json', 'allow-quiescence.json', 'quiescence-observed.json',
    'allow-receipt.json', 'receipt.json', 'cleanup-request.json',
    'cleanup-quiescence.json',
)
MODULES = frozenset({'test_windows_recovery_feasibility.py',
                    'windows_recovery_diagnostics.py', 'desktop_runtime.py',
                    'subprocess.py', 'pathlib.py', 'contextlib.py'})
ERROR_TYPES = frozenset({
    'OSError', 'PermissionError', 'FileNotFoundError', 'FileExistsError',
    'TimeoutError', 'RuntimeError', 'RuntimeSafetyError', 'ValueError',
    'TypeError', 'AttributeError', 'ImportError', 'ModuleNotFoundError',
    'OperationalError', 'DatabaseError', 'IntegrityError', 'ProgrammingError',
    'JSONDecodeError', 'AssertionError', 'SystemExit', 'KeyboardInterrupt',
})
MAX_RECORD_BYTES = 8192
MAX_REPORT_BYTES = 32768
MAX_ERRORS = 3
MAX_FRAMES = 12


def _number(value):
    return value if type(value) is int and -(2 ** 31) <= value < 2 ** 32 else None


def _error_record(error):
    frames = []
    trace = error.__traceback__
    # Inspect no source text or locals. Bound traversal independently of output.
    for _ in range(64):
        if trace is None:
            break
        module = Path(trace.tb_frame.f_code.co_filename).name
        if module in MODULES:
            frames.append({'module': module, 'line': trace.tb_lineno})
        trace = trace.tb_next
    name = type(error).__name__
    return {'type': name if name in ERROR_TYPES else 'other',
            'errno': _number(getattr(error, 'errno', None)),
            'winerror': _number(getattr(error, 'winerror', None)),
            'sqlite_errorcode': _number(getattr(error, 'sqlite_errorcode', None)),
            'frames': frames[-MAX_FRAMES:]}


class FixtureDiagnostics:
    def __init__(self, folder, role):
        self.folder, self.role = Path(folder), role
        self.phase = 'entry'
        self.attempted = False

    def at(self, phase):
        # Call sites use fixed literals; this is an in-memory assignment only.
        self.phase = phase

    def record_failure(self, error):
        """Best effort, once, before original child cleanup can mask its cause."""
        if self.attempted:
            return
        self.attempted = True
        try:
            if self.role not in ROLES or self.phase not in PHASES:
                return
            errors = []
            for _ in range(MAX_ERRORS):
                if error is None:
                    break
                errors.append(_error_record(error))
                error = error.__cause__ or error.__context__
            value = {'role': self.role, 'phase': self.phase, 'errors': errors}
            raw = json.dumps(value, sort_keys=True)
            if len(raw.encode('utf-8')) <= MAX_RECORD_BYTES:
                (self.folder / (self.role + '.failure.json')).write_text(raw, encoding='utf-8')
        except Exception:
            pass  # Never replace the original exception or change cleanup.

    def run(self, function, *args):
        try:
            return function(*args, diagnosis=self)
        except BaseException as error:
            self.record_failure(error)
            raise


def _read_failure(folder, role):
    """Treat even diagnostic files as untrusted; never echo arbitrary fields."""
    try:
        with (folder / (role + '.failure.json')).open('rb') as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError('oversized')
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'role', 'phase', 'errors'}
                or value['role'] != role or value['phase'] not in PHASES
                or type(value['errors']) is not list
                or not 1 <= len(value['errors']) <= MAX_ERRORS):
            raise ValueError('invalid')
        for error in value['errors']:
            if (type(error) is not dict or set(error) != {
                    'type', 'errno', 'winerror', 'sqlite_errorcode', 'frames'}
                    or error['type'] not in ERROR_TYPES | {'other'}
                    or any(error[key] is not None and _number(error[key]) is None
                           for key in ('errno', 'winerror', 'sqlite_errorcode'))
                    or type(error['frames']) is not list or len(error['frames']) > MAX_FRAMES):
                raise ValueError('invalid')
            for frame in error['frames']:
                if (type(frame) is not dict or set(frame) != {'module', 'line'}
                        or frame['module'] not in MODULES
                        or type(frame['line']) is not int or not 1 <= frame['line'] <= 1000000):
                    raise ValueError('invalid')
        return {'status': 'recorded', **value}
    except FileNotFoundError:
        return {'status': 'unavailable'}  # Includes native exit/pre-entry failure.
    except Exception:
        return {'status': 'unreadable'}


def failure_snapshot(folder, processes, scenario, *, barrier=None):
    folder = Path(folder)
    children = {}
    for role in ROLES:
        proc = processes.get(role)
        code = None if proc is None else proc.poll()
        children[role] = {
            'popen_owned': proc is not None,
            'returncode': _number(code),
            'failure': _read_failure(folder, role),
        }
    return {'kind': 'TEST_ONLY_ORIGINAL_WINDOWS_RECOVERY_FAILURE',
            'acceptance': False,
            'scenario': scenario if scenario in SCENARIOS else 'unknown',
            'awaited_barrier': barrier if barrier in WAIT_LABELS else 'unknown',
            'barriers': {name: (folder / name).is_file() for name in BARRIERS},
            'children': children}


def report_failure(folder, processes, scenario, *, artifact_dir, barrier=None):
    """Capture BEFORE parent cleanup; return safe text for the failing assertion.

    No child is waited, restarted, terminated or adopted here. The original
    assertion remains a failure even when evidence cannot be saved.
    """
    try:
        value = failure_snapshot(folder, processes, scenario, barrier=barrier)
        raw = json.dumps(value, sort_keys=True)
        if len(raw.encode('utf-8')) > MAX_REPORT_BYTES:
            raise ValueError('oversized')
    except Exception:
        return 'WINDOWS_RECOVERY_DIAGNOSTIC unavailable'
    try:
        artifact_dir = Path(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / ('smoke-timeout-windows-recovery-' + uuid.uuid4().hex + '.json')).write_text(
            raw + '\n', encoding='utf-8')
    except Exception:
        # Still include evidence in unittest's original failure output.
        return 'WINDOWS_RECOVERY_DIAGNOSTIC artifact_unavailable ' + raw
    return 'WINDOWS_RECOVERY_DIAGNOSTIC ' + raw
