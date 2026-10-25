"""Read-model projection into tables; each market uses the same typed widgets."""

from desktop_strings import ui_text
from quantlab.trading.application.contracts import ReconciliationView, UiState
from .labels import policy_label, state_label
from .widgets import rows


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
                ),
            )
            for item in state.strategies
        ),
    )


def _render_positions(self, state: UiState) -> None:
    rows(
        self.positions,
        tuple(
            (
                item.lot_id,
                (
                    item.instrument_id,
                    f'{ui_text("v2.long" if item.direction.value == "BUY" else "v2.short")} · {item.quantity} {self._unit_label(item.unit.value)}',
                    str(item.sellable_quantity),
                    policy_label(item.policy_label),
                    item.account_ref,
                    f'{item.strategy_id} · v{item.strategy_version}',
                    item.entry_day,
                    str(item.held_days),
                    state_label(item.exit_window),
                    state_label(item.protection),
                    state_label(item.source),
                    item.quote_time,
                ),
            )
            for item in state.positions
        ),
    )


def _render_orders(self, state: UiState) -> None:
    rows(
        self.orders,
        tuple(
            (
                item.order_id,
                (
                    item.instrument_id,
                    ui_text('v2.long' if item.side.value == 'BUY' else 'v2.short'),
                    f'{item.quantity} {self._unit_label(item.unit.value)}',
                    str(item.filled),
                    state_label(item.state),
                    ui_text('v2.exit_order' if item.reduce_only else 'v2.entry_order'),
                    item.account_ref,
                ),
            )
            for item in state.orders
        ),
    )


def reconciliation_cells(item: ReconciliationView) -> tuple[str, ...]:
    unit = ui_text('v2.shares' if item.unit.value == 'SHARE' else 'v2.contracts')

    def quantity(value: int | None) -> str:
        return ui_text('v2.reconciliation_quantity_unknown') if value is None else f'{value:+,} {unit}'

    delta = None if item.local_quantity is None or item.broker_quantity is None else item.broker_quantity - item.local_quantity
    status = state_label(item.status)
    if status == item.status:
        status = ui_text('v2.reconciliation_pending')
    return (
        item.account_ref,
        item.instrument_id,
        ui_text('v2.reconciliation_position' if item.kind == 'POSITION' else 'v2.reconciliation_order'),
        quantity(item.local_quantity),
        quantity(item.broker_quantity),
        quantity(delta),
        quantity(item.sellable_quantity),
        item.broker_order_ref or ui_text('v2.reconciliation_not_applicable'),
        status,
        item.as_of,
    )


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
                    str(item.net_pnl),
                    str(item.unrealized_pnl),
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
