"""Durable, version-owned observations of net liquidation PnL.

These are recorded valuation points, never training results or a promise that
every intervening quote was observed. Capital allocations and reservations are
not losses. The append-only state journal retains each committed observation.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import PositionLot, Side
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.quote_stats import unrealized_pnl
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer, trading_date

if TYPE_CHECKING:
    from .engine import TradingEngine
    from .state import AppState

ZERO = Decimal('0')
BASIS = 'RECORDED_NET_LIQUIDATION_V1'
Key = tuple[str, int]


@dataclass(frozen=True)
class VersionEquityTrack:
    strategy_id: str
    version: int
    first_at: datetime
    last_at: datetime
    trade_date: date
    equity: Decimal
    peak: Decimal
    max_drawdown: Decimal | None
    history_complete: bool
    samples: int = 1
    cashflow_adjustment: Decimal = ZERO
    lot_ids: tuple[str, ...] = ()
    basis: str = BASIS
    realized_adjustment: Decimal = ZERO
    daily_baseline: Decimal | None = None

    def __post_init__(self) -> None:
        identity(self.strategy_id)
        integer(self.version, 'strategy version', 1)
        aware(self.first_at)
        aware(self.last_at)
        trading_date(self.trade_date)
        integer(self.samples, 'valuation observations', 1)
        for name in ('equity', 'peak', 'cashflow_adjustment', 'realized_adjustment'):
            decimal_value(getattr(self, name), name)
        if self.max_drawdown is not None:
            decimal_value(self.max_drawdown, 'maximum drawdown', nonnegative=True)
        if self.daily_baseline is not None:
            decimal_value(self.daily_baseline, 'daily baseline')
        if (
            type(self.history_complete) is not bool
            or self.history_complete != (self.max_drawdown is not None)
            or self.first_at > self.last_at
            or self.peak < self.equity
            or self.basis != BASIS
            or type(self.lot_ids) is not tuple
            or self.lot_ids != tuple(sorted(set(self.lot_ids)))
        ):
            raise DomainError('validation_failed', 'version equity observation')
        for lot_id in self.lot_ids:
            identity(lot_id)


def seed_track(strategy_id: str, version: int, now: datetime, day: date) -> VersionEquityTrack:
    """Only a newly created, unexposed version has a proven zero baseline."""
    return VersionEquityTrack(strategy_id, version, now, now, day, ZERO, ZERO, ZERO, True, daily_baseline=ZERO)


@decimal_operation
def unrealized_liquidation(engine: 'TradingEngine', lot: PositionLot) -> Decimal:
    """The same executable-side, fee/slippage basis used by portfolio risk."""
    if not lot.quantity:
        return ZERO
    spec = engine.catalog.resolve(lot.instrument_id)
    quote = engine.quotes.get(lot.instrument_id)
    if quote is None or not 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30:
        raise DomainError('stale_quote', 'open position valuation is unknown')
    sign = 1 if lot.direction is Side.BUY else -1
    price = quote.bid if sign == 1 else quote.ask
    side = Side.SELL if sign == 1 else Side.BUY
    cost = lot.entry_price * lot.quantity * spec.multiplier * sign + (
        engine.fees.transaction(spec, side, price, lot.quantity) + engine.fees.slippage(spec, lot.quantity, legs=1, prices=(price,))
    )
    return cast(Decimal, unrealized_pnl(price, lot.quantity * sign, spec, cost, freshness=Freshness.LIVE))


def _next_track(
    previous: VersionEquityTrack | None,
    key: Key,
    equity: Decimal,
    adjustment: Decimal,
    realized_adjustment: Decimal,
    lots: tuple[str, ...],
    now: datetime,
    day: date,
) -> VersionEquityTrack:
    if previous is None:
        # A legacy snapshot has no trustworthy version-specific historical
        # peak. Observing today's equity cannot manufacture its missing prefix.
        return VersionEquityTrack(
            *key, now, now, day, equity, equity, None, False, cashflow_adjustment=adjustment, realized_adjustment=realized_adjustment, lot_ids=lots
        )
    if now < previous.last_at:
        return replace(previous, max_drawdown=None, history_complete=False)
    if (now, equity, adjustment, realized_adjustment, lots) == (
        previous.last_at,
        previous.equity,
        previous.cashflow_adjustment,
        previous.realized_adjustment,
        previous.lot_ids,
    ):
        return previous
    peak = max(previous.peak, equity)
    drawdown = max(previous.max_drawdown, peak - equity) if previous.history_complete else None
    return replace(
        previous,
        last_at=now,
        trade_date=day,
        equity=equity,
        peak=peak,
        max_drawdown=drawdown,
        samples=previous.samples + 1,
        cashflow_adjustment=adjustment,
        realized_adjustment=realized_adjustment,
        lot_ids=lots,
        daily_baseline=previous.daily_baseline if day == previous.trade_date else None,
    )


@decimal_operation
def advance_tracks(engine: 'TradingEngine', *, proposed_state: 'AppState | None' = None) -> tuple[VersionEquityTrack, ...]:
    """Prepare tracks without publishing state; commit with the owning transition.

    A policy handoff supplies its proposed owner state so marked book value is
    frozen in that same durable append, before any later quote or restart.
    """
    state = engine.state if proposed_state is None else proposed_state
    keys = tuple((s.strategy_id, s.version) for s in state.strategies)
    values = dict.fromkeys(keys, ZERO)
    previous = {(t.strategy_id, t.version): t for t in state.performance_tracks}
    adjustments = {key: previous[key].cashflow_adjustment if key in previous else ZERO for key in keys}
    realized_adjustments = {key: previous[key].realized_adjustment if key in previous else ZERO for key in keys}
    owners = {lot_id: (t.strategy_id, t.version) for t in state.performance_tracks for lot_id in t.lot_ids}
    entries = {o.order_id: o for o in state.orders if not o.plan.reduce_only}
    lots_by_key: dict[Key, list[str]] = {key: [] for key in keys}
    for order in entries.values():
        key = order.plan.strategy_id, order.plan.strategy_version
        if key in values:
            values[key] -= order.costs  # Actual entry fees, including partial fills.
    for lot in state.positions:
        key = lot.strategy_id, lot.strategy_version
        if key not in values:
            continue
        component = lot.realized_pnl + unrealized_liquidation(engine, lot)
        values[key] += component
        lots_by_key[key].append(lot.lot_id)
        entry = entries.get(lot.lot_id)
        original = (entry.plan.strategy_id, entry.plan.strategy_version) if entry else key
        old_owner = owners.get(lot.lot_id, original)
        if old_owner != key and old_owner in adjustments:
            # Explicit policy handoff moves the marked book value, not profit.
            # Preserve its prior owner's result and give the receiver a neutral
            # starting book; future gains/losses then accrue to that receiver.
            adjustments[old_owner] += component
            adjustments[key] -= component
            # Keep already executed closes with their original order owner.
            # Only this genuinely realized component belongs in cash results;
            # the rest of the marked handoff is not a newly executed profit.
            realized_adjustments[old_owner] += lot.realized_pnl
            realized_adjustments[key] -= lot.realized_pnl
    now, day = engine.clock.now(), state.trading_day
    result = tuple(
        _next_track(
            previous.get(key), key, values[key] + adjustments[key], adjustments[key], realized_adjustments[key], tuple(sorted(lots_by_key[key])), now, day
        )
        for key in keys
    )
    return (*tuple(track for key, track in previous.items() if key not in values), *result)
