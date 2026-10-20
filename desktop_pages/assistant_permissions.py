"""Two synchronized research menus; persisted preferences never grant authority."""

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QLabel

from desktop_strings import ui_text
from quantlab.errors import ERROR_TABLE


logger = logging.getLogger(__name__)
MODES = ('read_only', 'confirm_each_time')
SETTING_KEY = 'assistant_research_permission'


class ResearchPermission(QObject):
    changed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        # Deliberately never restore elevated session intent, including valid
        # saved confirm_each_time, unknown values, or corrupt settings.
        self.mode = 'read_only'
        self.error = False

    def select(self, value):
        mode = value if type(value) is str and value in MODES else 'read_only'
        if mode == self.mode:
            return
        self.mode = 'read_only'
        self.error = False
        load = getattr(self.settings, 'load', None)
        save = getattr(self.settings, 'save', None)
        try:
            if callable(load) and callable(save):
                saved = load()
                if type(saved) is not dict:
                    raise ValueError
                save({**saved, SETTING_KEY: mode})
            self.mode = mode
        except Exception:
            # No exception strings or rejected setting values enter diagnostics.
            self.error = True
        logger.info('assistant_permission_changed mode=%s', self.mode)
        self.changed.emit()


def install_menu(layout, state, name):
    label = QLabel(ui_text('assistant.permission_label'))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    layout.addWidget(label)
    menu = QComboBox()
    menu.setObjectName(name)
    menu.addItem(ui_text('assistant.permission_read'), 'read_only')
    menu.addItem(ui_text('assistant.permission_confirm'), 'confirm_each_time')
    menu.setAccessibleName(ui_text('assistant.permission_label'))
    menu.setAccessibleDescription(ui_text('assistant.permission_scope'))
    label.setBuddy(menu)
    layout.addWidget(menu)
    scope = QLabel(ui_text('assistant.permission_scope'))
    scope.setTextFormat(Qt.TextFormat.PlainText)
    scope.setWordWrap(True)
    layout.addWidget(scope)

    def refresh():
        menu.blockSignals(True)
        menu.setCurrentIndex(menu.findData(state.mode))
        menu.blockSignals(False)
        scope.setText(ERROR_TABLE['agent_tool_refused'].explanation if state.error else ui_text('assistant.permission_scope'))

    menu.currentIndexChanged.connect(lambda: state.select(menu.currentData()))
    state.changed.connect(refresh)
    refresh()
    return menu
