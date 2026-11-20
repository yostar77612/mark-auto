"""Offline timing of LiveMarketService.poll() under retained tick losses (OPT-1 P9).

One instrument whose history and live deques each hold about 43,200 one-minute bars (the 30-trade-day
bound), `losses` older retained TickLoss envelopes, then one poll() that drains 1,000 ticks and a batch
of new losses. No network, broker or credentials. Usage: python tools/bench_tick_loss.py [--repeat N] [--batch B]
"""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.trading.application.live_market import LiveBar, LiveMarketService  # noqa: E402
from quantlab.trading.domain.freshness import LiveMarketSettings  # noqa: E402
from quantlab.trading.domain.ticks import Tick  # noqa: E402
from quantlab.trading.ports.contracts import SubscriptionReceipt  # noqa: E402
from quantlab.trading.ports.tick_stream import TickLoss  # noqa: E402

KEY = 'BENCH:2330'
NOW = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
BARS = 43_200
LOSSES = (0, 100, 1_000, 10_000)
TICKS = 1_000


class Clock:
    def now(self):
        return NOW


class Resolver:
    def session_at(self, instrument_id, timestamp):
        return timestamp.date(), 'DAY'


class Market:
    """Ticks and losses handed out once per poll by the benchmark."""

    def __init__(self):
        self.ticks, self.losses = (), ()

    def subscribe(self, instrument_ids):
        return SubscriptionReceipt('bench-sub', tuple(instrument_ids), True, NOW)

    def unsubscribe(self, subscription_id):
        pass

    def history(self, instrument_id, start, end):
        raise AssertionError('no history reads in this benchmark')

    def drain_ticks(self, max_items):
        ticks, self.ticks = self.ticks, ()
        return ticks

    def drain_tick_losses(self):
        losses, self.losses = self.losses, ()
        return losses


def bar(start):
    price = Decimal('600.5')
    return LiveBar(KEY, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price + 1, price - 1, price, 10, final=True)


def prepared(retained):
    market = Market()
    service = LiveMarketService(market, Clock(), Resolver(), settings=LiveMarketSettings(buffer_trade_days=30))
    service.allocate((KEY,))
    buffer = service._buffers[KEY]
    first = NOW - timedelta(minutes=2 * BARS)
    buffer.history.extend(bar(first + timedelta(minutes=i)) for i in range(BARS))
    buffer.live.extend(bar(first + timedelta(minutes=BARS + i)) for i in range(BARS - 1))
    buffer.first_live_start = buffer.live[0].start
    # Retained losses: one-minute envelopes spread over the older half of the window.
    buffer.losses.extend(TickLoss(KEY, first + timedelta(minutes=3 * i), first + timedelta(minutes=3 * i), 1) for i in range(retained))
    return service, market


def ticks():
    start = NOW - timedelta(seconds=TICKS // 20)
    return tuple(
        Tick(KEY, Decimal('600.5') + (i % 3), 1, start + timedelta(milliseconds=50 * i), start + timedelta(milliseconds=50 * i), NOW.date(), sequence=i)
        for i in range(TICKS)
    )


def batch(size):
    return tuple(TickLoss(KEY, NOW - timedelta(minutes=1 + i), NOW - timedelta(minutes=1 + i), 3) for i in range(size))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--batch', type=int, default=10)
    args = parser.parse_args(argv)
    print(f'python {sys.version.split()[0]}; repeat {args.repeat}; {TICKS} ticks; new-loss batch {args.batch}; median ms of one poll()')
    print('retained losses | ticks only | ticks + loss batch')
    feed = ticks()
    for retained in LOSSES:
        results = []
        for with_losses in (False, True):
            runs = []
            for _ in range(args.repeat):
                service, market = prepared(retained)
                market.ticks = feed
                market.losses = batch(args.batch) if with_losses else ()
                started = time.perf_counter()
                service.poll(connected=True, in_session=True)
                runs.append((time.perf_counter() - started) * 1000)
            results.append(statistics.median(runs))
        print(f'{retained} | {results[0]:.1f} | {results[1]:.1f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
