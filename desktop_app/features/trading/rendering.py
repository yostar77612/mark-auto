"""Read-model projection into tables; each market uses the same typed widgets."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiState
from desktop_app.features.trading.labels import policy_label, state_label
from desktop_app.features.trading.widgets import rows
from desktop_app.features.trading.reconciliation_rows import reconciliation_cells
from desktop_app.features.trading.trading_page import refresh_position_details, position_quantity, position_time
from desktop_app.features.trading.strategy_controls import recent_signal_text
from desktop_app.shell.theme import align_table_item, set_financial_item, theme_colors


def render_tables(window, state: UiState, *, state_changed: bool) -> None:
    if state_changed:
        _render_strategies(window, state)
        _render_orders(window, state)
        _render_accounts(window, state)
        _render_reconciliation(window, state)
    _render_positions(window, state)
    _render_markets(window, state)
    _render_performance(window, state)


def _render_strategies(self, state: UiState) -> None:
    rows(
        self.strategies,
        tuple(
            (
                f'{item.strategy_id}:{item.version}',
                (
                    item.name,
                    str(item.version),
                    self._market_label(item.market),
                    item.instrument_id,
                    policy_label(item.policy_label),
                    state_label(item.state),
                    item.account_ref,
                    state_label(item.evidence),
                    self._environment_label(item.environment),
                    f'{item.today_pnl:,.2f}' if item.today_pnl is not None else ui_text('watch.unknown'),
                    recent_signal_text(item.recent_signal),
                ),
            )
            for item in state.strategies
        ),
    )
    for row_index, strategy in enumerate(state.strategies):
        for column in range(self.strategies.columnCount()):
            item = self.strategies.item(row_index, column)
            item.setToolTip(item.text())
        pnl = self.strategies.item(row_index, 9)
        align_table_item(pnl, numeric=True)
        set_financial_item(self.strategies, pnl, strategy.today_pnl)
        if strategy.today_pnl is None:
            pnl.setForeground(QColor(theme_colors(self.strategies)['disabled_text']))
    self.strategies_empty.setVisible(not state.strategies)


def _render_positions(self, state: UiState) -> None:
    rows(
        self.positions,
        tuple(
            (
                item.lot_id,
                (
                    item.instrument_id,
                    f'{ui_text("v2.long" if item.direction.value == "BUY" else "v2.short")} · {position_quantity(item.quantity, item.unit)}',
                    position_quantity(item.sellable_quantity, item.unit).split(' ')[0],
                    policy_label(item.policy_label),
                    item.account_ref,
                    f'{item.strategy_id} · v{item.strategy_version}',
                    item.entry_day,
                    str(item.held_days),
                    state_label(item.exit_window),
                    state_label(item.protection),
                    state_label(item.source),
                    position_time(item.quote_time),
                ),
            )
            for item in state.positions
        ),
    )
    refresh_position_details(self.positions)


def _render_orders(self, state: UiState) -> None:
    rows(
        self.orders,
        tuple(
            (
                item.order_id,
                (
                    item.instrument_id,
                    ui_text('v2.long' if item.side.value == 'BUY' else 'v2.short'),
                    position_quantity(item.quantity, item.unit),
                    position_quantity(item.filled, item.unit),
                    state_label(item.state),
                    ui_text('v2.exit_order' if item.reduce_only else 'v2.entry_order'),
                    item.account_ref,
                ),
            )
            for item in state.orders
        ),
    )

    by_id = {item.order_id: item for item in state.orders}
    for row in range(self.orders.rowCount()):
        item = by_id[self.orders.item(row, 0).data(Qt.ItemDataRole.UserRole)]
        for column, quantity in ((2, item.quantity), (3, item.filled)):
            cell = self.orders.item(row, column)
            cell.setToolTip(f'{quantity:,} {self._unit_label(item.unit.value)}')
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.orders.item(row, 6).setToolTip(item.account_ref)


def _render_reconciliation(self, state: UiState) -> None:
    rows(
        self.reconciliation,
        tuple((f'{item.kind}:{item.account_ref}:{item.instrument_id}:{item.broker_order_ref}', reconciliation_cells(item)) for item in state.reconciliation),
    )
    self.reconciliation_status.setText(
        ui_text('v2.reconciliation_count').format(len(state.reconciliation))
        if state.reconciliation
        else ui_text('v2.reconciliation_clear' if state.reconciliation_verified else 'v2.reconciliation_unknown')
    )


def _render_markets(self, state: UiState) -> None:
    rows(
        self.markets,
        tuple(
            (
                item.instrument_id,
                (
                    item.instrument_id,
                    self._market_label(item.market),
                    self._unit_label(item.unit.value),
                    str(item.price) if item.price is not None else ui_text('v2.unavailable'),
                    item.quote_time,
                    state_label(item.availability),
                    state_label(item.source),
                ),
            )
            for item in state.markets
        ),
    )


def _render_performance(self, state: UiState) -> None:
    self.performance.horizontalHeaderItem(5).setToolTip(ui_text('v2.performance_freshness_hint'))
    self.performance.horizontalHeaderItem(11).setToolTip(ui_text('v2.performance_freshness_hint'))
    rows(
        self.performance,
        tuple(
            (
                f'{item.strategy_id}:{item.version}',
                (
                    f'{item.strategy_id} · v{item.version}',
                    self._market_label(item.market),
                    policy_label(item.policy_label),
                    self._environment_label(item.environment),
                    str(item.net_pnl) if item.net_pnl is not None else ui_text('v2.valuation_unknown'),
                    str(item.unrealized_pnl) if item.unrealized_pnl is not None else ui_text('v2.valuation_unknown'),
                    str(item.costs),
                    str(item.attributed_pnl) if item.attributed_pnl is not None else ui_text('v2.drawdown_unknown'),
                    str(item.drawdown) if item.drawdown is not None else ui_text('v2.drawdown_unknown'),
                    item.holding_days,
                    ui_text('v2.drawdown_complete' if item.drawdown_coverage == 'COMPLETE' else 'v2.drawdown_incomplete'),
                    item.drawdown_as_of or ui_text('v2.drawdown_not_recorded'),
                ),
            )
            for item in state.performance
        ),
    )


def _render_accounts(self, state: UiState) -> None:
    rows(
        self.accounts,
        tuple(
            (
                item.account_ref,
                (
                    item.account_ref,
                    self._environment_label(item.environment),
                    self._market_label(item.market),
                    str(item.allocation),
                    state_label(item.readiness),
                ),
            )
            for item in state.accounts
        ),
    )
