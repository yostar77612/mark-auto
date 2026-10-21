"""Scrollable strategy work areas; actions and shared state stay with their owners."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QScrollArea, QTabWidget, QVBoxLayout, QWidget
from desktop_strings import ui_text


def strategy_tabs(layout):
    tabs = QTabWidget()
    tabs.setObjectName('strategy_tabs')
    # Reserve a stable work area for previews/results when switching tabs.
    tabs.setMinimumHeight(740)
    layout.addWidget(tabs)
    contents = []
    for name in ('settings', 'research', 'walk_forward'):
        scroll = QScrollArea()
        scroll.setObjectName('strategy_' + name + '_scroll')
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('strategy_' + name + '_tab')
        inner = QVBoxLayout(content)
        inner.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        tabs.addTab(scroll, ui_text('strategy.tabs.' + name))
        contents.append(inner)
    tabs.setCurrentIndex(0)
    return tabs, contents


def candidate_analysis_layout(layout):
    toggle = QCheckBox(ui_text('ui.analysis_section.title'))
    toggle.setObjectName('candidate_analysis_toggle')
    layout.addWidget(toggle)
    content = QWidget()
    content.setObjectName('candidate_analysis_section')
    inner = QVBoxLayout(content)
    layout.addWidget(content)
    content.hide()
    toggle.toggled.connect(content.setVisible)
    return inner
