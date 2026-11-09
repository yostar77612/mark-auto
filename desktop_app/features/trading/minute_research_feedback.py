"""Pure helpers: when the research button means minute research, and how its summary is worded."""

from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Environment, HoldingKind, Market


def minute_capable(strategy) -> bool:
    """Typed micro-TAIEX day-trade strategy in the broker simulation, researched on 1m/5m bars."""
    return (
        strategy is not None
        and strategy.environment is Environment.BROKER_SIMULATION
        and strategy.parameters is not None
        and strategy.holding_kind is HoldingKind.INTRADAY
        and strategy.market is Market.INDEX_FUTURE
        and strategy.parameters.bar_interval in ('1m', '5m')
    )


def minute_summary(reference: str) -> str:
    first, last, interval, trades, net, costs, drawdown, bars = reference.split('|')
    return ui_text('research.minute.summary').format(first, last, interval, trades, net, costs, drawdown, bars)


def minute_error_hint(code: str) -> str:
    return (
        ui_text('research.minute.too_few_days')
        if code == 'calendar_missing'
        else ui_text('research.minute.need_connection')
        if code == 'capability_missing'
        else ''
    )
