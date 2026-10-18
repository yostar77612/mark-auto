"""Native equity and drawdown plots sharing time coordinates."""
import math
from datetime import datetime
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QWidget, QToolTip
from desktop_strings import ui_text
from desktop_theme import COLORS
from desktop_presentation import display_number
from .result_widgets import taipei_time


class EquityPlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values, self.times, self.coordinates, self.drawdowns = [], [], [], []
        self.cursor_x = None
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self.setAccessibleName(ui_text('ui.__init__.text_1'))

    def set_values(self, rows):
        self.values, self.times, self.coordinates = [], [], []
        for row in rows:
            try:
                value = float(row['equity'])
                if not math.isfinite(value):
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            instant = row.get('timestamp', row.get('trade_date'))
            self.values.append(value); self.times.append(instant)
            try:
                self.coordinates.append(datetime.fromisoformat(str(instant).replace('Z', '+00:00')).timestamp())
            except (ValueError, TypeError, OverflowError, OSError):
                self.coordinates.append(float(len(self.values) - 1))
        if self.coordinates != sorted(self.coordinates):
            ordered = sorted(zip(self.coordinates, self.times, self.values), key=lambda item: item[0])
            self.coordinates, self.times, self.values = map(list, zip(*ordered))
        peak = None
        self.drawdowns = []
        for value in self.values:
            peak = value if peak is None else max(peak, value)
            self.drawdowns.append((value - peak) / peak if peak > 0 else None)
        self.cursor_x = None
        self.update()

    def x_positions(self):
        left = self.plot_left()
        right = max(left + 1, self.width() - 24)
        if not self.coordinates:
            return []
        low, high = self.coordinates[0], self.coordinates[-1]
        return [left + (right - left) * (value - low) / (high - low) if high > low else (left + right) / 2
                for value in self.coordinates]

    def plot_left(self):
        labels = self.axis_labels()['value']
        return max(100, max((self.fontMetrics().horizontalAdvance(text) + 12 for text in labels), default=0))

    def value_at(self, x_position):
        """Nearest supplied (time, equity) at a widget-local x pixel."""
        positions = self.x_positions()
        if not positions:
            return None
        index = min(range(len(positions)), key=lambda i: abs(positions[i] - x_position))
        return self.times[index], self.values[index]

    def axis_labels(self):
        if not self.values:
            return {'time': [], 'value': [], 'drawdown': []}
        dates = [taipei_time(value) if 'T' in str(value) else str(value or ui_text('forms.metric.text_2'))
                 for value in (self.times[0], self.times[-1])]
        lo, hi = min(self.values), max(self.values)
        dd = [value for value in self.drawdowns if value is not None]
        return {'time': dates, 'value': [display_number(v, 'cash') for v in (lo, (lo + hi) / 2, hi)],
                'drawdown': [display_number(min(dd), 'max_drawdown_pct'), display_number(0, 'max_drawdown_pct')] if dd else [ui_text('forms.metric.text_1')]}

    def mouseMoveEvent(self, event):
        self.cursor_x = event.position().x()
        value = self.value_at(self.cursor_x)
        if value is not None:
            QToolTip.showText(event.globalPosition().toPoint(), taipei_time(value[0]) + '\n' + display_number(value[1], 'cash'), self)
        self.update()

    def leaveEvent(self, event):
        self.cursor_x = None; QToolTip.hideText(); self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS['background']))
        painter.setPen(QColor(COLORS['text']))
        if not self.values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, ui_text('ui.paintEvent.text_1'))
            return
        labels = self.axis_labels()
        xs = self.x_positions()
        left = self.plot_left()
        top, bottom = 32, self.height() * .57
        dd_top, dd_bottom = self.height() * .69, self.height() - 42
        lo, hi = min(self.values), max(self.values)
        painter.drawText(8, 18, ui_text('results.equity'))
        painter.drawText(8, int(dd_top - 10), ui_text('results.drawdown'))
        for index, text in enumerate(labels['value']):
            y = bottom - index * (bottom - top) / 2
            painter.drawText(QRectF(0, y - 10, left - 6, 20), Qt.AlignmentFlag.AlignRight, text)
            painter.drawLine(QPointF(left, y), QPointF(self.width() - 24, y))
        for y, text in zip((dd_bottom, dd_top), labels['drawdown']):
            painter.drawText(QRectF(0, y - 10, left - 6, 20), Qt.AlignmentFlag.AlignRight, text)
        for index, text in enumerate(labels['time']):
            painter.drawText(QRectF(left, self.height() - 34, max(1, self.width() - left - 24), 30),
                             Qt.AlignmentFlag.AlignLeft if index == 0 else Qt.AlignmentFlag.AlignRight, text)
        painter.drawLine(QPointF(left, dd_bottom), QPointF(self.width() - 24, dd_bottom))
        painter.drawLine(QPointF(left, top), QPointF(left, bottom))
        painter.drawLine(QPointF(left, dd_top), QPointF(left, dd_bottom))
        points = QPolygonF([QPointF(x, bottom - (v - lo) * (bottom - top) / (hi - lo) if hi > lo else (top + bottom) / 2) for x, v in zip(xs, self.values)])
        painter.setPen(QPen(QColor(COLORS['primary']), 2))
        painter.drawPolyline(points)
        for point in points:
            painter.drawEllipse(point, 2, 2)
        valid = [value for value in self.drawdowns if value is not None]
        floor = min(valid) if valid else 0
        painter.setPen(QPen(QColor(COLORS['danger']), 2))
        segment = QPolygonF()
        for x, value in zip(xs, self.drawdowns):
            if value is None:
                painter.drawPolyline(segment); segment = QPolygonF()
            else:
                point = QPointF(x, dd_top + value / floor * (dd_bottom - dd_top) if floor < 0 else dd_top)
                segment.append(point); painter.drawEllipse(point, 2, 2)
        painter.drawPolyline(segment)
        if self.cursor_x is not None:
            painter.setPen(QPen(QColor(COLORS['text']), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(self.cursor_x, top), QPointF(self.cursor_x, dd_bottom))
