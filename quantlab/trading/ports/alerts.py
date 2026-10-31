"""Alert persistence and market scanner boundaries."""

from datetime import datetime
from typing import Protocol

from quantlab.trading.domain.alerts import AlertEvent, AlertKind, AlertObservation, AlertRule


class AlertStore(Protocol):
    warning: str

    def load_rules(self) -> tuple[AlertRule, ...]: ...
    def save_rules(self, rules: tuple[AlertRule, ...]) -> None: ...
    def load_events(self, now: datetime) -> tuple[AlertEvent, ...]: ...
    def append_event(self, event: AlertEvent) -> None: ...


class AlertScanner(Protocol):
    warning: str

    def set_kinds(self, kinds: frozenset[AlertKind]) -> None: ...
    def drain(self) -> tuple[AlertObservation, ...]: ...
