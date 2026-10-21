"""Shared job progress and terminal presentation, independent of worker control."""

import math
from collections import deque

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QProgressBar
from desktop_strings import ui_text, stage_error_message
from desktop_chatgpt_states import campaign_outcome, outcome_message, outcome_state
from quantlab.job_stages import normalize_stage
from quantlab.diagnostics import error_entry
from .data_gaps import import_event
from .error_guidance import clear_inline

TERMINAL = frozenset({'result', 'completed', 'success', 'error', 'failed', 'cancelled', 'canceled'})
SUCCESS = frozenset({'result', 'completed', 'success'})
CANCELLED = frozenset({'cancelled', 'canceled'})


class JobProgress(QWidget):
    def __init__(self, cancel, parent=None):
        super().__init__(parent)
        self.running = False
        self.cancel_pending = False
        self.bar = QProgressBar()
        self.stage = QLabel(ui_text('job.stage.unknown'))
        self.cancel_button = QPushButton(ui_text('job.cancel'))
        self.cancel_button.setObjectName('cancel_job')
        self.cancel_button.setProperty('role', 'secondary')
        self.cancel_button.setToolTip(ui_text('job.cancel_notice'))
        self.cancel_button.clicked.connect(lambda: self.request_cancel(cancel))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stage)
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.cancel_button)
        self.set_running(False)

    def request_cancel(self, cancel):
        if not self.running or self.cancel_pending:
            return
        self.cancel_pending = True
        self.cancel_button.setEnabled(False)
        cancel()

    def begin(self):
        self.cancel_pending = False
        self.set_running(True)
        self.update_event({})

    def set_running(self, running):
        self.running = bool(running)
        self.cancel_button.setEnabled(self.running and not self.cancel_pending)
        for child in (self.stage, self.bar, self.cancel_button):
            child.setVisible(self.running)
        if not self.running:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)

    def update_event(self, event):
        self.stage.setText(ui_text('job.stage.' + normalize_stage(event.get('stage'))))
        progress = event.get('progress')
        if type(progress) is int or (type(progress) is float and math.isfinite(progress)):
            self.bar.setRange(0, 100)
            self.bar.setValue(round(max(0, min(100, progress))))
        else:
            self.bar.setRange(0, 0)


class JobFeedback:
    """A single terminal packet owns presentation for each submitted job."""

    def __init__(self, widget, *, guidance_owner=None):
        self.widget = widget
        self.guidance_owner = guidance_owner
        self.job_id = None
        self.terminal = False
        self.campaign_code = None
        self.error_code = None
        self.diagnostic_stage = 'unknown'
        self.diagnostic_errors = deque(maxlen=32)

    def begin(self, job_id):
        clear_inline(self.guidance_owner)
        self.error_code = None
        self.job_id = job_id
        self.terminal = False
        self.campaign_code = None
        self.widget.begin()
        self.diagnostic_stage = 'prepare_operation'

    def result_failed(self, result):
        return any(row.get('error') for row in result.get('providers', {}).values()) or (
            self.campaign_code is not None and outcome_state(self.campaign_code) != 'success'
        )

    def accept(self, shell, event):
        if self.job_id is not None and (event.get('job_id') not in (None, self.job_id) or self.terminal):
            return False
        # Only import packets reach the lazy, display-only data report.
        page = getattr(shell, 'data_page', None)
        if getattr(shell, 'last_operation', None) == 'ui_import' and page is not None:
            import_event(page, event)
        if self.job_id is None:
            return True  # Not started through start_job; the host's own job-id filter already applied.
        if event.get('job_id') not in (None, self.job_id) or self.terminal:
            return False
        kind = event.get('type')
        self.diagnostic_stage = normalize_stage(event.get('stage', self.diagnostic_stage))
        if kind in ('error', 'failed'):
            self.error_code = event.get('error_code')
            self.diagnostic_errors.append(error_entry(event))
        if kind not in TERMINAL:
            self.widget.update_event(event)
            return True
        self.terminal = True
        self.widget.set_running(False)
        operation = shell.last_operation
        if operation == 'ui_campaign' and shell._subscription_campaign:
            code = campaign_outcome(event.get('result')) if kind in SUCCESS else event.get('error_code')
            self.campaign_code = code if type(code) is str else 'operation_failed'
            shell.chatgpt_controller.show_outcome(code)
        if kind in CANCELLED:
            shell.notify_local(ui_text('job.cancelled'), completion=True)
        elif operation == 'ui_walk_forward_run':
            message = ui_text('outcome.success.body') if kind in SUCCESS else stage_error_message(event.get('stage'))
            shell.notify_local(message, error=kind not in SUCCESS, completion=True)
        return True


def install_progress(shell, layout):
    widget = JobProgress(shell.cancel_job)
    shell.job_progress = widget
    shell.job_feedback = JobFeedback(widget, guidance_owner=shell.page_state)
    shell.page_state.diagnostics_feedback = shell.job_feedback
    shell.progress = widget.bar
    shell.cancel_button = widget.cancel_button
    layout.addWidget(widget)


def failure_notice(shell, event):
    if getattr(shell, 'last_operation', None) == 'ui_paper_replay':
        shell.page_state.replay_controls.cancel()
    chart = getattr(getattr(shell, 'market', None), 'chart', None)
    if (
        getattr(shell, 'last_operation', None) in ('ui_paper_cancel', 'ui_paper_cancel_all')
        and chart is not None
        and chart.paper_orders.notice == ui_text('orders.pending')
    ):
        chart.paper_orders.notice = ui_text('orders.failed')
        chart.update()
        return chart.paper_orders.notice
    if shell.job_feedback.campaign_code is not None:
        return outcome_message(shell.job_feedback.campaign_code)
    return stage_error_message(event.get('stage'))


def cancel_allowed(shell):
    if getattr(shell, 'last_operation', None) in ('ui_capital_scenario', 'ui_idea_research') and shell.jobs.active and not shell.job_feedback.terminal:
        shell.jobs.cancel()
        shell.status.setText(ui_text('job.cancel_notice'))
        return False
    quick = getattr(shell, 'quick_start', None)
    if quick is not None and quick.chain.stage is not None:
        quick.chain.stop()
    # A queued sign-in continuation still needs the existing abandonment path.
    panel = getattr(shell, 'chatgpt_panel', None)
    pending_sign_in = panel is not None and panel.primary_sign_in_pending
    return pending_sign_in or shell.chatgpt_controller.busy or (shell.jobs.active and not shell.job_feedback.terminal)


def progress_status(shell, event):
    # Preserve fixed context notices used by existing import/cancel workflows.
    message = event.get('message')
    keys = (
        'ui.analysis_plan.recomputing_training_evidence',
        'ui.execute_ui_operation.sending_single_request',
        'ui.execute_ui_operation.importing_local_history',
    )
    if type(message) is str and message in {ui_text(key) for key in keys}:
        return message
    return shell.job_progress.stage.text()
