"""Facts and rule-based checks for the selected strategy, phrased as one question for the AI assistant.

Only values already shown in the trading window are used (no out-of-sample or holdout data). The text is
prefilled into the assistant's input and never sent without the user's own send and consent.
"""

from decimal import Decimal

from desktop_app.features.trading.labels import policy_label, state_label
from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Market

MAX_CHARS = 1000  # the assistant input accepts 1024 characters
RESEARCHED_STATES = ('RESEARCHED', 'ACTIVE', 'DISABLED')
STOCK_LOT = 1000


def _money(value) -> str:
    return ui_text('watch.unknown') if value is None else f'{value:,.0f}'


def _quote(state, instrument_id):
    row = next((item for item in state.markets if item.instrument_id == instrument_id), None)
    return None if row is None else row.price


def check_codes(strategy, performance, price) -> tuple[str, ...]:
    """Short codes for settings that look unreasonable; each maps to one sentence."""
    codes = []
    parameters = strategy.parameters
    if strategy.state not in RESEARCHED_STATES:
        codes.append('unresearched')
    if parameters is not None:
        if parameters.entry_amount > strategy.allocation > 0:
            codes.append('entry_over_allocation')
        if parameters.stop_fraction < Decimal('0.01'):
            codes.append('stop_tight')
        if parameters.stop_fraction > Decimal('0.10'):
            codes.append('stop_wide')
    if strategy.market is Market.STOCK and price is not None:
        lot_cost = price * STOCK_LOT
        if lot_cost > strategy.allocation:
            codes.append('allocation_below_lot')
        elif parameters is not None and lot_cost * parameters.stop_fraction > strategy.allocation * strategy.risk_fraction:
            codes.append('risk_below_lot')
    if performance is not None and performance.net_pnl is not None and performance.net_pnl < 0 and performance.costs * 2 >= -performance.net_pnl:
        codes.append('costs')
    return tuple(codes)


def explain_prompt(state, strategy) -> str:
    performance = next((item for item in state.performance if (item.strategy_id, item.version) == (strategy.strategy_id, strategy.version)), None)
    parameters = strategy.parameters
    lines = [
        ui_text('assistant.explain_intro'),
        ui_text('assistant.explain_strategy').format(strategy.name, strategy.version, strategy.instrument_id, policy_label(strategy.policy_label)),
        ui_text('assistant.explain_params').format(
            _money(strategy.allocation),
            f'{strategy.risk_fraction * 100:g}',
            ui_text('watch.unknown') if parameters is None else f'{parameters.stop_fraction * 100:g}',
            ui_text('watch.unknown') if parameters is None else _money(parameters.entry_amount),
        ),
        ui_text('assistant.explain_state').format(state_label(strategy.state), strategy.evidence or ui_text('watch.unknown')),
        ui_text('assistant.explain_results').format(
            _money(strategy.today_pnl),
            _money(None if performance is None else performance.net_pnl),
            _money(None if performance is None else performance.costs),
            _money(None if performance is None else performance.drawdown),
        ),
        ui_text('assistant.explain_checks'),
    ]
    codes = check_codes(strategy, performance, _quote(state, strategy.instrument_id))
    if codes:
        lines.extend('- ' + ui_text('assistant.explain_check_' + code) for code in codes)
    else:
        lines.append('- ' + ui_text('assistant.explain_check_none'))
    return '\n'.join(lines)[:MAX_CHARS]
