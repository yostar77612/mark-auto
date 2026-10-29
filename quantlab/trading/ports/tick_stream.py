"""Optional typed tick-loss capability; no SDK fields or bar composition."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TickLoss:
    """Delivery loss envelope; Application maps source time to incomplete bars.

    A connector may conservatively coalesce multiple losses for one instrument
    into one interval between drains. Count is the exact number of lost ticks.
    """

    instrument_id: str
    first_source_at: datetime
    last_source_at: datetime
    count: int
    code: str = 'tick_queue_overflow'


@runtime_checkable
class TickLossSource(Protocol):
    def drain_tick_losses(self) -> tuple[TickLoss, ...]:
        """Consume pending loss envelopes once, independently of the tick budget."""
        ...


@runtime_checkable
class MarketConnectionSource(Protocol):
    """Optional session facts; recovery policy belongs to Application."""

    @property
    def connected(self) -> bool: ...

    @property
    def disconnected_at(self) -> datetime | None: ...
