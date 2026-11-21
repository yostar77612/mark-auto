"""Market-wide daily quotes (M6-3): one row per stock and trading day, and the volume-breakout-to-a-new-high judgement.

Prices are Decimal, volumes are lots (張) like the live snapshot, amounts are integer NT$.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from .validation import DomainError, decimal_value, identity, integer, trading_date

SOURCES = ('OFFICIAL', 'SNAPSHOT')
MARKETS = ('TWSE', 'TPEX', 'SNAPSHOT')


@dataclass(frozen=True)
class DailyQuote:
    code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: int
    source: str = 'OFFICIAL'

    def __post_init__(self) -> None:
        identity(self.code)
        trading_date(self.trade_date)
        for name in ('open', 'high', 'low', 'close'):
            decimal_value(getattr(self, name), 'daily ' + name, positive=True)
        integer(self.volume, 'daily volume')
        integer(self.amount, 'daily amount')
        if self.high < self.low or self.source not in SOURCES:
            raise DomainError('validation_failed', 'daily quote')


@dataclass(frozen=True)
class DailyRow:
    """What the statistics need of one earlier day."""

    trade_date: date
    high: Decimal
    volume: int
    amount: int


@dataclass(frozen=True)
class DailyStats:
    """Facts about one stock from the trading days before the judged day. A window or average the history cannot
    cover is simply absent: nothing is judged on partial data."""

    days: int
    highs: tuple[tuple[int, Decimal], ...] = ()  # (window, highest high of that many days), ascending windows
    avg_volume: int | None = None
    avg_amount: int | None = None


def daily_stats(rows: Sequence[DailyRow], windows: Iterable[int], average_days: int) -> DailyStats:
    """rows: this stock's earlier days, ascending by date."""
    highs = tuple((window, max(row.high for row in rows[-window:])) for window in sorted(windows) if len(rows) >= window)
    tail = rows[-average_days:] if len(rows) >= average_days else ()
    return DailyStats(
        len(rows), highs, sum(row.volume for row in tail) // average_days if tail else None, sum(row.amount for row in tail) // average_days if tail else None
    )


def breakout_window(price: Decimal, stats: DailyStats) -> int | None:
    """The largest window whose earlier high the price is above, or None."""
    reached = [window for window, high in stats.highs if price > high]
    return max(reached) if reached else None


def volume_breakout(
    price: Decimal, total_volume: int, volume_ratio: Decimal | None, stats: DailyStats, *, final: bool, multiple: Decimal, intraday_ratio: Decimal
) -> tuple[int, Decimal] | None:
    """(window, volume strength) when a stock breaks its earlier high on volume, else None.

    Final (after the close): the day's volume is at least `multiple` times its average; strength is volume / average.
    Provisional (in session): the snapshot volume ratio is at least `intraday_ratio`; strength is that ratio."""
    window = breakout_window(price, stats)
    if window is None:
        return None
    if final:
        if not stats.avg_volume or total_volume < stats.avg_volume * multiple:
            return None
        return window, Decimal(total_volume) / Decimal(stats.avg_volume)
    if volume_ratio is None or volume_ratio < intraday_ratio:
        return None
    return window, volume_ratio
