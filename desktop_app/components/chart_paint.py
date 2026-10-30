"""desktop_app components chart_paint responsibilities."""

from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
import desktop_app.shell.theme as _theme
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QPolygonF
from desktop_app.components.chart_footer import _display_time


def _paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step, paint_drawings):
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
    text(12, volume_top - 5, ui_text('charts.paint_event.volume'))
    self._draw_lines(p, self.overlays, start, end, x, y, r)
    paint_drawings(p, self.drawings, self.bars, r, x, y)
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
        caption = ui_text('charts.paint_event.snapshot_summary').format(_display_time(snapshots[0].as_of))
        policy = ui_text('charts.paint_event.protective_threshold')
        labels = [caption] + [
            (self.price_text(line.price) if _privacy.enabled(self) else ui_text('charts.paint_event.named_price').format(line.label, float(line.price)))
            for line in snapshots
        ]
        if any(ui_text('charts.paint_event.threshold') in line.label for line in snapshots):
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
