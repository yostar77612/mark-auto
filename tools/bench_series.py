"""Offline timing, page count and payload size of market series reads (OPT-1 P8, P11).

Two real engines are measured, each over synthetic one-minute bars (no network, broker or credentials):
  live      LiveMarketService over a history-only market: the legacy live path.
  terminal  MarketTerminalService over a temporary KlineStore: the path every chart read takes while the market
            connection is enabled. Needs the patched SQLite runtime (the repository .venv has it), skipped otherwise.
For each size and period the reads are:
  whole  every page, exactly as the market terminal and the legacy watch read before OPT-1 P11
         (first page, then each next_offset with the page's market revision)
  tail   one read of the last TAIL bars of the live engine (the sector board's OPT-1 P8 read; live only)
  index  the market terminal's TAIEX mini-chart read (terminal only): the first page, then the last page
Columns, all per read: engine ms (series() calls), codec ms (codec dumps + loads of every returned page's bars,
which the IPC adds on top of the engine), ui ms (series_bars of the whole result plus the prefix compare that
render_chart does), their total, pages, bars read and the encoded bytes of those bars (the unit series() budgets
pages in). Cross-process transport itself is not measured.
Usage: python tools/bench_series.py [--repeat N] [--tail K] [--engine live|terminal|both] [--sizes 1000,8100]
"""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_app.features.trading.market_watch_rows import series_bars  # noqa: E402
from quantlab.trading.application.codec import dumps, loads  # noqa: E402
from quantlab.trading.application.contracts import MarketSeriesPage, MarketSeriesQuery  # noqa: E402
from quantlab.trading.application.live_market import LiveMarketService  # noqa: E402
from quantlab.trading.domain.freshness import LiveMarketSettings  # noqa: E402
from quantlab.trading.domain.live_bars import LiveBar  # noqa: E402
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind  # noqa: E402
from quantlab.trading.ports.contracts import DataBatch, HistoryBar, SubscriptionReceipt  # noqa: E402


KEY = 'BENCH:2330'
TERMINAL_KEY = 'TWSE:2330'  # the terminal service resolves ids through the watch directory, so it needs a real identity
INDEX_KEY = FIXED_INDICES[0].instrument_id
END = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
SIZES = (1_000, 8_100, 34_000, 43_200)
# 8,100 one-minute bars are 30 stock trade days; 34,000 are 30 futures trade days including the night session.
LABELS = {8_100: 'stock 30d', 34_000: 'futures 30d+night'}
PERIODS = ('1m', '5m', '1d')
TERMINAL_SIZES = (8_100, 34_000)
TERMINAL_MIN_SQLITE = (3, 53, 0)


class Clock:
    def now(self):
        return END


class Resolver:
    """One trade date per calendar day; every minute belongs to a DAY session."""

    def session_at(self, instrument_id, timestamp):
        return timestamp.date(), 'DAY'


class HistoryMarket:
    """History-only market: subscriptions succeed, no ticks, `bars` one-minute bars ending at END."""

    def __init__(self, bars):
        self.count = bars

    def subscribe(self, instrument_ids):
        return SubscriptionReceipt('bench-sub', tuple(instrument_ids), True, END)

    def unsubscribe(self, subscription_id):
        pass

    def drain_ticks(self, max_items):
        return ()

    def history(self, instrument_id, start, end):
        bars = []
        for index in range(self.count, 0, -1):
            begin = END - timedelta(minutes=index)
            if start <= begin < end:
                close = Decimal(600 + index % 37) + Decimal('0.5')
                bars.append(HistoryBar(instrument_id, begin, begin + timedelta(minutes=1), close, close + 1, close - 1, close, 1000 + index % 97, 'BENCH'))
        return DataBatch(instrument_id, tuple(bars), 'BENCH', True)


class _Session:
    """A disconnected market session: no ticks, no quotes, no history queries."""

    connected = False

    def subscribe(self, item):
        pass

    def unsubscribe(self, key):
        pass

    def drain_ticks(self, limit):
        return ()

    def drain_tick_losses(self):
        return ()

    def usage(self):
        return None

    def quote_details(self, instrument_id):
        return {}

    def subscribe_bidask(self, item):
        pass

    def unsubscribe_bidask(self, key):
        pass

    def bidask(self, instrument_id):
        return None

    def history(self, item, start, end):
        return ()


class Facade:
    """The two calls the chart code makes, straight onto an engine, remembering every page it returned."""

    def __init__(self, service):
        self.service, self.pages = service, []

    def market_series(self, query):
        page = self.service.series(query)
        self.pages.append(page)
        return page


def live_service(bars):
    service = LiveMarketService(HistoryMarket(bars), Clock(), Resolver(), settings=LiveMarketSettings(buffer_trade_days=40))
    service.allocate((KEY,))
    service.backfill(KEY, END - timedelta(minutes=bars + 1), END)
    return service


def stored_bars(instrument_id, count):
    result = []
    for index in range(count, 0, -1):
        start = END - timedelta(minutes=index)
        price = Decimal(600 + index % 37) + Decimal('0.5')
        result.append(
            LiveBar(instrument_id, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price + 1, price - 1, price, 1000 + index % 97, final=True)
        )
    return tuple(result)


