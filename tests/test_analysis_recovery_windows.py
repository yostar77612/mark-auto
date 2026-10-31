"""Mocked protocol negatives are not native Windows proof.

The native case is bounded, synthetic, contains no provider operation and uses
retained handles. Cloud Windows evidence does not certify a standard-user PC.
"""

import ctypes
import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from quantlab import analysis_recovery_windows as recovery
from quantlab.research_core.adapters.workspace_store import AppPaths
from quantlab.desktop_runtime import RuntimeSafetyError


def _anticipated():
    return {
        'job_id': 'a' * 32,
        'helper_nonce': 'b' * 32,
        'analysis_id': 'c' * 64,
        'registration': 'd' * 32,
        'plan_hash': 'e' * 64,
        'provider_hash': 'f' * 64,
        'request_hash': '1' * 64,
        'source_request_hash': '2' * 64,
        'request_bytes': 100,
        'timeout_seconds': 1,
        'model': 'synthetic',
        'ledger_basename': 'chatgpt-analysis-' + 'c' * 64 + '.sqlite3',
    }


class _Pipe:
    def __init__(self, packets):
        self.packets = list(packets)
        self.sent = []

    def poll(self, timeout):
        return bool(self.packets)

    def recv_bytes(self, limit):
        value = self.packets.pop(0)
        if isinstance(value, Exception):
            raise value
        return json.dumps(value).encode()

    def send_bytes(self, raw):
        self.sent.append(json.loads(raw))


