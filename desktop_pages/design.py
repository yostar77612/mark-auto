"""Presentation sections shared by the simplified desktop workspaces."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

from desktop_strings import ui_text
from .preferences import disclosure_value, load_store


def card(layout, title_key):
    panel = QFrame()
    panel.setProperty('designCard', True)
    content = QVBoxLayout(panel)
    content.setContentsMargins(20, 16, 20, 18)
    content.setSpacing(12)
    title = QLabel(ui_text(title_key))
    title.setProperty('designHeading', True)
    content.addWidget(title)
    layout.addWidget(panel)
    return content


def section(layout, title_key, expanded=False, key=None, state=None):
    """Collapse real widgets, preserving keyboard reachability and ownership."""
    panel = QWidget()
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(8)
    toggle = QToolButton()
    toggle.setText(ui_text(title_key))
    toggle.setAccessibleName(toggle.text())
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setCheckable(True)
    toggle.setProperty('designDisclosure', True)
    toggle.setProperty('defaultExpanded', expanded)
    box = QWidget()
    inner = QVBoxLayout(box)
    inner.setContentsMargins(12, 4, 0, 8)
    inner.setSpacing(10)
    outer.addWidget(toggle)
    outer.addWidget(box)
    layout.addWidget(panel)

    def show(checked):
        box.setVisible(checked)
        toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    toggle.toggled.connect(show)

    def remember(checked):
        save = getattr(state, 'save_sections', None)
        if key and callable(save):
            save()

    toggle.setChecked(expanded)
    show(expanded)
    if key and state is not None and hasattr(state, '_section_toggles'):
        toggle.setObjectName(key)
        state._section_toggles[key] = toggle
        values = load_store(getattr(state, 'settings', None))
        stored = values.get('advanced_sections', {})
        toggle.setChecked(disclosure_value(key, toggle, stored))
    toggle.toggled.connect(remember)
    return inner
