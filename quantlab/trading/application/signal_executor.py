"""Pure completed-bar target decisions; order submission belongs to the M2 engine."""

from datetime import datetime

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.signal_strategy import AutoStrategy, SignalBar, SizingKind, TargetIntent, apply_direction, desired_target, window_bars
from quantlab.trading.ports.signals import SignalSource


class SignalExecutor:
    """The concrete contract is resolved by composition, never by the signal function.

    No environment, run-state or gateway lives here: LOCAL research uses exactly
    this decision path too. A future engine integration must gate new entries and
    submit reversal legs close-first through its existing risk/submit path.
    """

    def __init__(self, source: SignalSource, contract_ref: str, *, lot_size: int = 1000):
        self.source = source
        self.contract_ref = contract_ref
        self.lot_size = lot_size

    @decimal_operation
    def decide(self, auto: AutoStrategy, bars: tuple[SignalBar, ...], now: datetime, held_quantity: int) -> TargetIntent | None:
        completed = tuple(bar for bar in bars if bar.ends_at <= now)
        if not completed:
            return None
        last = completed[-1]
        window = window_bars(auto, completed, now, last.trade_date)
        if not window:
            return None
        points = self.source.signals(self.contract_ref, window, auto.signal_spec_json)
        target = apply_direction(desired_target(points, last.ends_at), auto.direction_policy)
        quantity = (
            auto.sizing.contracts if auto.sizing.kind is SizingKind.FIXED_CONTRACTS else int(auto.sizing.amount / last.close / self.lot_size) * self.lot_size
        )
        desired = (1 if target > 0 else -1 if target < 0 else 0) * quantity
        if desired == held_quantity:
            return None
        return TargetIntent(auto.strategy_id, auto.version, last.ends_at, desired, 'signal_target', auto.frozen_hash)
