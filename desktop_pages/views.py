"""Refresh and render shared research views after background callbacks."""

from desktop_strings import ui_text
from pathlib import Path
from quantlab.desktop_errors import error_message, exception_code
from quantlab.core import canonical_json, content_hash, to_dict
from quantlab.reporting import read_json as read_json, load_dataset as load_dataset, demo_config, load_result as load_result, load_selection
from PySide6.QtCore import Qt
from desktop_presentation import display_status, result_name as result_name
from .bindings import PageContext
from .compare_table import saved_row


class ViewCoordinator(PageContext):
    def __init__(self, host):
        self.setup_context(host)

    def refresh_views(self):
        self._refresh_walk_forward_references()
        self._refresh_analysis_saved()
        self._refresh_dataset_views()
        self._refresh_result_choices()
        history = self._refresh_saved_history()
        self._refresh_candidate_choices(history)
        self._restore_active_candidate()

    def _refresh_dataset_views(self):
        path = self.root / 'dataset.json'
        data = None
        if path.exists():
            try:
                data = self.host.callbacks['load_dataset'](path)
                self.overview.setText(ui_text('ui.refresh_views.source_summary').format(display_status(data.manifest['source_type']), len(data.bars)))
                self.data_card.setText(
                    ui_text('ui.refresh_views.source_details').format(
                        display_status(data.manifest['source_type']), ui_text('ui.refresh_views.bar_count').format(len(data.bars))
                    )
                )
                self.data_detail.setPlainText(canonical_json({'manifest': data.manifest, 'quality': data.quality}))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.overview.setText(error_message(exception_code(exc)))
        else:
            self.overview.setText(ui_text('ui.refresh_views.no_data'))
        # Keep the module's public names unchanged; only this refresh needs the error type.
        from quantlab.core import ValidationError

        stamp = content_hash(to_dict(data.manifest)) if data is not None else None
        if stamp != self._wf_source_stamp:
            first_source = self._wf_source_stamp is None
            self._wf_source_stamp = stamp
            if data is not None and first_source:
                try:
                    self.walk_forward_form.defaults_for_bars(len(data.bars))
                except ValidationError:
                    # Too few bars for walk-forward defaults; the run itself still validates.
                    pass
            self._invalidate_walk_forward_preview()
        self._dataset_ready = data is not None
        self.load_market_cache()
        if data is not None and self._campaign_data_hash != data.manifest['data_hash']:
            # Keep this dependency local to the stage that uses it.
            from quantlab.research import demo_campaign_config

            try:
                self.campaign_form.from_payload(to_dict(demo_campaign_config(data, demo_config())))
                self._campaign_data_hash = data.manifest['data_hash']
            except ValidationError:
                # Too few bars for demo research defaults; keep the form and let research validate.
                pass
        self.run_button.setEnabled(data is not None and not self.jobs.active)

    def _refresh_result_choices(self):
        old = self.result_choice.currentData()
        active = self.root / 'active_result.json'
        if self.last_operation == 'ui_backtest' and active.exists():
            digest = self.host.callbacks['read_json'](active).get('result_hash', '')
            if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
                old = str(self.root / 'reports' / digest / 'result.json')
        selected_results = {item.data(Qt.ItemDataRole.UserRole) for item in self.comparison_list.selectedItems()}
        self.result_choice.blockSignals(True)
        self.result_choice.clear()
        self.comparison_list.clear()
        names = {}
        comparison_records = []
        for result_path in sorted((self.root / 'reports').glob('*/result.json')):
            try:
                loaded = self.host.callbacks['load_result'](result_path)
                created = result_path.stat().st_ctime
                label = self.host.callbacks['result_name'](loaded, created)
                comparison_records.append((str(result_path), saved_row(loaded, created)))
            except (ValueError, KeyError, TypeError, OSError):
                label = ui_text('ui.refresh_views.unreadable_result')
                comparison_records.append((str(result_path), {'name': label}))
            names[label] = names.get(label, 0) + 1
            if names[label] > 1:
                label += ui_text('ui.refresh_views.parenthesized_value').format(names[label])
            comparison_records[-1][1]['name'] = label
            self.result_choice.addItem(label, str(result_path))
            self.result_choice.setItemData(self.result_choice.count() - 1, result_path.parent.name, Qt.ItemDataRole.ToolTipRole)
            self.comparison_list.addItem(label)
            self.comparison_list.item(self.comparison_list.count() - 1).setData(Qt.ItemDataRole.UserRole, str(result_path))
            self.comparison_list.item(self.comparison_list.count() - 1).setToolTip(result_path.parent.name)
            self.comparison_list.item(self.comparison_list.count() - 1).setSelected(str(result_path) in selected_results)
        self.comparison_list.table.set_saved(comparison_records)
        index = self.result_choice.findData(old)
        if index >= 0:
            self.result_choice.setCurrentIndex(index)
        self.result_choice.blockSignals(False)
        self.show_result()

    def _refresh_saved_history(self):
        selection = self.root / 'selection.json'
        self.selection_status.setText(
            ui_text('ui.refresh_views.active_candidate_hint') if selection.exists() else ui_text('ui.refresh_views.no_active_strategy')
        )
        self.selection_status.setToolTip(load_selection(selection)['strategy_hash'] if selection.exists() else '')
        policy = self.root / 'paper_policy.json'
        if policy.exists():
            policy_value = self.host.callbacks['read_json'](policy)
            self.paper_policy.setPlainText(canonical_json(policy_value))
            self.policy_form.from_payload(policy_value)
            self._remember(self.paper_policy)
        history = []
        for p in sorted((self.root / 'campaigns').glob('*/*.json'))[:100]:
            history.append({'file': str(p), 'content': self.host.callbacks['read_json'](p)})
        self.history.setPlainText(canonical_json(history) if history else ui_text('ui.refresh_views.no_research'))
        self.history_table.set_rows(
            [
                {'family': a.get('family'), 'sequence': a.get('sequence'), 'status': a.get('status'), 'strategy_hash': a.get('strategy_hash')}
                for entry in history
                for a in entry['content'].get('attempts', [])
            ]
        )
        self.evaluation_table.set_rows(
            [
                {
                    ui_text('ui.refresh_views.evaluation_segment'): split,
                    'status': row.get('status'),
                    'strategy_hash': row.get('strategy_hash'),
                    **row.get('metrics', {}),
                }
                for entry in history
                for split, rows in entry['content'].get('evaluations', {}).items()
                for row in rows
            ]
        )
        return history

    def _refresh_candidate_choices(self, history):
        selected_analysis = [item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        self.analysis_candidates.blockSignals(True)
        self.analysis_candidates.clear()
        selected_ref = self.candidate_choice.currentData()
        self.candidate_choice.blockSignals(True)
        self.candidate_choice.clear()
        for entry in history:
            state = entry['content']
            if not isinstance(state, dict):
                continue
            for attempt in state.get('attempts', []):
                ref = {
                    'campaign_folder': Path(entry['file']).parent.name,
                    'attempt_id': attempt.get('attempt_id'),
                    'strategy_hash': attempt.get('strategy_hash'),
                }
                label = f"{state.get('campaign_id', '')[:10]} · {display_status(attempt.get('family', '?'))} · v{attempt.get('sequence', '?')} · {display_status(attempt.get('status', '?'))}"
                self.candidate_choice.addItem(label, ref)
                if attempt.get('status') == 'evaluated' and Path(entry['file']).name == 'campaign.json':
                    family = attempt.get('spec', {}).get('family', attempt.get('family', ui_text('ui.refresh_views.candidate')))
                    family = {
                        'trend': ui_text('ui.refresh_views.trend'),
                        'mean_reversion': ui_text('ui.refresh_views.mean_reversion'),
                        'breakout': ui_text('ui.refresh_views.breakout'),
                        'momentum': ui_text('ui.refresh_views.momentum'),
                        'volatility': ui_text('ui.refresh_views.volatility'),
                    }.get(family, family)
                    self.analysis_candidates.addItem(
                        ui_text('ui.refresh_views.evaluated_result').format(
                            state.get('campaign_id', '')[:10], family, str(attempt.get('strategy_hash', ''))[:12]
                        )
                    )
                    item = self.analysis_candidates.item(self.analysis_candidates.count() - 1)
                    item.setData(Qt.ItemDataRole.UserRole, ref)
                    item.setSelected(ref in selected_analysis)
        index = self.candidate_choice.findData(selected_ref)
        if index >= 0:
            self.candidate_choice.setCurrentIndex(index)
        self.candidate_choice.blockSignals(False)
        self.inspect_candidate()
        self.analysis_candidates.blockSignals(False)

    def _restore_active_candidate(self):
        active_candidate = self.root / 'active_candidate.json'
        if self.active_candidate is None and active_candidate.exists():
            reference = self.host.callbacks['read_json'](active_candidate)
            index = self.candidate_choice.findData(reference)
            if index >= 0:
                self.candidate_choice.setCurrentIndex(index)
                self.use_candidate()
        self._refresh_recovery_controls(force=True)
        if hasattr(self.state, 'onboarding'):
            self.state.onboarding.refresh()

    def render_result(self, event):
        result = event.get('result', {})
        if isinstance(result, list):
            result = {'downloads': result}
        text = canonical_json(result)
        self.summary.setPlainText(text)
        if self.last_operation == 'ui_compare':
            self.comparison.setPlainText(text)
            self.comparison_table.set_rows(result.get('rows', []))
        if result.get('manual_export'):
            self.status.setText(ui_text('ui.poll_jobs.manual_request_exported'))
        if self.last_operation == 'ui_market_refresh':
            self._market_outcomes = result.get('providers', {})
        if self.last_operation and self.last_operation.startswith('ui_paper_'):
            self.paper_detail.setPlainText(text)
            if 'account' in result:
                self._show_account(result['account'])
        if self.last_operation == 'ui_paper_replay' and 'replay' in result:
            self.page_state.replay_controls.result(result)
        if self.last_operation == 'ui_backup_restore':
            self.freeze_paper(ui_text('ui.poll_jobs.backup_restored'))
        if self.last_operation in ('ui_paper_replay', 'ui_paper_kill') and 'account' in result:
            self._remember_stop(result['account'], 'replay' if self.last_operation == 'ui_paper_replay' else 'user')
        self.refresh_views()
        return result
