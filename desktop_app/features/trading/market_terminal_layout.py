"""Terminal panel arrangement using the retained C5 panel handles and store port."""

from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QToolButton, QMenu, QInputDialog
from desktop_app.strings.catalog import ui_text

PANEL_IDS = ('quotes', 'alerts', 'chart', 'index')


def terminal_preset(name='terminal_default'):
    if name not in ('terminal_default', 'chart_focus'):
        raise ValueError('unknown terminal preset')
    return {
        'version': 1,
        'panels': {
            'quotes': {'area': 'left', 'position': 0, 'size': 600, 'collapsed': False},
            'alerts': {'area': 'left', 'position': 1, 'size': 400, 'collapsed': name == 'chart_focus'},
            'chart': {'area': 'center', 'position': 0, 'size': 700, 'collapsed': False},
            'index': {'area': 'center', 'position': 1, 'size': 300, 'collapsed': name == 'chart_focus'},
        },
    }


class TerminalWorkspace:
    preset_ids = ('terminal_default', 'chart_focus')

    def __init__(self, dashboard, contents, store, panel_factory):
        self.dashboard, self.store = dashboard, store
        self.area_labels = {'left': ui_text('workspace.left'), 'center': ui_text('workspace.center')}
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName('terminal_panels')
        self.splitter.setAccessibleName(ui_text('terminal.title'))
        self.columns = {area: QSplitter(Qt.Orientation.Vertical) for area in self.area_labels}
        for area, column in self.columns.items():
            column.setChildrenCollapsible(False)
            column.setObjectName('terminal_column_' + area)
            column.setAccessibleName(self.area_labels[area])
            self.splitter.addWidget(column)
            column.splitterMoved.connect(lambda position, index, selected=area: self._sizes_changed(selected))
        self.splitter.setSizes((400, 600))
        self.panels = {key: panel_factory(self, key, title, content) for key, (title, content) in contents.items()}
        self.button = QToolButton()
        self.button.setText(ui_text('workspace.layouts'))
        self.button.setObjectName('terminal_layouts')
        self.button.setAccessibleName(ui_text('workspace.layouts'))
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.button)
        self.button.setMenu(self.menu)
        self.actions = {}
        for key, text in (('terminal_default', ui_text('terminal.default')), ('chart_focus', ui_text('workspace.chart_focus'))):
            self.actions[key] = self.menu.addAction(text, lambda checked=False, selected=key: self.apply_preset(selected))
        self.actions['save'] = self.menu.addAction(ui_text('workspace.save'), self._save_dialog)
        self.restore_menu = self.menu.addMenu(ui_text('workspace.restore'))
        self.delete_menu = self.menu.addMenu(ui_text('workspace.delete'))
        self.actions['reset'] = self.menu.addAction(ui_text('workspace.reset'), self.reset)
        self.apply_layout(store.current)
        self._named_menus()

    def serialize(self):
        return deepcopy(self._state)

    def apply_layout(self, value):
        self._state = deepcopy(value)
        for panel in self.panels.values():
            panel.setParent(self.dashboard)
        for area, column in self.columns.items():
            keys = sorted((key for key in PANEL_IDS if value['panels'][key]['area'] == area), key=lambda key: value['panels'][key]['position'])
            for key in keys:
                panel = self.panels[key]
                column.addWidget(panel)
                self.collapse(key, value['panels'][key]['collapsed'])
                panel.show()
            column.setSizes([value['panels'][key]['size'] if not value['panels'][key]['collapsed'] else 30 for key in keys])

    def _sizes_changed(self, area):
        column = self.columns[area]
        for index, size in enumerate(column.sizes()):
            key = column.widget(index).panel_id
            if not self._state['panels'][key]['collapsed']:
                self._state['panels'][key]['size'] = max(80, size)

    def apply_preset(self, name):
        self.apply_layout(terminal_preset(name))

    def reset(self):
        self.apply_preset('terminal_default')

    def move_panel(self, panel_id, area, position=0):
        if panel_id not in self.panels or area not in self.columns:
            return False
        state = self.serialize()
        peers = sorted((key for key in PANEL_IDS if key != panel_id and state['panels'][key]['area'] == area), key=lambda key: state['panels'][key]['position'])
        peers.insert(position, panel_id)
        for index, key in enumerate(peers):
            state['panels'][key].update(area=area, position=index)
        self.apply_layout(state)
        return True

    def reorder(self, panel_id, step):
        item = self._state['panels'][panel_id]
        return self.move_panel(panel_id, item['area'], max(0, item['position'] + step))

    def collapse(self, panel_id, collapsed=True):
        self._state['panels'][panel_id]['collapsed'] = collapsed
        panel = self.panels[panel_id]
        panel.content.setVisible(not collapsed)
        panel.actions['collapse'].setChecked(collapsed)
        panel.setMaximumHeight(panel.handle.sizeHint().height() + 4 if collapsed else 16777215)
        panel.handle.setText(ui_text('workspace.collapsed').format(panel.handle.accessibleName()) if collapsed else panel.handle.accessibleName())
        return True

    def _commit(self, layouts):
        try:
            self.store.save(layouts, self.serialize())
        except (OSError, ValueError):
            self.dashboard.show_message(ui_text('watch.request_error'))
            return False
        self._named_menus()
        return True

    def save_named(self, name):
        # Names are metadata keys in one JSON file, never paths.
        if not name or name != name.strip() or len(name) > 64 or any(c in name for c in '/\\:'):
            return False
        if name not in self.store.layouts and len(self.store.layouts) >= 20:
            return False
        layouts = deepcopy(self.store.layouts)
        layouts[name] = self.serialize()
        return self._commit(layouts)

    def restore_named(self, name):
        value = self.store.layouts.get(name)
        self.apply_layout(value if value is not None else terminal_preset())
        return value is not None

    def delete_named(self, name):
        if name not in self.store.layouts:
            return False
        layouts = deepcopy(self.store.layouts)
        del layouts[name]
        return self._commit(layouts)

    def _save_dialog(self):
        name, accepted = QInputDialog.getText(self.dashboard, ui_text('workspace.save'), ui_text('workspace.name'))
        if accepted:
            self.save_named(name)

    def _named_menus(self):
        self.restore_menu.clear()
        self.delete_menu.clear()
        for name in self.store.layouts:
            self.restore_menu.addAction(name, lambda checked=False, selected=name: self.restore_named(selected))
            self.delete_menu.addAction(name, lambda checked=False, selected=name: self.delete_named(selected))
