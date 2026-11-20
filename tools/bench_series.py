"""Offline timing and payload size of LiveMarketService.series() reads (OPT-1 P8).

Builds a real LiveMarketService over a synthetic history-only market (no network, broker or credentials),
backfills N one-minute bars, then measures (a) a full paged read exactly as the sector board detail did
(first page, then every next_offset with the page's market revision) and (b) a single tail read of the
last TAIL bars. Bytes are the sum of the UTF-8 codec encoding of every returned bar, the same measure
series() uses for its page byte budget.
Usage: python tools/bench_series.py [--repeat N] [--tail K]
"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.trading.application.codec import dumps  # noqa: E402
from quantlab.trading.application.contracts import MarketSeriesQuery  # noqa: E402
from quantlab.trading.application.live_market import LiveMarketService  # noqa: E402
from quantlab.trading.domain.freshness import LiveMarketSettings  # noqa: E402
from quantlab.trading.ports.contracts import DataBatch, HistoryBar, SubscriptionReceipt  # noqa: E402


KEY = 'BENCH:2330'
END = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
SIZES = (1_000, 8_100, 43_200)
PERIODS = ('1m', '5m', '1d')


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


def service_with(bars):
    service = LiveMarketService(HistoryMarket(bars), Clock(), Resolver(), settings=LiveMarketSettings(buffer_trade_days=40))
    service.allocate((KEY,))
    service.backfill(KEY, END - timedelta(minutes=bars + 1), END)
    return service


def full_read(service, period):
    """The former sector-board read: every page, revision-pinned after the first."""
    page = service.series(MarketSeriesQuery(KEY, period))
    pages = [page]
    bars = page.bars
    while page.next_offset is not None:
        page = service.series(MarketSeriesQuery(KEY, period, offset=page.next_offset, market_revision=page.market_revision))
        pages.append(page)
        bars += page.bars
    return bars, pages


def tail_read(service, period, tail, total):
    """One read of the last `tail` bars of a series whose length the caller already holds (as the UI cache does)."""
    page = service.series(MarketSeriesQuery(KEY, period, offset=max(0, total - tail)))
    return page.bars, [page]


def measure(read, repeat):
    runs, result = [], None
    for _ in range(repeat):
        started = time.perf_counter()
        result = read()
        runs.append((time.perf_counter() - started) * 1000)
    bars, pages = result
    size = sum(len(dumps(bar).encode('utf-8')) for bar in bars)
    return statistics.median(runs), len(bars), len(pages), size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--tail', type=int, default=240)
    args = parser.parse_args(argv)
    print(f'python {sys.version.split()[0]}; repeat {args.repeat}; tail {args.tail}; median ms; bytes = encoded bars')
    print('1m bars | period | read | median_ms | bars | pages | bytes')
    for count in SIZES:
        service = service_with(count)
        for period in PERIODS:
            service.series(MarketSeriesQuery(KEY, period, limit=1))  # warm the view cache like a live UI
            total = len(full_read(service, period)[0])
            for name, read in (('full', lambda: full_read(service, period)), ('tail', lambda: tail_read(service, period, args.tail, total))):
                ms, bars, pages, size = measure(read, args.repeat)
                print(f'{count} | {period} | {name} | {ms:.1f} | {bars} | {pages} | {size}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
