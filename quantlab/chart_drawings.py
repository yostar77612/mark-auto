"""Local display annotations; no research, market mutation or Qt dependencies.

Only UTC time/Decimal price anchors are durable. Projection returns transient
containing-bar positions; gaps and date-only bars do not invent timestamps.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tempfile
from quantlab.product_keys import converge_key, symbol_aliases

SCHEMA_VERSION = 1
MAX_DRAWINGS = 200
MAX_HISTORY = 100
MAX_FILE_BYTES = 262144


@dataclass(frozen=True)
class Anchor:
    timestamp: datetime
    price: Decimal

    def __post_init__(self):
        if not isinstance(self.timestamp, datetime) or self.timestamp.utcoffset() != timedelta(0):
            raise ValueError('anchor requires timezone-aware UTC time')
        if not isinstance(self.price, Decimal) or not self.price.is_finite() or self.price <= 0:
            raise ValueError('anchor requires positive finite Decimal price')


@dataclass(frozen=True)
class HorizontalLine:
    anchor: Anchor

    def __post_init__(self):
        if not isinstance(self.anchor, Anchor):
            raise ValueError('expected time/price anchor')


@dataclass(frozen=True)
class TrendLine:
    start: Anchor
    end: Anchor

    def __post_init__(self):
        if not isinstance(self.start, Anchor) or not isinstance(self.end, Anchor):
            raise ValueError('expected time/price anchors')


@dataclass(frozen=True)
class Ray(TrendLine):
    """Directed from start through end, clipped by the display viewport."""


@dataclass(frozen=True)
class Box(TrendLine):
    """Opposite time/price corners."""


KINDS = {'horizontal': HorizontalLine, 'trend': TrendLine, 'ray': Ray, 'box': Box}


def checked(drawings):
    result = tuple(drawings)
    if len(result) > MAX_DRAWINGS or any(type(d) not in KINDS.values() for d in result):
        raise ValueError('invalid or oversized drawing collection')
    return result


def anchors(drawing):
    return tuple(getattr(drawing, f.name) for f in fields(drawing))


def project_anchor(anchor, bars):
    """Return (transient ordinal, unchanged Decimal price), or None in a gap.

    Intervals are half open [timestamp, end); no nearest-bar extrapolation.
    """
    if not isinstance(anchor, Anchor):
        raise ValueError('expected time/price anchor')
    for position, bar in enumerate(bars):
        if bar.timestamp is not None and bar.end is not None and bar.timestamp <= anchor.timestamp < bar.end:
            return position, anchor.price
    return None


def serialize(drawings):
    records = []
    for drawing in checked(drawings):
        kind = next(k for k, cls in KINDS.items() if type(drawing) is cls)
        records.append(
            {
                'kind': kind,
                'anchors': [
                    {'timestamp': a.timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'), 'price': str(a.price)} for a in anchors(drawing)
                ],
            }
        )
    result = json.dumps({'version': SCHEMA_VERSION, 'drawings': records}, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(result.encode('utf-8')) > MAX_FILE_BYTES:
        raise ValueError('oversized drawings')
    return result


def deserialize(raw):
    try:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('oversized drawings')
        payload = json.loads(raw)
        if set(payload) != {'version', 'drawings'} or type(payload['version']) is not int or payload['version'] != SCHEMA_VERSION:
            raise ValueError('unsupported drawing schema')
        if not isinstance(payload['drawings'], list) or len(payload['drawings']) > MAX_DRAWINGS:
            raise ValueError('oversized drawings')
        result = []
        for record in payload['drawings']:
            if set(record) != {'kind', 'anchors'} or record['kind'] not in KINDS:
                raise ValueError('unknown drawing kind')
            values = []
            for a in record['anchors']:
                if set(a) != {'timestamp', 'price'} or not isinstance(a['price'], str):
                    raise ValueError('invalid anchor schema')
                values.append(Anchor(datetime.fromisoformat(a['timestamp'].replace('Z', '+00:00')), Decimal(a['price'])))
            result.append(KINDS[record['kind']](*values))
        return checked(result)
    except (TypeError, KeyError, ArithmeticError, RecursionError, AttributeError) as exc:
        raise ValueError('invalid drawings') from exc


class DrawingStore:
    """Dedicated <profile>/chart_drawings_v1/<instrument SHA256>.json files.

    Refuse research/data/results/hash-bound roots, including symlink targets.
    Invalid reads return no annotations and preserve the original file.
    """

    def __init__(self, profile):
        self.directory = Path(profile).resolve() / 'chart_drawings_v1'
        self._safe_path(self.directory)

    @staticmethod
    def _safe_path(path):
        if any(p.lower() in {'data', 'research', 'results', 'result_store', 'backtests'} or 'hash' in p.lower() for p in path.resolve().parts):
            raise ValueError('drawings require a separate display profile')

    def path_for(self, instrument):
        if not isinstance(instrument, str) or not instrument or len(instrument) > 256:
            raise ValueError('invalid instrument')
        path = self.directory / (hashlib.sha256(instrument.encode('utf-8')).hexdigest() + '.json')
        self._safe_path(path)
        return path

    def load_exact(self, instrument):
        path = self.path_for(instrument)
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            return deserialize(raw)
        except (OSError, ValueError, UnicodeError):
            return ()

    def load(self, instrument, enabled=True):
        """Read a deterministic union; never rewrite originals or shared views.

        Save always targets the exact original instrument. Shared results are
        display-only; edits must load_exact/save the owning instrument.
        Oversized unions fail closed rather than silently hiding some drawings.
        """
        self.path_for(instrument)
        key = converge_key(instrument, enabled)
        if not enabled or key not in {'TXF', 'MXF', 'TMF'}:
            return self.load_exact(instrument)
        sources = {instrument, *symbol_aliases(key)}
        try:
            for path in self.directory.glob('*.key'):
                self._safe_path(path)
                if path.stat().st_size > 1024:
                    continue
                original = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(original, str) and converge_key(original) == key and self.path_for(original).with_suffix('.key') == path:
                    sources.add(original)
            return checked(d for source in sorted(sources) for d in self.load_exact(source))
        except (OSError, ValueError, UnicodeError):
            return ()

    def save(self, instrument, drawings):
        raw = serialize(drawings).encode('utf-8')
        path = self.path_for(instrument)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Discovery metadata contains only the original display key; old code
        # aliases need no migration. No metadata or drawing is written on lookup.
        if converge_key(instrument) in {'TXF', 'MXF', 'TMF'}:
            path.with_suffix('.key').write_text(json.dumps(instrument), encoding='utf-8')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.drawings-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class DrawingHistory:
    """Immutable snapshots, at most MAX_HISTORY (100) undo/redo actions.

    Positions below select objects only; they are never market-bar anchors.
    Empty undo/redo are no-ops. Invalid actions leave both stacks untouched.
    """

    def __init__(self, drawings=()):
        self.drawings = checked(drawings)
        self._undo = []
        self._redo = []

    def _apply(self, drawings):
        value = checked(drawings)
        self._undo.append(self.drawings)
        self._undo = self._undo[-MAX_HISTORY:]
        self._redo.clear()
        self.drawings = value
        return value

    def add(self, drawing):
        return self._apply((*self.drawings, drawing))

    def move(self, position, drawing):
        values = list(self.drawings)
        values[position] = drawing
        return self._apply(values)

    def delete(self, position):
        values = list(self.drawings)
        del values[position]
        return self._apply(values)

    def undo(self):
        if self._undo:
            self._redo.append(self.drawings)
            self.drawings = self._undo.pop()
        return self.drawings

    def redo(self):
        if self._redo:
            self._undo.append(self.drawings)
            self.drawings = self._redo.pop()
        return self.drawings
