"""Window-owned, nonmodal notification center and reusable bottom toast slots."""

from html import escape
import re

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from desktop_strings import ui_text
from desktop_theme import set_status
from desktop_pages.app_header import _CloseWatcher
from desktop_pages.notification_log import KINDS, SEVERITIES, NotificationLog, safe_summary


class Toast(QLabel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.entry = None
        self.setWordWrap(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.expire)
        self.linkActivated.connect(self.follow_link)
        self.hide()

    def present(self, entry):
        self.timer.stop()
        self.entry = entry
        self.setText(ui_text('ui.notify_local.text_1').format(escape(entry.message)))
        self.setAccessibleName(entry.message)
        set_status(self, 'danger' if entry.severity == 'error' else 'neutral')
        self.show()
        if self.isVisible() and entry.severity != 'error':
            self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self.entry is not None and self.entry.severity != 'error':
            self.timer.start()

    def expire(self):
        if not self.isHidden() and self.entry is not None and self.entry.severity != 'error':
            self.hide()

    def follow_link(self, link):
        if link == 'close':
            self.hide()
        elif link == 'result' and self.entry is not None:
            self.owner.navigate(self.entry)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


class EntryList(QListWidget):
    def __init__(self, center):
        super().__init__(center)
        self.center = center

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.center.open_selected()
        elif event.key() == Qt.Key.Key_Delete:
            self.center.dismiss_selected()
        elif event.key() == Qt.Key.Key_Escape:
            self.center.hide()
        else:
            super().keyPressEvent(event)


class NotificationCenter(QWidget):
    def __init__(self, host, parent=None, *, toast_limit=3):
        super().__init__(parent)
        self.host = host
        self.log = NotificationLog()
        self.in_event = False
        self.rebuild_count = 0
        self.setObjectName('notification_center')
        self.setAccessibleName(ui_text('notifications.title'))
        self.button = QPushButton(self)
        self.button.setObjectName('notification_button')
        self.button.clicked.connect(self.open_center)
        self.rows = EntryList(self)
        self.rows.setObjectName('notification_entries')
        self.rows.setAccessibleName(ui_text('notifications.title'))
        self.rows.itemDoubleClicked.connect(lambda _: self.open_selected())
        layout = QVBoxLayout(self)
        layout.addWidget(self.rows)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        for text, name, callback in (
            (ui_text('notifications.open'), 'notification_open', self.open_selected),
            (ui_text('notifications.dismiss'), 'notification_dismiss', self.dismiss_selected),
            (ui_text('notifications.clear'), 'notification_clear', self.clear_all),
            (ui_text('notifications.close'), 'notification_close', self.hide),
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setAccessibleName(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        self.toasts = [Toast(self) for _ in range(toast_limit)]
        self.shortcuts = []
        if isinstance(host, QWidget):
            for key, callback in (('Ctrl+Shift+N', self.open_center), ('Ctrl+Shift+D', self.dismiss_toasts)):
                shortcut = QShortcut(QKeySequence(key), host)
                shortcut.activated.connect(callback)
                self.shortcuts.append(shortcut)
            self._close_watcher = _CloseWatcher(host, self.shutdown)
        self.update_badge()
        self.hide()

    def update_badge(self):
        text = ui_text('notifications.badge').format(self.log.unread_count)
        self.button.setText(text)
        self.button.setAccessibleName(text)

    def record_event(self, event):
        self.in_event = True
        feedback = getattr(self.host, 'job_feedback', None)
        code = getattr(feedback, 'campaign_code', None)
        if code is not None and event.get('type') in ('result', 'completed', 'success') and feedback.result_failed(event.get('result', {})):
            event = {**event, 'type': 'failed', 'error_code': code}
        entry = self.log.accept_event(getattr(self.host, 'last_operation', ''), event)
        if entry is not None:
            self.publish(entry, completion=True)
        return entry

    def notify_local(self, message, *, error=False, completion=False):
        if self.in_event:
            return
        operation = getattr(self.host, 'last_operation', '')
        # Preserve the old synthetic-demo compatibility message without accepting arbitrary payload text.
        match = re.fullmatch(re.escape(safe_summary('ui_demo', {'bars': 0})).replace('0', r'(\d{1,8})'), message) if type(message) is str else None
        if completion and operation == 'ui_demo' and match:
            entry = self.log.accept_event(operation, {'type': 'result', 'job_id': -self.log.sequence - 1, 'result': {'bars': int(match[1])}})
        else:
            entry = self.log.append(operation=operation, error=error, message=message)
        if entry is not None:
            self.publish(entry, completion=completion)

    def publish(self, entry, *, completion=False):
        self.update_badge()
        if not self.isHidden():
            self.rebuild()
        toggle = getattr(self.host, 'local_notifications', None)
        enabled = toggle is None or toggle.isChecked()
        if not enabled and not completion and entry.severity != 'error':
            return
        slot = next((toast for toast in self.toasts if toast.isHidden()), None)
        if slot is not None:
            slot.present(entry)

    def rebuild(self):
        self.rows.clear()
        self.rebuild_count = 0
        for entry in reversed(self.log.entries):
            self.rebuild_count += 1
            text = ui_text('notifications.row').format(entry.time, KINDS[entry.kind], SEVERITIES[entry.severity], entry.message)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            self.rows.addItem(item)
        if self.rows.count():
            self.rows.setCurrentRow(0)

    def open_center(self):
        self.log.mark_viewed()
        self.update_badge()
        self.rebuild()
        self.show()
        self.rows.setFocus()

    def selected(self):
        item = self.rows.currentItem()
        return next((entry for entry in self.log.entries if item is not None and entry.id == item.data(Qt.ItemDataRole.UserRole)), None)

    def open_selected(self):
        entry = self.selected()
        if entry is not None:
            self.navigate(entry)

    def navigate(self, entry):
        self.host._notification_operation = entry.operation
        callback = getattr(self.host, '_notification_link', None)
        if callable(callback):
            callback('result')

    def dismiss_selected(self):
        entry = self.selected()
        if entry is not None:
            self.log.dismiss(entry.id)
            for toast in self.toasts:
                if toast.entry is not None and toast.entry.id == entry.id:
                    toast.hide()
            self.rebuild()
            self.update_badge()

    def clear_all(self):
        self.log.clear()
        self.dismiss_toasts()
        self.rebuild()
        self.update_badge()

    def dismiss_toasts(self):
        close_banner(self.host)
        for toast in self.toasts:
            toast.hide()
            toast.timer.stop()

    def shutdown(self):
        self.dismiss_toasts()
        close_banner(self.host)
        self.hide()


def install_notifications(shell, layout):
    # Keep the historical banner independent of the sanitized notification log.
    banner = QLabel('')
    banner.setObjectName('local_notification')
    banner.setWordWrap(True)
    banner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    banner.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    banner.setTextFormat(Qt.TextFormat.RichText)
    callback = getattr(shell, '_notification_link', None)
    if callable(callback):
        banner.linkActivated.connect(callback)
    banner.hide()
    layout.addWidget(banner)
    shell.notification = banner
    shell.notification_timer = QTimer(shell)
    shell.notification_timer.setSingleShot(True)
    shell.notification_opacity = QGraphicsOpacityEffect(banner)
    banner.setGraphicsEffect(shell.notification_opacity)
    shell.notification_fade = QPropertyAnimation(shell.notification_opacity, b'opacity', shell)
    shell.notification_fade.setDuration(300)
    shell.notification_fade.setStartValue(1.0)
    shell.notification_fade.setEndValue(0.0)
    shell.notification_fade.finished.connect(banner.hide)
    shell.notification_timer.timeout.connect(shell.notification_fade.start)
    center = NotificationCenter(shell, shell, toast_limit=2)
    shell.notification_center = center
    shell.app_header.layout().insertWidget(shell.app_header.layout().count() - 1, center.button)
    for toast in center.toasts:
        layout.addWidget(toast)
    layout.addWidget(center)


def begin_event(host):
    center = getattr(host, 'notification_center', None)
    if center is not None:
        center.in_event = True


def record_event(host, event):
    center = getattr(host, 'notification_center', None)
    if center is not None:
        center.record_event(event)


def end_event(host):
    center = getattr(host, 'notification_center', None)
    if center is not None:
        center.in_event = False


def close_banner(host):
    for name in ('notification_timer', 'notification_fade'):
        timer = getattr(host, name, None)
        if timer is not None:
            timer.stop()
    banner = getattr(host, 'notification', None)
    if banner is not None:
        banner.hide()


def notify_local(host, message, *, error=False, completion=False):
    center = getattr(host, 'notification_center', None)
    if center is not None:
        center.notify_local(message, error=error, completion=completion)
    toggle = getattr(host, 'local_notifications', None)
    enabled = toggle is None or toggle.isChecked()
    banner = getattr(host, 'notification', None)
    if banner is None or (not completion and not enabled):
        return
    close_banner(host)
    opacity = getattr(host, 'notification_opacity', None)
    if opacity is not None:
        opacity.setOpacity(1.0)
    host._notification_operation = getattr(host, 'last_operation', None)
    # Existing callers supply presentation text; never stringify exceptions.
    text = message if type(message) is str else ui_text('notifications.error')
    banner.setText(ui_text('ui.notify_local.text_1').format(escape(text)))
    set_status(banner, 'danger' if error else 'neutral')
    banner.show()
    timer = getattr(host, 'notification_timer', None)
    if not error and timer is not None:
        timer.start(5000)
    if enabled and isinstance(host, QWidget):
        QApplication.alert(host, 1500)
