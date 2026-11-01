"""Short visible copy with complete, keyboard-accessible explanation dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text


class HelpText(QWidget):
    def __init__(self, short_text, full_text, name, parent=None, *, header=None):
        super().__init__(parent)
        self.setObjectName(name + '_help_row')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(self)
        self.summary.setObjectName(name)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary, 1)
        self.button = QToolButton(self)
        self.button.setObjectName(name + '_help')
        self.button.setText(ui_text('help.symbol'))
        self.button.setAccessibleName(ui_text('help.accessible'))
        self.button.setProperty('tradingHelp', True)
        self.button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        (header or layout).addWidget(self.button, alignment=Qt.AlignmentFlag.AlignTop)
        self.dialog = QDialog(self)
        self.dialog.setObjectName(name + '_help_details')
        self.dialog.setWindowTitle(ui_text('help.accessible'))
        self.dialog.resize(620, 200)
        body = QVBoxLayout(self.dialog)
        self.details = QLabel(self.dialog)
        self.details.setObjectName(name + '_help_text')
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        body.addWidget(self.details)
        self.button.clicked.connect(self.dialog.show)
        self.set_content(short_text, full_text)

    def set_content(self, short_text, full_text):
        self.summary.setText(short_text)
        self.summary.setAccessibleName(short_text)
        self.details.setText(full_text)
        self.details.setAccessibleName(full_text)
        self.button.setToolTip(full_text)
        self.button.setAccessibleDescription(full_text)
