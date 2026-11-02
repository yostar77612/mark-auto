"""Captured application-ledger closing facts, separate from broker fund reports."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Quote


@dataclass(frozen=True)
class ClosingQuote:
    account_ref: str
    trade_date: date
    session_close_at: datetime
    quote: Quote
    bar: LiveBar
    scope_fingerprint: str


@dataclass(frozen=True)
class DailyAccountClose:
    account_ref: str
    trade_date: date
    as_of: datetime
    captured_at: datetime
    net_pnl: Decimal
    closing_quotes: tuple[ClosingQuote, ...]
    ledger_fingerprint: str
    order_fingerprints: tuple[tuple[str, str], ...]
    calendar_id: str
    calendar_version: str
    fee_fingerprint: str
    source_id: str = 'APP_VERIFIED_DAY_CLOSE_V1'
    consumed_on: date | None = None
    invalidated: bool = False
