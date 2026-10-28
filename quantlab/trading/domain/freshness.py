"""Pure freshness classification and validated settings; no clock or connection IO."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .validation import DomainError, integer


class Freshness(str, Enum):
    LIVE = 'LIVE'
    DELAYED = 'DELAYED'
    STOPPED = 'STOPPED'
    CLOSED = 'CLOSED'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class LiveMarketSettings:
    delayed_seconds: int = 10
    stopped_seconds: int = 60
    buffer_trade_days: int = 30
    queue_limit: int = 10000
    subscription_limit: int = 20
    snapshot_bar_tail: int = 2
    series_page_limit: int = 1000

    def __post_init__(self) -> None:
        for name in ('delayed_seconds', 'stopped_seconds', 'buffer_trade_days', 'queue_limit', 'subscription_limit', 'snapshot_bar_tail', 'series_page_limit'):
            integer(getattr(self, name), name, 1)
        if self.snapshot_bar_tail > 32 or self.series_page_limit > type(self).series_page_limit:
            raise DomainError('validation_failed', 'market transport bounds')
        if self.stopped_seconds <= self.delayed_seconds or self.subscription_limit > type(self).subscription_limit:
            raise DomainError('validation_failed', 'freshness thresholds/subscription limit')


def classify_freshness(
    last_received_at: datetime | None,
    *,
    now: datetime,
    connected: bool,
    in_session: bool | None,
    settings: LiveMarketSettings = LiveMarketSettings(),
) -> Freshness:
    """Unknown calendar/data wins; known closed session wins over disconnection."""
    if in_session is None or last_received_at is None:
        return Freshness.UNKNOWN
    if not in_session:
        return Freshness.CLOSED
    age = (now - last_received_at).total_seconds()
    if age < 0:
        return Freshness.UNKNOWN
    if not connected or age > settings.stopped_seconds:
        return Freshness.STOPPED
    if age > settings.delayed_seconds:
        return Freshness.DELAYED
    return Freshness.LIVE
