"""Bounded declarative strategies; no code execution, credentials or AI authority."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json

from .arithmetic import decimal_operation
from .models import HoldingKind, HoldingPolicy, Market
from .validation import DomainError, aware, decimal_value, identity, integer


FIELDS = frozenset(('close', 'sma5', 'sma20', 'return5', 'volume'))
OPERATORS = frozenset(('GT', 'GE', 'LT', 'LE', 'EQ'))
STAGES = ('RULES_VALID', 'BACKTEST', 'WALK_FORWARD', 'PAPER', 'BROKER_SIMULATION', 'ENABLEABLE')


@dataclass(frozen=True)
class Rule:
    field: str
    operator: str
    value: Decimal

    def __post_init__(self) -> None:
        if type(self.field) is not str or type(self.operator) is not str or self.field not in FIELDS or self.operator not in OPERATORS:
            raise DomainError('validation_failed', 'strategy operator/field not allowed')
        decimal_value(self.value, 'rule threshold')

    def evaluate(self, features: tuple[tuple[str, Decimal], ...]) -> bool:
        values = dict(features)
        if len(values) != len(features) or self.field not in values:
            raise DomainError('validation_failed', 'missing or duplicate feature')
        actual = decimal_value(values[self.field], 'feature')
        return {'GT': actual > self.value, 'GE': actual >= self.value, 'LT': actual < self.value, 'LE': actual <= self.value, 'EQ': actual == self.value}[
            self.operator
        ]


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    version: int
    market: Market
    policy: HoldingPolicy
    bar_interval: str
    direction: str
    entry: tuple[Rule, ...]
    exit: tuple[Rule, ...]
    cost_version: str
    risk_ref: str
    schema_version: int = 2

    def __post_init__(self) -> None:
        identity(self.strategy_id)
        integer(self.version, 'strategy version', 1)
        identity(self.cost_version)
        identity(self.risk_ref)
        if self.schema_version != 2 or not isinstance(self.market, Market) or not isinstance(self.policy, HoldingPolicy):
            raise DomainError('validation_failed', 'strategy schema/types')
        if self.bar_interval not in ('1m', '5m', '1d') or self.direction not in ('LONG_ONLY', 'SHORT_ONLY', 'BOTH'):
            raise DomainError('validation_failed', 'strategy interval/direction')
        for rules in (self.entry, self.exit):
            if type(rules) is not tuple or not 1 <= len(rules) <= 16 or any(not isinstance(rule, Rule) for rule in rules):
                raise DomainError('validation_failed', 'strategy rule resource bound')

    @property
    def fingerprint(self) -> str:
        body = {
            'schema': self.schema_version,
            'id': self.strategy_id,
            'version': self.version,
            'market': self.market.value,
            'holding': (self.policy.kind.value, self.policy.min_days, self.policy.max_days, self.policy.night_enabled, self.policy.expiry_action),
            'interval': self.bar_interval,
            'direction': self.direction,
            'cost': self.cost_version,
            'risk': self.risk_ref,
            'entry': [(r.field, r.operator, str(r.value)) for r in self.entry],
            'exit': [(r.field, r.operator, str(r.value)) for r in self.exit],
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def revised(self, **changes: object) -> 'StrategyDefinition':
        if 'version' in changes or 'strategy_id' in changes or 'schema_version' in changes:
            raise DomainError('validation_failed', 'strategy revision identity is immutable')
        return replace(self, version=self.version + 1, **changes)


@dataclass(frozen=True)
class ResearchEvidence:
    stage: str
    strategy_fingerprint: str
    dataset_id: str
    producer: str
    completed_at: datetime
    partition: str
    result_hash: str

    def __post_init__(self) -> None:
        if self.stage not in STAGES or self.partition not in ('TRAINING', 'OUT_OF_SAMPLE', 'FINAL_HOLDOUT', 'PAPER', 'BROKER_SIMULATION'):
            raise DomainError('validation_failed', 'research evidence stage/partition')
        for name in ('strategy_fingerprint', 'dataset_id', 'producer', 'result_hash'):
            identity(getattr(self, name))
        aware(self.completed_at)


@dataclass(frozen=True)
class StrategyVersion:
    definition: StrategyDefinition
    evidence: tuple[ResearchEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.definition, StrategyDefinition) or type(self.evidence) is not tuple:
            raise DomainError('validation_failed', 'strategy version/evidence')
        if any(not isinstance(e, ResearchEvidence) for e in self.evidence):
            raise DomainError('validation_failed', 'typed research evidence required')
        expected = STAGES[: len(self.evidence)]
        if len(self.evidence) > len(STAGES) or tuple(e.stage for e in self.evidence) != expected:
            raise DomainError('validation_failed', 'research stages must be completed in order')
        if any(e.strategy_fingerprint != self.definition.fingerprint for e in self.evidence):
            raise DomainError('validation_failed', 'evidence belongs to a different strategy version')
        if any(a.completed_at > b.completed_at for a, b in zip(self.evidence, self.evidence[1:])):
            raise DomainError('validation_failed', 'research evidence chronology')

    def revised(self, **changes: object) -> 'StrategyVersion':
        return StrategyVersion(self.definition.revised(**changes))

    def add_evidence(self, evidence: ResearchEvidence) -> 'StrategyVersion':
        return StrategyVersion(self.definition, self.evidence + (evidence,))


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise DomainError('validation_failed', 'duplicate JSON key')
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise DomainError('validation_failed', f'non-finite JSON constant {value}')


def _keys(value: object, expected: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise DomainError('validation_failed', 'unknown or missing strategy fields')
    return value


def _rule(value: object) -> Rule:
    item = _keys(value, frozenset(('field', 'operator', 'value')))
    if type(item['value']) is not str or len(item['value']) > 40:
        raise DomainError('validation_failed', 'decimal strings required')
    try:
        return Rule(item['field'], item['operator'], Decimal(item['value']))
    except (TypeError, ArithmeticError) as exc:
        raise DomainError('validation_failed', 'rule type') from exc


def parse_strategy(raw: str) -> StrategyDefinition:
    if type(raw) is not str or len(raw.encode('utf-8')) > 65536:
        raise DomainError('validation_failed', 'strategy input size')
    try:
        data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        item = _keys(
            data,
            frozenset(
                (
                    'schema_version',
                    'strategy_id',
                    'version',
                    'market',
                    'holding_policy',
                    'bar_interval',
                    'direction',
                    'entry',
                    'exit',
                    'cost_version',
                    'risk_ref',
                )
            ),
        )
        policy = _keys(item['holding_policy'], frozenset(('kind', 'min_days', 'max_days', 'night_enabled', 'expiry_action')))
        for field in ('entry', 'exit'):
            if type(item[field]) is not list or not 1 <= len(item[field]) <= 16:
                raise DomainError('validation_failed', 'rule resource bound')
        return StrategyDefinition(
            item['strategy_id'],
            item['version'],
            Market(item['market']),
            HoldingPolicy(HoldingKind(policy['kind']), policy['min_days'], policy['max_days'], policy['night_enabled'], policy['expiry_action']),
            item['bar_interval'],
            item['direction'],
            tuple(_rule(r) for r in item['entry']),
            tuple(_rule(r) for r in item['exit']),
            item['cost_version'],
            item['risk_ref'],
            item['schema_version'],
        )
    except DomainError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as exc:
        raise DomainError('validation_failed', 'invalid structured strategy') from exc


@dataclass(frozen=True)
class CompletedBar:
    opened_at: datetime
    ended_at: datetime
    available_at: datetime
    open: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        for value in (self.opened_at, self.ended_at, self.available_at):
            aware(value)
        for value in (self.open, self.close):
            decimal_value(value, 'bar price', positive=True)
        integer(self.volume, 'volume')
        if not self.opened_at < self.ended_at <= self.available_at:
            raise DomainError('validation_failed', 'bar time ordering')


@decimal_operation
def features_at(bars: tuple[CompletedBar, ...], decision_at: datetime) -> tuple[tuple[str, Decimal], ...]:
    aware(decision_at)
    if type(bars) is not tuple or not bars or len(bars) > 100000:
        raise DomainError('validation_failed', 'bounded completed bars required')
    if any(not isinstance(b, CompletedBar) or b.available_at > decision_at for b in bars):
        raise DomainError('validation_failed', 'lookahead: bar is not available')
    if any(a.ended_at >= b.ended_at or a.available_at > b.available_at for a, b in zip(bars, bars[1:])):
        raise DomainError('validation_failed', 'bar ordering')
    values: list[tuple[str, Decimal]] = [('close', bars[-1].close), ('volume', Decimal(bars[-1].volume))]
    for period in (5, 20):
        if len(bars) >= period:
            values.append((f'sma{period}', sum((b.close for b in bars[-period:]), Decimal('0')) / period))
    if len(bars) >= 6:
        values.append(('return5', bars[-1].close / bars[-6].close - 1))
    return tuple(values)


def ensure_execution_after_signal(bar: CompletedBar, execution_at: datetime) -> None:
    if aware(execution_at) <= bar.available_at:
        raise DomainError('validation_failed', 'execution must follow information availability')


@dataclass(frozen=True)
class AIContext:
    partition: str
    strategy_id: str
    summary: str

    def __post_init__(self) -> None:
        if self.partition != 'TRAINING' or type(self.summary) is not str or len(self.summary) > 8192:
            raise DomainError('capability_missing', 'AI context allows bounded training summary only')
        identity(self.strategy_id)
        # Only the exact restricted semantic summary produced from rules is exported.
        if any(token in self.summary.lower() for token in ('secret', 'api_key', 'token', 'password', 'credential', 'holdout', 'out_of_sample')):
            raise DomainError('capability_missing', 'sensitive context rejected')


def ai_context(definition: StrategyDefinition, *, partition: str = 'TRAINING') -> AIContext:
    # No data rows, account identities, settings, credentials, or external arbitrary text.
    summary = json.dumps(
        {
            'market': definition.market.value,
            'interval': definition.bar_interval,
            'holding_kind': definition.policy.kind.value,
            'holding_days': [definition.policy.min_days, definition.policy.max_days],
            'entry': [(r.field, r.operator, str(r.value)) for r in definition.entry],
            'exit': [(r.field, r.operator, str(r.value)) for r in definition.exit],
        },
        separators=(',', ':'),
    )
    return AIContext(partition, definition.strategy_id, summary)