class ProtocolNegativeTests(unittest.TestCase):
    def run_protocol(self, packets, *, alive=True, verify=None, stop_error=None, publish_error=None, deadline=None):
        connection = _Pipe(packets)
        gate, tree = Mock(), Mock()
        tree.stop_and_join.side_effect = stop_error
        launch = dict(_anticipated(), installation='fixture')
        with (
            patch.object(recovery, '_alive', return_value=alive),
            patch.object(recovery, '_verify_launch', side_effect=verify, return_value=launch) as reader,
            patch.object(recovery, '_publish', side_effect=publish_error) as publisher,
        ):
            try:
                recovery._supervise(
                    connection, gate, None, _anticipated(), time.monotonic() + 1 if deadline is None else deadline, time.monotonic() + 1, None, 1, 2, tree
                )
                error = None
            except Exception as exc:
                error = exc
        return connection, gate, tree, reader, publisher, error

    def test_commit_is_verified_before_one_gate_release(self):
        result = self.run_protocol([{'activate': {'immutable': 'row'}}, {'activate': {'again': True}}])
        connection, gate, tree, reader, publisher, error = result
        self.assertIsNone(error)
        gate.set.assert_called_once()
        reader.assert_called_once_with(None, _anticipated(), for_admission=True, expected={'immutable': 'row'})
        tree.stop_and_join.assert_called_once()
        publisher.assert_called_once()
        self.assertEqual([p['state'] for p in connection.sent], ['ready', 'active', 'stopped'])

    def test_missing_commit_never_opens_gate_or_publishes(self):
        connection, gate, tree, reader, publisher, error = self.run_protocol([{'activate': {}}], verify=RuntimeSafetyError('missing'))
        self.assertIsInstance(error, RuntimeSafetyError)
        gate.set.assert_not_called()
        publisher.assert_not_called()
        tree.stop_and_join.assert_called_once()

    def test_original_gui_death_before_activate_reads_existing_only(self):
        connection, gate, tree, reader, publisher, error = self.run_protocol([], alive=False)
        self.assertIsNone(error)
        gate.set.assert_not_called()
        reader.assert_called_once_with(None, _anticipated(), recover_controls=True)
        tree.stop_and_join.assert_called_once()
        publisher.assert_called_once()
        self.assertTrue(connection.sent[-1]['receipt'])

    def test_gui_death_without_committed_row_has_no_receipt(self):
        connection, gate, tree, reader, publisher, error = self.run_protocol([], alive=False, verify=RuntimeSafetyError('missing'))
        self.assertIsNone(error)
        publisher.assert_not_called()
        self.assertFalse(connection.sent[-1]['receipt'])

    def test_termination_or_query_failure_cannot_publish(self):
        for error in ('terminate failed', 'query failed', 'nonzero deadline'):
            with self.subTest(error=error):
                result = self.run_protocol([{'activate': {}}, {'stop': True}], stop_error=RuntimeSafetyError(error))
                result[4].assert_not_called()
                self.assertNotIn('stopped', [p['state'] for p in result[0].sent])

    def test_publication_failure_cannot_acknowledge_receipt(self):
        connection, gate, tree, reader, publisher, error = self.run_protocol([{'activate': {}}, {'stop': True}], publish_error=OSError('disk full'))
        self.assertIsInstance(error, OSError)
        self.assertNotIn('stopped', [p['state'] for p in connection.sent])

    def test_eof_stops_exact_job_and_can_publish_already_committed_row(self):
        result = self.run_protocol([EOFError()])
        result[1].set.assert_not_called()
        result[2].stop_and_join.assert_called_once()
        result[4].assert_called_once()
        self.assertIsInstance(result[5], EOFError)

    def test_execution_deadline_stops_without_heartbeat_extension(self):
        result = self.run_protocol([{'activate': {}}], deadline=0)
        self.assertIsNone(result[5])
        result[2].stop_and_join.assert_called_once()
        result[4].assert_called_once()
        result[1].set.assert_not_called()

    def test_handle_observation_failure_is_not_absence(self):
        k = Mock()
        k.WaitForSingleObject.return_value = 0xFFFFFFFF
        with self.assertRaises(RuntimeSafetyError):
            recovery._alive(k, 123)

    def test_anticipated_identity_is_bounded_and_exact(self):
        recovery._validate_anticipated(_anticipated())
        for changed in ({'extra': True}, {'job_id': 'bad'}, {'request_bytes': True}, {'helper_nonce': 'a' * 32}, {'timeout_seconds': 121}):
            with self.subTest(changed=changed), self.assertRaises(RuntimeSafetyError):
                recovery._validate_anticipated({**_anticipated(), **changed})

    def test_wrong_helper_generation_cannot_adopt_old_row(self):
        with patch('quantlab.analysis_recovery.read_launch', return_value={**_anticipated(), 'helper_nonce': '9' * 32}):
            with self.assertRaises(RuntimeSafetyError):
                recovery._verify_launch(None, _anticipated())

    def test_job_is_unnamed_kill_on_close_and_assigned_by_original_handle(self):
        k = Mock()
        k.CreateJobObjectW.return_value = 777
        k.SetInformationJobObject.return_value = True
        k.AssignProcessToJobObject.return_value = True
        tree = recovery._OriginalJob(k, 456)
        k.CreateJobObjectW.assert_called_once_with(None, None)
        info = k.SetInformationJobObject.call_args.args[2]._obj
        self.assertEqual(info.BasicLimitInformation.LimitFlags, 0x2000)
        k.AssignProcessToJobObject.assert_called_once_with(777, 456)
        k.OpenProcess.assert_not_called()
        tree.close()
        tree.close()
        k.CloseHandle.assert_called_once_with(777)

    def test_failed_assignment_closes_original_job(self):
        k = Mock()
        k.CreateJobObjectW.return_value = 777
        k.SetInformationJobObject.return_value = True
        k.AssignProcessToJobObject.return_value = False
        with self.assertRaises(RuntimeSafetyError):
            recovery._OriginalJob(k, 456)
        k.CloseHandle.assert_called_once_with(777)

    def test_duplicate_transfers_noninheritable_handle_with_explicit_rights(self):
        k = Mock()
        k.GetCurrentProcess.return_value = -1

        def copied(source, handle, target, out, access, inherit, options):
            out._obj.value = 456
            return True

        k.DuplicateHandle.side_effect = copied
        self.assertEqual(recovery._duplicate(k, 123, 789, recovery.SYNCHRONIZE), 456)
        args = k.DuplicateHandle.call_args.args
        self.assertEqual(args[:3], (-1, 123, 789))
        self.assertEqual(args[4:], (recovery.SYNCHRONIZE, False, 0))
        k.OpenProcess.assert_not_called()

    def test_close_preserves_original_helper_when_exit_is_unconfirmed(self):
        tree = recovery.WindowsAnalysisRecoveryTree.__new__(recovery.WindowsAnalysisRecoveryTree)
        tree._connection = Mock()
        helper = tree._helper = Mock()
        helper.pid = 123
        helper.is_alive.return_value = True
        with self.assertRaises(RuntimeSafetyError) as caught:
            tree.close()
        self.assertIs(caught.exception.recovery_tree, tree)
        self.assertIs(tree._helper, helper)
        helper.close.assert_not_called()
        helper.terminate.assert_called_once()

    def test_nonwindows_adapter_rejects_without_spawning(self):
        with patch.object(recovery.sys, 'platform', 'linux'), patch.object(recovery.mp, 'get_context') as spawn:
            with self.assertRaises(RuntimeSafetyError):
                recovery.WindowsAnalysisRecoveryTree(None, None, None, 1, anticipated=_anticipated())
            spawn.assert_not_called()


