"""Reusable keyboard popup dispatching only existing local UI actions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from desktop_app.shell.palette_commands import command_row, command_table


class _Filter(QLineEdit):
    def __init__(self, palette):
        super().__init__(palette)
        self.palette = palette

    def keyPressEvent(self, event):
        if not self.palette.handle_key(event):
            super().keyPressEvent(event)


class _Results(QListWidget):
    def __init__(self, palette):
        super().__init__(palette)
        self.palette = palette

    def keyPressEvent(self, event):
        if not self.palette.handle_key(event):
            super().keyPressEvent(event)


class CommandPalette(QWidget):
    def __init__(self, host, refresh=None):
        super().__init__(host if isinstance(host, QWidget) else None, Qt.WindowType.Popup)
        self.host = host
        self.refresh = refresh
        self._opened = False
        self._previous = None
        self.setObjectName('command_palette')
        self.setAccessibleName(ui_text('palette.title'))
        self.setWindowTitle(ui_text('palette.title'))
        layout = QVBoxLayout(self)
        self.filter = _Filter(self)
        self.filter.setObjectName('palette_filter')
        self.filter.setAccessibleName(ui_text('palette.placeholder'))
        self.filter.setPlaceholderText(ui_text('palette.placeholder'))
        self.results = _Results(self)
        self.results.setObjectName('palette_results')
        self.results.setAccessibleName(ui_text('palette.results'))
        self.hint = QLabel(ui_text('palette.hint'), self)
        self.hint.setObjectName('palette_hint')
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setAccessibleName(ui_text('palette.hint'))
        for widget in (self.filter, self.results, self.hint):
            layout.addWidget(widget)
        QWidget.setTabOrder(self.filter, self.results)
        QWidget.setTabOrder(self.results, self.filter)
        self.filter.textChanged.connect(self.populate)
        self.resize(560, 360)
        self.populate()

    def target(self, command):
        navigation = getattr(self.host, 'navigation', None)
        if command.handler == 'navigate':
            return navigation.setCurrentRow if navigation is not None and 0 <= command_row(self.host, command) < navigation.count() else None
        if command.handler == 'refresh':
            return self.refresh
        if command.handler == 'cancel_job':
            return getattr(self.host, 'cancel_job', None)
        if command.handler == 'theme':
            combo = getattr(getattr(self.host, 'app_header', None), 'theme', None)
            return combo.setCurrentIndex if combo is not None and combo.count() > 1 else None
        if command.handler == 'privacy':
            toggle = getattr(getattr(self.host, 'privacy', None), 'toggle', None)
            return toggle.toggle if toggle is not None else None
        if command.handler in ('focus_import', 'focus_backtest') and navigation is not None and 0 <= command_row(self.host, command) < navigation.count():
            button = self.focus_button(command)
            return button.setFocus if button is not None else None
        return None

    def focus_button(self, command):
        finder = getattr(self.host, 'findChild', None)
        return finder(QPushButton, 'import_data' if command.handler == 'focus_import' else 'run_backtest') if callable(finder) else None

    def available(self, command):
        if command.handler == 'cancel_job':
            return bool(getattr(getattr(self.host, 'jobs', None), 'active', False))
        if command.handler in ('focus_import', 'focus_backtest'):
            button = self.focus_button(command)
            return button is not None and button.isEnabled()
        if command.handler == 'theme':
            return self.host.app_header.theme.isEnabled()
        if command.handler == 'privacy':
            return self.host.privacy.toggle.isEnabled()
        return True

    def commands(self):
        return tuple(command for command in command_table() if callable(self.target(command)))

    def populate(self):
        self.results.clear()
        query = self.filter.text().casefold()
        for command in self.commands():
            if query not in command.label.casefold() and query not in command.alias.casefold():
                continue
            text = command.label
            if command.handler == 'navigate':
                text = ui_text('keyboard.page').format(text, command_row(self.host, command) + 1)
            elif command.handler == 'refresh':
                text = ui_text('keyboard.refresh')
            elif command.handler == 'cancel_job':
                text = ui_text('keyboard.cancel')
            available = self.available(command)
            if not available:
                reason = ui_text('palette.unavailable') if command.handler == 'cancel_job' else ui_text('palette.prerequisite')
                text = reason.format(text)
            item = QListWidgetItem(text, self.results)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            item.setData(Qt.ItemDataRole.UserRole, command)
            if not available:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
        if not self.results.count():
            item = QListWidgetItem(ui_text('palette.empty'), self.results)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, ui_text('palette.empty'))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.results.setCurrentRow(row)
                break

    def toggle(self):
        if self._opened:
            self.hide()
            return
        self._previous = QApplication.focusWidget()
        if self._previous is None and isinstance(self.host, QWidget):
            self._previous = self.host.focusWidget()
        self.filter.clear()
        self.populate()
        self._opened = True
        self.show()
        self.filter.setFocus()

    def hideEvent(self, event):
        self._opened = False
        previous, self._previous = self._previous, None
        if previous is not None:
            try:
                previous.setFocus()
            except RuntimeError:  # The original control may have been destroyed independently.
                pass
        super().hideEvent(event)

    def execute(self):
        item = self.results.currentItem()
        if not self._opened or item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        command = item.data(Qt.ItemDataRole.UserRole)
        target = self.target(command) if command is not None else None
        if not callable(target) or not self.available(command):
            return
        self.hide()  # Close before dispatch: repeated Enter cannot execute twice.
        if command.handler == 'navigate':
            target(command_row(self.host, command))
        elif command.handler == 'theme':
            combo = self.host.app_header.theme
            target((combo.currentIndex() + 1) % combo.count())
        elif command.handler in ('focus_import', 'focus_backtest'):
            self.host.navigation.setCurrentRow(command_row(self.host, command))
            page = getattr(self.host, 'data_page', None)
            if command.handler == 'focus_import' and page is not None:
                page.sources.setCurrentIndex(0)
            if command.handler == 'focus_backtest':
                page = getattr(self.host, 'backtest_page', None)
                if page is not None:
                    page.setup_toggle.setChecked(True)
            target()
            scroll = self.host.stack.currentWidget()
            ensure = getattr(scroll, 'ensureWidgetVisible', None)
            if callable(ensure):
                button = self.host.findChild(QPushButton, 'import_data' if command.handler == 'focus_import' else 'run_backtest')
                if button is not None:
                    ensure(button)
        else:
            target()

    def handle_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape or (key == Qt.Key.Key_K and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.hide()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.execute()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 1 if key == Qt.Key.Key_Down else -1
            row = self.results.currentRow() + step
            while 0 <= row < self.results.count():
                if self.results.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                    self.results.setCurrentRow(row)
                    break
                row += step
        else:
            return False
        event.accept()
        return True

    def keyPressEvent(self, event):
        if not self.handle_key(event):
            super().keyPressEvent(event)
