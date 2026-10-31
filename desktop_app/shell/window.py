from desktop_app.components.validation_feedback import show_feedback
from desktop_app.shell import navigation as _navigation
from desktop_app.shell.theme import set_theme_property
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message, exception_code
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QScrollArea, QMessageBox
from desktop_app.components.result_layers import result_snapshot_lines
from desktop_app.shell.bindings import SharedStateBindings
from desktop_app.shell.setup import configure_window
from desktop_app.shell.job_presenter import JobPresenter
from desktop_app.features.analysis import presenter as _analysis_rows


class MainWindow(SharedStateBindings, QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None, *, services):
        super().__init__()
        self.services = services
        self.job_presenter = JobPresenter(self)
        configure_window(self, paths, jobs, settings, backups, guard)

    def page_services(self):
        return {
            'ui_operations': self.services.operations,
            'paper_risk_limits': lambda *a, **kw: self.services.paper_risk_limits(*a, **kw),
            '_paper': lambda *a, **kw: self.services.paper(*a, **kw),
            '_dataset': lambda *a, **kw: self.services.dataset(*a, **kw),
            'plan_provider': lambda *a, **kw: self.services.plan_provider(*a, **kw),
            'connection_event_from_payload': lambda *a, **kw: self.services.connection_event_from_payload(*a, **kw),
            'analysis_preview_text': lambda *a, **kw: _analysis_rows.analysis_preview_text(*a, **kw),
            'analysis_record_text': lambda *a, **kw: _analysis_rows.analysis_record_text(*a, **kw),
            'saved_analysis_entries': lambda *a, **kw: self.services.saved_analysis_entries(*a, **kw),
            'load_result': lambda *a, **kw: self.services.load_result(*a, **kw),
            'result_name': lambda *a, **kw: self.services.result_name(*a, **kw),
            'write_json': lambda *a, **kw: self.services.write_json(*a, **kw),
            'read_json': lambda *a, **kw: self.services.read_json(*a, **kw),
            'load_dataset': lambda *a, **kw: self.services.load_dataset(*a, **kw),
        }

    def _mount_market(self, page, label):
        return _navigation._mount_market(self, page, label)

    def _mount_page(self, page, label):
        return _navigation._mount_page(self, page, label)

    def _navigate_selected_page(self):
        return _navigation._navigate_selected_page(self)

    def _safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            message = error_message(exception_code(exc))
            self.status.setText(message)
            self.notify_local(message, error=True, completion=True)
            return None

    def form_feedback(self, widget, message):
        show_feedback(self.status, message)
        scroll = widget.parentWidget()
        while scroll is not None and (not isinstance(scroll, QScrollArea)):
            scroll = scroll.parentWidget()
        if scroll is not None:
            scroll.ensureWidgetVisible(widget)
        original = widget.property('feedback')
        set_theme_property(widget, 'feedback', True)
        QTimer.singleShot(1800, widget, lambda: set_theme_property(widget, 'feedback', original))

    def start_job(self, operation, payload):
        return self.job_presenter.start_job(*(operation, payload))

    def _busy(self, active, *, refresh_recovery=False):
        return self.job_presenter._busy(active, refresh_recovery=refresh_recovery)

    def cancel_job(self):
        return self.job_presenter.cancel_job()

    def poll_jobs(self):
        return self.job_presenter.poll_jobs()

    def notify_local(self, message, *, error=False, completion=False):
        return self.job_presenter.notify_local(message, error=error, completion=completion)

    def _notification_link(self, link):
        return self.job_presenter._notification_link(link)

    def _quiesce_and_recover(self, *, preserve_primary_sign_in=False):
        return self.job_presenter._quiesce_and_recover(preserve_primary_sign_in=preserve_primary_sign_in)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_poll_rearmed', False):
            self._poll_rearmed = True
            self.timer.start(150)

    def closeEvent(self, event):
        self.chatgpt_panel.abandon_primary_sign_in()
        if (
            self.jobs.active
            and QMessageBox.question(
                self,
                ui_text('ui.close_event.job_unfinished'),
                ui_text('ui.close_event.cancel_close_question'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            event.ignore()
            return
        try:
            self._closing = True
            self.chatgpt_controller.set_host_available(False)
            self.chatgpt_panel.consent.setChecked(False)
            self.jobs.close()
            self._quiesce_and_recover()
            if (self.last_operation == 'ui_walk_forward_run' or self._wf_pending_reconcile) and self._wf_launch is not None:
                self._wf_pending_reconcile = False
                self.jobs.poll()
                self.start_job('ui_walk_forward_reconcile', self._wf_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if (self._analysis_running or self._pending_analysis_reconcile) and self._analysis_launch is not None:
                self._analysis_running = False
                self._pending_analysis_reconcile = False
                self.jobs.poll()
                self.start_job('ui_analysis_reconcile', dict(self._analysis_launch))
                self._close_after_reconcile = True
                event.ignore()
                return
            if (self._subscription_campaign or self._pending_plan_reconcile) and self._plan_launch is not None:
                self._subscription_campaign = False
                self._pending_plan_reconcile = False
                self.jobs.poll()
                self.start_job('ui_chatgpt_reconcile', self._plan_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if self._chatgpt_job_request:
                self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request = None
            if self.guard is not None:
                self.guard.finish()
        except Exception:
            self._closing = False
            self.chatgpt_controller.set_host_available(True)
            event.ignore()
            self.status.setText(ui_text('ui.close_event.stop_unconfirmed'))
            return
        self._safe(self.save_market_preferences)
        self.market.popout.close()
        self.chatgpt_controller.set_host_available(False)
        self.timer.stop()
        self.app_header.timer.stop()
        event.accept()

    _result_snapshot_lines = staticmethod(result_snapshot_lines)
