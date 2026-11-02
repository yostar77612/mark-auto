"""An explicit opt-in to launch MarkAuto with the current Windows user."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from quantlab.errors import AutostartError, ERROR_TABLE


class AutostartPanel(QWidget):
    def __init__(self, parent=None, *, controller=None):
        super().__init__(parent)
        self.controller = controller if controller is not None else QApplication.instance().property('autostartController')
        self._checked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(ui_text('autostart.enable'))
        self.enabled.setObjectName('autostart_enabled')
        self.enabled.setToolTip(ui_text('autostart.hint'))
        layout.addWidget(self.enabled)
        self.hint = QLabel(ui_text('autostart.hint'))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self.controller is None:
            self.enabled.setEnabled(False)
            self.status.setText(ui_text('autostart.unavailable'))
        else:
            try:
                self._checked = self.controller.repair_enabled()
                self.enabled.setChecked(self._checked)
            except AutostartError as exc:
                self.enabled.setEnabled(False)
                self._show_error(exc.code)
        self.enabled.toggled.connect(self.set_enabled)

    def set_enabled(self, checked: bool) -> None:
        if self.property('offlinePreview') is True:
            self._restore_checked()
            return
        try:
            self.controller.set_enabled(checked)
        except AutostartError as exc:
            self._restore_checked()
            self._show_error(exc.code)
            return
        self._checked = checked
        self.status.setText(ui_text('autostart.enabled') if checked else ui_text('autostart.disabled'))

    def _show_error(self, code: str) -> None:
        entry = ERROR_TABLE[code]
        self.status.setText(ui_text('async.error').format(code, entry.explanation, entry.action))

    def _restore_checked(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._checked)
        self.enabled.blockSignals(False)
