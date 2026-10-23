from pathlib import Path
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPlainTextEdit, QLineEdit, QCheckBox, QFormLayout, QGroupBox, QFileDialog
from desktop_strings import ui_text
from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.reporting import write_json
from quantlab.desktop_errors import error_message
from desktop_forms import StrategyForm, CampaignForm, WalkForwardForm, ResultTable, CandidateSummaryCard
from .host import PageHost
from .strategy_tabs import strategy_tabs, candidate_analysis_layout


class StrategyPage(QWidget):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = host.state
        from quantlab.strategies import builtin_strategies

        layout = self.host.mount_page(self, ui_text('ui.strategy_page.title'))
        self.tabs, (layout, research, walk_forward) = strategy_tabs(layout)
        self.chatgpt_sign_in_entry = self.host.button(layout, ui_text('ui.strategy_page.chatgpt_sign_in'), 'chatgpt_sign_in_entry', self.host.show_sign_in)
        self.idea_dialog = None
        self.idea_research_entry = self.host.button(layout, ui_text('idea.entry_button'), 'idea_research_entry', self.open_idea_research)
        self.connection_status = QLabel(ui_text('settings.connection_hint'))
        layout.addWidget(self.connection_status)
        self.state.chatgpt_connection_status = self.connection_status
        layout.addWidget(QLabel(ui_text('ui.strategy_page.bounded_families_hint')))
        self.strategy_form = StrategyForm()
        layout.addWidget(self.strategy_form)
        advanced = self.host.advanced(layout)
        self.family = QComboBox()
        self.family.addItems([s.family for s in builtin_strategies()])
        advanced.addWidget(self.family)
        self.parameters = self.host.text(advanced, ui_text('ui.strategy_page.strategy_json'), '{}', True)
        self.strategy_detail = QPlainTextEdit()
        self.strategy_detail.setReadOnly(True)
        advanced.addWidget(self.strategy_detail)
        self.family.currentIndexChanged.connect(self._family_changed)
        self._family_changed()
        # Keep the legacy section toggle identity and preference key. The wizard
        # is always available; expanding an outer section is no longer required.
        self.host.advanced(walk_forward, ui_text('ui.strategy_page.walk_forward_advanced'))
        list(self.state._section_toggles.values())[-1].hide()
        self._walk_forward_section(walk_forward)
        research.addWidget(QLabel(ui_text('ui.strategy_page.fixture_disclaimer')))
        self.strategy_form.family.currentIndexChanged.connect(lambda: self.family.setCurrentIndex(self.strategy_form.family.currentIndex()))
        research_parameters = self.host.advanced(research, ui_text('ui.strategy_page.research_advanced'))
        self.campaign_form = CampaignForm()
        research_parameters.addWidget(self.campaign_form)
        self.campaign_config = self.host.text(research_parameters, ui_text('ui.strategy_page.research_json'), '', True)
        self.host.remember(self.campaign_config)
        self.provider_mode = QComboBox()
        self.provider_mode.addItem(ui_text('ui.strategy_page.chatgpt_source'), 'chatgpt_plan')
        self.provider_mode.addItem(ui_text('ui.strategy_page.fixture_source'), 'fixture')
        self.provider_mode.addItem(ui_text('ui.strategy_page.manual_source'), 'manual')
        research.addWidget(self.provider_mode)
        manual = QWidget()
        manual_layout = QVBoxLayout(manual)
        research.addWidget(manual)
        manual.hide()
        self.provider_mode.currentIndexChanged.connect(lambda: manual.setVisible(self.provider_mode.currentData() == 'manual'))
        self.manual_path = self.host.text(manual_layout, ui_text('ui.strategy_page.manual_response_path'))
        self.host.button(
            manual_layout, ui_text('ui.strategy_page.browse_manual_response'), 'browse_manual_response', lambda: self.host.browse(self.manual_path)
        )
        self.manual_response = self.host.text(manual_layout, ui_text('ui.strategy_page.paste_manual_response'), '', True)
        self.host.button(manual_layout, ui_text('ui.strategy_page.export_manual_request'), 'export_manual_request', self.export_manual_request)
        self.host.button(research, ui_text('ui.strategy_page.reconcile_request_record'), 'chatgpt_campaign_usage', self.host.inspect_plan_usage)
        self.host.button(research, ui_text('ui.strategy_page.generate_reopen'), 'run_campaign', self.run_campaign, role='primary')
        self.candidate_choice = QComboBox()
        self.candidate_choice.setObjectName('candidate_choice')
        self.candidate_choice.currentIndexChanged.connect(self.inspect_candidate)
        research.addWidget(self.candidate_choice)
        self.candidate_detail = QPlainTextEdit()
        self.candidate_detail.setReadOnly(True)
        research_parameters.addWidget(self.candidate_detail)
        evidence = self.host.advanced(research, ui_text('ui.strategy_page.candidate_history_advanced'))
        self.candidate_card = CandidateSummaryCard()
        evidence.addWidget(self.candidate_card)
        self.use_candidate_button = self.host.button(research, ui_text('ui.strategy_page.use_candidate'), 'use_candidate', self.use_candidate)
        self.host.button(layout, ui_text('ui.strategy_page.use_builtin'), 'use_builtin', self.use_builtin)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        research_parameters.addWidget(self.history)
        self.history_table = ResultTable()
        evidence.addWidget(self.history_table)
        evidence.addWidget(QLabel(ui_text('ui.strategy_page.saved_evaluations')))
        self.evaluation_table = ResultTable()
        evidence.addWidget(self.evaluation_table)
        self.analysis_layout = candidate_analysis_layout(research)

    def _walk_forward_section(self, layout):
        section = QGroupBox(ui_text('ui.walk_forward_section.title'))
        content = QVBoxLayout(section)
        layout.addWidget(section)
        self.walk_forward_form = WalkForwardForm()
        content.addWidget(self.walk_forward_form)
        self.walk_forward_saved_controls = QWidget()
        saved = QFormLayout(self.walk_forward_saved_controls)
        self.walk_forward_campaign = QComboBox()
        self.walk_forward_campaign.setObjectName('walk_forward_campaign')
        self.walk_forward_campaign.addItem(ui_text('ui.walk_forward_section.saved_research_placeholder'), None)
        saved.addRow(ui_text('ui.walk_forward_section.source_research'), self.walk_forward_campaign)
        self.walk_forward_original = QLineEdit()
        self.walk_forward_original.setReadOnly(True)
        self.walk_forward_original.setObjectName('walk_forward_original_dataset')
        self.walk_forward_original.setPlaceholderText(ui_text('ui.walk_forward_section.original_file_hint'))
        saved.addRow(ui_text('ui.walk_forward_section.original_file'), self.walk_forward_original)
        self.host.button(saved, ui_text('ui.walk_forward_section.browse_original'), 'pick_walk_forward_original', self.pick_walk_forward_original)
        notice = QLabel(ui_text('ui.walk_forward_section.original_data_requirement'))
        notice.setWordWrap(True)
        saved.addRow(notice)
        content.addWidget(self.walk_forward_saved_controls)
        self.walk_forward_saved_controls.setEnabled(False)
        self.host.button(content, ui_text('ui.walk_forward_section.preview'), 'preview_walk_forward', self.preview_walk_forward)
        self.walk_forward_preview = QPlainTextEdit()
        self.walk_forward_preview.setReadOnly(True)
        self.walk_forward_preview.setObjectName('walk_forward_preview')
        self.walk_forward_preview.setMinimumHeight(410)
        content.addWidget(self.walk_forward_preview)
        self.walk_forward_advanced_group = QGroupBox(ui_text('ui.walk_forward_section.advanced_evidence'))
        self.walk_forward_advanced_group.setCheckable(True)
        self.walk_forward_advanced_group.setChecked(False)
        self.state._section_toggles['strategy:walk_forward_evidence'] = self.walk_forward_advanced_group
        self.walk_forward_advanced_group.toggled.connect(lambda checked: self.host.safe(self.host.save_sections))
        advanced = QVBoxLayout(self.walk_forward_advanced_group)
        self.walk_forward_advanced = QPlainTextEdit()
        self.walk_forward_advanced.setReadOnly(True)
        self.walk_forward_advanced.setObjectName('walk_forward_advanced')
        self.walk_forward_advanced.hide()
        advanced.addWidget(self.walk_forward_advanced)
        self.walk_forward_advanced_group.toggled.connect(self.walk_forward_advanced.setVisible)
        content.addWidget(self.walk_forward_advanced_group)
        self.walk_forward_consent = QCheckBox(ui_text('ui.walk_forward_section.irreversible_consent'))
        self.walk_forward_consent.setObjectName('walk_forward_consent')
        content.addWidget(self.walk_forward_consent)
        self.walk_forward_start = self.host.button(content, ui_text('ui.walk_forward_section.run'), 'run_walk_forward', self.run_walk_forward)
        self.walk_forward_choice = QComboBox()
        self.walk_forward_choice.setObjectName('walk_forward_choice')
        content.addWidget(self.walk_forward_choice)
        self.host.button(content, ui_text('ui.walk_forward_section.read_saved'), 'read_walk_forward', self.read_walk_forward)
        self.walk_forward_status = QLabel(ui_text('ui.walk_forward_section.no_preview'))
        self.walk_forward_status.setWordWrap(True)
        content.addWidget(self.walk_forward_status)
        from .result_widgets import ResultTable as SortableResultTable
        from .result_panels import WalkForwardResults

        self.walk_forward_results = SortableResultTable()
        content.addWidget(self.walk_forward_results)
        self.result_panel = WalkForwardResults()
        self.result_panel.scenario_host = self.host
        self.result_panel.scenario_state = self.state
        from .wf_wizard import WalkForwardWizard

        self.wf_wizard = WalkForwardWizard(self, content)

    def _connect_walk_forward_inputs(self):
        for form in (self.walk_forward_form, self.state.backtest_form):
            for field in form.fields.values():
                signal = field.currentIndexChanged if isinstance(field, QComboBox) else field.textChanged
                signal.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_form.fields['pool_origin'].currentIndexChanged.connect(self._walk_forward_origin_changed)
        self.walk_forward_campaign.currentIndexChanged.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_original.textChanged.connect(self._invalidate_walk_forward_preview)
        self.state.backtest_form.expiries.table.itemChanged.connect(self._invalidate_walk_forward_preview)
        model = self.state.backtest_form.expiries.table.model()
        model.rowsInserted.connect(self._invalidate_walk_forward_preview)
        model.rowsRemoved.connect(self._invalidate_walk_forward_preview)
        self.state.config.textChanged.connect(self._invalidate_walk_forward_preview)

    def _walk_forward_origin_changed(self, *args):
        saved = self.walk_forward_form.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        self.walk_forward_saved_controls.setEnabled(saved)
        self._invalidate_walk_forward_preview()

    def pick_walk_forward_original(self):
        name, _ = self.host.open_file(ui_text('ui.pick_walk_forward_original.dialog_title'), '', ui_text('ui.pick_walk_forward_original.json_filter'))
        if not name:
            return
        if '://' in name or name.startswith(('//', '\\\\')) or not Path(name).is_absolute():
            raise ValidationError(ui_text('ui.pick_walk_forward_original.absolute_path_required'))
        path = Path(name).resolve(strict=True)
        if not path.is_file():
            raise ValidationError(ui_text('ui.pick_walk_forward_original.complete_file_required'))
        self.walk_forward_original.setText(str(path))
        self.host.form_feedback(self.walk_forward_original, ui_text('ui.pick_walk_forward_original.original_selected'))

    def _walk_forward_saved_source(self):
        if self.walk_forward_form.fields['pool_origin'].currentData() != 'saved_campaign_pool':
            return None
        reference = self.walk_forward_campaign.currentData()
        if not reference:
            raise ValidationError(ui_text('ui.walk_forward_saved_source.research_required'))
        path = self.walk_forward_original.text()
        if not path:
            raise ValidationError(ui_text('ui.walk_forward_saved_source.original_required'))
        return {'campaign_reference': reference, 'original_dataset': {'kind': 'local_dataset_file', 'path': path}}

    def _invalidate_walk_forward_preview(self, *args):
        self.state._wf_preview = None
        self.walk_forward_consent.setChecked(False)
        self.walk_forward_start.setEnabled(False)
        self.walk_forward_preview.setPlainText(ui_text('ui.invalidate_walk_forward_preview.source_changed'))
        self.walk_forward_status.setText(ui_text('ui.invalidate_walk_forward_preview.preview_invalidated'))
        self.walk_forward_advanced.clear()
        self.wf_wizard.summary.set_rows([])
        self.wf_wizard.timeline.setVisible(False)
        self.wf_wizard.preview_summary.clear()
        self.wf_wizard.message.clear()

    def _walk_forward_input_key(self):
        path = self.state.root / 'dataset.json'
        stat = path.stat()
        typed = self.state.backtest_form.build_payload()
        config = self.host.payload(self.state.config, lambda: typed['config'])
        plan = self.walk_forward_form.build_payload(config)
        # Worker checks full data/manifest and engine hashes again before running;
        # this cheap UI key only discards stale asynchronous preview responses.
        source = self._walk_forward_saved_source()
        inputs = {'plan': plan, 'source': [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]}
        if source is not None:
            from quantlab.desktop_runtime import validate_walk_forward_request

            validate_walk_forward_request(plan, source)
            from desktop_walk_forward import source_campaign_folder

            folder = source_campaign_folder(self.state.paths, source['campaign_reference'])
            files = (folder / 'campaign.json', folder / 'campaign.sqlite3', Path(source['original_dataset']['path']))
            inputs['saved_source'] = source
            inputs['saved_files'] = [[p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns] for p in files]
        return content_hash(inputs), plan

    def preview_walk_forward(self):
        self._invalidate_walk_forward_preview()
        self.walk_forward_results.set_rows([])
        key, plan = self._walk_forward_input_key()
        payload = {'plan': plan}
        source = self._walk_forward_saved_source()
        if source is not None:
            payload['saved_source'] = source
        self.host.start_job('ui_walk_forward_preview', payload)
        self.state._wf_request_key = key
        self.walk_forward_preview.setPlainText(ui_text('ui.preview_walk_forward.checking_source'))
        self.walk_forward_status.setText(ui_text('ui.preview_walk_forward.checking_budget'))

    def run_walk_forward(self):
        self.wf_wizard.message.clear()
        if self.state._wf_preview is None or not self.walk_forward_consent.isChecked():
            raise ValidationError(ui_text('ui.run_walk_forward.preview_consent_required'))
        key, plan = self._walk_forward_input_key()
        if key != self.state._wf_request_key:
            self._invalidate_walk_forward_preview()
            raise ValidationError(ui_text('ui.run_walk_forward.source_changed'))
        identity = self.state._wf_preview['preview_identity']
        if (self.state.root / 'walk_forward' / identity / 'walk_forward.sqlite3').exists():
            self.host.start_job('ui_walk_forward_read', {'reference': identity})
            self.walk_forward_consent.setChecked(False)
            return
        payload = {'plan': plan, 'preview_identity': identity}
        source = self._walk_forward_saved_source()
        if source is not None:
            payload['saved_source'] = source
        job = self.host.start_job('ui_walk_forward_run', payload)
        self.state._wf_launch = {'reference': identity, 'stopped_job_id': job}
        self.walk_forward_consent.setChecked(False)

    def read_walk_forward(self):
        reference = self.walk_forward_choice.currentData()
        if not reference:
            raise ValidationError(ui_text('ui.read_walk_forward.no_saved_record'))
        self.host.start_job('ui_walk_forward_read', {'reference': reference})

    def _refresh_walk_forward_references(self):
        previous = self.walk_forward_choice.currentData()
        self.walk_forward_choice.clear()
        for path in sorted((self.state.root / 'walk_forward').glob('*/walk_forward.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_choice.addItem(ui_text('ui.refresh_walk_forward_references.record_id').format(name[:12]), name)
        index = self.walk_forward_choice.findData(previous)
        if index >= 0:
            self.walk_forward_choice.setCurrentIndex(index)
        selected = self.walk_forward_campaign.currentData()
        self.walk_forward_campaign.blockSignals(True)
        self.walk_forward_campaign.clear()
        self.walk_forward_campaign.addItem(ui_text('ui.refresh_walk_forward_references.research_placeholder'), None)
        for path in sorted((self.state.root / 'campaigns').glob('*/campaign.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_campaign.addItem(ui_text('ui.refresh_walk_forward_references.research_id').format(name[:12]), name)
        index = self.walk_forward_campaign.findData(selected)
        self.walk_forward_campaign.setCurrentIndex(max(0, index))
        self.walk_forward_campaign.blockSignals(False)
        if selected != self.walk_forward_campaign.currentData():
            self._invalidate_walk_forward_preview()

    def _walk_forward_event(self, event):
        operation = self.state.last_operation or ''
        if not operation.startswith('ui_walk_forward_'):
            return False
        from .wf_wizard import failure_hint

        kind = event.get('type')
        if kind == 'progress':
            self.state.status.setText(ui_text('ui.walk_forward_event.running'))
            return True
        if kind == 'failed':
            result = event.get('result')
            result = result if type(result) is dict else {}
            self.wf_wizard.message.setText(failure_hint(event.get('error_code') or result.get('error_code')))
            return True
        if kind not in ('result', 'error', 'cancelled'):
            return True
        self.host.record_event(operation, kind)
        if kind == 'result':
            result = event['result']
            if operation == 'ui_walk_forward_preview':
                try:
                    current = self._walk_forward_input_key()[0]
                except (ValueError, OSError):
                    current = None
                if current != self.state._wf_request_key:
                    self._invalidate_walk_forward_preview()
                    self.state.status.setText(ui_text('ui.walk_forward_event.source_changed'))
                    return True
                from desktop_walk_forward import preview_text

                self.walk_forward_preview.setPlainText(preview_text(result))
                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                if result.get('admission_status') == 'rejected':
                    self.state._wf_preview = None
                    self.walk_forward_consent.setChecked(False)
                    self.walk_forward_start.setEnabled(False)
                    self.walk_forward_status.setText(ui_text('ui.walk_forward_event.preview_rejected'))
                    self.state.status.setText(ui_text('ui.walk_forward_event.pool_rejected'))
                    return True
                self.state._wf_preview = result
                self.wf_wizard.show_preview(result)
                self.walk_forward_status.setText(ui_text('ui.walk_forward_event.preview_ready'))
                self.state.status.setText(ui_text('ui.walk_forward_event.preview_ready_status'))
            else:
                from desktop_walk_forward import result_rows, status_label, preview_text

                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                summary = result.get('summary', {})
                from .wf_wizard import display_result_rows

                self.walk_forward_results.set_rows(display_result_rows(result))
                self.result_panel.set_result(result)
                self.walk_forward_status.setText(
                    ui_text('ui.walk_forward_event.result_evidence').format(
                        status_label(result.get('display_status', result['status'])),
                        status_label(summary.get('evidence_mode')),
                        status_label(summary.get('exposure_status')),
                        ui_text('ui.walk_forward_event.experiment_budget').format(
                            summary.get('evaluations_reserved', 0),
                            summary.get('evaluation_limit', ui_text('ui.walk_forward_event.unknown')),
                            summary.get('evaluated_oos_folds', 0),
                        ),
                        ui_text('ui.walk_forward_event.source_model_status').format(status_label(result['pool_admission']['real_model_status']))
                        if result.get('pool_admission')
                        else '',
                        str(result.get('reference', ''))[:12],
                    )
                )
                self.state.status.setText(ui_text('ui.walk_forward_event.saved_record_read'))
                self._refresh_walk_forward_references()
                if operation in ('ui_walk_forward_run', 'ui_walk_forward_reconcile'):
                    self.state._wf_launch = None
        else:
            if operation == 'ui_walk_forward_preview':
                self.walk_forward_status.setText(ui_text('ui.walk_forward_event.preview_incomplete'))
            self.state.status.setText(error_message('operation_failed'))
            if operation == 'ui_walk_forward_run':
                self.state._wf_pending_reconcile = self.state._wf_launch is not None
        result = event.get('result')
        result = result if type(result) is dict else {}
        if kind == 'error' or result.get('status') in ('failed', 'error', 'blocked'):
            self.wf_wizard.message.setText(failure_hint(event.get('error_code') or result.get('error_code')))
        return True

    def _family_changed(self):
        self.state.active_candidate = None
        if hasattr(self, 'candidate_choice'):
            (self.state.root / 'active_candidate.json').unlink(missing_ok=True)
        self.parameters.setReadOnly(False)
        from quantlab.strategies import builtin_strategies

        spec = builtin_strategies()[self.family.currentIndex()]
        self.parameters.setPlainText(canonical_json(spec.parameters))
        self.host.remember(self.parameters)
        self.strategy_form.family.blockSignals(True)
        try:
            self.strategy_form.from_payload(to_dict(spec))
        finally:
            self.strategy_form.family.blockSignals(False)
        self.strategy_form.setEnabled(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy': spec, 'sha256': content_hash(spec), 'scope': 'research_and_paper_only'}))

    def open_idea_research(self):
        if self.idea_dialog is None:
            from .idea_research import IdeaResearchDialog

            self.idea_dialog = IdeaResearchDialog(self.host, self)
        self.idea_dialog.show()
        self.idea_dialog.raise_()
        return self.idea_dialog

    def run_campaign(self):
        config = self.host.payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.state.backtest_form.build_payload()['config']))
        options = {'mode': self.provider_mode.currentData()}
        if options['mode'] not in ('chatgpt_plan', 'fixture', 'manual'):
            raise ValidationError(ui_text('ui.run_campaign.subscription_only'))
        if options['mode'] == 'chatgpt_plan':
            from dataclasses import asdict

            options = asdict(self.state.chatgpt_panel.build_plan_options())
            options['expected_binding'] = self.state._plan_usage_binding
            from quantlab.__main__ import config_from_json

            checked = dict(config)
            checked['backtest_config'] = config_from_json(checked['backtest_config'])
            self.host.plan_provider(self.state.paths, self.host.dataset(self.state.root, {}), checked, options)
        if options['mode'] == 'manual':
            options.update(response_path=self.manual_path.text().strip(), response_text=self.manual_response.toPlainText())
        subscription_campaign = options['mode'] == 'chatgpt_plan'
        launched_job = self.host.start_job('ui_campaign', {'config': config, 'provider': options})
        self.state._subscription_campaign = subscription_campaign
        if self.state._subscription_campaign:
            local_options = {**options, 'network_opt_in': False, 'included_usage_policy_confirmed': False}
            self.state._plan_launch = json.loads(
                canonical_json({'config': config, 'provider': local_options, 'binding': options['expected_binding'], 'stopped_job_id': launched_job})
            )
            self.state.chatgpt_controller.invalidate_campaign_usage()

    def export_manual_request(self):
        config = self.host.payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.state.backtest_form.build_payload()['config']))
        if config.get('max_improvements') != 0:
            raise ValidationError(ui_text('ui.export_manual_request.zero_refinements_required'))
        name, _ = self.host.save_file(ui_text('ui.export_manual_request.dialog_title'), 'manual-ai-request.json', 'JSON (*.json)')
        if name:
            if Path(name).exists():
                raise ValidationError(ui_text('ui.export_manual_request.new_filename_required'))
            self.host.start_job('ui_campaign', {'config': config, 'provider': {'mode': 'manual'}, 'manual_export': name})

    def inspect_candidate(self, index=None):
        self.state._candidate_valid = False
        reference = self.candidate_choice.currentData()
        if not reference:
            self.candidate_detail.setPlainText(ui_text('ui.inspect_candidate.no_candidate'))
        else:
            try:
                spec, provenance = self.host.candidate_record(self.state.root, reference)
                self.candidate_detail.setPlainText(canonical_json({'strategy': spec, **provenance}))
                self.candidate_card.set_values(
                    {
                        ui_text('ui.inspect_candidate.strategy'): spec.strategy_id,
                        ui_text('ui.inspect_candidate.paper_eligibility'): provenance['paper_qualified'],
                        ui_text('ui.inspect_candidate.oos_holdout'): provenance['evaluations'],
                    }
                )
                self.state._candidate_valid = True
            except Exception:
                self.candidate_detail.setPlainText(ui_text('ui.inspect_candidate.invalid_candidate'))
        self.use_candidate_button.setEnabled(self.state._candidate_valid and not self.state.jobs.active)

    def use_candidate(self):
        reference = self.candidate_choice.currentData()
        spec, provenance = self.host.candidate_record(self.state.root, reference)
        self.family.setCurrentText(spec.family)
        self.state.active_candidate = reference
        write_json(self.state.root / 'active_candidate.json', reference)
        self.parameters.setPlainText(canonical_json(spec.parameters))
        self.parameters.setReadOnly(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy': spec, **provenance}))
        self.strategy_form.load({key: spec.parameters.get(key, '') for key in self.strategy_form.fields if key != 'family'})
        self.strategy_form.setEnabled(False)
        self.state.batch.setChecked(False)
        self.host.form_feedback(self.strategy_form, ui_text('ui.use_candidate.immutable_candidate_applied'))

    def use_builtin(self):
        self._family_changed()
        self.host.form_feedback(self.strategy_form, ui_text('ui.use_builtin.builtin_selected'))
