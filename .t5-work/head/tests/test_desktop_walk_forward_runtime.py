"""Offline walk-forward worker admission and exact subtree-proof boundaries.

Mock process/Job Object checks are protocol tests, not native Windows evidence.
"""
import copy
from contextlib import closing
from functools import partial
import multiprocessing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.core import to_dict
from quantlab.desktop_runtime import (AppPaths, JobManager, RuntimeSafetyError,
    UI_OPERATIONS, WALK_FORWARD_OPERATIONS, _job_worker)
from quantlab.reporting import demo_config
from quantlab.walk_forward import build_walk_forward_plan


REFERENCE = 'a' * 64
OTHER_REFERENCE = 'b' * 64


def plan_payload():
    return to_dict(build_walk_forward_plan(backtest_config=demo_config(),
        train_bars=60, validation_bars=40, oos_bars=40, fold_count=3,
        final_holdout=(220, 240), process_start_method='spawn'))


def _held_walk_forward_evaluation(dataset, spec, config, started, release):
    """Keep a genuine nested evaluator alive while its durable reservation is read."""
    from quantlab.walk_forward import _evaluate_split
    started.set()
    release.wait(30)
    return _evaluate_split(dataset, spec, config)


def _cancellable_walk_forward_worker(*args, evaluation_started, evaluation_release):
    from quantlab.walk_forward import _run_bounded

    def held_evaluation(function, arguments, **kwargs):
        return _run_bounded(_held_walk_forward_evaluation,
            (*arguments, evaluation_started, evaluation_release), **kwargs)

    with patch('quantlab.walk_forward._run_bounded', side_effect=held_evaluation):
        _job_worker(*args)


class WalkForwardRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'app').ensure()
        self.manager = JobManager(self.paths)
        self.plan = plan_payload()
        self.trace = []

    def start_fake(self, operation='ui_walk_forward_run', payload=None):
        if payload is None:
            payload = {'plan': self.plan, 'preview_identity': REFERENCE}
        self.frames = []
        self.alive = True
        self.process = Mock(pid=424242)
        self.process.is_alive.side_effect = lambda: self.alive
        self.process.join.side_effect = lambda *args: self.trace.append('joined')
        self.process.close.side_effect = lambda: self.trace.append('released')
        self.receiver = Mock()
        self.receiver.poll.side_effect = lambda: bool(self.frames)
        self.receiver.recv_bytes.side_effect = lambda limit: self.frames.pop(0)
        self.tree = Mock()
        def stopped():
            self.alive = False
            self.trace.append('subtree_stopped')
        self.tree.stop_and_join.side_effect = stopped
        context = Mock()
        context.Pipe.return_value = self.receiver, Mock()
        context.Process.return_value = self.process
        with patch('quantlab.desktop_runtime.mp.get_context', return_value=context), \
                patch('quantlab.desktop_runtime._WindowsProcessTree', return_value=self.tree):
            job_id = self.manager.start(operation, payload)
        # Use the same isolated-tree protocol on all test host platforms.
        self.manager.tree = self.tree
        self.worker_args = context.Process.call_args.kwargs['args']
        return job_id

    def frame(self, kind='result', **values):
        self.frames.append(json.dumps({'job_id': self.manager.job_id,
            'type': kind, **values}).encode())

    def stop(self):
        self.manager.cancel()
        return self.manager.poll()

    def test_exact_allowlist_and_no_implicit_worker_on_construction(self):
        self.assertEqual(WALK_FORWARD_OPERATIONS, {
            'ui_walk_forward_preview', 'ui_walk_forward_run',
            'ui_walk_forward_read', 'ui_walk_forward_reconcile'})
        self.assertTrue(WALK_FORWARD_OPERATIONS <= UI_OPERATIONS)
        self.assertFalse(self.manager.active)
        self.assertIsNone(self.manager._quiesced_walk_forward)
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            for operation in ('ui_walk_forward_retry', 'ui_walk_forward_resume', 'exec'):
                with self.subTest(operation=operation), self.assertRaises(RuntimeSafetyError):
                    self.manager.start(operation, {})
        spawn.assert_not_called()

    def test_strict_payloads_rejected_before_spawn(self):
        good = {'plan': self.plan, 'preview_identity': REFERENCE}
        invalid = [
            ('ui_walk_forward_run', {'plan': self.plan}),
            ('ui_walk_forward_run', {**good, 'descendants_stopped': True}),
            ('ui_walk_forward_run', {**good, 'preview_identity': '../outside'}),
            ('ui_walk_forward_run', {**good, 'preview_identity': 'A' * 64}),
            ('ui_walk_forward_preview', {'plan': None}),
            ('ui_walk_forward_preview', {'plan': self.plan, 'reference': REFERENCE}),
            ('ui_walk_forward_read', {'reference': REFERENCE, 'plan': self.plan}),
            ('ui_walk_forward_read', {'reference': OTHER_REFERENCE[:-1]}),
            ('ui_walk_forward_reconcile', {'reference': REFERENCE}),
        ]
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            for operation, payload in invalid:
                with self.subTest(operation=operation, keys=set(payload)), self.assertRaises(RuntimeSafetyError):
                    self.manager.start(operation, payload)
        spawn.assert_not_called()

    def test_run_requires_typed_bounded_plan(self):
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            for value in (True, None, 0, -1, 7201, '300'):
                plan = {**self.plan, 'max_runtime_seconds': value}
                with self.subTest(seconds=value), self.assertRaises(RuntimeSafetyError):
                    self.manager.start('ui_walk_forward_run', {'plan': plan, 'preview_identity': REFERENCE})
            plan = {**self.plan, 'injected_callable': 'unsafe'}
            with self.assertRaises(RuntimeSafetyError):
                self.manager.start('ui_walk_forward_preview', {'plan': plan})
        spawn.assert_not_called()

    def test_run_deadline_honors_plan_and_typed_default(self):
        for explicit in (True, False):
            plan = copy.deepcopy(self.plan)
            if explicit:
                plan['max_runtime_seconds'] = 17
            else:
                plan.pop('max_runtime_seconds')
            with patch('quantlab.desktop_runtime.time.monotonic', return_value=100):
                self.start_fake(payload={'plan': plan, 'preview_identity': REFERENCE if explicit else OTHER_REFERENCE})
            self.assertEqual(self.manager._deadline, 100 + (17 if explicit else 300) + 10)
            self.assertTrue(self.manager._requires_tree_quiescence)
            self.assertIs(self.worker_args[-1], False)
            self.stop()

    def test_reconcile_rejects_missing_forged_and_restarted_proof(self):
        payload = {'reference': REFERENCE, 'stopped_job_id': 'guessed'}
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'stop proof'):
                self.manager.start('ui_walk_forward_reconcile', payload)
        spawn.assert_not_called()
        job_id = self.start_fake()
        self.stop()
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            for value in ({'reference': OTHER_REFERENCE, 'stopped_job_id': job_id},
                          {'reference': REFERENCE, 'stopped_job_id': 'forged'}):
                with self.subTest(value=value), self.assertRaises(RuntimeSafetyError):
                    self.manager.start('ui_walk_forward_reconcile', value)
            restarted = JobManager(self.paths)
            with self.assertRaises(RuntimeSafetyError):
                restarted.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})
        spawn.assert_not_called()

    def test_same_manager_exact_run_proof_admits_reconciliation(self):
        job_id = self.start_fake()
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.stop()
        self.assertEqual(self.manager._quiesced_walk_forward, (job_id, REFERENCE))
        self.start_fake('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})
        self.assertIs(self.worker_args[-1], True)
        self.stop()
        self.assertEqual(self.manager._quiesced_walk_forward, (job_id, REFERENCE))

    def test_read_is_safe_without_stop_proof_and_never_creates_proof(self):
        self.start_fake('ui_walk_forward_read', {'reference': REFERENCE})
        self.assertIs(self.worker_args[-1], False)
        self.frame(result={'reference': REFERENCE, 'status': 'running'})
        self.alive = False
        events = self.manager.poll()
        self.assertEqual(events[0]['result']['status'], 'running')
        self.assertIsNone(self.manager._quiesced_walk_forward)

    def test_new_run_invalidates_previous_stop_proof(self):
        old_id = self.start_fake()
        self.stop()
        self.start_fake(payload={'plan': self.plan, 'preview_identity': OTHER_REFERENCE})
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.stop()
        with self.assertRaises(RuntimeSafetyError):
            self.manager.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': old_id})

    def test_existing_journal_cannot_mint_a_new_writer_stop_proof(self):
        journal = self.paths.state / 'walk_forward' / REFERENCE / 'walk_forward.sqlite3'
        journal.parent.mkdir(parents=True)
        journal.write_bytes(b'existing journal must remain untouched')
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'read-only'):
                self.manager.start('ui_walk_forward_run', {'plan': self.plan, 'preview_identity': REFERENCE})
        spawn.assert_not_called()
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.assertEqual(journal.read_bytes(), b'existing journal must remain untouched')

    def test_exclusive_owner_blocks_concurrent_manager_and_restart_before_journal(self):
        job_id = self.start_fake()
        owner = self.paths.state / 'walk_forward' / REFERENCE / '.desktop-run-owner.json'
        self.assertEqual(json.loads(owner.read_text(encoding='utf-8'))['job_id'], job_id)
        self.assertFalse(owner.with_name('walk_forward.sqlite3').exists())
        other = JobManager(self.paths)
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'already claimed'):
                other.start('ui_walk_forward_run', {'plan': self.plan, 'preview_identity': REFERENCE})
        spawn.assert_not_called()
        self.stop()
        with self.assertRaisesRegex(RuntimeSafetyError, 'already claimed'):
            self.manager.start('ui_walk_forward_run', {'plan': self.plan, 'preview_identity': REFERENCE})
        with self.assertRaisesRegex(RuntimeSafetyError, 'stop proof'):
            other.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})

    def test_reconciliation_rejects_replaced_owner_marker(self):
        job_id = self.start_fake()
        self.stop()
        owner = self.paths.state / 'walk_forward' / REFERENCE / '.desktop-run-owner.json'
        value = json.loads(owner.read_text(encoding='utf-8'))
        owner.write_text(json.dumps({**value, 'job_id': 'forged'}), encoding='utf-8')
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'ownership mismatch'):
                self.manager.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': job_id})
        spawn.assert_not_called()

    def test_failed_spawn_setup_keeps_owner_and_cannot_be_retried(self):
        payload = {'plan': self.plan, 'preview_identity': REFERENCE}
        with patch('quantlab.desktop_runtime.mp.get_context', side_effect=OSError('Spawn unavailable')):
            with self.assertRaises(OSError):
                self.manager.start('ui_walk_forward_run', payload)
        owner = self.paths.state / 'walk_forward' / REFERENCE / '.desktop-run-owner.json'
        self.assertTrue(owner.is_file())
        self.assertFalse(self.manager.active)
        self.assertIsNone(self.manager._quiesced_walk_forward)
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'already claimed'):
                self.manager.start('ui_walk_forward_run', payload)
        spawn.assert_not_called()

    def test_claim_does_not_follow_a_symlinked_reference_directory(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        folder = self.paths.state / 'walk_forward' / REFERENCE
        folder.parent.mkdir()
        try:
            folder.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Host cannot create a test symlink')
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaises(RuntimeSafetyError):
                self.manager.start('ui_walk_forward_run', {'plan': self.plan, 'preview_identity': REFERENCE})
        spawn.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_cancel_retains_slot_and_never_grants_proof(self):
        self.start_fake()
        stopped = self.tree.stop_and_join.side_effect
        self.tree.stop_and_join.side_effect = RuntimeSafetyError('Unknown descendants')
        with self.assertRaises(RuntimeSafetyError):
            self.manager.cancel()
        self.assertTrue(self.manager.active)
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.process.close.assert_not_called()
        self.assertEqual(self.manager._pending, [])
        with self.assertRaises(RuntimeSafetyError):
            self.manager.start('ui_walk_forward_reconcile', {'reference': REFERENCE, 'stopped_job_id': self.manager.job_id})
        self.tree.stop_and_join.side_effect = stopped
        self.stop()

    def test_terminal_result_waits_for_process_and_descendant_join(self):
        job_id = self.start_fake()
        self.frame(result={'reference': REFERENCE, 'status': 'completed'})
        self.assertEqual(self.manager.poll(), [])
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.alive = False
        self.tree.stop_and_join.side_effect = RuntimeSafetyError('Still alive')
        with self.assertRaises(RuntimeSafetyError):
            self.manager.poll()
        self.assertTrue(self.manager.active)
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.process.close.assert_not_called()
        self.tree.stop_and_join.side_effect = lambda: self.trace.append('subtree_stopped')
        events = self.manager.poll()
        self.assertEqual([event['type'] for event in events], ['result'])
        self.assertLess(self.trace.index('joined'), self.trace.index('subtree_stopped'))
        self.assertLess(self.trace.index('subtree_stopped'), self.trace.index('released'))
        self.assertEqual(self.manager._quiesced_walk_forward, (job_id, REFERENCE))

    def test_terminal_failure_is_preserved_after_successful_cancel_cleanup(self):
        self.start_fake()
        self.frame('error', message='Recorded failure')
        self.assertEqual(self.manager.poll(), [])
        events = self.stop()
        self.assertEqual([event['type'] for event in events], ['error'])
        self.assertEqual(events[0]['message'], 'Recorded failure')

    def test_stale_job_and_mismatched_reference_never_deliver_result(self):
        for index, frame in enumerate(({'job_id': 'old-job', 'type': 'result', 'result': {'reference': REFERENCE}},
                      {'type': 'result', 'result': {'reference': OTHER_REFERENCE}},
                      {'type': 'result', 'result': {'status': 'completed'}})):
            with self.subTest(frame=frame):
                self.start_fake(payload={'plan': self.plan, 'preview_identity': f'{index:064x}'})
                self.frames.append(json.dumps({'job_id': self.manager.job_id, **frame}).encode())
                events = self.manager.poll() + self.manager.poll()
                self.assertFalse(any(event['type'] == 'result' for event in events))
                self.assertTrue(any(event['type'] == 'error' for event in events))
                self.assertFalse(self.manager.active)
                self.tree.stop_and_join.assert_called()

    def test_parent_deadline_stops_whole_tree_without_retry(self):
        job_id = self.start_fake()
        self.manager._deadline = 0
        events = self.manager.poll()
        self.assertEqual([event['type'] for event in events], ['error'])
        self.assertEqual(events[0]['error_type'], 'DeadlineExceeded')
        self.assertFalse(self.manager.active)
        self.tree.stop_and_join.assert_called()
        self.process.start.assert_called_once()
        self.assertEqual(self.manager._quiesced_walk_forward, (job_id, REFERENCE))

    def test_deadline_does_not_relabel_received_terminal_packet(self):
        self.start_fake()
        self.frame(result={'reference': REFERENCE, 'status': 'blocked_interrupted'})
        self.manager._deadline = 0
        events = self.manager.poll()
        self.assertEqual([event['type'] for event in events], ['result'])
        self.assertFalse(self.manager.active)

    def test_windows_missing_tree_proof_is_rejected(self):
        self.start_fake()
        self.manager.tree = None
        self.alive = False
        with patch('quantlab.desktop_runtime.sys.platform', 'win32'):
            with self.assertRaisesRegex(RuntimeSafetyError, 'Cannot prove'):
                self.manager.poll()
        self.assertTrue(self.manager.active)
        self.assertIsNone(self.manager._quiesced_walk_forward)
        self.manager.tree = self.tree
        self.stop()

    def test_subscription_reconcile_still_requires_original_proof(self):
        with self.assertRaises(RuntimeSafetyError):
            self.manager.start('ui_chatgpt_reconcile', {'stopped_job_id': 'guessed'})
        self.manager._quiesced_subscription_id = 'subscription-job'
        self.start_fake('ui_chatgpt_reconcile', {'stopped_job_id': 'subscription-job'})
        self.assertIs(self.worker_args[-1], True)
        self.stop()
        self.assertIsNone(self.manager._quiesced_walk_forward)

    def test_worker_passes_proof_only_from_private_admission_argument(self):
        for admitted in (False, True):
            sender, gate = Mock(), Mock()
            gate.wait.return_value = True
            execute = Mock(return_value={'reference': REFERENCE})
            with patch('quantlab.desktop_runtime.os.setsid', create=True), \
                    patch.dict('sys.modules', {'desktop_ui': SimpleNamespace(execute_ui_operation=execute)}):
                _job_worker(sender, gate, 'ui_walk_forward_reconcile',
                    {'reference': REFERENCE, 'descendants_stopped': True},
                    str(self.paths.root), None, 'worker-fixture', admitted)
            self.assertIs(execute.call_args.kwargs['descendants_stopped'], admitted)
            sender.close.assert_called_once()


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Pinned Qt required by desktop worker adapter')
class WalkForwardSpawnSmokeTests(unittest.TestCase):
    """Actual offline spawned workers and generated bars; no provider or broker."""
    def setUp(self):
        from quantlab.reporting import save_dataset
        from tests.test_walk_forward import inputs
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'app').ensure()
        data, plan = inputs(process_start_method='spawn', max_runtime_seconds=60)
        self.plan = to_dict(plan)
        save_dataset(data, self.paths.state / 'dataset.json')
        self.manager = JobManager(self.paths)
        self.addCleanup(self.manager.close)

    def finish(self):
        events = []
        deadline = time.monotonic() + 80
        while self.manager.active and time.monotonic() < deadline:
            events.extend(self.manager.poll())
            time.sleep(.01)
        self.assertFalse(self.manager.active, 'Bounded spawned task did not finish')
        failures = [event for event in events if event['type'] == 'error']
        self.assertEqual(failures, [], events)
        results = [event['result'] for event in events if event['type'] == 'result']
        self.assertEqual(len(results), 1, events)
        return results[0]

    def preview(self):
        self.manager.start('ui_walk_forward_preview', {'plan': self.plan})
        result = self.finish()
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse((self.paths.state / 'walk_forward').exists())
        return result['preview_identity']

    def test_generated_run_completes_and_reloads_without_replay(self):
        reference = self.preview()
        job_id = self.manager.start('ui_walk_forward_run', {
            'plan': self.plan, 'preview_identity': reference})
        result = self.finish()
        self.assertEqual(result['reference'], reference)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.manager._quiesced_walk_forward, (job_id, reference))
        self.assertEqual(len(result['folds']), 3)
        journal = self.paths.state / 'walk_forward' / reference / 'walk_forward.sqlite3'
        original = journal.read_bytes()
        with self.assertRaises(RuntimeSafetyError):
            self.manager.start('ui_walk_forward_run', {'plan': self.plan, 'preview_identity': reference})
        self.manager.start('ui_walk_forward_read', {'reference': reference})
        self.assertEqual(self.finish(), result)
        self.assertEqual(journal.read_bytes(), original)

    def test_generated_cancel_requires_original_job_then_reconciles_without_evaluation(self):
        reference = self.preview()
        context = multiprocessing.get_context('spawn')
        evaluation_started, evaluation_release = context.Event(), context.Event()
        worker = partial(_cancellable_walk_forward_worker,
            evaluation_started=evaluation_started, evaluation_release=evaluation_release)
        with patch('quantlab.desktop_runtime._job_worker', worker):
            job_id = self.manager.start('ui_walk_forward_run', {
                'plan': self.plan, 'preview_identity': reference})
        journal = self.paths.state / 'walk_forward' / reference / 'walk_forward.sqlite3'
        observed = None
        event_evidence = []
        terminal_journal = None

        def read_journal():
            with closing(sqlite3.connect(journal, timeout=.1)) as db, db:
                row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            return json.loads(row[0]) if row else None

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            # A concurrent SELECT can make the zero-timeout writer fail before
            # cancellation. Read only once the genuine nested evaluator is held
            # after its reservation commit, with the parent writer quiescent.
            if evaluation_started.is_set() and journal.exists():
                try:
                    candidate = read_journal()
                    if candidate:
                        if candidate['evaluations'] and candidate['evaluations'][-1]['status'] == 'running':
                            observed = candidate
                            break
                except sqlite3.OperationalError:
                    pass  # The writer may still be creating its first table.
            polled = self.manager.poll()
            for event in polled:
                item = {'type': event['type']}
                if 'message' in event:
                    item['message'] = str(event['message'])[:2000]
                if isinstance(event.get('result'), dict):
                    item['result_status'] = event['result'].get('status')
                event_evidence.append(item)
            event_evidence = event_evidence[-20:]
            if any(event['type'] in ('result', 'error', 'cancelled') for event in polled):
                break  # A terminal worker cannot later expose an active evaluation.
            time.sleep(.005)
        if observed is None and journal.exists():
            try:
                candidate = read_journal()
                terminal_journal = None if candidate is None else {
                    'status': candidate['status'],
                    'evaluation_statuses': [item['status'] for item in candidate['evaluations']]}
            except sqlite3.OperationalError as exc:
                terminal_journal = {'read_error': str(exc)}
        self.assertIsNotNone(observed, 'Did not observe a durable running evaluation to cancel; ' +
            json.dumps({'worker_events': event_evidence, 'journal': terminal_journal}, ensure_ascii=False))
        self.manager.cancel()
        events = self.manager.poll()
        self.assertEqual([event['type'] for event in events], ['cancelled'])
        from quantlab.walk_forward import read_walk_forward_state
        stopped = read_walk_forward_state(journal.parent)
        reserved_count = len(stopped['evaluations'])
        self.assertEqual(stopped['status'], 'running')
        restarted = JobManager(self.paths)
        with self.assertRaises(RuntimeSafetyError):
            restarted.start('ui_walk_forward_reconcile', {'reference': reference, 'stopped_job_id': job_id})
        self.manager.start('ui_walk_forward_reconcile', {'reference': reference, 'stopped_job_id': job_id})
        result = self.finish()
        reconciled = read_walk_forward_state(journal.parent)
        self.assertEqual(result['status'], 'blocked_interrupted')
        self.assertEqual(len(reconciled['evaluations']), reserved_count)
        self.assertEqual(reconciled['registry_reservation'], stopped['registry_reservation'])
        self.assertFalse(any(record['status'] == 'running' for record in reconciled['evaluations']))


if __name__ == '__main__':
    unittest.main()
