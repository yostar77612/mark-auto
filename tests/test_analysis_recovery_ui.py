"""Actual production Qt recovery UI against synthetic original-control records.

No test-policy adapter: production admission, buttons, callbacks and backup
controller are exercised. Receipt publication uses an explicitly synthetic
query fixture; original Windows handle semantics are a separate native test.
No provider/network/helper is executed. All workspaces are temporary.
"""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None

from quantlab.research_core.adapters.workspace_store import AppPaths, WorkspaceLocator
from desktop_app.research_bootstrap import create_job_manager
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.research_core.adapters.workspace_backup import BackupManager
from quantlab import analysis_recovery as recovery
from tests import test_restart_availability_contract as contract
from tests.test_restart_availability_contract import _offline_worker, _snapshot


@unittest.skipUnless(HAS_QT, 'Actual Qt required')
class AnalysisRecoveryUITests(unittest.TestCase):
    setUpClass = contract.RestartAvailabilityContractTests.__dict__['setUpClass']
    _seed_synthetic_evidence = contract.RestartAvailabilityContractTests._seed_synthetic_evidence
    _protected = contract.RestartAvailabilityContractTests._protected
    _click = contract.RestartAvailabilityContractTests._click
    _wait_job = contract.RestartAvailabilityContractTests._wait_job
    _enable_backup = contract.RestartAvailabilityContractTests._enable_backup

    def setUp(self):
        from desktop_app.shell.window import MainWindow
        from quantlab.research_analysis import _read_analysis_journal

        self.tmp = tempfile.TemporaryDirectory(prefix='markauto-recovery-ui-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.paths = AppPaths(self.base / 'workspace', self.base / 'bootstrap').ensure()
        self._seed_synthetic_evidence()
        plan = _read_analysis_journal(self.paths.state / 'analyses', self.pending_id)['plan']
        binding = plan['binding']
        packet = binding['packet']
        request = {
            'campaign_reference': self.campaign.name,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(self.dataset)},
            'attempt_ids': sorted({row['attempt_id'] for row in packet['provenance']['result_links']}),
            'task': packet['context']['task'],
            'model': binding['model'],
            'registration': binding['registration'],
            'timeout_seconds': binding['timeout_seconds'],
        }
        with recovery.admission(self.paths) as token:
            self.launch = recovery.register_launch(self.paths, job_id='c' * 32, helper_nonce='d' * 32, approved_plan=plan, request=request, admission=token)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in (
            'socket.create_connection',
            'http.client.HTTPSConnection',
            'quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport',
            'quantlab.research_core.application.analysis_operations.analysis_provider_for',
        ):
            self.stack.enter_context(patch(target, side_effect=AssertionError('No recovery UI network/provider')))
        self.stack.enter_context(patch('quantlab.research_core.adapters.job_worker._job_worker', _offline_worker))
        self.jobs = create_job_manager(self.paths)
        self.backups = BackupManager(self.paths, self.jobs)
        self.window = MainWindow(
            self.paths, self.jobs, SettingsStore(self.paths.state / 'settings.json'), self.backups, services=_c_create_ui_services(_c_create_operation_ports())
        )
        self.addCleanup(lambda: (self.cleanup_window(), contract._destroy_owned_window(self, self.window)))
        self.window.timer.stop()
        self.panel = self.window.automatic_backup_panel
        self.panel.timer.stop()
        self.jobs.logging_enabled = False
        self.window.show()
        self.app.processEvents()
        self.protected = self._protected()

    def cleanup_window(self):
        self.window.timer.stop()
        self.panel.timer.stop()
        self.jobs.close()
        self.window._analysis_running = self.window._pending_analysis_reconcile = False
        self.window._analysis_launch = None
        self.window.close()  # Must work while the original ledger remains unresolved.
        self.app.processEvents()
        self.assertFalse(self.window.isVisible(), 'Unresolved analysis must not prevent ordinary close')
        self.assertFalse(self.jobs.active)

    def publish_synthetic_stop(self):
        recovery._StopPublisher(self.paths, self.launch, lambda: 0).publish()

    def test_real_reads_backtest_compare_and_close_keep_unresolved_controls(self):
        w = self.window
        w.analysis_saved.setCurrentIndex(w.analysis_saved.findData(self.completed_id))
        self._click('read_candidate_analysis')
        self._wait_job()
        self.assertTrue(w.analysis_findings.toPlainText())
        w.analysis_saved.setCurrentIndex(w.analysis_saved.findData(self.pending_id))
        self.assertIn('中斷檢查點', w.analysis_checkpoint_notice.text())
        self.assertFalse(w.analysis_recover.isEnabled())
        self._click('run_backtest')
        self._wait_job()
        self.assertTrue(w.plot.values)
        w.comparison_list.item(0).setSelected(True)
        self._click('compare_results')
        self._wait_job()
        self.assertIn('result_hash', w.comparison.toPlainText())
        self.assertFalse(w.analysis_start.isEnabled())
        self.assertEqual(self._protected(), self.protected)
        w.close()
        self.app.processEvents()
        self.assertFalse(w.isVisible())
        self.assertTrue(recovery.inspect_recovery(self.paths).workspace_unresolved)

    def test_refresh_completion_and_freeze_keep_conflicts_before_backup_claim(self):
        from PySide6.QtWidgets import QPushButton

        self._enable_backup()
        before = self.panel.scheduler.path.read_bytes()
        for callback in (
            lambda: self.window._busy(False, refresh_recovery=True),
            self.window.refresh_views,
            self.window.poll_jobs,
            lambda: self.window.freeze_paper('synthetic clock event'),
        ):
            self.window._analysis_preview = {'receipt_snapshot': {'receipts': []}}
            callback()
            for name in ('run_candidate_analysis', 'create_backup', 'restore_backup', 'import_data', 'run_campaign', 'market_refresh'):
                self.assertFalse(self.window.findChild(QPushButton, name).isEnabled(), name)
            self.assertTrue(self.window.run_button.isEnabled())
        with (
            patch.object(self.panel.scheduler, 'claim_due', wraps=self.panel.scheduler.claim_due) as claim,
            patch.object(self.window, 'start_job', wraps=self.window.start_job) as start,
        ):
            self.panel.tick()
            claim.assert_not_called()
            start.assert_not_called()
        self.assertEqual(self.panel.scheduler.path.read_bytes(), before)
        self.assertFalse(self.panel.paused, 'Expected quarantine is a deferral, not a failed attempt')
        self.assertEqual(self._protected(), self.protected)
        with patch('quantlab.research_core.adapters.job_process.mp.get_context') as spawn:
            for operation in recovery.SOURCE_WRITERS | recovery.ANALYSIS_STARTS | recovery.WORKSPACE_MUTATIONS:
                if operation.startswith('ui_'):
                    with self.subTest(operation=operation), self.assertRaises(recovery.RecoveryError):
                        self.window.start_job(operation, {})
            spawn.assert_not_called()

    def test_idle_display_throttles_reads_but_reapplies_masks_and_dispatch_is_fresh(self):
        from PySide6.QtWidgets import QPushButton

        self.window._refresh_recovery_controls(force=True)
        with (
            patch('time.monotonic', return_value=self.window._recovery_display[0] + 3),
            patch('quantlab.analysis_recovery.inspect_recovery', wraps=recovery.inspect_recovery) as inspect,
        ):
            for _ in range(12):
                self.window._busy(False)
                self.assertFalse(self.window.findChild(QPushButton, 'restore_backup').isEnabled())
            inspect.assert_not_called()
            with self.assertRaises(recovery.RecoveryError):
                self.window.start_job('ui_import', {})
            inspect.assert_called_once()
        database = self.paths.controls / 'analysis-recovery-v1.sqlite3'
        info = database.stat()
        os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with (
            patch('time.monotonic', return_value=self.window._recovery_display[0] + 3),
            patch('quantlab.analysis_recovery.inspect_recovery', wraps=recovery.inspect_recovery) as inspect,
        ):
            self.window._busy(False)
            inspect.assert_called_once()
        self.assertEqual(self._protected(), self.protected)

    @patch('quantlab.analysis_recovery.supports_durable_recovery', return_value=True)
    def test_exact_receipt_enables_explicit_route_but_restore_epoch_disables_it(self, supported):
        self.window.analysis_saved.setCurrentIndex(self.window.analysis_saved.findData(self.pending_id))
        self.assertFalse(self.window.analysis_recover.isEnabled())
        self.publish_synthetic_stop()
        self.window._busy(False, refresh_recovery=True)
        self.assertTrue(self.window.analysis_recover.isEnabled())
        controls = _snapshot(self.paths.controls)
        with patch.object(self.jobs, 'start', return_value='local-repair-job') as start:
            self.window.reconcile_saved_analysis()
            start.assert_called_once_with(
                'ui_analysis_reconcile', {'analysis_id': self.pending_id, 'registration': 'a' * 32, 'recovery_launch_id': self.launch['job_id']}
            )
        self.assertEqual(_snapshot(self.paths.controls), controls)
        self.assertIsNone(self.jobs._quiesced_analysis)
        with recovery.admission(self.paths) as token:
            recovery.advance_restore_epoch(self.paths, 'e' * 32, admission=token)
        self.window._busy(False, refresh_recovery=True)
        self.assertFalse(self.window.analysis_recover.isEnabled())
        with patch.object(self.jobs, 'start') as start:
            with self.assertRaises(ValueError):
                self.window.reconcile_saved_analysis()
            start.assert_not_called()

    def test_unsupported_runtime_never_offers_durable_reconciliation(self):
        self.publish_synthetic_stop()
        self.window.analysis_saved.setCurrentIndex(self.window.analysis_saved.findData(self.pending_id))
        with patch('quantlab.analysis_recovery.supports_durable_recovery', return_value=False):
            self.window._busy(False, refresh_recovery=True)
            self.assertFalse(self.window.analysis_recover.isEnabled())
            with self.assertRaises(ValueError):
                self.window.reconcile_saved_analysis()

    def test_unknown_controls_keep_non_ai_available_without_becoming_legacy(self):
        from desktop import _prepare_startup_workspace

        database = self.paths.controls / 'analysis-recovery-v1.sqlite3'
        database.write_bytes(b'corrupt synthetic controls')
        original = _snapshot(self.paths.controls)
        with patch.object(self.backups, 'recover', side_effect=AssertionError('Unknown controls cannot authorize restore')):
            self.assertIsNone(_prepare_startup_workspace(self.paths, self.backups))
            self.window.freeze_paper('unknown controls')
        self.window._busy(False, refresh_recovery=True)
        self.assertIn('無法安全核對', self.window.analysis_recovery_notice.text())
        self.assertFalse(self.window.analysis_recover.isEnabled())
        self._click('run_backtest')
        self._wait_job()
        self.assertTrue(self.window.plot.values)
        with self.assertRaises(recovery.RecoveryError):
            recovery.inspect_recovery(self.paths)
        self.assertEqual(_snapshot(self.paths.controls), original)
        self.window.close()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_positive_stop_allows_real_backup_when_journal_is_missing(self):
        (self.pending_folder / 'analysis.sqlite3').unlink()
        self.publish_synthetic_stop()
        controls = _snapshot(self.paths.controls)
        self.window._busy(False, refresh_recovery=True)
        self._enable_backup()
        self.panel.tick()
        self._wait_job()
        result = self.panel.scheduler.load()
        self.assertEqual(result['last_status'], 'success')
        self.assertTrue(Path(result['last_archive']).is_file())
        self.assertFalse((self.pending_folder / 'analysis.sqlite3').exists())
        self.assertFalse((self.pending_folder / 'analysis.json').exists())
        self.assertEqual(_snapshot(self.paths.controls), controls)

    def test_startup_is_safe_for_intact_unresolved_and_rejects_ambiguous_layout(self):
        from desktop import _prepare_startup_workspace

        before = self._protected()
        with patch.object(self.backups, 'recover', side_effect=AssertionError('Must not recover unresolved writer')):
            disposition = _prepare_startup_workspace(self.paths, self.backups)
        self.assertTrue(disposition.workspace_unresolved)
        self.assertEqual(self._protected(), before)
        rollback = self.paths.root / 'state-v1.rollback'
        rollback.mkdir()
        (rollback / 'preserve').write_bytes(b'synthetic original')
        journal = self.paths.root / 'restore-transaction.json'
        journal.write_text(json.dumps({'id': 'f' * 32, 'phase': 'prepared'}))
        before = _snapshot(self.paths.root)
        try:
            with patch.object(self.paths.__class__, 'ensure', side_effect=AssertionError('No state writes')):
                with self.assertRaises(recovery.RecoveryError):
                    _prepare_startup_workspace(self.paths, self.backups)
            with self.assertRaises(recovery.RecoveryError):
                self.window.freeze_paper('ambiguous synthetic restore')
            self.assertEqual(_snapshot(self.paths.root), before)
        finally:
            journal.unlink()
            (rollback / 'preserve').unlink()
            rollback.rmdir()

    def test_other_workspace_keeps_non_ai_but_enforces_installation_source_conflict(self):
        from PySide6.QtWidgets import QPushButton
        from desktop_app.shell.window import MainWindow
        from quantlab.reporting import save_dataset

        original = _snapshot(self.paths.root)
        controls = _snapshot(self.paths.controls)
        locator = WorkspaceLocator(self.paths.bootstrap)
        locator.configure(self.base / 'other-workspace')
        other = locator.load(probe=False).ensure()
        save_dataset(self.data, other.state / 'dataset.json')
        jobs = create_job_manager(other)
        window = MainWindow(
            other, jobs, SettingsStore(other.state / 'settings.json'), BackupManager(other, jobs), services=_c_create_ui_services(_c_create_operation_ports())
        )
        window.timer.stop()
        window.automatic_backup_panel.timer.stop()
        try:
            self.assertFalse(recovery.inspect_recovery(other).workspace_unresolved)
            from desktop import _prepare_startup_workspace

            with patch.object(BackupManager, 'recover', side_effect=AssertionError('Global unresolved may protect external source')):
                self.assertTrue(_prepare_startup_workspace(other, BackupManager(other)).unresolved)
            rollback = other.root / 'state-v1.rollback'
            rollback.mkdir()
            try:
                with self.assertRaises(recovery.RecoveryError):
                    _prepare_startup_workspace(other, BackupManager(other))
                with self.assertRaises(recovery.RecoveryError):
                    window.freeze_paper('other workspace ambiguous restore')
            finally:
                rollback.rmdir()
            self.assertTrue(window.run_button.isEnabled())
            self.assertFalse(window.findChild(QPushButton, 'import_data').isEnabled())
            self.assertTrue(window.findChild(QPushButton, 'create_backup').isEnabled())
            self.assertFalse(window.findChild(QPushButton, 'restore_backup').isEnabled())
            with self.assertRaises(recovery.RecoveryError):
                window.start_job('ui_backup_restore', {})
            with self.assertRaises(recovery.RecoveryError):
                window.start_job('ui_import', {})
            window.run_backtest()
            deadline = time.monotonic() + 20
            while jobs.active and time.monotonic() < deadline:
                self.app.processEvents()
                window.poll_jobs()
                time.sleep(0.01)
            window.poll_jobs()
            self.assertFalse(jobs.active, window.status.text())
            self.assertEqual(len(list((other.state / 'reports').glob('*/result.json'))), 1)
        finally:
            jobs.close()
            window.close()
            self.app.processEvents()
        self.assertEqual(_snapshot(self.paths.root), original)
        self.assertEqual(_snapshot(self.paths.controls), controls)

    def test_full_normal_startup_and_close_with_unresolved_analysis(self):
        self._assert_full_startup_and_close()

    def test_full_normal_startup_and_close_with_unknown_controls(self):
        (self.paths.controls / 'analysis-recovery-v1.sqlite3').write_bytes(b'corrupt synthetic controls')
        self._assert_full_startup_and_close(unknown=True)

    def _assert_full_startup_and_close(self, *, unknown=False):
        import desktop
        from desktop_app.shell.window import MainWindow
        from PySide6.QtCore import QTimer

        locator = WorkspaceLocator(self.paths.bootstrap)
        locator.configure(self.paths.root)
        self.window.hide()
        before = self._protected()
        real_show = MainWindow.show
        opened = []

        def show_then_close(window):
            real_show(window)
            opened.append(window)

            def finish():
                window.close()
                self.app.exit(0)

            QTimer.singleShot(40, finish)

        with (
            patch('PySide6.QtWidgets.QApplication', return_value=self.app),
            patch.object(AppPaths, 'discover', return_value=AppPaths(self.paths.bootstrap)),
            patch.object(MainWindow, 'show', show_then_close),
            patch.object(BackupManager, 'recover', side_effect=AssertionError('Unresolved startup must skip recovery')),
            patch('desktop._offer_workspace_after_recovery_block', side_effect=AssertionError('Intact state must remain usable')),
        ):
            self.assertEqual(desktop.main([]), 0)
        self.assertEqual(len(opened), 1)
        self.assertFalse(opened[0].isVisible())
        self.assertEqual(self._protected(), before)
        if unknown:
            with self.assertRaises(recovery.RecoveryError):
                recovery.inspect_recovery(self.paths)
        else:
            self.assertTrue(recovery.inspect_recovery(self.paths).workspace_unresolved)

    def test_clean_legacy_startup_has_no_recovery_ledger_or_conflict(self):
        from desktop import _prepare_startup_workspace
        from desktop_app.shell.window import MainWindow

        clean = AppPaths(self.base / 'legacy-workspace', self.base / 'legacy-bootstrap').ensure()
        backups = BackupManager(clean)
        self.assertTrue(_prepare_startup_workspace(clean, backups).legacy)
        self.assertFalse((clean.controls / 'analysis-recovery-v1.sqlite3').exists())
        jobs = create_job_manager(clean)
        window = MainWindow(clean, jobs, SettingsStore(clean.state / 'settings.json'), backups, services=_c_create_ui_services(_c_create_operation_ports()))
        window.timer.stop()
        window.automatic_backup_panel.timer.stop()
        try:
            from PySide6.QtWidgets import QPushButton

            self.assertTrue(window.findChild(QPushButton, 'create_demo').isEnabled())
            self.assertTrue(window.findChild(QPushButton, 'create_backup').isEnabled())
            self.assertTrue(window.findChild(QPushButton, 'restore_backup').isEnabled())
            self.assertEqual(window.analysis_recovery_notice.text(), '')
        finally:
            jobs.close()
            window.close()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
