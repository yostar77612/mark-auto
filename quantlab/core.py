"""Validated, deterministic shared records. No broker or external dependencies."""
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import re


class ValidationError(ValueError):
    """Invalid research input; callers must fail closed."""



def _immutable(*args, **kwargs):
    raise TypeError("immutable research value; construct a new version")


class FrozenDict(dict):
    """Read-compatible dict snapshot whose ordinary mutation APIs reject writes."""
    __slots__ = ()
    def __new__(cls, *args, **kwargs):
        obj = dict.__new__(cls)
        dict.update(obj, *args, **kwargs)
        return obj
    def __init__(self, *args, **kwargs):
        pass
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable
    def __copy__(self): return self
    def __deepcopy__(self, memo): return self
    def __reduce__(self): return (FrozenDict, (dict(self),))


class FrozenList(list):
    """List-compatible immutable sequence for typed JSON AST callers."""
    __slots__ = ()
    def __new__(cls, values=()):
        obj = list.__new__(cls)
        list.extend(obj, values)
        return obj
    def __init__(self, values=()):
        pass
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _immutable
    def __copy__(self): return self
    def __deepcopy__(self, memo): return self
    def __reduce__(self): return (FrozenList, (list(self),))


def freeze(value):
    """Detach nested container aliases and preserve dict/list read semantics."""
    if isinstance(value, dict):
        return FrozenDict((key, freeze(item)) for key, item in value.items())
    if isinstance(value, list):
        return FrozenList(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value


def _freeze_fields(record):
    for item in fields(record):
        object.__setattr__(record, item.name, freeze(getattr(record, item.name)))

def validate_utc(value, name="timestamp"):
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValidationError(f"{name} must be timezone-aware UTC")


def validate_date(value, name="date"):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be ISO YYYY-MM-DD") from None


def validate_contract(value):
    if not isinstance(value, str) or not re.fullmatch(r"TAIFEX:TMF:\d{6}", value):
        raise ValidationError("explicit TAIFEX:TMF:YYYYMM contract required")
    try:
        date(int(value[-6:-2]), int(value[-2:]), 1)
    except ValueError:
        raise ValidationError("invalid contract month") from None


def validate_int(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValidationError(f"{name} must be integer" + (f" >= {minimum}" if minimum is not None else ""))


def validate_decimal(value, name, minimum=None, tick=False):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError(f"{name} must be finite Decimal")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{name} below minimum {minimum}")
    if tick and value != value.to_integral_value():
        raise ValidationError(f"{name} must be integral one-point tick")


def _json_value(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Decimal):
        validate_decimal(value, "decimal")
        return format(value, 'f')
    if isinstance(value, datetime):
        validate_utc(value)
        return value.isoformat().replace('+00:00', 'Z')
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValidationError("JSON keys must be strings")
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("nonfinite JSON number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValidationError(f"unsupported JSON value {type(value).__name__}")


def to_dict(value):
    result = _json_value(value)
    if not isinstance(result, dict):
        raise ValidationError("to_dict requires an object")
    return result


def canonical_json(value):
    return json.dumps(_json_value(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Instrument:
    contract_id: str
    multiplier: Decimal = Decimal('10')
    tick_size: Decimal = Decimal('1')
    expiry: str | None = None

    def __post_init__(self):
        validate_contract(self.contract_id)
        if self.multiplier != Decimal('10') or self.tick_size != Decimal('1'):
            raise ValidationError("only TMF multiplier 10 and tick 1 supported")
        validate_decimal(self.multiplier, 'multiplier')
        validate_decimal(self.tick_size, 'tick_size')
        if self.expiry is not None:
            validate_date(self.expiry, 'expiry')


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    end: datetime
    trade_date: str
    session: str
    contract_id: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_id: str = ''

    def __post_init__(self):
        validate_utc(self.timestamp)
        validate_utc(self.end, 'end')
        if self.end <= self.timestamp:
            raise ValidationError("bar end must follow start")
        validate_date(self.trade_date, 'trade_date')
        validate_contract(self.contract_id)
        if self.session not in ('day', 'night'):
            raise ValidationError("invalid session")
        for name in ('open', 'high', 'low', 'close'):
            validate_decimal(getattr(self, name), name, Decimal('1'), tick=True)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValidationError("inconsistent OHLC")
        validate_int(self.volume, 'volume', 0)


@dataclass(frozen=True)
class Dataset:
    bars: tuple[Bar, ...]
    manifest: dict
    quality: dict

    def __post_init__(self):
        if not isinstance(self.bars, tuple) or any(not isinstance(b, Bar) for b in self.bars):
            raise ValidationError("bars must be tuple of Bar")
        if not isinstance(self.manifest, dict) or not isinstance(self.quality, dict):
            raise ValidationError("manifest and quality must be objects")
        canonical_json(self.manifest)
        canonical_json(self.quality)
        _freeze_fields(self)


@dataclass(frozen=True)
class CostSpec:
    commission_per_side: Decimal
    tax_rate: Decimal
    slippage_ticks: int
    tax_rounding: str
    effective_from: str
    version: str

    def __post_init__(self):
        validate_decimal(self.commission_per_side, 'commission', Decimal('0'))
        validate_decimal(self.tax_rate, 'tax_rate', Decimal('0'))
        validate_int(self.slippage_ticks, 'slippage_ticks', 0)
        validate_date(self.effective_from, 'effective_from')
        if not isinstance(self.tax_rounding, str) or not self.tax_rounding or not isinstance(self.version, str) or not self.version:
            raise ValidationError("named tax rounding and version required")


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    family: str
    parameters: dict
    rules: dict
    schema_version: int = 1

    def __post_init__(self):
        if not self.strategy_id or not self.family or not isinstance(self.parameters, dict) or not isinstance(self.rules, dict):
            raise ValidationError("strategy requires id, family and parameter/rule objects")
        validate_int(self.schema_version, 'schema_version', 1)
        canonical_json(self.parameters)
        canonical_json(self.rules)
        _freeze_fields(self)


@dataclass(frozen=True)
class Signal:
    timestamp: datetime
    contract_id: str
    target_position: int
    reason: str

    def __post_init__(self):
        validate_utc(self.timestamp)
        validate_contract(self.contract_id)
        validate_int(self.target_position, 'target_position')


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    timestamp: datetime
    contract_id: str
    side: str
    quantity: int
    price: Decimal
    commission: Decimal
    tax: Decimal
    reason: str = ''

    def __post_init__(self):
        validate_utc(self.timestamp)
        validate_contract(self.contract_id)
        validate_int(self.quantity, 'quantity', 1)
        validate_decimal(self.price, 'price', Decimal('1'), tick=True)
        validate_decimal(self.commission, 'commission', Decimal('0'))
        validate_decimal(self.tax, 'tax', Decimal('0'))
        if self.side not in ('buy', 'sell') or not self.fill_id or not self.order_id:
            raise ValidationError("fill needs buy/sell side and identifiers")


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: Decimal
    costs: CostSpec
    max_position: int = 1
    same_bar_policy: str = 'conservative'
    seed: int = 0
    initial_margin_per_contract: Decimal | None = None
    margin_version: str | None = None
    maintenance_margin_per_contract: Decimal | None = None
    cost_schedule: tuple[CostSpec, ...] = ()
    margin_schedule: tuple[dict, ...] = ()
    instrument_expiries: dict = field(default_factory=dict)
    roll_events: tuple[dict, ...] = ()
    settlement_mode: str = 'unsettled_pnl'
    settlement_events: tuple[dict, ...] = ()
    source_commit: str = 'unrecorded'

    def __post_init__(self):
        validate_decimal(self.initial_cash, 'initial_cash', Decimal('0'))
        if not isinstance(self.costs, CostSpec):
            raise ValidationError("explicit CostSpec required")
        validate_int(self.max_position, 'max_position', 1)
        validate_int(self.seed, 'seed', 0)
        for name in ('initial_margin_per_contract', 'maintenance_margin_per_contract'):
            if getattr(self, name) is not None:
                validate_decimal(getattr(self, name), name, Decimal('0'))
        if not isinstance(self.cost_schedule, tuple) or any(not isinstance(c, CostSpec) for c in self.cost_schedule):
            raise ValidationError('cost_schedule must be tuple of CostSpec')
        for name in ('margin_schedule', 'roll_events', 'settlement_events'):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(v, dict) for v in value):
                raise ValidationError(f'{name} must be tuple of objects')
            canonical_json(value)
        if not isinstance(self.instrument_expiries, dict):
            raise ValidationError('instrument_expiries must be object')
        if self.settlement_mode not in ('unsettled_pnl', 'daily_mtm'):
            raise ValidationError('unsupported settlement_mode')
        if self.same_bar_policy != 'conservative':
            raise ValidationError("only conservative same-bar policy supported")
        _freeze_fields(self)


@dataclass(frozen=True)
class BacktestResult:
    manifest: dict
    signals: tuple[Signal, ...]
    fills: tuple[Fill, ...]
    ledger: tuple[dict, ...]
    equity: tuple[dict, ...]
    metrics: dict
    rejects: tuple[dict, ...]
    warnings: tuple[str, ...]


    def __post_init__(self):
        canonical_json(self)
        _freeze_fields(self)
