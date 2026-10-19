"""Opt-in synthetic scale benchmark; no timing assertions and no real data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    if args.repeats < 5:
        parser.error('--repeats must be at least 5')
    from quantlab.backtest import run_backtest
    from quantlab.reporting import synthetic_dataset, save_dataset, demo_config
    from quantlab.strategies import builtin_strategies

    rows = []
    # NamedTemporaryFile uses inherited directory permissions on Windows.
    for count in (1000, 10000):
        data = synthetic_dataset(count)  # Public generator lives in reporting, not data.py.
        spec, config = builtin_strategies()[0], demo_config()
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as stream:
            path = Path(stream.name)
        try:
            save_dataset(data, path)
            size = path.stat().st_size
        finally:
            path.unlink()
        times = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            run_backtest(data, spec, config)
            times.append(time.perf_counter() - started)
        rows.append(dict(bars=count, bytes=size, median=statistics.median(times), min=min(times), max=max(times), samples=times))
    report = dict(python=sys.version, platform=platform.platform(), strategy=spec.strategy_id, repeats=args.repeats, rows=rows)
    raw = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(raw + '\n', encoding='utf-8')
    print(raw)
    print('\nbars         JSON bytes      median(s)       min(s)       max(s)')
    for row in rows:
        print(f"{row['bars']:6} {row['bytes']:16} {row['median']:14.6f} {row['min']:12.6f} {row['max']:12.6f}")


if __name__ == '__main__':
    main()
