"""Application artwork shared by development and PyInstaller's _internal tree."""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QStyle


def application_icon(app):
    icon = QIcon(str(Path(__file__).resolve().parent / 'packaging/markauto.ico'))
    if icon.isNull():
        # A source checkout can omit binary artwork; startup must remain usable.
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    return icon
