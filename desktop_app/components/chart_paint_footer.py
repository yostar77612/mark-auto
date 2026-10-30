"""desktop_app components chart_paint_footer responsibilities."""

from desktop_app.strings.catalog import ui_text
import desktop_app.shell.theme as _theme
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen
from desktop_app.components.chart_footer import _display_time, _footer_items


def _paint_chart_footer(self, p, fm, text, start, end, r, x, y, volume_bottom, marker_index, detail, snapshots, labels):
    first_time = self.bar_details(start)['time']
    last_time = self.bar_details(end - 1)['time']
    footer_detail = ui_text('charts.paint_event.visible_range').format(first_time, last_time)
    if self.trace:
        footer_detail += ui_text('charts.paint_event.trace_hashes').format(self.trace.mode, self.trace.data_hash, self.trace.strategy_hash)
    if self.crosshair_index is not None and start <= self.crosshair_index < end:
        xx = x(self.crosshair_index)
        yy = y(self.bars[self.crosshair_index].close)
        p.setPen(QPen(QColor(_theme.chart_color(self, 'crosshair')), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(xx, r.top()), QPointF(xx, volume_bottom))
        p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
        marker_text = ' / '.join(
            ui_text('charts.paint_event.marker_summary').format(
                ui_text('charts.paint_event.signal') if m.kind == 'signal' else ui_text('charts.paint_event.fill'), m.label, m.reason
            )
            + (
                ui_text('charts.paint_event.fill_details').format(
                    self.price_text(m.price), m.quantity, self.price_text(m.cost) if m.cost is not None else ui_text('charts.paint_event.not_provided')
                )
                if m.kind == 'fill'
                else ui_text('charts.paint_event.target_position').format(
                    m.target_position if m.target_position is not None else ui_text('charts.paint_event.not_provided')
                )
            )
            + (
                ui_text('charts.paint_event.event_time').format(_display_time(m.timestamp))
                if m.timestamp is not None
                else ui_text('charts.paint_event.time_missing')
            )
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
