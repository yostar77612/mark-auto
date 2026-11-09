"""Offline M5 sector board snapshots with a synthetic market and the shared fake facade.

Run with ``python -m tools.m5_sector_snapshot --out docs/analysis/m5-2-sectors``.
No desktop startup, broker SDK, credential resolver or financial operation runs.
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QRect, QThreadPool
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import time

from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.workspace import WorkspacePanel
from desktop_app.features.trading.market_terminal import MarketTerminalWidget
from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
from desktop_app.features.trading.sector_board import SectorBoardWidget
from desktop_app.features.trading.window import TradingWindow
from desktop_app.shell.theme import _apply_terminal_theme
from quantlab.research_core.adapters.market_layout import LayoutStore
from quantlab.trading.application.sector_service import SectorService
from quantlab.trading.domain.concept_groups import BUILTIN_GROUPS
from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.sector_alerts import SectorAlert
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from tests.test_market_terminal_ui import FakeFacade, OTHER, STOCK
from tools.ui_snapshot import _save_png, page_metrics

TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 9, 10, 12, 30, tzinfo=TAIPEI)


def synthetic_service():
    """Every built-in concept member plus a few industry stocks, with a deterministic spread of moves."""
    codes = []
    for group in BUILTIN_GROUPS:
        codes.extend(code for code in group.codes if code not in codes)
    extra = ('1101', '1102', '2002', '2603', '2882', '2412')
    stocks = tuple(
        WatchInstrument(f'TWSE:{code}', WatchKind.STOCK, 'TSE', code, 'N' + code, ('24', '28', '25', '27', '01', '10', '15', '17')[index % 8])
        for index, code in enumerate((*codes, *extra))
    )
    rows = []
    for index, item in enumerate(stocks):
        pct = Decimal((index * 37) % 140 - 40) / 10
        limit = 'UP' if pct >= Decimal('9.5') else ''
        rows.append(
            QuoteRow(
                item.code,
                Decimal(30 + index * 7),
                pct,
                limit,
                1000 + index,
                (1 + index % 9) * 250_000_000,
                Decimal(str(round(0.4 + (index % 11) * 0.35, 2))),
                NOW - timedelta(seconds=index),
            )
        )

    class Source:
        connected = True

        def snapshots(self, instruments):
            return tuple(rows)

    service = SectorService(lambda: stocks, Source(), lambda: NOW)
    service.refresh()
    names = {group.id: group.name for group in BUILTIN_GROUPS}
    for index, (group_id, direction) in enumerate((('builtin.memory', 'DOWN'), ('builtin.power', 'NEUTRAL'), ('builtin.cooling', 'UP'))):
        service._alerts.append(
            SectorAlert(
                NOW - timedelta(minutes=9 - 3 * index), group_id, names[group_id], 'BURST', direction, 320_000_000, 80_000_000, Decimal('4.0'), members=7
            )
        )
    service.monitor_info = lambda: (
        ('builtin.cooling', 'builtin.power', 'builtin.memory'),
        (('builtin.cooling', 5, 7), ('builtin.power', 5, 5), ('builtin.memory', 8, 8)),
    )
    service.side_ratio = lambda code: Decimal(30 + (int(code) * 7) % 60) / 100
    return service, stocks


def fonts(app):
    app.setStyle('Fusion')
    if os.name == 'nt':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setFont(QFont('Microsoft JhengHei UI', 10))


def settle(app, widgets):
    deadline = time.monotonic() + 3
    while any(widget._requests for widget in widgets) and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    app.processEvents()


def capture(out):
    app = QApplication.instance() or QApplication([])
    fonts(app)
    service, stocks = synthetic_service()
    facade = FakeFacade((STOCK.instrument_id, OTHER.instrument_id))
    facade.sector_board = lambda query: service.board(query.group_id)
    terminal = MarketTerminalWidget(
        facade,
        CandlestickChart(),
        facade.state,
        layout_store=LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset()),
        index_chart=CandlestickChart(show_volume=False),
        panel_factory=WorkspacePanel,
        style_terminal=_apply_terminal_theme,
    )
    board = SectorBoardWidget(facade, CandlestickChart())
    window = TradingWindow(facade, facade.state, market_watch=terminal, sector_board=board)
    window.poll.stop()
    out.mkdir(parents=True, exist_ok=True)
    metrics = {}
    try:
        for width, height in ((1366, 768), (1920, 1080)):
            screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, width + 40, height + 80))
            with patch.object(window, 'screen', return_value=screen):
                window.resize(width, height)
                window.navigation.setCurrentRow(2)
                window.show()
                window.market_tabs.setCurrentWidget(board)
                settle(app, (terminal, board))
                board.select_group('builtin.cooling')
                settle(app, (terminal, board))
                member = next(item for item in board.view.members)
                board.select_stock(member.instrument_id)
                settle(app, (terminal, board))
                board.refresh()
                settle(app, (terminal, board))
                _save_png(window, out / f'sector-{width}x{height}.png', 1)
                metrics[f'{width}x{height}'] = page_metrics(board)
        (out / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('docs/analysis/m5-5-monitor'))
    capture(parser.parse_args().out)


if __name__ == '__main__':
    main()
