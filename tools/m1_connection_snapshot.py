"""Offline connection-settings screenshot using the shared UI snapshot renderer."""

import os
from pathlib import Path
import json

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
import shiboken6

from desktop_app.features.trading.window import TradingWindow
from tests.test_trading_ui import RecordingFacade
from tools.ui_snapshot import _save_png, page_metrics


def capture():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    if os.name == 'nt':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setFont(QFont('Microsoft JhengHei UI', 10))
    facade = RecordingFacade()
    window = TradingWindow(facade, facade.state)
    window.poll.stop()
    window.navigation.setCurrentRow(5)
    window.show()
    app.processEvents()
    window.resize(1366, 768)
    app.processEvents()
    out = Path('docs/analysis/m1-connection')
    out.mkdir(parents=True, exist_ok=True)
    try:
        _save_png(window, out / '1366x768.png', 1)
        (out / 'metrics.json').write_text(json.dumps(page_metrics(window.broker_panel), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        shiboken6.delete(window)


if __name__ == '__main__':
    capture()
