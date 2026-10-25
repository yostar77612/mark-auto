"""Real spawned training worker identity, faults, deadlines and handle cleanup."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import multiprocessing
import json
import os
from time import monotonic
from threading import Thread
from time import sleep
import unittest

from quantlab.trading.application.codec import dumps
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.research import research
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_catalog, synthetic_history
from quantlab.trading.runtime.provenance import compute_profile
from quantlab.trading.runtime.research_worker import MAX_SECONDS, SpawnResearchRunner, WorkerFault


def _orphan_probe_owner(channel) -> None:
    """Fixed test-only owner. Its actual training child must self-exit if it dies."""
    fixture = IsolatedResearchTests()
    fixture.setUp()
    runner = SpawnResearchRunner(diagnostic_fault=WorkerFault.STALL_AFTER_DECODE)

    def run() -> None:
        try:
            fixture.run_worker(runner)
        except DomainError:
            pass

    thread = Thread(target=run)
    thread.start()
    until = monotonic() + 10
    while not runner.last_child_ready and thread.is_alive() and monotonic() < until:
        sleep(0.01)
    channel.send_bytes(json.dumps({'owner_pid': os.getpid(), 'worker_pid': runner.last_child_pid, 'ready': runner.last_child_ready}).encode())
    channel.close()
    thread.join()


class IsolatedResearchTests(unittest.TestCase):
    def test_result_waits_for_clean_exit_inside_original_deadline(self):
        runner = SpawnResearchRunner(max_seconds=10, diagnostic_fault=WorkerFault.SLOW_COMPLETION)
        result = self.run_worker(runner)
        self.assertEqual(result.observations, len(self.bars))
        self.assertTrue(runner.last_cleanup_verified)

    def setUp(self) -> None:
        self.calendar = synthetic_calendar()
        catalog = synthetic_catalog()
        self.spec = catalog.instruments[0]
        self.bars = synthetic_history(catalog, self.calendar)[self.spec.instrument_id][:30]
        self.fees = FeeSchedule()
        form = StrategyForm(
            'worker-training',
            self.spec.market,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            self.spec.instrument_id,
            'local-stock',
            Environment.LOCAL,
            Decimal('30000'),
            Decimal('0.02'),
            'BUY_AND_HOLD',
        )
        self.strategy = StrategyRecord('isolated-training', 1, form, HoldingPolicy(HoldingKind.SWING, 3, 5), 'RULE_VALID')

    def run_worker(self, runner: SpawnResearchRunner, *, bars=None, profile=None):
        return runner.run(
            self.strategy,
            self.spec,
            self.calendar,
            self.bars if bars is None else bars,
            self.fees,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
            source_profile=profile,
        )

    def assert_clean(self, runner: SpawnResearchRunner) -> None:
        self.assertTrue(runner.last_cleanup_verified)
        self.assertIsNotNone(runner.last_child_pid)
        self.assertNotEqual(runner.last_child_pid, os.getpid())
        self.assertNotIn(runner.last_child_pid, {child.pid for child in multiprocessing.active_children()})

    def test_real_child_matches_authoritative_result_and_full_producer_profile(self) -> None:
        runner, profile = SpawnResearchRunner(), compute_profile()
        expected = research(self.strategy, self.spec, self.calendar, self.bars, self.fees, source_profile=profile)
        actual = self.run_worker(runner, profile=profile)
        self.assertEqual(actual, expected)
        self.assertEqual(actual.producer_profile, profile.profile_id)
        self.assertEqual(actual.source_digest, profile.source_digest)
        self.assertEqual(actual.partition, 'TRAINING')
        self.assert_clean(runner)

    def test_direct_lookahead_is_rejected_by_the_actual_child(self) -> None:
        first = replace(self.bars[0], available_at=self.bars[1].ended_at + timedelta(seconds=1))
        runner = SpawnResearchRunner()
        with self.assertRaises(DomainError) as caught:
            self.run_worker(runner, bars=(first, *self.bars[1:]))
        self.assertEqual(caught.exception.code, 'validation_failed')
        self.assert_clean(runner)

    def test_child_crash_is_a_failure_and_never_leaves_a_process(self) -> None:
        runner = SpawnResearchRunner(diagnostic_fault=WorkerFault.EXIT_AFTER_DECODE)
        with self.assertRaises(DomainError) as caught:
            self.run_worker(runner)
        self.assertEqual(caught.exception.code, 'research_worker_failed')
        self.assert_clean(runner)

    def test_deadline_terminates_only_the_owned_stalled_child(self) -> None:
        before = {child.pid for child in multiprocessing.active_children()}
        runner = SpawnResearchRunner(max_seconds=0.3, diagnostic_fault=WorkerFault.STALL_AFTER_DECODE)
        started = monotonic()
        with self.assertRaises(DomainError) as caught:
            self.run_worker(runner)
        self.assertEqual(caught.exception.code, 'research_timeout')
        self.assertLess(monotonic() - started, 10)
        self.assert_clean(runner)
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

    def test_expired_deadline_and_untyped_payload_never_start_a_child(self) -> None:
        runner = SpawnResearchRunner()
        with self.assertRaises(DomainError) as caught:
            runner.run(self.strategy, self.spec, self.calendar, self.bars, self.fees, deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        self.assertEqual(caught.exception.code, 'research_timeout')
        self.assertIsNone(runner.last_child_pid)
        with self.assertRaises(DomainError):
            self.run_worker(runner, bars=list(self.bars))
        self.assertIsNone(runner.last_child_pid)
        self.assertTrue(runner.last_cleanup_verified)

    def test_policy_mismatch_and_resource_expansion_cannot_enter_worker(self) -> None:
        runner = SpawnResearchRunner()
        changed = replace(self.strategy, policy=HoldingPolicy(HoldingKind.POSITION, 30, 60))
        with self.assertRaises(DomainError):
            runner.run(changed, self.spec, self.calendar, self.bars, self.fees, deadline=datetime.now(timezone.utc) + timedelta(seconds=30))
        self.assertIsNone(runner.last_child_pid)
        for limit in (MAX_SECONDS + 1, float('nan'), float('inf'), True, 0):
            with self.subTest(limit=limit), self.assertRaises(DomainError):
                SpawnResearchRunner(max_seconds=limit)

    def test_close_cancels_a_real_ready_stalled_child_without_waiting_for_job_deadline(self) -> None:
        runner = SpawnResearchRunner(diagnostic_fault=WorkerFault.STALL_AFTER_DECODE)
        outcomes: list[str] = []

        def run() -> None:
            try:
                self.run_worker(runner)
            except DomainError as exc:
                outcomes.append(exc.code)

        thread = Thread(target=run, name='training-cancel-test')
        thread.start()
        waiting_until = monotonic() + 10
        while not runner.last_child_ready and thread.is_alive() and monotonic() < waiting_until:
            sleep(0.01)
        try:
            self.assertTrue(runner.last_child_ready, 'actual child never acknowledged its decoded training job')
            started = monotonic()
            runner.close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertLess(monotonic() - started, 3)
            self.assertEqual(outcomes, ['research_worker_failed'])
            self.assert_clean(runner)
            with self.assertRaises(DomainError):
                self.run_worker(runner)
        finally:
            runner.close()
            thread.join(timeout=3)

    def test_repeated_owned_jobs_use_new_children_and_keep_no_handles(self) -> None:
        def handles() -> int | None:
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes

                library = ctypes.WinDLL('kernel32.dll', use_last_error=True)
                library.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
                library.GetProcessHandleCount.restype = wintypes.BOOL
                count = wintypes.DWORD()
                if not library.GetProcessHandleCount(wintypes.HANDLE(-1), ctypes.byref(count)):
                    self.fail('Unable to inspect own process handle count')
                return count.value
            if os.path.isdir('/proc/self/fd'):
                return len(os.listdir('/proc/self/fd'))
            return None

        runner = SpawnResearchRunner()
        first = self.run_worker(runner)
        first_pid = runner.last_child_pid
        self.assert_clean(runner)
        before = handles()
        second = self.run_worker(runner)
        self.assert_clean(runner)
        self.assertNotEqual(first_pid, runner.last_child_pid)
        self.assertEqual(dumps(first), dumps(second))
        after = handles()
        if before is not None:
            self.assertLessEqual(after, before)

    def test_forced_owner_process_death_cannot_leave_a_training_orphan(self) -> None:
        context = multiprocessing.get_context('spawn')
        receiver, writer = context.Pipe(duplex=False)
        owner = context.Process(target=_orphan_probe_owner, args=(writer,), name='OwnedTrainingCrashProbe')
        handle = None
        pidfd = None
        owner.start()
        writer.close()
        try:
            self.assertTrue(receiver.poll(15), 'training probe did not report its actual child')
            info = json.loads(receiver.recv_bytes(4096))
            self.assertTrue(info['ready'])
            self.assertEqual(info['owner_pid'], owner.pid)
            self.assertNotIn(info['worker_pid'], (os.getpid(), owner.pid, None))
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes

                library = ctypes.WinDLL('kernel32.dll', use_last_error=True)
                library.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                library.OpenProcess.restype = wintypes.HANDLE
                library.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                library.WaitForSingleObject.restype = wintypes.DWORD
                library.CloseHandle.argtypes = (wintypes.HANDLE,)
                library.CloseHandle.restype = wintypes.BOOL
                # Synchronization-only handle to this probe's reported child.
                handle = library.OpenProcess(0x00100000, False, info['worker_pid'])
                self.assertTrue(handle)
            elif hasattr(os, 'pidfd_open'):
                pidfd = os.pidfd_open(info['worker_pid'])
            owner.terminate()  # only the exact owned probe Process handle
            owner.join(timeout=3)
            self.assertFalse(owner.is_alive())
            if handle is not None:
                self.assertEqual(library.WaitForSingleObject(handle, 3000), 0, 'orphaned training child did not self-exit')
            elif pidfd is not None:
                from select import select

                self.assertTrue(select([pidfd], [], [], 3)[0], 'orphaned training child did not self-exit')
            else:
                # Platforms without a process wait handle still observe only this
                # owned PID; no process listing, group signal or foreign kill.
                until = monotonic() + 3
                alive = True
                while alive and monotonic() < until:
                    try:
                        os.kill(info['worker_pid'], 0)
                    except ProcessLookupError:
                        alive = False
                    sleep(0.01)
                self.assertFalse(alive)
        finally:
            receiver.close()
            if owner.is_alive():
                owner.terminate()
                owner.join(timeout=3)
            owner.close()
            if handle is not None:
                library.CloseHandle(handle)
            if pidfd is not None:
                os.close(pidfd)


if __name__ == '__main__':
    unittest.main()
