"""Atomic workspace rule JSON and retained local alert JSONL."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from quantlab.trading.domain.alerts import AlertEvent, AlertKind, AlertRule
from quantlab.trading.domain.validation import DomainError, aware


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError(type(value).__name__)


class JsonAlertStore:
    def __init__(self, workspace: Path):
        self.directory = workspace / 'market'
        self.rules_path = self.directory / 'alert_rules.json'
        self.events_path = self.directory / 'alert_events.jsonl'
        self.warning = ''

    def _quarantine(self, path: Path):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        try:
            path.rename(path.with_name(path.name + '.bad-' + stamp))
        except OSError as exc:
            raise DomainError('alert_store_unavailable', 'preserve corrupt alert file') from exc
        self.warning = 'alert.rules_corrupt'

    def load_rules(self) -> tuple[AlertRule, ...]:
        if not self.rules_path.exists():
            return ()
        try:
            data = json.loads(self.rules_path.read_text(encoding='utf-8'))
            if data['version'] != 1 or len(data['rules']) > 100:
                raise ValueError('version/rule limit')
            rules = tuple(AlertRule(**{**row, 'kind': AlertKind(row['kind'])}) for row in data['rules'])
            if len({rule.rule_id for rule in rules}) != len(rules):
                raise ValueError('duplicate rules')
            return rules
        except (ValueError, TypeError, KeyError, UnicodeError):
            self._quarantine(self.rules_path)
            return ()
        except OSError as exc:
            raise DomainError('alert_store_unavailable', 'read rules') from exc

    def _atomic(self, path: Path, text: str):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + '.tmp')
            temporary.write_text(text, encoding='utf-8')
            temporary.replace(path)
        except OSError as exc:
            raise DomainError('alert_store_unavailable', 'write alert store') from exc

    def save_rules(self, rules: tuple[AlertRule, ...]):
        rows = [
            dict(
                rule_id=rule.rule_id,
                kind=rule.kind.value,
                scope=rule.scope,
                instrument_id=rule.instrument_id,
                params=dict(rule.params),
                enabled=rule.enabled,
                cooldown_seconds=rule.cooldown_seconds,
            )
            for rule in rules
        ]
        self._atomic(self.rules_path, json.dumps({'version': 1, 'rules': rows}, default=_json_value, ensure_ascii=False))

    def load_events(self, now: datetime) -> tuple[AlertEvent, ...]:
        if not self.events_path.exists():
            return ()
        try:
            rows = []
            expired = False
            for line in self.events_path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                stamp = aware(datetime.fromisoformat(row['occurred_at'])).astimezone(timezone.utc)
                if stamp >= now - timedelta(days=30):
                    rows.append(
                        AlertEvent(
                            **{
                                **row,
                                'kind': AlertKind(row['kind']),
                                'occurred_at': stamp,
                                'value': None if row['value'] is None else Decimal(row['value']),
                                'message_args': tuple(row['message_args']),
                            }
                        )
                    )
                else:
                    expired = True
            if expired:
                # The owner's no-data-deletion boundary takes precedence over
                # retention: preserve the complete original before active cleanup.
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                self.events_path.rename(self.events_path.with_name(self.events_path.name + '.archive-' + stamp))
                self._atomic(self.events_path, ''.join(json.dumps(asdict(event), default=_json_value, ensure_ascii=False) + '\n' for event in rows))
            return tuple(rows[-500:])
        except (ValueError, KeyError, TypeError, UnicodeError, InvalidOperation):
            self._quarantine(self.events_path)
            return ()
        except OSError as exc:
            raise DomainError('alert_store_unavailable', 'read events') from exc

    def append_event(self, event: AlertEvent):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.events_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(asdict(event), default=_json_value, ensure_ascii=False) + '\n')
        except OSError as exc:
            raise DomainError('alert_store_unavailable', 'append event') from exc
