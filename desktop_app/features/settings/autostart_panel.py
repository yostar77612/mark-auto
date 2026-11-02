"""An explicit opt-in to launch MarkAuto with the current Windows user."""

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QVBoxLayout, QWidget

from desktop_app.components.async_status import AsyncStatus
from desktop_app.strings.catalog import ui_text
from quantlab.errors import AutostartError


class AutostartPanel(QWidget):
    def __init__(self, parent=None, *, controller=None):
        super().__init__(parent)
        self.controller = controller if controller is not None else QApplication.instance().property('autostartController')
        self._checked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(ui_text('autostart.enable'))
        self.enabled.setObjectName('autostart_enabled')
        layout.addWidget(self.enabled)
        self.hint = QLabel(ui_text('autostart.hint'))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.async_status = AsyncStatus(self)
        self.async_status.set_state('empty', message='')
        layout.addWidget(self.async_status)
        if self.controller is None:
            self.enabled.setEnabled(False)
            self.async_status.set_state('empty', message=ui_text('autostart.unavailable'))
        else:
            try:
                self._checked = self.controller.repair_enabled()
                self.enabled.setChecked(self._checked)
            except AutostartError as exc:
                self.enabled.setEnabled(False)
                self.async_status.set_state('error', error_code=exc.code)
        self.enabled.toggled.connect(self.set_enabled)

    def set_enabled(self, checked: bool) -> None:
        if self.property('offlinePreview') is True:
            self._restore_checked()
            return
        try:
            self.controller.set_enabled(checked)
        except AutostartError as exc:
            self._restore_checked()
            self.async_status.set_state('error', error_code=exc.code)
            return
        self._checked = checked
        self.async_status.set_state('empty', message=ui_text('autostart.enabled') if checked else ui_text('autostart.disabled'))

    def _restore_checked(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self._checked)
        self.enabled.blockSignals(False)
