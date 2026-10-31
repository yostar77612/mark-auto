"""Desktop job implementation extracted without changing safety control flow."""

from __future__ import annotations
import ctypes
import json
from quantlab.research_core.domain.job_protocol import MAX_JSON
import multiprocessing as mp
import os
from pathlib import Path
import signal
import sys
import time
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.domain.job_protocol import DEFAULT_OPERATION_REGISTRAR, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS


class _WindowsProcessTree:
    """Kill-on-close job object. Child waits until assigned; grandchildren inherit."""

    def __init__(self, pid):
        # Load this platform-specific API only on its supported execution path.
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', w.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', w.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', w.DWORD),
                ('SchedulingClass', w.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    'ReadOperationCount',
                    'WriteOperationCount',
                    'OtherOperationCount',
                    'ReadTransferCount',
                    'WriteTransferCount',
                    'OtherTransferCount',
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', Basic),
                ('IoInfo', Counters),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeSafetyError('Cannot create worker isolation job')
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        child = k.OpenProcess(0x0100 | 0x0001, False, pid)
        try:
            if (
                not child
                or not k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not k.AssignProcessToJobObject(self.handle, child)
            ):
                self.close()
                raise RuntimeSafetyError('Cannot isolate worker process tree')
        finally:
            if child:
                k.CloseHandle(child)

    def stop_and_join(self, *, deadline=None):
        """Keep the Job handle; an earlier caller deadline shares the six-second reserve."""
        # Keep operation-specific dependencies out of module startup.
        import math

        now = time.monotonic()
        if deadline is None:
            deadline = now + 6
        elif type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise RuntimeSafetyError('Invalid worker cleanup deadline')
        else:
            deadline = min(deadline, now + 6)
        # Load this platform-specific API only on its supported execution path.
        from ctypes import wintypes as w

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
                (name, w.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')
            ]

        k = self.kernel
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        if not self.handle or not k.TerminateJobObject(self.handle, 1):
            raise RuntimeSafetyError('Cannot stop worker process tree')
        while True:
            info = Accounting()
            if not k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                raise RuntimeSafetyError('Cannot verify worker process tree')
            if time.monotonic() > deadline:
                raise RuntimeSafetyError('Worker cleanup exceeded unchanged deadline')
            if info.ActiveProcesses == 0:
                return
            if time.monotonic() >= deadline:
                raise RuntimeSafetyError('Worker descendants still active')
            time.sleep(0.02)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _launch_job_process(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request):
    from quantlab.research_core.adapters import job_worker

    context = mp.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    gate = context.Event()
    self._gate = gate
    self.job_id = job_id
    self._terminal = False
    self._pipe_eof = False
    self._deferred = []
    worker_args = (
        sender,
        gate,
        operation,
        payload,
        str(self.paths.root),
        str(self.paths.bootstrap) if self.paths.bootstrap else None,
        self.job_id,
        reconciliation_admitted,
    )
    if helper_nonce is not None:
        worker_args += (helper_nonce,)
    if job_worker._executor_registrar not in (None, DEFAULT_OPERATION_REGISTRAR):
        if helper_nonce is None:
            worker_args += (None,)
        worker_args += (job_worker._executor_registrar,)
    self.process = context.Process(target=job_worker._job_worker, args=worker_args, kwargs={'storage_port': self.storage_port})
    self.receiver = receiver
    try:
        self.process.start()
        sender.close()
        if helper_nonce is not None:
            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery import admission, register_launch, plan_bindings

            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery_windows import WindowsAnalysisRecoveryTree

            # Keep operation-specific dependencies out of module startup.
            from quantlab.core import content_hash

            anticipated = {
                'job_id': job_id,
                'helper_nonce': helper_nonce,
                **plan_bindings(approved_analysis_plan),
                'source_request_hash': content_hash(request),
            }
            self.tree = WindowsAnalysisRecoveryTree(self.process, gate, self.paths, max(0.0, self._deadline - time.monotonic()), anticipated=anticipated)
            with admission(self.paths) as ownership:
                launch = register_launch(
                    self.paths, job_id=job_id, helper_nonce=helper_nonce, approved_plan=approved_analysis_plan, request=request, admission=ownership
                )
            self.tree.activate(launch)
        else:
            if sys.platform == 'win32':
                self.tree = _WindowsProcessTree(self.process.pid)
            gate.set()
        self._log('started')
    except BaseException as exc:
        sender.close()
        if self.tree is None and getattr(exc, 'recovery_tree', None) is not None:
            self.tree = exc.recovery_tree  # Retain exact ownership after incomplete helper cleanup.
        self.cancel()
        raise


def _join_descendants(self, pid):
    if self.tree:
        self.tree.stop_and_join()
        return
    if not pid or sys.platform == 'win32':
        if self._operation in WALK_FORWARD_OPERATIONS or self._operation in ANALYSIS_OPERATIONS:
            raise RuntimeSafetyError('Cannot prove managed subtree stopped; reconciliation blocked')
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 6
    while True:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        # A reparented zombie cannot perform I/O. Linux may retain it until
        # its new parent reaps it; prove every remaining group member is Z.
        if sys.platform.startswith('linux'):
            live = False
            for item in Path('/proc').iterdir():
                if not item.name.isdigit():
                    continue
                try:
                    fields = (item / 'stat').read_text().rsplit(')', 1)[1].split()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if int(fields[2]) == pid and fields[0] != 'Z':
                    live = True
                    break
            if not live:
                return
        if time.monotonic() >= deadline:
            raise RuntimeSafetyError('Worker descendants still active; reconciliation blocked')
        time.sleep(0.02)


def _stop(self):
    proc = self.process
    if self.tree:
        if self._requires_tree_quiescence:
            self.tree.stop_and_join()
        else:
            self.tree.close()
    elif proc.pid and proc.is_alive():
        if sys.platform != 'win32':
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                proc.terminate()
        else:
            proc.terminate()
    if proc.pid:
        proc.join(3)
        if proc.is_alive():
            proc.kill()
            proc.join(3)
        if proc.is_alive():
            raise RuntimeSafetyError('Worker did not stop; do not restore or close')


class DesktopJobProcess:
    launch = staticmethod(_launch_job_process)
    join_descendants = staticmethod(_join_descendants)
    stop = staticmethod(_stop)


def _drain(self, events):
    for _ in range(16):
        # The protocol ends at its terminal packet. Windows PeekNamedPipe
        # raises ERROR_BROKEN_PIPE after sender close, unlike POSIX poll.
        if self._terminal or self._pipe_eof:
            return
        try:
            if not self.receiver.poll():
                return
            raw = self.receiver.recv_bytes(MAX_JSON)
        except EOFError:
            self._pipe_eof = True
            return
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 109:  # ERROR_BROKEN_PIPE
                self._pipe_eof = True
                return
            raise  # Invalid handles, oversized packets, etc. fail closed.
        event = json.loads(raw)
        if not isinstance(event, dict) or event.get('job_id') != self.job_id or event.get('type') not in {'progress', 'result', 'error', 'auth_progress'}:
            raise RuntimeSafetyError('Invalid worker response')
        if event['type'] == 'result' and self._walk_forward_result_reference is not None:
            result = event.get('result')
            if not isinstance(result, dict) or result.get('reference') != self._walk_forward_result_reference:
                raise RuntimeSafetyError('Walk-forward worker reference mismatch')
        if event['type'] == 'result' and self._analysis_result_reference is not None:
            result = event.get('result')
            if not isinstance(result, dict) or result.get('analysis_id') != self._analysis_result_reference:
                raise RuntimeSafetyError('Analysis worker reference mismatch')
        if event['type'] == 'auth_progress':
            auth_event = event.get('auth_event')
            allowed = {
                'request_id',
                'kind',
                'state',
                'registrations',
                'active_registration',
                'authorization_url',
                'error_code',
                'revocation_confirmed',
                'models',
                'model_labels',
                'account_labels',
            }
            if (
                self._operation != 'ui_chatgpt_auth'
                or not isinstance(auth_event, dict)
                or set(auth_event) - allowed
                or auth_event.get('request_id') != self._auth_request_id
                or auth_event.get('kind') not in ('authorization', 'progress')
            ):
                raise RuntimeSafetyError('Invalid private authentication event')
            # Transient OAuth query data must never enter persistent logs.
        else:
            self._log(event['type'], error_code=event.get('error_code') if event['type'] == 'error' else None)
        if event['type'] in {'result', 'error'}:
            self._terminal = True
            self._deferred.append(event)
        else:
            events.append(event)


DesktopJobProcess.drain = staticmethod(_drain)
