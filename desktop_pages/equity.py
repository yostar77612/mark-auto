from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QWidget
from desktop_strings import ui_text

class EquityPlot(QWidget):
    """Small native paint widget; no browser or extra plotting dependency."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(180)
        self.setAccessibleName(ui_text('ui.__init__.text_1'))

    def set_values(self, rows):
        self.values = [float(row['equity']) for row in rows]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#172230'))
        painter.setPen(QColor('#dbe4ef'))
        if not self.values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, ui_text('ui.paintEvent.text_1'))
            return
        lo, hi = min(self.values), max(self.values)
        painter.drawText(8, 18, ui_text('ui.paintEvent.text_2').format(lo, hi))
        points = QPolygonF([QPointF(16 + i * (self.width()-32) / max(1, len(self.values)-1),
                       self.height()-20-(v-lo) * (self.height()-55) / max(1, hi-lo)) for i, v in enumerate(self.values)])
        painter.setPen(QPen(QColor('#2563eb'), 2))
        painter.drawPolyline(points)
