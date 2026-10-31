"""Official daily market service boundary; consent remains an explicit argument."""

from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol
from quantlab.market import MarketSeries


class MarketDataLoad(Protocol):
    series: tuple[MarketSeries, ...]
    stale: bool
    error: str


class MarketDataProvider(Protocol):
    MAX_BYTES: int

    def load_cached(self, provider: str, root: str | Path) -> MarketDataLoad: ...

    def import_daily(self, provider: str, root: str | Path, raw: bytes, *, format: str = 'json', received_at: datetime | None = None) -> MarketDataLoad: ...

    def refresh_daily(
        self,
        provider: str,
        root: str | Path,
        *,
        received_at: datetime | None = None,
        network_enabled: bool = False,
        transport: Callable[[str], bytes] = ...,
    ) -> MarketDataLoad: ...
