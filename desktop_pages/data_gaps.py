"""Lazy read-only gap table and deterministic per-contract/day timeline."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QBrush
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView

import desktop_privacy as privacy
from desktop_strings import ui_text
from quantlab.data_gap_report import GapReport, build_gap_report

TAIPEI = timezone(timedelta(hours=8))


def segment_text(gap):
    start = datetime.fromisoformat(gap.start).astimezone(TAIPEI).isoformat(timespec='minutes')
    end = datetime.fromisoformat(gap.end).astimezone(TAIPEI).isoformat(timespec='minutes')
    return ui_text('data.gaps.segment').format(gap.trade_date, gap.contract_id, start, end)


def timeline_rows(gaps):
    groups = defaultdict(list)
    for gap in gaps:
        groups[gap.contract_id, gap.trade_date].append(gap)
    rows = []
    for (contract, day), segments in sorted(groups.items()):
        starts = [datetime.fromisoformat(g.start).astimezone(TAIPEI) for g in segments]
        ends = [datetime.fromisoformat(g.end).astimezone(TAIPEI) for g in segments]
        origin = min(starts).replace(hour=0, minute=0, second=0, microsecond=0)
        span = ((max(ends).date() - origin.date()).days + 1) * 86400
        rows.append((contract, day, tuple(sorted(((s - origin).total_seconds() / span, (e - origin).total_seconds() / span) for s, e in zip(starts, ends)))))
    return tuple(rows)


class GapTimeline(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = ()
        self.setAccessibleName(ui_text('data.gaps.timeline'))

    def set_gaps(self, gaps):
        self.rows = timeline_rows(gaps)
        self.setAccessibleDescription('\n'.join(segment_text(g) for g in gaps))
        self.setMinimumHeight(len(self.rows) * 30)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        palette = self.palette()
        for index, (contract, day, segments) in enumerate(self.rows):
            top = index * 30
            painter.setPen(palette.text().color())
            painter.drawText(0, top + 17, ui_text('data.gaps.day').format(contract, day))
            left = min(280, self.width() // 2)
            width = max(0, self.width() - left - 8)
            painter.fillRect(QRectF(left, top + 4, width, 18), palette.alternateBase())
            for start, end in segments:
                rect = QRectF(left + start * width, top + 4, max(2, (end - start) * width), 18)
                painter.fillRect(rect, QBrush(palette.highlight().color(), Qt.BrushStyle.Dense4Pattern))
                painter.drawRect(rect)
        painter.end()


class GapPanel(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.report = GapReport()
        layout = QVBoxLayout(self)
        self.notice = QLabel(self)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.table = QTableWidget(0, 3, self)
        self.table.setAccessibleName(ui_text('data.gaps.table'))
        self.table.setHorizontalHeaderLabels([ui_text('data.gaps.contract'), ui_text('data.gaps.date'), ui_text('data.gaps.missing')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.timeline = GapTimeline(self)
        layout.addWidget(self.timeline)
        privacy.bind_text(self.notice, self.refresh)

    def set_report(self, report):
        self.report = report
        self.refresh()

    def refresh(self):
        report = self.report
        self.notice.setText(report.message + '\n' + ui_text('data.gaps.options') + (ui_text('data.gaps.more').format(report.more) if report.more else ''))
        gaps = sorted(report.gaps, key=lambda g: (g.contract_id, g.trade_date, g.start))
        self.table.setRowCount(len(gaps))
        for row, gap in enumerate(gaps):
            for column, value in enumerate((gap.contract_id, gap.trade_date, segment_text(gap))):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.timeline.set_gaps(gaps)
        self.setVisible(bool(gaps))


def import_event(page, event):
    packet = event.get('gap_report')
    if event.get('type') == 'progress' and isinstance(packet, dict):
        report = build_gap_report(packet.get('quality'), packet.get('code'))
        more = packet.get('more', 0)
        if type(more) is int and more > 0 and report.gaps:
            report = GapReport(report.gaps, more + report.more, report.code)
        page.show_gap_report(report)
    elif event.get('type') in ('result', 'completed', 'success'):
        page.reset_gap_report()
