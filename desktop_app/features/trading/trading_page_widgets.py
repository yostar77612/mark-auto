"""Remembered column choices and actionable empty tables; no storage ownership."""

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from desktop_app.features.trading.widgets import button
from desktop_app.strings.catalog import ui_text


class PositionColumns(QObject):
    def __init__(self, table, header, saved, save, notify, *, defaults=(0, 1, 2, 5, 8, 9), name='position_columns', caption=None, hint=None):
        super().__init__(table)
        self.table, self.save, self.notify = table, save, notify
        self.selected = defaults
        if isinstance(saved, (list, tuple)) and saved and 0 in saved and all(type(value) is int and 0 <= value < table.columnCount() for value in saved):
            self.selected = tuple(sorted(set(saved)))
        self.button = button('m2t.columns', name)
        if caption is not None:
            self.button.setText(caption)
            self.button.setAccessibleName(caption)
        self.button.setToolTip(hint or ui_text('m2t.columns_hint'))
        self.menu = QMenu(self.button)
        self.actions = {}
        for column in range(table.columnCount()):
            action = QAction(table.horizontalHeaderItem(column).text(), self.menu)
            action.setCheckable(True)
            action.setEnabled(column != 0)
            action.triggered.connect(lambda checked=False, column=column: self._choose(column, checked))
            self.menu.addAction(action)
            self.actions[column] = action
        self.button.setMenu(self.menu)
        header.addWidget(self.button)
        self._render()

    def _choose(self, column, checked):
        selected = set(self.selected)
        if checked:
            selected.add(column)
        else:
            selected.discard(column)
        proposed = tuple(sorted(selected | {0}))
        try:
            if self.save is not None:
                self.save(proposed)
        except (OSError, ValueError, RuntimeError):
            self.notify(ui_text('m2t.columns_failed'))
        else:
            self.selected = proposed
        self._render()

    def _render(self):
        for column, action in self.actions.items():
            with QSignalBlocker(action):
                action.setChecked(column in self.selected)
            self.table.setColumnHidden(column, column not in self.selected)


class EmptyTableState(QWidget):
    def __init__(self, table, text, navigate):
        super().__init__(table.viewport())
        self.setObjectName(table.objectName() + '_empty')
        layout = QVBoxLayout(self)
        layout.addStretch()
        self.reason = QLabel(text, self)
        self.reason.setTextFormat(Qt.TextFormat.PlainText)
        self.reason.setWordWrap(True)
        self.reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reason.setAccessibleName(text)
        layout.addWidget(self.reason)
        self.next = button('m2t.open_strategy', table.objectName() + '_empty_next')
        self.next.clicked.connect(navigate)
        layout.addWidget(self.next, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        table.viewport().installEventFilter(self)
        self.setGeometry(table.viewport().rect())
        self.hide()

    def eventFilter(self, watched, event):
        if event.type() is QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)
