"""Presentation-only helpers that fill existing validated input controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QTableWidgetItem
from desktop_strings import ui_text
from desktop_presentation import display_number
from quantlab.taifex_expiries import load_expiries, lookup_expiry


class ExpiryPicker(QWidget):
    selected = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        try:
            self.data = load_expiries()
        except (ValueError, OSError):
            # Fail closed without preventing the established manual workflow.
            self.summary = QLabel(ui_text('expiry.unavailable'))
            self.summary.setWordWrap(True)
            layout.addWidget(self.summary)
            return
        row = QHBoxLayout()
        self.product = QComboBox()
        self.product.setObjectName('expiry_product')
        self.product.setAccessibleName(ui_text('expiry.product'))
        self.product.addItems(self.data['products'])
        self.month = QComboBox()
        self.month.setObjectName('expiry_month')
        self.month.setAccessibleName(ui_text('expiry.month'))
        self.month.setEditable(True)
        self.month.addItem(ui_text('expiry.manual'), '')
        for entry in self.data['expiries']:
            self.month.addItem(entry['contract_month'], entry['contract_month'])
        row.addWidget(self.product)
        row.addWidget(self.month)
        self.source_button = QPushButton(ui_text('expiry.source'))
        self.source_button.setObjectName('expiry_view_source')
        self.source_button.setCheckable(True)
        row.addWidget(self.source_button)
        layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setObjectName('expiry_summary')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.source = QLabel()
        self.source.setObjectName('expiry_provenance')
        self.source.setWordWrap(True)
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source.hide()
        self.source_button.toggled.connect(self.source.setVisible)
        layout.addWidget(self.source)
        self.product.currentIndexChanged.connect(self._changed)
        self.month.currentTextChanged.connect(self._changed)
        self._changed()

    def _changed(self, *args):
        month = self.month.currentText().strip()
        match = lookup_expiry(self.product.currentText(), month, data=self.data)
        self.summary.setText(ui_text('expiry.date').format(match['expiry_date']) if match else ui_text('expiry.uncovered'))
        source = match['source'] if match else self.data['sources'][0]
        self.source.setText(ui_text('expiry.provenance').format(source['url'], self.data['data_version'], self.data['verified_date'], source['retrieval_date']))
        if match:
            self.selected.emit(self.product.currentText(), month, match['expiry_date'])


def attach_expiry_table(form):
    picker = ExpiryPicker(form)
    form.expiry_picker = picker
    form.outer.insertWidget(form.outer.indexOf(form.expiries), picker)

    def fill(product, month, expiry):
        contract = 'TAIFEX:{}:{}'.format(product, month)
        table = form.expiries.table
        # An explicit manual row always wins; never rewrite the user's date.
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.text().strip() == contract:
                return
        form.expiries.add_row()
        row = table.rowCount() - 1
        for column, value in enumerate((contract, expiry)):
            table.setItem(row, column, QTableWidgetItem(value))

    picker.selected.connect(fill)


def attach_history_picker(dialog, layout):
    picker = ExpiryPicker(dialog)
    dialog.expiry_picker = picker
    layout.addRow(picker)

    def fill(product, month, expiry):
        dialog.product.setCurrentIndex(dialog.product.findData(product))
        dialog.expiry_type.setCurrentIndex(dialog.expiry_type.findData('monthly'))
        dialog.month.setText(month)

    picker.selected.connect(fill)


def show_research_dataset(label, dataset):
    """Visible synthetic-only summary; official quote snapshots are untouched."""
    label.clear()
    label.hide()
    if dataset is None or dataset.manifest.get('source_type') != 'synthetic' or not dataset.bars:
        return
    contracts = ', '.join(sorted({bar.contract_id for bar in dataset.bars}))
    dates = sorted(bar.trade_date for bar in dataset.bars)
    label.setText(ui_text('market.demo_summary').format(contracts, display_number(len(dataset.bars)), dates[0], dates[-1]))
    label.show()
