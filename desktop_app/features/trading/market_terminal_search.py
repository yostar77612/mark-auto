"""Debounced directory popup; search selection never edits the watchlist."""

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QPixmap, QPainter, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.symbol_search import search_symbols


class SymbolSearch(QWidget):
    def __init__(self, directory, select, parent=None):
        super().__init__(parent)
        self.setObjectName('terminal_search_panel')
        self.setAccessibleName(ui_text('terminal.search_placeholder'))
        self.directory, self.select = directory, select
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setAccessibleName(ui_text('terminal.search_icon'))
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().text().color(), 1.5))
        painter.drawEllipse(2, 2, 9, 9)
        painter.drawLine(10, 10, 16, 16)
        painter.end()
        icon.setPixmap(pixmap)
        row.addWidget(icon)
        self.input = QLineEdit()
        self.input.setObjectName('terminal_search')
        self.input.setAccessibleName(ui_text('terminal.search_placeholder'))
        self.input.setPlaceholderText(ui_text('terminal.search_placeholder'))
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        layout.addLayout(row)
        self.results = QListWidget(self)
        self.results.setObjectName('terminal_search_results')
        self.results.setAccessibleName(ui_text('terminal.search_placeholder'))
        self.results.setMaximumHeight(180)
        self.results.installEventFilter(self)
        self.results.hide()
        self.offline = QLabel(ui_text('terminal.search_offline'))
        self.offline.setObjectName('terminal_search_offline')
        self.offline.setAccessibleName(ui_text('terminal.search_offline'))
        self.offline.hide()
        layout.addWidget(self.offline)
        layout.addWidget(self.results)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.search)
        self.input.textEdited.connect(lambda _: self.timer.start())
        self.results.itemClicked.connect(self.choose)
        self.results.itemActivated.connect(self.choose)
        self.input.returnPressed.connect(self.choose)

    def search(self):
        self.results.clear()
        matches = search_symbols(self.directory(), self.input.text())
        exchanges = {'TSE': ui_text('terminal.exchange_tse'), 'OTC': ui_text('terminal.exchange_otc'), 'INDEX': ui_text('terminal.exchange_index')}
        for instrument in matches:
            item = QListWidgetItem(f'{instrument.code}  {instrument.name}  {exchanges[instrument.exchange]}')
            item.setData(Qt.ItemDataRole.UserRole, instrument)
            self.results.addItem(item)
        if not matches:
            item = QListWidgetItem(ui_text('terminal.search_none'))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
        self.results.setVisible(bool(self.input.text().strip()))

    def choose(self, item=None):
        if self.timer.isActive():
            self.timer.stop()
            self.search()
        selected = item or self.results.currentItem() or self.results.item(0)
        instrument = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        if instrument is not None:
            self.input.setText(instrument.code + ' ' + instrument.name)
            self.results.hide()
            self.select(instrument.instrument_id)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.timer.stop()
                self.input.clear()
                self.results.hide()
                return True
            if watched is self.results and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.choose()
                return True
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                self.results.setCurrentRow(max(0, min(self.results.count() - 1, self.results.currentRow() + step)))
                return True
        return super().eventFilter(watched, event)
