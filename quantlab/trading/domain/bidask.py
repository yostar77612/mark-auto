"""Five-level order book snapshot for one instrument; prices Decimal, volumes in lots."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .validation import DomainError, aware, decimal_value, identity, integer

LEVELS = 5


@dataclass(frozen=True)
class BidAskSnapshot:
    instrument_id: str
    source_at: datetime
    bid_prices: tuple[Decimal, ...]
    bid_volumes: tuple[int, ...]
    ask_prices: tuple[Decimal, ...]
    ask_volumes: tuple[int, ...]

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        aware(self.source_at)
        for prices, volumes in ((self.bid_prices, self.bid_volumes), (self.ask_prices, self.ask_volumes)):
            if len(prices) != LEVELS or len(volumes) != LEVELS:
                raise DomainError('validation_failed', 'bidask levels')
            for price in prices:
                decimal_value(price, 'bidask price', nonnegative=True)
            for volume in volumes:
                integer(volume, 'bidask volume')

    @property
    def total_bid_volume(self) -> int:
        return sum(self.bid_volumes)

    @property
    def total_ask_volume(self) -> int:
        return sum(self.ask_volumes)
