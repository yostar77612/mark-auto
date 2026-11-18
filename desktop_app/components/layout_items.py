"""Read a layout's widgets and child layouts without QLayout.itemAt().

PySide6 (6.12) keeps every QLayoutItem that QLayout.itemAt() returns alive as a child of the layout's Python
wrapper. When Qt later deletes that item on its own (its widget is reparented, moved into another layout or
deleted while the layout lives on) the wrapper outlives it and still points at the freed memory. Any object Qt
later allocates at that address is then returned as the stale wrapper (CI saw windowHandle() come back as a
QWidgetItem), and calls through such a wrapper corrupt the heap: the intermittent native access violations.

QLayout.indexOf() returns only an int, so these helpers never create an item wrapper.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QWidget

_DIRECT = Qt.FindChildOption.FindDirectChildrenOnly


def layout_entries(layout):
    """The widgets and child layouts directly in `layout`, in layout order (spacers are skipped)."""
    parent = layout.parentWidget()
    candidates = list(parent.findChildren(QWidget, options=_DIRECT)) if parent is not None else []
    candidates += layout.findChildren(QLayout, options=_DIRECT)
    placed = [(layout.indexOf(candidate), candidate) for candidate in candidates]
    return [candidate for index, candidate in sorted((pair for pair in placed if pair[0] >= 0), key=lambda pair: pair[0])]


def layout_entry(layout, index):
    """The widget or child layout at `index` in `layout`, or None (a spacer or an index out of range)."""
    if index < 0:
        return None
    return next((entry for entry in layout_entries(layout) if layout.indexOf(entry) == index), None)


def child_layouts(layout):
    """The layouts nested directly in `layout`."""
    return [entry for entry in layout_entries(layout) if isinstance(entry, QLayout)]
