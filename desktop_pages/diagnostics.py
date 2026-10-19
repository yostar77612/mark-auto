"""Explicit, read-only snapshot of cached state and optional local error codes."""

from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from desktop_strings import ui_text
from quantlab.diagnostics import build_diagnostics, copy_diagnostics, read_error_records


def snapshot_for_state(state, *, now=None):
    data, job = {}, {}
    workspace, errors = None, None
    paths = getattr(state, 'paths', None)
    try:
        workspace = paths.root.is_dir()
        errors = read_error_records(paths.logs / 'desktop-events.jsonl')
    except (AttributeError, OSError, TypeError):
        pass
    feedback = getattr(state, 'diagnostics_feedback', None)
    if feedback is not None:
        memory = list(feedback.diagnostic_errors)
        # Runtime logs and memory can contain the same terminal error.
        if memory:
            errors = (errors or []) + [row for row in memory if row not in (errors or [])]
        job['stage'] = feedback.diagnostic_stage
    job['operation'] = getattr(state, 'last_operation', None)
    job['active'] = getattr(getattr(state, 'jobs', None), 'active', False)
    market = getattr(state, 'market', None)
    series = market.selected_series() if market is not None else None
    if series is not None and series.bars:
        bar = series.bars[-1]
        data = {
            'source': series.instrument.exchange,
            'mode': series.provenance.mode,
            'latest_bar_timestamp': bar.timestamp,
            'latest_bar_trade_date': bar.trade_date,
        }
    return build_diagnostics(
        workspace=workspace,
        data=data,
        job=job,
        errors=errors,
        now=now if now is not None else datetime.now(timezone.utc),
        startup_timing=getattr(state, 'startup_timing', None),
    )


class DiagnosticsPanel(QWidget):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.setToolTip(ui_text('diagnostics.startup_timing_hint'))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(ui_text('diagnostics.notice')))
        self.output = QPlainTextEdit()
        self.output.setObjectName('diagnostics_snapshot')
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(180)
        self.refresh_button = QPushButton(ui_text('diagnostics.refresh'))
        self.refresh_button.setObjectName('refresh_diagnostics')
        self.copy_button = QPushButton(ui_text('diagnostics.copy'))
        self.copy_button.setObjectName('copy_diagnostics')
        for widget in (self.refresh_button, self.output, self.copy_button):
            layout.addWidget(widget)
        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button.clicked.connect(self.copy)
        self.text = ''

    def refresh(self):
        self.text = self.snapshot()
        self.output.setPlainText(self.text)

    def copy(self):
        self.refresh()
        copy_diagnostics(self.text, QApplication.clipboard())
