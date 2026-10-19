"""Display-only result components; source records and metric semantics stay intact."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTableWidgetItem
from desktop_strings import ui_text
from desktop_presentation import display_number, display_value, RATIOS, AMOUNTS
from desktop_forms import ResultTable as LegacyTable, BacktestFillsTable, RESULT_LABELS, _report_text

MISSING = object()
NUMERIC_FIELDS = (
    AMOUNTS
    | RATIOS
    | frozenset(
        (
            'profit_factor',
            'sharpe',
            'closed_lots',
            'trade_count',
            'quantity',
            'price',
            'folds',
            'evaluated_oos_folds',
            'evaluations_reserved',
            'evaluation_limit',
            'positions',
            'orders',
            'fills',
        )
    )
)


def numeric(value):
    if isinstance(value, bool) or len(str(value)) > 128:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def position_text(value):
    number = numeric(value)
    if number is None:
        return ui_text('forms.metric.text_2')
    if number == 0:
        return ui_text('results.flat')
    return ui_text('results.short' if number < 0 else 'results.long').format(display_number(abs(number)))


def taipei_time(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone required')
        return parsed.astimezone(timezone(timedelta(hours=8))).isoformat(sep=' ', timespec='seconds').removesuffix('+08:00')
    except (ValueError, TypeError, AttributeError):
        return ui_text('forms.set_rows.text_5')


def shown(value=MISSING, key=''):
    if value is MISSING:
        return ui_text('forms.metric.text_2')
    if value is None:
        return ui_text('forms.metric.text_1')
    if key.endswith(('_id', '_hash')) and value is not None:
        return str(value)
    if key in ('open_position', 'position'):
        return position_text(value)
    if key == 'timestamp':
        return taipei_time(value)
    number = numeric(value)
    if number is not None:
        text = display_number(value, key)
        if key not in RATIOS and key not in AMOUNTS and numeric(text) is not None:
            whole, dot, fraction = text.partition('.')
            text = format(int(whole), ',') + (dot + fraction if dot else '')
        return text
    if key in NUMERIC_FIELDS:
        return ui_text('presentation.display_number.text_1')
    if isinstance(value, (dict, list, tuple)):
        return ui_text('presentation.display_number.text_1')
    return display_value(value, key) or ui_text('forms.metric.text_2')


def column_label(key):
    if key == 'timestamp':
        return ui_text('results.taipei')
    if key == 'position':
        return RESULT_LABELS['open_position']
    return RESULT_LABELS.get(key, key)


class SortItem(QTableWidgetItem):
    def __lt__(self, other):
        left, right = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class CopyTable:
    def enable_copy(self):
        action = QAction(ui_text('results.copy'), self)
        action.setShortcut(QKeySequence.StandardKey.Copy)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(self.copy_text)
        self.addAction(action)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

    def copy_text(self):
        rows = [[self.horizontalHeaderItem(c).text() for c in range(self.columnCount())]]
        rows.extend(
            [[self.item(r, c).text() if self.item(r, c) else ui_text('forms.metric.text_2') for c in range(self.columnCount())] for r in range(self.rowCount())]
        )
        text = '\n'.join('\t'.join(cell.replace('\t', ' ').replace('\n', ' ') for cell in row) for row in rows)
        QApplication.clipboard().setText(text)
        return text


class ResultTable(CopyTable, LegacyTable):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.enable_copy()

    def set_rows(self, rows, columns=None, formats=None):
        rows = list(rows)
        columns = columns or list(dict.fromkeys(key for row in rows for key in row))
        self.setSortingEnabled(False)
        self.clear()
        self.setColumnCount(len(columns))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels([column_label(key) for key in columns])
        for r, row in enumerate(rows):
            for c, key in enumerate(columns):
                value = row.get(key, MISSING)
                item = SortItem(shown(value, (formats or {}).get(key, key)))
                number = numeric(value)
                item.setData(Qt.ItemDataRole.UserRole, (0, number) if number is not None else (1, item.text()))
                item.setToolTip(str(value) if value is not MISSING else ui_text('forms.metric.text_2'))
                self.setItem(r, c, item)
        # Enable header sorting without reordering a newly loaded report.
        self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            self.setColumnWidth(c, min(self.columnWidth(c), 340))


class TaipeiFillsTable(CopyTable, BacktestFillsTable):
    """Retain the legacy adapter/type and exact tooltips, adding sorting and local time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enable_copy()

    def set_rows(self, rows, columns=None):
        rows = list(rows)
        self.setSortingEnabled(False)
        super().set_rows(rows, columns)
        for r, row in enumerate(rows):
            for c, key in enumerate(self._columns):
                old = self.item(r, c)
                item = SortItem(old.text())
                item.setToolTip(old.toolTip())
                if key == 'timestamp':
                    item.setText(taipei_time(row.get(key)))
                elif numeric(row.get(key)) is not None:
                    item.setText(shown(row[key], key))
                number = numeric(row.get(key))
                item.setData(Qt.ItemDataRole.UserRole, (0, number) if number is not None else (1, item.text()))
                self.setItem(r, c, item)
        self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.horizontalHeaderItem(0).setText(ui_text('results.taipei'))


class KpiCards(QWidget):
    def __init__(self, keys, parent=None):
        super().__init__(parent)
        self.keys = keys
        self.labels = {}
        self.reasons = {}
        row = QHBoxLayout(self)
        for key in keys:
            card = QWidget()
            card.setProperty('resultCard', True)
            column = QVBoxLayout(card)
            title = QLabel(
                RESULT_LABELS.get(
                    key,
                    ui_text('results.' + key)
                    if key in ('evaluations_reserved', 'evaluation_limit', 'folds', 'evaluated_oos_folds', 'orders', 'fills', 'positions', 'stop')
                    else key,
                )
            )
            title.setWordWrap(True)
            column.addWidget(title)
            value = QLabel()
            value.setWordWrap(True)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setProperty('kpiValue', True)
            column.addWidget(value)
            self.labels[key] = value
            reason = QLabel()
            reason.setWordWrap(True)
            column.addWidget(reason)
            self.reasons[key] = reason
            row.addWidget(card)
        self.set_values({})

    def set_values(self, values):
        for key in self.keys:
            self.labels[key].setText(shown(values.get(key, MISSING), key))
            reason = self.reasons[key]
            undefined = key in values and values[key] is None and key in ('profit_factor', 'sharpe')
            reason.setText(_report_text(values.get(key + '_reason')) if undefined else '')
            reason.setVisible(undefined)
