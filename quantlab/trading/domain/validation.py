"""Strict values at public domain boundaries."""

from datetime import date, datetime
from decimal import Decimal


class DomainError(ValueError):
    def __init__(self, code: str, detail: str = '') -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f'{code}: {detail}')


def decimal_value(value: Decimal, name: str, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainError('validation_failed', f'{name} requires a finite Decimal')
    if len(value.as_tuple().digits) > 50 or not -64 <= value.as_tuple().exponent <= 18 or value.copy_abs() > Decimal('1e18'):
        raise DomainError('validation_failed', f'{name} exceeds numeric resource bounds')
    if positive and value <= 0 or nonnegative and value < 0:
        raise DomainError('validation_failed', name)
    return value


def integer(value: int, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > 1000000000000:
        raise DomainError('validation_failed', name)
    return value


def aware(value: datetime, name: str = 'timestamp') -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError('validation_failed', f'{name} requires timezone')
    return value


def trading_date(value: date) -> date:
    if type(value) is not date:
        raise DomainError('validation_failed', 'trade_date')
    return value


def identity(value: str, name: str = 'identity') -> str:
    if not isinstance(value, str) or not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise DomainError('validation_failed', name)
    return value
