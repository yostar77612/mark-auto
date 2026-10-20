"""Explicit frozen packaging proof, using disposable synthetic smoke state only.

No provider is constructed. Source tests/mocks are not frozen or client proof.
"""

from __future__ import annotations

import ctypes
import math
import multiprocessing as mp
import os
from pathlib import Path as Path
import sys
import threading
import time
import uuid

from quantlab.analysis_recovery_windows import WindowsAnalysisRecoveryTree
from quantlab.desktop_runtime import AppPaths

CAP_SECONDS = 40
PREP_SECONDS = 6
SCOPE = 'synthetic frozen helper bootstrap/containment/receipt proof only; not GUI-death, real-model, OAuth or Windows-client acceptance'


def _remaining(deadline):
    return max(0.0, deadline - time.monotonic())


def _grandchild(deadline):
    # Finite lifetime even if the smoke observer itself disappears.
    while _remaining(deadline):
        time.sleep(min(0.05, _remaining(deadline)))


def _gated_worker(gate, connection, deadline):
    child = None
    try:
        if not gate.wait(_remaining(deadline)):
            return
        child = mp.get_context('spawn').Process(target=_grandchild, args=(deadline,))
        child.start()
        # Keep the original source handle alive until observer duplication.
        connection.send_bytes(str(int(child._popen._handle)).encode('ascii'))
        if not connection.poll(_remaining(deadline)) or connection.recv_bytes(8) != b'ACK':
            return
        while _remaining(deadline):
            time.sleep(min(0.05, _remaining(deadline)))
    finally:
        if child is not None:
            if child.is_alive():
                child.terminate()  # Retained multiprocessing handle, not PID lookup.
            child.join(timeout=min(1, _remaining(deadline)))
            if not child.is_alive():
                child.close()
        connection.close()


def _prepare_plan(fixture_paths, campaign_state, deadline):
    from quantlab.core import content_hash
    from quantlab.research_analysis import build_analysis_packet, make_analysis_plan
    from quantlab.saved_candidate_pool import _read_campaign, load_original_dataset

    root = fixture_paths.state
    dataset_path = root / 'dataset.json'
    data = load_original_dataset(dataset_path)
    if data.manifest.get('source_type') != 'synthetic' or len(data.bars) != 120:
        raise ValueError('Only the fixed packaging dataset is admissible')
    if (
        not isinstance(campaign_state, dict)
        or campaign_state.get('status') != 'completed'
        or campaign_state.get('real_model_status') != 'not_verified'
        or campaign_state.get('binding', {}).get('provider', {}).get('mode') != 'fixture'
    ):
        raise ValueError('Only the completed offline fixture campaign is admissible')
    campaign_root = root / 'campaigns'
    candidates = list(campaign_root.iterdir())
    if len(candidates) > 4:
        raise ValueError('Packaging fixture campaign bound exceeded')
    matches = []
    for folder in candidates:
        if folder.is_symlink() or not folder.is_dir():
            continue
        if len(folder.name) == 64 and all(c in '0123456789abcdef' for c in folder.name):
            state = _read_campaign(folder)
            if state == campaign_state:
                matches.append(folder)
    if len(matches) != 1:
        raise ValueError('Exact smoke campaign unavailable')
    attempts = campaign_state.get('attempts', [])
    if not attempts or attempts[0].get('status') != 'evaluated':
        raise ValueError('Fixture attempt was not evaluated')
    attempt = attempts[0]['attempt_id']
    remaining = min(PREP_SECONDS, int(_remaining(deadline)))
    if remaining < 1:
        raise TimeoutError('Frozen helper preparation budget exhausted')
    packet = build_analysis_packet(source_campaign_dir=matches[0], original_dataset=data, attempt_ids=[attempt], task='critique', max_runtime_seconds=remaining)
    # Pure synthetic descriptor, never credential provenance or a provider grant.
    plan = make_analysis_plan(
        packet,
        model='frozen-packaging-fixture',
        registration=uuid.uuid4().hex,
        provider_implementation={'source_sha256': {'offline_packaging_fixture': content_hash('synthetic')}},
        timeout_seconds=1,
    )
    request = {
        'campaign_reference': matches[0].name,
        'original_dataset': {'kind': 'local_dataset_file', 'path': str(dataset_path)},
        'attempt_ids': [attempt],
        'task': 'critique',
        'model': plan['binding']['model'],
        'registration': plan['binding']['registration'],
        'timeout_seconds': 1,
    }
    return plan, request


