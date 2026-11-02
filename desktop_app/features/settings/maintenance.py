"""Explicit settings actions, independent of research jobs and user data."""

from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
from queue import SimpleQueue
import sys
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from desktop_app.components.async_status import AsyncStatus
from quantlab import __version__
from quantlab.build_info import build_commit
from quantlab.payload_cleanup import execute_payload_cleanup, plan_payload_cleanup
from quantlab.errors import ERROR_TABLE
from quantlab.update_check import UpdateError, UpdateResult, check_for_update


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


def _check_in_background(queue, version, commit):
    queue.put(check_for_update(version, commit))


@dataclass(frozen=True)
class DownloadResult:
    path: Path | None = None
    error_code: str = ''


def _cancel_download(queue, cancel, lock):
    # Synchronize disposal with publication, so a completed file cannot arrive
    # after its receiving window has gone. No Qt objects cross this boundary.
    with lock:
        cancel.set()
        while not queue.empty():
            result = queue.get_nowait()
            if result.path is not None:
                result.path.unlink(missing_ok=True)
                result.path.parent.rmdir()


def _download_in_background(queue, release, cancel, download, lock):
    try:
        path = download(release, cancel)
        with lock:
            if cancel.is_set():
                path.unlink()
                path.parent.rmdir()
                queue.put(DownloadResult(error_code='update_download_cancelled'))
            else:
                queue.put(DownloadResult(path))
    except UpdateError as exc:
        queue.put(DownloadResult(error_code=exc.code))
    except OSError:
        queue.put(DownloadResult(error_code='update_download_failed'))


class MaintenancePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.release = None
        self.download_cancel = Event()
        self.download_lock = Lock()
        self.downloads = SimpleQueue()
        # The composition root injects concrete I/O; presentation never imports it.
        self.app = QApplication.instance()
        stop_download = partial(_cancel_download, self.downloads, self.download_cancel, self.download_lock)
        self.app.aboutToQuit.connect(stop_download)
        self.destroyed.connect(lambda _=None, stop=stop_download: stop())
        self.version_label = QLabel(ui_text('update.installed').format(__version__))
        self.latest_label = QLabel(ui_text('update.latest').format(ui_text('update.unknown')))
        self.published_label = QLabel(ui_text('update.published').format(ui_text('update.unknown')))
        for label in (self.version_label, self.latest_label, self.published_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.install_button = QPushButton(ui_text('update.install'))
        self.install_button.setObjectName('download_and_install_update')
        self.install_button.setProperty('role', 'primary')
        self.install_button.hide()
        self.cancel_button = QPushButton(ui_text('update.cancel'))
        self.cancel_button.hide()
        self.update_button = QPushButton(ui_text('maintenance.check_updates'))
        self.update_button.setObjectName('check_for_updates')
        self.cleanup_button = QPushButton(ui_text('maintenance.check_payloads'))
        self.cleanup_button.setObjectName('check_old_program_versions')
        self.async_status = AsyncStatus()
        self.async_status.setObjectName('maintenance_async_status')
        self.async_status.set_state('empty', message='')
        self.status = self.async_status.label
        for widget in (self.update_button, self.install_button, self.cancel_button, self.cleanup_button, self.async_status):
            layout.addWidget(widget)
        self.install_button.clicked.connect(self.install_update)
        self.cancel_button.clicked.connect(self.download_cancel.set)
        self.download_timer = QTimer(self)
        self.download_timer.setInterval(50)
        self.download_timer.timeout.connect(self.poll_download)
        self.update_button.clicked.connect(self.check_updates)
        self.cleanup_button.clicked.connect(self.check_payloads)
        self.results = SimpleQueue()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll_update)

    def check_updates(self):
        if self.property('offlinePreview') is True:
            self.update_button.setEnabled(False)
            self.async_status.set_state('empty', message=ui_text('redesign.preview.network_disabled'))
            return
        if not self.update_button.isEnabled():
            return
        self.update_button.setEnabled(False)
        self.async_status.set_state('loading')
        try:
            Thread(target=_check_in_background, args=(self.results, __version__, build_commit()), daemon=True).start()
            self.timer.start()
        except RuntimeError:
            self.results.put(UpdateResult('error', 'check_failed'))
            self.poll_update()

    def poll_update(self):
        if self.property('offlinePreview') is True:
            self.timer.stop()
            self.update_button.setEnabled(False)
            self.async_status.set_state('empty', message=ui_text('redesign.preview.network_disabled'))
            return
        if self.results.empty():
            return
        result = self.results.get_nowait()
        self.timer.stop()
        self.update_button.setEnabled(True)
        key = {'update_available': 'maintenance.available', 'up_to_date': 'maintenance.current', 'error': 'maintenance.update_error'}[result.status]
        if result.status == 'error':
            self.async_status.set_state('error', error_code='update_check_failed', retry=self.check_updates)
        else:
            message = (
                ui_text('update.available').format(result.version)
                if result.status == 'update_available' and result.release
                else ui_text(key).format(result.version)
            )
            self.async_status.set_state('empty', message=message)
        self.release = result.release
        self.latest_label.setText(ui_text('update.latest').format(result.version or ui_text('update.unknown')))
        published = result.release.published_at.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y/%m/%d %H:%M') if result.release else ui_text('update.unknown')
        self.published_label.setText(ui_text('update.published').format(published))
        self.install_button.setVisible(result.status == 'update_available')

    def install_update(self):
        if self.property('offlinePreview') is True or self.download_timer.isActive():
            return
        if self.release is None:
            self.async_status.set_state('error', error_code='update_metadata_missing')
            return
        can_install = self.app.property('maintenanceCanInstall')
        if can_install is None or not can_install():
            self.async_status.set_state('error', error_code='update_not_installed')
            return
        release = self.release
        confirmed = QMessageBox.question(
            self,
            ui_text('update.confirm_title'),
            ui_text('update.confirm').format(release.installer_url, release.version, release.installer_sha256[:12]),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirmed != QMessageBox.Yes:
            return
        self.download_cancel.clear()
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.cleanup_button.setEnabled(False)
        self.cancel_button.show()
        self.async_status.set_state('empty', message=ui_text('update.downloading'))
        try:
            Thread(
                target=_download_in_background,
                args=(self.downloads, release, self.download_cancel, self.app.property('maintenanceDownload'), self.download_lock),
                # Complete cancellation/file cleanup after Qt's event loop exits.
                daemon=False,
            ).start()
            self.download_timer.start()
        except RuntimeError:
            self.downloads.put(DownloadResult(error_code='update_download_failed'))
            self.poll_download()

    def poll_download(self):
        if self.downloads.empty():
            return
        result = self.downloads.get_nowait()
        self.download_timer.stop()
        self.cancel_button.hide()
        self.install_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.cleanup_button.setEnabled(True)
        if result.error_code:
            if result.error_code == 'update_download_cancelled':
                self.async_status.set_state('empty', message=ui_text('update.cancelled'))
            else:
                self.async_status.set_state('error', error_code=result.error_code)
            return
        if self.download_cancel.is_set() or self.property('offlinePreview') is True:
            result.path.unlink()
            result.path.parent.rmdir()
            self.async_status.set_state('empty', message=ui_text('update.cancelled'))
            return
        errors = {code: entry.explanation + ' ' + entry.action for code, entry in ERROR_TABLE.items() if code.startswith('update_')}
        try:
            self.app.property('maintenanceQueueInstall')(result.path, self.release.installer_sha256, errors)
        except (UpdateError, OSError) as exc:
            result.path.unlink(missing_ok=True)
            result.path.parent.rmdir()
            self.async_status.set_state('error', error_code=exc.code if isinstance(exc, UpdateError) else 'update_install_start_failed')
            return
        self.async_status.set_state('empty', message=ui_text('update.ready'))
        if not self.window().close():
            self.app.property('maintenanceCancelInstall')()
            self.async_status.set_state('error', error_code='update_shutdown_failed')

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
