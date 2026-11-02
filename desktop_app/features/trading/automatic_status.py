"""Automatic execution facts and explicit reconcile-then-resume controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from desktop_app.features.trading.labels import state_label
from desktop_app.features.trading.trading_page import confirm_trading_action, position_time
from desktop_app.features.trading.widgets import button
from desktop_app.features.trading.daily_execution import DailyExecution
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment


def error_next(code, window):
    return ' '.join(window.strategy_error_texts.get(code, (ui_text('watch.unknown'), ui_text('u4.reconcile_first'))))


def plain_label(name):
    widget = QLabel()
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class AutomaticControls:
    def __init__(self, window, header):
        self.window = window
        self.reconciled_scope = None
        self.header = plain_label('automatic_header_status')
        self.header.setWordWrap(False)
        self.header.setMaximumWidth(300)
        self.header.setMaximumHeight(48)
        header.addWidget(self.header)
        self.stop = button('u4.stop_all', 'persistent_stop_all')
        self.stop.setProperty('role', 'danger')
        self.stop.setToolTip(ui_text('u4.stop_semantics'))
        self.stop.clicked.connect(lambda: confirm_trading_action(window, UiAction.STOP_NEW))
        header.addWidget(self.stop)
        self.header_resume = button('u4.auto_resume', 'header_auto_resume')
        self.header_resume.clicked.connect(self.resume)
        header.addWidget(self.header_resume)
        cards = QGroupBox(ui_text('dashboard.today'))
        card_layout = QHBoxLayout(cards)
        self.cards = [plain_label('overview_key_' + key) for key in ('pnl', 'strategies', 'positions', 'pending', 'connection')]
        for card in self.cards:
            card_layout.addWidget(card)
        window.pages.widget(0).widget().layout().insertWidget(1, cards)
        self.panels = []
        self.daily_panels = []
        for index, name in ((0, 'overview'), (3, 'trading')):
            group = QGroupBox(ui_text('u4.automatic'))
            layout = QVBoxLayout(group)
            status, evaluations = plain_label(name + '_automatic_status'), plain_label(name + '_automatic_evaluations')
            layout.addWidget(status)
            layout.addWidget(evaluations)
            controls = QHBoxLayout()
            reconcile = button('u4.auto_reconcile', name + '_auto_reconcile')
            resume = button('u4.auto_resume', name + '_auto_resume')
            reconcile.clicked.connect(self.reconcile)
            resume.clicked.connect(self.resume)
            controls.addWidget(reconcile)
            controls.addWidget(resume)
            layout.addLayout(controls)
            daily = DailyExecution(window, name)
            layout.addWidget(daily)
            self.daily_panels.append(daily)
            window.pages.widget(index).widget().layout().insertWidget(2 if index == 0 else 1, group)
            self.panels.append((status, evaluations, reconcile, resume))
        self._preflight()

    @staticmethod
    def scope(state):
        return state.context_id, state.context_epoch, state.environment, state.account_ref, state.trading_day

    def _preflight(self):
        group = QGroupBox(ui_text('u4.preflight'))
        layout = QFormLayout(group)
        self.checks = {}
        for key, caption in (
            ('connection', ui_text('u4.check_connection')),
            ('account', ui_text('u4.check_account')),
            ('permission', ui_text('u4.check_permission')),
            ('ca', ui_text('u4.check_ca')),
            ('market', ui_text('u4.check_market')),
            ('service', ui_text('u4.check_service')),
            ('reconciliation', ui_text('u4.check_reconciliation')),
        ):
            self.checks[key] = plain_label('preflight_' + key)
            layout.addRow(caption, self.checks[key])
        reminder = plain_label('keep_computer_on_reminder')
        reminder.setText(ui_text('u4.keep_on'))
        layout.addRow(reminder)
        check = button('u4.check_now', 'check_preflight')
        check.clicked.connect(self.check)
        layout.addRow(check)
        self.check_button = check
        self.window.pages.widget(0).widget().layout().insertWidget(3, group)

    def check(self):
        self.window.command(UiAction.CHECK_PREFLIGHT, account_ref=self.window.state.account_ref)

    def reconcile(self):
        self.reconciled_scope = None
        self.window.command(UiAction.AUTO_RECONCILE)

    def received(self, command, state, receipt):
        if command is not None and command.action is UiAction.AUTO_RECONCILE:
            self.reconciled_scope = self.scope(state) if receipt is not None and receipt.accepted and state.reconciliation_verified else None

    def resume(self):
        window, state = self.window, self.window.state
        if state.environment is Environment.LIVE:
            window._feedback(ui_text('m2t.orders_disabled'))
            return
        if self.reconciled_scope != self.scope(state) or not state.reconciliation_verified:
            window._feedback(ui_text('u4.reconcile_first'))
            return
        stamp = (*self.scope(state), state.version)
        if not window._confirm(ui_text('u4.resume_confirm')):
            return
        if stamp != (*self.scope(window.state), window.state.version):
            window._feedback(ui_text('v2.state_conflict'))
            return
        self.reconciled_scope = None
        window.command(UiAction.AUTO_RESUME)

    def render(self, state):
        values = (
            (
                ui_text('dashboard.today.net_pnl'),
                f'{state.daily_pnl:,.2f}' if state.financial_facts_verified and state.daily_pnl is not None else ui_text('watch.unknown'),
            ),
            (ui_text('u4.active_strategies'), str(sum(item.state == 'ACTIVE' for item in state.strategies))),
            (
                ui_text('u4.position_count'),
                str(sum(bool(item.quantity) for item in state.positions)) if state.financial_facts_verified else ui_text('watch.unknown'),
            ),
            (ui_text('u4.pending_count'), str(len(state.issues) + len(state.reconciliation))),
            (
                ui_text('dashboard.status.broker').format(''),
                ui_text('dashboard.status.local') if state.environment is Environment.LOCAL else state_label(state.sinopac_connection.phase),
            ),
        )
        for card, (caption, value) in zip(self.cards, values):
            card.setText(caption + '\n' + value)
        paused = state.automatic.state == 'PAUSED_WAITING_RESUME'
        status = ui_text('u4.paused') if paused else ui_text('u4.waiting_session') if state.automatic.state == 'WAITING_SESSION' else ui_text('u4.running')
        reasons = '\n'.join(error_next(code, self.window) for code in state.automatic.reasons)
        explanation = self.window.strategy_error_texts.get(state.automatic.reasons[0], (ui_text('watch.unknown'), ''))[0] if state.automatic.reasons else ''
        self.header.setText(status + ('\n' + explanation.splitlines()[0] if explanation else ''))
        self.header.setToolTip(reasons)
        self.header.setAccessibleName(status + ' ' + reasons)
        self.stop.setText(ui_text('m2t.live_stop') if state.environment is Environment.LIVE else ui_text('u4.stop_all'))
        self.stop.setToolTip(ui_text('m2t.live_stop_hint') if state.environment is Environment.LIVE else ui_text('u4.stop_semantics'))
        evaluations = state.automatic.evaluations
        if evaluations:
            last = max(evaluations, key=lambda item: item.evaluated_at)
            result = (
                error_next(last.code, self.window)
                if last.code
                else state_label(last.order_result.value)
                if last.order_result is not None
                else ui_text('u4.no_order')
            )
            details = ui_text('u4.evaluation').format(
                position_time(last.evaluated_at.isoformat()),
                position_time(last.next_evaluation_at.isoformat()) if last.next_evaluation_at is not None else ui_text('watch.unknown'),
                result,
            )
        else:
            details = ui_text('u4.no_evaluation')
        live = state.environment is Environment.LIVE
        can_resume = not live and paused and state.reconciliation_verified and self.reconciled_scope == self.scope(state)
        resume_hint = (
            ui_text('m2t.orders_disabled')
            if live
            else ui_text('u4.reconcile_first')
            if paused
            else ui_text('u4.daily_pending')
            if state.automatic.state == 'WAITING_SESSION'
            else ui_text('u4.running')
        )
        self.header_resume.setEnabled(can_resume)
        self.header_resume.setToolTip(resume_hint)
        for label, evaluation, reconcile, resume in self.panels:
            label.setText(status + ('\n' + reasons if reasons else ''))
            evaluation.setText(details)
            resume.setEnabled(can_resume)
            resume.setToolTip(resume_hint)
        view = next((item for item in state.preflight if item.account_ref == state.account_ref and item.trade_date.isoformat() == state.trading_day), None)
        rows = {item.key: item for item in view.checks} if view is not None else {}
        for key, label in self.checks.items():
            row = rows.get(key)
            text = (
                ui_text('u4.not_checked')
                if row is None
                else ui_text('u4.not_required')
                if row.state == 'NOT_REQUIRED'
                else ui_text('u4.passed')
                if row.state == 'PASS'
                else error_next(row.code, self.window)
            )
            label.setText(text)
        self.check_button.setEnabled(bool(state.account_ref))
        for daily in self.daily_panels:
            daily.render(state)
        if self.window.style_automatic_controls is not None:
            self.window.style_automatic_controls(self.window, state)
