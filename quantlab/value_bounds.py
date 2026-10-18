"""Shared numeric and metadata validation, independent of experiment runners."""
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import re
from .core import ValidationError

def _bounded_number(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError('Finite bounded decimal required')
    parts = value.as_tuple()
    if abs(parts.exponent) > 32 or len(parts.digits) > 64 or value.copy_abs() > Decimal('1e15'):
        raise ValidationError('Decimal precision, exponent or magnitude exceeds resource bounds')



def _exact_number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValidationError('Finite numeric value required')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError('Finite numeric value required') from None
    _bounded_number(result)
    return result



def _bounded_value(value, *, max_nodes=4096):
    """Bound BEFORE canonical serialization or JSON numeric conversion."""
    count, byte_count = 0, 0
    def visit(item, depth=0):
        nonlocal count, byte_count
        count += 1
        if count > max_nodes or depth > 16:
            raise ValidationError('Plan/metadata structure exceeds resource bounds')
        if isinstance(item, Decimal):
            _bounded_number(item)
        elif is_dataclass(item) and not isinstance(item, type):
            for entry in fields(item):
                visit(getattr(item, entry.name), depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError('JSON object keys must be strings')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > 16384:
                raise ValidationError('Plan/metadata string exceeds resource bounds')
            byte_count += len(item.encode('utf-8'))
            if byte_count > 131072:
                raise ValidationError('Plan/metadata bytes exceed resource bounds')
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', item):
                _exact_number(item)
        elif type(item) is int:
            if item.bit_length() > 64:
                raise ValidationError('Integer exceeds resource bounds')
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValidationError('Nonfinite JSON value')
            _bounded_number(Decimal(str(item)))
        elif item is not None and type(item) is not bool and not isinstance(item, datetime):
            raise ValidationError('Unsupported plan/metadata type')
    visit(value)

