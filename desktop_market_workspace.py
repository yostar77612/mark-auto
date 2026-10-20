"""Movable, collapsible display panels with a keyboard-equivalent drag API.

Owns layout metadata only. Retained content is never rebuilt or deleted.
"""

from copy import deepcopy
from PySide6.QtCore import Qt, QMimeData, QEvent
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton, QMenu, QInputDialog, QLabel
from desktop_strings import ui_text
from quantlab.desktop_errors import error_message
from desktop_market_layout import PANEL_IDS, AREAS, MAX_LAYOUTS, LayoutStore, preset, valid_name, validate_layout

MIME = 'application/x-markauto-market-panel'


def _button(text, name):
    button = QToolButton()
    button.setText(text)
    button.setObjectName(name)
    button.setAccessibleName(text)
    button.setAccessibleDescription(ui_text('workspace.keyboard_hint'))
    button.setToolTip(ui_text('workspace.keyboard_hint'))
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return button


class PanelHandle(QToolButton):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.origin = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_C:
            self.panel.actions['collapse'].trigger()
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self.showMenu()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton and (event.position().toPoint() - self.origin).manhattanLength() > 10:
            mime = QMimeData()
            mime.setData(MIME, self.panel.panel_id.encode('ascii'))
            drag = QDrag(self)
            drag.setMimeData(mime)
            self.origin = None
            # Qt's modal drag loop; no layout value is executable input.
            drag.exec_(Qt.DropAction.MoveAction)
        else:
            super().mouseMoveEvent(event)


class WorkspacePanel(QWidget):
    def __init__(self, workspace, panel_id, title, content):
        super().__init__(workspace.dashboard)
        self.workspace = workspace
        self.panel_id = panel_id
        self.content = content
        self.setObjectName('market_dock_' + panel_id)
        self.setProperty('panelId', panel_id)
        self.setProperty('themePart', 'panelCard')
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.handle = PanelHandle(self)
        self.handle.setObjectName('market_dock_' + panel_id + '_handle')
        self.handle.setText(title)
        self.handle.setAccessibleName(title)
        self.handle.setAccessibleDescription(ui_text('workspace.keyboard_hint'))
        self.handle.setToolTip(ui_text('workspace.keyboard_hint'))
        self.handle.setProperty('themePart', 'panelTitleBar')
        self.handle.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.handle)
        self.handle.setMenu(menu)
        self.actions = {}
        collapse = QAction(ui_text('workspace.collapse'), menu)
        collapse.setCheckable(True)
        collapse.triggered.connect(lambda checked: workspace.collapse(panel_id, checked))
        menu.addAction(collapse)
        self.actions['collapse'] = collapse
        self.handle.clicked.connect(collapse.trigger)
        for area, label in workspace.area_labels.items():
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, a=area: workspace.move_panel(panel_id, a))
            self.actions['move_' + area] = action
        for key, label, step in [('earlier', ui_text('workspace.earlier'), -1), ('later', ui_text('workspace.later'), 1)]:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, s=step: workspace.reorder(panel_id, s))
            self.actions[key] = action
        layout.addWidget(self.handle)
        layout.addWidget(content, 1)
        if panel_id == 'watchlist':
            content.setMinimumWidth(content.sizeHint().width())
            self.setMinimumWidth(self.minimumSizeHint().width())

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self.panel_id == 'watchlist':
            # Button minimum hints permit compression below their text size.
            # Keep the content's preferred width as a splitter constraint, and
            # recompute it through Qt's hint API as fonts/themes change.
            hint.setWidth(max(hint.width(), self.content.sizeHint().width()))
        return hint

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and getattr(self, 'panel_id', None) == 'watchlist':
            self.content.setMinimumWidth(self.content.sizeHint().width())
            self.setMinimumWidth(self.minimumSizeHint().width())
        return result

    def dragEnterEvent(self, event):
        if event.source() in [panel.handle for panel in self.workspace.panels.values()] and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() in [panel.handle for panel in self.workspace.panels.values()]:
            panel_id = bytes(event.mimeData().data(MIME)).decode('ascii', errors='ignore')
            if panel_id in PANEL_IDS:
                target = self.workspace.serialize()['panels'][self.panel_id]
                self.workspace.move_panel(panel_id, target['area'], target['position'])
                event.acceptProposedAction()


