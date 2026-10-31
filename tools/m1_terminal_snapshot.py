"""Offline M1 terminal snapshots using the shared ui_snapshot renderer and fake facade.

Run with ``python -m tools.m1_terminal_snapshot --out docs/analysis/m1-terminal``.
No desktop startup, broker SDK, credential resolver or financial operation runs.
"""

import argparse
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QThreadPool, QRect
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
import shiboken6

from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.workspace import WorkspacePanel
from desktop_app.features.trading.market_terminal import MarketTerminalWidget
from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
from desktop_app.features.trading.window import TradingWindow
from quantlab.research_core.adapters.market_layout import LayoutStore
from tests.test_market_terminal_ui import FakeFacade, STOCK, OTHER
from tools.ui_snapshot import _save_png, page_metrics


def capture_terminal(out):
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    if os.name == 'nt':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setFont(QFont('Microsoft JhengHei UI', 10))
    facade = FakeFacade((STOCK.instrument_id, OTHER.instrument_id))
    store = LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset())
    widget = MarketTerminalWidget(
        facade, CandlestickChart(), facade.state, layout_store=store, index_chart=CandlestickChart(show_volume=False), panel_factory=WorkspacePanel
    )
    widget.select_instrument(STOCK.instrument_id)
    frame = QWidget()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    out.mkdir(parents=True, exist_ok=True)
    metrics = {}
    try:
        for width, height in ((1366, 768), (1920, 1080)):
            frame.resize(width, height)
            frame.show()
            deadline = time.monotonic() + 3
            while widget._requests and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(5)
            app.processEvents()
            if widget._requests:
                raise TimeoutError('Offline terminal did not settle')
            stem = f'{width}x{height}'
            _save_png(frame, out / f'{stem}.png', 1)
            metrics[stem] = page_metrics(widget)
            metrics[stem]['chart_size'] = [widget.chart.width(), widget.chart.height()]
        (out / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()
        shiboken6.delete(frame)


def capture_window(out):
    """Inspect the real TradingWindow shell using a projected logical monitor.

    This only replaces the monitor rectangle, as existing geometry tests do;
    actual widget sizing, styling, headers and the fit routine remain active.
    """
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    if os.name == 'nt':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setFont(QFont('Microsoft JhengHei UI', 10))
    facade = FakeFacade((STOCK.instrument_id, OTHER.instrument_id))
    terminal = MarketTerminalWidget(
        facade,
        CandlestickChart(),
        facade.state,
        layout_store=LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset()),
        index_chart=CandlestickChart(show_volume=False),
        panel_factory=WorkspacePanel,
    )
    window = TradingWindow(facade, facade.state, market_watch=terminal)
    window.poll.stop()
    terminal.select_instrument(STOCK.instrument_id)
    out.mkdir(parents=True, exist_ok=True)
    metrics = {}
    try:
        for width, height in ((1366, 768), (1920, 1080)):
            screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, width + 40, height + 80))
            with patch.object(window, 'screen', return_value=screen):
                window.resize(width, height)
                window.navigation.setCurrentRow(2)
                window.show()
                deadline = time.monotonic() + 3
                while terminal._requests and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(5)
                app.processEvents()
                if terminal._requests:
                    raise TimeoutError('Offline terminal window did not settle')
                page = window.pages.currentWidget()
                stem = f'window-{width}x{height}'
                _save_png(window, out / f'{stem}.png', 1)
                metrics[stem] = page_metrics(terminal)
                metrics[stem].update(
                    window_size=[window.width(), window.height()],
                    terminal_size=[terminal.width(), terminal.height()],
                    chart_size=[terminal.chart.width(), terminal.chart.height()],
                    outer_scroll_areas=len(page.findChildren(QScrollArea)),
                )
        (out / 'window-metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        window.poll.stop()
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()
        shiboken6.delete(window)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('docs/analysis/m1-terminal'))
    parser.add_argument('--window', action='store_true', help='capture the real TradingWindow shell with a fake facade')
    args = parser.parse_args()
    (capture_window if args.window else capture_terminal)(args.out)


if __name__ == '__main__':
    main()
