"""Immutable alert transport values and presentation-facing application proxy."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from quantlab.trading.domain.alerts import AlertEvent, AlertKind, AlertRule
from quantlab.trading.domain.validation import DomainError
from .codec import register


@dataclass(frozen=True)
class AlertRuleData:
    rule_id: str
    kind: AlertKind
    scope: str
    instrument_id: str
    params: tuple[tuple[str, object], ...]
    enabled: bool
    cooldown_seconds: int

    @classmethod
    def from_rule(cls, rule: AlertRule):
        return cls(rule.rule_id, rule.kind, rule.scope, rule.instrument_id, tuple(rule.params.items()), rule.enabled, rule.cooldown_seconds)

    def to_rule(self) -> AlertRule:
        if len(dict(self.params)) != len(self.params):
            raise DomainError('alert_invalid_params', 'duplicate parameter')
        return AlertRule(self.rule_id, self.kind, self.scope, self.instrument_id, dict(self.params), self.enabled, self.cooldown_seconds)


class AlertOperation(str, Enum):
    SNAPSHOT = 'SNAPSHOT'
    ADD = 'ADD'
    ENABLE = 'ENABLE'
    DELETE = 'DELETE'
    CLEAR = 'CLEAR'


@dataclass(frozen=True)
class AlertCommand:
    operation: AlertOperation = AlertOperation.SNAPSHOT
    rule: AlertRuleData | None = None
    rule_id: str = ''
    enabled: bool = True

    def __post_init__(self):
        if not isinstance(self.operation, AlertOperation):
            raise DomainError('alert_invalid_params', 'operation')
        if self.operation == AlertOperation.ADD and not isinstance(self.rule, AlertRuleData):
            raise DomainError('alert_invalid_params', 'rule')
        if self.operation in (AlertOperation.ENABLE, AlertOperation.DELETE) and not self.rule_id:
            raise DomainError('alert_invalid_params', 'rule_id')
        if type(self.enabled) is not bool:
            raise DomainError('alert_invalid_params', 'enabled')


@dataclass(frozen=True)
class AlertSnapshot:
    rules: tuple[AlertRuleData, ...] = ()
    events: tuple[AlertEvent, ...] = ()
    warning: str = ''


class AlertActions(Protocol):
    rules: tuple[AlertRule, ...]
    events: tuple[AlertEvent, ...]
    warning: str

    def add_rule(self, rule: AlertRule) -> None: ...
    def set_enabled(self, rule_id: str, enabled: bool) -> None: ...
    def delete_rule(self, rule_id: str) -> None: ...
    def clear_events(self) -> None: ...


class AlertProxy:
    """Owns no storage; an injected authenticated IPC call reaches the engine."""

    def __init__(self, call: Callable[[AlertCommand], AlertSnapshot]):
        self.call = call
        self.rules: tuple[AlertRule, ...] = ()
        self.events: tuple[AlertEvent, ...] = ()
        self.warning = ''

    def _update(self, command: AlertCommand) -> None:
        snapshot = self.call(command)
        self.rules = tuple(data.to_rule() for data in snapshot.rules)
        self.events, self.warning = snapshot.events, snapshot.warning

    def refresh(self):
        self._update(AlertCommand())

    def add_rule(self, rule: AlertRule):
        self._update(AlertCommand(AlertOperation.ADD, rule=AlertRuleData.from_rule(rule)))

    def set_enabled(self, rule_id: str, enabled: bool):
        self._update(AlertCommand(AlertOperation.ENABLE, rule_id=rule_id, enabled=enabled))

    def delete_rule(self, rule_id: str):
        self._update(AlertCommand(AlertOperation.DELETE, rule_id=rule_id))

    def clear_events(self):
        self._update(AlertCommand(AlertOperation.CLEAR))


register(AlertKind, AlertEvent, AlertRuleData, AlertOperation, AlertCommand, AlertSnapshot)
