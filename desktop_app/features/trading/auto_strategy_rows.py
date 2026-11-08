"""Frozen strategy list and reference-only candidate selection, isolated from AI."""

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHeaderView, QHBoxLayout, QLabel, QTableWidget, QVBoxLayout, QWidget

from desktop_app.features.trading.build_auto_dialog import BuildAutoDialog
from desktop_app.features.trading.promotion_panel import PromotionPanel
from desktop_app.features.trading.widgets import button, label, rows, selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction


# AI-built strategies are parked (owner decision 2026-11-08: AI is an assistant, not a strategy generator). The
# code stays; this one switch hides every AI-strategy surface in the desktop UI.
SHOW_AI_STRATEGY = False

STAGE_KEYS = {'BACKTEST': 'm3.stage_backtest', 'BROKER_SIM': 'm3.stage_sim', 'LIVE_APPROVED': 'm3.stage_live_approved'}
PAUSE_KEYS = {
    'DRIFT': 'm3.pause_drift',
    'EVIDENCE_CHANGED': 'm3.pause_evidence',
    'MANUAL': 'm3.pause_manual',
    'ORDER_FAILURES': 'm3.pause_orders',
    'RESTART': 'm3.pause_restart',
}


def stage_text(view):
    text = ui_text(STAGE_KEYS[view.stage.value])
    if view.stage.value == 'LIVE_APPROVED':
        text += ' · ' + ui_text('m2t.orders_disabled')
    return text


def state_text(view):
    if view.run_state.value == 'PAUSED':
        reason = ui_text(PAUSE_KEYS.get(getattr(view.pause_reason, 'value', None), 'm3.check_unknown')).format('1.5')
        return ui_text('m3.state_paused').format(reason)
    if view.run_state.value == 'RETIRED':
        return ui_text('m3.state_retired')
    if view.stage.value in ('BACKTEST', 'LIVE_APPROVED'):
        return ui_text('m3.state_waiting_checks')
    if view.progress.eligible:
        return ui_text('m3.state_eligible')
    return ui_text('m3.state_running')


def strategy_rows(views):
    result = []
    for index, view in enumerate(views, 1):
        kind = ui_text(
            {'INTRADAY': 'm3.kind_intraday', 'SWING': 'm3.kind_swing', 'POSITION': 'm3.kind_position'}.get(view.holding_kind.value, 'm3.check_unknown')
        )
        progress = next((c for c in view.progress.checks if c.name in ('trading_days', 'round_trips')), None)
        progress_text = f'{progress.actual}/{progress.limit}' if progress else ui_text('m3.progress_waiting')
        result.append(
            (
                f'{view.strategy_id}:{view.version}',
                (
                    ui_text('m3.strategy_name').format(index, view.version),
                    kind,
                    ui_text('m3.near_month') if view.instrument_rule == 'TMF_NEAR' else ui_text('v2.index_future'),
                    stage_text(view),
                    progress_text,
                    state_text(view),
                ),
            )
        )
    return tuple(result)


def summary_text(views):
    return ui_text('m3.overview_card_value').format(
        sum(v.run_state.value == 'RUNNING' and v.stage.value == 'BROKER_SIM' for v in views),
        sum(v.run_state.value == 'PAUSED' for v in views),
        sum(v.progress.eligible and v.run_state.value == 'RUNNING' and v.stage.value == 'BROKER_SIM' for v in views),
    )


class _Candidates(QThread):
    loaded = Signal(object)
    unavailable = Signal()

    def __init__(self, facade, parent):
        super().__init__(parent)
        self.facade = facade

    def run(self):
        try:
            candidates = self.facade.candidates()
        except Exception:
            self.unavailable.emit()
        else:
            self.loaded.emit(candidates)


