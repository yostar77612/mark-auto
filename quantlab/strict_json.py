"""Shared JSON input boundary: unique keys, standard constants and bounded files."""

import json
from pathlib import Path

from .core import ValidationError


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValidationError(f'Invalid JSON constant: {value}')


def loads(text):
    """Parse JSON text, rejecting ambiguous objects and nonstandard constants."""
    if not isinstance(text, str):
        raise ValidationError('JSON input must be text')
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except ValidationError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ValidationError('Invalid JSON document') from exc


def read(path, max_bytes):
    """Check the byte limit before decoding UTF-8 or parsing the document."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValidationError('JSON byte limit must be a nonnegative integer')
    path = Path(path)
    limit = f'{max_bytes // (1024 * 1024)} MiB' if max_bytes and max_bytes % (1024 * 1024) == 0 else f'{max_bytes} bytes'
    if path.stat().st_size > max_bytes:
        raise ValidationError(f'JSON file exceeds {limit} limit')
    # A bounded binary read also enforces the limit if the file grows after stat.
    with path.open('rb') as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationError(f'JSON file exceeds {limit} limit')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValidationError('JSON file must be UTF-8') from exc
    return loads(text)
