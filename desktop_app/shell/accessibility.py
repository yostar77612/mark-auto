"""Semantic control names and visual keyboard traversal for dynamic disclosures."""

from PySide6.QtCore import QObject, QEvent, QTimer, Qt, QPoint
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QAbstractButton,
    QLineEdit,
    QComboBox,
    QAbstractSpinBox,
    QTabBar,
    QAbstractItemView,
    QPlainTextEdit,
    QTextEdit,
    QFormLayout,
    QGroupBox,
    QSizePolicy,
)
from desktop_app.strings.catalog import ui_text

INTERACTIVE = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QTabBar, QAbstractItemView, QPlainTextEdit, QTextEdit)
ROW_TOLERANCE = 8


def semantic_name(widget):
    if isinstance(widget, QAbstractButton) and widget.text().strip():
        return widget.text()
    parent = widget.parentWidget()
    if parent is not None:
        if isinstance(parent, INTERACTIVE) and parent.accessibleName():
            return parent.accessibleName()
        for label in parent.findChildren(QLabel):
            if label.buddy() is widget:
                return label.text()
        layout = parent.layout()
        if isinstance(layout, QFormLayout):
            label = layout.labelForField(widget)
            if isinstance(label, QLabel):
                return label.text()
        if layout:
            for i in range(1, layout.count()):
                if layout.itemAt(i).widget() is widget:
                    previous = layout.itemAt(i - 1).widget()
                    if isinstance(previous, QLabel) and previous.text():
                        return previous.text()
    if isinstance(widget, QTabBar):
        return ui_text('access.tabs')
    if isinstance(widget, QAbstractItemView):
        return ui_text('access.table')
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return ui_text('access.editor')
    while parent is not None:
        if isinstance(parent, QGroupBox) and parent.title():
            return parent.title()
        parent = parent.parentWidget()
    return ui_text('access.field')


def visual_focus_order(page):
    controls = []
    for widget in page.findChildren(QWidget):
        if not widget.isVisibleTo(page) or not widget.isEnabled():
            continue
        if not widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
            continue
        if widget.focusProxy() is not None:
            # QTabWidget delegates to QTabBar. Ordering both moves the proxy's
            # entire subchain a second time and can strand page controls.
            continue
        # Composite editors delegate focus internally. Traverse the owning control once.
        parent = widget.parentWidget()
        if isinstance(parent, (QAbstractSpinBox, QComboBox, QAbstractItemView, QPlainTextEdit, QTextEdit)):
            continue
        controls.append(widget)
    positions = {w: w.mapTo(page, QPoint()) for w in controls}
    ordered = sorted(controls, key=lambda w: (positions[w].y(), positions[w].x()))
    result = []
    while ordered:
        top = positions[ordered[0]].y()
        row = [w for w in ordered if positions[w].y() <= top + ROW_TOLERANCE]
        result.extend(sorted(row, key=lambda w: positions[w].x()))
        ordered = [w for w in ordered if w not in row]
    return result


class AccessibleLayout(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = False
        for widget in window.findChildren(QWidget):
            widget.installEventFilter(self)
            if widget.objectName() == 'ScrollLeftButton':
                widget.setAccessibleName(ui_text('access.previous_tabs'))
            elif widget.objectName() == 'ScrollRightButton':
                widget.setAccessibleName(ui_text('access.next_tabs'))
            if isinstance(widget, INTERACTIVE) and not widget.accessibleName().strip():
                widget.setAccessibleName(semantic_name(widget))
            if isinstance(widget, QTabBar):
                for index in range(widget.count()):
                    widget.setAccessibleTabName(index, widget.tabText(index))
            if isinstance(widget, QLabel):
                widget.setWordWrap(True)
            if isinstance(widget, QAbstractButton):
                policy = widget.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Minimum)
                widget.setSizePolicy(policy)
        window.navigation.setAccessibleName(ui_text('access.navigation'))
        self.schedule()

    def schedule(self):
        if self.window.isVisible() and not self.pending:
            self.pending = True
            QTimer.singleShot(0, self, self._update_visible_order)

    def _update_visible_order(self):
        self.pending = False
        if self.window.isVisible():
            self.update_order()

    def update_order(self):
        self.pending = False
        page = self.window.stack.currentWidget()
        if page is not None:
            # Navigation enters the page, then the header/status action region.
            # Status text is a read-only label and deliberately has no tab stop.
            status_actions = (self.window.notification_center.button, self.window.cancel_button)
            header = [widget for widget in visual_focus_order(self.window.app_header) if widget not in status_actions]
            controls = [self.window.navigation, *visual_focus_order(page), *header]
            controls.extend(widget for widget in status_actions if widget.isEnabled() and widget.isVisibleTo(self.window))
            for first, second in zip(controls, controls[1:]):
                QWidget.setTabOrder(first, second)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and isinstance(watched, QAbstractButton)
            and watched.isEnabled()
        ):
            if not event.isAutoRepeat():
                watched.click()
            return True
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self.schedule()
        return False


def install_accessibility(window):
    window.accessible_layout = AccessibleLayout(window)
