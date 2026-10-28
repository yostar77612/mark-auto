"""Validated immutable incoming ticks; session/calendar resolution belongs to callers."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .validation import DomainError, aware, decimal_value, identity, integer, trading_date


@dataclass(frozen=True)
class Tick:
    instrument_id: str
    price: Decimal
    volume: int
    source_at: datetime
    received_at: datetime
    trade_date: date
    session: str = 'DAY'
    sequence: int | None = None
    source: str = 'LOCAL_SIMULATED'

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        decimal_value(self.price, 'tick price', positive=True)
        integer(self.volume, 'tick volume')
        aware(self.source_at)
        aware(self.received_at)
        trading_date(self.trade_date)
        identity(self.source)
        if self.received_at < self.source_at or self.session not in ('DAY', 'NIGHT'):
            raise DomainError('validation_failed', 'tick ordering/session')
        if self.sequence is not None:
            integer(self.sequence, 'tick sequence')
