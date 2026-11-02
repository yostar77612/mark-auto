"""Inline next steps for connection facts; disclosure never performs an action."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text


class ReadinessGuidance(QWidget):
    def __init__(self, short_text: str, full_text: str, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(name + '_guidance')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.summary = QLabel(self)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        self.button = QToolButton(self)
        self.button.setObjectName(name + '_help')
        self.button.setText(ui_text('help.symbol'))
        self.button.setAccessibleName(ui_text('u1.readiness.help'))
        self.button.setCheckable(True)
        self.button.setProperty('tradingHelp', True)
        row.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        self.details = QLabel(self)
        self.details.setObjectName(name + '_details')
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self.details)
        self.details.hide()
        self.button.toggled.connect(self.details.setVisible)
        self.set_content(short_text, full_text)

    def set_content(self, short_text: str, full_text: str) -> None:
        self.summary.setText(short_text)
        self.summary.setAccessibleName(short_text)
        self.details.setText(full_text)
        self.details.setAccessibleName(full_text)
        self.button.setToolTip(full_text)
        self.button.setAccessibleDescription(full_text)


def account_guidance(signed: bool | None) -> tuple[str, str]:
    short = (
        ui_text('u1.readiness.signed_next')
        if signed is True
        else ui_text('u1.readiness.unsigned_next')
        if signed is False
        else ui_text('u1.readiness.unknown_next')
    )
    return short, ui_text('u1.readiness.agreement_steps')


def readiness_steps(code: str) -> str:
    return {
        'market': ui_text('u1.readiness.market_steps'),
        'accounts': ui_text('u1.readiness.reconciliation_steps'),
        'simulation_orders': ui_text('u1.readiness.simulation_steps'),
        'production_orders': ui_text('u1.readiness.live_steps'),
    }[code]
