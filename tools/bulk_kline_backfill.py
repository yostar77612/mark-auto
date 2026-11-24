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

With --existing the tool does not rank anything: it extends every stock that already holds 1-minute bars (the 已下載
K 線 list, indices left alone) back to --days days, for example three years for all of them:

    .venv\\Scripts\\python.exe tools\\bulk_kline_backfill.py --existing --days 1095 --max-bars-today 100000000

With --stock-futures N the tool ranks the single-stock futures (ETF futures left out) by the volume of their near-month
contract and downloads one year (--days) of 1-minute bars of the N most traded continuous front-month contracts
(for example CDFR1), stored as TAIFEX:<code>. A trading date of a stock future starts with the night session of the evening
before (15:00-05:00) and ends with the day session (08:45-13:45), and the snapshot total counts from the night open: it covers
one complete trading date only between 13:50 and 15:00 on a weekday. The ranking is therefore refused outside that window
(--any-time overrides it, and then the totals are partial: before 08:45 they are the night session alone). A K-line query
that reaches today also times out while the day session is open, so download in the same window.

    .venv\\Scripts\\python.exe tools\\bulk_kline_backfill.py --stock-futures 100 --max-bars-today 100000000
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantlab.trading.adapters.shioaji.sdk import sdk_text, sdk_value  # noqa: E402
from quantlab.trading.adapters.shioaji.snapshot_poller import BATCH, ShioajiSnapshotSource  # noqa: E402
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory  # noqa: E402
from quantlab.trading.adapters.storage.kline_store import KlineStore  # noqa: E402
from quantlab.trading.application.history_sync import HistorySettings, HistorySync  # noqa: E402
from quantlab.trading.application.market_settings import MarketDataSettings  # noqa: E402
from quantlab.trading.domain.models import Environment  # noqa: E402
from quantlab.trading.domain.sector import eligible_stock  # noqa: E402
from quantlab.trading.domain.validation import DomainError  # noqa: E402
from quantlab.trading.domain.watch import WatchKind, is_future, is_stock_future_code, stock_future  # noqa: E402
from quantlab.trading.runtime.market_connection import create_market_session  # noqa: E402

TAIPEI = ZoneInfo('Asia/Taipei')
# A stock future's trading date runs from the night session (15:00) of the evening before to the day close (13:45): the snapshot total is
# complete only after the close and before the next night open.
RANKING_WINDOW = (clock_time(13, 50), clock_time(15, 0))
DEFAULT_CONTEXT = Path(os.environ.get('LOCALAPPDATA', '')) / 'MarkAuto-v2' / 'local' / 'context-engines' / 'sinopac-simulation'


def now() -> datetime:
    return datetime.now(TAIPEI)


def ranking_window_open(moment: datetime) -> bool:
    local = moment.astimezone(TAIPEI)
    return local.weekday() < 5 and RANKING_WINDOW[0] <= local.time() < RANKING_WINDOW[1]


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


def ranked_stock_futures(session, top: int):
    """The N most traded single-stock futures as (watch instrument, volume in contracts), ETF futures left out.

    The volume is the snapshot total of the near-month contract (the continuous contract itself cannot be snapshotted). It counts
    from the night open, so it is one complete trading date only between the day close and the next night open (see RANKING_WINDOW).
    Contracts the broker does not list in full, without volume, or whose name is unusable are left out."""
    facade = session.facade
    near_month = {}
    for base in facade.market_contracts('FUT'):
        try:
            code = sdk_text(sdk_value(base, 'code'))
            if not is_stock_future_code(code):
                continue
            info = facade.market_contract_info(base)
            underlying = sdk_text(getattr(info, 'underlying_code', '') or '')
            if sdk_text(getattr(info, 'underlying_kind', '') or '') != 'S' or underlying.startswith('00'):
                continue  # not a single stock: ETF futures (underlying 00xx), index, commodity and currency futures
            target = sdk_text(getattr(base, 'target_code', '') or '')
            contract = facade.market_contract(target) if target and target != code else None
            if contract is not None:
                near_month[target] = (stock_future(code, sdk_text(getattr(info, 'name', '') or code)), contract)
        except DomainError:
            continue  # one unreadable contract row must not stop the ranking
    volumes = {}
    rows = list(near_month.values())
    for start in range(0, len(rows), BATCH):
        for raw in facade.snapshots([contract for _, contract in rows[start : start + BATCH]]):
            code = sdk_text(getattr(raw, 'code', ''))
            if code in near_month:
                volumes[code] = int(getattr(raw, 'total_volume', 0) or 0)
    order = sorted((target for target in near_month if volumes.get(target, 0) > 0), key=lambda target: (-volumes[target], near_month[target][0].code))
    return [(near_month[target][0], volumes[target]) for target in order[:top]]


def stored_bars(store: KlineStore, instrument_id: str, start: datetime, end: datetime) -> int:
    return len(store.read(instrument_id, start, end))


def finished_status(store: KlineStore, instrument_id: str, start: datetime, end: datetime, by_extent: bool) -> str:
    """What the progress line says about a finished instrument: the earliest stored bar when extending or for futures (one index seek), else the bar count of the window."""
    if not by_extent:
        return f'{stored_bars(store, instrument_id, start, end):,} 根'
    extent = store.minute_extent(instrument_id)
    return f'最早 {extent[0]:%Y-%m-%d}' if extent else '沒有 1 分 K'