class MarketWorkspace:
    preset_ids = ('overview', 'chart_focus', 'watchlist_focus')

    def __init__(self, dashboard, root, header, cards, watchlist, chart):
        self.dashboard = dashboard
        self.splitter = dashboard.main_splitter
        self.side = dashboard.right_panel
        self.store = LayoutStore()
        self._applying = False
        self.area_labels = {
            'top': ui_text('workspace.top'),
            'left': ui_text('workspace.left'),
            'center': ui_text('workspace.center'),
            'right': ui_text('workspace.right'),
            'bottom': ui_text('workspace.bottom'),
        }
        # Retain existing top-card position and horizontal splitter semantics.
        self.top = QWidget()
        self.top_layout = QVBoxLayout(self.top)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        root.replaceWidget(cards, self.top)
        self.bottom = QWidget()
        self.bottom_layout = QVBoxLayout(self.bottom)
        self.bottom_layout.setContentsMargins(0, 0, 0, 0)
        root.insertWidget(root.indexOf(self.splitter) + 1, self.bottom)
        self.panels = {
            'cards': WorkspacePanel(self, 'cards', ui_text('workspace.cards'), cards),
            'watchlist': WorkspacePanel(self, 'watchlist', ui_text('workspace.watchlist'), watchlist),
            'chart': WorkspacePanel(self, 'chart', ui_text('workspace.chart'), chart),
        }
        self.button = _button(ui_text('workspace.layouts'), 'market_layouts')
        header.insertWidget(2, self.button)
        self.menu = QMenu(self.button)
        self.button.setMenu(self.menu)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.actions = {}
        presets = self.menu.addMenu(ui_text('workspace.apply'))
        for key, label in [
            ('overview', ui_text('workspace.overview')),
            ('chart_focus', ui_text('workspace.chart_focus')),
            ('watchlist_focus', ui_text('workspace.watchlist_focus')),
        ]:
            action = presets.addAction(label)
            action.triggered.connect(lambda checked=False, p=key: self.apply_preset(p))
            self.actions[key] = action
        self.actions['save'] = self.menu.addAction(ui_text('workspace.save'), self._save_dialog)
        self.restore_menu = self.menu.addMenu(ui_text('workspace.restore'))
        self.delete_menu = self.menu.addMenu(ui_text('workspace.delete'))
        self.actions['reset'] = self.menu.addAction(ui_text('workspace.reset'), self.reset)
        for panel in self.panels.values():
            self.menu.addMenu(panel.handle.menu()).setText(panel.handle.text())
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setAccessibleName(ui_text('workspace.error'))
        self.error.hide()
        root.insertWidget(1, self.error)
        self.apply_layout(preset('overview'))
        self.splitter.splitterMoved.connect(self._sizes_changed)

    def configure_store(self, directory=None):
        """Called once at page mount; bare dashboards use in-memory defaults."""
        self.store = LayoutStore(directory)
        self.apply_layout(self.store.current)
        self._named_menus()

    def serialize(self):
        return deepcopy(self._state)

    def apply_layout(self, value):
        state = validate_layout(value) or preset('overview')
        if getattr(self, '_state', None) == state:
            return
        self._applying = True
        try:
            self._state = state
            ordered = sorted(PANEL_IDS, key=lambda key: (AREAS.index(state['panels'][key]['area']), state['panels'][key]['position'], PANEL_IDS.index(key)))
            for panel in self.panels.values():
                panel.setParent(self.dashboard)
            horizontal = []
            for key in ordered:
                panel = self.panels[key]
                item = state['panels'][key]
                if item['area'] == 'top':
                    self.top_layout.addWidget(panel)
                elif item['area'] == 'bottom':
                    self.bottom_layout.addWidget(panel)
                else:
                    self.splitter.insertWidget(len(horizontal), panel)
                    horizontal.append(key)
                panel.content.setVisible(not item['collapsed'])
                panel.actions['collapse'].setChecked(item['collapsed'])
                panel.handle.setText(
                    ui_text('workspace.collapsed').format(panel.handle.accessibleName()) if item['collapsed'] else panel.handle.accessibleName()
                )
                panel.show()
            self._horizontal = horizontal
            self.splitter.setSizes([state['panels'][key]['size'] for key in horizontal] + [230])
            for index in range(self.splitter.count()):
                self.splitter.setCollapsible(index, False)
            self.top.setVisible(self.top_layout.count() > 0)
            self.bottom.setVisible(self.bottom_layout.count() > 0)
        finally:
            self._applying = False

    def _sizes_changed(self, position, index):
        if not self._applying:
            for key, size in zip(self._horizontal, self.splitter.sizes()):
                self._state['panels'][key]['size'] = max(80, min(2000, size))

    def apply_preset(self, preset_id):
        self.apply_layout(preset(preset_id))

    def reset(self):
        self.apply_preset('overview')

    def move_panel(self, panel_id, area, position=0):
        if panel_id not in PANEL_IDS or area not in AREAS or type(position) is not int or not 0 <= position < len(PANEL_IDS):
            return False
        state = self.serialize()
        state['panels'][panel_id].update(area=area, position=position)
        self.apply_layout(state)
        return True

    def reorder(self, panel_id, step):
        state = self.serialize()
        item = state['panels'][panel_id]
        peers = [key for key in PANEL_IDS if state['panels'][key]['area'] == item['area']]
        peers.sort(key=lambda key: (state['panels'][key]['position'], PANEL_IDS.index(key)))
        index = peers.index(panel_id)
        target = max(0, min(len(peers) - 1, index + step))
        peers.insert(target, peers.pop(index))
        for position, key in enumerate(peers):
            state['panels'][key]['position'] = position
        self.apply_layout(state)

    def collapse(self, panel_id, collapsed=True):
        if panel_id not in PANEL_IDS or type(collapsed) is not bool:
            return False
        self._state['panels'][panel_id]['collapsed'] = collapsed
        panel = self.panels[panel_id]
        panel.content.setVisible(not collapsed)
        panel.actions['collapse'].setChecked(collapsed)
        panel.handle.setText(ui_text('workspace.collapsed').format(panel.handle.accessibleName()) if collapsed else panel.handle.accessibleName())
        return True

    def _commit(self, layouts):
        try:
            self.store.save(layouts, self.serialize())
        except (OSError, ValueError):
            self.error.setText(error_message('operation_failed_local'))
            self.error.show()
            return False
        self.error.hide()
        self._named_menus()
        return True

    def save_named(self, name):
        if not valid_name(name) or (name not in self.store.layouts and len(self.store.layouts) >= MAX_LAYOUTS):
            return False
        layouts = deepcopy(self.store.layouts)
        layouts[name] = self.serialize()
        return self._commit(layouts)

    def restore_named(self, name):
        value = self.store.layouts.get(name) if valid_name(name) else None
        self.apply_layout(value)
        return value is not None

    def delete_named(self, name):
        if name not in self.store.layouts:
            return False
        layouts = deepcopy(self.store.layouts)
        del layouts[name]
        return self._commit(layouts)

    def _save_dialog(self):
        name, accepted = QInputDialog.getText(self.dashboard, ui_text('workspace.save'), ui_text('workspace.name'))
        if accepted and not self.save_named(name) and self.error.isHidden():
            self.error.setText(error_message('validation_failed'))
            self.error.show()

    def _named_menus(self):
        self.restore_menu.clear()
        self.delete_menu.clear()
        for name in self.store.layouts:
            restore = self.restore_menu.addAction(name)
            restore.triggered.connect(lambda checked=False, n=name: self.restore_named(n))
            delete = self.delete_menu.addAction(name)
            delete.triggered.connect(lambda checked=False, n=name: self.delete_named(n))