class TerminalEngine:
    """MarketTerminalService over a temporary KlineStore holding `bars` one-minute bars of KEY and of the TAIEX index."""

    def __init__(self, bars):
        from quantlab.trading.adapters.storage.kline_store import KlineStore
        from quantlab.trading.application.history_sync import HistorySync
        from quantlab.trading.application.market_terminal_service import MarketTerminalService

        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = KlineStore(Path(self.temp.name) / 'klines.sqlite3')
        self.history = HistorySync(self.store, _Session(), now=lambda: END, autostart=False)
        item = WatchInstrument(TERMINAL_KEY, WatchKind.STOCK, 'TSE', '2330', 'BENCH')
        self.service = MarketTerminalService(self.store, self.history, _Session(), lambda: (*FIXED_INDICES, item), now=lambda: END)
        for instrument_id in (TERMINAL_KEY, INDEX_KEY):
            self.store.upsert(stored_bars(instrument_id, bars))

    def close(self):
        self.history.close()
        self.store.close()
        self.temp.cleanup()


def whole_read(facade, key, period):
    """The market terminal's and the legacy watch's read before OPT-1 P11: every page, revision-pinned after the first."""
    page = facade.market_series(MarketSeriesQuery(key, period))
    bars = page.bars
    while page.next_offset is not None:
        page = facade.market_series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
        bars += page.bars
    return bars


def tail_read(facade, key, period, tail, total):
    """One read of the last `tail` bars of a series whose length the caller already holds (as the sector board cache does)."""
    return facade.market_series(MarketSeriesQuery(key, period, offset=max(0, total - tail))).bars


def index_read(facade, key, period):
    """The market terminal's TAIEX mini-chart read: the first page, then the last page when there are more."""
    index = facade.market_series(MarketSeriesQuery(key, '1m'))
    if index.next_offset is not None:
        index = facade.market_series(
            MarketSeriesQuery(index.instrument_id, '1m', offset=max(0, index.total - len(index.bars)), market_revision=index.market_revision)
        )
    return index.bars


def median_ms(operation, repeat):
    runs = []
    for _ in range(repeat):
        started = time.perf_counter()
        operation()
        runs.append((time.perf_counter() - started) * 1000)
    return statistics.median(runs)


def measure(facade, read, repeat, period):
    """(engine ms, codec ms, ui ms, pages, bars read, bytes) of one read, medians over `repeat` runs."""

    def run():
        facade.pages.clear()
        return read()

    result = []
    engine = median_ms(lambda: result.append(run()), repeat)
    bars, pages = result[-1], list(facade.pages)
    steps = min(repeat, 3)
    codec = median_ms(lambda: [loads(dumps(page.bars)) for page in pages], steps)
    chart = MarketSeriesPage(KEY, period, bars)
    previous = series_bars(chart)  # what the chart holds from the last refresh

    def ui():
        current = series_bars(replace(chart, bars=bars))
        return current[: len(previous) - 1] == previous[:-1]

    interface = median_ms(ui, steps)
    bars_read = sum(len(page.bars) for page in pages)
    size = sum(len(dumps(bar).encode('utf-8')) for page in pages for bar in page.bars)
    return engine, codec, interface, len(pages), bars_read, size


def report(engine, count, period, name, row):
    engine_ms, codec_ms, ui_ms, pages, bars, size = row
    label = LABELS.get(count, '')
    print(
        f'{engine} | {count} {label} | {period} | {name} | {engine_ms:.1f} | {codec_ms:.1f} | {ui_ms:.1f} | {engine_ms + codec_ms + ui_ms:.1f} | {pages} | {bars} | {size}'
    )


def run_live(sizes, repeat, tail):
    for count in sizes:
        facade = Facade(live_service(count))
        for period in PERIODS:
            facade.market_series(MarketSeriesQuery(KEY, period, limit=1))  # warm the view cache like a live UI
            total = len(whole_read(facade, KEY, period))
            report('live', count, period, 'whole', measure(facade, lambda: whole_read(facade, KEY, period), repeat, period))
            report('live', count, period, 'tail', measure(facade, lambda: tail_read(facade, KEY, period, tail, total), repeat, period))


def run_terminal(sizes, repeat, tail):
    if sqlite3.sqlite_version_info < TERMINAL_MIN_SQLITE:
        print(f'terminal engine skipped: SQLite {sqlite3.sqlite_version} is older than the patched runtime the K-line store needs (use the repository .venv)')
        return
    for count in sizes:
        engine = TerminalEngine(count)
        try:
            facade = Facade(engine.service)
            for period in PERIODS:
                whole_read(facade, TERMINAL_KEY, period)  # warm the store read cache
                report('terminal', count, period, 'whole', measure(facade, lambda: whole_read(facade, TERMINAL_KEY, period), repeat, period))
            report('terminal', count, '1m', 'index', measure(facade, lambda: index_read(facade, INDEX_KEY, '1m'), repeat, '1m'))
        finally:
            engine.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--tail', type=int, default=240)
    parser.add_argument('--engine', choices=('live', 'terminal', 'both'), default='both')
    parser.add_argument('--sizes', help='comma separated one-minute bar counts (defaults per engine)')
    args = parser.parse_args(argv)
    chosen = tuple(int(item) for item in args.sizes.split(',')) if args.sizes else None
    print(f'python {sys.version.split()[0]}; sqlite {sqlite3.sqlite_version}; repeat {args.repeat}; tail {args.tail}; median ms per read')
    print('engine | 1m bars | period | read | engine_ms | codec_ms | ui_ms | total_ms | pages | bars read | bytes')
    if args.engine in ('live', 'both'):
        run_live(chosen or SIZES, args.repeat, args.tail)
    if args.engine in ('terminal', 'both'):
        run_terminal(chosen or TERMINAL_SIZES, args.repeat, args.tail)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