class AdapterAcknowledgementTests(unittest.TestCase):
    def adapter(self, packets):
        tree = recovery.WindowsAnalysisRecoveryTree.__new__(recovery.WindowsAnalysisRecoveryTree)
        tree._connection = _Pipe(packets)
        tree._helper = Mock()
        tree._helper.is_alive.return_value = False
        tree._activated = tree._stopped = False
        tree._terminal_packet = tree._stop_deadline = None
        tree._admission_deadline = time.monotonic() + 1
        return tree

    def test_late_active_after_activation_timeout_does_not_hide_stop(self):
        tree = self.adapter([])
        with self.assertRaises(RuntimeSafetyError):
            tree.activate({'launch': 'fixture'})
        tree._connection.packets.extend([{'state': 'active'}, {'state': 'stopped', 'receipt': True}])
        tree.stop_and_join()
        self.assertTrue(tree._stopped)
        tree._helper.join.assert_called_once()
        tree._helper.is_alive.assert_called_once()
        tree.stop_and_join()
        tree._helper.join.assert_called_once()

    def test_terminal_before_active_is_cached_for_cleanup(self):
        tree = self.adapter([{'state': 'stopped', 'receipt': True}])
        with self.assertRaises(RuntimeSafetyError):
            tree.activate({'launch': 'fixture'})
        self.assertEqual(tree._connection.packets, [])
        tree.stop_and_join()
        self.assertTrue(tree._stopped)
        tree._helper.is_alive.assert_called_once()

    def test_failed_terminal_cannot_be_overwritten_by_later_success(self):
        tree = self.adapter([{'state': 'failed'}, {'state': 'stopped', 'receipt': True}])
        with self.assertRaises(RuntimeSafetyError):
            tree.activate({})
        with self.assertRaises(RuntimeSafetyError):
            tree.stop_and_join()
        self.assertFalse(tree._stopped)
        tree._helper.join.assert_not_called()

    def test_registered_activation_missing_receipt_rejects_cached_stop(self):
        tree = self.adapter([{'state': 'stopped', 'receipt': False}])
        with self.assertRaises(RuntimeSafetyError):
            tree.activate({})
        with self.assertRaises(RuntimeSafetyError):
            tree.stop_and_join()
        self.assertFalse(tree._stopped)
        tree._helper.join.assert_not_called()

    def test_only_bounded_known_nonterminal_states_can_be_drained(self):
        for packets in (
            [{'state': 'active'}, {'state': 'active'}],
            [{'state': 'unexpected'}],
            [{'state': 'stopped', 'receipt': 1}],
            [{'state': 'active', 'extra': True}],
        ):
            with self.subTest(packets=packets):
                tree = self.adapter(packets)
                with self.assertRaises(RuntimeSafetyError):
                    tree.stop_and_join()
                self.assertFalse(tree._stopped)

    def test_drain_and_retry_share_original_stop_deadline(self):
        tree = self.adapter([{'state': 'ready'}, {'state': 'active'}])
        observed = []
        original_poll = tree._connection.poll
        clock = [100.0]

        def poll(timeout):
            observed.append(timeout)
            clock[0] += 1
            return original_poll(timeout)

        tree._connection.poll = poll
        with patch.object(recovery.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(RuntimeSafetyError):
                tree.stop_and_join()
            deadline = tree._stop_deadline
            with self.assertRaises(RuntimeSafetyError):
                tree.stop_and_join()
        self.assertEqual(deadline, 107)
        self.assertEqual(tree._stop_deadline, deadline)
        self.assertEqual(observed, [7, 6, 5, 4])
        self.assertFalse(tree._stopped)

    def test_valid_receipt_still_requires_original_helper_exit(self):
        tree = self.adapter([{'state': 'stopped', 'receipt': True}])
        helper = tree._helper
        helper.is_alive.return_value = True
        with self.assertRaises(RuntimeSafetyError):
            tree.stop_and_join()
        self.assertIs(tree._helper, helper)
        self.assertFalse(tree._stopped)
        helper.close.assert_not_called()
        # A retry consumes cached original evidence, not a new stop message.
        helper.is_alive.return_value = False
        deadline = tree._stop_deadline
        tree.stop_and_join()
        self.assertTrue(tree._stopped)
        self.assertEqual(tree._stop_deadline, deadline)


def _bounded_gated_worker(gate, executed):
    if gate.wait(15):
        executed.set()
    time.sleep(0.1)


def _synthetic_gui(connection, folder):
    # Pure ledger binding fixture only. No model, transport, token or auth calls.
    from quantlab import analysis_recovery as ledger
    from quantlab.core import content_hash

    paths = AppPaths(Path(folder)).ensure()
    anticipated = _anticipated()
    request = {
        'campaign_reference': '3' * 64,
        'original_dataset': {'kind': 'local_dataset_file', 'path': str(paths.root / 'original.json')},
        'attempt_ids': ['4' * 64],
        'task': 'critique',
        'registration': anticipated['registration'],
        'model': anticipated['model'],
        'timeout_seconds': anticipated['timeout_seconds'],
    }
    anticipated['source_request_hash'] = content_hash(request)
    context = mp.get_context('spawn')
    gate, executed = context.Event(), context.Event()
    grandchild_receiver, grandchild_sender = context.Pipe(duplex=False)
    worker = context.Process(target=_bounded_gated_worker_long, args=(gate, executed, grandchild_sender))
    tree = None
    grandchild_handle = None
    try:
        worker.start()
        grandchild_sender.close()
        tree = recovery.WindowsAnalysisRecoveryTree(worker, gate, paths, 12, anticipated=anticipated)
        plan_binding = {k: v for k, v in anticipated.items() if k not in ('job_id', 'helper_nonce', 'source_request_hash')}
        with patch.object(ledger, 'plan_bindings', return_value=plan_binding), ledger.admission(paths) as token:
            launch = ledger.register_launch(
                paths,
                job_id=anticipated['job_id'],
                helper_nonce=anticipated['helper_nonce'],
                approved_plan={
                    'binding': {
                        'packet': {
                            'provenance': {'campaign_ref': request['campaign_reference'], 'result_links': [{'attempt_id': request['attempt_ids'][0]}]},
                            'context': {'task': request['task']},
                        }
                    }
                },
                request=request,
                admission=token,
            )
        tree.activate(launch)
        if not executed.wait(3):
            raise AssertionError('contained synthetic worker did not start')
        from ctypes import wintypes as w

        k = recovery._kernel()
        if not grandchild_receiver.poll(1):
            raise AssertionError('grandchild original handle was not retained')
        copied = w.HANDLE()
        if not k.DuplicateHandle(
            int(worker._popen._handle), grandchild_receiver.recv(), k.GetCurrentProcess(), ctypes.byref(copied), recovery.SYNCHRONIZE | 0x0001, False, 0
        ):
            raise AssertionError('cannot retain original grandchild handle')
        grandchild_handle = copied.value
        connection.send({'worker': int(worker._popen._handle), 'helper': int(tree._helper._popen._handle), 'grandchild': grandchild_handle})
        # Original process handles stay retained until observer duplicates them.
        if not connection.poll(15):
            raise AssertionError('observer did not stop synthetic GUI')
        connection.recv()
    except BaseException as exc:
        tree = getattr(exc, 'recovery_tree', tree)
        raise
    finally:
        try:
            if tree is not None:
                tree.close()
        finally:
            try:
                if worker.pid is not None:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join(timeout=2)
            finally:
                if grandchild_handle is not None:
                    recovery._kernel().CloseHandle(grandchild_handle)
                grandchild_receiver.close()
                connection.close()


def _bounded_grandchild():
    time.sleep(15)


def _bounded_gated_worker_long(gate, executed, grandchild_sender):
    grandchild = None
    try:
        if gate.wait(15):
            grandchild = mp.get_context('spawn').Process(target=_bounded_grandchild)
            grandchild.start()
            grandchild_sender.send(int(grandchild._popen._handle))
            executed.set()
            time.sleep(15)
    finally:
        if grandchild is not None:
            if grandchild.is_alive():
                grandchild.terminate()
            grandchild.join(timeout=2)
        grandchild_sender.close()


@unittest.skipUnless(sys.platform == 'win32', 'actual Win32 handles/job semantics required')
class NativeHelperTests(unittest.TestCase):
    def test_original_gui_death_publishes_durable_receipt_for_exact_job(self):
        self._native_crash_case(helper_death=False)

    def test_helper_death_kills_original_job_without_manufacturing_receipt(self):
        self._native_crash_case(helper_death=True)

    def _native_crash_case(self, *, helper_death):
        from ctypes import wintypes as w
        from quantlab.analysis_recovery import validate_stop_receipt

        context = mp.get_context('spawn')
        parent, child = context.Pipe()
        retained = []
        k = recovery._kernel()
        k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        k.TerminateProcess.restype = w.BOOL
        with tempfile.TemporaryDirectory() as folder:
            gui = context.Process(target=_synthetic_gui, args=(child, folder))
            try:
                gui.start()
                child.close()
                self.assertTrue(parent.poll(15), 'synthetic GUI setup deadline')
                source = parent.recv()
                for name in ('worker', 'helper', 'grandchild'):
                    handle = w.HANDLE()
                    self.assertTrue(
                        k.DuplicateHandle(
                            int(gui._popen._handle), source[name], k.GetCurrentProcess(), ctypes.byref(handle), recovery.SYNCHRONIZE | 0x0001, False, 0
                        )
                    )
                    retained.append(handle.value)
                if helper_death:
                    self.assertTrue(k.TerminateProcess(retained[1], 94))
                    self.assertTrue(gui.is_alive(), 'helper-only crash must leave GUI alive')
                    with self.assertRaises(ValueError):
                        validate_stop_receipt(AppPaths(Path(folder)), _anticipated()['job_id'])
                else:
                    gui.terminate()  # multiprocessing retains this exact GUI handle.
                    gui.join(timeout=2)
                    self.assertFalse(gui.is_alive())
                    deadline = time.monotonic() + 8
                    paths = AppPaths(Path(folder))
                    while True:
                        try:
                            launch = validate_stop_receipt(paths, _anticipated()['job_id'])
                            break
                        except ValueError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(0.02)
                    self.assertEqual(launch['helper_nonce'], _anticipated()['helper_nonce'])
                exit_deadline = time.monotonic() + 2
                for handle in retained:
                    self.assertEqual(
                        k.WaitForSingleObject(handle, max(0, int((exit_deadline - time.monotonic()) * 1000))),
                        0,
                        'original helper/worker/grandchild handle did not signal',
                    )
                if helper_death:
                    with self.assertRaises(ValueError):
                        validate_stop_receipt(AppPaths(Path(folder)), _anticipated()['job_id'])
            finally:
                # Native failure cleanup uses only retained handles, never PID lookup.
                for handle in retained:
                    if recovery._alive(k, handle):
                        k.TerminateProcess(handle, 93)
                        k.WaitForSingleObject(handle, 2000)
                    k.CloseHandle(handle)
                if gui.pid is not None:
                    if gui.is_alive():
                        gui.terminate()
                    gui.join(timeout=2)
                    gui.close()
                parent.close()

    def test_uncommitted_worker_is_contained_and_stopped_without_gate(self):
        context = mp.get_context('spawn')
        gate, executed = context.Event(), context.Event()
        worker = context.Process(target=_bounded_gated_worker, args=(gate, executed))
        tree = None
        with tempfile.TemporaryDirectory() as folder:
            paths = AppPaths(Path(folder)).ensure()
            try:
                worker.start()
                tree = recovery.WindowsAnalysisRecoveryTree(worker, gate, paths, 3, anticipated=_anticipated())
                self.assertTrue(worker.is_alive())
                tree.stop_and_join()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertFalse(executed.is_set())
                self.assertFalse(gate.is_set())
            except BaseException as exc:
                tree = getattr(exc, 'recovery_tree', tree)
                raise
            finally:
                if tree is not None:
                    tree.close()
                if worker.pid is not None:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join(timeout=2)
                    self.assertFalse(worker.is_alive(), 'bounded original worker cleanup failed')
                    worker.close()


if __name__ == '__main__':
    mp.freeze_support()
    unittest.main()
