"""Presentation-only date adapters; raw restored strings remain authoritative.

No zone database is needed. Taiwan uses UTC+8 without daylight saving time.
Only an explicit picker edit creates a new canonical value. Loading even an
invalid legacy string preserves it for the existing fail-closed validators.
"""

from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone, Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QLabel, QDateEdit, QDateTimeEdit, QStyledItemDelegate, QLineEdit
from desktop_app.strings.catalog import ui_text

TAIPEI = timezone(timedelta(hours=8))
DATE_KEYS = frozenset(('effective_from', 'start_date', 'end_date', 'trade_date', 'expiry_date'))
TIME_KEYS = frozenset(('created_at', 'timestamp', 'session_open', 'session_end', 'now', 'open', 'end'))


def taipei_to_utc_iso(value):
    """Treat a naive wall clock as Taipei; return the existing UTC Z spelling."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def utc_iso_to_taipei(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() != timedelta(0):
        raise ValueError('UTC timestamp required')
    return parsed.astimezone(TAIPEI)


class DateInput(QWidget):
    """Line-edit-compatible adapter with an explicit unset checkbox."""

    textChanged = Signal(str)

    def __init__(self, value='', *, timestamp=False, manual=False, parent=None):
        super().__init__(parent)
        self.timestamp = timestamp
        self._value = ''
        self._loading = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.manual = QLineEdit() if manual else None
        if self.manual is not None:
            self.manual.setAccessibleName(ui_text('forms.init.expiry_date'))
            layout.addWidget(self.manual)
            self.manual.textChanged.connect(self.setText)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocusProxy(self.manual)
        self.enabled_value = QCheckBox(ui_text('timeinput.set'))
        self.enabled_value.setAccessibleName(ui_text('timeinput.set'))
        self.picker = QDateTimeEdit() if timestamp else QDateEdit()
        self.picker.setTimeZone(QTimeZone.fromSecondsAheadOfUtc(8 * 3600))
        self.picker.setCalendarPopup(True)
        self.picker.setDisplayFormat('yyyy-MM-dd HH:mm:ss' if timestamp else 'yyyy-MM-dd')
        self.picker.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.picker.setDate(QDate(2026, 1, 1))
        self.picker.setAccessibleName(ui_text('timeinput.taipei'))
        self.hint = QLabel()
        self.hint.setProperty('prerequisite', True)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.enabled_value)
        layout.addWidget(self.picker)
        layout.addWidget(self.hint)
        self.enabled_value.toggled.connect(self._edited)
        self.picker.dateTimeChanged.connect(self._edited)
        self.setText(value)

    def text(self):
        return self._value

    def setText(self, value):
        previous = self._value
        self._loading = True
        self._value = str(value)
        if self.manual is not None and self.manual.text() != self._value:
            blocked = self.manual.blockSignals(True)
            self.manual.setText(self._value)
            self.manual.blockSignals(blocked)
        valid = False
        try:
            if self.timestamp:
                local = utc_iso_to_taipei(self._value)
                self.picker.setDateTime(
                    QDateTime(
                        QDate(local.year, local.month, local.day),
                        QTime(local.hour, local.minute, local.second, local.microsecond // 1000),
                        QTimeZone.fromSecondsAheadOfUtc(8 * 3600),
                    )
                )
            else:
                day = date.fromisoformat(self._value)
                self.picker.setDate(QDate(day.year, day.month, day.day))
            valid = True
        except (ValueError, OverflowError, TypeError):
            pass
        self.enabled_value.setChecked(bool(self._value))
        self.picker.setEnabled(bool(self._value))
        self._update_hint(valid)
        self._loading = False
        if previous != self._value:
            self.textChanged.emit(self._value)

    def _update_hint(self, valid=True):
        if not self._value:
            text = ui_text('timeinput.unset')
        elif not valid:
            text = ui_text('timeinput.invalid')
        elif self.timestamp:
            text = ui_text('timeinput.utc').format(taipei_to_utc_iso(utc_iso_to_taipei(self._value)))
        else:
            text = ui_text('timeinput.date')
        self.hint.setText(text)

    def _edited(self, *_):
        if self._loading:
            return
        previous = self._value
        self.picker.setEnabled(self.enabled_value.isChecked())
        if not self.enabled_value.isChecked():
            self._value = ''
        elif self.timestamp:
            day, clock = self.picker.date(), self.picker.time()
            self._value = taipei_to_utc_iso(datetime(day.year(), day.month(), day.day(), clock.hour(), clock.minute(), clock.second()))
        else:
            self._value = self.picker.date().toString('yyyy-MM-dd')
        if self.manual is not None:
            blocked = self.manual.blockSignals(True)
            self.manual.setText(self._value)
            self.manual.blockSignals(blocked)
        self._update_hint()
        if previous != self._value:
            self.textChanged.emit(self._value)

    def clear(self):
        self.setText('')

    def setPlaceholderText(self, text):
        self.setToolTip(text)


class DateDelegate(QStyledItemDelegate):
    """Keep canonical table items and legacy setItem/test accessors intact."""

    def __init__(self, timestamp, parent, *, manual=False):
        super().__init__(parent)
        self.timestamp = timestamp
        self.manual = manual

    def createEditor(self, parent, option, index):
        editor = DateInput(timestamp=self.timestamp, manual=self.manual, parent=parent)
        editor.textChanged.connect(lambda _: self.commitData.emit(editor))
        return editor

    def setEditorData(self, editor, index):
        editor.blockSignals(True)
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or '')
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 42))
        size.setWidth(max(size.width(), 400 if self.timestamp else 260))
        return size


def install_date_columns(table, columns):
    for column, (key, _) in enumerate(columns):
        if key in DATE_KEYS | TIME_KEYS:
            table.setItemDelegateForColumn(column, DateDelegate(key in TIME_KEYS, table, manual=key == 'expiry_date'))


def open_date_editors(table, columns, row):
    from PySide6.QtWidgets import QTableWidgetItem

    for column, (key, _) in enumerate(columns):
        if key in DATE_KEYS | TIME_KEYS:
            if table.item(row, column) is None:
                table.setItem(row, column, QTableWidgetItem(''))
            table.openPersistentEditor(table.item(row, column))
    table.resizeRowsToContents()


def history_utc_hint(date_field, clock, parent=None):
    """History retains its existing separate Taipei date and time objectNames."""
    hint = QLabel(parent)
    hint.setProperty('prerequisite', True)

    def refresh(*_):
        try:
            day = date.fromisoformat(date_field.text())
            value = datetime(day.year, day.month, day.day, clock.time().hour(), clock.time().minute())
            hint.setText(ui_text('timeinput.utc').format(taipei_to_utc_iso(value)))
        except ValueError:
            hint.setText(ui_text('timeinput.unset') if not date_field.text() else ui_text('timeinput.invalid'))

    date_field.textChanged.connect(refresh)
    clock.timeChanged.connect(refresh)
    refresh()
    return hint
