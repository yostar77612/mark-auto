"""Measure offline chart replacement and full-buffer polls; no broker or UI workflow."""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def measure(label, action, count):
    samples = []
    for _ in range(count):
        start = perf_counter()
        action()
        samples.append((perf_counter() - start) * 1000)
    print(f'{label}: ms={samples}; median={statistics.median(samples):.3f}; max={max(samples):.3f}')


def chart(count):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from desktop_charts import CandlestickChart
    from quantlab.market import InstrumentRef, MarketBar

    app = QApplication.instance() or QApplication([])
    widget = CandlestickChart()
    ref = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202610', '202610')
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bars = tuple(
        MarketBar(
            ref,
            (start + timedelta(minutes=i)).date().isoformat(),
            'day',
            Decimal(100),
            Decimal(102),
            Decimal(99),
            Decimal(101),
            1,
            interval='1m',
            timestamp=start + timedelta(minutes=i),
            end=start + timedelta(minutes=i + 1),
            session_open=start,
            session_end=start + timedelta(minutes=34001),
        )
        for i in range(34000)
    )
    measure('set_series 34000 (validation/update scheduling; excludes painting)', lambda: widget.set_series(bars), count)
    widget.close()
    app.processEvents()


def poll(count):
    from quantlab.trading.application.live_market import LiveMarketService
    from quantlab.trading.domain.live_bars import LiveBar
    from quantlab.trading.domain.ticks import Tick
    from quantlab.trading.ports.contracts import SubscriptionReceipt

    class Fixture:
        value = datetime(2026, 10, 28, 1, tzinfo=timezone.utc)
        sequence = 0
        ticks = ()

        def now(self):
            return self.value

        def session_at(self, key, timestamp):
            return timestamp.date(), 'DAY'

        def subscribe(self, keys):
            return SubscriptionReceipt(keys[0], keys, True, self.value)

        def drain_ticks(self, limit):
            ticks, self.ticks = self.ticks[:limit], self.ticks[limit:]
            return ticks

    fixture = Fixture()
    service = LiveMarketService(fixture, fixture, fixture)
    keys = tuple(f'PROBE:{i}' for i in range(20))
    service.allocate(keys)
    price = Decimal(100)
    for key, buffer in service._buffers.items():
        buffer.history.extend(
            LiveBar(
                key,
                fixture.value - timedelta(minutes=34200 - i),
                fixture.value - timedelta(minutes=34199 - i),
                (fixture.value - timedelta(minutes=34200 - i)).date(),
                'DAY',
                price,
                price,
                price,
                price,
                1,
                final=True,
            )
            for i in range(34200)
        )

    def update():
        fixture.sequence += 1
        fixture.value += timedelta(milliseconds=500)
        fixture.ticks = tuple(
            Tick(key, price, 1, fixture.value, fixture.value, fixture.value.date(), 'DAY', fixture.sequence * 5 + j, 'PROBE') for key in keys for j in range(5)
        )
        service.poll(in_session=True)
        service.views()
        service.overview()

    measure('poll+snapshot 20 x 34200 history, 100 accepted ticks/batch', update, count)
    measure('quiet poll+snapshot', lambda: (service.poll(in_session=True), service.views(), service.overview()), count)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('chart', 'poll'))
    parser.add_argument('--calls', type=int, default=10)
    args = parser.parse_args()
    print(f'host={platform.node()}; {platform.platform()}; CPU={platform.processor()}; Python={sys.version}; Qt={os.environ.get("QT_QPA_PLATFORM")}')
    (chart if args.mode == 'chart' else poll)(args.calls)
