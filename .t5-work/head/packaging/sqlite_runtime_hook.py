"""PyInstaller startup gate: every frozen entry/child loads the pinned SQLite."""
from pathlib import Path
import sys
from quantlab.sqlite_runtime import verify

verify(Path(sys._MEIPASS) / 'sqlite-runtime.json', Path(sys._MEIPASS))
