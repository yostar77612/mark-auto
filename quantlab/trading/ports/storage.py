"""Durable event storage contract. No SQLite types cross this boundary."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Fence:
    scope: str
    owner: str
    generation: int


@dataclass(frozen=True)
class StoredEvent:
    sequence: int
    kind: str
    payload: str
    previous_hash: str
    digest: str


class Journal(Protocol):
    def append(self, kind: str, payload: str, now: datetime, *, expected_sequence: int) -> StoredEvent: ...
    def replay(self) -> tuple[StoredEvent, ...]: ...
    def heartbeat(self, now: datetime) -> None: ...
    def backup(self, destination: Path) -> None: ...
    def close(self) -> None: ...
