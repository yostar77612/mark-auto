"""Six workspaces backed exclusively by typed Application commands/read models."""

from dataclasses import replace
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QFileDialog, QMainWindow, QMessageBox, QVBoxLayout

from desktop_strings import ui_text
from quantlab.trading.application.contracts import BrokerSettings, SettingsForm, StrategyForm, TradingFacade, UiAction, UiCommand, UiReceipt, UiState
from quantlab.trading.domain.models import Environment

from .labels import event_label, policy_label, state_label
from .widgets import fit_available_screen, label, selected_id
from .rendering import reconciliation_cells, render_tables
from .workspaces import build
from .wizard import StrategyWizard


class _Operation(QThread):
    completed = Signal(object, object)
    failed = Signal()

    def __init__(self, facade: TradingFacade, command: UiCommand | None, parent, *, refresh_before: bool = False):
        super().__init__(parent)
        self.facade = facade
        self.command = command
        self.refresh_before = refresh_before

    def run(self) -> None:
        try:
            if self.refresh_before and self.command is not None:
                self.command = replace(self.command, expected_version=self.facade.snapshot().version)
            receipt = (
                self._save_draft()
                if self.command is not None and self.command.action is UiAction.CREATE_STRATEGY
                else (self.facade.execute(self.command) if self.command is not None else None)
            )
            state = self.facade.snapshot()
        except Exception:
            self.failed.emit()
        else:
            self.completed.emit(state, receipt)

    def _save_draft(self) -> UiReceipt:
        # A draft is metadata, never deployment or an order. Retain its exact
        # immutable form/context; only an explicit CAS refusal permits one retry.
        command = self.command
        for attempt in range(2):
            current = self.facade.snapshot()
            if (
                command.strategy is None
                or current.environment is not command.strategy.environment
                or (command.context_id and current.context_id != command.context_id)
                or (command.context_epoch is not None and current.context_epoch != command.context_epoch)
            ):
                return UiReceipt(False, 'state_conflict', '')
            self.command = replace(command, expected_version=current.version)
            receipt = self.facade.execute(self.command)
            if receipt.accepted or receipt.code != 'state_conflict' or receipt.reference or attempt:
                return receipt
            after = self.facade.snapshot()
            if after.version == self.command.expected_version:
                return receipt
        return receipt


