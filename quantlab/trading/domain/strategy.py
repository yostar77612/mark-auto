"""Bounded declarative strategies; no code execution, credentials or AI authority."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
import re

from .arithmetic import decimal_operation
from .calendar import TradingCalendar
from .costs import FeeSchedule
from .models import HoldingKind, HoldingPolicy, InstrumentSpec, Market, Side
from .validation import DomainError, aware, decimal_value, identity, integer


FIELDS = frozenset(('close', 'sma5', 'sma20', 'return5', 'volume'))
OPERATORS = frozenset(('GT', 'GE', 'LT', 'LE', 'EQ'))
STAGES = ('RULES_VALID', 'BACKTEST', 'WALK_FORWARD', 'PAPER', 'BROKER_SIMULATION', 'ENABLEABLE')
TMF_CONSERVATIVE_MARGIN = Decimal('50000')


@dataclass(frozen=True)
class StrategyParameters:
    """Explicit M2 execution settings, frozen with each researched version."""

    bar_interval: str
    stop_fraction: Decimal
    entry_amount: Decimal
    contracts: int = 1
    stock_intraday_enabled: bool = False
    stock_intraday_confirmed: bool = False
    instrument_rule: str = 'EXACT'

    def __post_init__(self) -> None:
        decimal_value(self.stop_fraction, 'protective stop', positive=True)
        decimal_value(self.entry_amount, 'entry amount', positive=True)
        integer(self.contracts, 'contracts', 1)
        if self.bar_interval not in ('1m', '5m', '1d') or self.stop_fraction >= 1 or self.contracts > 5:
            raise DomainError('strategy_parameters_invalid')
        if self.instrument_rule not in ('EXACT', 'TMF_NEAR') or any(
            type(value) is not bool for value in (self.stock_intraday_enabled, self.stock_intraday_confirmed)
        ):
            raise DomainError('strategy_parameters_invalid')


@dataclass(frozen=True)
class StrategyDefaults:
    kind: HoldingKind
    min_days: int | None
    max_days: int | None
    bar_interval: str
    intervals: tuple[str, ...]
    stop_fraction: Decimal | None
    futures_exit_at: time | None = None
    stock_exit_at: time | None = None


@dataclass(frozen=True)
class SizingDecision:
    quantity: int
    margin_source: str
    required_cash: Decimal


def strategy_defaults(kind: HoldingKind) -> StrategyDefaults:
    """M2 defaults; custom holding/stop values require explicit user input."""
    return {
        HoldingKind.INTRADAY: StrategyDefaults(kind, 0, 0, '5m', ('1m', '5m'), Decimal('0.01'), time(13, 35), time(13, 20)),
        HoldingKind.SWING: StrategyDefaults(kind, 2, 10, '1d', ('5m', '1d'), Decimal('0.03')),
        HoldingKind.POSITION: StrategyDefaults(kind, 10, 60, '1d', ('1d',), Decimal('0.08')),
        HoldingKind.CUSTOM: StrategyDefaults(kind, None, None, '1d', ('1m', '5m', '1d'), None),
    }[kind]


def is_tmf(spec: InstrumentSpec) -> bool:
    """Match actual TMF contract identities, never the shared TAIEX underlying."""
    return spec.market is Market.INDEX_FUTURE and spec.exchange == 'TAIFEX' and re.fullmatch(r'(?:TAIFEX:)?TMF:?[0-9]{6}', spec.instrument_id) is not None


def validate_strategy_parameters(kind: HoldingKind, spec: InstrumentSpec, parameters: StrategyParameters) -> None:
    """Validate the typed strategy input once, before it enters the ledger."""
    if parameters.bar_interval not in strategy_defaults(kind).intervals:
        raise DomainError('strategy_parameters_invalid', 'interval not supported by holding type')
    if kind in (HoldingKind.SWING, HoldingKind.POSITION) and spec.market is not Market.STOCK:
        raise DomainError('strategy_instrument_restricted', 'swing and position strategies require stocks')
    if spec.market is not Market.STOCK and not is_tmf(spec):
        raise DomainError('strategy_instrument_restricted', 'only TMF futures are supported')
    if kind is HoldingKind.INTRADAY and spec.market is Market.STOCK:
        if not parameters.stock_intraday_enabled or not parameters.stock_intraday_confirmed:
            raise DomainError('strategy_daytrade_confirmation_required')
    if parameters.instrument_rule == 'TMF_NEAR' and not is_tmf(spec):
        raise DomainError('strategy_instrument_restricted', 'near-month rule requires TMF')


def effective_strategy_spec(spec: InstrumentSpec) -> InstrumentSpec:
    """Use the labelled conservative TMF margin only when the broker omitted it."""
    if is_tmf(spec) and spec.margin is None:
        return replace(spec, margin=TMF_CONSERVATIVE_MARGIN)
    return spec


@decimal_operation
def strategy_quantity(
    spec: InstrumentSpec, parameters: StrategyParameters, price: Decimal, available: Decimal, fees: FeeSchedule, side: Side = Side.BUY
) -> SizingDecision:
    """Whole stock lots or the requested TMF count, including the shared costs."""
    decimal_value(price, 'sizing price', positive=True)
    decimal_value(available, 'available strategy funds', nonnegative=True)
    if spec.market is Market.STOCK:
        budget = min(parameters.entry_amount, available)
        # Amount is an all-in ceiling. Search the legal lot grid using the same
        # fee authority as commit, including minimum fees and slippage.
        lower, upper = 0, int(budget // (price * 1000))
        while lower < upper:
            lots = (lower + upper + 1) // 2
            if fees.entry_cash(spec, price, lots * 1000, side) <= budget:
                lower = lots
            else:
                upper = lots - 1
        quantity = lower * 1000
        source = 'NOT_APPLICABLE'
    else:
        if not is_tmf(spec):
            raise DomainError('strategy_instrument_restricted')
        quantity = parameters.contracts
        source = 'BROKER' if spec.margin is not None else 'BUILTIN_CONSERVATIVE'
        spec = effective_strategy_spec(spec)
    required = fees.entry_cash(spec, price, quantity, side) if quantity else Decimal('0')
    if not quantity or required > available:
        raise DomainError('strategy_size_insufficient')
    return SizingDecision(quantity, source, required)


def resolve_tmf_near(instruments: tuple[InstrumentSpec, ...], calendar: TradingCalendar, day: date) -> InstrumentSpec:
    """Roll on the preceding verified trading day; block every settlement day."""
    day_index = calendar.index(day)
    contracts = sorted((spec for spec in instruments if is_tmf(spec) and spec.expiry >= day), key=lambda spec: spec.expiry)
    if not contracts:
        raise DomainError('instrument_unresolved', 'TMF near-month contract unavailable')
    front = contracts[0]
    if day == front.expiry:
        raise DomainError('strategy_settlement_day')
    expiry_index = calendar.index(front.expiry)
    if day_index >= expiry_index - 1:
        if len(contracts) < 2:
            raise DomainError('instrument_unresolved', 'TMF next-month contract unavailable')
        return contracts[1]
    return front


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
