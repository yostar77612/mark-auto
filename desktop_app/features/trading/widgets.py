"""Small accessible desktop presentation building blocks."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from desktop_app.strings.catalog import ui_text


ACCESSIBLE_KEYS = {
    'strategies': 'v2.strategies',
    'positions': 'v2.positions',
    'orders': 'v2.orders',
    'markets': 'v2.markets',
    'performance_rows': 'v2.performance_rows',
    'accounts': 'v2.accounts',
    'market': 'v2.market',
    'policy': 'v2.policy',
    'direction': 'v2.direction',
    'risk': 'v2.risk',
    'rules': 'v2.rules',
    'environment': 'v2.environment',
    'stock_budget': 'v2.stock_budget',
    'futures_budget': 'v2.futures_budget',
    'broker_readiness_checks': 'v2.broker_readiness_checks',
    'reconciliation_differences': 'v2.reconciliation_title',
}


def fit_available_screen(widget: QWidget) -> None:
    """Keep native chrome and client controls inside the actual logical screen.

    Qt already applies the screen's real device-pixel ratio. Do not guess that
    ratio from an environment variable or shrink fonts to accommodate a window.
    """
    screen = widget.screen()
    if screen is None:
        return
    available = screen.availableGeometry()
    owner = widget.parentWidget()
    if isinstance(widget, QDialog) and owner is not None:
        # A dialog must also fit its owner's usable viewport. A larger monitor
        # is not evidence that a small owner window can expose its footer.
        owner_available = available.intersected(owner.window().frameGeometry())
        if not owner_available.isEmpty():
            available = owner_available
    available = available.adjusted(8, 8, -8, -8)
    frame = widget.frameGeometry()
    extra_width = max(0, frame.width() - widget.width())
    extra_height = max(0, frame.height() - widget.height())
    maximum = available.size()
    maximum.setWidth(max(1, maximum.width() - extra_width))
    maximum.setHeight(max(1, maximum.height() - extra_height))
    # Only the window bounds adapt; all content retains its font, focus order,
    # accessible names and scroll areas. Very small secondary screens must not
    # inherit a minimum larger than their entire available desktop.
    widget.setMinimumSize(widget.minimumSize().boundedTo(maximum))
    widget.resize(widget.size().boundedTo(maximum))
    width, height = widget.width() + extra_width, widget.height() + extra_height
    left = max(available.left(), min(frame.left(), available.right() - width + 1))
    top = max(available.top(), min(frame.top(), available.bottom() - height + 1))
    widget.move(left, top)


def label(key: str) -> QLabel:
    widget = QLabel(ui_text(key))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(key: str, name: str) -> QPushButton:
    widget = QPushButton(ui_text(key))
    widget.setObjectName(name)
    widget.setAccessibleName(ui_text(key))
    widget.setMinimumHeight(36)
    return widget


def combo(values: tuple[tuple[str, object], ...], name: str) -> QComboBox:
    widget = QComboBox()
    widget.setObjectName(name)
    widget.setAccessibleName(ui_text(ACCESSIBLE_KEYS[name]))
    widget.setMinimumContentsLength(12)
    for key, value in values:
        widget.addItem(ui_text(key), value)
    return widget


def table(headers: tuple[str, ...], name: str) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setObjectName(name)
    widget.setAccessibleName(ui_text(ACCESSIBLE_KEYS[name]))
    widget.setHorizontalHeaderLabels([ui_text(key) for key in headers])
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.verticalHeader().setVisible(False)
    widget.setAlternatingRowColors(True)
    widget.setMinimumHeight(165)
    widget.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    return widget


def rows(widget: QTableWidget, values: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    selected = selected_id(widget)
    if widget.rowCount() != len(values):
        widget.setRowCount(len(values))
    for row_index, (identity, cells) in enumerate(values):
        for column, text in enumerate(cells):
            item = widget.item(row_index, column)
            if item is None:
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, identity)
                widget.setItem(row_index, column, item)
            else:
                if item.text() != text:
                    item.setText(text)
                if item.data(Qt.ItemDataRole.UserRole) != identity:
                    item.setData(Qt.ItemDataRole.UserRole, identity)
    if selected and selected_id(widget) != selected:
        target_row = next((index for index, (identity, _) in enumerate(values) if identity == selected), None)
        if target_row is None:
            widget.clearSelection()
            widget.setCurrentCell(-1, -1)
        else:
            widget.selectRow(target_row)


def selected_id(widget: QTableWidget) -> str:
    selected = widget.selectedItems()
    return str(selected[0].data(Qt.ItemDataRole.UserRole)) if selected else ''
