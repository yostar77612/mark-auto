"""Bounded native read-only OHLCV chart. Host owns data, aggregation and indicators.

No network, trading, indicator calculation or inferred execution. All indices refer
exactly to the supplied immutable series. Changing series clears index-based layers;
time/price drawings survive aggregation changes.
"""

from desktop_strings import ui_text
import desktop_privacy as _privacy
import desktop_theme as _theme
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
import re
from types import MappingProxyType
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
import quantlab.chart_drawings as _drawings
import desktop_order_lines as _order_lines


def _paint_drawings(painter, drawings, bars, rect, x, y):
    """Project durable time/price anchors only at paint time; clip all geometry."""
    painter.save()
    painter.setClipRect(rect)
    painter.setPen(QPen(QColor('#64d9df'), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for drawing in drawings:
        projected = [_drawings.project_anchor(a, bars) for a in _drawings.anchors(drawing)]
        if any(point is None for point in projected):
            continue
        points = [QPointF(x(position), y(price)) for position, price in projected]
        if any(not math.isfinite(point.y()) for point in points):
            continue
        first = points[0]
        if isinstance(drawing, _drawings.HorizontalLine):
            painter.drawLine(QPointF(rect.left(), first.y()), QPointF(rect.right(), first.y()))
        elif isinstance(drawing, _drawings.Box):
            painter.drawRect(QRectF(first, points[1]).normalized())
        else:
            last = points[1]
            if isinstance(drawing, _drawings.Ray):
                dx, dy = last.x() - first.x(), last.y() - first.y()
                if dx or dy:
                    # Extend beyond the viewport in its directed screen-space vector.
                    factor = 1 + (rect.width() + rect.height() + abs(first.x() - rect.left()) + abs(first.y() - rect.top())) / max(abs(dx), abs(dy))
                    last = QPointF(first.x() + dx * factor, first.y() + dy * factor)
            painter.drawLine(first, last)
    painter.restore()


def _display_time(value, date_only=''):
    """Presentation only; no timezone inference for unverified naive values."""
    if value is None:
        return date_only or ui_text('charts._display_time.text_1')
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return ui_text('charts._display_time.text_2')
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return ui_text('charts._display_time.text_3')
    return ui_text('charts._display_time.text_4').format(value.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y/%m/%d %H:%M'))


def _footer_items(width, metrics, first_time, last_time, trace=None):
    """Non-overlapping single-row paint slots; full labels stay in the tooltip."""
    width = max(0, int(width))
    gap = 8
    first_width = metrics.horizontalAdvance(first_time)
    last_width = metrics.horizontalAdvance(last_time)
    trace_text = ui_text('charts._footer_items.text_1').format(trace.mode, trace.data_hash[:8], trace.strategy_hash[:8]) if trace else ''
    trace_width = metrics.horizontalAdvance(trace_text)
    if first_width + last_width + trace_width + gap * (2 if trace else 1) <= width:
        items = [(0, first_width, first_time), (width - last_width, last_width, last_time)]
        if trace:
            items.insert(1, (first_width + gap, trace_width, trace_text))
        return tuple(items)
    # At narrow widths retain the verified mode and elide only display labels.
    trace_text = trace.mode if trace else ''
    trace_width = min(metrics.horizontalAdvance(trace_text), width // 3)
    gaps = min(gap, width // 4) * (2 if trace else 1)
    side_width = max(0, (width - trace_width - gaps) // 2)
    items = [
        (0, side_width, metrics.elidedText(first_time, Qt.TextElideMode.ElideRight, side_width)),
        (width - side_width, side_width, metrics.elidedText(last_time, Qt.TextElideMode.ElideRight, side_width)),
    ]
    if trace:
        items.insert(1, ((width - trace_width) // 2, trace_width, metrics.elidedText(trace_text, Qt.TextElideMode.ElideRight, trace_width)))
    return tuple(items)


@dataclass(frozen=True)
class ChartTrace:
    contract_id: str
    data_hash: str
    strategy_hash: str
    mode: str

    def __post_init__(self):
        if not self.contract_id or self.mode not in (ui_text('charts.__post_init__.text_1'), ui_text('charts.__post_init__.text_2')):
            raise ValueError(ui_text('charts.__post_init__.text_3'))
        if any(not re.fullmatch('[0-9a-f]{64}', x) for x in (self.data_hash, self.strategy_hash)):
            raise ValueError(ui_text('charts.__post_init__.text_4'))


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
        raise ValueError(ui_text('charts._number.text_1'))
    return float(value)


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
            raise ValueError(ui_text('charts.__post_init__.text_5'))
        if not self.label:
            raise ValueError(ui_text('charts.__post_init__.text_6'))
        if self.target_position is not None and type(self.target_position) is not int:
            raise ValueError(ui_text('charts.__post_init__.text_7'))
        if self.kind == 'signal' and self.price is not None:
            raise ValueError(ui_text('charts.__post_init__.text_8'))
        if self.kind == 'fill' and (self.price is None or type(self.quantity) is not int or self.quantity <= 0):
            raise ValueError(ui_text('charts.__post_init__.text_9'))
        for value in (self.price, self.cost):
            if value is not None:
                _number(value)
        if self.cost is not None and self.cost < 0:
            raise ValueError(ui_text('charts.__post_init__.text_10'))


@dataclass(frozen=True)
class ReferenceLine:
    label: str
    price: Decimal
    snapshot_index: int | None = None
    as_of: datetime | None = None

    def __post_init__(self):
        if not self.label:
            raise ValueError(ui_text('charts.__post_init__.text_11'))
        _number(self.price)
        if (self.snapshot_index is None) != (self.as_of is None):
            raise ValueError(ui_text('charts.__post_init__.text_12'))
        if self.snapshot_index is not None:
            if type(self.snapshot_index) is not int or self.snapshot_index < 0:
                raise ValueError(ui_text('charts.__post_init__.text_13'))
            if not isinstance(self.as_of, datetime) or self.as_of.utcoffset() != timedelta(0):
                raise ValueError(ui_text('charts.__post_init__.text_14'))


class _ChartAnnotationMixin:
    """Marker and reference-line setters (kept outside CandlestickChart to bound its size)."""

    def update(self, *args):
        super().update(*args)
        self.display_changed.emit()

    def set_markers(self, markers, *, trace):
        if self.trace is None or trace != self.trace:
            raise ValueError(ui_text('charts.set_markers.text_1'))
        markers = tuple(markers)
        if len(markers) > 100000 or any(not isinstance(m, ChartMarker) or m.index >= len(self.bars) for m in markers):
            raise ValueError(ui_text('charts.set_markers.text_2'))
        self.markers = markers
        indexed = {}
        for m in markers:
            indexed.setdefault(m.index, []).append(m)
        self._marker_index = indexed
        self.update()

    def set_reference_lines(self, lines, *, trace=None):
        lines = tuple(lines)
        if len(lines) > 16 or any(not isinstance(x, ReferenceLine) for x in lines):
            raise ValueError(ui_text('charts.set_reference_lines.text_1'))
        snapshots = [line for line in lines if line.snapshot_index is not None]
        if snapshots:
            if self.trace is None or trace != self.trace:
                raise ValueError(ui_text('charts.set_reference_lines.text_2'))
            if len(snapshots) > 6:
                raise ValueError(ui_text('charts.set_reference_lines.text_3'))
            for line in snapshots:
                if line.snapshot_index >= len(self.bars) or self.bars[line.snapshot_index].end != line.as_of:
                    raise ValueError(ui_text('charts.set_reference_lines.text_4'))
        self.reference_lines = lines
        self.update()

    def visible_reference_lines(self):
        """End-event snapshots never project backward into a historical viewport."""
        start, end = self.visible_range
        return tuple(line for line in self.reference_lines if line.snapshot_index is None or start <= line.snapshot_index < end)


class CandlestickChart(_ChartAnnotationMixin, _order_lines.PaperOrderChartMixin, QWidget):
    """Wheel zoom / left-drag pan / hover OHLC; arrows pan, +/- zoom, Home reset.

    set_series accepts MarketSeries or sequence of MarketBar. Optional ChartTrace
    binds signal/fill layers to host-verified contract/data/strategy. The host must
    map event timestamps to containing bars (not nearest guessed market prices).
    set_timeframe only emits a host request; it never relabels or resamples bars.
    """

    crosshair_changed = Signal(object)
    timeframe_changed = Signal(str)
    display_changed = Signal()
    view_changed = Signal()
    timeframes = ('1m', '3m', '5m', '15m', '30m', '60m', '1d', '1w')
    MAX_VISIBLE = 600

    @property
    def UP(self):
        return QColor(_theme.up_down_colors(_theme.appearance(self)[1])[0])

    @property
    def DOWN(self):
        return QColor(_theme.up_down_colors(_theme.appearance(self)[1])[1])

    @property
    def TEXT(self):
        return QColor(_theme.chart_color(self, 'text'))

    @property
    def COLORS(self):
        return _theme.chart_color(self, 'overlay')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360, 280)
        self.setAccessibleName(ui_text('charts.__init__.text_1'))
        self.bars = ()
        self.trace = None
        self.overlays = MappingProxyType({})
        self.panes = MappingProxyType({})
        self._unavailable_overlays = set()
        self._unavailable_panes = set()
        self.pane_styles = {}
        self.markers = ()
        self.reference_lines = ()
        self.drawings = ()
        self.layer_visibility = {'signal': True, 'fill': True}
        self.source_label = ui_text('charts.__init__.text_2')
        self.status_label = ''
        self.error = ''
        self.timeframe = '1d'
        self.crosshair_index = None
        self._count = 100
        self._start = 0
        self._drag = None
        self.last_rendered_bar_count = 0
        self.paper_orders = _order_lines.PaperOrderLines()

    @property
    def price_rect(self):
        lower = 0.55 if self.panes else 0.71
        return QRectF(12, 86, max(40, self.width() - 102), max(50, self.height() * lower - 86))

    @property
    def visible_range(self):
        return self._start, min(len(self.bars), self._start + self._count)

    def set_series(self, series, *, trace=None, source_label='', status_label=''):
        bars = tuple(getattr(series, 'bars', series))
        if len(bars) > 100000:
            raise ValueError(ui_text('charts.set_series.text_1'))
        contracts = {b.contract_id for b in bars}
        if len(contracts) > 1 or (trace and contracts and contracts != {trace.contract_id}):
            raise ValueError(ui_text('charts.set_series.text_2'))
        if len({getattr(b, 'interval', None) for b in bars}) > 1:
            raise ValueError(ui_text('charts.set_series.text_3'))
        for b in bars:
            o, h, l, c = map(_number, (b.open, b.high, b.low, b.close))
            if not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError(ui_text('charts.set_series.text_4'))
            if b.volume is not None and (type(b.volume) is not int or b.volume < 0):
                raise ValueError(ui_text('charts.set_series.text_5'))
        self.bars = bars
        self.paper_orders.drag, self.paper_orders.hits = None, ()
        if trace is not None:
            self.set_paper_snapshot(None, mode=None)
        self.trace = trace
        provenance = getattr(series, 'provenance', None)
        self.source_label = source_label or (
            ui_text('charts.set_series.text_6').format(provenance.attribution, provenance.as_of) if provenance else ui_text('charts.set_series.text_7')
        )
        self.status_label = status_label or (provenance.mode if provenance else ui_text('charts.set_series.text_8'))
        self.overlays = MappingProxyType({})
        self.panes = MappingProxyType({})
        self.markers = ()
        self.reference_lines = ()
        self._unavailable_overlays = set()
        self._unavailable_panes = set()
        self.pane_styles = {}
        self._marker_index = {}
        self.crosshair_index = None
        self.error = ''
        self.reset_view()

    def reset_view(self):
        self._count = min(self.MAX_VISIBLE, 100)
        self._start = max(0, len(self.bars) - self._count)
        self.view_changed.emit()
        self.update()

    def set_error(self, message):
        self.error = str(message)
        self.update()

    def set_timeframe(self, timeframe):
        if timeframe not in self.timeframes:
            raise ValueError(ui_text('charts.set_timeframe.text_1'))
        if timeframe != self.timeframe:
            self.timeframe = timeframe
            self.timeframe_changed.emit(timeframe)

    def set_drawings(self, drawings):
        """Set at most 200 display-only objects; never emit a market request.

        Hosts select the instrument's DrawingStore/History explicitly. Unlike
        index-based result layers, these immutable anchors survive set_series.
        """
        self.drawings = _drawings.checked(drawings)
        self.update()

    def set_overlays(self, values, *, panes=None, pane_styles=None):
        def checked(mapping):
            result = {}
            for label, sequence in mapping.items():
                sequence = tuple(sequence)
                if not label or len(sequence) != len(self.bars):
                    raise ValueError(ui_text('charts.checked.text_1'))
                for v in sequence:
                    if v is not None:
                        _number(v)
                result[str(label)] = sequence
            return MappingProxyType(result)

        overlays = checked(values)
        extra = checked(panes or {})
        if len(overlays) > 16 or len(extra) > 8:
            raise ValueError(ui_text('charts.set_overlays.text_1'))
        styles = dict(pane_styles or {})
        if any(label not in extra or style not in ('line', 'histogram') for label, style in styles.items()):
            raise ValueError(ui_text('charts.set_overlays.text_2'))
        self.overlays = overlays
        self.panes = extra
        self.pane_styles = styles
        self._unavailable_overlays = {label for label, seq in overlays.items() if all(v is None for v in seq)}
        self._unavailable_panes = {label for label, seq in extra.items() if all(v is None for v in seq)}
        self.update()

    def price_text(self, value):
        return _privacy.display(self, str(value), 'price')

    def _legend_label(self, label, *, pane=False):
        unavailable = self._unavailable_panes if pane else self._unavailable_overlays
        return ui_text('charts._legend_label.text_1').format(label) if label in unavailable else label

    def set_layer_visible(self, kind, visible):
        if kind not in self.layer_visibility:
            raise ValueError(ui_text('charts.set_layer_visible.text_1'))
        self.layer_visibility[kind] = bool(visible)
        self.update()

    def bar_details(self, index):
        b = self.bars[index]
        timestamp = getattr(b, 'timestamp', None)
        change = b.close - b.open
        return {
            'index': index,
            'time': _display_time(timestamp, b.trade_date),
            'trade_date': b.trade_date,
            'open': b.open,
            'high': b.high,
            'low': b.low,
            'close': b.close,
            'volume': b.volume,
            'change_text': f'{change:+g}',
            'partial': getattr(b, 'partial', False),
            'markers': tuple(getattr(self, '_marker_index', {}).get(index, ())),
        }

    def bar_point(self, index):
        start, end = self.visible_range
        r = self.price_rect
        return QPointF(r.left() + (index - start + 0.5) * r.width() / max(1, end - start), r.center().y()).toPoint()

    def _pan(self, bars):
        self._start = max(0, min(max(0, len(self.bars) - self._count), self._start + bars))
        self.view_changed.emit()
        self.update()

    def _zoom(self, factor, anchor=0.5):
        old = self._count
        new = max(10, min(self.MAX_VISIBLE, len(self.bars) or 10, round(old * factor)))
        self._start = max(0, min(max(0, len(self.bars) - new), round(self._start + (old - new) * anchor)))
        self._count = new
        self.view_changed.emit()
        self.update()

    def wheelEvent(self, event):
        r = self.price_rect
        anchor = max(0, min(1, (event.position().x() - r.left()) / r.width()))
        self._zoom(0.8 if event.angleDelta().y() > 0 else 1.25, anchor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            if self.paper_orders.press(event.position(), self.price_rect):
                event.accept()
                return
            self._drag = (event.position().x(), self._start)
            event.accept()

    def mouseMoveEvent(self, event):
        r = self.price_rect
        start, end = self.visible_range
        if self._drag is not None:
            x, origin = self._drag
            self._start = max(0, min(max(0, len(self.bars) - self._count), origin - round((event.position().x() - x) / r.width() * max(1, end - start))))
            self.view_changed.emit()
        if self.bars and r.contains(event.position()):
            self.crosshair_index = min(end - 1, max(start, start + int((event.position().x() - r.left()) / r.width() * max(1, end - start))))
            self.crosshair_changed.emit(self.bar_details(self.crosshair_index))
        else:
            self.crosshair_index = None
        self.update()

    def leaveEvent(self, event):
        self.crosshair_index = None
        self.crosshair_changed.emit(None)
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.paper_orders.drag = None
            self._drag = None
        elif key == Qt.Key.Key_Left:
            self._pan(-max(1, self._count // 10))
        elif key == Qt.Key.Key_Right:
            self._pan(max(1, self._count // 10))
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom(0.8)
        elif key == Qt.Key.Key_Minus:
            self._zoom(1.25)
        elif key == Qt.Key.Key_Home:
            self.reset_view()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(_theme.chart_color(self, 'background')))
        p.setPen(self.TEXT)

        def text(x, y, s):
            p.drawText(QPointF(x, y), str(s))

        fm = p.fontMetrics()
        text(
            12,
            22,
            fm.elidedText(ui_text('charts.paintEvent.text_1').format(self.source_label, self.status_label), Qt.TextElideMode.ElideRight, self.width() - 24),
        )
        text(12, 43, _theme.chart_legend(self))
        if self.paper_orders.notice:
            text(12, 81, self.paper_orders.notice)
        self.last_rendered_bar_count = 0
        if self.error or not self.bars:
            self.setToolTip('')
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error or ui_text('charts.paintEvent.text_3'))
            p.end()
            return
        start, end = self.visible_range
        visible = self.bars[start:end]
        r = self.price_rect
        if not visible:
            p.end()
            return
        self.last_rendered_bar_count = len(visible)
        detail, low, high, references, marker_index, y, step, x = _prepare_chart_geometry(self, p, fm, text, start, end, visible, r)
        volume_bottom = _paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step)
        snapshots, labels = _paint_chart_references(self, p, fm, text, references, r, x, y, step)
        _paint_chart_markers_and_panes(self, p, text, start, end, marker_index, r, x, y, step, volume_bottom)
        _paint_chart_footer(self, p, fm, text, start, end, r, x, y, volume_bottom, marker_index, detail, snapshots, labels)
        p.end()

    def _draw_lines(self, p, series, start, end, x, y, clip):
        p.save()
        p.setClipRect(clip)
        for j, (label, values) in enumerate(series.items()):
            p.setPen(QPen(QColor(self.COLORS[j % len(self.COLORS)]), 1.4))
            previous = None
            for i in range(start, end):
                value = values[i]
                if value is None:
                    previous = None
                    continue
                point = QPointF(x(i), y(value))
                if previous is not None:
                    p.drawLine(previous, point)
                previous = point
        p.restore()


def _prepare_chart_geometry(self, p, fm, text, start, end, visible, r):
    idx = self.crosshair_index if self.crosshair_index is not None else end - 1
    d = self.bar_details(idx)
    detail = ui_text('charts.paintEvent.text_5').format(
        d['time'],
        self.price_text(d['open']),
        self.price_text(d['high']),
        self.price_text(d['low']),
        self.price_text(d['close']),
        self.price_text(d['change_text']),
        d['volume'] if d['volume'] is not None else ui_text('charts.paintEvent.text_4'),
    ) + (ui_text('charts.paintEvent.text_6') if d['partial'] else '')
    text(12, 65, fm.elidedText(detail, Qt.TextElideMode.ElideRight, self.width() - 24))
    low = min(float(b.low) for b in visible)
    high = max(float(b.high) for b in visible)
    extras = [float(v) for seq in self.overlays.values() for v in seq[start:end] if v is not None]
    references = self.visible_reference_lines()
    extras.extend(float(line.price) for line in references)
    marker_index = getattr(self, '_marker_index', {})
    extras.extend(float(m.price) for i in range(start, end) for m in marker_index.get(i, ()) if m.kind == 'fill' and self.layer_visibility['fill'])
    if extras:
        low = min(low, min(extras))
        high = max(high, max(extras))
    pad = max((high - low) * 0.06, 0.5)
    low -= pad
    high += pad
    low, high = self.paper_orders.price_bounds(self, visible, start, end, references, marker_index, low, high)
    y = lambda value: r.bottom() - (float(value) - float(low)) / float(high - low) * r.height()
    step = r.width() / len(visible)
    x = lambda i: r.left() + (i - start + 0.5) * step
    return detail, low, high, references, marker_index, y, step, x


def _paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step):
    p.setPen(QPen(QColor(_theme.chart_color(self, 'grid')), 1))
    for tick in range(5):
        value = low + (high - low) * tick / 4
        yy = y(value)
        p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
        p.setPen(self.TEXT)
        text(r.right() + 6, yy + 4, self.price_text(f'{value:,.2f}'))
        p.setPen(QColor(_theme.chart_color(self, 'grid')))
    volume_top = r.bottom() + 30
    volume_bottom = self.height() * (0.76 if self.panes else 0.91)
    volume_max = max((b.volume or 0 for b in visible), default=0) or 1
    for i, b in enumerate(visible, start):
        color = self.UP if b.close > b.open else self.DOWN if b.close < b.open else QColor(_theme.chart_color(self, 'flat'))
        p.setPen(QPen(color, 1))
        p.setBrush(color)
        p.drawLine(QPointF(x(i), y(b.high)), QPointF(x(i), y(b.low)))
        p.drawRect(QRectF(x(i) - max(0.7, step * 0.3), min(y(b.open), y(b.close)), max(1, step * 0.6), max(1, abs(y(b.open) - y(b.close)))))
        if b.volume is not None:
            vh = (volume_bottom - volume_top) * b.volume / volume_max
            p.fillRect(QRectF(x(i) - step * 0.3, volume_bottom - vh, max(1, step * 0.6), vh), color)
    p.setPen(self.TEXT)
    text(12, volume_top - 5, ui_text('charts.paintEvent.text_7'))
    self._draw_lines(p, self.overlays, start, end, x, y, r)
    _paint_drawings(p, self.drawings, self.bars, r, x, y)
    self.paper_orders.paint(p, r, visible[0].contract_id, y, low, high)
    return volume_bottom


def _paint_chart_references(self, p, fm, text, references, r, x, y, step):
    legend_x = r.left()
    for j, label in enumerate(self.overlays):
        p.setPen(QColor(_theme.chart_color(self, 'muted')) if label in self._unavailable_overlays else QColor(self.COLORS[j % len(self.COLORS)]))
        label = fm.elidedText(self._legend_label(label), Qt.TextElideMode.ElideRight, 240)
        if legend_x + fm.horizontalAdvance(label) > r.right():
            break
        text(legend_x, r.top() - 5, label)
        legend_x += fm.horizontalAdvance(label) + 14
    for line in references:
        p.setPen(QPen(QColor(_theme.chart_color(self, 'reference')), 1, Qt.PenStyle.DashLine))
        yy = y(line.price)
        if line.snapshot_index is None:
            p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
            text(r.left() + 5, yy - 4, f'{line.label} {self.price_text(line.price)}')
        else:
            # A short tick at the known event boundary, never a full-history line.
            xx = x(line.snapshot_index) + step / 2
            p.drawLine(QPointF(xx - 5, yy), QPointF(xx + 5, yy))
    snapshots = [line for line in references if line.snapshot_index is not None]
    labels = []
    if snapshots:
        caption = ui_text('charts.paintEvent.text_8').format(_display_time(snapshots[0].as_of))
        policy = ui_text('charts.paintEvent.text_9')
        labels = [caption] + [
            (self.price_text(line.price) if _privacy.enabled(self) else ui_text('charts.paintEvent.text_10').format(line.label, float(line.price)))
            for line in snapshots
        ]
        if any(ui_text('charts.paintEvent.text_11') in line.label for line in snapshots):
            labels.append(policy)
        width = min(r.width(), max(fm.horizontalAdvance(label) for label in labels) + 12)
        panel = QRectF(r.left() + 4, r.top() + 4, width, (fm.height() + 2) * len(labels) + 8)
        panel_color = QColor(_theme.chart_color(self, 'background'))
        panel_color.setAlpha(225)
        p.fillRect(panel, panel_color)
        p.setPen(QColor(_theme.chart_color(self, 'reference')))
        for index, label in enumerate(labels):
            text(
                panel.left() + 5,
                panel.top() + fm.ascent() + 4 + index * (fm.height() + 2),
                fm.elidedText(label, Qt.TextElideMode.ElideRight, int(width - 10)),
            )
    return snapshots, labels


def _paint_chart_markers_and_panes(self, p, text, start, end, marker_index, r, x, y, step, volume_bottom):
    for i in range(start, end):
        for marker in marker_index.get(i, ()):
            if not self.layer_visibility[marker.kind]:
                continue
            xx = x(i)
            if marker.kind == 'signal':
                yy = r.top() + 13
                points = [QPointF(xx, yy - 5), QPointF(xx + 5, yy), QPointF(xx, yy + 5), QPointF(xx - 5, yy)]
                p.setPen(QColor(_theme.chart_color(self, 'signal')))
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                yy = y(marker.price)
                points = [QPointF(xx, yy - 6), QPointF(xx + 5, yy + 4), QPointF(xx - 5, yy + 4)]
                p.setPen(QColor(_theme.chart_color(self, 'fill')))
                p.setBrush(QColor(_theme.chart_color(self, 'fill')))
            p.drawPolygon(QPolygonF(points))
    if self.panes:
        pane_top = volume_bottom + 23
        height = max(10, (self.height() * 0.93 - pane_top) / len(self.panes))
        for j, (label, seq) in enumerate(self.panes.items()):
            area = QRectF(r.left(), pane_top + j * height, r.width(), max(8, height - 15))
            values = [float(v) for v in seq[start:end] if v is not None]
            lo = min(values) if values else 0
            hi = max(values) if values else 1
            histogram = self.pane_styles.get(label) == 'histogram'
            if histogram:
                lo = min(0, lo)
                hi = max(0, hi)
            if hi == lo:
                hi += 1
                lo -= 1
            py = lambda v, area=area, lo=lo, hi=hi: area.bottom() - (float(v) - lo) / (hi - lo) * area.height()
            if histogram:
                p.save()
                p.setClipRect(area)
                for i in range(start, end):
                    if seq[i] is None:
                        continue
                    value = float(seq[i])
                    baseline = py(0)
                    yy = py(value)
                    p.fillRect(
                        QRectF(x(i) - step * 0.3, min(baseline, yy), max(1, step * 0.6), max(1, abs(baseline - yy))), self.UP if value >= 0 else self.DOWN
                    )
                p.restore()
            else:
                self._draw_lines(p, {label: seq}, start, end, x, py, area)
            p.setPen(QColor(_theme.chart_color(self, 'muted')) if label in self._unavailable_panes else self.TEXT)
            text(area.left() + 3, area.top() + 10, self._legend_label(label, pane=True))


def _paint_chart_footer(self, p, fm, text, start, end, r, x, y, volume_bottom, marker_index, detail, snapshots, labels):
    first_time = self.bar_details(start)['time']
    last_time = self.bar_details(end - 1)['time']
    footer_detail = ui_text('charts.paintEvent.text_12').format(first_time, last_time)
    if self.trace:
        footer_detail += ui_text('charts.paintEvent.text_13').format(self.trace.mode, self.trace.data_hash, self.trace.strategy_hash)
    if self.crosshair_index is not None and start <= self.crosshair_index < end:
        xx = x(self.crosshair_index)
        yy = y(self.bars[self.crosshair_index].close)
        p.setPen(QPen(QColor(_theme.chart_color(self, 'crosshair')), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(xx, r.top()), QPointF(xx, volume_bottom))
        p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
        marker_text = ' / '.join(
            ui_text('charts.paintEvent.text_16').format(
                ui_text('charts.paintEvent.text_14') if m.kind == 'signal' else ui_text('charts.paintEvent.text_15'), m.label, m.reason
            )
            + (
                ui_text('charts.paintEvent.text_18').format(
                    self.price_text(m.price), m.quantity, self.price_text(m.cost) if m.cost is not None else ui_text('charts.paintEvent.text_17')
                )
                if m.kind == 'fill'
                else ui_text('charts.paintEvent.text_20').format(m.target_position if m.target_position is not None else ui_text('charts.paintEvent.text_19'))
            )
            + (ui_text('charts.paintEvent.text_21').format(_display_time(m.timestamp)) if m.timestamp is not None else ui_text('charts.paintEvent.text_22'))
            for m in marker_index.get(self.crosshair_index, ())
        )
        snapshot_text = '\n'.join(labels) if snapshots else ''
        self.setToolTip(detail + ('\n' + marker_text if marker_text else '') + ('\n' + snapshot_text if snapshot_text else '') + '\n' + footer_detail)
    else:
        self.setToolTip(footer_detail)
    p.setPen(self.TEXT)
    for offset, width, label in _footer_items(r.width(), fm, first_time, last_time, self.trace):
        p.save()
        p.setClipRect(QRectF(r.left() + offset, self.height() - 12 - fm.ascent(), width, fm.height()))
        text(r.left() + offset, self.height() - 12, label)
        p.restore()
