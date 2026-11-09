"""Concept group editor dialog. Every action is one engine command; the engine validates and persists."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from desktop_app.features.trading.market_terminal_search import SymbolSearch
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.sector_contracts import SectorGroupsCommand


def group_label(group) -> str:
    marks = []
    if group.builtin:
        marks.append(ui_text('sector.builtin_mark'))
    if group.builtin and group.edited:
        marks.append(ui_text('sector.edited_mark'))
    if group.deleted:
        marks.append(ui_text('sector.deleted_mark'))
    return group.name + (' · ' + ' '.join(marks) if marks else '')


class SectorEditor(QDialog):
    def __init__(self, facade, directory, submit, parent=None, on_changed=lambda: None):
        super().__init__(parent)
        self.facade, self.submit, self.on_changed = facade, submit, on_changed
        self.directory = {item.code: item for item in directory}
        self.view = None
        self.setObjectName('sector_editor')
        self.setWindowTitle(ui_text('sector.editor_title'))
        self.setAccessibleName(ui_text('sector.editor_title'))
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(self._title(ui_text('sector.editor_groups')))
        self.groups = QListWidget()
        self.groups.setObjectName('sector_editor_groups')
        self.groups.setAccessibleName(ui_text('sector.editor_groups'))
        self.groups.currentItemChanged.connect(lambda current, previous: self._show_members())
        left.addWidget(self.groups, 1)
        buttons = QHBoxLayout()
        self.add_button = self._button('sector_editor_add', 'sector.add', self.add_group)
        self.rename_button = self._button('sector_editor_rename', 'sector.rename', self.rename_group)
        self.delete_button = self._button('sector_editor_delete', 'sector.delete', self.delete_group)
        self.restore_button = self._button('sector_editor_restore', 'sector.restore', self.restore_group)
        for button in (self.add_button, self.rename_button, self.delete_button, self.restore_button):
            buttons.addWidget(button)
        left.addLayout(buttons)
        right.addWidget(self._title(ui_text('sector.editor_members')))
        self.members = QListWidget()
        self.members.setObjectName('sector_editor_members')
        self.members.setAccessibleName(ui_text('sector.editor_members'))
        self.members.currentItemChanged.connect(lambda current, previous: self._update_buttons())
        right.addWidget(self.members, 1)
        self.search = SymbolSearch(lambda: tuple(self.directory.values()), self.add_code)
        self.search.setObjectName('sector_editor_search')
        right.addWidget(self.search)
        self.remove_button = self._button('sector_editor_remove_code', 'sector.remove_code', self.remove_code)
        right.addWidget(self.remove_button)
        body.addLayout(left, 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        self.message = QLabel()
        self.message.setObjectName('sector_editor_message')
        self.message.setAccessibleName(ui_text('sector.editor_title'))
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.message)
        close = self._button('sector_editor_close', 'sector.close', self.accept)
        root.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(720, 480)
        self.send_command(SectorGroupsCommand())

    def _title(self, text):
        label = QLabel(text)
        label.setAccessibleName(text)
        return label

    def _button(self, name, key, slot):
        button = QPushButton(ui_text(key))
        button.setObjectName(name)
        button.setAccessibleName(ui_text(key))
        button.clicked.connect(lambda checked=False: slot())
        return button

    # --- engine round trip ---------------------------------------------
    def send_command(self, command):
        def completed(value, error):
            if error is not None:
                self.message.setText(ui_text('sector.editor_failed'))
                return
            self.message.setText('')
            self.apply(value)
            if command.action != 'LIST':
                self.on_changed()

        self.submit(lambda: self.facade.sector_groups(command), completed)

    def apply(self, view):
        selected = view.selected_id or (self.current_group().id if self.current_group() else '')
        self.view = view
        self.groups.blockSignals(True)
        self.groups.clear()
        for group in view.groups:
            item = QListWidgetItem(group_label(group))
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            if group.deleted:
                item.setForeground(QColor('#808080'))
            self.groups.addItem(item)
            if group.id == selected:
                self.groups.setCurrentItem(item)
        if self.groups.currentItem() is None and self.groups.count():
            self.groups.setCurrentRow(0)
        self.groups.blockSignals(False)
        if view.warning:
            self.message.setText(
                ui_text('sector.store_' + view.warning)
                if view.warning in ('sector_groups_corrupt', 'sector_groups_unwritable', 'sector_groups_unreadable')
                else ''
            )
        self._show_members()

    def current_group(self):
        item = self.groups.currentItem()
        if item is None or self.view is None:
            return None
        return next((group for group in self.view.groups if group.id == item.data(Qt.ItemDataRole.UserRole)), None)

    def _show_members(self):
        group = self.current_group()
        self.members.clear()
        if group is not None:
            for code in group.codes:
                instrument = self.directory.get(code)
                missing = code in group.unknown_codes
                item = QListWidgetItem(f'{code} {instrument.name if instrument else ""}'.strip() + (' · ' + ui_text('sector.missing_code') if missing else ''))
                item.setData(Qt.ItemDataRole.UserRole, code)
                if missing:
                    item.setForeground(QColor('#c62828'))
                    item.setToolTip(ui_text('sector.missing_code'))
                self.members.addItem(item)
        self._update_buttons()

    def _update_buttons(self):
        group = self.current_group()
        live = group is not None and not group.deleted
        self.rename_button.setEnabled(live)
        self.delete_button.setEnabled(live)
        self.restore_button.setEnabled(group is not None and group.builtin and (group.edited or group.deleted))
        self.remove_button.setEnabled(live and self.members.currentItem() is not None)
        self.search.setEnabled(live)

    # --- actions ---------------------------------------------------------------
    def add_group(self):
        name, accepted = QInputDialog.getText(self, ui_text('sector.add'), ui_text('sector.name_prompt'))
        if accepted and name.strip():
            self.send_command(SectorGroupsCommand('CREATE', name=name))

    def rename_group(self):
        group = self.current_group()
        if group is None:
            return
        name, accepted = QInputDialog.getText(self, ui_text('sector.rename'), ui_text('sector.name_prompt'), text=group.name)
        if accepted and name.strip() and name.strip() != group.name:
            self.send_command(SectorGroupsCommand('RENAME', group.id, name))

    def delete_group(self):
        group = self.current_group()
        if group is None:
            return
        answer = QMessageBox.question(self, ui_text('sector.delete'), ui_text('sector.delete_confirm').format(group.name))
        if answer == QMessageBox.StandardButton.Yes:
            self.send_command(SectorGroupsCommand('DELETE', group.id))

    def restore_group(self):
        group = self.current_group()
        if group is not None:
            self.send_command(SectorGroupsCommand('RESTORE', group.id))

    def add_code(self, instrument_id):
        group = self.current_group()
        code = instrument_id.split(':')[-1]
        if group is None or group.deleted or code in group.codes:
            return
        self.send_command(SectorGroupsCommand('SET_CODES', group.id, codes=(*group.codes, code)))

    def remove_code(self):
        group, item = self.current_group(), self.members.currentItem()
        if group is None or item is None:
            return
        code = item.data(Qt.ItemDataRole.UserRole)
        self.send_command(SectorGroupsCommand('SET_CODES', group.id, codes=tuple(value for value in group.codes if value != code)))
