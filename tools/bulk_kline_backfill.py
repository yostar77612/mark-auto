"""Download about one year of 1-minute K-lines for the top-N stocks by traded amount (read-only market data).

Run it only while MarkAuto is closed: it writes the active context's K-line store directly, the same store the
市場 charts read. It logs in to SinoPac market data once with the stored key reference (never printed, never
typed), ranks ordinary shares by today's traded amount from one full-market snapshot round, and queues each stock
through the app's own HistorySync. The quota guard (keeps 10% of the daily traffic allowance), the shared
40-queries-per-10-seconds limiter and the 29-day chunks therefore apply unchanged, and ranges already covered are
skipped, so rerunning the tool resumes where it stopped (for example the next day once the quota resets).

The development venv has no broker SDK: put the pinned shioaji 1.7.9 on PYTHONPATH (the M5 probe keeps a copy):

    $env:PYTHONPATH = "$env:LOCALAPPDATA\\MarkAuto-probe\\sdk"
    .venv\\Scripts\\python.exe tools\\bulk_kline_backfill.py --top 200
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantlab.trading.adapters.shioaji.snapshot_poller import ShioajiSnapshotSource  # noqa: E402
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory  # noqa: E402
from quantlab.trading.adapters.storage.kline_store import KlineStore  # noqa: E402
from quantlab.trading.application.history_sync import HistorySettings, HistorySync  # noqa: E402
from quantlab.trading.application.market_settings import MarketDataSettings  # noqa: E402
from quantlab.trading.domain.models import Environment  # noqa: E402
from quantlab.trading.domain.sector import eligible_stock  # noqa: E402
from quantlab.trading.domain.watch import WatchKind  # noqa: E402
from quantlab.trading.runtime.market_connection import create_market_session  # noqa: E402

DEFAULT_CONTEXT = Path(os.environ.get('LOCALAPPDATA', '')) / 'MarkAuto-v2' / 'local' / 'context-engines' / 'sinopac-simulation'


def markauto_running() -> bool:
    if os.name != 'nt':
        return False
    listing = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq MarkAuto.exe', '/NH'], capture_output=True, text=True, check=False)
    return 'MarkAuto.exe' in listing.stdout


def market_settings(context: Path) -> MarketDataSettings:
    body = json.loads((context / 'settings.json').read_text(encoding='utf-8'))['settings']['sinopac_connection_v1']
    return MarketDataSettings(Environment(body['environment']), body['key_ref'], True)


def ranked(session, directory: SymbolDirectory, top: int):
    stocks = tuple(item for item in directory.items if item.kind is WatchKind.STOCK and eligible_stock(item.code))
    rows = ShioajiSnapshotSource(session).snapshots(stocks)
    by_code = {item.code: item for item in stocks}
    order = sorted((row for row in rows if row.code in by_code), key=lambda row: row.total_amount, reverse=True)
    return [(by_code[row.code], row.total_amount) for row in order[:top]]


def stored_bars(store: KlineStore, instrument_id: str, start: datetime, end: datetime) -> int:
    return len(store.read(instrument_id, start, end))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--context', type=Path, default=DEFAULT_CONTEXT, help='MarkAuto context-engine folder')
    parser.add_argument('--top', type=int, default=200)
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--max-bars-today', type=int, default=HistorySettings().daily_bar_limit)
    parser.add_argument('--rank-only', action='store_true', help='print the ranking and stop')
    args = parser.parse_args(argv)
    if markauto_running():
        print('MarkAuto 正在執行：請先關閉 MarkAuto 再下載（兩邊同時寫入 K 線庫不安全）。')
        return 2
    settings = market_settings(args.context)
    directory = SymbolDirectory(args.context / 'market' / 'symbol_directory.json')
    session = create_market_session(settings, directory)
    session.connect()
    try:
        top = ranked(session, directory, args.top)
        print(f'成交金額前 {len(top)} 名（{settings.environment.value}）：')
        for rank, (item, amount) in enumerate(top, 1):
            print(f'  {rank:3d}. {item.code} {item.name}  成交金額 {amount / 1e8:,.1f} 億')
        if args.rank_only:
            return 0
        store = KlineStore(args.context / 'market' / 'klines.sqlite3')
        history = HistorySync(store, session, HistorySettings(daily_bar_limit=args.max_bars_today), autostart=False)
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(days=args.days)
        for rank, (item, _) in enumerate(top, 1):
            history.request(item, start, end, priority=rank)
        started = time.monotonic()
        done = set()
        while history.run_next():
            state = history.state()
            for rank, (item, _) in enumerate(top, 1):
                instrument = item.instrument_id
                if instrument in done or history.is_backfilling(instrument):
                    continue
                done.add(instrument)
                error = dict(state.history_error).get(instrument, '')
                usage = f'{state.usage.used_bytes / 2**20:,.0f}/{state.usage.limit_bytes / 2**20:,.0f} MB' if state.usage else '流量未知'
                status = f'失敗 {error}' if error else f'{stored_bars(store, instrument, start, end):,} 根'
                print(f'  [{len(done):3d}/{len(top)}] {item.code} {item.name}: {status}  今日流量 {usage}  {time.monotonic() - started:,.0f} 秒', flush=True)
            if state.paused:
                print('今日流量或 K 棒數已達保護上限，已暫停；明天再執行一次會從中斷處接著下載。')
                break
        return 0
    finally:
        session.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