class TradingWindow(QMainWindow):
    legacy_requested = Signal(str)
    close_ui_requested = Signal()

    def __init__(self, facade: TradingFacade, initial_state: UiState, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.state = initial_state
        self._operation: _Operation | None = None
        self._priority_operation: _Operation | None = None
        self._rendered_version: tuple[int, int, int] | None = None
        self._context_rendering = False
        self._settings_dirty = False
        self._last_feedback = ''
        self._engine_reachable = True
        self._connecting_request = False
        self._screen_hooked = False
        self._pending_wizard = None
        self.setObjectName('multi_market_window')
        self.setWindowTitle(ui_text('v2.title'))
        font = self.font()
        font.setPointSize(max(11, font.pointSize()))
        self.setFont(font)
        self.resize(1180, 720)
        self.setMinimumSize(600, 300)
        build(self)
        self.apply_state(initial_state)
        self.poll = QTimer(self)
        self.poll.setInterval(1000)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()
        QShortcut(QKeySequence('Ctrl+N'), self, activated=self.new_strategy)
        QShortcut(QKeySequence('F5'), self, activated=self.refresh)
        QShortcut(QKeySequence('Ctrl+1'), self, activated=lambda: self.navigation.setCurrentRow(0))
        QShortcut(QKeySequence('Ctrl+4'), self, activated=lambda: self.navigation.setCurrentRow(3))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._screen_hooked and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(lambda _screen: fit_available_screen(self))
            self._screen_hooked = True
        QTimer.singleShot(0, lambda: fit_available_screen(self))

    def _dirty_settings(self) -> None:
        if not self._context_rendering:
            self._settings_dirty = True

    def _feedback(self, text: str) -> None:
        self._last_feedback = text
        self.notice.setText(text)

    def refresh(self) -> None:
        self._run(None)

    def command(
        self,
        action: UiAction,
        target_id: str = '',
        *,
        strategy: StrategyForm | None = None,
        settings: SettingsForm | None = None,
        environment: Environment | None = None,
        account_ref: str = '',
        destination_strategy_id: str = '',
        broker_settings: BrokerSettings | None = None,
        context_id: str | None = None,
        profile_ref: str = '',
    ) -> None:
        self._run(
            UiCommand(
                action,
                self.state.version,
                target_id,
                strategy,
                settings,
                environment,
                account_ref,
                destination_strategy_id,
                broker_settings,
                self.state.context_id if context_id is None else context_id,
                profile_ref,
                self.state.context_epoch if self.state.contexts else None,
            )
        )

    def _run(self, command: UiCommand | None) -> None:
        if self._priority_operation is not None:
            if command is not None:
                self._feedback(ui_text('v2.stop_in_progress'))
            return
        if self._operation is not None:
            if command is not None:
                if command.action == UiAction.STOP_NEW:
                    self._priority_stop()
                else:
                    self._feedback(ui_text('v2.busy'))
            return
        # Navigation is read-only: refresh its observation stamp while keeping
        # the selected context epoch. Actual book mutations retain the exact
        # version the user reviewed and are never silently refreshed/retried.
        operation = _Operation(self.facade, command, self, refresh_before=command is not None and command.action is UiAction.SWITCH_CONTEXT)
        self._operation = operation
        operation.completed.connect(self._completed)
        operation.failed.connect(self._failed)
        operation.finished.connect(self._finished)
        if command is not None:
            self._feedback(ui_text('v2.working'))
        operation.start()

    def _completed(self, state: UiState, receipt: UiReceipt | None) -> None:
        action = self._operation.command.action if self._operation is not None and self._operation.command is not None else None
        self._result(state, receipt, action)

    def _priority_stop(self) -> None:
        operation = _Operation(
            self.facade,
            UiCommand(
                UiAction.STOP_NEW, self.state.version, context_id=self.state.context_id, context_epoch=self.state.context_epoch if self.state.contexts else None
            ),
            self,
            refresh_before=True,
        )
        self._priority_operation = operation
        operation.completed.connect(self._priority_completed)
        operation.failed.connect(self._failed)
        operation.finished.connect(self._priority_finished)
        self._feedback(ui_text('v2.stop_in_progress'))
        operation.start()

    def _priority_completed(self, state: UiState, receipt: UiReceipt | None) -> None:
        self._result(state, receipt, UiAction.STOP_NEW)

    def _priority_finished(self) -> None:
        operation = self._priority_operation
        self._priority_operation = None
        if operation is not None:
            operation.deleteLater()

    def _result(self, state: UiState, receipt: UiReceipt | None, action: UiAction | None) -> None:
        if self._stamp(state) < self._stamp(self.state):
            return
        self._engine_reachable = True
        if receipt is not None and receipt.accepted:
            if action == UiAction.SAVE_SETTINGS:
                self._settings_dirty = False
            elif action == UiAction.SAVE_BROKER_SETTINGS:
                self.broker_panel.dirty = False
        if action in (UiAction.SWITCH_CONTEXT, UiAction.ADD_CONTEXT):
            self._rendered_version = None
        self.apply_state(state)
        if receipt is not None:
            message = receipt.message or ui_text('v2.completed' if receipt.accepted else 'v2.connection_failed')
            if not receipt.accepted and receipt.code == 'state_conflict':
                message = receipt.message or ui_text('v2.state_conflict')
                if action is UiAction.CREATE_STRATEGY and self._pending_wizard is not None:
                    message += ' ' + ui_text('v2.draft_retained')
            if receipt.accepted and action in (UiAction.CREATE_STRATEGY, UiAction.SWITCH_CONTEXT):
                self._clear_pending_wizard()
            if receipt.accepted and receipt.code == 'connection_pending':
                self._connecting_request = state.engine_state == 'CONNECTING'
                message = ui_text('v2.connection_pending' if self._connecting_request else 'v2.connection_request_finished')
            if action is UiAction.SWITCH_CONTEXT and not receipt.accepted:
                message = ui_text('v2.context_switch_failed').format(self._environment_label(state.environment), state.account_ref, message)
            self._feedback(message)
            self.notice.setAccessibleName(receipt.code)
            if receipt.accepted and receipt.reference:
                for row in range(self.strategies.rowCount()):
                    if self.strategies.item(row, 0).data(Qt.ItemDataRole.UserRole) == receipt.reference:
                        self.strategies.selectRow(row)
                        break

    def _failed(self) -> None:
        self._engine_reachable = False
        self._feedback(ui_text('v2.connection_failed'))

    def _finished(self) -> None:
        operation = self._operation
        self._operation = None
        if operation is not None:
            operation.deleteLater()

    def new_strategy(self) -> None:
        self._wizard('')

    def new_version(self) -> None:
        identity = selected_id(self.strategies)
        strategy = next((item for item in self.state.strategies if f'{item.strategy_id}:{item.version}' == identity), None)
        if strategy is not None:
            self._wizard(strategy.strategy_id)
        else:
            self._feedback(ui_text('v2.select_strategy'))

    def _wizard(self, parent_strategy_id: str) -> None:
        if self._operation is not None or self._priority_operation is not None:
            self._feedback(ui_text('v2.busy'))
            return
        context = (self.state.context_id, self.state.context_epoch, self.state.environment, self.state.account_ref, parent_strategy_id)
        if self._pending_wizard is None or self._pending_wizard[0] != context:
            self._clear_pending_wizard()
            self._pending_wizard = (context, StrategyWizard(self.state, self, parent_strategy_id=parent_strategy_id))
        wizard = self._pending_wizard[1]
        if wizard.exec() == StrategyWizard.DialogCode.Accepted:
            self.command(UiAction.CREATE_STRATEGY, strategy=wizard.form())
        else:
            self._clear_pending_wizard()

    def _clear_pending_wizard(self) -> None:
        if self._pending_wizard is not None:
            self._pending_wizard[1].deleteLater()
            self._pending_wizard = None

    def _strategy_action(self, action: UiAction) -> None:
        identity = selected_id(self.strategies)
        if identity:
            self.command(action, identity)
        else:
            self._feedback(ui_text('v2.select_strategy'))

    def _confirm(self, text: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, ui_text('v2.review_scope'), text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.button(QMessageBox.StandardButton.Yes).setText(ui_text('v2.confirm'))
        box.button(QMessageBox.StandardButton.Cancel).setText(ui_text('v2.cancel'))
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def deploy_selected(self) -> None:
        identity = selected_id(self.strategies)
        strategy = next((item for item in self.state.strategies if f'{item.strategy_id}:{item.version}' == identity), None)
        if strategy is None:
            self._feedback(ui_text('v2.select_strategy'))
            return
        if strategy.allocation <= 0:
            self._feedback(ui_text('v2.strategy_config_missing'))
            return
        summary = ui_text('v2.deploy_summary').format(
            strategy.name,
            strategy.version,
            self._environment_label(strategy.environment),
            strategy.account_ref,
            strategy.instrument_id,
            policy_label(strategy.policy_label),
            strategy.allocation,
            strategy.risk_fraction * 100,
        )
        summary += '\n' + ui_text('v2.expiry_summary').format(
            ui_text('v2.expiry_roll' if strategy.expiry_action == 'ROLL' else 'v2.expiry_exit'), strategy.roll_contract_id or ui_text('v2.no_roll_target')
        )
        if self._confirm(summary):
            self.command(UiAction.DEPLOY, identity)

    def flatten_selected(self) -> None:
        if self.reconciliation.selectedItems():
            self._feedback(ui_text('v2.reconciliation_cannot_flatten'))
            return
        identity = selected_id(self.positions)
        position = next((item for item in self.state.positions if item.lot_id == identity), None)
        if position is None:
            self._feedback(ui_text('v2.select_position'))
            return
        if not position.account_ref:
            self._feedback(ui_text('v2.position_account_missing'))
            return
        summary = ui_text('v2.flatten_summary').format(
            position.account_ref,
            position.instrument_id,
            position.quantity,
            self._unit_label(position.unit.value),
            position.sellable_quantity,
            state_label(position.source),
        )
        summary += '\n' + ui_text('v2.flatten_direction').format(ui_text('v2.long' if position.direction.value == 'BUY' else 'v2.short'))
        if self._confirm(summary):
            self.command(UiAction.FLATTEN, identity)

    def transfer_selected(self) -> None:
        identity = selected_id(self.positions)
        if not identity:
            self._feedback(ui_text('v2.select_position'))
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle(ui_text('v2.transfer'))
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('v2.transfer_hint'))
        destinations = QComboBox()
        for strategy in self.state.strategies:
            destinations.addItem(f'{strategy.name} · v{strategy.version} · {policy_label(strategy.policy_label)}', f'{strategy.strategy_id}:{strategy.version}')
        layout.addWidget(destinations)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText(ui_text('v2.confirm_transfer'))
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText(ui_text('v2.cancel'))
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        if dialog.exec() == QDialog.DialogCode.Accepted and destinations.currentData():
            self.command(UiAction.TRANSFER, identity, destination_strategy_id=destinations.currentData())

    def shutdown_engine(self) -> None:
        summary = (
            ui_text('v2.shutdown_summary').format(len(self.state.positions), len(self.state.orders))
            if self.state.financial_facts_verified
            else ui_text('v2.shutdown_unverified')
        )
        if self._confirm(summary):
            self.command(UiAction.SHUTDOWN_ENGINE)

    def save_settings(self) -> None:
        try:
            settings = SettingsForm(Decimal(self.stock_budget.text()), Decimal(self.futures_budget.text()), self.setting_risk.currentData())
            if not settings.stock_allocation.is_finite() or not settings.futures_allocation.is_finite():
                raise ValueError('nonfinite')
        except (InvalidOperation, ValueError):
            self._feedback(ui_text('v2.form_invalid'))
            return
        self.command(UiAction.SAVE_SETTINGS, settings=settings)

    def _environment_selected(self) -> None:
        if self._context_rendering:
            return
        self._populate_accounts(Environment(self.environment.currentData()))
        self._switch_context()

    def _populate_accounts(self, environment: Environment) -> None:
        self._context_rendering = True
        self.account.clear()
        if self.state.contexts:
            for item in self.state.contexts:
                if item.environment == environment:
                    for account_ref in item.account_refs:
                        caption = (item.label + ' · ' if item.label else '') + account_ref
                        if item.status != 'CONFIGURED':
                            caption += ' · ' + ui_text('v2.context_unavailable')
                        self.account.addItem(caption, (item.context_id, account_ref))
        else:
            for item in self.state.accounts:
                if item.environment == environment:
                    self.account.addItem(item.account_ref, item.account_ref)
        self._context_rendering = False

    def _switch_context(self) -> None:
        if not self._context_rendering and self.account.currentData():
            selected = self.account.currentData()
            context_id, account_ref = (selected[0], selected[1]) if self.state.contexts else ('', selected)
            if self.state.contexts and (context_id, account_ref) == (self.state.context_id, self.state.account_ref):
                return
            if self._settings_dirty or self.broker_panel.dirty:
                if not self._confirm(ui_text('v2.context_unsaved')):
                    self._rendered_version = None
                    self.apply_state(self.state)
                    return
            if self.state.positions and not self._confirm(
                ui_text('v2.context_background_book').format(self._environment_label(self.state.environment), self.state.account_ref, len(self.state.positions))
            ):
                self._rendered_version = None
                self.apply_state(self.state)
                return
            self.command(UiAction.SWITCH_CONTEXT, environment=Environment(self.environment.currentData()), account_ref=account_ref, context_id=context_id)
        elif not self._context_rendering:
            self._feedback(ui_text('v2.no_account'))

    def add_context(self) -> None:
        selected = Environment(self.environment.currentData())
        if selected is Environment.LOCAL:
            self._feedback(ui_text('v2.context_profile_broker_only'))
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('v2.context_add_profile'), '', ui_text('v2.context_profile_filter'))
        if path:
            self.command(UiAction.ADD_CONTEXT, environment=selected, profile_ref=path)

    def connect_read_only(self) -> None:
        if self.state.environment is Environment.LOCAL:
            self._feedback(ui_text('v2.context_profile_broker_only'))
            return
        if self._confirm(ui_text('v2.connect_readonly_summary').format(self._environment_label(self.state.environment), self.state.account_ref)):
            self.command(UiAction.CONNECT_READ_ONLY)

    @staticmethod
    def _environment_label(environment: Environment) -> str:
        return ui_text({Environment.LOCAL: 'v2.local', Environment.BROKER_SIMULATION: 'v2.broker_sim', Environment.LIVE: 'v2.live'}[environment])

    @staticmethod
    def _unit_label(unit: str) -> str:
        return ui_text('v2.shares' if unit == 'SHARE' else 'v2.contracts')

    @staticmethod
    def _market_label(market) -> str:
        return ui_text({'STOCK': 'v2.stock', 'INDEX_FUTURE': 'v2.index_future', 'STOCK_FUTURE': 'v2.stock_future'}[market.value])

    def apply_state(self, state: UiState) -> None:
        if self._stamp(state) < self._stamp(self.state):
            return
        freshness_changed = (
            state.financial_facts_verified != self.state.financial_facts_verified
            or tuple((item.instrument_id, item.availability) for item in state.markets)
            != tuple((item.instrument_id, item.availability) for item in self.state.markets)
            or tuple((item.strategy_id, item.version, item.net_pnl is None, item.unrealized_pnl is None) for item in state.performance)
            != tuple((item.strategy_id, item.version, item.net_pnl is None, item.unrealized_pnl is None) for item in self.state.performance)
        )
        changed_context = (state.context_epoch, state.context_id) != (self.state.context_epoch, self.state.context_id)
        if changed_context:
            self._settings_dirty = False
            self.broker_panel.dirty = False
            self._last_feedback = ''
            self._rendered_version = None
            self._connecting_request = False
            for table in (self.strategies, self.positions, self.orders, self.reconciliation):
                table.clearSelection()
                table.setCurrentCell(-1, -1)
        self.state = state
        if self._connecting_request and state.engine_state != 'CONNECTING':
            self._connecting_request = False
            self._last_feedback = ui_text('v2.connection_request_finished')
        account_caption = state.account_ref
        option = next((item for item in state.contexts if item.context_id == state.context_id), None)
        if option and option.label:
            account_caption = ui_text('v2.account_context_caption').format(state.account_ref, option.label)
        self.context.setText(
            ui_text('v2.context_line').format(
                self._environment_label(state.environment),
                account_caption,
                state_label(state.engine_state),
                state.trading_day or ui_text('v2.context_unknown_day'),
                policy_label(state.policy_label) if state.policy_label else ui_text('v2.context_no_policy'),
            )
        )
        if state.financial_facts_verified and state.daily_pnl is not None and state.remaining_risk is not None:
            self.summary.setText(
                ui_text('v2.summary_line').format(state.allocated_cash, state.daily_pnl, state.remaining_risk, state_label(state.quote_status))
            )
        else:
            self.summary.setText(ui_text('v2.summary_unknown_line').format(state.allocated_cash, state_label(state.quote_status)))
        self.notice.setText(
            ui_text('v2.issue_summary').format(len(state.issues), state.issues[0]) if state.issues else self._last_feedback or ui_text('v2.no_issues')
        )
        self.overview_step.setEnabled(state.environment == Environment.LOCAL)
        self.connect_read_only_button.setEnabled(state.environment is not Environment.LOCAL and state.engine_state == 'DISCONNECTED')
        self.add_context_button.setVisible(bool(state.contexts))
        self.overview_status.setText(
            ui_text('v2.context_facts_pending')
            if not state.financial_facts_verified
            else ui_text('v2.local_data')
            if state.synthetic_data
            else ui_text('v2.external_data')
        )
        render_version = self._stamp(state)
        if self._rendered_version == render_version and not freshness_changed:
            return
        state_changed = self._rendered_version is None or self._rendered_version[:2] != render_version[:2]
        self._rendered_version = render_version
        render_tables(self, state, state_changed=state_changed)
        if not state_changed:
            return
        self.overview_deployments.setText(
            '\n'.join(f'{item.name} · v{item.version} · {policy_label(item.policy_label)} · {state_label(item.state)}' for item in state.strategies[-10:])
            or ui_text('v2.no_strategies')
        )
        self.issue_details.clear()
        self.issue_details.addItems(list(state.issues) or [ui_text('v2.no_issues')])
        self.issue_details.addItems(
            [ui_text('v2.reconciliation_overview').format(*reconciliation_cells(item)[:2], *reconciliation_cells(item)[3:6]) for item in state.reconciliation]
        )
        self.diagnostics.setText(ui_text('v2.diagnostics').format(state.version, state.engine_state) + '\n' + '\n'.join(state.events[-20:]))
        self.events.clear()
        self.events.addItems([event_label(code) for code in state.events[-100:]])
        self._context_rendering = True
        self.environment.setCurrentIndex(self.environment.findData(state.environment))
        self._populate_accounts(state.environment)
        self._context_rendering = True
        wanted = (state.context_id, state.account_ref) if state.contexts else state.account_ref
        if state.contexts:
            selected = next((i for i in range(self.account.count()) if tuple(self.account.itemData(i)) == wanted), -1)
        else:
            selected = self.account.findData(wanted)
        self.account.setCurrentIndex(selected)
        if not self._settings_dirty:
            self.stock_budget.setText(str(state.settings.stock_allocation))
            self.futures_budget.setText(str(state.settings.futures_allocation))
            self.setting_risk.setCurrentIndex(self.setting_risk.findData(state.settings.risk_fraction))
        self._context_rendering = False
        self.broker_panel.apply(state.broker_settings, state.broker_readiness)

    @staticmethod
    def _stamp(state: UiState) -> tuple[int, int, int]:
        return state.context_epoch, state.version, state.quote_revision

    def closeEvent(self, event) -> None:
        if self._operation is not None or self._priority_operation is not None:
            self._feedback(ui_text('v2.busy'))
            event.ignore()
            return
        close_key = (
            'v2.close_unverified'
            if not self.state.financial_facts_verified
            else 'v2.close_unknown'
            if not self._engine_reachable
            else 'v2.close_already_stopped'
            if self.state.engine_state == 'CLOSED'
            else 'v2.close_summary'
        )
        if not self.property('allow_close_for_tests') and not self._confirm(
            ui_text(close_key).format(state_label(self.state.engine_state), len(self.state.positions))
        ):
            event.ignore()
            return
        self.poll.stop()
        self.close_ui_requested.emit()
        super().closeEvent(event)
