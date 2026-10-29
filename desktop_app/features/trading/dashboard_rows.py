"""Pure dashboard display rows and status text; no Qt, IO or financial calculations.

Application owns all money, daily counts and freshness. Existing exit windows,
quote times and holding days are displayed without deriving duplicate facts.
"""

from dataclasses import dataclass

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import MarketHealthView, UiState
from quantlab.trading.domain.models import Environment, Side
from desktop_app.features.trading.labels import event_label, policy_label, state_label
from desktop_app.features.trading.reconciliation_rows import reconciliation_cells
from desktop_app.features.trading.market_watch_rows import freshness_text, value_text


@dataclass(frozen=True)
class StatusLight:
    key: str
    level: str
    label: str


def status_lights(state: UiState) -> tuple[StatusLight, ...]:
    connection = {
        'CONNECTED': ('live', ui_text('dashboard.status.connected')),
        'DISCONNECTED': ('red', ui_text('dashboard.status.disconnected')),
        'CONNECTING': ('warning', ui_text('dashboard.status.connecting')),
        'UNKNOWN': ('muted', ui_text('watch.unknown')),
    }[state.market_connection]
    if state.environment is Environment.LOCAL:
        connection = ('muted', ui_text('dashboard.status.local'))
    priority = {'STOPPED': 0, 'DELAYED': 1, 'UNKNOWN': 2, 'CLOSED': 3, 'LIVE': 4}
    health = min(state.market_health.instruments, key=lambda item: priority[item.freshness], default=MarketHealthView())
    market_label, market_level = freshness_text(health)
    if health.freshness == 'STOPPED':
        market_level = 'red'
    engine_level = (
        'live' if state.engine_state == 'RUNNING' else 'muted' if state.engine_state == 'CLOSED' else 'warning' if state.engine_state == 'CONNECTING' else 'red'
    )
    return (
        StatusLight('broker', connection[0], ui_text('dashboard.status.broker').format(connection[1])),
        StatusLight('market', market_level, ui_text('dashboard.status.market').format(market_label)),
        StatusLight('engine', engine_level, ui_text('dashboard.status.engine').format(state_label(state.engine_state))),
        StatusLight(
            'reconciliation',
            'live' if state.reconciliation_verified else 'red',
            ui_text('dashboard.status.reconciled') if state.reconciliation_verified else ui_text('dashboard.status.pending'),
        ),
    )


def red_summary_text(state: UiState) -> str:
    labels = tuple(light.label for light in status_lights(state) if light.level == 'red')
    return ui_text('dashboard.status.attention').format(ui_text('dashboard.separator').join(labels)) if labels else ''


def today_summary_items(state: UiState) -> tuple[tuple[str, str], ...]:
    return (
        (ui_text('dashboard.today.net_pnl'), value_text(state.daily_pnl)),
        (ui_text('dashboard.today.unrealized_pnl'), value_text(state.unrealized_pnl)),
        (ui_text('dashboard.today.remaining_risk'), value_text(state.remaining_risk)),
        (ui_text('dashboard.today.remaining_loss'), value_text(state.remaining_daily_loss)),
        (ui_text('dashboard.today.fills'), value_text(state.today_fill_count)),
    )


def strategy_rows(state: UiState) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            f'{item.strategy_id}:{item.version}',
            (
                item.name,
                str(item.version),
                {
                    'RUNNING': ui_text('dashboard.strategy.running'),
                    'PAUSED': ui_text('dashboard.strategy.paused'),
                    'RISK_STOPPED': ui_text('dashboard.strategy.risk_stopped'),
                }.get(item.activity_state, state_label(item.activity_state) if item.activity_state is not None else ui_text('watch.unknown')),
                value_text(item.today_order_count),
                value_text(item.today_pnl),
            ),
        )
        for item in state.strategies
    )


def position_rows(state: UiState) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            item.lot_id,
            (
                item.instrument_id,
                f'{item.strategy_id}:{item.strategy_version}',
                ui_text('v2.long') if item.direction is Side.BUY else ui_text('v2.short'),
                str(item.quantity),
                str(item.held_days),
                state_label(item.exit_window),
                value_text(item.unrealized_pnl) if item.quote_freshness == 'LIVE' else ui_text('watch.unknown'),
                value_text(item.quote_time),
            ),
        )
        for item in state.positions
    )


def issue_rows(state: UiState) -> tuple[str, ...]:
    return state.issues or (ui_text('v2.no_issues'),)


def event_rows(state: UiState) -> tuple[str, ...]:
    return tuple(event_label(event) for event in reversed(state.events))


def data_status_text(state: UiState) -> str:
    if not state.financial_facts_verified:
        return ui_text('v2.context_facts_pending')
    return ui_text('v2.local_data') if state.synthetic_data else ui_text('v2.external_data')


def today_summary_text(state: UiState) -> str:
    return ui_text('dashboard.separator').join(ui_text('dashboard.summary.item').format(label, value) for label, value in today_summary_items(state))


def strategy_summary_text(state: UiState) -> str:
    return '\n'.join(
        ui_text('dashboard.strategy.summary').format(item.name, item.version, policy_label(item.policy_label), state_label(item.state))
        for item in state.strategies[-10:]
    ) or ui_text('v2.no_strategies')


def pending_issue_rows(state: UiState) -> tuple[str, ...]:
    return issue_rows(state) + tuple(
        ui_text('v2.reconciliation_overview').format(*reconciliation_cells(item)[:2], *reconciliation_cells(item)[3:6]) for item in state.reconciliation
    )
