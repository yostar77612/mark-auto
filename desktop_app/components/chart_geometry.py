"""desktop_app components chart_geometry responsibilities."""

from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import Qt


def _prepare_chart_geometry(self, fm, text, start, end, visible, r):
    idx = self.crosshair_index if self.crosshair_index is not None else end - 1
    d = self.bar_details(idx)
    detail = ui_text('charts.paint_event.ohlcv').format(
        d['time'],
        self.price_text(d['open']),
        self.price_text(d['high']),
        self.price_text(d['low']),
        self.price_text(d['close']),
        self.price_text(d['change_text']),
        d['volume'] if d['volume'] is not None else ui_text('charts.paint_event.unknown'),
    ) + (ui_text('charts.paint_event.incomplete') if d['partial'] else '')
    text(12, 65, fm.elidedText(detail, Qt.TextElideMode.ElideRight, self.width() - 24))
    low = min(float(b.low) for b in visible)
    high = max(float(b.high) for b in visible)
    extras = [float(v) for seq in self.overlays.values() for v in seq[start:end] if v is not None]
    references = self.visible_reference_lines()
    extras.extend(float(line.price) for line in references)
    marker_index = self._marker_index
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
