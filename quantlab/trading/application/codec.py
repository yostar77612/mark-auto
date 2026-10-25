"""Bounded, tagged DTO wire format. Only explicitly registered classes decode."""

from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import json

from quantlab.trading.domain.validation import DomainError

MAX_BYTES = 4 * 1024 * 1024
_TYPES: dict[str, type] = {}


def register(*classes: type) -> None:
    for cls in classes:
        key = cls.__module__ + '.' + cls.__qualname__
        if key in _TYPES and _TYPES[key] is not cls:
            raise DomainError('validation_failed', 'duplicate wire type')
        _TYPES[key] = cls


def _encode(value: object, depth: int = 0) -> object:
    if depth > 32:
        raise DomainError('validation_failed', 'wire depth')
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return {'@': type(value).__module__ + '.' + type(value).__qualname__, 'value': value.value}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DomainError('validation_failed', 'nonfinite money')
        return {'@': 'decimal', 'value': str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DomainError('validation_failed', 'naive wire time')
        return {'@': 'datetime', 'value': value.astimezone(timezone.utc).isoformat()}
    if type(value) is date:
        return {'@': 'date', 'value': value.isoformat()}
    if isinstance(value, (tuple, frozenset)):
        sequence = sorted(value, key=str) if isinstance(value, frozenset) else value
        return {'@': 'set' if isinstance(value, frozenset) else 'tuple', 'value': [_encode(v, depth + 1) for v in sequence]}
    if is_dataclass(value) and not isinstance(value, type):
        key = type(value).__module__ + '.' + type(value).__qualname__
        if key not in _TYPES:
            raise DomainError('validation_failed', 'unregistered DTO')
        return {'@': key, 'fields': {f.name: _encode(getattr(value, f.name), depth + 1) for f in fields(value)}}
    raise DomainError('validation_failed', 'unsupported wire value')


def dumps(value: object) -> str:
    result = json.dumps(_encode(value), ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(result.encode()) > MAX_BYTES:
        raise DomainError('validation_failed', 'wire byte limit')
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DomainError('validation_failed', 'duplicate wire key')
        result[key] = value
    return result


def _decode(value: object, depth: int = 0) -> object:
    if depth > 32:
        raise DomainError('validation_failed', 'wire depth')
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is not dict or '@' not in value:
        raise DomainError('validation_failed', 'untyped wire object')
    kind = value['@']
    if kind in ('decimal', 'datetime', 'date', 'tuple', 'set'):
        if set(value) != {'@', 'value'}:
            raise DomainError('validation_failed', 'wire fields')
        raw = value['value']
        if kind == 'decimal':
            if type(raw) is not str:
                raise DomainError('validation_failed', 'money must be decimal text')
            result = Decimal(raw)
            if not result.is_finite():
                raise DomainError('validation_failed', 'nonfinite money')
            return result
        if kind == 'datetime':
            result = datetime.fromisoformat(raw)
            if result.tzinfo is None or result.utcoffset() is None:
                raise DomainError('validation_failed', 'naive wire time')
            return result
        if kind == 'date':
            return date.fromisoformat(raw)
        if type(raw) is not list or len(raw) > 10000:
            raise DomainError('validation_failed', 'wire collection')
        items = tuple(_decode(v, depth + 1) for v in raw)
        return frozenset(items) if kind == 'set' else items
    cls = _TYPES.get(kind)
    if cls is None:
        raise DomainError('validation_failed', 'unknown wire schema')
    if issubclass(cls, Enum):
        if set(value) != {'@', 'value'}:
            raise DomainError('validation_failed', 'enum fields')
        return cls(value['value'])
    if set(value) != {'@', 'fields'} or type(value['fields']) is not dict:
        raise DomainError('validation_failed', 'DTO fields')
    return cls(**{k: _decode(v, depth + 1) for k, v in value['fields'].items()})


def loads(text: str) -> object:
    if type(text) is not str or len(text.encode()) > MAX_BYTES:
        raise DomainError('validation_failed', 'wire byte limit')
    try:
        return _decode(json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant'))))
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError('validation_failed', 'invalid wire document') from exc
