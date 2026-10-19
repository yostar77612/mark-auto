"""TEST-ONLY Windows supervision experiment; NOT production recovery authority.

Locked gates: original helper-owned job survives GUI death; the helper observes
real process-handle death and zero active job members before durable TEST_ONLY
receipt publication; premature helper death never publishes a receipt. Three
native scenarios plus pure TEST_ONLY protocol fault cuts. No provider, credentials,
network, service, or product changes.

Maximum four child processes (GUI stub/helper/worker/grandchild), one job, and
one temporary directory per case. All waits are bounded. A class-wide 90-second
watchdog aborts the test runner with a failing exit after handle-only cleanup.
Server/token provenance is diagnostic, not clean-client or standard-user proof.
"""

from __future__ import annotations

import ctypes
import hashlib
import sqlite3
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.windows_recovery_diagnostics import FixtureDiagnostics, report_failure

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
    k.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
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


def _terminate(k, handle, *, deadline=None):
    if _state(k, handle) == WAIT_TIMEOUT:
        if not k.TerminateProcess(handle, 91):
            error = ctypes.get_last_error()  # Preserve before another Win32 call.
            if error != 5:  # ERROR_ACCESS_DENIED can race asynchronous termination.
                raise OSError(error, 'TerminateProcess failed')
            # Cleanup may have already requested termination through this exact
            # retained handle. An access error is NOT proof of exit. Wait only
            # within the existing shared cleanup budget and require signalled.
            remaining_ms = 0 if deadline is None else max(0, int((deadline - time.monotonic()) * 1000))
            state = k.WaitForSingleObject(handle, remaining_ms)
            if state == WAIT_OBJECT_0:
                return
            if state != WAIT_TIMEOUT:
                raise OSError(ctypes.get_last_error(), 'termination confirmation wait failed')
            raise OSError(error, 'TerminateProcess failed; original handle did not signal within cleanup budget')


def _write(folder, name, value):
    from quantlab.desktop_runtime import atomic_write

    atomic_write(folder / name, json.dumps(value, sort_keys=True).encode(), durable=True)


_FIXTURE_JSON_LIMIT = 16384


class _FixtureRecordAbsent(FileNotFoundError):
    """Only initial open absence; read/metadata/close failures stay fatal."""


