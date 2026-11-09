"""Visible feedback for existing strategy research operations; never executes work."""

from PySide6.QtCore import Qt

from desktop_app.features.trading.minute_research_feedback import minute_error_hint, minute_summary
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment


class StrategyResearchFeedback:
    def __init__(self, window, layout):
        self.window = window
        self.pending = False
        self.scope = None
        self.target = ''
        self.caption = ''
        self.status = window.research_status_factory(window)
        self.status.setObjectName('strategy_research_status')
        self.status.label.setObjectName('strategy_research_status_text')
        self.status.action.setObjectName('strategy_research_next')
        layout.insertWidget(1, self.status)
        self.status.hide()

    @staticmethod
    def context(state):
        return state.context_id, state.context_epoch, state.environment, state.account_ref

    def render(self, state):
        selected = self.window.strategy_controls.selected(state)
        for control in (self.window.research_button, self.window.validate_button):
            control.setEnabled(not self.pending and selected is not None)
            control.setToolTip(ui_text('research.feedback.running') if self.pending else ui_text('v2.select_strategy') if selected is None else '')
        if self.scope != self.context(state):
            self.status.hide()

    def started(self, command, operation):
        if command is None or command.action not in (UiAction.RESEARCH, UiAction.RESEARCH_MINUTES, UiAction.VALIDATE):
            return
        self.scope = self.context(self.window.state)
        self.target = command.target_id
        selected = next((item for item in self.window.state.strategies if f'{item.strategy_id}:{item.version}' == self.target), None)
        self.caption = ui_text('research.feedback.target').format(selected.name, selected.version) if selected else ui_text('v2.select_strategy')
        self.pending = True
        self.show('loading', self.caption + '\n' + ui_text('research.feedback.running'))
        self.render(self.window.state)
        operation.completed.connect(lambda state, receipt: self.completed(command.action, state, receipt))
        operation.failed.connect(self.failed)
        operation.finished.connect(self.finished)

    def show(self, state, text, *, next_text=None, next_action=None):
        self.status.set_state(state, message=text, action_text=next_text, action=next_action)
        # AsyncStatus supplies the common state styling; this view uses injected
        # v2 error text and the operation's own caption instead of legacy copy.
        self.status.label.setText(text)
        self.status.label.style().unpolish(self.status.label)
        self.status.label.style().polish(self.status.label)
        self.status.label.setAccessibleName(text)
        self.status.setAccessibleName(text)
        self.status.show()

    def error(self, code, *, unconfirmed=False, hint=''):
        detail = ' '.join(self.window.strategy_error_texts[code]) if code in self.window.strategy_error_texts else ui_text('async.error_unknown')
        heading = ui_text('research.feedback.unconfirmed') if unconfirmed else ui_text('research.feedback.failed')
        text = ui_text('research.feedback.summary').format(self.caption, heading, ui_text('watch.unknown')) + '\n' + detail + ('\n' + hint if hint else '')
        self.show('error', text)

    def completed(self, action, state, receipt):
        if self.scope != self.context(self.window.state) or self.scope != self.context(state):
            return
        if self.window._stamp(state) < self.window._stamp(self.window.state):
            self.error('state_conflict', unconfirmed=True)
            return
        if not receipt.accepted:
            self.error(receipt.code, hint=minute_error_hint(receipt.code) if action is UiAction.RESEARCH_MINUTES else '')
            return
        if action is UiAction.RESEARCH_MINUTES:
            self.show('empty', self.caption + '\n' + minute_summary(receipt.reference))
            return
        strategy = next((item for item in state.strategies if f'{item.strategy_id}:{item.version}' == self.target), None)
        if strategy is None:
            self.error('state_conflict', unconfirmed=True)
            return
        if action is UiAction.VALIDATE:
            heading, source = ui_text('research.feedback.validated'), ui_text('research.feedback.no_data')
            next_text, next_action = ui_text('research.feedback.continue'), self.continue_research
        else:
            sources = {
                'LOCAL_SYNTHETIC_TRAINING': ui_text('research.feedback.local'),
                'OFFICIAL_DAILY_TRAINING': ui_text('research.feedback.official'),
            }
            source = sources.get(strategy.evidence)
            if source is None:
                self.error('strategy_evidence_stale', unconfirmed=True)
                return
            heading = ui_text('research.feedback.passed')
            next_text = ui_text('research.feedback.list') if state.environment is Environment.LIVE else ui_text('research.feedback.activate')
            next_action = self.return_to_list
        self.show('empty', ui_text('research.feedback.summary').format(self.caption, heading, source), next_text=next_text, next_action=next_action)

    def failed(self):
        if self.scope == self.context(self.window.state):
            self.error('operation_failed', unconfirmed=True)

    def finished(self):
        self.pending = False
        self.render(self.window.state)

    def select_target(self):
        if self.pending or self.scope != self.context(self.window.state):
            return False
        for row in range(self.window.strategies.rowCount()):
            if self.window.strategies.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.target:
                self.window.strategies.selectRow(row)
                return True
        return False

    def return_to_list(self):
        if self.select_target():
            self.window.navigation.setCurrentRow(1)
            self.window.strategy_tabs.setCurrentIndex(0)
            (self.window.deploy_button if self.window.deploy_button.isEnabled() else self.window.strategies).setFocus()

    def continue_research(self):
        # The button says 'continue research': it selects the validated target and runs the
        # read-only research for it (no order path), instead of only moving focus.
        if self.select_target():
            self.window.research_button.setFocus()
            self.window._strategy_action(UiAction.RESEARCH)
