"""Explicit settings actions, independent of research jobs and user data."""

import os
from pathlib import Path
from queue import SimpleQueue
import sys
from threading import Thread

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout, QWidget

from desktop_strings import ui_text
from .async_status import AsyncStatus
from quantlab import __version__
from quantlab.payload_cleanup import execute_payload_cleanup, plan_payload_cleanup
from quantlab.update_check import UpdateResult, check_for_update


def installed_payload_root():
    """Offer deletion only from the supported, frozen per-user installation."""
    local = os.environ.get('LOCALAPPDATA')
    if not getattr(sys, 'frozen', False) or not local:
        return None
    root = Path(local) / 'Programs' / 'MarkAuto' / 'payloads'
    executable = Path(sys.executable)
    # payloads/<version>/<unique-name>/MarkAuto.exe, never the workspace.
    if executable.parent.parent.name != __version__ or executable.parent.parent.parent != root:
        return None
    return root


def _check_in_background(queue, version):
    try:
        result = check_for_update(version)
    except Exception:
        result = UpdateResult('error', 'check_failed')
    queue.put(result)


class MaintenancePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.update_button = QPushButton(ui_text('maintenance.check_updates'))
        self.update_button.setObjectName('check_for_updates')
        self.cleanup_button = QPushButton(ui_text('maintenance.check_payloads'))
        self.cleanup_button.setObjectName('check_old_program_versions')
        self.async_status = AsyncStatus()
        self.async_status.setObjectName('maintenance_async_status')
        self.async_status.set_state('empty', message='')
        self.status = self.async_status.label
        for widget in (self.update_button, self.cleanup_button, self.async_status):
            layout.addWidget(widget)
        self.update_button.clicked.connect(self.check_updates)
        self.cleanup_button.clicked.connect(self.check_payloads)
        self.results = SimpleQueue()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll_update)

    def check_updates(self):
        if self.property('offlinePreview') is True:
            self.async_status.set_state('empty', message=ui_text('redesign.preview.network_disabled'))
            return
        if not self.update_button.isEnabled():
            return
        self.update_button.setEnabled(False)
        self.async_status.set_state('loading')
        try:
            Thread(target=_check_in_background, args=(self.results, __version__), daemon=True).start()
            self.timer.start()
        except RuntimeError:
            self.results.put(UpdateResult('error', 'check_failed'))
            self.poll_update()

    def poll_update(self):
        if self.results.empty():
            return
        result = self.results.get_nowait()
        self.timer.stop()
        self.update_button.setEnabled(True)
        key = {'update_available': 'maintenance.available', 'up_to_date': 'maintenance.current', 'error': 'maintenance.update_error'}[result.status]
        if result.status == 'error':
            self.async_status.set_state('error', error_code='operation_failed', retry=self.check_updates)
        else:
            self.async_status.set_state('empty', message=ui_text(key).format(result.version))

    def check_payloads(self):
        root = installed_payload_root()
        if root is None:
            self.async_status.set_state('empty', message=ui_text('maintenance.not_installed'))
            return
        plan = plan_payload_cleanup(root, __version__)
        if plan.reason:
            self.async_status.set_state('empty', message=ui_text('maintenance.refused'))
            return
        if not plan.candidates:
            self.async_status.set_state('empty', message=ui_text('maintenance.nothing'))
            return
        names = '\n'.join(path.name for path in plan.candidates)
        message = ui_text('maintenance.confirm').format(str(plan.root), names)
        confirmed = QMessageBox.question(self, ui_text('maintenance.check_payloads'), message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirmed != QMessageBox.Yes:
            self.async_status.set_state('empty', message=ui_text('maintenance.cancelled'))
            return
        result = execute_payload_cleanup(plan)
        key = 'maintenance.cleanup_error' if result.reason else 'maintenance.cleaned'
        self.async_status.set_state('empty', message=ui_text(key).format(len(result.deleted)))
