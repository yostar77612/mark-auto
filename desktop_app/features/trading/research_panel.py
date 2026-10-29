"""Embedded research view; no storage, SDK, authentication or engine access."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text


class ResearchPanel(QWidget):
    page_requested = Signal(str)
    back_requested = Signal()
    ROUTES = {
        'data': (2, 'data'),
        'strategy': (1, 'strategy'),
        'backtest': (4, 'backtest'),
        'compare': (4, 'compare'),
        'paper': (3, 'paper'),
        'market': (2, 'market'),
        'settings': (5, 'settings'),
        'connection': (5, 'settings'),
        'assistant': (1, 'settings'),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('unified_research_panel')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.back = QPushButton(ui_text('unified.back'))
        self.back.setObjectName('research_back_to_platform')
        self.back.clicked.connect(self.back_requested)
        toolbar.addWidget(self.back)
        self.choice = QComboBox()
        self.choice.setObjectName('unified_research_navigation')
        self.choice.setAccessibleName(ui_text('unified.research_navigation'))
        captions = {
            'data': ui_text('unified.page.data'),
            'strategy': ui_text('unified.page.strategy'),
            'backtest': ui_text('unified.page.backtest'),
            'compare': ui_text('unified.page.compare'),
            'paper': ui_text('unified.page.paper'),
            'market': ui_text('unified.page.market'),
            'settings': ui_text('unified.page.settings'),
            'connection': ui_text('unified.page.connection'),
            'assistant': ui_text('unified.page.assistant'),
        }
        for page, caption in captions.items():
            self.choice.addItem(caption, page)
        self.choice.activated.connect(lambda: self.page_requested.emit(self.choice.currentData()))
        toolbar.addWidget(self.choice, 1)
        self.job_status = QLabel()
        self.job_status.setTextFormat(Qt.TextFormat.PlainText)
        toolbar.addWidget(self.job_status)
        layout.addLayout(toolbar)
        self.scope = QLabel(ui_text('unified.research_scope'))
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.error = QLabel(ui_text('unified.loading'))
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        self.content = QVBoxLayout()
        layout.addLayout(self.content, 1)

    def mount(self, widget):
        self.error.hide()
        self.content.addWidget(widget)

    def set_error(self, text):
        self.error.setText(text)
        self.error.show()

    def set_page(self, page):
        self.choice.blockSignals(True)
        self.choice.setCurrentIndex(self.choice.findData(page))
        self.choice.blockSignals(False)
