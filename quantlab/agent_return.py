"""Pure D11 envelopes for already projected, authorized JSON rows.

This module does not establish provenance. Callers must filter protected data
BEFORE supplying rows, including before deriving totals or cursor fingerprints.
Cursor hashes bind visible content, scope and offset; they are consistency
checks, not credentials or authorization grants.
"""

import hashlib
import json
import math

from quantlab.agent_tool_contract import MAX_LIMIT, MAX_RETURN_BYTES


MAX_FIELD_CHARS = 256
MAX_DEPTH = 16
MAX_NODES = 1000000


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _size(value):
    # Bound both canonical UTF-8 and ordinary json.dumps consumers (ASCII escapes
    # and spaces), so callers cannot accidentally enlarge a bounded return.
    return max(len(_json(value).encode('utf-8')), len(json.dumps(value, allow_nan=False).encode('utf-8')))


def _copy(value, markers, field=(), depth=0, budget=None):
    if budget is None:
        budget = [MAX_NODES]
    budget[0] -= 1
    if depth > MAX_DEPTH or budget[0] < 0:
        raise ValueError
    kind = type(value)
    if kind is dict:
        if any(type(key) is not str or len(key) > MAX_FIELD_CHARS for key in value):
            raise ValueError
        return {key: _copy(child, markers, (*field, key), depth + 1, budget) for key, child in sorted(value.items())}
    if kind is list:
        return [_copy(child, markers, (*field, index), depth + 1, budget) for index, child in enumerate(value)]
    if kind is str:
        value.encode('utf-8')  # Refuse lone surrogates, even beyond the field cap.
        if len(value) > MAX_FIELD_CHARS:
            markers.append({'field': list(field), 'truncated': True})
        return value[:MAX_FIELD_CHARS]
    if kind is float and not math.isfinite(value):
        raise ValueError
    if value is None or kind in (bool, int, float):
        return value
    raise ValueError


def bounded_return(rows, *, limit=MAX_LIMIT, cursor=None, scope=''):
    """Return one bounded page; refuse unsafe JSON, invalid limits/cursors.

    Limits are strict, never coerced/clamped. Full source JSON is fingerprinted
    before field capping, so edits beyond a capped prefix also stale a cursor.
    Empty/non-progressing byte pages refuse rather than loop or silently drop an
    item. Field capping is explicit and does not imply a continuation exists.
    """
    if type(rows) is not list or type(limit) is not int or not 1 <= limit <= MAX_LIMIT or type(scope) is not str:
        raise ValueError
    markers = []
    copied = _copy(rows, markers)
    source = _json([scope, rows])  # _copy has rejected all non-JSON types.

    def token(offset):
        digest = hashlib.sha256((str(offset) + ':' + source).encode('utf-8')).hexdigest()
        return str(offset) + ':' + digest

    start = 0
    if cursor is not None:
        if type(cursor) is not str or len(cursor) > 128:
            raise ValueError
        offset = cursor.split(':', 1)[0]
        if not offset.isascii() or not offset.isdecimal() or len(offset) > 10:
            raise ValueError
        start = int(offset)
        if not 0 < start < len(rows) or cursor != token(start):
            raise ValueError

    def envelope(end, reason):
        fields = [{'item': entry['field'][0] - start, 'field': entry['field'][1:], 'truncated': True} for entry in markers if start <= entry['field'][0] < end]
        more = end < len(rows)
        return {
            'ok': True,
            'items': copied[start:end],
            'count': end - start,
            'total': len(rows),
            'limit': limit,
            'truncated': more or bool(fields),
            'reason': reason if more else ('field_limit' if fields else None),
            'next_cursor': token(end) if more else None,
            'field_truncations': fields,
        }

    end = min(start + limit, len(rows))
    result = envelope(end, 'item_limit')
    while _size(result) > MAX_RETURN_BYTES and end > start:
        end -= 1
        result = envelope(end, 'byte_limit')
    if _size(result) > MAX_RETURN_BYTES or (end == start and start < len(rows)):
        raise ValueError
    return result
