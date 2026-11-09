"""Snapshot source port for the sector board."""

from typing import Protocol

from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.watch import WatchInstrument


class SnapshotSourcePort(Protocol):
    @property
    def connected(self) -> bool: ...

    def snapshots(self, instruments: tuple[WatchInstrument, ...]) -> tuple[QuoteRow, ...]: ...
