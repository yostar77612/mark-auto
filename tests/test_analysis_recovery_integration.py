"""Offline production-boundary tests, not native Windows handle certification.

The Windows capability switch is patched for platform-neutral ledger/journal
integration. No kernel object, original-GUI-death or Windows token claim follows.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from quantlab import analysis_recovery as r
from quantlab import desktop_runtime as runtime
from quantlab import research_analysis as a
from quantlab.core import ValidationError, canonical_json, content_hash
from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
import quantlab.assistant.adapters.chatgpt.provider as p
from tests.test_research_analysis import source, prepare, PROVENANCE, AnalysisWire


def snapshot(root):
    return {str(file.relative_to(root)): file.read_bytes() for file in root.rglob('*') if file.is_file()}


class DurableRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.paths = runtime.AppPaths(self.base / 'workspace', self.base / 'bootstrap').ensure()
        self.data, self.state, self.folder = source(self.paths.state / 'campaigns')
        self.plan = a.make_analysis_plan(
            prepare(self.folder, self.data, self.state), model='fixture-model', registration='a' * 32, provider_implementation=PROVENANCE
        )
        self.request = {
            'campaign_reference': self.folder.name,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(self.base / 'original.json')},
            'attempt_ids': [self.state['attempts'][0]['attempt_id']],
            'task': 'critique',
            'registration': 'a' * 32,
            'model': 'fixture-model',
            'timeout_seconds': 30,
        }
        for patcher in (
            patch.object(p, 'implementation_provenance', return_value=PROVENANCE),
            patch.object(p, 'PlanHTTPTransport', AnalysisWire),
            patch('http.client.HTTPSConnection', side_effect=AssertionError('No network')),
            patch.object(p.ChatGPTPlanProvider, 'analyze', side_effect=AssertionError('No model call')),
            patch.object(p.ChatGPTPlanProvider, 'analysis_preflight', side_effect=AssertionError('No preflight')),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        AnalysisWire.requests = []
        self.provider = p.analysis_provider(self.plan, OAuthCredentialReference(str(self.paths.bootstrap), 'a' * 32))
        self.output = self.paths.state / 'analyses'
        self.analysis_folder = self.output / self.plan['analysis_id']

    def register(self):
        with r.admission(self.paths) as token:
            return r.register_launch(self.paths, job_id='b' * 32, helper_nonce='c' * 32, approved_plan=self.plan, request=self.request, admission=token)

    def pending_record(self):
        self.analysis_folder.mkdir(parents=True)
        with closing(sqlite3.connect(self.analysis_folder / 'analysis.lock.sqlite3')):
            pass
        record = {
            'schema_version': 1,
            'plan': self.plan,
            'provider_descriptor': self.provider.provider_descriptor(),
            'status': 'running',
            'response': None,
            'response_hash': None,
            'receipt_snapshot': self.provider.read_receipt_snapshot(),
            'real_model_status': 'not_verified',
        }
        a._save(self.analysis_folder, record)
        request = a.analysis_request(self.plan)
        self.provider._reserve(content_hash(request), len(canonical_json(request).encode()))
        return record

    def stopped(self):
        launch = self.register()
        self.pending_record()
        r._StopPublisher(self.paths, launch, lambda: 0).publish()
        return launch

    def reconcile(self, **changes):
        args = dict(output_root=self.output, analysis_id=self.plan['analysis_id'], provider=self.provider, recovery=(self.paths, 'b' * 32))
        args.update(changes)
        with patch.object(r, 'supports_durable_recovery', return_value=True):
            return a.reconcile_analysis(**args)

    def test_new_manager_admission_then_real_local_repair_preserves_provider_controls(self):
        from desktop_app.shell.main_window import execute_ui_operation

        self.stopped()
        manager = runtime.JobManager(self.paths)
        self.assertIsNone(manager._quiesced_analysis)
        payload = {'analysis_id': self.plan['analysis_id'], 'registration': 'a' * 32, 'recovery_launch_id': 'b' * 32}
        process, sender, receiver, gate = Mock(), Mock(), Mock(), Mock()
        process.pid = 12345
        process.is_alive.return_value = False
        context = Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Event.return_value = gate
        context.Process.return_value = process
        with (
            patch.object(r, 'supports_durable_recovery', return_value=True),
            patch.object(runtime.mp, 'get_context', return_value=context),
            patch.object(runtime, '_WindowsProcessTree') as simulated_tree,
        ):
            manager.start('ui_analysis_reconcile', payload)
        self.assertEqual(context.Process.call_args.kwargs['args'][3], payload)
        process.start.assert_called_once()
        gate.set.assert_called_once()
        # Admission above is a simulated launch, not a claimed native process test.
        manager._release()
        self.assertIsNone(manager._quiesced_analysis)
        process.close.assert_called_once()
        receiver.close.assert_called_once()
        if runtime.sys.platform == 'win32':
            simulated_tree.assert_called_once_with(process.pid)
            simulated_tree.return_value.close.assert_called_once()
        else:
            simulated_tree.assert_not_called()
        controls, campaigns = snapshot(self.paths.controls), snapshot(self.paths.state / 'campaigns')
        with patch.object(r, 'supports_durable_recovery', return_value=True):
            result = execute_ui_operation('ui_analysis_reconcile', payload, self.paths)
        self.assertEqual(result['record']['status'], 'blocked')
        self.assertEqual(result['record']['receipt_snapshot']['receipts'][0]['status'], 'reserved_unknown')
        self.assertEqual(snapshot(self.paths.controls), controls)
        self.assertEqual(snapshot(self.paths.state / 'campaigns'), campaigns)
        self.assertEqual(AnalysisWire.requests, [])
        self.assertEqual(self.reconcile(), result['record'])
        self.assertEqual(len(self.provider.read_receipts()), 1)

    def test_missing_receipt_and_wrong_launch_reject_before_repair(self):
        self.register()
        self.pending_record()
        before = snapshot(self.analysis_folder)
        for reference in ('b' * 32, 'f' * 32):
            with self.assertRaises(r.RecoveryError):
                self.reconcile(recovery=(self.paths, reference))
        self.assertEqual(snapshot(self.analysis_folder), before)
        self.assertEqual(AnalysisWire.requests, [])

    def test_wrong_helper_nonce_cannot_enter_actual_worker_operation(self):
        launch = self.register()
        with self.assertRaises(runtime.RuntimeSafetyError):
            with runtime._worker_recovery_guard(self.paths, 'ui_analysis_run', launch['job_id'], 'd' * 32):
                self.fail('Wrong helper generation entered operation')
        r._StopPublisher(self.paths, launch, lambda: 0).publish()
        with self.assertRaises(r.RecoveryError):
            with runtime._worker_recovery_guard(self.paths, 'ui_analysis_run', launch['job_id'], launch['helper_nonce']):
                self.fail('Stopped launch reopened')

    def test_receipt_rechecked_inside_exclusive_analysis_lock(self):
        self.stopped()
        original = r.validate_stop_receipt
        observed = []

        def verify(*args, **kwargs):
            with closing(sqlite3.connect(self.analysis_folder / 'analysis.lock.sqlite3', timeout=0)) as other:
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute('BEGIN EXCLUSIVE')
            observed.append(kwargs.get('record', {}).get('status'))
            return original(*args, **kwargs)

        with patch.object(r, 'validate_stop_receipt', side_effect=verify):
            self.assertEqual(self.reconcile()['status'], 'blocked')
        self.assertEqual(observed, ['running'])

    def test_repair_holds_installation_admission_through_final_journal_write(self):
        self.stopped()
        original_save = a._save
        attempted = []

        def save_while_restore_contends(folder, record):
            def restore():
                try:
                    with r.admission(self.paths, timeout=0.05) as token:
                        r.advance_restore_epoch(self.paths, 'd' * 32, admission=token)
                    attempted.append('unexpectedly admitted')
                except r.RecoveryError:
                    attempted.append('blocked')

            thread = threading.Thread(target=restore)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(attempted, ['blocked'])
            return original_save(folder, record)

        with patch.object(a, '_save', side_effect=save_while_restore_contends):
            self.assertEqual(self.reconcile()['status'], 'blocked')
        self.assertEqual(attempted, ['blocked'])
        self.assertEqual(r._load(self.paths)['workspaces'][r._directory(self.paths.root)['root']]['epoch'], 0)
        self.assertEqual(self.provider.read_receipts()[0]['status'], 'reserved_unknown')

    def test_restore_epoch_changed_after_adapter_precheck_is_rechecked_under_lock(self):
        from desktop_app.shell.main_window import execute_ui_operation

        self.stopped()
        original = a.reconcile_analysis

        def change_epoch(**kwargs):
            with r.admission(self.paths) as token:
                r.advance_restore_epoch(self.paths, 'd' * 32, admission=token)
            return original(**kwargs)

        before = snapshot(self.analysis_folder)
        with patch.object(r, 'supports_durable_recovery', return_value=True), patch.object(a, 'reconcile_analysis', side_effect=change_epoch):
            with self.assertRaises(r.RecoveryError):
                execute_ui_operation(
                    'ui_analysis_reconcile', {'analysis_id': self.plan['analysis_id'], 'registration': 'a' * 32, 'recovery_launch_id': 'b' * 32}, self.paths
                )
        self.assertEqual(snapshot(self.analysis_folder), before)
        self.assertEqual(AnalysisWire.requests, [])

    def test_unrelated_root_invalid_journal_and_original_provider_checks_survive(self):
        self.stopped()
        other = runtime.AppPaths(self.base / 'other', self.paths.bootstrap).ensure()
        with self.assertRaises(ValidationError):
            self.reconcile(recovery=(other, 'b' * 32))
        original = (self.analysis_folder / 'analysis.sqlite3').read_bytes()
        with closing(sqlite3.connect(self.analysis_folder / 'analysis.sqlite3')) as db, db:
            row = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            row['plan']['binding']['timeout_seconds'] = 31
            db.execute('UPDATE state SET payload=? WHERE id=1', (canonical_json(row),))
        with self.assertRaises(ValueError):
            self.reconcile()
        (self.analysis_folder / 'analysis.sqlite3').write_bytes(original)
        wrong_provider = Mock()
        wrong_provider.provider_descriptor.return_value = {**self.provider.provider_descriptor(), 'model': 'wrong'}
        with self.assertRaises(ValidationError):
            self.reconcile(provider=wrong_provider)
        wrong_provider.read_receipt_snapshot.assert_not_called()
        self.assertEqual(AnalysisWire.requests, [])

    def test_windows_missing_approved_plan_rejects_before_spawn(self):
        payload = {
            'request': self.request,
            'expected_analysis_id': self.plan['analysis_id'],
            'expected_plan_hash': content_hash(self.plan),
            'user_confirmed': True,
            'network_opt_in': True,
            'included_usage_policy_confirmed': True,
        }
        manager = runtime.JobManager(self.paths)
        # Only enter Windows validation; no Win32 API or path operation is run.
        with patch.object(runtime.sys, 'platform', 'win32'), patch.object(runtime.mp, 'get_context') as spawn:
            with self.assertRaises(ValueError):
                manager.start('ui_analysis_run', payload)
        spawn.assert_not_called()
        self.assertTrue(r.inspect_recovery(self.paths).legacy)
        self.assertFalse(self.analysis_folder.exists())

    def test_linux_durable_route_remains_rejected_at_every_product_boundary(self):
        from desktop_app.shell.main_window import execute_ui_operation

        self.stopped()
        payload = {'analysis_id': self.plan['analysis_id'], 'registration': 'a' * 32, 'recovery_launch_id': 'b' * 32}
        with patch.object(r, 'supports_durable_recovery', return_value=False):
            manager = runtime.JobManager(self.paths)
            with patch.object(runtime.mp, 'get_context') as spawn, self.assertRaises(runtime.RuntimeSafetyError):
                manager.start('ui_analysis_reconcile', payload)
            spawn.assert_not_called()
            with self.assertRaises(ValidationError):
                execute_ui_operation('ui_analysis_reconcile', payload, self.paths)
            with self.assertRaises(ValidationError):
                a.reconcile_analysis(output_root=self.output, analysis_id=self.plan['analysis_id'], provider=self.provider, recovery=(self.paths, 'b' * 32))

    def test_direct_backup_services_block_unresolved_before_writes(self):
        self.register()
        backup = runtime.BackupManager(self.paths)
        before = snapshot(self.paths.root)
        backup.recover()  # No artifacts is a real no-op, including no lock writes.
        self.assertEqual(before, snapshot(self.paths.root))
        archive = self.base / 'backup.zip'
        for action in (lambda: backup.create(archive), lambda: backup.restore(archive)):
            with self.assertRaises(r.RecoveryError):
                action()
        self.assertFalse(archive.exists())
        (self.paths.root / 'restore-transaction.json').write_text('{"id":"' + 'e' * 32 + '","phase":"prepared"}')
        before = snapshot(self.paths.root)
        with self.assertRaises(r.RecoveryError):
            backup.recover()
        self.assertEqual(before, snapshot(self.paths.root))

    def test_alternate_workspace_restore_cannot_replace_original_external_source(self):
        other = runtime.AppPaths(self.base / 'source-workspace', self.paths.bootstrap).ensure()
        source_file = other.state / 'dataset.json'
        source_file.write_text('original source bytes')
        self.request['original_dataset']['path'] = str(source_file)
        self.register()
        backup = runtime.BackupManager(other)
        before = snapshot(other.root)
        with self.assertRaises(r.RecoveryError):
            backup.restore(self.base / 'not-opened.zip')
        self.assertEqual(snapshot(other.root), before)
        (other.root / 'restore-transaction.json').write_text('{"id":"' + 'e' * 32 + '","phase":"prepared"}')
        before = snapshot(other.root)
        with self.assertRaises(r.RecoveryError):
            backup.recover()
        self.assertEqual(snapshot(other.root), before)
        self.assertEqual(source_file.read_text(), 'original source bytes')

    def test_corrupt_analysis_controls_preserve_independent_selection_and_paper_risk_gates(self):
        from datetime import timedelta
        from desktop_app.shell.main_window import execute_ui_operation
        from quantlab.core import to_dict
        from quantlab.reporting import save_dataset, demo_config
        from quantlab.paper import ReconciliationError, LiveBroker, LiveTradingDisabled

        save_dataset(self.data, self.paths.state / 'dataset.json')
        execute_ui_operation('ui_backtest', {'family': 'trend', 'config': to_dict(demo_config())}, self.paths)
        report = next((self.paths.state / 'reports').glob('*/result.json'))
        self.register()
        (self.paths.controls / r._DATABASE).unlink()
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        controls = snapshot(self.paths.controls)
        source = (self.paths.state / 'dataset.json').read_bytes()
        campaigns = snapshot(self.paths.state / 'campaigns')

        def call(operation, payload):
            # The real service dispatcher admission plus actual paper adapter.
            r.require_operation(self.paths, operation)
            with runtime._worker_recovery_guard(self.paths, operation, 'f' * 32, None):
                return execute_ui_operation(operation, payload, self.paths)

        selection = call('ui_select', {'result': str(report)})
        self.assertEqual(selection['scope'], 'research_and_paper_only')
        first, last = self.data.bars[0], self.data.bars[-1]
        policy = {
            'contract_id': first.contract_id,
            'risk_sessions': [
                {
                    'open': first.timestamp.isoformat(),
                    'end': last.end.isoformat(),
                    'trade_date': first.trade_date,
                    'session': first.session,
                    'contract_id': first.contract_id,
                    'source': 'explicit synthetic demonstration',
                }
            ],
            'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}],
        }
        result = call('ui_paper_snapshot', {'policy': policy})
        self.assertTrue(result['account']['reconciliation_required'])
        with self.assertRaises(ReconciliationError):
            call('ui_paper_reconcile', {'policy': policy, 'snapshot': {}})
        account = call(
            'ui_paper_reconcile', {'policy': policy, 'snapshot': {'account_id': 'synthetic', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}}
        )['account']
        for operation in ('ui_paper_submit', 'ui_paper_replay'):
            with self.assertRaises(ValidationError):
                call(operation, {'policy': policy, 'snapshot': account})
        now = (first.timestamp + timedelta(minutes=1)).isoformat()
        result = call(
            'ui_paper_submit',
            {
                'policy': policy,
                'snapshot': account,
                'reconcile_confirmed': True,
                'intent': {
                    'client_order_id': 'risk-rejected',
                    'strategy_hash': selection['strategy_hash'],
                    'contract_id': first.contract_id,
                    'side': 'buy',
                    'quantity': 2,
                    'order_type': 'market',
                    'created_at': now,
                },
                'quote': {
                    'account_id': 'synthetic',
                    'contract_id': first.contract_id,
                    'timestamp': now,
                    'price': '20000',
                    'trade_date': first.trade_date,
                    'session_open': first.timestamp.isoformat(),
                    'session_end': last.end.isoformat(),
                    'margin_per_contract': '100000',
                },
                'now': now,
            },
        )
        order = result['account']['orders']['risk-rejected']
        self.assertEqual(order['status'], 'rejected')
        self.assertEqual(order['reason'], 'max_order_quantity')
        self.assertEqual(result['account']['positions'], {})
        self.assertEqual(result['account']['fills'], {})
        cancelled = call('ui_paper_cancel', {'policy': policy, 'order_id': 'risk-rejected', 'now': now})
        self.assertEqual(cancelled['account']['orders']['risk-rejected']['status'], 'rejected')
        self.assertTrue(call('ui_paper_kill', {'policy': policy})['account']['kill_switch'])
        call('ui_disable', {})
        self.assertFalse((self.paths.state / 'selection.json').exists())
        self.assertEqual((self.paths.state / 'dataset.json').read_bytes(), source)
        self.assertEqual(snapshot(self.paths.state / 'campaigns'), campaigns)
        self.assertEqual(snapshot(self.paths.controls), controls)
        self.assertEqual(AnalysisWire.requests, [])
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()
        for operation in ('ui_chatgpt_auth', 'ui_chatgpt_reconcile', 'ui_campaign', 'ui_analysis_run', 'ui_import', 'ui_backup_restore'):
            with self.assertRaises(r.RecoveryError):
                r.require_operation(self.paths, operation)

    def test_legacy_backup_restore_and_real_restore_epoch_hook(self):
        backup = runtime.BackupManager(self.paths)
        archive = self.base / 'backup.zip'
        (self.paths.state / 'note.txt').write_text('original')
        backup.create(archive)
        (self.paths.state / 'note.txt').write_text('changed')
        backup.restore(archive)
        self.assertEqual((self.paths.state / 'note.txt').read_text(), 'original')
        self.assertTrue(r.inspect_recovery(self.paths).legacy)
        launch = self.stopped()
        backup.restore(archive)
        with self.assertRaises(r.RecoveryError):
            r.validate_stop_receipt(self.paths, launch['job_id'])
        self.assertEqual(r._load(self.paths)['workspaces'][launch['workspace']['root']]['epoch'], 1)
        self.assertFalse(r.inspect_recovery(self.paths).unresolved)

    def test_actual_worker_body_holds_conflict_guard_until_operation_finishes(self):
        entered, finish, gate = threading.Event(), threading.Event(), threading.Event()
        gate.set()
        sender = Mock()

        def slow_operation(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(5))
            return {}

        with patch('desktop_app.shell.main_window.execute_ui_operation', side_effect=slow_operation), patch.object(runtime.os, 'setsid', create=True):
            thread = threading.Thread(
                target=runtime._job_worker, args=(sender, gate, 'ui_import', {}, str(self.paths.root), str(self.paths.bootstrap), 'f' * 32)
            )
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(r.RecoveryError):
                    self.register()
                self.assertTrue(r.inspect_recovery(self.paths).legacy)
            finally:
                finish.set()
                thread.join(5)
                self.assertFalse(thread.is_alive())
        events = [json.loads(call.args[0]) for call in sender.send_bytes.call_args_list]
        self.assertEqual(events[-1]['type'], 'result')
        self.register()


if __name__ == '__main__':
    unittest.main()
