"""Strategy management and research navigation over the existing command port."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from desktop_app.features.trading.labels import policy_label
from desktop_app.features.trading.widgets import selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment


def recent_signal_text(code):
    return ui_text('u3.entry_signal') if code == 'ENTRY' else ui_text('u3.no_signal') if not code else ui_text('watch.unknown')


def strategy_block_reason(strategy, error_texts):
    if strategy.entry_block_code:
        return ' '.join(error_texts[strategy.entry_block_code]) if strategy.entry_block_code in error_texts else ui_text('u3.research_needed')
    if strategy.state not in ('RESEARCHED', 'DISABLED', 'ACTIVE') or strategy.evidence in (
        '',
        'NONE',
        'UNRESEARCHED',
        error_texts.get('strategy_evidence_stale', ('', ''))[0],
    ):
        return ui_text('u3.research_needed')
    return ''


class StrategyControls:
    def __init__(self, window, layout, research_layout):
        self.window = window
        self.filled_versions = set()
        self.details = QLabel()
        self.details.setObjectName('strategy_selection_details')
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.research_details = QLabel()
        self.research_details.setObjectName('strategy_research_details')
        self.research_details.setTextFormat(Qt.TextFormat.PlainText)
        self.research_details.setWordWrap(True)
        research_layout.insertWidget(0, self.research_details)
        window.strategies.itemSelectionChanged.connect(lambda: self.render(window.state))
        window.version_button.setText(ui_text('u3.revise'))
        window.version_button.setAccessibleName(ui_text('u3.revise'))
        window.new_strategy_button.setProperty('role', 'primary')
        window.deploy_button.setText(ui_text('u3.activate'))
        window.deploy_button.setAccessibleName(ui_text('u3.activate'))

    def selected(self, state=None):
        state = state or self.window.state
        identity = selected_id(self.window.strategies)
        return next((item for item in state.strategies if f'{item.strategy_id}:{item.version}' == identity), None)

    @staticmethod
    def stamp(state):
        return state.context_id, state.context_epoch, state.environment, state.account_ref, state.version

    def render(self, state):
        strategy = self.selected(state)
        if strategy is None:
            self.details.setText(ui_text('v2.select_strategy'))
            self.research_details.setText(ui_text('v2.select_strategy'))
        else:
            reason = strategy_block_reason(strategy, self.window.strategy_error_texts)
            self.details.setText(
                ui_text('u3.selection_details').format(
                    strategy.name, strategy.version, self.window._environment_label(strategy.environment), recent_signal_text(strategy.recent_signal)
                )
                + ('\n' + reason if reason else '')
            )
            self.research_details.setText(self.details.text() + '\n' + ui_text('u3.research_scope'))
        for control in (self.window.version_button, self.window.clone_strategy_button, self.window.disable_strategy_button, self.window.delete_strategy_button):
            control.setEnabled(strategy is not None)
        has_fills = strategy is not None and (
            (state.context_id, selected_id(self.window.strategies)) in self.filled_versions
            or any((item.strategy_id, item.strategy_version) == (strategy.strategy_id, strategy.version) for item in state.positions)
        )
        self.window.delete_strategy_button.setEnabled(strategy is not None and not has_fills)
        self.window.delete_strategy_button.setToolTip(ui_text('u3.delete_warning'))
        self.window.deploy_button.setEnabled(
            strategy is not None and state.environment is not Environment.LIVE and not strategy_block_reason(strategy, self.window.strategy_error_texts)
        )
        self.window.deploy_button.setToolTip(
            ui_text('m2t.orders_disabled')
            if state.environment is Environment.LIVE
            else strategy_block_reason(strategy, self.window.strategy_error_texts)
            if strategy
            else ui_text('v2.select_strategy')
        )
        self.window.go_strategy_research.setEnabled(strategy is not None)

    def research(self):
        self.window.strategy_tabs.setCurrentIndex(1)
        self.window.research_button.setFocus()

    def manage(self, action):
        strategy = self.selected()
        if strategy is None:
            self.window._feedback(ui_text('v2.select_strategy'))
            return
        identity = f'{strategy.strategy_id}:{strategy.version}'
        if action is UiAction.CLONE_STRATEGY:
            self.window.command(action, identity)
            return
        state = self.window.state
        stamp = self.stamp(state)
        text = ui_text('u3.disable_warning') if action is UiAction.DISABLE_STRATEGY else ui_text('u3.delete_warning')
        text = ui_text('m2m.confirm_scope').format(strategy.account_ref, strategy.name + '\n' + text)
        if not self.window._confirm(text):
            return
        if self.stamp(self.window.state) != stamp or selected_id(self.window.strategies) != identity:
            self.window._feedback(ui_text('v2.state_conflict'))
            return
        self.window.command(action, identity)

    def activate(self):
        strategy = self.selected()
        if strategy is None:
            self.window._feedback(ui_text('v2.select_strategy'))
            return
        if self.window.state.environment is Environment.LIVE:
            self.window._feedback(ui_text('m2t.orders_disabled'))
            return
        if strategy.allocation <= 0:
            self.window._feedback(ui_text('v2.strategy_config_missing'))
            return
        reason = strategy_block_reason(strategy, self.window.strategy_error_texts)
        if reason:
            self.window._feedback(reason)
            return
        state = self.window.state
        stamp, identity = self.stamp(state), f'{strategy.strategy_id}:{strategy.version}'
        text = ui_text('v2.deploy_summary').format(
            strategy.name,
            strategy.version,
            self.window._environment_label(strategy.environment),
            strategy.account_ref,
            strategy.instrument_id,
            policy_label(strategy.policy_label),
            strategy.allocation,
            strategy.risk_fraction * 100,
        )
        text += '\n' + ui_text('v2.expiry_summary').format(
            ui_text('v2.expiry_roll' if strategy.expiry_action == 'ROLL' else 'v2.expiry_exit'), strategy.roll_contract_id or ui_text('v2.no_roll_target')
        )
        if not self.window._confirm(text):
            return
        if self.stamp(self.window.state) != stamp or selected_id(self.window.strategies) != identity:
            self.window._feedback(ui_text('v2.state_conflict'))
            return
        self.window.command(UiAction.DEPLOY, identity)

    def received(self, command, state, receipt):
        if command is not None and command.action is UiAction.DELETE_STRATEGY and receipt is not None and receipt.code == 'strategy_has_fills':
            self.filled_versions.add((state.context_id, command.target_id))
            self.render(self.window.state)

    def restore(self, wizard, strategy):
        wizard.policy.setCurrentIndex(wizard.policy.findData(strategy.holding_kind))
        if strategy.parameters is not None:
            parameters = strategy.parameters
            from PySide6.QtCore import QSignalBlocker

            with QSignalBlocker(wizard.options.stock_intraday):
                wizard.options.stock_intraday.setChecked(parameters.stock_intraday_enabled)
            wizard.options.stock_confirmed = parameters.stock_intraday_confirmed
            wizard.options.refresh_markets()
            wizard.options.interval.setCurrentIndex(wizard.options.interval.findData(parameters.bar_interval))
            wizard.options.stop.setText(str(parameters.stop_fraction * 100))
            wizard.options.entry_amount.setText(str(parameters.entry_amount))
            wizard.options.contracts.setValue(parameters.contracts)
            wizard.options.instrument_rule.setCurrentIndex(wizard.options.instrument_rule.findData(parameters.instrument_rule))
        wizard.market.setCurrentIndex(wizard.market.findData(strategy.market))
        wizard.instrument.setCurrentIndex(wizard.instrument.findData(strategy.resolved_instrument_id or strategy.instrument_id))
        wizard.account.setCurrentIndex(wizard.account.findData(strategy.account_ref))
        minimum, maximum = strategy.policy_label.split(':')[1].split('-')
        wizard.minimum.setValue(int(minimum))
        wizard.maximum.setValue(int(maximum))
        wizard.name.setText(strategy.name)
        wizard.allocation.setText(str(strategy.allocation))
        wizard.risk.setCurrentIndex(wizard.risk.findData(strategy.risk_fraction))
        wizard.expiry_action.setCurrentIndex(wizard.expiry_action.findData(strategy.expiry_action))
        if strategy.expiry_action == 'ROLL':
            wizard.roll_contract.setCurrentIndex(wizard.roll_contract.findData(strategy.roll_contract_id))
        # The View does not include the original direction/rule form. Ask for
        # explicit choices in the wizard instead of silently changing either.
        wizard.direction.setCurrentIndex(-1)
        wizard.rules.setCurrentIndex(-1)
        wizard.error.setText(ui_text('u3.revision_review'))
