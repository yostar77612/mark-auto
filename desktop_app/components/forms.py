"""desktop_app components forms responsibilities."""

from desktop_app.components.fields import named_field

from desktop_app.components.tables import fill_table

from desktop_app.strings.catalog import ui_text
from desktop_app.components.timeinput import DateInput, DATE_KEYS, TIME_KEYS, install_date_columns, open_date_editors
from copy import deepcopy
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
)
from quantlab.core import ValidationError
from desktop_app.components.form_values import number, required


class _Form(QWidget):
    """Shared label/field plumbing only; each payload is explicit below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        self.outer = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.outer.addLayout(self.form)

    def note(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        self.outer.addWidget(label)
        return label

    def field(self, key, label, value='', choices=None):
        if choices is None:
            widget = DateInput(str(value), timestamp=key in TIME_KEYS) if key in DATE_KEYS | TIME_KEYS else QLineEdit(str(value))
        else:
            widget = QComboBox()
            for caption, data in choices:
                widget.addItem(caption, data)
        caption = QLabel(label)
        named_field(widget, key, label, caption=caption)
        self.form.addRow(caption, widget)
        self.fields[key] = widget
        return widget

    def text(self, key):
        return self.fields[key].text().strip()

    def num(self, key, minimum=0, maximum='1e12', **kwargs):
        return number(self.text(key), self.fields[key].accessibleName(), minimum, maximum, **kwargs)

    def load(self, values):
        for key, value in values.items():
            if key not in self.fields:
                continue
            field = self.fields[key]
            if isinstance(field, QComboBox):
                index = field.findData(value)
                if index < 0:
                    raise ValidationError(ui_text('forms.load.unsupported_option').format(field.accessibleName()))
                field.setCurrentIndex(index)
            else:
                field.setText('' if value is None else str(value))
        return self


class _Rows(QWidget):
    """Plain typed table for bounded policy rows, with keyboard-accessible buttons."""

    def __init__(self, name, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self._original = []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(columns))
        self.table.setObjectName(name)
        self.table.setHorizontalHeaderLabels([label for _, label in columns])
        layout.addWidget(self.table)
        install_date_columns(self.table, columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.resizeColumnsToContents()
        for index, (_, label) in enumerate(columns):
            self.table.horizontalHeaderItem(index).setToolTip(label)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        add = QPushButton(ui_text('forms.init.add_row'))
        add.setObjectName(name + '_add')
        add.clicked.connect(self.add_row)
        remove = QPushButton(ui_text('forms.init.remove_row'))
        remove.setObjectName(name + '_remove')
        remove.setProperty('role', 'danger')
        remove.clicked.connect(self.remove_row)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()

    def add_row(self):
        self.table.insertRow(self.table.rowCount())
        self._original.append({})
        open_date_editors(self.table, self.columns, self.table.rowCount() - 1)

    def remove_row(self):
        row = self.table.currentRow()
        if (
            row >= 0
            and QMessageBox.question(
                self,
                ui_text('forms.remove_row.confirm_title'),
                ui_text('forms.remove_row.confirm_question'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.table.removeRow(row)
            self._original.pop(row)

    def load(self, rows):
        self.table.setRowCount(len(rows))
        self._original = deepcopy(rows)
        fill_table(
            self.table,
            rows,
            [key for key, _ in self.columns],
            lambda row, key: QTableWidgetItem(str(row.get(key, ''))),
            after_row=lambda i: open_date_editors(self.table, self.columns, i),
        )

    def values(self):
        rows = deepcopy(self._original)
        for i, row in enumerate(rows):
            for j, (key, label) in enumerate(self.columns):
                item = self.table.item(i, j)
                row[key] = required(item.text() if item else '', label)
        return rows
