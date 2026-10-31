"""One keyboard-operable disclosure treatment for advanced UI sections."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton


def disclosure_button(title, name='', parent=None):
    toggle = QToolButton(parent)
    toggle.setText(title)
    toggle.setObjectName(name)
    toggle.setAccessibleName(title)
    toggle.setCheckable(True)
    toggle.setProperty('designDisclosure', True)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setArrowType(Qt.ArrowType.RightArrow)
    toggle.toggled.connect(lambda checked: toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
    return toggle
