"""desktop_app components charts responsibilities."""

from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
import desktop_app.shell.theme as _theme
import math
from types import MappingProxyType
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
import quantlab.chart_drawings as _drawings
import desktop_app.features.paper.order_lines as _order_lines
from desktop_app.components.chart_annotations import _ChartAnnotationMixin, _number, _validate_chart_bar
from desktop_app.components.chart_footer import _display_time
from desktop_app.components.chart_geometry import _prepare_chart_geometry
from desktop_app.components.chart_interaction import ChartInteraction
from desktop_app.components.chart_paint import _paint_chart_bars, _paint_chart_markers_and_panes, _paint_chart_references
from desktop_app.components.chart_paint_footer import _paint_chart_footer


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
        self.setAccessibleName(ui_text('charts.init.accessible_name'))
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
        self.source_label = ui_text('charts.init.no_data')
        self.status_label = ''
        self.error = ''
        self.timeframe = '1d'
        self.crosshair_index = None
        self._count = 100
        self._start = 0
        self._drag = None
        self._marker_index = {}
        self.interaction = ChartInteraction(self)
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
            raise ValueError(ui_text('charts.set_series.bar_limit'))
        contracts = {b.contract_id for b in bars}
        if len(contracts) > 1 or (trace and contracts and contracts != {trace.contract_id}):
            raise ValueError(ui_text('charts.set_series.contract_mismatch'))
        if len({getattr(b, 'interval', None) for b in bars}) > 1:
            raise ValueError(ui_text('charts.set_series.mixed_timeframes'))
        for b in bars:
            _validate_chart_bar(b)
        self.bars = bars
        self.paper_orders.drag, self.paper_orders.hits = None, ()
        if trace is not None:
            self.set_paper_snapshot(None, mode=None)
        self.trace = trace
        provenance = getattr(series, 'provenance', None)
        self.source_label = source_label or (
            ui_text('charts.set_series.source_title').format(provenance.attribution, provenance.as_of)
            if provenance
            else ui_text('charts.set_series.host_source')
        )
        self.status_label = status_label or (provenance.mode if provenance else ui_text('charts.set_series.status_unknown'))
        self._refresh_series_layers()
        self.crosshair_index = None
        self.error = ''
        self.reset_view()

    def _refresh_series_layers(self):
        self.overlays = MappingProxyType({})
        self.panes = MappingProxyType({})
        self.markers = ()
        self.reference_lines = ()
        self._unavailable_overlays = set()
        self._unavailable_panes = set()
        self.pane_styles = {}
        self._marker_index = {}

    def append_bar(self, bar):
        """Append supplied display data, preserving the viewport and labels."""
        if len(self.bars) >= 100000:
            raise ValueError(ui_text('charts.set_series.bar_limit'))
        self._validate_incremental_bar(bar, self.bars)
        following = self.visible_range[1] == len(self.bars)
        self.bars = (*self.bars, bar)
        if following:
            self._start = max(0, len(self.bars) - self._count)
        self._refresh_series_layers()
        self.paper_orders.drag, self.paper_orders.hits = None, ()
        self.view_changed.emit()
        self.update()

    def replace_last_bar(self, bar):
        """Replace supplied final display data; an empty series has no last bar."""
        if not self.bars:
            raise ValueError(ui_text('charts.set_series.last_bar_required'))
        self._validate_incremental_bar(bar, self.bars if len(self.bars) > 1 else ())
        self.bars = (*self.bars[:-1], bar)
        self._refresh_series_layers()
        self.paper_orders.drag, self.paper_orders.hits = None, ()
        self.update()

    def _validate_incremental_bar(self, bar, retained):
        if (retained and bar.contract_id != retained[0].contract_id) or (self.trace and bar.contract_id != self.trace.contract_id):
            raise ValueError(ui_text('charts.set_series.contract_mismatch'))
        if retained and getattr(bar, 'interval', None) != getattr(retained[0], 'interval', None):
            raise ValueError(ui_text('charts.set_series.mixed_timeframes'))
        _validate_chart_bar(bar)

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
            raise ValueError(ui_text('charts.set_timeframe.unsupported_timeframe'))
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
                    raise ValueError(ui_text('charts.checked.indicator_name_length_required'))
                for v in sequence:
                    if v is not None:
                        _number(v)
                result[str(label)] = sequence
            return MappingProxyType(result)

        overlays = checked(values)
        extra = checked(panes or {})
        if len(overlays) > 16 or len(extra) > 8:
            raise ValueError(ui_text('charts.set_overlays.indicator_limit'))
        styles = dict(pane_styles or {})
        if any(label not in extra or style not in ('line', 'histogram') for label, style in styles.items()):
            raise ValueError(ui_text('charts.set_overlays.invalid_panel_style'))
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
        return ui_text('charts.legend_label.insufficient_data').format(label) if label in unavailable else label

    def set_layer_visible(self, kind, visible):
        if kind not in self.layer_visibility:
            raise ValueError(ui_text('charts.set_layer_visible.unsupported_layer'))
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
            'markers': tuple(self._marker_index.get(index, ())),
        }

    def bar_point(self, index):
        start, end = self.visible_range
        r = self.price_rect
        return QPointF(r.left() + (index - start + 0.5) * r.width() / max(1, end - start), r.center().y()).toPoint()

    def wheelEvent(self, event):
        self.interaction.wheelEvent(event)

    def mousePressEvent(self, event):
        self.interaction.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.interaction.mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.interaction.leaveEvent(event)

    def keyPressEvent(self, event):
        if not self.interaction.keyPressEvent(event):
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
            fm.elidedText(ui_text('charts.paint_event.title').format(self.source_label, self.status_label), Qt.TextElideMode.ElideRight, self.width() - 24),
        )
        text(12, 43, _theme.chart_legend(self))
        if self.paper_orders.notice:
            text(12, 81, self.paper_orders.notice)
        self.last_rendered_bar_count = 0
        if self.error or not self.bars:
            self.setToolTip('')
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error or ui_text('charts.paint_event.no_data'))
            p.end()
            return
        start, end = self.visible_range
        visible = self.bars[start:end]
        r = self.price_rect
        if not visible:
            p.end()
            return
        self.last_rendered_bar_count = len(visible)
        detail, low, high, references, marker_index, y, step, x = _prepare_chart_geometry(self, fm, text, start, end, visible, r)
        volume_bottom = _paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step, _paint_drawings)
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
