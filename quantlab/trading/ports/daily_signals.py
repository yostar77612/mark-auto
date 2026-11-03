"""Read-only official daily data; adapters own acquisition and finality evidence."""

from datetime import date
from typing import Protocol

from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory


class OfficialDailySignalSource(Protocol):
    def history(
        self, instrument_id: str, calendar: TradingCalendar, *, through: date, start: date | None = None, cached_only: bool = False
    ) -> OfficialDailyHistory: ...
    def cached_history(self, instrument_id: str, calendar: TradingCalendar, *, through: date, start: date | None = None) -> OfficialDailyHistory | None: ...
