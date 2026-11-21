"""Typed read models for the stock screener tab; they cross the engine boundary, so everything is a plain value."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantlab.trading.domain.screener import LISTS, PATTERN_FILTERS
from quantlab.trading.domain.validation import DomainError, aware, identity

KLINE_STATES = ('', 'YEAR', 'DOWNLOADING', 'FAILED')
# OFFLINE/EMPTY: nothing to show; WARMUP: the open is still settling; LIVE/STALE: in session; CLOSED: last close;
# ACCUMULATING: the market-wide daily K-lines do not yet cover the longest window (progress_days / progress_needed).
STATES = ('OFFLINE', 'EMPTY', 'WARMUP', 'LIVE', 'STALE', 'CLOSED', 'ACCUMULATING')


@dataclass(frozen=True)
class ScreenerQuery:
    """Which list to read; download_id first queues that stock's one-year K-line download (the right-click action)."""

    list_id: str = 'SURGE'
    pattern: str = 'ALL'
    download_id: str = ''

    def __post_init__(self) -> None:
        if self.list_id not in LISTS or self.pattern not in PATTERN_FILTERS:
            raise DomainError('validation_failed', 'screener query')
        if self.download_id:
            identity(self.download_id)


@dataclass(frozen=True)
class ScreenerRowView:
    """One stock of the surge or breakout list. ratio is the volume ratio (surge) or volume over its average (breakout);
    label is the pattern (SURGE_RED, SURGE_BLACK) or the breakout window in days ('60', '120', '240')."""

    instrument_id: str
    code: str
    name: str
    price: Decimal
    change_pct: Decimal
    ratio: Decimal | None = None
    label: str = ''
    kline: str = ''
    provisional: bool = False

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        if self.kline not in KLINE_STATES:
            raise DomainError('validation_failed', 'screener kline state')


@dataclass(frozen=True)
class DownloadedRowView:
    instrument_id: str
    code: str
    name: str
    first: datetime
    last: datetime
    updated: datetime | None = None

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        aware(self.first)
        aware(self.last)


@dataclass(frozen=True)
class ScreenerView:
    list_id: str
    pattern: str = 'ALL'
    state: str = 'EMPTY'
    rows: tuple[ScreenerRowView, ...] = ()
    downloaded: tuple[DownloadedRowView, ...] = ()
    min_volume_lots: int = 0
    data_at: datetime | None = None
    progress_days: int = 0
    progress_needed: int = 0
    code: str = ''  # reason code when the K-line store or the daily K-lines cannot be read

    def __post_init__(self) -> None:
        if self.list_id not in LISTS or self.pattern not in PATTERN_FILTERS or self.state not in STATES:
            raise DomainError('validation_failed', 'screener view')