def run_recovery_smoke(fixture_paths, campaign_state, *, deadline):
    """A single bounded actual-frozen Windows path; caller retains failed cleanup.

    This must receive only the existing disposable packaging fixture. It reuses
    its completed campaign and never calls any provider/auth/model transport.
    The hard watchdog cannot turn a timeout into PASS; the EXE exits nonzero.
    """
    report = {
        'status': 'not_applicable',
        'scope': SCOPE,
        'source_type': 'synthetic',
        'frozen': bool(getattr(sys, 'frozen', False)),
        'network_used': False,
        'model_calls': 0,
        'real_model_status': 'not_verified',
        'windows_client_status': 'not_verified',
        'cleanup_verified': True,
    }
    if sys.platform != 'win32' or not report['frozen']:
        return report
    report['status'] = 'failed'
    if type(deadline) not in (float, int) or not math.isfinite(deadline):
        report['error_type'] = 'InvalidDeadline'
        return report
    started = time.monotonic()
    end = min(deadline, started + CAP_SECONDS)
    if end - started < CAP_SECONDS:
        report['error_type'] = 'InsufficientExistingSmokeBudget'
        return report
    # Protect the existing outer budget even against a native/bootstrap hang.
    # All our children have the same finite emergency deadline. No PASS/report
    # can survive this process exit; installer checks require exit code zero.
    watchdog = threading.Timer(_remaining(end), lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    worker = tree = parent = child_pipe = lock = gate = None
    grandchild = None
    kernel = None
    cleanup_ok = True
    try:
        from PySide6.QtCore import QLockFile
        from ctypes import wintypes as w
        from quantlab.analysis_recovery import admission, register_launch, plan_bindings, validate_stop_receipt, inspect_recovery
        from quantlab.core import content_hash
        from quantlab.analysis_recovery_windows import _kernel, SYNCHRONIZE

        plan, request = _prepare_plan(fixture_paths, campaign_state, end - 30)
        proof_root = fixture_paths.root / ('frozen-helper-' + uuid.uuid4().hex)
        paths = AppPaths(proof_root).ensure()
        lock = QLockFile(str(proof_root / 'original-gui.lock'))
        if not lock.tryLock(0):
            raise RuntimeError('Original synthetic GUI lock unavailable')
        job_id, nonce = uuid.uuid4().hex, uuid.uuid4().hex
        anticipated = {'job_id': job_id, 'helper_nonce': nonce, **plan_bindings(plan), 'source_request_hash': content_hash(request)}
        context = mp.get_context('spawn')
        gate = context.Event()
        parent, child_pipe = context.Pipe()
        worker = context.Process(target=_gated_worker, args=(gate, child_pipe, end), name='frozen-recovery-fixture')
        worker.start()
        child_pipe.close()
        child_pipe = None
        # Leave enough shared cap for bounded stop and original-handle cleanup.
        tree = WindowsAnalysisRecoveryTree(worker, gate, paths, max(0.1, _remaining(end) - 12), anticipated=anticipated)
        report['production_helper_ready'] = True
        if gate.is_set():
            raise RuntimeError('Gate opened before original GUI commit')
        with admission(paths) as owner:
            launch = register_launch(paths, job_id=job_id, helper_nonce=nonce, approved_plan=plan, request=request, admission=owner)
        tree.activate(launch)
        report['original_launch_committed_before_gate'] = True
        report['production_helper_activated'] = True
        if not parent.poll(min(3, _remaining(end))):
            raise TimeoutError('Contained grandchild did not start')
        source_handle = int(parent.recv_bytes(32).decode('ascii'))
        kernel = _kernel()
        copied = w.HANDLE()
        if not kernel.DuplicateHandle(int(worker._popen._handle), source_handle, kernel.GetCurrentProcess(), ctypes.byref(copied), SYNCHRONIZE | 1, False, 0):
            raise RuntimeError('Original grandchild handle transfer failed')
        grandchild = copied.value
        parent.send_bytes(b'ACK')
        if kernel.WaitForSingleObject(grandchild, 0) != 258:
            raise RuntimeError('Grandchild exited before containment test')
        tree.stop_and_join()
        worker.join(timeout=min(2, _remaining(end)))
        if worker.is_alive() or kernel.WaitForSingleObject(grandchild, max(0, int(min(2, _remaining(end)) * 1000))) != 0:
            raise RuntimeError('Original descendant handles did not signal')
        if validate_stop_receipt(paths, job_id) != launch or inspect_recovery(paths).status != 'stopped':
            raise RuntimeError('Exact strict stop receipt unavailable')
        report.update(
            status='passed',
            original_worker_joined=True,
            original_grandchild_signalled=True,
            original_helper_joined=True,
            strict_stop_receipt_verified=True,
            original_job_quiescence_verified=True,
            helper_module='quantlab.analysis_recovery_windows',
            cap_seconds=CAP_SECONDS,
        )
    except BaseException as exc:
        tree = getattr(exc, 'recovery_tree', tree)
        report.update(status='failed', error_type=type(exc).__name__)
    finally:
        if tree is not None:
            try:
                tree.close()
            except BaseException:
                cleanup_ok = False
        if worker is not None and worker.pid is not None:
            try:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=min(2, _remaining(end)))
                if worker.is_alive():
                    cleanup_ok = False
                else:
                    worker.close()
            except BaseException:
                cleanup_ok = False
        if grandchild is not None:
            try:
                if kernel.WaitForSingleObject(grandchild, max(0, int(min(2, _remaining(end)) * 1000))) != 0:
                    # Never kill by discovered PID or infer successful cleanup.
                    cleanup_ok = False
                kernel.CloseHandle(grandchild)
            except BaseException:
                cleanup_ok = False
        for connection in (parent, child_pipe):
            if connection is not None:
                try:
                    connection.close()
                except BaseException:
                    cleanup_ok = False
        # If admission opened but original descendant identity was never
        # transferred, retain the fixture rather than infer subtree cleanup.
        if gate is not None and gate.is_set() and grandchild is None:
            cleanup_ok = False
        if lock is not None:
            try:
                lock.unlock()
            except BaseException:
                cleanup_ok = False
        watchdog.cancel()
        report['cleanup_verified'] = cleanup_ok
        report['seconds'] = round(time.monotonic() - started, 3)
        if not cleanup_ok or time.monotonic() >= end:
            report['status'] = 'failed'
    return report
