"""Read-only projection of the runtime's allowlisted log reader."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractItemView, QFileDialog, QVBoxLayout
from .async_status import AsyncStatus
from desktop_strings import ui_text, LOG_OPERATION_NAMES, LOG_EVENT_NAMES
from desktop_theme import align_table_item


def choose_log_export(parent):
    return QFileDialog.getSaveFileName(parent, ui_text('logs.export'), '', ui_text('logs.csv'))[0]


def log_rows(lines):
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
            operation, event = value['operation'], value['event']
            if operation not in LOG_OPERATION_NAMES or event not in LOG_EVENT_NAMES:
                continue
            stamp = datetime.fromtimestamp(value['time'], timezone(timedelta(hours=8)))
            rows.append((stamp.strftime('%Y-%m-%d %H:%M:%S'), ui_text(LOG_OPERATION_NAMES[operation]), ui_text(LOG_EVENT_NAMES[event]), event))
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
    return rows


class LogTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 3)
        self.empty_status = AsyncStatus(self.viewport())
        self.empty_status.setObjectName('logs_empty_status')
        self.empty_status.set_state('empty', message=ui_text('async.logs_empty'))
        overlay = QVBoxLayout(self.viewport())
        overlay.addWidget(self.empty_status)
        self.rows = []
        self.errors_only = False
        self.setHorizontalHeaderLabels([ui_text('logs.time'), ui_text('logs.operation'), ui_text('logs.result')])
        for column in range(self.columnCount()):
            align_table_item(self.horizontalHeaderItem(column))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)
        self.setAccessibleName(ui_text('ui.settings_page.read_logs'))

    def load(self, lines):
        self.rows = log_rows(lines)
        self.refresh()

    def filter_errors(self, checked):
        self.errors_only = checked
        self.refresh()

    def visible_rows(self):
        return [row[:3] for row in self.rows if not self.errors_only or row[3] == 'error']

    def refresh(self):
        rows = self.visible_rows()
        self.empty_status.setVisible(not rows)
        self.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text)
                align_table_item(item)
                self.setItem(index, column, item)
        self.resizeColumnsToContents()

    def export(self):
        name = choose_log_export(self)
        if not name:
            return
        with Path(name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow([self.horizontalHeaderItem(i).text() for i in range(3)])
            writer.writerows(self.visible_rows())
