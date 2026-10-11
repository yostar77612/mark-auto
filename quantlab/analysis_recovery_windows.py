"""One Windows analysis helper; original handles only, no PID-based recovery.

The helper owns the only unnamed kill-on-close job handle. The GUI commits the
launch before activation. Missing durable proof remains unresolved, including
helper death. An anticipated immutable binding covers lost activation messages.
"""
from __future__ import annotations

import ctypes
import json
import math
import multiprocessing as mp
import sys
import time

from .desktop_runtime import RuntimeSafetyError, WindowsAppMutex

GATE_SECONDS = 15
STOP_SECONDS = 6
MAX_PACKET = 16384
SYNCHRONIZE = 0x00100000


def _kernel():
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE,
                                 ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
    k.DuplicateHandle.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.WaitForSingleObject.restype = w.DWORD
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    k.CreateJobObjectW.restype = w.HANDLE
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.SetInformationJobObject.restype = w.BOOL
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.AssignProcessToJobObject.restype = w.BOOL
    k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    k.TerminateJobObject.restype = w.BOOL
    k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
    k.QueryInformationJobObject.restype = w.BOOL
    return k


def _alive(k, handle):
    result = k.WaitForSingleObject(handle, 0)
    if result not in (0, 258):
        raise RuntimeSafetyError('Cannot observe original process handle')
    return result == 258


def _duplicate(k, handle, target, access):
    from ctypes import wintypes as w
    copied = w.HANDLE()
    if not k.DuplicateHandle(k.GetCurrentProcess(), handle, target,
                             ctypes.byref(copied), access, False, 0):
        raise RuntimeSafetyError('Cannot transfer original process handle')
    return copied.value


