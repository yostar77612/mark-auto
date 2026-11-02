"""M3 frozen signal strategies: value types, canonical hash and pure window/target helpers.

``*_pct`` values are fractions (``Decimal('0.01')`` is 1%). The v1 signal function itself is reached
only through ``ports.signals.SignalSource``; nothing here imports it or performs I/O.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from functools import cached_property
import hashlib
import json

from .models import HoldingKind
from .promotion import Stage, thresholds_for
from .validation import DomainError, aware, decimal_value, identity, integer, trading_date


PROTOCOL_VERSION = 'm3-auto-v1'
INTERVALS = ('1m', '5m', '1d')
SESSIONS = ('day', 'night')
MAX_SPEC_JSON_CHARS = 100_000
MAX_CONTRACTS = 5

# M2 D5: allowed bar intervals and the time-stop cap (trading days) per holding kind.
KIND_INTERVALS = {
    HoldingKind.INTRADAY: ('1m', '5m'),
    HoldingKind.SWING: ('5m', '1d'),
    HoldingKind.POSITION: ('1d',),
}
KIND_MAX_HOLD_DAYS = {HoldingKind.INTRADAY: 0, HoldingKind.SWING: 10, HoldingKind.POSITION: 60}


class DirectionPolicy(str, Enum):
    BOTH = 'BOTH'
    LONG_ONLY = 'LONG_ONLY'


class WindowMode(str, Enum):
    FULL_HISTORY = 'FULL_HISTORY'
    PER_SESSION = 'PER_SESSION'


class SizingKind(str, Enum):
    FIXED_CONTRACTS = 'FIXED_CONTRACTS'
    LOT_AMOUNT = 'LOT_AMOUNT'


@dataclass(frozen=True)
class SignalBar:
    starts_at: datetime
    ends_at: datetime
    trade_date: date
    session: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        aware(self.starts_at, 'bar start')
        aware(self.ends_at, 'bar end')
        trading_date(self.trade_date)
        integer(self.volume, 'bar volume')
        prices = [decimal_value(getattr(self, name), name, positive=True) for name in ('open', 'high', 'low', 'close')]
        if self.starts_at >= self.ends_at or self.session not in SESSIONS or self.high < max(prices) or self.low > min(prices):
            raise DomainError('validation_failed', 'signal bar shape')


@dataclass(frozen=True)
class SignalPoint:
    """``at`` is the end of the bar that produced the signal; ``target`` is signed like v1 ``target_position``."""

    at: datetime
    target: int
    reason: str

    def __post_init__(self) -> None:
        aware(self.at, 'signal time')
        if type(self.target) is not int or type(self.reason) is not str or len(self.reason) > 200:
            raise DomainError('validation_failed', 'signal point')


@dataclass(frozen=True)
class TargetIntent:
    strategy_id: str
    version: int
    bar_end: datetime
    desired_quantity: int
    reason: str
    frozen_hash: str

    def __post_init__(self) -> None:
        identity(self.strategy_id)
        integer(self.version, 'strategy version', 1)
        aware(self.bar_end, 'bar end')
        identity(self.frozen_hash)
        if type(self.desired_quantity) is not int or type(self.reason) is not str:
            raise DomainError('validation_failed', 'target intent')

    def idempotency_key(self, leg: int) -> str:
        integer(leg, 'order leg')
        return f'auto:{self.frozen_hash[:12]}:{self.bar_end.astimezone(timezone.utc).isoformat()}:{leg}'


@dataclass(frozen=True)
class SizingRule:
    kind: SizingKind
    contracts: int | None = None
    amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.kind is SizingKind.FIXED_CONTRACTS and self.amount is None and type(self.contracts) is int and 1 <= self.contracts <= MAX_CONTRACTS:
            return
        if self.kind is SizingKind.LOT_AMOUNT and self.contracts is None and self.amount is not None:
            decimal_value(self.amount, 'sizing amount', positive=True)
            return
        raise DomainError('validation_failed', 'sizing rule')


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), 'f')


@dataclass(frozen=True)
class AutoStrategy:
    """The frozen build of a candidate. Any change is a new version via ``revised``; later stages live in the run record."""

    strategy_id: str
    version: int
    signal_spec_json: str
    candidate_fingerprint: str
    holding_kind: HoldingKind
    instrument_rule: str
    bar_interval: str
    window_mode: WindowMode
    history_anchor: date | None
    direction_policy: DirectionPolicy
    sizing: SizingRule
    protective_stop_pct: Decimal
    max_hold_days: int
    cost_version: str
    risk_ref: str
    thresholds_version: str
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        identity(self.strategy_id)
        integer(self.version, 'strategy version', 1)
        for name in ('candidate_fingerprint', 'instrument_rule', 'cost_version', 'risk_ref'):
            identity(getattr(self, name), name)
        thresholds_for(self.thresholds_version)
        if self.protocol_version != PROTOCOL_VERSION:
            raise DomainError('validation_failed', 'protocol version')
        if type(self.signal_spec_json) is not str or not self.signal_spec_json or len(self.signal_spec_json) > MAX_SPEC_JSON_CHARS:
            raise DomainError('validation_failed', 'signal spec json bounds')
        try:
            is_object = isinstance(json.loads(self.signal_spec_json), dict)
        except ValueError:
            is_object = False
        if not is_object:
            raise DomainError('validation_failed', 'signal spec must be a JSON object')
        if not isinstance(self.holding_kind, HoldingKind) or self.holding_kind not in KIND_INTERVALS:
            raise DomainError('validation_failed', 'holding kind')
        if not isinstance(self.direction_policy, DirectionPolicy) or not isinstance(self.sizing, SizingRule):
            raise DomainError('validation_failed', 'direction/sizing types')
        if self.bar_interval not in KIND_INTERVALS[self.holding_kind]:
            raise DomainError('validation_failed', 'bar interval not allowed for holding kind')
        intraday = self.holding_kind is HoldingKind.INTRADAY
        if self.window_mode is not (WindowMode.PER_SESSION if intraday else WindowMode.FULL_HISTORY):
            raise DomainError('validation_failed', 'window mode does not match holding kind')
        if (self.history_anchor is None) == (self.window_mode is WindowMode.FULL_HISTORY):
            raise DomainError('validation_failed', 'history anchor is required exactly for full-history windows')
        if self.history_anchor is not None:
            trading_date(self.history_anchor)
        if not Decimal(0) < decimal_value(self.protective_stop_pct, 'protective stop') < 1:
            raise DomainError('validation_failed', 'protective stop must be a fraction between 0 and 1')
        cap = KIND_MAX_HOLD_DAYS[self.holding_kind]
        if type(self.max_hold_days) is not int or not (self.max_hold_days == 0 if intraday else 1 <= self.max_hold_days <= cap):
            raise DomainError('validation_failed', 'max hold days')

    @property
    def stage(self) -> Stage:
        """A built or revised strategy always starts at BACKTEST."""
        return Stage.BACKTEST

    @cached_property
    def frozen_hash(self) -> str:
        body = {
            'strategy_id': self.strategy_id,
            'version': self.version,
            'signal_spec_json': self.signal_spec_json,
            'candidate_fingerprint': self.candidate_fingerprint,
            'holding_kind': self.holding_kind.value,
            'instrument_rule': self.instrument_rule,
            'bar_interval': self.bar_interval,
            'window_mode': self.window_mode.value,
            'history_anchor': None if self.history_anchor is None else self.history_anchor.isoformat(),
            'direction_policy': self.direction_policy.value,
            'sizing': [self.sizing.kind.value, self.sizing.contracts, None if self.sizing.amount is None else _decimal_text(self.sizing.amount)],
            'protective_stop_pct': _decimal_text(self.protective_stop_pct),
            'max_hold_days': self.max_hold_days,
            'cost_version': self.cost_version,
            'risk_ref': self.risk_ref,
            'thresholds_version': self.thresholds_version,
            'protocol_version': self.protocol_version,
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()

    def revised(self, **changes: object) -> 'AutoStrategy':
        if {'strategy_id', 'version', 'protocol_version'} & changes.keys():
            raise DomainError('validation_failed', 'strategy revision identity is immutable')
        return replace(self, version=self.version + 1, **changes)


@dataclass(frozen=True)
class CandidateSummary:
    candidate_ref: str
    verdict: str
    completed_at: datetime
    dataset_interval: str

    def __post_init__(self) -> None:
        identity(self.candidate_ref)
        identity(self.verdict)
        aware(self.completed_at, 'completed at')
        if self.dataset_interval not in INTERVALS:
            raise DomainError('validation_failed', 'dataset interval')


@dataclass(frozen=True)
class CandidateEvidence:
    """E1 qualification facts only. It deliberately has no field that can hold OOS or final-holdout values."""

    candidate_ref: str
    campaign_ref: str
    candidate_fingerprint: str
    verdict: str
    oos_consumed: bool
    sample_count: int
    completed_at: datetime
    dataset_family: str
    dataset_interval: str
    signal_spec_json: str

    def __post_init__(self) -> None:
        for name in ('candidate_ref', 'campaign_ref', 'candidate_fingerprint', 'verdict', 'dataset_family'):
            identity(getattr(self, name), name)
        integer(self.sample_count, 'sample count')
        aware(self.completed_at, 'completed at')
        if type(self.oos_consumed) is not bool or self.dataset_interval not in INTERVALS:
            raise DomainError('validation_failed', 'candidate evidence')
        if type(self.signal_spec_json) is not str or not self.signal_spec_json or len(self.signal_spec_json) > MAX_SPEC_JSON_CHARS:
            raise DomainError('validation_failed', 'signal spec json bounds')


def window_bars(auto: AutoStrategy, bars: tuple[SignalBar, ...], now: datetime, trade_date: date | None = None) -> tuple[SignalBar, ...]:
    """Completed bars (``ends_at <= now``) in the strategy window; never truncated, so the signals match the backtest.

    ``trade_date`` is the current trading day and is required for ``PER_SESSION``.
    """
    aware(now, 'now')
    if auto.window_mode is WindowMode.PER_SESSION:
        if trade_date is None:
            raise DomainError('validation_failed', 'per-session window requires the trade date')
        selected = tuple(b for b in bars if b.ends_at <= now and b.trade_date == trade_date)
    else:
        selected = tuple(b for b in bars if b.ends_at <= now and b.trade_date >= auto.history_anchor)
    if len(selected) > thresholds_for(auto.thresholds_version).EXECUTOR_MAX_BARS:
        raise DomainError('validation_failed', 'window exceeds the executor bar limit')
    return selected


def desired_target(points: tuple[SignalPoint, ...], as_of: datetime) -> int:
    """Target of the latest signal with ``at <= as_of`` (later entry wins a tie); no signal means flat."""
    aware(as_of, 'as of')
    target, latest = 0, None
    for point in points:
        if point.at <= as_of and (latest is None or point.at >= latest):
            target, latest = point.target, point.at
    return target


def apply_direction(target: int, policy: DirectionPolicy) -> int:
    return max(target, 0) if policy is DirectionPolicy.LONG_ONLY else target
