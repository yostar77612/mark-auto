"""Decimal quote reference, change and P&L calculations; no calendar lookup or fees IO."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .arithmetic import decimal_operation
from .freshness import Freshness
from .models import InstrumentSpec


@dataclass(frozen=True)
class TradeDateClose:
    trade_date: date
    close: Decimal
    source_at: datetime


@dataclass(frozen=True)
class QuoteStats:
    reference_price: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None


def reference_price(previous_trade_date: date, closes: tuple[TradeDateClose, ...]) -> Decimal | None:
    """The caller supplies the calendar's previous trade date, including holidays."""
    matching = tuple(close for close in closes if close.trade_date == previous_trade_date)
    return max(matching, key=lambda close: close.source_at).close if matching else None


@decimal_operation
def quote_stats(price: Decimal, previous_trade_date: date, closes: tuple[TradeDateClose, ...]) -> QuoteStats:
    reference = reference_price(previous_trade_date, closes)
    if reference is None:
        return QuoteStats(None, None, None)
    change = price - reference
    return QuoteStats(reference, change, change / reference * Decimal('100'))


@decimal_operation
def unrealized_pnl(price: Decimal, quantity: int, spec: InstrumentSpec, cost: Decimal, *, freshness: Freshness) -> Decimal | None:
    """Signed quantity and signed cost support shorts; None means unknown valuation."""
    if freshness is not Freshness.LIVE:
        return None
    return price * quantity * spec.multiplier - cost
