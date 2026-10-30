"""TEST_ONLY proposed restart availability contract; NOT production safety.

The adapter below is deliberately confined to this test module. It exercises
real Qt widgets/controllers and existing spawned workers under a fixed proposed
conflict policy. It does not discover an orphan, authenticate a receipt, grant
reconciliation, or provide cross-process launch/restore serialization. Those
remain production integration gates. No service, helper or real AI is launched.

Run with the prepared cloud Qt interpreter, QT_QPA_PLATFORM=offscreen, and a
90-second outer timeout. Each actual worker wait is capped at 20 seconds.
"""

from __future__ import annotations

from contextlib import ExitStack, closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None

from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, RuntimeSafetyError, SettingsStore, WorkspaceLocator


def _destroy_owned_window(case, window):
    """Destroy only this fixture's native Qt tree after its close assertions."""
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from shiboken6 import isValid

    case.assertTrue(isValid(window), 'Fixture window must still be valid before explicit destruction')
    timers = window.findChildren(QTimer)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    case.assertFalse(isValid(window), 'Owned native window must be destroyed after fixture cleanup')
    for timer in timers:
        case.assertFalse(isValid(timer), 'Owned native timers must be destroyed with the fixture window')


def _offline_worker(*args, **kwargs):
    """Spawn-safe wrapper around the unchanged real worker, with network denied."""
    from quantlab.desktop_runtime import _job_worker

    with (
        patch('socket.create_connection', side_effect=AssertionError('TEST_ONLY: no network')),
        patch('http.client.HTTPSConnection', side_effect=AssertionError('TEST_ONLY: no HTTP')),
        patch('quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport', side_effect=AssertionError('TEST_ONLY: no provider')),
        patch('desktop_app.shell.main_window.analysis_provider_for', side_effect=AssertionError('TEST_ONLY: no analysis provider')),
    ):
        return _job_worker(*args, **kwargs)


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class _TestOnlyConflictPolicy:
    """Fixed test adapter, never imported by product code or accepted as proof.

    No mutex here is represented as production serialization: the eventual
    launch-registration/restore-promotion checks need one interprocess durable
    critical section, independently tested in the Windows protocol fixture.
    """

    BLOCKED = frozenset(
        {'ui_analysis_run', 'ui_analysis_reconcile', 'ui_backup_create', 'ui_backup_restore', 'ui_demo', 'ui_import', 'ui_refresh', 'ui_campaign'}
    )
    BUTTONS = ('run_candidate_analysis', 'create_backup', 'restore_backup', 'create_demo', 'import_data', 'refresh_data', 'run_campaign')

    def __init__(self, jobs, backups):
        self.unresolved = True
        self.jobs, self.backups = jobs, backups
        self.start_original = jobs.start
        self.recover_original = backups.recover
        self.claim_original = None
        self.dispatched = []
        self.denied = []

    def start(self, operation, payload):
        if self.unresolved and operation in self.BLOCKED:
            self.denied.append(operation)
            raise RuntimeSafetyError('TEST_ONLY unresolved analysis conflict')
        self.dispatched.append(operation)
        return self.start_original(operation, payload)

    def claim(self, *, quiescent):
        if self.unresolved:
            return None  # Before the original scheduler can consume its day.
        return self.claim_original(quiescent=quiescent)

    def recover(self):
        if self.unresolved:
            root = self.jobs.paths.root
            if any((root / name).exists() for name in ('state-v1.rollback', 'restore-transaction.json')):
                raise RuntimeSafetyError('TEST_ONLY ambiguous restore layout')
            return None  # Intact analysis-only workspace; no restore mutation.
        return self.recover_original()

    def mask_buttons(self, window):
        if not self.unresolved:
            return
        from PySide6.QtWidgets import QPushButton

        for name in self.BUTTONS:
            button = window.findChild(QPushButton, name)
            if button is not None:
                button.setEnabled(False)

    def observe_zero_for_contract_only(self):
        # Synthetic disposition only. This NEVER writes _quiesced_analysis,
        # authenticates a receipt, repairs a journal, or changes account state.
        self.unresolved = False


def _contract_window_type(policy):
    from desktop_app.shell.main_window import MainWindow

    class TestOnlyContractWindow(MainWindow):
        def _busy(self, active, *, refresh_recovery=False):
            super()._busy(active, refresh_recovery=refresh_recovery)
            policy.mask_buttons(self)

        def refresh_views(self):
            try:
                return super().refresh_views()
            finally:
                policy.mask_buttons(self)

    return TestOnlyContractWindow


