"""Downloaded observations cross the port as validated immutable values."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar


@dataclass(frozen=True)
class OfficialPayload:
    source_url: str
    digest: str
    raw: bytes


@dataclass(frozen=True)
class OfficialStockBatch:
    instrument_id: str
    start: date
    end: date
    bars: tuple[DailyStockBar, ...]
    events: tuple[CorporateAction, ...]
    payloads: tuple[OfficialPayload, ...]


class OfficialStockSource(Protocol):
    def month(self, instrument_id: str, month: date) -> tuple[tuple[DailyStockBar, ...], OfficialPayload]: ...
    def events(self, instrument_id: str, start: date, end: date) -> tuple[tuple[CorporateAction, ...], OfficialPayload]: ...


class DailyStockStore(Protocol):
    def official_payload(self, source_url: str, digest: str) -> OfficialPayload: ...
    def import_daily(self, batch: OfficialStockBatch) -> None: ...
    def daily_history(self, instrument_id: str, start: date, end: date) -> OfficialStockBatch: ...
    def daily_coverage(self, instrument_id: str, start: date, end: date) -> bool: ...