class _Status(QLabel):
    """Plain fallback for standalone hosts; the shell injects AsyncStatus."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_state(self, state, *, message=None):
        self.setText(ui_text('async.loading') if state == 'loading' else message or '')
        self.setAccessibleName(self.text())


class AutoStrategiesWidget(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.worker = None
        self.views = ()
        self.candidate_scope = None
        layout = QVBoxLayout(self)
        self.candidates = QComboBox()
        self.candidates.setObjectName('auto_candidate')
        self.candidates.setAccessibleName(ui_text('m3.candidate'))
        self.candidates.setMinimumContentsLength(12)
        controls = QHBoxLayout()
        controls.addWidget(self.candidates, 1)
        self.refresh = button('m3.refresh_candidates', 'auto_refresh_candidates')
        self.refresh.clicked.connect(self.load_candidates)
        controls.addWidget(self.refresh)
        self.build_button = button('m3.build_button', 'build_auto_strategy_button')
        self.build_button.setToolTip(ui_text('m3.candidates_unavailable'))
        self.build_button.setEnabled(False)
        self.build_button.clicked.connect(self.build_selected)
        controls.addWidget(self.build_button)
        layout.addLayout(controls)
        self.status = host.research_status_factory(self) if host.research_status_factory is not None else _Status(self)
        self.status.setObjectName('auto_build_status')
        if hasattr(self.status, 'label'):
            self.status.label.setObjectName('auto_build_status_text')
            self.status.action.setObjectName('auto_build_status_action')
        self.status.set_state('empty', message=ui_text('m3.candidates_unavailable'))
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName('auto_strategy_table')
        self.table.setAccessibleName(ui_text('m3.overview_card'))
        self.table.setHorizontalHeaderLabels(
            [ui_text(key) for key in ('v2.name', 'm3.field_kind', 'v2.instrument', 'm3.col_stage', 'm3.col_progress', 'v2.state')]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.setMinimumHeight(160)
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table)
        self.empty = label('m3.empty_title')
        layout.addWidget(self.empty)
        self.hint = label('m3.empty_hint')
        layout.addWidget(self.hint)
        research = button('m3.goto_research', 'auto_go_research')
        research.setToolTip(ui_text('m3.frozen_hint'))
        research.clicked.connect(lambda: host.legacy_requested.emit('strategy'))
        layout.addWidget(research)
        self.panel = PromotionPanel(host, self)
        layout.addWidget(self.panel)

    def scope(self):
        state = self.host.state
        return state.context_id, state.context_epoch, state.environment, state.account_ref

    def load_candidates(self):
        if self.worker is not None:
            return
        self.candidate_scope = self.scope()
        self.candidates.clear()
        self.build_button.setEnabled(False)
        self.refresh.setEnabled(False)
        self.status.set_state('loading')
        self.worker = _Candidates(self.host.facade, self)
        self.worker.loaded.connect(self.loaded)
        self.worker.unavailable.connect(self.unavailable)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def loaded(self, candidates):
        if self.candidate_scope != self.scope():
            self.unavailable()
            return
        # Only the authoritative catalogue provides these references. The
        # walk-forward display verdict and arbitrary JSON are never inputs.
        for index, candidate in enumerate(candidates, 1):
            self.candidates.addItem(ui_text('m3.candidate_number').format(index), candidate)
        self.build_button.setEnabled(bool(candidates))
        self.build_button.setToolTip(ui_text('m3.build_button_tip' if candidates else 'm3.candidates_unavailable'))
        self.status.set_state('empty', message=ui_text('m3.dialog_hint' if candidates else 'm3.candidates_unavailable'))

    def unavailable(self):
        self.candidates.clear()
        self.build_button.setEnabled(False)
        self.status.set_state('empty', message=ui_text('m3.candidates_unavailable'))

    def finished(self):
        worker, self.worker = self.worker, None
        self.refresh.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def build_selected(self):
        candidate = self.candidates.currentData()
        scope = self.scope()
        if candidate is None or scope != self.candidate_scope:
            self.unavailable()
            return
        if self.host._operation is not None or self.host._priority_operation is not None:
            self.host._feedback(ui_text('v2.busy'))
            return
        reviewed_version = self.host.state.version
        dialog = BuildAutoDialog(candidate, self.host.state.account_ref, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            if self.scope() != scope or self.host.state.version != reviewed_version:
                self.host._feedback(ui_text('v2.state_conflict'))
            else:
                self.host.command(UiAction.BUILD_AUTO_STRATEGY, auto_build=dialog.request())
        dialog.deleteLater()

    def render(self, state):
        if self.candidate_scope is not None and self.candidate_scope != self.scope():
            self.unavailable()
        self.views = state.auto_strategies
        rows(self.table, strategy_rows(self.views))
        self.table.resizeRowsToContents()
        self.empty.setVisible(not self.views)
        self.hint.setVisible(not self.views)
        self.select()

    def select(self):
        identity = selected_id(self.table)
        view = next((v for v in self.views if f'{v.strategy_id}:{v.version}' == identity), None)
        self.panel.render(view)

    def started(self, command):
        if command is not None and command.action is UiAction.BUILD_AUTO_STRATEGY:
            self.build_button.setEnabled(False)
            self.status.set_state('loading')

    def received(self, command, receipt):
        if command is None or command.action is not UiAction.BUILD_AUTO_STRATEGY or receipt is None:
            return
        self.build_button.setEnabled(self.candidates.count() > 0 and self.candidate_scope == self.scope())
        message = receipt.message
        if receipt.accepted:
            key = 'm3.built_ok_sim' if command.auto_build.start_in_sim else 'm3.built_ok'
            message = ui_text(key).format(command.auto_build.strategy_id)
        self.status.set_state('empty', message=message or ui_text('v2.connection_failed'))

    def failed(self):
        self.status.set_state('empty', message=ui_text('v2.connection_failed'))
        self.build_button.setEnabled(self.candidates.count() > 0 and self.candidate_scope == self.scope())
