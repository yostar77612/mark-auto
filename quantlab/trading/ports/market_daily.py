"""Where the market-wide daily quotes come from: official URLs and their parsers, never an account or credential."""

from datetime import date
from typing import Protocol

from quantlab.trading.domain.market_daily import DailyQuote


class MarketDailySourcePort(Protocol):
    def url(self, market: str, day: date) -> str: ...

    def parse(self, market: str, raw: bytes, day: date) -> tuple[DailyQuote, ...] | None:
        """The day's ordinary shares; None when the exchange has no data for that day (a holiday)."""
        ...