@unittest.skipUnless(HAS_QT, 'Actual Qt required; fake widgets are not contract evidence')
class RestartAvailabilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='markauto-qt-restart-contract-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.paths = AppPaths(self.base / 'workspace', self.base / 'bootstrap').ensure()
        self._seed_synthetic_evidence()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in (
            'socket.create_connection',
            'http.client.HTTPSConnection',
            'quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport',
            'desktop_app.shell.main_window.analysis_provider_for',
        ):
            self.stack.enter_context(patch(target, side_effect=AssertionError('TEST_ONLY forbidden: ' + target)))
        self.stack.enter_context(patch('quantlab.desktop_runtime._job_worker', _offline_worker))
        self.jobs = JobManager(self.paths)
        self.backups = BackupManager(self.paths, self.jobs)
        self.policy = _TestOnlyConflictPolicy(self.jobs, self.backups)
        self.stack.enter_context(patch.object(self.jobs, 'start', self.policy.start))
        self.stack.enter_context(patch.object(self.backups, 'recover', self.policy.recover))
        Window = _contract_window_type(self.policy)
        self.window = Window(self.paths, self.jobs, SettingsStore(self.paths.state / 'settings.json'), self.backups)
        self.addCleanup(self._cleanup_window)
        self.window.timer.stop()
        self.panel = self.window.automatic_backup_panel
        self.panel.timer.stop()
        self.policy.claim_original = self.panel.scheduler.claim_due
        self.stack.enter_context(patch.object(self.panel.scheduler, 'claim_due', self.policy.claim))
        self.jobs.logging_enabled = False
        self.window.show()
        self.app.processEvents()
        self.protected = self._protected()

    def _seed_synthetic_evidence(self):
        from quantlab.core import canonical_json, content_hash
        from quantlab.reporting import save_dataset
        from tests.test_research_analysis import AnalysisWire, PROVENANCE, prepare, source
        from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
        import quantlab.assistant.adapters.chatgpt.provider as provider
        import quantlab.research_analysis as analysis

        self.data, state, self.campaign = source(self.paths.state / 'campaigns')
        self.dataset = self.paths.state / 'dataset.json'
        save_dataset(self.data, self.dataset)
        packet = prepare(self.campaign, self.data, state)
        AnalysisWire.requests = []
        AnalysisWire.failure = AnalysisWire.mutate = None
        with (
            patch.object(provider, 'implementation_provenance', return_value=PROVENANCE),
            patch.object(provider, 'PlanHTTPTransport', AnalysisWire),
            patch('http.client.HTTPSConnection', side_effect=AssertionError('No live fixture HTTP')),
        ):
            plan = analysis.make_analysis_plan(packet, model='fixture-model', registration='a' * 32, provider_implementation=PROVENANCE)
            reference = OAuthCredentialReference(str(self.paths.bootstrap), 'a' * 32)
            original = provider.analysis_provider(plan, reference, network_opt_in=True, included_usage_policy_confirmed=True)
            result = analysis.run_analysis(
                output_root=self.paths.state / 'analyses', plan=plan, provider=original, expected_analysis_id=plan['analysis_id'], user_confirmed=True
            )
            self.completed = result['record']
            self.completed_id = plan['analysis_id']
            pending = analysis.make_analysis_plan(packet, model='synthetic-pending-model', registration='a' * 32, provider_implementation=PROVENANCE)
            pending_provider = provider.analysis_provider(pending, reference)
            self.pending_id = pending['analysis_id']
            self.pending_folder = self.paths.state / 'analyses' / self.pending_id
            self.pending_folder.mkdir()
            record = {
                'schema_version': 1,
                'plan': pending,
                'provider_descriptor': pending_provider.provider_descriptor(),
                'status': 'running',
                'response': None,
                'response_hash': None,
                'receipt_snapshot': pending_provider.read_receipt_snapshot(),
                'real_model_status': 'not_verified',
            }
            analysis._save(self.pending_folder, record)
            request = analysis.analysis_request(pending)
            pending_provider._reserve(content_hash(request), len(canonical_json(request).encode()))
            (self.pending_folder / 'analysis.json').unlink()
            with closing(sqlite3.connect(self.pending_folder / 'analysis.lock.sqlite3')) as db, db:
                pass
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')  # Synthetic fixture connection must be closed.
        self.assertEqual(len(AnalysisWire.requests), 1, 'Only the synthetic saved fixture was generated')

    def _protected(self):
        return {
            'dataset': self.dataset.read_bytes(),
            'campaign': _snapshot(self.campaign),
            'analyses': _snapshot(self.paths.state / 'analyses'),
            'controls': _snapshot(self.paths.controls),
        }

    def _cleanup_window(self):
        self.window.timer.stop()
        self.panel.timer.stop()
        self.jobs.close()
        self.window._analysis_running = self.window._pending_analysis_reconcile = False
        self.window._analysis_launch = None
        # End the synthetic test policy only for teardown, never by disk/PID inference.
        self.policy.unresolved = False
        self.window.close()
        self.app.processEvents()
        self.assertFalse(self.jobs.active, 'Actual worker cleanup must complete')
        self.assertFalse(self.window.isVisible(), 'Fixture close must hide the owned window before destruction')
        _destroy_owned_window(self, self.window)

    def _click(self, name):
        from tests.test_desktop_ui import NativeDesktopTests

        NativeDesktopTests.click(self, name)

    def _wait_job(self):
        deadline = time.monotonic() + 20
        while self.jobs.active and time.monotonic() < deadline:
            self.app.processEvents()
            self.window.poll_jobs()
            time.sleep(0.01)
        self.window.poll_jobs()
        self.assertFalse(self.jobs.active, self.window.status.text())
        self.assertNotIn('失敗', self.window.status.text(), self.window.status.text())

    def _enable_backup(self):
        self.panel.enabled.setChecked(True)
        self.panel.directory.setText(str(self.base / 'archives'))
        self.panel.save()
        self.assertFalse(self.panel.paused, self.panel.status.text())

    def _assert_blocked_buttons(self):
        from PySide6.QtWidgets import QPushButton

        for name in self.policy.BUTTONS:
            button = self.window.findChild(QPushButton, name)
            self.assertIsNotNone(button, name)
            self.assertFalse(button.isEnabled(), name)

    def test_unresolved_saved_read_checkpoint_backtest_compare_survive_real_completion(self):
        w = self.window
        w.analysis_saved.setCurrentIndex(w.analysis_saved.findData(self.completed_id))
        self._click('read_candidate_analysis')
        self._wait_job()
        self.assertTrue(w.analysis_findings.toPlainText())
        self.assertEqual(w.analysis_saved.currentData(), self.completed_id)
        dispatched = list(self.policy.dispatched)
        w.analysis_saved.setCurrentIndex(w.analysis_saved.findData(self.pending_id))
        self.assertIn('中斷檢查點', w.analysis_checkpoint_notice.text())
        self._click('read_candidate_analysis')
        self.assertEqual(self.policy.dispatched, dispatched)
        self.assertEqual(w.analysis_findings.toPlainText(), '')
        self.assertFalse((self.pending_folder / 'analysis.json').exists())
        self._click('run_backtest')
        self._wait_job()
        reports = list((self.paths.state / 'reports').glob('*/result.json'))
        self.assertEqual(len(reports), 1)
        self.assertTrue(w.plot.values)
        w.comparison_list.item(0).setSelected(True)
        self._click('compare_results')
        self._wait_job()
        self.assertIn('result_hash', w.comparison.toPlainText())
        self.assertEqual(self.policy.dispatched, ['ui_analysis_read', 'ui_backtest', 'ui_compare'])
        self._assert_blocked_buttons()
        self.assertEqual(self._protected(), self.protected)
        self.assertIsNone(self.jobs._quiesced_analysis)

    def test_conflicts_denied_before_claim_after_refresh_busy_and_freeze_callbacks(self):
        w = self.window
        self._enable_backup()
        scheduler_before = self.panel.scheduler.path.read_bytes()
        for callback in (lambda: w._busy(False), w.refresh_views, w.poll_jobs, lambda: w.freeze_paper('TEST_ONLY clock/freeze callback')):
            with self.subTest(callback=callback):
                w._analysis_preview = {'receipt_snapshot': {'receipts': []}}
                callback()
                self._assert_blocked_buttons()
                self.assertTrue(w.run_button.isEnabled())
        with (
            patch.object(self.policy, 'claim_original', wraps=self.policy.claim_original) as claim,
            patch.object(self.policy, 'start_original', wraps=self.policy.start_original) as start,
        ):
            self.panel.tick()  # Real controller calls the guarded claim boundary.
            claim.assert_not_called()
            start.assert_not_called()
            for operation in sorted(self.policy.BLOCKED):
                with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeSafetyError, 'TEST_ONLY unresolved'):
                    self.jobs.start(operation, {})  # Service boundary, not just disabled buttons.
            start.assert_not_called()
        self.assertEqual(self.panel.scheduler.path.read_bytes(), scheduler_before)
        self.assertIsNone(self.panel.scheduler.load()['last_attempt_day'])
        self.assertIsNone(self.panel.archive)
        self.assertFalse((self.base / 'archives').exists())
        self.assertEqual(self._protected(), self.protected)

    def test_positive_stop_disposition_allows_backup_without_journal_or_reconcile_authority(self):
        # A known-stopped launch must not retain the live-tree conflict merely
        # because it died before writing a journal. No stop receipt is forged.
        (self.pending_folder / 'analysis.sqlite3').unlink()
        self.policy.observe_zero_for_contract_only()
        self.assertIsNone(self.jobs._quiesced_analysis)
        with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
            with self.assertRaisesRegex(RuntimeSafetyError, 'subtree stop proof'):
                self.jobs.start('ui_analysis_reconcile', {'analysis_id': self.pending_id, 'registration': 'a' * 32, 'stopped_job_id': 'not-an-original-job'})
            spawn.assert_not_called()
        controls = _snapshot(self.paths.controls)
        self._enable_backup()
        self.panel.tick()
        self._wait_job()
        state = self.panel.scheduler.load()
        self.assertEqual(state['last_status'], 'success')
        self.assertTrue(Path(state['last_archive']).is_file())
        self.assertFalse((self.pending_folder / 'analysis.sqlite3').exists())
        self.assertFalse((self.pending_folder / 'analysis.json').exists())
        self.assertEqual(_snapshot(self.paths.controls), controls)
        self.assertIsNone(self.jobs._quiesced_analysis)

    def test_ambiguous_restore_layout_blocks_freeze_without_swap_or_marker_clear(self):
        rollback = self.paths.root / 'state-v1.rollback'
        rollback.mkdir()
        (rollback / 'synthetic-original').write_bytes(b'preserve')
        journal = self.paths.root / 'restore-transaction.json'
        journal.write_text(json.dumps({'id': 'b' * 32, 'phase': 'prepared'}))
        before = _snapshot(self.paths.root)
        with patch.object(self.policy, 'recover_original', wraps=self.policy.recover_original) as recover:
            with self.assertRaisesRegex(RuntimeSafetyError, 'TEST_ONLY ambiguous'):
                self.window.freeze_paper('TEST_ONLY ambiguous restore')
            recover.assert_not_called()
        self.assertEqual(_snapshot(self.paths.root), before)
        self.assertTrue(self.policy.unresolved)
        # Remove only fixture-created artifacts so ordinary test teardown does
        # not perform the very recovery this contract forbids while unresolved.
        journal.unlink()
        (rollback / 'synthetic-original').unlink()
        rollback.rmdir()

    def test_other_workspace_non_ai_use_preserves_original_controls_and_state(self):
        from desktop_app.shell.main_window import MainWindow
        from quantlab.reporting import save_dataset

        before = _snapshot(self.paths.root)
        controls = _snapshot(self.paths.controls)
        locator = WorkspaceLocator(self.paths.bootstrap)
        locator.configure(self.base / 'other-workspace')
        other = locator.load(probe=False).ensure()
        self.assertEqual(other.controls, self.paths.controls)
        self.assertEqual(other.credentials, self.paths.credentials)
        save_dataset(self.data, other.state / 'dataset.json')
        jobs = JobManager(other)
        window = MainWindow(other, jobs, SettingsStore(other.state / 'settings.json'), BackupManager(other, jobs))
        window.timer.stop()
        window.automatic_backup_panel.timer.stop()
        try:
            self.assertTrue(window.run_button.isEnabled())
            window.run_backtest()
            deadline = time.monotonic() + 20
            while jobs.active and time.monotonic() < deadline:
                self.app.processEvents()
                window.poll_jobs()
                time.sleep(0.01)
            window.poll_jobs()
            self.assertFalse(jobs.active, window.status.text())
            self.assertNotIn('失敗', window.status.text())
            self.assertEqual(len(list((other.state / 'reports').glob('*/result.json'))), 1)
        finally:
            jobs.close()
            window.close()
            self.app.processEvents()
        self.assertEqual(_snapshot(self.paths.root), before)
        self.assertEqual(_snapshot(self.paths.controls), controls)
        self.assertTrue(self.policy.unresolved, 'Workspace switching never clears the original conflict')


if __name__ == '__main__':
    unittest.main()
