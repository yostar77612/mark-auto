"""Saved in-sample projections and a lazy, read-only comparison canvas."""

from bisect import bisect_left
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation
from math import ceil, isfinite

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_app.components.chart_footer import _footer_items
import desktop_app.components.privacy as privacy
from desktop_app.strings.catalog import ui_text
from desktop_app.features.compare.compare_table import safe_text


CAP = 8
PAINT_LIMIT = 2048
COLORS = ('#0072b2', '#d55e00', '#009e73', '#cc79a7', '#e69f00', '#56b4e9', '#777777', '#a6761d')
PATTERNS = ((), (8, 3), (2, 3), (8, 3, 2, 3), (8, 3, 2, 3, 2, 3), (12, 3), (4, 3), (12, 3, 4, 3))
PATTERN_LABELS = ('____', '-- --', '. . .', '-- .', '-- . .', '---- ----', '- - -', '---- -')


def series_pen(index):
    pen = QPen(QColor(COLORS[index]), 2)
    if PATTERNS[index]:
        pen.setDashPattern(PATTERNS[index])
    return pen


def project_equity(rows):
    """Allowlist dates and equity only; daily closing observations, no filling."""
    values, dropped = {}, 0
    if not isinstance(rows, (list, tuple)):
        return (), 0
    for row in rows:
        if not isinstance(row, dict):
            dropped += 1
            continue
        # Explicit partition markers fail closed; nested auxiliary fields are never read.
        if any(row.get(key) not in (None, '', 'is', 'in_sample', 'train') for key in ('partition', 'split', 'sample')):
            continue
        try:
            day = date.fromisoformat(str(row.get('trade_date', row.get('timestamp', '')))[:10]).toordinal()
            value = Decimal(str(row['equity']))
            if not value.is_finite() or not isfinite(float(value)):
                dropped += 1
                continue
            values[day] = value
        except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
            dropped += 1
    return tuple(sorted(values.items())), dropped


def drawdown(points):
    """Peak-to-trough fraction of the same saved equity; nonpositive peaks give zero."""
    peak = None
    result = []
    for day, value in points:
        peak = value if peak is None else max(peak, value)
        result.append((day, (peak - value) / peak if peak > 0 else Decimal(0)))
    return tuple(result)


def paint_points(points, limit=PAINT_LIMIT):
    """Bound painting and retain gap identities so reduction cannot bridge gaps."""
    if not points:
        return ()
    stride = max(1, ceil(len(points) / max(1, limit - 1)))
    result, segment, previous = [], 0, None
    for index, (day, value) in enumerate(points):
        if previous is not None and day - previous > 1:
            segment += 1
        previous = day
        if index % stride == 0 or index == len(points) - 1:
            result.append((day, float(value), segment))
    return tuple(result)


def normalised_series(points):
    """Reject unpaintable ratios as well as invalid saved numeric observations."""
    if not points or points[0][1] <= 0:
        return (), (), 0
    try:
        equity = tuple((day, value / points[0][1]) for day, value in points)
        dd = drawdown(points)
        valid = tuple((e, d) for e, d in zip(equity, dd) if isfinite(float(e[1])) and isfinite(float(d[1])))
    except (DecimalException, OverflowError, ValueError):
        return (), (), len(points)
    return tuple(e for e, _ in valid), tuple(d for _, d in valid), len(points) - len(valid)


