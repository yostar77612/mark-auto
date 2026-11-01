"""Validated alert rules and deterministic Decimal-only signal evaluation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .freshness import Freshness
from .live_bars import LiveBar
from .validation import DomainError, aware, decimal_value, identity


class AlertKind(str, Enum):
    PRICE_CROSS = 'PRICE_CROSS'
    CHANGE_PERCENT = 'CHANGE_PERCENT'
    FAST_MOVE = 'FAST_MOVE'
    DAY_HIGH_LOW = 'DAY_HIGH_LOW'
    PREV_DAY_BREAK = 'PREV_DAY_BREAK'
    VOLUME_SURGE = 'VOLUME_SURGE'
    MA_CROSS = 'MA_CROSS'
    KD_CROSS = 'KD_CROSS'
    LIMIT_UP = 'LIMIT_UP'
    LIMIT_DOWN = 'LIMIT_DOWN'
    PRICE_JUMP = 'PRICE_JUMP'
    VOLUME_BURST = 'VOLUME_BURST'


SCANNER_KINDS = frozenset((AlertKind.LIMIT_UP, AlertKind.LIMIT_DOWN, AlertKind.PRICE_JUMP, AlertKind.VOLUME_BURST))
BAR_KINDS = frozenset((AlertKind.FAST_MOVE, AlertKind.VOLUME_SURGE, AlertKind.MA_CROSS, AlertKind.KD_CROSS))
DEFAULT_PARAMS = {
    AlertKind.PRICE_CROSS: {'price': Decimal('100'), 'direction': 'UP'},
    AlertKind.CHANGE_PERCENT: {'percent': Decimal('1'), 'direction': 'ANY'},
    AlertKind.FAST_MOVE: {'minutes': 5, 'percent': Decimal('1'), 'direction': 'ANY'},
    AlertKind.DAY_HIGH_LOW: {'direction': 'ANY'},
    AlertKind.PREV_DAY_BREAK: {'direction': 'ANY'},
    AlertKind.VOLUME_SURGE: {'period': '1m', 'count': 5, 'multiple': Decimal('2')},
    AlertKind.MA_CROSS: {'period': '1m', 'short': 5, 'long': 20, 'direction': 'ANY'},
    AlertKind.KD_CROSS: {'period': '1m', 'n': 9, 'k_smoothing': 3, 'd_smoothing': 3, 'low': Decimal('20'), 'high': Decimal('80'), 'direction': 'ANY'},
    AlertKind.LIMIT_UP: {'subtype': 'TOUCH'},
    AlertKind.LIMIT_DOWN: {'subtype': 'TOUCH'},
    AlertKind.PRICE_JUMP: {'direction': 'ANY'},
    AlertKind.VOLUME_BURST: {},
}


def validate_params(kind: AlertKind, supplied: Mapping) -> Mapping:
    """Validate once at UI/file boundaries; return normalized immutable values."""
    params = {**DEFAULT_PARAMS[kind], **supplied}
    if set(params) != set(DEFAULT_PARAMS[kind]):
        raise DomainError('alert_invalid_params', 'unknown parameter')
    ranges = {
        'percent': ('0.1', '10'),
        'minutes': (1, 30),
        'count': (3, 60),
        'multiple': ('1.5', '20'),
        'short': (2, 60),
        'long': (3, 240),
        'n': (2, 30),
        'k_smoothing': (2, 30),
        'd_smoothing': (2, 30),
        'low': ('0', '50'),
        'high': ('50', '100'),
    }
    integers = {'minutes', 'count', 'short', 'long', 'n', 'k_smoothing', 'd_smoothing'}
    try:
        for key, value in tuple(params.items()):
            if key in integers:
                number = Decimal(str(value))
                if number != number.to_integral_value():
                    raise ValueError(key)
                params[key] = int(number)
            elif key in ranges or key == 'price':
                params[key] = Decimal(str(value))
                if not params[key].is_finite():
                    raise ValueError(key)
            if key in ranges:
                low, high = ranges[key]
                if not Decimal(str(low)) <= params[key] <= Decimal(str(high)):
                    raise ValueError(key)
        if 'price' in params and params['price'] <= 0:
            raise ValueError('price')
        if 'short' in params and params['short'] >= params['long']:
            raise ValueError('short/long')
        if 'direction' in params and params['direction'] not in ('UP', 'DOWN', 'ANY'):
            raise ValueError('direction')
        if 'subtype' in params and params['subtype'] not in ('NEAR', 'TOUCH', 'OPEN'):
            raise ValueError('subtype')
        if 'period' in params and params['period'] not in (('1m', '5m', '15m') if kind == AlertKind.VOLUME_SURGE else ('1m', '5m', '15m', '1d')):
            raise ValueError('period')
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise DomainError('alert_invalid_params', key if isinstance(exc, InvalidOperation) else str(exc)) from exc
    return MappingProxyType(params)


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    kind: AlertKind
    scope: str = 'INSTRUMENT'
    instrument_id: str = ''
    params: Mapping = field(default_factory=dict)
    enabled: bool = True
    cooldown_seconds: int = 60

    def __post_init__(self):
        identity(self.rule_id, 'rule_id')
        if not isinstance(self.kind, AlertKind):
            raise DomainError('alert_invalid_params', 'kind')
        if self.scope not in ('INSTRUMENT', 'WATCHLIST', 'MARKET') or (self.scope == 'INSTRUMENT' and not self.instrument_id):
            raise DomainError('alert_invalid_params', 'scope/instrument')
        if self.scope == 'INSTRUMENT':
            identity(self.instrument_id, 'instrument_id')
            if self.instrument_id.startswith('INDEX:') and self.kind in (AlertKind.VOLUME_SURGE, *SCANNER_KINDS):
                raise DomainError('alert_invalid_params', 'stock-only rule')
        if self.scope == 'MARKET' and self.kind not in SCANNER_KINDS:
            raise DomainError('alert_invalid_params', 'market scope requires scanner')
        if type(self.enabled) is not bool or type(self.cooldown_seconds) is not int or not 10 <= self.cooldown_seconds <= 3600:
            raise DomainError('alert_invalid_params', 'cooldown/enabled')
        object.__setattr__(self, 'params', validate_params(self.kind, self.params))


@dataclass(frozen=True)
class AlertEvent:
    event_id: str
    rule_id: str
    kind: AlertKind
    instrument_id: str
    occurred_at: datetime
    value: Decimal | None
    message_key: str
    message_args: tuple = ()

    def __post_init__(self):
        identity(self.event_id, 'event_id')
        identity(self.rule_id, 'rule_id')
        identity(self.instrument_id, 'instrument_id')
        object.__setattr__(self, 'occurred_at', aware(self.occurred_at).astimezone(timezone.utc))
        if self.value is not None:
            decimal_value(self.value, 'alert value')
        if self.message_key != 'alert.event.' + self.kind.value.lower():
            raise DomainError('alert_invalid_params', 'message_key')


@dataclass(frozen=True)
class AlertObservation:
    instrument_id: str
    occurred_at: datetime
    price: Decimal | None = None
    previous_price: Decimal | None = None
    reference_price: Decimal | None = None
    previous_high: Decimal | None = None
    previous_low: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    minutes_since_open: int = 0
    freshness: Freshness = Freshness.UNKNOWN
    backfilling: bool = False
    bars: tuple[LiveBar, ...] = ()
    period: str = '1m'
    scanner_kind: AlertKind | None = None
    scanner_subtype: str = ''
    scanner_direction: str = 'ANY'
    scanner_active: bool = True


def sma(values: tuple[Decimal, ...], count: int) -> Decimal | None:
    return sum(values[-count:], Decimal(0)) / count if len(values) >= count else None


def kd(bars: tuple[LiveBar, ...], n: int = 9, k_smoothing: int = 3, d_smoothing: int = 3) -> tuple[tuple[Decimal, Decimal], ...]:
    k = d = Decimal(50)
    result = []
    for end in range(n, len(bars) + 1):
        window = bars[end - n : end]
        high, low = max(bar.high for bar in window), min(bar.low for bar in window)
        rsv = Decimal(50) if high == low else (window[-1].close - low) / (high - low) * 100
        k = ((k_smoothing - 1) * k + rsv) / k_smoothing
        d = ((d_smoothing - 1) * d + k) / d_smoothing
        result.append((k, d))
    return tuple(result)


def _direction(up: bool, down: bool, direction: str) -> bool:
    return (direction in ('UP', 'ANY') and up) or (direction in ('DOWN', 'ANY') and down)


def alert_condition(rule: AlertRule, observation: AlertObservation) -> tuple[bool, Decimal | None] | None:
    """None means no eligible input; False means eligible and re-armable."""
    kind, p, o = rule.kind, rule.params, observation
    if kind in SCANNER_KINDS:
        if o.scanner_kind != kind:
            return None
        matches = o.scanner_active and ('subtype' not in p or o.scanner_subtype == p['subtype'])
        if kind == AlertKind.PRICE_JUMP:
            matches = matches and (p['direction'] == 'ANY' or p['direction'] == o.scanner_direction)
        return matches, o.price
    if kind in BAR_KINDS:
        return _bar_condition(rule, observation)
    return _tick_condition(rule, observation)


def _bar_condition(rule: AlertRule, observation: AlertObservation) -> tuple[bool, Decimal | None] | None:
    kind, p, o = rule.kind, rule.params, observation
    expected_period = '1m' if kind == AlertKind.FAST_MOVE else p['period']
    if o.period != expected_period or not o.bars or not o.bars[-1].final or o.bars[-1].incomplete:
        return None
    bars = tuple(bar for bar in o.bars if bar.final and not bar.incomplete)
    closes = tuple(bar.close for bar in bars)
    if kind == AlertKind.FAST_MOVE:
        if len(bars) < p['minutes'] or bars[-p['minutes']].open == 0:
            return None
        value = (bars[-1].close / bars[-p['minutes']].open - 1) * 100
        return _direction(value >= p['percent'], value <= -p['percent'], p['direction']), value
    if kind == AlertKind.VOLUME_SURGE:
        if len(bars) <= p['count'] or o.instrument_id.split(':')[-1].startswith('IX'):
            return None
        average = sum(Decimal(bar.volume) for bar in bars[-p['count'] - 1 : -1]) / p['count']
        return average > 0 and bars[-1].volume >= average * p['multiple'], Decimal(bars[-1].volume)
    if kind == AlertKind.MA_CROSS:
        if len(closes) <= p['long']:
            return None
        before = sma(closes[:-1], p['short']) - sma(closes[:-1], p['long'])
        value = sma(closes, p['short']) - sma(closes, p['long'])
        return _direction(before <= 0 < value, before >= 0 > value, p['direction']), value
    values = kd(bars, p['n'], p['k_smoothing'], p['d_smoothing'])
    if len(values) < 2:
        return None
    (pk, pd), (k, d) = values[-2:]
    return _direction(pk <= pd and k > d and k < p['low'], pk >= pd and k < d and k > p['high'], p['direction']), k


def _tick_condition(rule: AlertRule, observation: AlertObservation) -> tuple[bool, Decimal | None] | None:
    kind, p, o = rule.kind, rule.params, observation
    if o.freshness != Freshness.LIVE or o.backfilling or o.price is None:
        return None
    price = o.price
    if kind == AlertKind.PRICE_CROSS:
        if o.previous_price is None:
            return None
        return _direction(o.previous_price < p['price'] <= price, o.previous_price > p['price'] >= price, p['direction']), price
    if kind == AlertKind.CHANGE_PERCENT:
        if o.reference_price is None or o.reference_price <= 0:
            return None
        value = (price / o.reference_price - 1) * 100
        return _direction(value >= p['percent'], value <= -p['percent'], p['direction']), value
    if kind == AlertKind.DAY_HIGH_LOW:
        if o.minutes_since_open < 5 or o.day_high is None or o.day_low is None:
            return None
        return _direction(price > o.day_high, price < o.day_low, p['direction']), price
    if o.previous_high is None or o.previous_low is None:
        return None
    return _direction(price > o.previous_high, price < o.previous_low, p['direction']), price


@dataclass(frozen=True)
class AlertTriggerState:
    active: bool = False
    last_fired_at: datetime | None = None


def evaluate_alert(rule: AlertRule, observation: AlertObservation, state: AlertTriggerState) -> tuple[AlertTriggerState, bool, Decimal | None]:
    condition = alert_condition(rule, observation) if rule.enabled else None
    if condition is None:
        return state, False, None
    active, value = condition
    cooled = state.last_fired_at is None or (observation.occurred_at - state.last_fired_at).total_seconds() >= rule.cooldown_seconds
    fired = active and not state.active and cooled
    return AlertTriggerState(active, observation.occurred_at if fired else state.last_fired_at), fired, value
