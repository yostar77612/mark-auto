"""TEST-ONLY Windows supervision experiment; NOT production recovery authority.

Locked gates: original helper-owned job survives GUI death; the helper observes
real process-handle death and zero active job members before durable TEST_ONLY
receipt publication; premature helper death never publishes a receipt. Three
scenarios only. No provider, credentials, network, service, or product changes.

Maximum four child processes (GUI stub/helper/worker/grandchild), one job, and
one temporary directory per case. All waits are bounded. A class-wide 90-second
watchdog aborts the test runner with a failing exit after handle-only cleanup.
Server/token provenance is diagnostic, not clean-client or standard-user proof.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
CASE_SECONDS = 18
CHILD_SECONDS = 30


def _kernel():
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetProcessId.argtypes = [w.HANDLE]
    k.GetProcessId.restype = w.DWORD
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.WaitForSingleObject.restype = w.DWORD
    k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k.TerminateProcess.restype = w.BOOL
    k.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE,
                                 ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
    k.DuplicateHandle.restype = w.BOOL
    return k


def _check(value, operation):
    if not value:
        raise OSError(ctypes.get_last_error(), operation)
    return value


def _state(k, handle):
    result = k.WaitForSingleObject(handle, 0)
    if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
        raise OSError(ctypes.get_last_error(), 'WaitForSingleObject failed')
    return result


def _terminate(k, handle):
    if _state(k, handle) == WAIT_TIMEOUT:
        if not k.TerminateProcess(handle, 91):
            # An independent natural exit can race the termination request.
            if _state(k, handle) != WAIT_OBJECT_0:
                raise OSError(ctypes.get_last_error(), 'TerminateProcess failed')


def _write(folder, name, value):
    from quantlab.desktop_runtime import atomic_write
    atomic_write(folder / name, json.dumps(value, sort_keys=True).encode(), durable=True)


def _wait_file(folder, name, deadline):
    while time.monotonic() < deadline:
        if (folder / 'cleanup-request.json').exists():
            raise RuntimeError('fixture cleanup requested')
        if (folder / name).is_file():
            return json.loads((folder / name).read_text())
        time.sleep(.01)
    raise TimeoutError(name)


def _command(role, folder, observer, token, *extra):
    return [sys.executable, str(Path(__file__).resolve()), '--fixture', role,
            str(folder), str(observer), token, *map(str, extra)]


def _publish_process_handle(process, folder, role):
    """Publish a retained SOURCE handle; the observer performs duplication.

    No handle is allocated in the observer until it receives this record. The
    worker retains this Popen object until ACK or teardown, so the source handle
    cannot be recycled while the fixture is waiting for acknowledgement.
    """
    _write(folder, role + '.handle.json', {'source_handle': int(process._handle)})


def _dispose_child(process):
    if process is not None:
        if process.poll() is None:
            process.kill()  # Popen retains the original Windows process handle.
        process.wait(timeout=3)


def _active_processes(tree):
    from ctypes import wintypes as w
    class Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int64) for name in
                    ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime',
                     'ThisPeriodTotalKernelTime')] + [(name, w.DWORD) for name in
                    ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses',
                     'TotalTerminatedProcesses')]
    info = Accounting()
    _check(tree.kernel.QueryInformationJobObject(tree.handle, 1, ctypes.byref(info),
                                               ctypes.sizeof(info), None), 'query original job')
    return info.ActiveProcesses


def _fixture(role, folder, observer, token, extra):
    k = _kernel()
    deadline = time.monotonic() + CHILD_SECONDS
    if role in ('gui', 'grandchild'):
        # A finite emergency lifetime bounds even test-observer disappearance.
        while time.monotonic() < deadline:
            time.sleep(.02)
        return
    if role == 'worker':
        child = None
        try:
            _wait_file(folder, 'worker-go.json', deadline)
            child = subprocess.Popen(_command('grandchild', folder, observer, token),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=True)
            _publish_process_handle(child, folder, 'grandchild')
            _wait_file(folder, 'grandchild-ack.json', deadline)
            _write(folder, 'worker-ready.json', {'test_only': True})
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('grandchild exited before fixture stop')
                time.sleep(.01)
            raise TimeoutError('worker emergency deadline')
        finally:
            _dispose_child(child)
    if role != 'helper':
        raise ValueError('unknown fixture role')
    from quantlab.desktop_runtime import _WindowsProcessTree
    gui_handle, worker_handle = map(int, extra)
    tree = None
    try:
        if _state(k, gui_handle) != WAIT_TIMEOUT:
            raise RuntimeError('GUI must be alive at helper admission')
        if _state(k, worker_handle) != WAIT_TIMEOUT:
            raise RuntimeError('gated worker must be alive at helper admission')
        worker_pid = _check(k.GetProcessId(worker_handle), 'original worker identity')
        tree = _WindowsProcessTree(worker_pid)
        _write(folder, 'worker-go.json', {'test_only': True})
        _wait_file(folder, 'worker-ready.json', deadline)
        _write(folder, 'helper-ready.json', {'test_only': True, 'job_handle_retained': True})
        while _state(k, gui_handle) != WAIT_OBJECT_0:
            if (folder / 'cleanup-request.json').exists():
                raise RuntimeError('fixture cleanup requested')
            if time.monotonic() >= deadline:
                raise TimeoutError('GUI death wait')
            time.sleep(.01)
        _write(folder, 'gui-death-observed.json', {'test_only': True})
        _wait_file(folder, 'allow-quiescence.json', deadline)
        tree.stop_and_join()
        active = _active_processes(tree)  # Query the SAME still-open job again.
        if active != 0:
            raise RuntimeError('nonzero original job after stop_and_join')
        _write(folder, 'quiescence-observed.json', {'active_processes': active})
        # Observer checks all retained descendant handles before publication.
        _wait_file(folder, 'allow-receipt.json', deadline)
        if _active_processes(tree) != 0:
            raise RuntimeError('original job changed before receipt')
        _write(folder, 'receipt.json', {'kind': 'TEST_ONLY_NOT_PRODUCTION_ADMISSIBLE',
               'test_launch': token, 'active_processes': 0, 'gui_death_observed': True})
    finally:
        if tree is not None:
            try:
                tree.stop_and_join()
                if _active_processes(tree) != 0:
                    raise RuntimeError('nonzero original job in cleanup')
                _write(folder, 'cleanup-quiescence.json', {'test_only': True, 'active_processes': 0})
            finally:
                tree.close()
        _check(k.CloseHandle(worker_handle), 'close worker process handle')
        _check(k.CloseHandle(gui_handle), 'close GUI process handle')


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only prototype; native verification deferred')
class WindowsRecoveryFeasibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._lock = threading.RLock()
        cls._handles = set()
        cls._kernel = _kernel()
        def hard_watchdog():
            # All handles are original or explicitly duplicated process handles.
            # Terminating helper closes the sole Job Object handle too. Children
            # additionally have finite emergency lifetimes. Never report PASS.
            acquired = False
            try:
                # Never let a stalled main-thread critical section disable the
                # outer stop. Normal teardown remains responsible for verified
                # cleanup; the emergency path must terminate with failure.
                acquired = cls._lock.acquire(blocking=False)
                if acquired:
                    for handle in tuple(cls._handles):
                        try:
                            _terminate(cls._kernel, handle)
                        except OSError:
                            pass
                # No logging here: even stderr may be a full blocking pipe.
            finally:
                try:
                    if acquired:
                        cls._lock.release()
                finally:
                    os._exit(124)  # Includes broken stderr and cleanup errors.
        cls._watchdog = threading.Timer(90, hard_watchdog)
        cls._watchdog.daemon = True
        cls._watchdog.start()

    @classmethod
    def tearDownClass(cls):
        cls._watchdog.cancel()

    def _case(self, scenario):
        from ctypes import wintypes as w
        k = self._kernel
        deadline = time.monotonic() + CASE_SECONDS
        token = uuid.uuid4().hex
        handles, processes = {}, {}
        transferred = []
        with tempfile.TemporaryDirectory(prefix='TEST_ONLY_windows_recovery_') as temp:
            folder = Path(temp)
            def register(role, handle):
                with self._lock:
                    handles[role] = handle
                    self._handles.add(handle)
            def collect():
                for role in ('grandchild',):
                    path = folder / (role + '.handle.json')
                    if role not in handles and path.is_file():
                        source = json.loads(path.read_text())['source_handle']
                        if type(source) is not int or source <= 0:
                            raise ValueError('invalid source process handle')
                        duplicate = w.HANDLE()
                        _check(k.DuplicateHandle(handles['worker'], source, k.GetCurrentProcess(),
                                ctypes.byref(duplicate), SYNCHRONIZE | PROCESS_TERMINATE,
                                False, 0), 'receive retained grandchild handle')
                        # Register immediately, before any operation that could
                        # fail, so teardown owns every allocated target handle.
                        register(role, duplicate.value)
                        _state(k, duplicate.value)
                        _write(folder, role + '-ack.json', {'test_only': True})
            def until(predicate, message):
                while time.monotonic() < deadline:
                    collect()
                    if predicate():
                        return
                    for role in ('gui', 'helper'):
                        proc = processes.get(role)
                        if proc is not None and role not in expected_dead and proc.poll() is not None:
                            self.fail(role + ' failed before expected barrier')
                    time.sleep(.01)
                self.fail('bounded fixture timeout: ' + message)
            expected_dead = set()
            try:
                gui = subprocess.Popen(_command('gui', folder, os.getpid(), token),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
                processes['gui'] = gui
                register('gui', int(gui._handle))
                # Observer owns the worker handle BEFORE helper launch: even a
                # helper failure before job assignment cannot orphan this child.
                worker = subprocess.Popen(_command('worker', folder, os.getpid(), token),
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, close_fds=True)
                processes['worker'] = worker
                register('worker', int(worker._handle))
                for proc in (gui, worker):
                    duplicate = w.HANDLE()
                    _check(k.DuplicateHandle(k.GetCurrentProcess(), int(proc._handle),
                            k.GetCurrentProcess(), ctypes.byref(duplicate),
                            SYNCHRONIZE | 0x1000, True, 0), 'duplicate inherited process handle')
                    transferred.append(duplicate)
                startup = subprocess.STARTUPINFO()
                startup.lpAttributeList = {'handle_list': [handle.value for handle in transferred]}
                helper = subprocess.Popen(_command('helper', folder, os.getpid(), token,
                                                   *(handle.value for handle in transferred)),
                                          startupinfo=startup, close_fds=True,
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
                processes['helper'] = helper
                register('helper', int(helper._handle))
                while transferred:
                    _check(k.CloseHandle(transferred[-1]), 'close parent process duplicate')
                    transferred.pop()
                until(lambda: (folder / 'helper-ready.json').is_file(), 'helper readiness')
                self.assertEqual(set(handles), {'gui', 'helper', 'worker', 'grandchild'})
                self.assertFalse((folder / 'receipt.json').exists())
                if scenario != 'helper_before_gui':
                    expected_dead.add('gui')
                    _terminate(k, handles['gui'])
                    until(lambda: (folder / 'gui-death-observed.json').is_file(), 'GUI death')
                    self.assertEqual(_state(k, handles['gui']), WAIT_OBJECT_0)
                    self.assertEqual(_state(k, handles['worker']), WAIT_TIMEOUT)
                    self.assertEqual(_state(k, handles['grandchild']), WAIT_TIMEOUT)
                    self.assertFalse((folder / 'receipt.json').exists())
                if scenario == 'normal':
                    _write(folder, 'allow-quiescence.json', {'test_only': True})
                    until(lambda: (folder / 'quiescence-observed.json').is_file(), 'zero active')
                    self.assertEqual(json.loads((folder / 'quiescence-observed.json').read_text()),
                                     {'active_processes': 0})
                    for role in ('worker', 'grandchild'):
                        self.assertEqual(_state(k, handles[role]), WAIT_OBJECT_0)
                    self.assertFalse((folder / 'receipt.json').exists())
                    expected_dead.add('helper')
                    _write(folder, 'allow-receipt.json', {'test_only': True})
                    until(lambda: (folder / 'receipt.json').is_file(), 'durable receipt')
                    receipt = json.loads((folder / 'receipt.json').read_text())
                    self.assertEqual(receipt, {'kind': 'TEST_ONLY_NOT_PRODUCTION_ADMISSIBLE',
                        'test_launch': token, 'active_processes': 0, 'gui_death_observed': True})
                    until(lambda: helper.poll() is not None, 'helper clean exit')
                    self.assertEqual(helper.returncode, 0)
                else:
                    expected_dead.add('helper')
                    _terminate(k, handles['helper'])
                    until(lambda: all(_state(k, handles[r]) == WAIT_OBJECT_0 for r in
                                      ('helper', 'worker', 'grandchild')), 'kill-on-close cleanup')
                    self.assertFalse((folder / 'receipt.json').exists())
                    self.assertFalse((folder / 'quiescence-observed.json').exists())
                    if scenario == 'helper_before_gui':
                        self.assertEqual(_state(k, handles['gui']), WAIT_TIMEOUT)
            finally:
                errors = []
                cleanup_deadline = time.monotonic() + 7
                # Prefer original helper's verified join on partial setup. This
                # covers a child created just before its handle record appeared.
                try:
                    collect()
                    _write(folder, 'cleanup-request.json', {'test_only': True})
                except (OSError, ValueError) as exc:
                    errors.append(str(exc))
                if 'gui' in handles:
                    try:
                        _terminate(k, handles['gui'])
                    except OSError as exc:
                        errors.append(str(exc))
                if 'helper' in processes and processes['helper'].poll() is None:
                    try:
                        processes['helper'].wait(timeout=min(6.5, max(0, cleanup_deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        errors.append('helper did not confirm cooperative cleanup')
                # Last-resort termination still targets retained handles only.
                for role in ('gui', 'helper', 'worker'):
                    if role in handles:
                        try:
                            _terminate(k, handles[role])
                        except OSError as exc:
                            errors.append(str(exc))
                for proc in processes.values():
                    try:
                        proc.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired as exc:
                        errors.append(str(exc))
                # Uncollected source handles belong to the now-stopped worker,
                # never to this observer. Its job contained the grandchild before
                # publication; closing helper's sole job handle stops that tree.
                for role, handle in list(handles.items()):
                    try:
                        _terminate(k, handle)
                        remaining_ms = max(0, int((cleanup_deadline - time.monotonic()) * 1000))
                        if k.WaitForSingleObject(handle, remaining_ms) != WAIT_OBJECT_0:
                            raise RuntimeError('cleanup did not confirm exit: ' + role)
                    except (OSError, RuntimeError) as exc:
                        errors.append(str(exc))
                    finally:
                        with self._lock:
                            self._handles.discard(handle)
                            if role not in processes:
                                if not k.CloseHandle(handle):
                                    errors.append('CloseHandle failed: ' + role)
                for handle in transferred:
                    if not k.CloseHandle(handle):
                        errors.append('CloseHandle failed: process transfer')
                self.assertFalse(errors, 'fixture cleanup failed: ' + '; '.join(errors))

    def test_gui_death_quiesces_before_test_only_durable_receipt(self):
        self._case('normal')

    def test_helper_death_before_gui_never_publishes_receipt(self):
        self._case('helper_before_gui')

    def test_helper_death_after_gui_before_quiescence_never_publishes_receipt(self):
        self._case('helper_after_gui')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fixture':
        if sys.platform != 'win32':
            raise SystemExit('Windows fixture only')
        _fixture(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6:])
    else:
        unittest.main()
