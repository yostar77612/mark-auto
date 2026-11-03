"""Read-only audit checks and explicit, version-bound owner controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QProgressBar, QVBoxLayout

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.widgets import button, label
from quantlab.trading.application.contracts import AutoStrategyCommand, UiAction


CHECK_KEYS = {
    'history_complete': 'm3.check_history',
    'trading_days': 'm3.panel_days',
    'trades': 'm3.panel_trades',
    'round_trips': 'm3.panel_round_trips',
    'return': 'm3.check_return',
    'drawdown': 'm3.check_drawdown',
    'win_rate': 'm3.check_win_rate',
    'reject_rate': 'm3.check_reject_rate',
    'reconciliation_clean': 'm3.panel_clean',
}


def percent(value):
    return ui_text('watch.unknown') if value is None else f'{value * 100:,.2f}%'


def check_text(check):
    key = CHECK_KEYS.get(check.name, 'm3.check_unknown')
    if check.name in ('trading_days', 'trades', 'round_trips'):
        text = ui_text(key).format(check.actual, check.limit)
    elif check.actual is not None:
        text = ui_text('m3.check_value').format(ui_text(key), percent(check.actual), percent(check.limit))
    else:
        text = ui_text(key)
    return ui_text('m3.check_pass' if check.passed else 'm3.check_pending') + ' · ' + text


class PromotionPanel(QGroupBox):
    def __init__(self, host, parent=None):
        super().__init__(ui_text('m3.panel_title'), parent)
        self.host = host
        self.selected = None
        self.setObjectName('promotion_panel')
        self.setAccessibleName(ui_text('m3.panel_title'))
        layout = QVBoxLayout(self)
        self.stage = label('m3.select_strategy')
        self.stage.setObjectName('auto_stage_badge')
        layout.addWidget(self.stage)
        self.run_state = label('m3.progress_waiting')
        layout.addWidget(self.run_state)
        self.fingerprint = label('m3.fingerprint_pending')
        layout.addWidget(self.fingerprint)
        self.days = label('m3.progress_waiting')
        self.days.setObjectName('promotion_days')
        layout.addWidget(self.days)
        self.progress = QLabel()
        self.progress.setTextFormat(Qt.TextFormat.PlainText)
        self.progress.setWordWrap(True)
        self.progress.setObjectName('promotion_progress')
        layout.addWidget(self.progress)
        self.drift = label('m3.progress_waiting')
        layout.addWidget(self.drift)
        self.gauge = QProgressBar()
        self.gauge.setObjectName('drift_gauge')
        self.gauge.setAccessibleName(ui_text('m3.check_drawdown'))
        self.gauge.setRange(0, 100)
        layout.addWidget(self.gauge)
        self.note = label('m3.dialog_sim_only')
        layout.addWidget(self.note)
        layout.addWidget(label('m3.panel_sim_optimistic'))
        controls = QGridLayout()
        self.buttons = {}
        for index, (action, key, name, role) in enumerate(
            (
                (UiAction.APPROVE_LIVE_INTENT, 'm3.approve_button', 'approve_live_button', 'primary'),
                (UiAction.PAUSE_AUTO_STRATEGY, 'm3.pause_button', 'pause_auto_button', 'secondary'),
                (UiAction.RESUME_AUTO_STRATEGY, 'm3.resume_button', 'resume_auto_button', 'secondary'),
                (UiAction.RETIRE_AUTO_STRATEGY, 'm3.retire_button', 'retire_auto_button', 'danger'),
            )
        ):
            control = button(key, name, role=role)
            control.clicked.connect(lambda checked=False, action=action: self.act(action))
            controls.addWidget(control, index // 2, index % 2)
            self.buttons[action] = control
        layout.addLayout(controls)
        self.render(None)

    def render(self, view):
        self.selected = view
        for control in self.buttons.values():
            control.setEnabled(False)
            control.setToolTip(ui_text('m3.select_strategy'))
        self.setVisible(view is not None)
        if view is None:
            return
        from desktop_app.features.trading.auto_strategy_rows import stage_text, state_text

        self.stage.setText(stage_text(view))
        self.run_state.setText(state_text(view))
        self.run_state.setProperty('status', 'warning' if view.run_state.value == 'PAUSED' else 'neutral')
        self.run_state.style().unpolish(self.run_state)
        self.run_state.style().polish(self.run_state)
        self.stage.setProperty('status', 'neutral' if view.stage.value == 'BACKTEST' else 'success')
        self.stage.style().unpolish(self.stage)
        self.stage.style().polish(self.stage)
        self.fingerprint.setText(ui_text('m3.dialog_fingerprint').format(view.frozen_hash[:12]))
        checks = view.progress.checks
        day = next((c for c in checks if c.name in ('trading_days', 'round_trips')), None)
        self.days.setText(check_text(day) if day else ui_text('m3.progress_waiting'))
        self.progress.setText('\n'.join(check_text(c) for c in checks if c is not day) or ui_text('m3.history_incomplete'))
        self.progress.setAccessibleName(self.progress.text())
        line, observed = view.progress.drift_line_pct, view.progress.observed_drawdown_pct
        self.drift.setText(ui_text('m3.panel_drawdown').format(percent(observed), percent(line)))
        self.gauge.setValue(min(100, int(observed / line * 100)) if line and observed is not None else 0)
        self.gauge.setFormat(self.drift.text())
        self.gauge.setEnabled(line is not None and observed is not None)
        self.note.setText(
            ui_text(
                'm3.stage_live_approved_note'
                if view.stage.value == 'LIVE_APPROVED'
                else 'm3.panel_eligible_note'
                if view.progress.eligible
                else 'm3.dialog_sim_only'
            )
        )
        active = view.run_state.value != 'RETIRED'
        eligibility = (
            active and view.run_state.value == 'RUNNING' and view.stage.value == 'BROKER_SIM' and view.progress.eligible and view.progress.history_complete
        )
        self.buttons[UiAction.APPROVE_LIVE_INTENT].setEnabled(eligibility)
        self.buttons[UiAction.APPROVE_LIVE_INTENT].setToolTip(ui_text('m3.panel_eligible_note' if eligibility else 'm3.approval_unavailable'))
        self.buttons[UiAction.PAUSE_AUTO_STRATEGY].setEnabled(active and view.run_state.value == 'RUNNING' and view.stage.value != 'BACKTEST')
        self.buttons[UiAction.RESUME_AUTO_STRATEGY].setEnabled(active and view.run_state.value == 'PAUSED')
        self.buttons[UiAction.RETIRE_AUTO_STRATEGY].setEnabled(active)
        for action in (UiAction.PAUSE_AUTO_STRATEGY, UiAction.RESUME_AUTO_STRATEGY, UiAction.RETIRE_AUTO_STRATEGY):
            self.buttons[action].setToolTip(ui_text('m3.state_retired' if not active else 'm3.dialog_sim_only'))
        if view.stage.value == 'BACKTEST':
            self.buttons[UiAction.PAUSE_AUTO_STRATEGY].setToolTip(ui_text('m3.state_waiting_checks'))

    def act(self, action):
        view = self.selected
        if view is None or not self.buttons[action].isEnabled():
            return
        scope = (self.host.state.context_id, self.host.state.context_epoch, self.host.state.environment, self.host.state.account_ref)
        reviewed_version = self.host.state.version
        confirmed = False
        if action is UiAction.APPROVE_LIVE_INTENT:
            # Capture the exact view before opening a nested event loop. Polling
            # cannot silently replace the version/hash the owner is confirming.
            if not self.host._confirm(ui_text('m3.approve_confirm_body').format(view.strategy_id, 30)):
                return
            confirmed = True
        elif action is UiAction.RETIRE_AUTO_STRATEGY:
            if not self.host._confirm(ui_text('m3.retire_confirm')):
                return
            confirmed = True
        current = (self.host.state.context_id, self.host.state.context_epoch, self.host.state.environment, self.host.state.account_ref)
        if current != scope or self.host.state.version != reviewed_version:
            self.host._feedback(ui_text('v2.state_conflict'))
            return
        self.host.command(action, auto_strategy=AutoStrategyCommand(view.strategy_id, view.version, view.frozen_hash, confirmed))
