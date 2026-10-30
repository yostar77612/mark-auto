"""desktop_app components chart_annotations responsibilities."""

from desktop_app.strings.catalog import ui_text
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta
import math
import re


@dataclass(frozen=True)
class ChartTrace:
    contract_id: str
    data_hash: str
    strategy_hash: str
    mode: str

    def __post_init__(self):
        if not self.contract_id or self.mode not in (ui_text('charts.post_init.backtest'), ui_text('charts.post_init.paper')):
            raise ValueError(ui_text('charts.post_init.contract_mode_required'))
        if any(not re.fullmatch('[0-9a-f]{64}', x) for x in (self.data_hash, self.strategy_hash)):
            raise ValueError(ui_text('charts.post_init.data_strategy_hash_required'))


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
        raise ValueError(ui_text('charts.number.finite_number_required'))
    return float(value)


def _validate_chart_bar(bar):
    """Validate one externally supplied display bar for every series boundary."""
    o, h, l, c = map(_number, (bar.open, bar.high, bar.low, bar.close))
    if not l <= min(o, c) <= max(o, c) <= h:
        raise ValueError(ui_text('charts.set_series.invalid_ohlc'))
    if bar.volume is not None and (type(bar.volume) is not int or bar.volume < 0):
        raise ValueError(ui_text('charts.set_series.invalid_volume'))


@dataclass(frozen=True)
class ChartMarker:
    index: int
    kind: str
    label: str
    price: Decimal | None = None
    quantity: int | None = None
    cost: Decimal | None = None
    reason: str = ''
    timestamp: object = None
    target_position: int | None = None

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0 or self.kind not in ('signal', 'fill'):
            raise ValueError(ui_text('charts.post_init.invalid_marker'))
        if not self.label:
            raise ValueError(ui_text('charts.post_init.label_required'))
        if self.target_position is not None and type(self.target_position) is not int:
            raise ValueError(ui_text('charts.post_init.integer_target_required'))
        if self.kind == 'signal' and self.price is not None:
            raise ValueError(ui_text('charts.post_init.signal_price_forbidden'))
        if self.kind == 'fill' and (self.price is None or type(self.quantity) is not int or self.quantity <= 0):
            raise ValueError(ui_text('charts.post_init.fill_price_quantity_required'))
        for value in (self.price, self.cost):
            if value is not None:
                _number(value)
        if self.cost is not None and self.cost < 0:
            raise ValueError(ui_text('charts.post_init.negative_cost'))


@dataclass(frozen=True)
class ReferenceLine:
    label: str
    price: Decimal
    snapshot_index: int | None = None
    as_of: datetime | None = None

    def __post_init__(self):
        if not self.label:
            raise ValueError(ui_text('charts.post_init.reference_label_required'))
        _number(self.price)
        if (self.snapshot_index is None) != (self.as_of is None):
            raise ValueError(ui_text('charts.post_init.snapshot_pair_required'))
        if self.snapshot_index is not None:
            if type(self.snapshot_index) is not int or self.snapshot_index < 0:
                raise ValueError(ui_text('charts.post_init.invalid_snapshot_index'))
            if not isinstance(self.as_of, datetime) or self.as_of.utcoffset() != timedelta(0):
                raise ValueError(ui_text('charts.post_init.snapshot_utc_required'))


class _ChartAnnotationMixin:
    """Marker and reference-line setters (kept outside CandlestickChart to bound its size)."""

    def update(self, *args):
        super().update(*args)
        self.display_changed.emit()

    def set_markers(self, markers, *, trace):
        if self.trace is None or trace != self.trace:
            raise ValueError(ui_text('charts.set_markers.identity_mismatch'))
        markers = tuple(markers)
        if len(markers) > 100000 or any(not isinstance(m, ChartMarker) or m.index >= len(self.bars) for m in markers):
            raise ValueError(ui_text('charts.set_markers.marker_outside_data'))
        self.markers = markers
        indexed = {}
        for m in markers:
            indexed.setdefault(m.index, []).append(m)
        self._marker_index = indexed
        self.update()

    def set_reference_lines(self, lines, *, trace=None):
        lines = tuple(lines)
        if len(lines) > 16 or any(not isinstance(x, ReferenceLine) for x in lines):
            raise ValueError(ui_text('charts.set_reference_lines.invalid_reference'))
        snapshots = [line for line in lines if line.snapshot_index is not None]
        if snapshots:
            if self.trace is None or trace != self.trace:
                raise ValueError(ui_text('charts.set_reference_lines.snapshot_identity_mismatch'))
            if len(snapshots) > 6:
                raise ValueError(ui_text('charts.set_reference_lines.reference_limit'))
            for line in snapshots:
                if line.snapshot_index >= len(self.bars) or self.bars[line.snapshot_index].end != line.as_of:
                    raise ValueError(ui_text('charts.set_reference_lines.snapshot_time_mismatch'))
        self.reference_lines = lines
        self.update()

    def visible_reference_lines(self):
        """End-event snapshots never project backward into a historical viewport."""
        start, end = self.visible_range
        return tuple(line for line in self.reference_lines if line.snapshot_index is None or start <= line.snapshot_index < end)