def downloaded_stocks(store: KlineStore, directory: SymbolDirectory):
    """The stocks that already hold 1-minute bars (the 已下載 K 線 list without indices), in code order, and the held ids the directory does not know.

    Futures bars share the store but are not stocks and are not 'unknown' either: they are left out of both lists."""
    known = {item.instrument_id: item for item in directory.items}
    held = [instrument_id for instrument_id in store.instrument_ids() if store.minute_extent(instrument_id) is not None]
    stocks = sorted((known[i] for i in held if i in known and known[i].kind is WatchKind.STOCK), key=lambda item: item.code)
    return stocks, [i for i in held if i not in known and not is_future(i)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--context', type=Path, default=DEFAULT_CONTEXT, help='MarkAuto context-engine folder')
    parser.add_argument('--top', type=int, default=200)
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--max-bars-today', type=int, default=HistorySettings().daily_bar_limit)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        '--existing',
        action='store_true',
        help='extend the stocks that already have 1-minute bars instead of ranking by traded amount (use with --days 1095 for three years)',
    )
    modes.add_argument(
        '--stock-futures',
        type=int,
        metavar='N',
        default=None,
        help='download the N most traded single-stock futures (continuous front-month contracts, ETF futures left out) instead of ranking stocks',
    )
    parser.add_argument(
        '--any-time',
        action='store_true',
        help='with --stock-futures: rank outside 13:50-15:00 on a weekday anyway (the totals then do not cover a complete trading date)',
    )
    parser.add_argument('--rank-only', action='store_true', help='print the ranking (or, with --existing, the stocks that would be extended) and stop')
    args = parser.parse_args(argv)
    if args.stock_futures is not None and args.stock_futures < 1:
        parser.error('--stock-futures needs a positive number')
    if markauto_running():
        print('MarkAuto 正在執行：請先關閉 MarkAuto 再下載（兩邊同時寫入 K 線庫不安全）。')
        return 2
    if args.stock_futures and not args.any_time and not ranking_window_open(now()):
        print('個股期貨的成交量要在平日 13:50 到 15:00 之間排名（收盤後、夜盤開始前才是完整的一個交易日）；要硬排請加 --any-time。')
        return 2
    settings = market_settings(args.context)
    directory = SymbolDirectory(args.context / 'market' / 'symbol_directory.json')
    store_path = args.context / 'market' / 'klines.sqlite3'
    store = None
    try:  # the store is closed on every way out: an unclosed store leaves an open token that makes the next app start run a full check
        if args.existing:
            store = KlineStore(store_path)
            stocks, unknown = downloaded_stocks(store, directory)
            top = [(item, None) for item in stocks]
            print(f'已有 1 分 K 的股票 {len(top)} 檔，各補到近 {args.days} 天：' + ' '.join(item.code for item, _ in top))
            if unknown:
                print(f'符號目錄查不到而略過的代號 {len(unknown)} 個：' + ' '.join(unknown))
            if args.rank_only:
                return 0
            if not top:
                print('K 線庫裡沒有可以延伸的股票（符號目錄是否讀得到？），不登入、不下載。')
                return 0
        session = create_market_session(settings, directory)
        session.connect()
        try:
            if args.stock_futures:
                top = ranked_stock_futures(session, args.stock_futures)
                print(f'個股期貨成交量前 {len(top)} 名（近月合約當日快照成交量，ETF 期貨不計；{settings.environment.value}）：')
                for rank, (item, volume) in enumerate(top, 1):
                    print(f'  {rank:3d}. {item.code} {item.name}  {volume:,} 口')
                if args.rank_only:
                    return 0
                store = KlineStore(store_path)
            elif not args.existing:
                top = ranked(session, directory, args.top)
                print(f'成交金額前 {len(top)} 名（{settings.environment.value}）：')
                for rank, (item, amount) in enumerate(top, 1):
                    print(f'  {rank:3d}. {item.code} {item.name}  成交金額 {amount / 1e8:,.1f} 億')
                if args.rank_only:
                    return 0
                store = KlineStore(store_path)
            history = HistorySync(store, session, HistorySettings(daily_bar_limit=args.max_bars_today), autostart=False)
            end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            start = end - timedelta(days=args.days)
            for rank, (item, _) in enumerate(top, 1):
                history.request(item, start, end, priority=rank)
            started = time.monotonic()
            done = set()
            while True:
                if not history.run_next():
                    wait = history.next_retry_in()
                    if wait is None or history.state().paused:
                        break
                    time.sleep(wait + 0.1)  # a failed query is retried after a delay; wait for it instead of quitting
                    continue
                state = history.state()
                for rank, (item, _) in enumerate(top, 1):
                    instrument = item.instrument_id
                    if instrument in done or history.is_backfilling(instrument):
                        continue
                    done.add(instrument)
                    error = dict(state.history_error).get(instrument, '')
                    usage = f'{state.usage.used_bytes / 2**20:,.0f}/{state.usage.limit_bytes / 2**20:,.0f} MB' if state.usage else '流量未知'
                    status = f'失敗 {error}' if error else finished_status(store, instrument, start, end, bool(args.existing or args.stock_futures))
                    print(
                        f'  [{len(done):3d}/{len(top)}] {item.code} {item.name}: {status}  今日流量 {usage}  {time.monotonic() - started:,.0f} 秒', flush=True
                    )
                if state.paused:
                    print('今日流量或 K 棒數已達保護上限，已暫停；明天再執行一次會從中斷處接著下載。')
                    break
            return 0
        finally:
            session.disconnect()
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
