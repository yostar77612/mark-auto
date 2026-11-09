"""Read-only five-level quote and trade-tape view of one instrument."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantlab.trading.domain.bidask import BidAskSnapshot
from quantlab.trading.domain.ticks import TICK_SIDES
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer


@dataclass(frozen=True)
class TapeEntry:
    source_at: datetime
    price: Decimal
    volume: int
    side: str

    def __post_init__(self) -> None:
        aware(self.source_at)
        decimal_value(self.price, 'tape price', positive=True)
        integer(self.volume, 'tape volume')
        if self.side not in TICK_SIDES:
            raise DomainError('validation_failed', 'tape side')


@dataclass(frozen=True)
class OrderBookView:
    instrument_id: str
    supported: bool = False
    bidask: BidAskSnapshot | None = None
    bidask_limited: bool = False
    tape: tuple[TapeEntry, ...] = ()
    buy_volume: int = 0
    sell_volume: int = 0
    undecided_volume: int = 0
    since: datetime | None = None

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        for value in (self.buy_volume, self.sell_volume, self.undecided_volume):
            integer(value, 'tape volume total')