def _read_fixture_json(path, *, kernel=None):
    """Bounded immutable fixture snapshot; coexist with a rename's DELETE handle."""
    path = Path(path)
    if sys.platform != 'win32' and kernel is None:
        try:
            stream = path.open('rb')
        except FileNotFoundError as error:
            raise _FixtureRecordAbsent(*error.args) from None
        with stream:
            raw = stream.read(_FIXTURE_JSON_LIMIT + 1)
        if len(raw) > _FIXTURE_JSON_LIMIT:
            raise ValueError('fixture JSON exceeds bound')
        return json.loads(raw.decode('utf-8'))
    from ctypes import wintypes as w

    class Information(ctypes.Structure):
        _fields_ = [
            ('attributes', w.DWORD),
            ('created', w.FILETIME),
            ('accessed', w.FILETIME),
            ('written', w.FILETIME),
            ('volume', w.DWORD),
            ('size_high', w.DWORD),
            ('size_low', w.DWORD),
            ('links', w.DWORD),
            ('index_high', w.DWORD),
            ('index_low', w.DWORD),
        ]

    k = _kernel() if kernel is None else kernel
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(Information)]
    k.GetFileInformationByHandle.restype = w.BOOL
    k.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    k.ReadFile.restype = w.BOOL
    # No FILE_SHARE_WRITE: atomically published fixture records are immutable.
    handle = k.CreateFileW(str(path), 0x80000000, 0x1 | 0x4, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in (2, 3):
            raise _FixtureRecordAbsent('fixture record not yet published') from None
        raise ctypes.WinError(error)
    try:
        info = Information()
        if not k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & (0x10 | 0x400):
            raise ValueError('fixture JSON requires a regular non-reparse file')
        if (info.size_high << 32) | info.size_low > _FIXTURE_JSON_LIMIT:
            raise ValueError('fixture JSON exceeds bound')
        buffer = ctypes.create_string_buffer(_FIXTURE_JSON_LIMIT + 1)
        received = w.DWORD()
        if not k.ReadFile(handle, buffer, len(buffer), ctypes.byref(received), None):
            raise ctypes.WinError(ctypes.get_last_error())
        raw = buffer.raw[: received.value]
        if len(raw) > _FIXTURE_JSON_LIMIT:
            raise ValueError('fixture JSON exceeds bound')
        return json.loads(raw.decode('utf-8'))
    finally:
        if not k.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _wait_file(folder, name, deadline):
    while time.monotonic() < deadline:
        if (folder / 'cleanup-request.json').exists():
            raise RuntimeError('fixture cleanup requested')
        try:
            return _read_fixture_json(folder / name)
        except _FixtureRecordAbsent:
            pass
        time.sleep(0.01)
    raise TimeoutError(name)


def _command(role, folder, observer, token, *extra):
    return [sys.executable, str(Path(__file__).resolve()), '--fixture', role, str(folder), str(observer), token, *map(str, extra)]


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
        _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
            (name, w.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')
        ]

    info = Accounting()
    _check(tree.kernel.QueryInformationJobObject(tree.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None), 'query original job')
    return info.ActiveProcesses


def _fixture(role, folder, observer, token, extra, *, diagnosis):
    diagnosis.at('kernel')
    k = _kernel()
    deadline = time.monotonic() + CHILD_SECONDS
    if role in ('gui', 'grandchild'):
        if role == 'gui':
            # TEST_ONLY stand-in for original GUI ownership of the single-instance
            # admission boundary. This experiment does not instantiate QLockFile.
            diagnosis.at('gui.launch.commit')
            protocol = _TestOnlyProtocol(folder, _test_binding(folder, token))
            protocol.commit_launch(original_gui_admission=True)
            diagnosis.at('gui.launch.signal')
            _write(folder, 'gui-launch-committed.json', {'test_only': True})
        diagnosis.at('idle')
        # A finite emergency lifetime bounds even test-observer disappearance.
        while time.monotonic() < deadline:
            time.sleep(0.02)
        return
    if role == 'worker':
        child = None
        try:
            diagnosis.at('worker.gate.wait')
            _wait_file(folder, 'worker-go.json', deadline)
            # The real gated worker independently reopens the committed launch.
            diagnosis.at('worker.launch.read')
            _TestOnlyProtocol(folder, _test_binding(folder, token)).read_launch()
            diagnosis.at('worker.grandchild.start')
            child = subprocess.Popen(
                _command('grandchild', folder, observer, token), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True
            )
            diagnosis.at('worker.handle.publish')
            _publish_process_handle(child, folder, 'grandchild')
            diagnosis.at('worker.ack.wait')
            _wait_file(folder, 'grandchild-ack.json', deadline)
            diagnosis.at('worker.ready.signal')
            _write(folder, 'worker-ready.json', {'test_only': True})
            diagnosis.at('worker.monitor')
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('grandchild exited before fixture stop')
                time.sleep(0.01)
            raise TimeoutError('worker emergency deadline')
        except BaseException as error:
            diagnosis.record_failure(error)
            raise
        finally:
            diagnosis.at('worker.cleanup')
            _dispose_child(child)
    if role != 'helper':
        raise ValueError('unknown fixture role')
    diagnosis.at('helper.runtime.import')
    from quantlab.desktop_runtime import _WindowsProcessTree

    diagnosis.at('helper.admission')
    gui_handle, worker_handle = map(int, extra)
    tree = None
    try:
        diagnosis.at('helper.admission')
        if _state(k, gui_handle) != WAIT_TIMEOUT:
            raise RuntimeError('GUI must be alive at helper admission')
        if _state(k, worker_handle) != WAIT_TIMEOUT:
            raise RuntimeError('gated worker must be alive at helper admission')
        worker_pid = _check(k.GetProcessId(worker_handle), 'original worker identity')
        diagnosis.at('helper.job.create')
        tree = _WindowsProcessTree(worker_pid)
        diagnosis.at('helper.protocol.open')
        protocol = _TestOnlyProtocol(folder, _test_binding(folder, token))
        diagnosis.at('helper.gui_commit.wait')
        _wait_file(folder, 'gui-launch-committed.json', deadline)
        diagnosis.at('helper.gate.open')
        protocol.open_registered_gate(lambda: _write(folder, 'worker-go.json', {'test_only': True}), original_helper_owned=True)
        diagnosis.at('helper.worker_ready.wait')
        _wait_file(folder, 'worker-ready.json', deadline)
        diagnosis.at('helper.ready.signal')
        _write(folder, 'helper-ready.json', {'test_only': True, 'job_handle_retained': True})
        diagnosis.at('helper.gui_death.wait')
        while _state(k, gui_handle) != WAIT_OBJECT_0:
            if (folder / 'cleanup-request.json').exists():
                raise RuntimeError('fixture cleanup requested')
            if time.monotonic() >= deadline:
                raise TimeoutError('GUI death wait')
            time.sleep(0.01)
        diagnosis.at('helper.gui_death.signal')
        _write(folder, 'gui-death-observed.json', {'test_only': True})
        diagnosis.at('helper.quiescence.wait')
        _wait_file(folder, 'allow-quiescence.json', deadline)
        diagnosis.at('helper.job.stop')
        tree.stop_and_join()
        active = _active_processes(tree)  # Query the SAME still-open job again.
        if active != 0:
            raise RuntimeError('nonzero original job after stop_and_join')
        diagnosis.at('helper.quiescence.signal')
        _write(folder, 'quiescence-observed.json', {'active_processes': active})
        # Observer checks all retained descendant handles before publication.
        diagnosis.at('helper.receipt.wait')
        _wait_file(folder, 'allow-receipt.json', deadline)
        if _active_processes(tree) != 0:
            raise RuntimeError('original job changed before receipt')
        diagnosis.at('helper.receipt.publish')
        receipt = protocol.publish(lambda: _active_processes(tree))
        # Diagnostic projection is not authority; committed SQLite is reread.
        diagnosis.at('helper.receipt.signal')
        _write(folder, 'receipt.json', receipt)
    except BaseException as error:
        diagnosis.record_failure(error)
        raise
    finally:
        diagnosis.at('helper.cleanup')
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


# This protocol model deliberately lives only in this test module. Its records
# and caller-supplied observations are NEVER accepted by product reconciliation.
# Hashes bind fixture context; they do not authenticate hostile same-user edits or
# rollback of the entire control store. No restore or production epoch API exists.
_TEST_BINDING_KEYS = frozenset(
    {
        'kind',
        'installation',
        'control_root',
        'workspace_root',
        'epoch',
        'launch',
        'analysis',
        'registration',
        'plan_hash',
        'provider_hash',
        'request_hash',
        'request_bytes',
        'budget_ledger',
        'helper_build',
    }
)
_TEST_RECORD_LIMIT = 16384
_TEST_LEDGER_LIMIT = 131072


def _test_binding(folder, token):
    return {
        'kind': 'TEST_ONLY_LAUNCH_V1',
        'installation': 'fixture-installation',
        'control_root': str((folder / 'controls').resolve()),
        'workspace_root': str((folder / 'workspace').resolve()),
        'epoch': 0,
        'launch': token,
        'analysis': 'a' * 64,
        'registration': 'b' * 32,
        'plan_hash': 'c' * 64,
        'provider_hash': 'd' * 64,
        'request_hash': 'e' * 64,
        'request_bytes': 17,
        'budget_ledger': 'TEST_ONLY_consumed_budget',
        'helper_build': 'TEST_ONLY_fixture_v1',
    }


def _test_encoded(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > _TEST_RECORD_LIMIT:
        raise ValueError('TEST_ONLY record exceeds bound')
    return encoded


class _TestOnlyProtocol:
    """Small crash-cut model, NOT a production ledger/verifier implementation."""

    def __init__(self, folder, binding):
        self.folder = Path(folder)
        self.path = self.folder / 'controls' / 'TEST_ONLY_recovery.sqlite3'
        self.binding = json.loads(_test_encoded(binding))
        if (
            set(self.binding) != _TEST_BINDING_KEYS
            or self.binding['kind'] != 'TEST_ONLY_LAUNCH_V1'
            or type(self.binding['epoch']) is not int
            or self.binding['epoch'] < 0
            or type(self.binding['request_bytes']) is not int
            or not 1 <= self.binding['request_bytes'] <= 65536
            or any(type(value) is not str or not value or len(value) > 4096 for key, value in self.binding.items() if key not in ('epoch', 'request_bytes'))
        ):
            raise ValueError('invalid TEST_ONLY launch binding')

    def _open(self, *, initialize=False, write=False):
        if initialize:
            self.path.parent.mkdir(exist_ok=True)
        if self.path.is_symlink():
            raise ValueError('TEST_ONLY ledger link refused')
        if self.path.exists() and self.path.stat().st_size > _TEST_LEDGER_LIMIT:
            raise ValueError('TEST_ONLY ledger exceeds bound')
        mode = 'rwc' if initialize else ('rw' if write else 'ro')
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=0)
        if write or initialize:
            db.execute('PRAGMA synchronous=FULL')
        return db

    @staticmethod
    def _row(db, table):
        if table not in ('launch', 'receipt', 'gate'):
            raise ValueError('invalid fixture table')
        sizes = db.execute('SELECT id,length(CAST(payload AS BLOB)) FROM ' + table).fetchmany(2)
        if not sizes:
            return None
        if len(sizes) != 1 or sizes[0][0] != 1 or not 1 <= sizes[0][1] <= _TEST_RECORD_LIMIT:
            raise ValueError('invalid bounded TEST_ONLY record')
        value = json.loads(db.execute('SELECT payload FROM ' + table + ' WHERE id=1').fetchone()[0])
        _test_encoded(value)
        return value

    def _original_launch(self, db):
        launch = self._row(db, 'launch')
        if launch is None or _test_encoded(launch) != _test_encoded(self.binding):
            raise ValueError('original TEST_ONLY launch/context mismatch')
        if self.binding['control_root'] != str(self.path.parent.resolve()):
            raise ValueError('original TEST_ONLY control root mismatch')
        return launch

    def commit_launch(self, *, original_gui_admission=False, before_commit=None, after_commit=None):
        """Model original-GUI commit inside its held admission boundary only.

        The Boolean is an explicit fixture observation, never production proof.
        No helper path calls this method, and acknowledgement loss cannot transfer
        original-GUI authority to a new helper or permit another launch.
        """
        if original_gui_admission is not True:
            raise ValueError('TEST_ONLY original GUI admission ownership required')
        if self.binding['control_root'] != str(self.path.parent.resolve()):
            raise ValueError('original TEST_ONLY control root mismatch')
        with closing(self._open(initialize=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for table in ('launch', 'receipt', 'gate'):
                db.execute('CREATE TABLE IF NOT EXISTS ' + table + ' (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
            if self._row(db, 'launch') is not None:
                raise ValueError('TEST_ONLY launch already claimed; never re-execute')
            db.execute('INSERT INTO launch VALUES(1,?)', (_test_encoded(self.binding),))
            if before_commit:
                before_commit()
            db.commit()
        if after_commit:
            after_commit()

    def open_registered_gate(self, open_gate, *, original_helper_owned=False):
        """One original-helper gate claim; receipt reads remain idempotent.

        Ownership is an explicit TEST_ONLY observation of the fixture's actual
        retained job/worker handles, not a production Boolean authorization API.
        """
        if original_helper_owned is not True:
            raise ValueError('TEST_ONLY original helper ownership required')
        with closing(self._open(write=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            launch = self._original_launch(db)
            if self._row(db, 'receipt') is not None or self._row(db, 'gate') is not None:
                raise ValueError('TEST_ONLY gate already claimed or launch stopped')
            claim = {'kind': 'TEST_ONLY_ONE_USE_GATE', 'launch_hash': self._receipt(launch)['launch_hash']}
            db.execute('INSERT INTO gate VALUES(1,?)', (_test_encoded(claim),))
            db.commit()
        # A lost callback/ACK leaves a claimed gate, never a retry opportunity.
        open_gate()

    def guarded_conflicting_operation(self, operation):
        """Serialize fixture live-tree checks AND the operation with admission.

        This is only an operation-boundary model. It is not an implemented GUI
        quarantine, backup admission guard, filesystem policy, or repair route.
        """
        with closing(self._open(write=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            launch = self._row(db, 'launch')
            if launch is not None:
                self._original_launch(db)
                receipt = self._row(db, 'receipt')
                if receipt is None or _test_encoded(receipt) != _test_encoded(self._receipt(launch)):
                    raise ValueError('TEST_ONLY unresolved original tree conflict')
            result = operation()  # Remains inside the SAME serialization lock.
            db.commit()
            return result

    def read_launch(self):
        with closing(self._open()) as db:
            return self._original_launch(db)

    def _receipt(self, launch):
        return {
            'kind': 'TEST_ONLY_NOT_PRODUCTION_ADMISSIBLE',
            'test_launch': launch['launch'],
            'active_processes': 0,
            'gui_death_observed': True,
            'launch_hash': hashlib.sha256(_test_encoded(launch).encode()).hexdigest(),
        }

    def publish(self, observe_original_job, *, before_commit=None, after_commit=None):
        with closing(self._open(write=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            launch = self._original_launch(db)
            active = observe_original_job()
            if type(active) is not int or active != 0:
                raise ValueError('TEST_ONLY original job is not observed zero')
            receipt = self._receipt(launch)
            old = self._row(db, 'receipt')
            if old is None:
                db.execute('INSERT INTO receipt VALUES(1,?)', (_test_encoded(receipt),))
            elif _test_encoded(old) != _test_encoded(receipt):
                raise ValueError('conflicting TEST_ONLY receipt')
            if before_commit:
                before_commit()
            db.commit()
        if after_commit:
            after_commit()
        return receipt

    def read_receipt(self):
        # No initialize-on-read, no write, no burning of a one-use token.
        with closing(self._open()) as db:
            launch = self._original_launch(db)
            receipt = self._row(db, 'receipt')
            if receipt is None or _test_encoded(receipt) != _test_encoded(self._receipt(launch)):
                raise ValueError('missing or invalid TEST_ONLY receipt')
            return receipt


class TestOnlyDurableProtocolTests(unittest.TestCase):
    """Pure temporary-ledger fault cuts; no GUI/process/provider execution."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='TEST_ONLY_protocol_')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.binding = _test_binding(self.folder, 'fixture-launch')
        self.store = _TestOnlyProtocol(self.folder, self.binding)
        self.protected = self.folder / 'TEST_ONLY_original_controls.json'
        self.protected.write_text('{"calls":1,"status":"reserved_unknown","registration":"original"}')
        self.before = self.protected.read_bytes()
        self.addCleanup(lambda: self.assertEqual(self.protected.read_bytes(), self.before))

    @staticmethod
    def fault():
        raise OSError('TEST_ONLY injected publication fault')

    def assert_no_authority(self):
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.store.read_receipt()

    def test_admission_is_committed_before_gate_and_cannot_be_reopened(self):
        gates = []
        self.store.commit_launch(original_gui_admission=True)
        self.store.open_registered_gate(lambda: gates.append(self.store.read_launch()), original_helper_owned=True)
        self.assertEqual(gates, [self.binding])
        with self.assertRaises(ValueError):
            self.store.commit_launch(original_gui_admission=True)
        with self.assertRaises(ValueError):
            self.store.open_registered_gate(lambda: gates.append('forbidden second execution'), original_helper_owned=True)
        self.assertEqual(gates, [self.binding])
        self.assert_no_authority()

    def test_admission_failure_and_lost_ack_never_open_gate(self):
        gates = []
        with self.assertRaises(OSError):
            self.store.commit_launch(original_gui_admission=True, before_commit=self.fault)
            self.store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(gates, [])
        self.assert_no_authority()
        # No launch was committed by the failed transaction. A separate fixture
        # admission now tests the commit/ACK cut, not product retry permission.
        with self.assertRaises(OSError):
            self.store.commit_launch(original_gui_admission=True, after_commit=self.fault)
            self.store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(self.store.read_launch(), self.binding)
        with self.assertRaises(ValueError):
            self.store.commit_launch(original_gui_admission=True)
            self.store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(gates, [])
        self.assert_no_authority()

    def test_missing_controls_and_legacy_absence_do_not_initialize_on_read(self):
        self.assert_no_authority()
        self.assertFalse(self.store.path.parent.exists())
        # This absence grants no receipt; the model does not implement or claim
        # a production quarantine or block unrelated legacy/non-AI operations.

    def test_nonzero_unknown_and_failed_publication_never_grant_authority(self):
        self.store.commit_launch(original_gui_admission=True)
        for active in (1, None, False):
            with self.subTest(active=active), self.assertRaises(ValueError):
                self.store.publish(lambda: active)
            self.assert_no_authority()
        with self.assertRaises(OSError):
            self.store.publish(self.fault)
        self.assert_no_authority()
        with self.assertRaises(OSError):
            self.store.publish(lambda: 0, before_commit=self.fault)
        self.assert_no_authority()

    def test_committed_receipt_lost_ack_is_idempotent_not_an_execution_token(self):
        gates = []
        self.store.commit_launch(original_gui_admission=True)
        self.store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        with self.assertRaises(OSError):
            self.store.publish(lambda: 0, after_commit=self.fault)
        receipt = self.store.read_receipt()
        before = self.store.path.read_bytes()
        reopened = _TestOnlyProtocol(self.folder, self.binding)
        self.assertEqual(reopened.read_receipt(), receipt)
        self.assertEqual(reopened.read_receipt(), receipt)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(reopened.publish(lambda: 0), receipt)
        with self.assertRaises(ValueError):
            reopened.commit_launch(original_gui_admission=True)
        with self.assertRaises(ValueError):
            reopened.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(gates, [True])

    def test_altered_binding_root_epoch_and_launch_replay_are_rejected_without_write(self):
        self.store.commit_launch(original_gui_admission=True)
        self.store.publish(lambda: 0)
        before = self.store.path.read_bytes()
        for key in _TEST_BINDING_KEYS - {'kind'}:
            changed = dict(self.binding)
            changed[key] = changed[key] + 1 if type(changed[key]) is int else changed[key] + '-altered'
            with self.subTest(key=key):
                impostor = _TestOnlyProtocol(self.folder, changed)
                with self.assertRaises(ValueError):
                    impostor.read_receipt()
                with self.assertRaises(ValueError):
                    impostor.publish(lambda: 0)
                with self.assertRaises(ValueError):
                    impostor.open_registered_gate(lambda: self.fail('replayed execution'), original_helper_owned=True)
                self.assertEqual(self.store.path.read_bytes(), before)
        # Copying the ledger into another controls root does not make its old
        # launch root authoritative, even when copied bytes are identical.
        other = self.folder / 'copy'
        (other / 'controls').mkdir(parents=True)
        copy = _TestOnlyProtocol(other, self.binding)
        copy.path.write_bytes(before)
        with self.assertRaises(ValueError):
            copy.read_receipt()
        self.assertEqual(copy.path.read_bytes(), before)

    def test_conflicting_receipt_is_not_overwritten(self):
        self.store.commit_launch(original_gui_admission=True)
        self.store.publish(lambda: 0)
        with closing(self.store._open(write=True)) as db, db:
            wrong = self.store._receipt(self.binding)
            wrong['launch_hash'] = 'f' * 64
            db.execute('UPDATE receipt SET payload=? WHERE id=1', (_test_encoded(wrong),))
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.publish(lambda: 0)
        self.assert_no_authority()
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_gate_requires_original_helper_and_never_reopens_after_claim_or_callback_failure(self):
        self.store.commit_launch(original_gui_admission=True)
        gates = []
        with self.assertRaises(ValueError):
            self.store.open_registered_gate(lambda: gates.append(True))
        with self.assertRaises(OSError):
            self.store.open_registered_gate(self.fault, original_helper_owned=True)
        reopened = _TestOnlyProtocol(self.folder, self.binding)
        for store in (self.store, reopened):
            with self.assertRaises(ValueError):
                store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(gates, [])
        self.assert_no_authority()

    def test_stop_receipt_before_gate_permanently_refuses_later_execution(self):
        self.store.commit_launch(original_gui_admission=True)
        receipt = self.store.publish(lambda: 0)
        gates = []
        for store in (self.store, _TestOnlyProtocol(self.folder, self.binding)):
            with self.assertRaises(ValueError):
                store.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
            self.assertEqual(store.read_receipt(), receipt)
        self.assertEqual(gates, [])

    def test_gui_death_before_commit_cannot_be_adopted_by_helper(self):
        gates = []
        with self.assertRaises(OSError):
            self.store.commit_launch(original_gui_admission=True, before_commit=self.fault)
        helper = _TestOnlyProtocol(self.folder, self.binding)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            helper.commit_launch()  # Helper has no original-GUI admission role.
        with self.assertRaises((ValueError, sqlite3.Error)):
            helper.open_registered_gate(lambda: gates.append(True), original_helper_owned=True)
        self.assertEqual(gates, [])
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assert_no_authority()

    def test_admission_and_conflicting_operation_are_serialized_not_check_then_act(self):
        # Explicit fixture installation setup, separate from recovery/read paths.
        with closing(self.store._open(initialize=True)) as db, db:
            for table in ('launch', 'receipt', 'gate'):
                db.execute('CREATE TABLE ' + table + ' (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
        contender = _TestOnlyProtocol(self.folder, self.binding)
        events = []

        def operation_while_locked():
            with self.assertRaises(sqlite3.OperationalError):
                contender.commit_launch(original_gui_admission=True)
            events.append('operation completed under admission lock')

        self.store.guarded_conflicting_operation(operation_while_locked)

        def before_admission_commit():
            with self.assertRaises(sqlite3.OperationalError):
                contender.guarded_conflicting_operation(lambda: events.append('forbidden overlap'))
            with self.assertRaises(sqlite3.OperationalError):
                contender.commit_launch(original_gui_admission=True)

        self.store.commit_launch(original_gui_admission=True, before_commit=before_admission_commit)
        with self.assertRaises(ValueError):
            contender.guarded_conflicting_operation(lambda: events.append('forbidden unresolved action'))

        def before_receipt_commit():
            with self.assertRaises(sqlite3.OperationalError):
                contender.guarded_conflicting_operation(lambda: events.append('forbidden premature action'))

        self.store.publish(lambda: 0, before_commit=before_receipt_commit)
        contender.guarded_conflicting_operation(lambda: events.append('operation after committed stop'))
        self.assertEqual(events, ['operation completed under admission lock', 'operation after committed stop'])

    def test_valid_stop_clears_live_tree_conflict_but_not_missing_journal_validation(self):
        self.store.commit_launch(original_gui_admission=True)
        with self.assertRaises(ValueError):
            self.store.guarded_conflicting_operation(lambda: 'forbidden')
        self.store.publish(lambda: 0)
        self.assertEqual(self.store.guarded_conflicting_operation(lambda: 'fixture local action'), 'fixture local action')
        # A valid TEST_ONLY stop row cannot supply a missing research journal.
        # This invokes the unchanged strict product reader, not a repair action.
        from quantlab.research_analysis import read_analysis

        with self.assertRaises(ValueError):
            read_analysis(self.folder / 'missing-analyses', self.binding['analysis'])
        self.assertFalse((self.folder / 'missing-analyses').exists())
        self.assertEqual(self.store.read_receipt()['kind'], 'TEST_ONLY_NOT_PRODUCTION_ADMISSIBLE')


class TerminationCleanupRegressionTests(unittest.TestCase):
    """Deterministic Win32-result protocol test; never starts a process."""

    def test_async_termination_race_requires_exact_handle_signal_within_existing_budget(self):
        class Kernel:
            def __init__(self, states):
                self.states = iter(states)
                self.waits = []
                self.terminations = []

            def WaitForSingleObject(self, handle, milliseconds):
                self.waits.append((handle, milliseconds))
                return next(self.states)

            def TerminateProcess(self, handle, code):
                self.terminations.append((handle, code))
                return 0

        original = 123456  # Synthetic handle, never passed to the operating system.
        for outcome, succeeds in ((WAIT_OBJECT_0, True), (WAIT_TIMEOUT, False), (0xFFFFFFFF, False)):
            with self.subTest(outcome=outcome):
                kernel = Kernel([WAIT_TIMEOUT, outcome])
                with patch.object(ctypes, 'get_last_error', return_value=5, create=True), patch.object(time, 'monotonic', return_value=100):
                    if succeeds:
                        _terminate(kernel, original, deadline=101)
                    else:
                        with self.assertRaises(OSError):
                            _terminate(kernel, original, deadline=101)
                self.assertEqual(kernel.waits, [(original, 0), (original, 1000)])
                self.assertEqual(kernel.terminations, [(original, 91)])
        # Genuine non-access API errors fail immediately, regardless of deadline.
        kernel = Kernel([WAIT_TIMEOUT])
        with patch.object(ctypes, 'get_last_error', return_value=6, create=True):
            with self.assertRaises(OSError):
                _terminate(kernel, original, deadline=101)
        self.assertEqual(kernel.waits, [(original, 0)])
        # An exhausted budget cannot acquire a fresh wait allowance.
        kernel = Kernel([WAIT_TIMEOUT, WAIT_TIMEOUT])
        with patch.object(ctypes, 'get_last_error', return_value=5, create=True), patch.object(time, 'monotonic', return_value=101):
            with self.assertRaises(OSError):
                _terminate(kernel, original, deadline=100)
        self.assertEqual(kernel.waits, [(original, 0), (original, 0)])


class FixtureJsonSnapshotTests(unittest.TestCase):
    def fake_kernel(self, raw=b'{}', *, size=None):
        from unittest.mock import Mock

        kernel = SimpleNamespace(CreateFileW=Mock(return_value=100), GetFileInformationByHandle=Mock(), ReadFile=Mock(), CloseHandle=Mock(return_value=True))

        def info(handle, pointer):
            pointer._obj.attributes = 0x80
            pointer._obj.size_high = 0
            pointer._obj.size_low = len(raw) if size is None else size
            return True

        def read(handle, buffer, capacity, received, overlapped):
            ctypes.memmove(buffer, raw, len(raw))
            received._obj.value = len(raw)
            return True

        kernel.GetFileInformationByHandle.side_effect = info
        kernel.ReadFile.side_effect = read
        return kernel

    @staticmethod
    def native_error(code):
        error = PermissionError(13, 'synthetic native denial') if code in (5, 32) else OSError('synthetic native failure')
        error.winerror = code
        return error

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows DELETE-share control')
    def test_delete_holder_blocks_ordinary_read_but_snapshot_succeeds_while_open(self):
        from ctypes import wintypes as w

        with tempfile.TemporaryDirectory(prefix='TEST_ONLY_delete_share_') as temporary:
            folder = Path(temporary)
            value = {'source_handle': 123}
            _write(folder, 'grandchild.handle.json', value)
            path = folder / 'grandchild.handle.json'
            kernel = _kernel()
            kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
            kernel.CreateFileW.restype = w.HANDLE
            holder = kernel.CreateFileW(str(path), 0x10000, 0x7, None, 3, 0x80, None)
            self.assertNotEqual(holder, ctypes.c_void_p(-1).value)
            try:
                with self.assertRaises(PermissionError) as ordinary:
                    path.read_text(encoding='utf-8')
                self.assertEqual(ordinary.exception.errno, 13)
                self.assertEqual(_read_fixture_json(path), value)
                # Compatible read completed while the original DELETE owner remained open.
                self.assertEqual(_read_fixture_json(path), value)
            finally:
                _check(kernel.CloseHandle(holder), 'close DELETE control handle')

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows exclusive-read control')
    def test_exclusive_read_denial_is_not_swallowed(self):
        from ctypes import wintypes as w

        with tempfile.TemporaryDirectory(prefix='TEST_ONLY_exclusive_share_') as temporary:
            folder = Path(temporary)
            _write(folder, 'held.json', {})
            path = folder / 'held.json'
            kernel = _kernel()
            kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
            kernel.CreateFileW.restype = w.HANDLE
            holder = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
            self.assertNotEqual(holder, ctypes.c_void_p(-1).value)
            try:
                with self.assertRaises(PermissionError) as failure:
                    _read_fixture_json(path)
                self.assertEqual(failure.exception.winerror, 32)
            finally:
                _check(kernel.CloseHandle(holder), 'close exclusive control handle')

    def test_native_access_denied_is_fatal_not_absence(self):
        kernel = self.fake_kernel()
        kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
        with patch.object(ctypes, 'get_last_error', return_value=5, create=True), patch.object(ctypes, 'WinError', side_effect=self.native_error, create=True):
            with self.assertRaises(PermissionError) as failure:
                _read_fixture_json('fixture.json', kernel=kernel)
        self.assertEqual(failure.exception.winerror, 5)
        self.assertNotIsInstance(failure.exception, _FixtureRecordAbsent)
        kernel.CloseHandle.assert_not_called()

    def test_initial_missing_record_is_distinct_from_other_failures(self):
        kernel = self.fake_kernel()
        kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
        with patch.object(ctypes, 'get_last_error', return_value=2, create=True):
            with self.assertRaises(_FixtureRecordAbsent):
                _read_fixture_json('fixture.json', kernel=kernel)
        kernel.ReadFile.assert_not_called()
        kernel.CloseHandle.assert_not_called()

    def test_invalid_json_closes_handle_and_preserves_failure(self):
        kernel = self.fake_kernel(b'{invalid')
        with self.assertRaises(json.JSONDecodeError):
            _read_fixture_json('fixture.json', kernel=kernel)
        kernel.CloseHandle.assert_called_once_with(100)

    def test_oversize_record_is_bounded_and_handle_is_closed(self):
        kernel = self.fake_kernel(size=_FIXTURE_JSON_LIMIT + 1)
        with self.assertRaisesRegex(ValueError, 'exceeds bound'):
            _read_fixture_json('fixture.json', kernel=kernel)
        kernel.ReadFile.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(100)

    def test_close_failure_is_fatal_even_when_json_was_valid(self):
        kernel = self.fake_kernel()
        kernel.CloseHandle.return_value = False
        with patch.object(ctypes, 'get_last_error', return_value=6, create=True), patch.object(ctypes, 'WinError', side_effect=self.native_error, create=True):
            with self.assertRaises(OSError) as failure:
                _read_fixture_json('fixture.json', kernel=kernel)
        self.assertEqual(failure.exception.winerror, 6)
        kernel.CloseHandle.assert_called_once_with(100)

    def test_poll_does_not_turn_acl_denial_or_late_missing_error_into_readiness(self):
        with tempfile.TemporaryDirectory(prefix='TEST_ONLY_poll_failure_') as temporary:
            for failure in (self.native_error(5), FileNotFoundError('late read/close error')):
                with self.subTest(kind=type(failure).__name__), patch(__name__ + '._read_fixture_json', side_effect=failure):
                    with self.assertRaises(type(failure)):
                        _wait_file(Path(temporary), 'not-yet-published.json', time.monotonic() + 1)


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
                    if role not in handles:
                        try:
                            value = _read_fixture_json(path)
                        except _FixtureRecordAbsent:
                            continue
                        source = value['source_handle']
                        if type(source) is not int or source <= 0:
                            raise ValueError('invalid source process handle')
                        duplicate = w.HANDLE()
                        _check(
                            k.DuplicateHandle(
                                handles['worker'], source, k.GetCurrentProcess(), ctypes.byref(duplicate), SYNCHRONIZE | PROCESS_TERMINATE, False, 0
                            ),
                            'receive retained grandchild handle',
                        )
                        # Register immediately, before any operation that could
                        # fail, so teardown owns every allocated target handle.
                        register(role, duplicate.value)
                        _state(k, duplicate.value)
                        _write(folder, role + '-ack.json', {'test_only': True})

            def fail_with_diagnostic(message, barrier):
                evidence = report_failure(folder, processes, scenario, artifact_dir=ROOT / 'dist' / 'validation', barrier=barrier)
                self.fail(message + '; ' + evidence)

            def until(predicate, message):
                while time.monotonic() < deadline:
                    collect()
                    if predicate():
                        return
                    for role in ('gui', 'helper'):
                        proc = processes.get(role)
                        if proc is not None and role not in expected_dead and proc.poll() is not None:
                            fail_with_diagnostic(role + ' failed before expected barrier', message)
                    time.sleep(0.01)
                fail_with_diagnostic('bounded fixture timeout: ' + message, message)

            expected_dead = set()
            try:
                gui = subprocess.Popen(
                    _command('gui', folder, os.getpid(), token), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True
                )
                processes['gui'] = gui
                register('gui', int(gui._handle))
                # Observer owns the worker handle BEFORE helper launch: even a
                # helper failure before job assignment cannot orphan this child.
                worker = subprocess.Popen(
                    _command('worker', folder, os.getpid(), token),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                processes['worker'] = worker
                register('worker', int(worker._handle))
                for proc in (gui, worker):
                    duplicate = w.HANDLE()
                    _check(
                        k.DuplicateHandle(
                            k.GetCurrentProcess(), int(proc._handle), k.GetCurrentProcess(), ctypes.byref(duplicate), SYNCHRONIZE | 0x1000, True, 0
                        ),
                        'duplicate inherited process handle',
                    )
                    transferred.append(duplicate)
                startup = subprocess.STARTUPINFO()
                startup.lpAttributeList = {'handle_list': [handle.value for handle in transferred]}
                helper = subprocess.Popen(
                    _command('helper', folder, os.getpid(), token, *(handle.value for handle in transferred)),
                    startupinfo=startup,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes['helper'] = helper
                register('helper', int(helper._handle))
                while transferred:
                    _check(k.CloseHandle(transferred[-1]), 'close parent process duplicate')
                    transferred.pop()
                until(lambda: (folder / 'helper-ready.json').is_file(), 'helper readiness')
                self.assertEqual(set(handles), {'gui', 'helper', 'worker', 'grandchild'})
                protocol = _TestOnlyProtocol(folder, _test_binding(folder, token))
                self.assertEqual(protocol.read_launch(), _test_binding(folder, token))
                with self.assertRaises(ValueError):
                    protocol.read_receipt()
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
                    self.assertEqual(_read_fixture_json(folder / 'quiescence-observed.json'), {'active_processes': 0})
                    for role in ('worker', 'grandchild'):
                        self.assertEqual(_state(k, handles[role]), WAIT_OBJECT_0)
                    self.assertFalse((folder / 'receipt.json').exists())
                    expected_dead.add('helper')
                    _write(folder, 'allow-receipt.json', {'test_only': True})
                    until(lambda: (folder / 'receipt.json').is_file(), 'durable receipt')
                    receipt = _read_fixture_json(folder / 'receipt.json')
                    self.assertEqual(receipt, protocol.read_receipt())
                    self.assertEqual(receipt, protocol._receipt(protocol.binding))
                    until(lambda: helper.poll() is not None, 'helper clean exit')
                    self.assertEqual(helper.returncode, 0)
                else:
                    expected_dead.add('helper')
                    _terminate(k, handles['helper'])
                    until(lambda: all(_state(k, handles[r]) == WAIT_OBJECT_0 for r in ('helper', 'worker', 'grandchild')), 'kill-on-close cleanup')
                    self.assertFalse((folder / 'receipt.json').exists())
                    self.assertFalse((folder / 'quiescence-observed.json').exists())
                    with self.assertRaises(ValueError):
                        protocol.read_receipt()
                    if scenario == 'helper_after_gui':
                        # Both original GUI and helper are now dead. Absence of
                        # either process never becomes a durable stop receipt.
                        self.assertEqual(_state(k, handles['gui']), WAIT_OBJECT_0)
                        self.assertEqual(_state(k, handles['helper']), WAIT_OBJECT_0)
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
                    errors.append('cleanup-request: ' + str(exc))
                if 'gui' in handles:
                    try:
                        _terminate(k, handles['gui'], deadline=cleanup_deadline)
                    except OSError as exc:
                        errors.append('gui initial-stop: ' + str(exc))
                if 'helper' in processes and processes['helper'].poll() is None:
                    try:
                        processes['helper'].wait(timeout=min(6.5, max(0, cleanup_deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        errors.append('helper did not confirm cooperative cleanup')
                # Last-resort termination still targets retained handles only.
                for role in ('gui', 'helper', 'worker'):
                    if role in handles:
                        try:
                            _terminate(k, handles[role], deadline=cleanup_deadline)
                        except OSError as exc:
                            errors.append(role + ' fallback-stop: ' + str(exc))
                for role, proc in processes.items():
                    try:
                        proc.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired as exc:
                        errors.append(role + ' Popen wait: ' + str(exc))
                # Uncollected source handles belong to the now-stopped worker,
                # never to this observer. Its job contained the grandchild before
                # publication; closing helper's sole job handle stops that tree.
                for role, handle in list(handles.items()):
                    try:
                        _terminate(k, handle, deadline=cleanup_deadline)
                        remaining_ms = max(0, int((cleanup_deadline - time.monotonic()) * 1000))
                        if k.WaitForSingleObject(handle, remaining_ms) != WAIT_OBJECT_0:
                            raise RuntimeError('cleanup did not confirm exit: ' + role)
                    except (OSError, RuntimeError) as exc:
                        errors.append(role + ' final-confirmation: ' + str(exc))
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
        folder, role = Path(sys.argv[3]), sys.argv[2]
        FixtureDiagnostics(folder, role).run(_fixture, role, folder, int(sys.argv[4]), sys.argv[5], sys.argv[6:])
    else:
        unittest.main()