class _OriginalJob:
    """Constructed only inside the helper from an already-retained worker handle."""
    def __init__(self, kernel, worker_handle):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
                        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Counters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeSafetyError('Cannot create original analysis job')
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        try:
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise RuntimeSafetyError('Cannot set original analysis job limits')
            if not kernel.AssignProcessToJobObject(self.handle, worker_handle):
                raise RuntimeSafetyError('Cannot contain original analysis worker')
        except BaseException:
            self.close()
            raise

    def active_processes(self):
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime', 'TotalKernelTime',
                        'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [(name, w.DWORD)
                        for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]
        info = Accounting()
        if not self.handle or not self.kernel.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise RuntimeSafetyError('Cannot query original analysis job')
        return info.ActiveProcesses

    def stop_and_join(self):
        if not self.handle or not self.kernel.TerminateJobObject(self.handle, 1):
            raise RuntimeSafetyError('Cannot stop original analysis job')
        deadline = time.monotonic() + STOP_SECONDS
        while self.active_processes() != 0:
            if time.monotonic() >= deadline:
                raise RuntimeSafetyError('Original analysis descendants still active')
            time.sleep(.02)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _send(connection, message):
    raw = json.dumps(message, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_PACKET:
        raise RuntimeSafetyError('Analysis helper packet too large')
    connection.send_bytes(raw)


def _receive(connection):
    message = json.loads(connection.recv_bytes(MAX_PACKET))
    if type(message) is not dict:
        raise RuntimeSafetyError('Invalid analysis helper packet')
    return message


def _verify_launch(paths, anticipated, *, for_admission=False, expected=None, recover_controls=False):
    # Read existing controls only. Never create/register or reconstruct a plan.
    from .analysis_recovery import read_launch
    if recover_controls:
        # GUI crash can leave an interrupted SQLite transaction. Roll it back
        # only under original control admission; this grants no stop authority.
        from .analysis_recovery import admission, recover_control_journal
        with admission(paths) as token:
            recover_control_journal(paths, admission=token)
            launch = read_launch(paths, anticipated['job_id'], expected=expected,
                                 for_admission=for_admission)
    else:
        launch = read_launch(paths, anticipated['job_id'], expected=expected,
                             for_admission=for_admission)
    if any(launch.get(key) != value for key, value in anticipated.items()):
        raise RuntimeSafetyError('Original helper launch binding differs')
    return launch


def _publish(paths, launch, tree):
    from .analysis_recovery import _StopPublisher
    _StopPublisher(paths, launch, tree.active_processes).publish()


def _supervise(connection, gate, paths, anticipated, deadline, admission_deadline,
               k, gui, worker, tree):
    """Finite protocol, separable for negative fault tests without Windows claims."""
    launch = None
    try:
        _send(connection, {'state': 'ready'})
        while time.monotonic() < min(admission_deadline, deadline):
            if not _alive(k, gui) or not _alive(k, worker):
                return
            if connection.poll(.02):
                packet = _receive(connection)
                if set(packet) != {'activate'}:
                    return
                launch = _verify_launch(paths, anticipated, for_admission=True,
                                        expected=packet['activate'])
                if (time.monotonic() >= min(admission_deadline, deadline)
                        or not _alive(k, gui) or not _alive(k, worker)):
                    return
                gate.set()
                _send(connection, {'state': 'active'})
                break
        else:
            return
        while time.monotonic() < deadline:
            if not _alive(k, gui) or not _alive(k, worker):
                break
            if connection.poll(.02):
                # Any further message seals this one-shot admission.
                _receive(connection)
                break
    finally:
        tree.stop_and_join()
        if launch is None:
            # GUI may commit and die before its activation packet arrives.
            # Only this helper's pre-bound exact row can be read; absence,
            # mismatch, corrupt controls or storage failure grants no proof.
            try:
                launch = _verify_launch(paths, anticipated, recover_controls=True)
            except Exception:
                launch = None
        if launch is not None:
            _publish(paths, launch, tree)
        _send(connection, {'state': 'stopped', 'receipt': launch is not None})


def _helper_main(connection, gate, paths, anticipated, deadline, admission_deadline):
    _validate_anticipated(anticipated)
    k = _kernel()
    gui = worker = tree = mutex = None
    try:
        remaining = max(0, admission_deadline - time.monotonic())
        if not connection.poll(remaining):
            return
        packet = _receive(connection)
        if set(packet) != {'gui', 'worker'} or any(type(packet[key]) is not int or packet[key] <= 0 for key in packet):
            raise RuntimeSafetyError('Invalid original analysis handles')
        gui, worker = packet['gui'], packet['worker']
        mutex = WindowsAppMutex()
        if not _alive(k, gui) or not _alive(k, worker):
            return
        tree = _OriginalJob(k, worker)
        _supervise(connection, gate, paths, anticipated, deadline, admission_deadline, k, gui, worker, tree)
    except (Exception, KeyboardInterrupt):
        try:
            _send(connection, {'state': 'failed'})
        except (OSError, EOFError):
            pass
    finally:
        # Last-handle close is safety fallback only. It never publishes proof.
        if tree is not None:
            tree.close()
        for handle in (worker, gui):
            if handle:
                k.CloseHandle(handle)
        if mutex is not None:
            mutex.close()
        connection.close()


def _validate_anticipated(value):
    # The GUI derives these bounded pure values before spawning this generation.
    fields = {'job_id', 'helper_nonce', 'analysis_id', 'registration', 'plan_hash',
              'provider_hash', 'request_hash', 'request_bytes', 'model',
              'timeout_seconds', 'ledger_basename', 'source_request_hash'}
    import re
    if type(value) is not dict or set(value) != fields:
        raise RuntimeSafetyError('Invalid anticipated analysis binding')
    for key in ('job_id', 'helper_nonce', 'registration', 'analysis_id', 'plan_hash',
                'provider_hash', 'request_hash', 'source_request_hash'):
        length = 32 if key in ('job_id', 'helper_nonce', 'registration') else 64
        if type(value[key]) is not str or re.fullmatch('[0-9a-f]{' + str(length) + '}', value[key]) is None:
            raise RuntimeSafetyError('Invalid anticipated analysis identity')
    if (value['helper_nonce'] == value['job_id'] or type(value['request_bytes']) is not int
            or not 1 <= value['request_bytes'] <= 65536
            or type(value['timeout_seconds']) is not int or not 1 <= value['timeout_seconds'] <= 120
            or type(value['model']) is not str or re.fullmatch('[A-Za-z0-9._:-]{1,128}', value['model']) is None
            or value['ledger_basename'] != 'chatgpt-analysis-' + value['analysis_id'] + '.sqlite3'):
        raise RuntimeSafetyError('Invalid anticipated analysis binding')


class WindowsAnalysisRecoveryTree:
    """GUI-side adapter. Construct, commit launch in GUI, then activate once."""
    def __init__(self, process, gate, paths, execution_timeout, *, anticipated):
        if sys.platform != 'win32':
            raise RuntimeSafetyError('Durable analysis supervision requires Windows')
        if (type(execution_timeout) not in (int, float) or not math.isfinite(execution_timeout)
                or not 0 < execution_timeout <= 250):
            raise RuntimeSafetyError('Invalid analysis helper deadline')
        _validate_anticipated(anticipated)
        self.helper_nonce = anticipated['helper_nonce']
        self._connection = self._helper = None
        self._activated = self._stopped = False
        self._terminal_packet = None
        self._stop_deadline = None
        self._admission_deadline = time.monotonic() + GATE_SECONDS
        deadline = time.monotonic() + execution_timeout
        context = mp.get_context('spawn')
        self._connection, child = context.Pipe(duplex=True)
        self._helper = context.Process(target=_helper_main,
            args=(child, gate, paths, anticipated, deadline, self._admission_deadline), name='analysis-stop-helper')
        try:
            self._helper.start()
            child.close()
            k = _kernel()
            target = int(self._helper._popen._handle)
            gui = _duplicate(k, k.GetCurrentProcess(), target, SYNCHRONIZE)
            worker = _duplicate(k, int(process._popen._handle), target, SYNCHRONIZE | 0x0100 | 0x0001)
            _send(self._connection, {'gui': gui, 'worker': worker})
            self._expect('ready', max(0, self._admission_deadline - time.monotonic()))
        except BaseException as original:
            child.close()
            try:
                self.close()
            except BaseException as cleanup:
                # JobManager retains this exact adapter before cancellation;
                # never lose an unconfirmed original helper handle on setup.
                error = RuntimeSafetyError('Analysis helper setup cleanup is unconfirmed')
                error.recovery_tree = self
                raise error from cleanup
            raise original

    def _expect(self, expected, timeout, *, deadline=None):
        deadline = time.monotonic() + timeout if deadline is None else deadline
        drained = set()
        while True:
            packet = self._terminal_packet
            if packet is None:
                if self._connection is None or not self._connection.poll(max(0, deadline - time.monotonic())):
                    raise RuntimeSafetyError('Analysis helper response deadline exceeded')
                packet = _receive(self._connection)
                state = packet.get('state')
                fields = {'state', 'receipt'} if state == 'stopped' else {'state'}
                if (state not in ('ready', 'active', 'stopped', 'failed') or set(packet) != fields
                        or (state == 'stopped' and type(packet['receipt']) is not bool)):
                    raise RuntimeSafetyError('Invalid analysis helper acknowledgement')
                if state in ('stopped', 'failed'):
                    # Activation can race a terminal packet. Preserve it for
                    # cleanup rather than requiring an acknowledgement twice.
                    self._terminal_packet = packet
            state = packet['state']
            if state == expected:
                return packet
            if expected == 'stopped' and state in ('ready', 'active') and state not in drained:
                drained.add(state)
                if time.monotonic() >= deadline:
                    raise RuntimeSafetyError('Analysis helper response deadline exceeded')
                continue
            raise RuntimeSafetyError('Analysis helper did not confirm ' + expected)

    def activate(self, launch):
        if self._activated or self._stopped:
            raise RuntimeSafetyError('Analysis helper admission already sealed')
        self._activated = True
        _send(self._connection, {'activate': launch})
        self._expect('active', max(0, self._admission_deadline - time.monotonic()))

    admit = activate

    def stop_and_join(self):
        if self._stopped:
            return
        if self._stop_deadline is None:
            self._stop_deadline = time.monotonic() + STOP_SECONDS + 1
        try:
            if self._connection is not None:
                _send(self._connection, {'stop': True})
        except (OSError, EOFError):
            pass
        packet = self._expect('stopped', 0, deadline=self._stop_deadline)
        if self._activated and packet['receipt'] is not True:
            raise RuntimeSafetyError('Analysis stop receipt unavailable')
        self._helper.join(timeout=min(1, max(0, self._stop_deadline + 1 - time.monotonic())))
        if self._helper.is_alive():
            raise RuntimeSafetyError('Analysis helper did not exit')
        self._stopped = True

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._helper is not None:
            if self._helper.pid is not None:
                self._helper.join(timeout=STOP_SECONDS + 1)
                if self._helper.is_alive():
                    self._helper.terminate()
                    self._helper.join(timeout=1)
                if self._helper.is_alive():
                    error = RuntimeSafetyError('Original analysis helper exit is unconfirmed')
                    error.recovery_tree = self
                    raise error
                self._helper.close()
            self._helper = None
