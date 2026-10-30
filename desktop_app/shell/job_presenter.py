from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message, exception_code
from quantlab.desktop_feedback import completion_summary
from quantlab.core import ValidationError
import desktop_app.components.job_progress as _job_progress
import desktop_app.shell.notifications as _notifications


class JobPresenter:
    def __init__(self, view):
        self.view = view

    def start_job(self, operation, payload):
        self.view.services.require_operation(self.view.paths, operation)
        if operation not in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
            self.view.chatgpt_panel.abandon_primary_sign_in()
        if self.view.jobs.active:
            raise ValidationError(ui_text('ui.start_job.job_busy'))
        job_id = self.view.jobs.start(operation, payload)
        self.view.last_operation = operation
        self.view._ui_job_id = job_id
        self.view.job_feedback.begin(job_id)
        self.view.status.setText(ui_text('ui.start_job.running'))
        self.view._busy(True)
        return job_id

    def _busy(self, active, *, refresh_recovery=False):
        controller = getattr(self.view, 'chatgpt_controller', None)
        if controller is not None:
            controller.set_background_busy(bool(active))
        panel = getattr(getattr(self.view, 'strategy_page', None), 'result_panel', None)
        if panel is not None:
            panel.set_scenario_busy(active)
        for button in self.view.actions:
            button.setEnabled(not active)
        self.view.data_page.next_button.setEnabled(bool(getattr(self.view, '_dataset_ready', False)) and (not active))
        self.view.market.set_loading(active)
        self.view.kill_button.setEnabled(True)
        self.view.job_progress.set_running(active and (not self.view.job_feedback.terminal))
        if not active:
            self.view.progress.setValue(0)
            self.view.run_button.setEnabled(bool(getattr(self.view, '_dataset_ready', False)))
            self.view.use_candidate_button.setEnabled(bool(getattr(self.view, '_candidate_valid', False)))
            self.view.select_button.setEnabled(bool(getattr(self.view, '_selection_allowed', False)))
            self.view.walk_forward_start.setEnabled(self.view._wf_preview is not None and self.view.walk_forward_consent.isChecked())
            self.view.analysis_start.setEnabled(self.view._analysis_preview is not None and (not self.view._analysis_preview['receipt_snapshot']['receipts']))
            if getattr(self.view, 'paper_page', None) is not None:
                self.view.paper_page._apply_order_lock()
        self.view._refresh_recovery_controls(force=active or refresh_recovery)

    def cancel_job(self):
        if not _job_progress.cancel_allowed(self.view):
            return

        def cancel_and_recover():
            self.view.freeze_paper(ui_text('ui.cancel_and_recover.user_cancel'))
            self.view.status.setText(ui_text('job.cancel_notice'))

        self.view._safe(cancel_and_recover)

    def poll_jobs(self):
        try:
            recovery_changed = False
            for event in self.view.jobs.poll():
                recovery_changed = self._project_job_event(event, recovery_changed)
            if not self.view.jobs.active:
                self._continue_after_jobs(recovery_changed)
        except Exception as exc:
            self.view.status.setText(error_message(exception_code(exc)))
        finally:
            _notifications.end_event(self.view)

    def notify_local(self, message, *, error=False, completion=False):
        _notifications.notify_local(self.view, message, error=error, completion=completion)

    def _notification_link(self, link):
        if link == 'close':
            _notifications.close_banner(self.view)
            return
        if link != 'result':
            return
        operation = self.view._notification_operation or ''
        page = (
            4
            if operation.startswith('ui_paper_')
            else 2
            if operation == 'ui_backtest'
            else 3
            if operation in ('ui_compare', 'ui_select', 'ui_disable')
            else 1
            if operation.startswith(('ui_analysis_', 'ui_walk_forward_')) or operation == 'ui_campaign'
            else 6
            if operation.startswith(('ui_backup_', 'ui_chatgpt_'))
            else 0
        )
        self.view.navigation.setCurrentRow(page)
        target = (
            self.view.paper_card
            if page == 4
            else self.view.result_card
            if page == 2 and hasattr(self.view, 'result_card')
            else self.view.stack.widget(page).widget()
        )
        self.view.stack.widget(page).ensureWidgetVisible(target)

    def _quiesce_and_recover(self, *, preserve_primary_sign_in=False):
        if getattr(self.view.page_state, 'replay_controls', None):
            self.view.page_state.replay_controls.cancel()
        if not preserve_primary_sign_in:
            self.view.chatgpt_panel.abandon_primary_sign_in()
        if self.view.jobs.active:
            self.view.jobs.cancel()
        if self.view.jobs.active:
            raise ValidationError(ui_text('ui.quiesce_and_recover.process_stop_required'))
        return self.view.services.recover_state(self.view.paths, self.view.backups)

    def _project_job_event(self, event, recovery_changed):
        if event.get('job_id') is not None and self.view._ui_job_id is not None and (event['job_id'] != self.view._ui_job_id):
            return recovery_changed
        _notifications.begin_event(self.view)
        if not self.view.job_feedback.accept(self.view, event):
            return recovery_changed
        _notifications.record_event(self.view, event)
        recovery_changed = recovery_changed or event.get('type') in ('result', 'error', 'failed', 'cancelled', 'canceled')
        self.view.automatic_backup_panel.handle_job_event(event)
        import desktop_app.features.capital_scenario.worker as _capital

        if _capital.event(self.view, event):
            return recovery_changed
        from desktop_app.features.strategy.idea_events import event as _c__ideas_event

        if _c__ideas_event(self.view, event):
            return recovery_changed
        if self.view._walk_forward_event(event):
            return recovery_changed
        if self.view._analysis_event(event):
            return recovery_changed
        kind = event.get('type', '')
        if self.view._chatgpt_event(event):
            return recovery_changed
        if self.view._subscription_campaign and kind in ('result', 'error', 'failed', 'cancelled'):
            self.view.chatgpt_controller.invalidate_campaign_usage()
            self.view.chatgpt_controller.account_status_known = False
            self.view._pending_plan_reconcile = self.view._plan_launch is not None
            self.view._pending_usage_refresh = True
            self.view._subscription_campaign = False
        self.view.record_event(self.view.last_operation, kind)
        self._project_job_outcome(kind, event)
        return recovery_changed

    def _project_job_outcome(self, kind, event):
        if kind in ('result', 'completed', 'success'):
            result = self.view.views_page.render_result(event)
            message = completion_summary(self.view.last_operation, result)
            if self.view.job_feedback.campaign_code is not None:
                message = self.view.chatgpt_controller.message
            if self.view.last_operation == 'ui_market_refresh' and any((v.get('error') for v in self.view._market_outcomes.values())):
                message += ui_text('ui.poll_jobs.cache_retained')
            self.view.status.clear()
            self.view.notify_local(message, error=self.view.job_feedback.result_failed(result), completion=True)
        elif kind in ('error', 'failed'):
            if self.view.last_operation == 'ui_backup_restore':
                self.view.freeze_paper(ui_text('ui.poll_jobs.restore_incomplete'))
            self.view.status.clear()
            self.view.notify_local(_job_progress.failure_notice(self.view, event), error=True, completion=True)
        elif kind in ('cancelled', 'canceled'):
            self.view.freeze_paper(ui_text('ui.poll_jobs.cancelled_title'))
            self.view.status.setText(ui_text('ui.poll_jobs.cancelled_files_retained'))
        else:
            self.view.status.setText(_job_progress.progress_status(self.view, event))

    def _continue_after_jobs(self, recovery_changed):
        self.view._busy(False, refresh_recovery=recovery_changed)
        if self.view._wf_pending_reconcile and self.view._wf_launch is not None:
            self.view._wf_pending_reconcile = False
            self.view.start_job('ui_walk_forward_reconcile', self.view._wf_launch)
            return
        if self.view._pending_analysis_reconcile and self.view._analysis_launch is not None:
            self.view._pending_analysis_reconcile = False
            self.view.start_job('ui_analysis_reconcile', dict(self.view._analysis_launch))
            return
        if getattr(self.view, '_close_after_reconcile', False):
            self.view._close_after_reconcile = False
            self.view.close()
            return
        if self.view._pending_plan_reconcile and (not self.view.chatgpt_controller.busy) and (not getattr(self.view, '_closing', False)):
            self.view._pending_plan_reconcile = False
            self.view.start_job('ui_chatgpt_reconcile', self.view._plan_launch)
        if (
            not self.view.jobs.active
            and self.view._pending_chatgpt_restore
            and (not self.view.chatgpt_controller.busy)
            and (not getattr(self.view, '_closing', False))
        ):
            self.view._pending_chatgpt_restore = False
            self.view.chatgpt_panel.start_auto_restore()
        if (
            not self.view.jobs.active
            and self.view._pending_usage_refresh
            and (not self.view.chatgpt_controller.busy)
            and (not getattr(self.view, '_closing', False))
        ):
            self.view._pending_usage_refresh = False
            reference = self.view.chatgpt_controller.active_registration
            if reference:
                self.view.start_job('ui_chatgpt_usage', {'registration': reference})
        if not self.view.jobs.active and getattr(self.view, '_kill_pending', False):
            self.view._kill_pending = False
            self.view.paper_job('kill')
