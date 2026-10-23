"""Comparison, immutable selection and saved candidate analysis presentation."""

from desktop_strings import ui_text
from pathlib import Path
from quantlab.desktop_errors import error_message
from quantlab.core import ValidationError, canonical_json, content_hash
from quantlab.reporting import saved_analysis_entries
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QListWidget,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QAbstractItemView,
    QHBoxLayout,
)
from .compare_table import SavedResultsTable, SideBySideTable
from .bindings import PageContext
from .design import section
from .palette_commands import page_index

ANALYSIS_NOTICE = ui_text('ui.labels.recalculated_evidence')
ANALYSIS_WARNING = ui_text('ui.labels.unverified_ai_advice')
ANALYSIS_CHECKPOINT_STATUS = ui_text('ui.labels.interrupted_checkpoint')
ANALYSIS_CHECKPOINT_NOTICE = ui_text('ui.labels.missing_result_export').format(ANALYSIS_CHECKPOINT_STATUS)


class ComparePage(PageContext, QWidget):
    def __init__(self, host, analysis_layout):
        super().__init__()
        self.setup_context(host)
        layout = self.host.mount_page(self, ui_text('ui.compare_page.title'))
        hint = QLabel(ui_text('ui.compare_page.comparison_hint'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.comparison_list = QListWidget(self)
        self.comparison_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.comparison_list.hide()
        self.saved_results_table = SavedResultsTable(self.comparison_list)
        self.saved_results_table.setMaximumHeight(180)
        layout.addWidget(self.saved_results_table)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self._button(
            actions,
            ui_text('ui.compare_page.compare_selected'),
            'compare_results',
            lambda: self.start_job('ui_compare', {'results': [i.data(Qt.ItemDataRole.UserRole) for i in self.comparison_list.selectedItems()]}),
            role='primary',
        )
        self._button(actions, ui_text('redesign.compare.back'), 'compare_to_backtest', self.return_to_results)
        self.comparison = QPlainTextEdit()
        self.comparison.setReadOnly(True)
        comparison_details = section(layout, 'redesign.compare.details', key='redesign_compare_details', state=self.state)
        comparison_details.addWidget(self.comparison)
        self.comparison_table = SideBySideTable(self.saved_results_table)
        self.comparison_table.setMaximumHeight(160)
        layout.addWidget(self.comparison_table)
        # Deferred to keep comparison presentation independent of canvas construction.
        from .compare_equity import attach_overlay

        attach_overlay(self, comparison_details)
        selection = section(layout, 'redesign.compare.selection', expanded=True, key='redesign_compare_selection', state=self.state)
        selection_actions = QHBoxLayout()
        selection.addLayout(selection_actions)
        self.select_button = self._button(selection_actions, ui_text('ui.compare_page.activate_strategy'), 'select_strategy', self.select_strategy)
        self._button(selection_actions, ui_text('ui.compare_page.deactivate_strategy'), 'disable_strategy', lambda: self.start_job('ui_disable', {}))
        self.selection_status = QLabel()
        self.selection_status.setWordWrap(True)
        selection.addWidget(self.selection_status)
        self._analysis_section(analysis_layout)

    def return_to_results(self):
        index = page_index(self.state, 'backtest')
        if index >= 0:
            self.state.navigation.setCurrentRow(index)

    def _analysis_section(self, layout):
        title = QLabel(ui_text('ui.analysis_section.title'))
        layout.addWidget(title)
        warning = QLabel(ANALYSIS_WARNING + '\n' + ANALYSIS_NOTICE)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.analysis_candidates = QListWidget()
        self.analysis_candidates.setObjectName('analysis_candidates')
        self.analysis_candidates.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        layout.addWidget(self.analysis_candidates)
        self.analysis_original = QLineEdit()
        self.analysis_original.setReadOnly(True)
        self.analysis_original.setObjectName('analysis_original_dataset')
        self.analysis_original.setPlaceholderText(ui_text('ui.analysis_section.original_required'))
        layout.addWidget(self.analysis_original)
        self._button(layout, ui_text('ui.analysis_section.browse_original'), 'pick_analysis_original', self.pick_analysis_original)
        self._button(layout, ui_text('ui.analysis_section.preview_candidate'), 'preview_candidate_analysis', lambda: self.preview_analysis('critique'))
        self._button(layout, ui_text('ui.analysis_section.preview_comparison'), 'preview_candidate_comparison', lambda: self.preview_analysis('compare'))
        self.analysis_preview = QPlainTextEdit()
        self.analysis_preview.setReadOnly(True)
        self.analysis_preview.setObjectName('analysis_preview')
        layout.addWidget(self.analysis_preview)
        self.analysis_evidence = QPlainTextEdit()
        self.analysis_evidence.setReadOnly(True)
        self.analysis_evidence.setObjectName('analysis_evidence')
        self._advanced(layout).addWidget(self.analysis_evidence)
        self.analysis_consent = QCheckBox(ui_text('ui.analysis_section.consent'))
        self.analysis_consent.setObjectName('analysis_one_call_consent')
        layout.addWidget(self.analysis_consent)
        note = QLabel(ui_text('ui.analysis_section.shared_connection_hint'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.analysis_start = self._button(layout, ui_text('ui.analysis_section.send'), 'run_candidate_analysis', self.run_analysis)
        self.analysis_start.setEnabled(False)
        self.analysis_saved = QComboBox()
        self.analysis_saved.setObjectName('analysis_saved')
        layout.addWidget(self.analysis_saved)
        self._analysis_checkpoint_ids = set()
        self.analysis_checkpoint_notice = QLabel()
        self.analysis_checkpoint_notice.setObjectName('analysis_checkpoint_notice')
        self.analysis_checkpoint_notice.setWordWrap(True)
        layout.addWidget(self.analysis_checkpoint_notice)
        self._button(layout, ui_text('ui.analysis_section.read_saved'), 'read_candidate_analysis', self.read_analysis)
        self.analysis_recovery_notice = QLabel()
        self.analysis_recovery_notice.setWordWrap(True)
        self.analysis_recovery_notice.setObjectName('analysis_recovery_notice')
        layout.addWidget(self.analysis_recovery_notice)
        self.analysis_recover = self._button(layout, ui_text('ui.analysis_section.reconcile_saved'), 'reconcile_saved_analysis', self.reconcile_saved_analysis)
        self.analysis_recover.setEnabled(False)
        self.analysis_findings = QPlainTextEdit()
        self.analysis_findings.setReadOnly(True)
        self.analysis_findings.setObjectName('analysis_findings')
        layout.addWidget(self.analysis_findings)
        self.analysis_saved.currentIndexChanged.connect(self._analysis_saved_changed)
        self.analysis_candidates.itemSelectionChanged.connect(self._invalidate_analysis_preview)
        self.analysis_original.textChanged.connect(self._invalidate_analysis_preview)

    def _invalidate_analysis_preview(self, *args):
        self._analysis_preview = None
        self._analysis_request_key = None
        if hasattr(self, 'analysis_consent'):
            self.analysis_consent.setChecked(False)
            self.analysis_start.setEnabled(False)
            self.analysis_preview.clear()
            self.analysis_evidence.clear()

    def pick_analysis_original(self):
        name, _ = self.host.open_file(ui_text('ui.pick_analysis_original.dialog_title'), '', 'JSON (*.json)')
        if not name:
            return
        if '://' in name or name.startswith(('//', chr(92) * 2)) or not Path(name).is_absolute():
            raise ValidationError(ui_text('ui.pick_analysis_original.absolute_path_required'))
        path = Path(name).resolve(strict=True)
        if not path.is_file():
            raise ValidationError(ui_text('ui.pick_analysis_original.original_required'))
        self.analysis_original.setText(str(path))
        self.form_feedback(self.analysis_original, ui_text('ui.pick_analysis_original.original_selected'))

    def _analysis_request(self, task):
        from quantlab.desktop_runtime import validate_analysis_request

        refs = [item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        if not refs or len({ref['campaign_folder'] for ref in refs}) != 1:
            raise ValidationError(ui_text('ui.analysis_request.same_research_required'))
        c = self.chatgpt_controller
        p = self.chatgpt_panel
        if c.busy or c.state != 'plan_ready' or not c.active_registration or p.model.currentData() not in c.models:
            raise ValidationError(ui_text('ui.analysis_request.connection_required'))
        request = {
            'campaign_reference': refs[0]['campaign_folder'],
            'original_dataset': {'kind': 'local_dataset_file', 'path': self.analysis_original.text()},
            'attempt_ids': sorted(ref['attempt_id'] for ref in refs),
            'task': task,
            'registration': c.active_registration,
            'model': p.model.currentData(),
            'timeout_seconds': p.timeout.value(),
        }
        validate_analysis_request(request)
        return request

    def preview_analysis(self, task):
        request = self._analysis_request(task)
        self._invalidate_analysis_preview()
        self._analysis_request_key = content_hash(request)
        self.start_job('ui_analysis_preview', {'request': request})

    def run_analysis(self):
        from desktop_chatgpt_ui import SubscriptionOptions

        preview = self._analysis_preview
        if preview is None or not self.analysis_consent.isChecked():
            raise ValidationError(ui_text('ui.run_analysis.preview_consent_required'))
        plan = preview['plan']
        request = self._analysis_request(plan['binding']['packet']['context']['task'])
        if content_hash(request) != self._analysis_request_key:
            raise ValidationError(ui_text('ui.run_analysis.selection_changed'))
        c = self.chatgpt_controller
        p = self.chatgpt_panel
        if not c.account_status_known or c.account_paused or c.account_pending or preview['receipt_snapshot']['receipts']:
            raise ValidationError(ui_text('ui.run_analysis.budget_consumed'))
        if (
            not p.consent.isChecked()
            or not p.included_usage_only.isChecked()
            or p._included_usage_registration != request['registration']
            or p.account.currentData() != request['registration']
        ):
            raise ValidationError(ui_text('ui.run_analysis.usage_consent_required'))
        SubscriptionOptions(request['registration'], request['model'], 1, request['timeout_seconds'], network_opt_in=True, included_usage_policy_confirmed=True)
        import copy

        payload = {
            'request': request,
            'approved_plan': copy.deepcopy(plan),
            'expected_analysis_id': plan['analysis_id'],
            'expected_plan_hash': content_hash(plan),
            'user_confirmed': True,
            'network_opt_in': True,
            'included_usage_policy_confirmed': True,
        }
        self.analysis_consent.setChecked(False)
        p.consent.setChecked(False)
        p._reset_included_usage()
        job_id = self.start_job('ui_analysis_run', payload)
        self._analysis_launch = {'analysis_id': plan['analysis_id'], 'registration': request['registration'], 'stopped_job_id': job_id}
        self._analysis_running = True
        self._analysis_preview = None
        c.invalidate_campaign_usage()
        self._plan_usage_binding = None

    def read_analysis(self):
        reference = self.analysis_saved.currentData()
        if not reference:
            raise ValidationError(ui_text('ui.read_analysis.saved_analysis_required'))
        self._invalidate_analysis_preview()
        if reference in self._analysis_checkpoint_ids:
            self._analysis_saved_changed()
            return
        self.start_job('ui_analysis_read', {'analysis_id': reference})

    def _analysis_saved_changed(self, *args):
        self.analysis_checkpoint_notice.clear()
        if self.analysis_saved.currentData() in self._analysis_checkpoint_ids:
            self._invalidate_analysis_preview()
            self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText(ANALYSIS_CHECKPOINT_NOTICE)
            self.status.setText(ANALYSIS_CHECKPOINT_STATUS)
        elif self.status.text() == ANALYSIS_CHECKPOINT_STATUS:
            self.status.setText(ui_text('ui.analysis_saved_changed.read_saved_hint'))
        self._refresh_recovery_controls(force=True)

    def _selected_recovery_launch(self, disposition=None):
        from quantlab.analysis_recovery import inspect_recovery, validate_stop_receipt, supports_durable_recovery, RecoveryError

        if not supports_durable_recovery():
            return None
        reference = self.analysis_saved.currentData()
        if not reference:
            return None
        display_only = disposition is not None
        disposition = disposition or inspect_recovery(self.paths)
        for launch in disposition.workspace_stopped:
            if launch['analysis_id'] != reference:
                continue
            if display_only:
                return launch  # Current validated snapshot; presentation only.
            try:
                return validate_stop_receipt(self.paths, launch['job_id'])
            except RecoveryError:
                return None
        return None

    def reconcile_saved_analysis(self):
        if self.jobs.active:
            raise ValidationError(ui_text('ui.reconcile_saved_analysis.job_busy'))
        launch = self._selected_recovery_launch()
        if launch is None:
            raise ValidationError(ui_text('ui.reconcile_saved_analysis.stop_record_missing'))
        self._invalidate_analysis_preview()
        self.start_job(
            'ui_analysis_reconcile', {'analysis_id': launch['analysis_id'], 'registration': launch['registration'], 'recovery_launch_id': launch['job_id']}
        )

    def _recovery_display_fingerprint(self):
        # Metadata is presentation invalidation only, never stop/admission proof.
        # lstat does not follow a newly substituted link or open its target.
        bootstrap = self.paths.bootstrap or self.paths.root
        database = self.paths.controls / 'analysis-recovery-v1.sqlite3'
        result = []
        for path in (
            bootstrap,
            self.paths.controls,
            self.paths.root,
            bootstrap / '.analysis-recovery-v1.json',
            database,
            Path(str(database) + '-journal'),
            Path(str(database) + '-wal'),
            Path(str(database) + '-shm'),
        ):
            try:
                info = path.lstat()
                result.append((info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            except OSError as exc:
                result.append((type(exc).__name__, exc.errno))
        return tuple(result)

    def _refresh_recovery_controls(self, *, force=False):
        """Cache presentation only; every dispatch and explicit repair revalidates."""
        if not hasattr(self, 'analysis_recover'):
            return
        import time
        from quantlab.analysis_recovery import inspect_recovery, RecoveryError

        now = time.monotonic()
        cached = getattr(self, '_recovery_display', None)
        refresh = force or cached is None
        if not refresh and now - cached[0] >= 2:
            refresh = self._recovery_display_fingerprint() != self._recovery_display_metadata
            if not refresh:
                cached = (now, *cached[1:])
                self._recovery_display = cached
        if refresh:
            self._recovery_display_metadata = self._recovery_display_fingerprint()
            failed = False
            launch = None
            try:
                disposition = inspect_recovery(self.paths)
                source_blocked = bool(disposition.unresolved)
                workspace_blocked = bool(disposition.workspace_unresolved)
                if not self.jobs.active:
                    launch = self._selected_recovery_launch(disposition)
            except (RecoveryError, OSError):
                failed = True
                source_blocked = workspace_blocked = True
            if failed:
                message = ui_text('ui.refresh_recovery_controls.stop_record_unverifiable')
            elif workspace_blocked:
                message = ui_text('ui.refresh_recovery_controls.analysis_stop_unconfirmed')
            elif source_blocked:
                message = ui_text('ui.refresh_recovery_controls.other_workspace_busy')
            elif launch is not None:
                message = ui_text('ui.refresh_recovery_controls.stop_record_available')
            else:
                message = ''
            cached = (now, source_blocked, workspace_blocked, launch is not None, message)
            self._recovery_display = cached
        _, source_blocked, workspace_blocked, eligible, message = cached
        # Reapply cached restrictions even when _busy(False) just reset buttons.
        if source_blocked:
            for name in (
                'create_demo',
                'import_data',
                'refresh_data',
                'market_refresh',
                'import_market_file',
                'import_market_history',
                'run_campaign',
                'run_walk_forward',
                'preview_candidate_analysis',
                'preview_candidate_comparison',
                'run_candidate_analysis',
                'restore_backup',
            ):
                button = self.host.find_child(QPushButton, name)
                if button is not None:
                    button.setEnabled(False)
        if workspace_blocked:
            button = self.host.find_child(QPushButton, 'create_backup')
            if button is not None:
                button.setEnabled(False)
        self.analysis_recover.setEnabled(eligible and not self.jobs.active)
        self.analysis_recovery_notice.setText(message)

    def _analysis_event(self, event):
        if self.last_operation not in ('ui_analysis_preview', 'ui_analysis_run', 'ui_analysis_read', 'ui_analysis_reconcile'):
            return False
        kind = event.get('type')
        if kind == 'progress':
            self.status.setText(str(event.get('message', ui_text('ui.analysis_event.running'))))
            return True
        if kind not in ('result', 'error', 'failed', 'cancelled', 'canceled'):
            return True
        operation = self.last_operation
        self.record_event(operation, kind)
        if operation == 'ui_analysis_run':
            self._analysis_running = False
            self._pending_analysis_reconcile = self._analysis_launch is not None
            self.chatgpt_controller.account_status_known = False
            self.chatgpt_controller.invalidate_campaign_usage()
            self._pending_usage_refresh = True
        if kind == 'result':
            result = event['result']
            if operation == 'ui_analysis_preview':
                plan = result['plan']
                task = plan['binding']['packet']['context']['task']
                if content_hash(self._analysis_request(task)) != self._analysis_request_key:
                    self._invalidate_analysis_preview()
                    self.status.setText(ui_text('ui.analysis_event.selection_changed'))
                    return True
                if result['analysis_id'] != plan['analysis_id']:
                    raise ValidationError(ui_text('ui.analysis_event.preview_id_mismatch'))
                self._analysis_preview = result
                self.chatgpt_controller.set_account_status(plan['binding']['registration'], result['account_status'])
                self.analysis_preview.setPlainText(self.host.callbacks['analysis_preview_text'](plan))
                self.analysis_evidence.setPlainText(canonical_json(plan['binding']['packet']['context']))
                self.analysis_start.setEnabled(not result['receipt_snapshot']['receipts'])
                self._refresh_recovery_controls(force=True)
                self.status.setText(ui_text('ui.analysis_event.preview_local_only'))
            else:
                self._refresh_analysis_saved(preferred_reference=result['analysis_id'])
                if result['analysis_id'] in self._analysis_checkpoint_ids:
                    return True
                if self.analysis_saved.currentData() != result['analysis_id']:
                    self.analysis_findings.clear()
                    self.analysis_evidence.clear()
                    self.status.setText(ui_text('ui.analysis_event.saved_result_unavailable'))
                    return True
                self.analysis_findings.setPlainText(self.host.callbacks['analysis_record_text'](result['record']))
                self.analysis_evidence.setPlainText(canonical_json(result['record']['plan']['binding']['packet']['context']))
                self.status.setText(ui_text('ui.analysis_event.saved_result_loaded'))
        else:
            self.analysis_consent.setChecked(False)
            self.status.setText(error_message('operation_failed'))
        return True

    def _refresh_analysis_saved(self, *, preferred_reference=None):
        old = preferred_reference or self.analysis_saved.currentData()
        failed = False
        try:
            entries = self.host.callbacks['saved_analysis_entries'](self.root / 'analyses')
        except (OSError, ValidationError):
            entries = ()
            failed = True
        self._analysis_checkpoint_ids = {name for name, checkpoint in entries if checkpoint}
        blocked = self.analysis_saved.blockSignals(True)
        try:
            self.analysis_saved.clear()
            for name, checkpoint in entries:
                label = ANALYSIS_CHECKPOINT_STATUS + ' · ' + name if checkpoint else name
                self.analysis_saved.addItem(label, name)
            index = self.analysis_saved.findData(old)
            if index >= 0:
                self.analysis_saved.setCurrentIndex(index)
        finally:
            self.analysis_saved.blockSignals(blocked)
        self._analysis_saved_changed()
        if failed:
            self._invalidate_analysis_preview()
            self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText(ui_text('ui.refresh_analysis_saved.listing_unsafe'))

    def select_strategy(self):
        path = self.result_choice.currentData()
        if not path:
            raise ValidationError(ui_text('ui.select_strategy.result_required'))
        self.start_job('ui_select', {'result': path})
