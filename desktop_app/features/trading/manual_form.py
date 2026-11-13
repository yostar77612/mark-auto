"""Manual simulation inputs; economic checks belong to the application."""

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout

from desktop_app.features.trading.page_help import HelpText
from desktop_app.features.trading.widgets import button, label
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ManualOrderForm
from quantlab.trading.domain.models import QuantityUnit, Side


class ManualForm(QGroupBox):
    def __init__(self, parent=None):
        super().__init__(ui_text('m2m.title'), parent)
        self.setObjectName('manual_simulation')
        layout = QVBoxLayout(self)
        layout.addWidget(HelpText(ui_text('m2m.hint'), ui_text('m2m.help'), 'manual_simulation'))
        self.status = label('m2m.not_ready')
        self.status.setObjectName('manual_status')
        layout.addWidget(self.status)
        # Not connected to the broker simulation: one click to the place where that is done.
        self.connect_button = QPushButton(ui_text('m2m.open_connection'))
        self.connect_button.setAccessibleName(ui_text('m2m.open_connection'))
        self.connect_button.setMinimumHeight(36)
        self.connect_button.setVisible(False)
        layout.addWidget(self.connect_button)
        book = QHBoxLayout()
        self.capital = QLineEdit()
        self.capital.setMaximumWidth(150)
        self._field(book, self.capital, ui_text('m2m.capital'), 'manual_capital')
        self.prepare = button('m2m.prepare', 'manual_prepare')
        book.addWidget(self.prepare)
        book.addStretch()
        self.test_order = button('m2m.test', 'manual_test')
        book.addWidget(self.test_order)
        layout.addLayout(book)
        fields = QGridLayout()
        self.instrument, self.side, self.quantity = QComboBox(), QComboBox(), QSpinBox()
        self.side.addItem(ui_text('m2m.buy'), Side.BUY)
        self.side.addItem(ui_text('m2m.sell'), Side.SELL)
        self.quantity.setRange(1, 1000000)
        self.price, self.stop = QLineEdit(), QLineEdit()
        self.price.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.stop.setAlignment(Qt.AlignmentFlag.AlignRight)
        for index, (widget, text, name) in enumerate(
            (
                (self.instrument, ui_text('m2m.instrument'), 'manual_instrument'),
                (self.side, ui_text('m2m.side'), 'manual_side'),
                (self.quantity, ui_text('m2m.quantity'), 'manual_quantity'),
                (self.price, ui_text('m2m.price'), 'manual_price'),
                (self.stop, ui_text('m2m.stop'), 'manual_stop'),
            )
        ):
            row, column = divmod(index, 3)
            caption = QLabel(text)
            caption.setBuddy(widget)
            widget.setObjectName(name)
            widget.setAccessibleName(text)
            fields.addWidget(caption, row * 2, column)
            fields.addWidget(widget, row * 2 + 1, column)
        layout.addLayout(fields)
        self.contract_details = label('m2m.not_ready')
        self.contract_details.setObjectName('manual_contract_details')
        layout.addWidget(self.contract_details)
        self.preview = label('m2m.no_preview')
        self.preview.setObjectName('manual_preview_details')
        layout.addWidget(self.preview)
        actions = QHBoxLayout()
        self.preview_button = button('m2m.preview', 'manual_preview')
        self.submit = button('m2m.submit', 'manual_submit', role='primary')
        self.positions_button = button('m2m.open_positions', 'manual_positions')
        actions.addWidget(self.preview_button)
        actions.addWidget(self.submit)
        actions.addWidget(self.positions_button)
        actions.addStretch()
        layout.addLayout(actions)

    @staticmethod
    def _field(layout, widget, text, name):
        caption = QLabel(text)
        caption.setBuddy(widget)
        widget.setObjectName(name)
        widget.setAccessibleName(text)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(caption)
        layout.addWidget(widget)

    def order(self, scope, instrument, request_id):
        # The server supplies the unit conversion. No price/risk/margin formula
        # or invented contract defaults are trusted at this boundary.
        quantity = self.quantity.value() * (instrument.lot_size if instrument.quantity_unit is QuantityUnit.SHARE else 1)
        return ManualOrderForm(
            scope, request_id, instrument.instrument_id, Side(self.side.currentData()), quantity, Decimal(self.price.text()), Decimal(self.stop.text())
        )