class OverlayCanvas(QWidget):
    readout_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.series = ()
        self.days = ()
        self.cursor = 0
        self.x_range = (0, 0)
        self.ticks = ()
        self.setMinimumHeight(300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(ui_text('compare.overlay.title'))

    def set_series(self, records):
        series = []
        all_days = set()
        self.dropped = 0
        for label, points in records:
            equity, dd, dropped = normalised_series(points)
            self.dropped += dropped
            if not equity:
                continue
            series.append((label, dict(equity), dict(dd), paint_points(equity), paint_points(dd)))
            all_days.update(day for day, _ in equity)
        self.series = tuple(series)
        self.days = tuple(sorted(all_days))
        self.cursor = 0
        self.x_range = (self.days[0], self.days[-1]) if self.days else (0, 0)
        self.ticks = tuple(dict.fromkeys((self.days[0], self.days[len(self.days) // 2], self.days[-1]))) if self.days else ()
        self.bounds = tuple(
            (min((p[1] for s in series for p in s[field]), default=0), max((p[1] for s in series for p in s[field]), default=1)) for field in (3, 4)
        )
        self.update()

    def axes(self):
        """Both panels use precisely the same date range and ticks."""
        return ((self.x_range, self.ticks), (self.x_range, self.ticks))

    def readout(self):
        if not self.days:
            return ui_text('compare.overlay.empty')
        day = self.days[self.cursor]
        parts = [date.fromordinal(day).isoformat()]
        for label, equity, dd, _, _ in self.series:
            if day in equity:
                parts.append(ui_text('compare.overlay.value').format(label, format(equity[day], '.4f'), format(dd[day], '.4f')))
        return ' / '.join(parts)

    def publish_readout(self):
        text = privacy.mask_money('') if privacy.enabled(self) else self.readout()
        self.setAccessibleDescription(text)
        self.readout_changed.emit(text)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.days:
            self.cursor = min(len(self.days) - 1, max(0, self.cursor + (1 if event.key() == Qt.Key.Key_Right else -1)))
            self.publish_readout()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if self.days:
            fraction = min(1, max(0, (event.position().x() - 60) / max(1, self.width() - 80)))
            day = self.x_range[0] + fraction * (self.x_range[1] - self.x_range[0])
            self.cursor = min(len(self.days) - 1, bisect_left(self.days, day))
            self.publish_readout()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if privacy.enabled(self) or not self.series:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, privacy.mask_money('') if privacy.enabled(self) else ui_text('compare.overlay.empty'))
            return
        for index, _ in enumerate(self.series):
            x = 60 + (index % 4) * max(1, self.width() - 80) / 4
            y = 10 + (index // 4) * 20
            painter.setPen(series_pen(index))
            painter.drawLine(QPointF(x, y), QPointF(x + 45, y))
            painter.drawText(QPointF(x + 50, y + 5), ui_text('compare.overlay.legend').format(index + 1, '', ''))
        height = (self.height() - 85) / 2
        for panel, title in enumerate((ui_text('compare.overlay.equity'), ui_text('compare.overlay.drawdown'))):
            rect = QRectF(60, 60 + panel * height, max(1, self.width() - 80), height - 35)
            painter.setPen(self.palette().text().color())
            painter.drawText(QPointF(rect.left(), rect.top() - 5), title)
            painter.drawRect(rect)
            low, high = self.bounds[panel]
            span = high - low or 1
            painter.drawText(QPointF(0, rect.top() + 12), format(high, '.3f'))
            painter.drawText(QPointF(0, rect.bottom()), format(low, '.3f'))
            for day in self.ticks:
                x = rect.left() + (day - self.x_range[0]) / max(1, self.x_range[1] - self.x_range[0]) * rect.width()
                painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() + 4))
            painter.save()
            painter.setClipRect(rect.adjusted(-2, -2, 2, 2))
            for index, series in enumerate(self.series):
                painter.setPen(series_pen(index))
                previous = None
                for day, value, segment in series[3 + panel]:
                    point = QPointF(
                        rect.left() + (day - self.x_range[0]) / max(1, self.x_range[1] - self.x_range[0]) * rect.width(),
                        rect.bottom() - (value - low) / span * rect.height(),
                    )
                    painter.drawPoint(point)
                    if previous is not None and previous[1] == segment:
                        painter.drawLine(previous[0], point)
                    previous = point, segment
            painter.restore()
        painter.setPen(self.palette().text().color())
        for offset, width, label in _footer_items(self.width() - 80, painter.fontMetrics(), *(date.fromordinal(day).isoformat() for day in self.x_range)):
            painter.drawText(QRectF(60 + offset, self.height() - 25, width, 22), Qt.AlignmentFlag.AlignLeft, label)


class EquityOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel(self)
        self.legend = QLabel(self)
        self.legend.setWordWrap(True)
        self.legend.setTextFormat(Qt.TextFormat.PlainText)
        self.canvas = OverlayCanvas(self)
        self.detail = QLabel(self)
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        for widget in (self.summary, self.legend, self.canvas, self.detail):
            layout.addWidget(widget)
        self.canvas.readout_changed.connect(self.detail.setText)
        self.setAccessibleName(ui_text('compare.overlay.title'))
        self.records = ()
        self.total = self.dropped = 0
        privacy.bind_text(self, self.refresh_privacy)

    def set_records(self, records):
        self.total = len(records)
        self.records = tuple(records[:CAP])
        self.dropped = sum(record[2] for record in self.records)
        self.refresh_privacy()

    def refresh_privacy(self):
        masked = privacy.enabled(self)
        labels = [
            ui_text('compare.overlay.legend').format(index + 1, PATTERN_LABELS[index], privacy.mask_money('') if masked else safe_text(name))
            for index, (name, _, _) in enumerate(self.records)
        ]
        self.canvas.set_series([(label, row[1]) for label, row in zip(labels, self.records)])
        self.legend.setText('\n'.join(labels))
        days = self.canvas.days
        start, end = (date.fromordinal(days[0]).isoformat(), date.fromordinal(days[-1]).isoformat()) if days else ('', '')
        text = ui_text('compare.overlay.summary').format(len(self.canvas.series), start, end, self.dropped + self.canvas.dropped)
        if self.total > CAP:
            text += '\n' + ui_text('compare.overlay.cap').format(CAP, self.total)
        self.summary.setText(text + '\n' + ui_text('compare.overlay.normalisation'))
        self.setAccessibleDescription(self.summary.text())
        self.canvas.publish_readout()


def attach_overlay(page, layout):
    """Install a signal-only adapter; allocate no widget before selection."""

    def refresh():
        selected = page.comparison_list.selectedItems()
        overlay = getattr(page, '_equity_overlay', None)
        if not selected and overlay is None:
            return
        if overlay is None:
            overlay = page._equity_overlay = EquityOverlay(page)
            layout.addWidget(overlay)
        saved = page.saved_results_table
        cache = getattr(saved, '_overlay_records', {})
        overlay.set_records([cache.get(item.data(Qt.ItemDataRole.UserRole), (item.text(), (), 0)) for item in selected])

    page.comparison_list.itemSelectionChanged.connect(refresh)
    page.saved_results_table.overlay_changed.connect(refresh)
