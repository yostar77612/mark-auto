"""Read a layout's widgets and child layouts without QLayout.itemAt().

PySide6 (6.12) keeps every QLayoutItem that QLayout.itemAt() returns alive as a child of the layout's Python
wrapper. When Qt later deletes that item on its own (its widget is reparented, moved into another layout or
deleted while the layout lives on) the wrapper outlives it and still points at the freed memory. Any object Qt
later allocates at that address is then returned as the stale wrapper (CI saw windowHandle() come back as a
QWidgetItem), and calls through such a wrapper corrupt the heap: the intermittent native access violations.

QLayout.indexOf() returns only an int, so these helpers never create an item wrapper. `owner` is the widget the
layout (or the layout it is nested in) is installed on: the layout's widgets are that widget's direct children.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QWidget

_DIRECT = Qt.FindChildOption.FindDirectChildrenOnly


def _candidates(layout, owner):
    return [*owner.findChildren(QWidget, options=_DIRECT), *layout.findChildren(QLayout, options=_DIRECT)]


def layout_entries(layout, owner):
    """The widgets and child layouts directly in `layout`, in layout order (spacers are skipped)."""
    placed = sorted(((layout.indexOf(entry), position, entry) for position, entry in enumerate(_candidates(layout, owner))), key=lambda row: row[:2])
    return [entry for index, _, entry in placed if index >= 0]


def layout_entry(layout, index, owner):
    """The widget or child layout at `index` in `layout`, or None (a spacer or an index out of range)."""
    if not 0 <= index < layout.count():
        return None
    return next((entry for entry in _candidates(layout, owner) if layout.indexOf(entry) == index), None)


def child_layouts(layout):
    """The layouts nested directly in `layout`, in layout order."""
    return [child for child in sorted(layout.findChildren(QLayout, options=_DIRECT), key=layout.indexOf) if layout.indexOf(child) >= 0]
