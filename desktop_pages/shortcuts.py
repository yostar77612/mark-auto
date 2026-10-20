"""Window shortcuts dispatch to existing UI handlers, including their guards."""

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton
from desktop_strings import ui_text
from .command_palette import CommandPalette


def install_shortcuts(window):
    window.command_palette = CommandPalette(window, lambda: refresh_current_page(window))
    window.palette_shortcut = QShortcut(QKeySequence('Ctrl+K'), window)
    window.palette_shortcut.activated.connect(window.command_palette.toggle)
    window.page_shortcuts = []
    for index in range(window.navigation.count()):
        shortcut = QShortcut(QKeySequence('Ctrl+' + str(index + 1)), window)
        shortcut.activated.connect(lambda row=index: window.navigation.setCurrentRow(row))
        window.page_shortcuts.append(shortcut)
        item = window.navigation.item(index)
        item.setToolTip(ui_text('keyboard.page').format(item.text(), index + 1))
    window.navigation.setToolTip(ui_text('keyboard.help'))
    window.refresh_shortcut = QShortcut(QKeySequence('F5'), window)
    window.refresh_shortcut.activated.connect(lambda: refresh_current_page(window))
    window.cancel_shortcut = QShortcut(QKeySequence('Esc'), window)
    window.cancel_shortcut.activated.connect(
        lambda: (
            window.notification_center.hide()
            if getattr(window, 'notification_center', None) is not None and not window.notification_center.isHidden()
            else window.command_palette.hide()
            if window.command_palette._opened
            else window.cancel_job()
            if window.jobs.active
            else None
        )
    )
    window.cancel_button.setToolTip(ui_text('keyboard.cancel'))
    window.market.refresh_button.setToolTip(ui_text('keyboard.refresh'))
    log_button = window.findChild(QPushButton, 'read_logs')
    if log_button is not None:
        log_button.setToolTip(ui_text('keyboard.refresh'))
    window.setWhatsThis(ui_text('keyboard.help'))


def refresh_current_page(window):
    if window.stack.currentWidget() is window.market:
        window._safe(window.refresh_market)
    elif window.stack.currentIndex() == 6:
        window._safe(window.read_logs)
    else:
        window._safe(window.refresh_views)
