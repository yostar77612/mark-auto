"""Coordinate alert edge state, scopes, bounded history and persistence."""

from collections import deque
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from quantlab.trading.domain.alerts import SCANNER_KINDS, AlertEvent, AlertKind, AlertObservation, AlertRule, AlertTriggerState, evaluate_alert, kd
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.alerts import AlertScanner, AlertStore
from .alert_contracts import AlertCommand, AlertOperation, AlertRuleData, AlertSnapshot


class AlertService:
    def __init__(self, store: AlertStore, *, now: datetime, scanner: AlertScanner | None = None):
        self.store, self.scanner = store, scanner
        self.rules = store.load_rules()
        self.events = deque(store.load_events(now), maxlen=500)
        self.warning = store.warning
        self.watchlist: tuple[str, ...] = ()
        self.fixed_indices: tuple[str, ...] = ('INDEX:IX0001', 'INDEX:IX0043')
        self._states: dict[tuple[str, str], AlertTriggerState] = {}
        self._sync_scanner()

    def _sync_scanner(self):
        if self.scanner is not None:
            self.scanner.set_kinds(frozenset(rule.kind for rule in self.rules if rule.enabled and rule.kind in SCANNER_KINDS))

    def add_rule(self, rule: AlertRule):
        if len(self.rules) >= 100 or any(item.rule_id == rule.rule_id for item in self.rules):
            raise DomainError('alert_invalid_params', 'rule limit/duplicate')
        self._save((*self.rules, rule))

    def _save(self, rules: tuple[AlertRule, ...]):
        self.store.save_rules(rules)
        self.rules = rules
        self._states = {key: value for key, value in self._states.items() if any(rule.rule_id == key[0] and rule.enabled for rule in rules)}
        self._sync_scanner()

    def set_enabled(self, rule_id: str, enabled: bool):
        self._save(tuple(replace(rule, enabled=enabled) if rule.rule_id == rule_id else rule for rule in self.rules))

    def delete_rule(self, rule_id: str):
        self._save(tuple(rule for rule in self.rules if rule.rule_id != rule_id))

    def clear_events(self):
        """Clear the visible session log; retained local audit events stay on disk."""
        self.events.clear()

    def observe(self, observation: AlertObservation) -> tuple[AlertEvent, ...]:
        emitted = []
        for rule in self.rules:
            if rule.scope == 'INSTRUMENT' and rule.instrument_id != observation.instrument_id:
                continue
            if rule.scope == 'WATCHLIST' and observation.instrument_id not in (*self.watchlist, *self.fixed_indices):
                continue
            key = rule.rule_id, observation.instrument_id
            state, fired, value = evaluate_alert(rule, observation, self._states.get(key, AlertTriggerState()))
            self._states[key] = state
            if fired:
                direction = _event_direction(rule, observation, value)
                event = AlertEvent(
                    str(uuid4()),
                    rule.rule_id,
                    rule.kind,
                    observation.instrument_id,
                    observation.occurred_at,
                    value,
                    'alert.event.' + rule.kind.value.lower(),
                    ('' if value is None else str(value), direction),
                )
                self.store.append_event(event)
                self.events.append(event)
                emitted.append(event)
        return tuple(emitted)

    def poll_scanner(self) -> tuple[AlertEvent, ...]:
        if self.scanner is None:
            return ()
        events = tuple(event for observation in self.scanner.drain() for event in self.observe(observation))
        self.warning = self.scanner.warning or self.warning
        return events

    def execute(self, command: AlertCommand) -> AlertSnapshot:
        if command.operation == AlertOperation.ADD:
            self.add_rule(command.rule.to_rule())
        elif command.operation == AlertOperation.ENABLE:
            self.set_enabled(command.rule_id, command.enabled)
        elif command.operation == AlertOperation.DELETE:
            self.delete_rule(command.rule_id)
        elif command.operation == AlertOperation.CLEAR:
            self.clear_events()
        return AlertSnapshot(tuple(AlertRuleData.from_rule(rule) for rule in self.rules), tuple(self.events), self.warning)

    def set_scanner(self, scanner: AlertScanner | None):
        if self.scanner is not None:
            self.scanner.set_kinds(frozenset())
        self.scanner = scanner
        self._sync_scanner()


def _event_direction(rule: AlertRule, observation: AlertObservation, value) -> str:
    if rule.kind in SCANNER_KINDS:
        return observation.scanner_direction
    if rule.kind == AlertKind.PRICE_CROSS:
        return 'UP' if observation.price > observation.previous_price else 'DOWN'
    if rule.kind == AlertKind.DAY_HIGH_LOW:
        return 'UP' if observation.price > observation.day_high else 'DOWN'
    if rule.kind == AlertKind.PREV_DAY_BREAK:
        return 'UP' if observation.price > observation.previous_high else 'DOWN'
    if rule.kind == AlertKind.KD_CROSS:
        k, d = kd(observation.bars, rule.params['n'], rule.params['k_smoothing'], rule.params['d_smoothing'])[-1]
        return 'UP' if k > d else 'DOWN'
    if rule.kind == AlertKind.VOLUME_SURGE:
        return 'ANY'
    return 'UP' if value > 0 else 'DOWN' if value < 0 else 'ANY'
