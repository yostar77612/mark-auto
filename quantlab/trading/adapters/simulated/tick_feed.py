"""Seeded pull-based synthetic ticks; no bars, freshness or session inference.

The clock gates delivery of a timestamped stream. A resolver supplies every
trade date/session. Draining in different batch sizes preserves the stream.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from random import Random

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, integer
from quantlab.trading.ports.interfaces import Clock, SessionResolver


class SimulatedTickFeed:
    def __init__(
        self,
        clock: Clock,
        resolver: SessionResolver,
        *,
        start: datetime,
        seed: int = 0,
        interval: timedelta = timedelta(seconds=1),
        price: Decimal = Decimal('100'),
        catch_up: bool = True,
    ) -> None:
        aware(start)
        integer(seed, 'seed')
        decimal_value(price, 'synthetic price', positive=True)
        if interval <= timedelta(0):
            raise DomainError('validation_failed', 'positive tick interval required')
        if type(catch_up) is not bool:
            raise DomainError('validation_failed', 'explicit catch-up setting required')
        self.clock, self.resolver = clock, resolver
        self.start, self.interval, self.price = start, interval, price
        self.catch_up = catch_up
        self.random = Random(seed)
        self.sequence = 0
        self.next_at: dict[str, datetime] = {}

    @decimal_operation
    def drain_ticks(self, instrument_ids: tuple[str, ...], max_items: int) -> tuple[Tick, ...]:
        integer(max_items, 'max_items')
        now = self.clock.now()
        active = set(instrument_ids)
        self.next_at = {key: value for key, value in self.next_at.items() if key in active}
        for key in instrument_ids:
            self.next_at.setdefault(key, max(self.start, now))
            if not self.catch_up:
                self.next_at[key] = max(self.next_at[key], now)
        result = []
        for _ in range(max_items):
            if not self.next_at:
                break
            key = min(self.next_at, key=lambda key: (self.next_at[key], key))
            timestamp = self.next_at[key]
            if timestamp > now:
                break
            day, session = self.resolver.session_at(key, timestamp)
            self.sequence += 1
            result.append(
                Tick(key, self.price + Decimal(self.random.randrange(10)), self.random.randrange(1, 6), timestamp, timestamp, day, session, self.sequence)
            )
            self.next_at[key] += self.interval
        return tuple(result)
