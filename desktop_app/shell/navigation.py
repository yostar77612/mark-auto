from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame as _QFrame, QVBoxLayout, QLabel, QScrollArea, QSizePolicy as _QSizePolicy, QLayout as _QLayout


def _mount_market(self, page, label):
    self.navigation.addItem(label)
    self.stack.addWidget(page)


def _mount_page(self, page, label):
    self.navigation.addItem(label)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 22, 28, 24)
    layout.setSpacing(14)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    title = QLabel(label)
    title.setProperty('themePart', 'pageTitle')
    layout.addWidget(title)
    scroll = QScrollArea()
    scroll.setFrameShape(_QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    self.stack.addWidget(scroll)
    if type(page).__name__ == 'StrategyPage':
        page.setSizePolicy(_QSizePolicy.Policy.Expanding, _QSizePolicy.Policy.Ignored)
        layout.setSizeConstraint(_QLayout.SizeConstraint.SetNoConstraint)
        layout.setAlignment(Qt.AlignmentFlag(0))
    return layout


def _navigate_selected_page(self):
    selected = self.navigation.selectedItems()
    if len(selected) == 1:
        self.navigation.setCurrentRow(self.navigation.row(selected[0]))
