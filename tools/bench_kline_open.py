"""Offline timing of KlineStore opening and its PRAGMA quick_check on large synthetic caches (OPT-1 P10).

Creates a K-line cache with KlineStore's own schema in a temporary directory, fills bars_1m with synthetic
one-minute rows until the file reaches each target size, then measures (a) the whole KlineStore(path)
construction after a clean close, which runs _open; (b) the same after an unclean exit (the open flag in
meta is left set, untimed, before each run), the path that still runs the full check; and (c) one PRAGMA
quick_check on a fresh connection. The OS file cache
is warm (the file was just written); a cold first open after reboot can only be slower. No network,
broker, credentials or user data. Usage: python tools/bench_kline_open.py [--repeat N] [--sizes 10,200,1024]
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.trading.adapters.storage.kline_store import KlineStore  # noqa: E402

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
BATCH = 50_000


def fill(path, target_bytes):
    """Append synthetic rows (200 instruments x consecutive minutes) until the file reaches target_bytes."""
    KlineStore(path).close()  # the store's own schema, meta and daily tables
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    minute, rows = 0, 0
    while path.stat().st_size < target_bytes:
        batch = []
        for _ in range(BATCH):
            instrument = f'TWSE:{1000 + rows % 200}'
            start = START + timedelta(minutes=minute)
            if rows % 200 == 199:
                minute += 1
            batch.append(
                (
                    instrument,
                    start.isoformat(),
                    (start + timedelta(minutes=1)).isoformat(),
                    start.date().isoformat(),
                    'DAY',
                    '600.5',
                    '601.5',
                    '599.5',
                    '600.5',
                    1000,
                    'BENCH',
                )
            )
            rows += 1
        with db:
            db.executemany('INSERT OR REPLACE INTO bars_1m VALUES (?,?,?,?,?,?,?,?,?,?,?)', batch)
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    db.close()
    return rows


def timed(action, repeat, setup=None):
    runs = []
    for _ in range(repeat):
        if setup:
            setup()
        started = time.perf_counter()
        action()
        runs.append((time.perf_counter() - started) * 1000)
    return statistics.median(runs)


def leave_open_flag(path):
    """What an exit without KlineStore.close() leaves behind."""
    db = sqlite3.connect(path)
    with db:
        db.execute("INSERT OR REPLACE INTO meta VALUES('open_state','open')")
    db.close()


def quick_check(path):
    db = sqlite3.connect(path, timeout=2)
    try:
        assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--sizes', default='10,200,1024', help='target sizes in MiB')
    args = parser.parse_args(argv)
    print(f'python {sys.version.split()[0]}; sqlite {sqlite3.sqlite_version}; repeat {args.repeat}; warm OS cache; median ms')
    print('target MiB | file MiB | rows | clean-close open ms | unclean-exit open ms | quick_check ms')
    with tempfile.TemporaryDirectory(prefix='bench-kline-') as folder:
        for size in (int(value) for value in args.sizes.split(',')):
            path = Path(folder) / f'klines-{size}.sqlite3'
            rows = fill(path, size * 1024 * 1024)
            opened = timed(lambda: KlineStore(path).close(), args.repeat)
            unclean = timed(lambda: KlineStore(path).close(), args.repeat, setup=lambda: leave_open_flag(path))
            check = timed(lambda: quick_check(path), args.repeat)
            print(f'{size} | {path.stat().st_size / 1048576:.1f} | {rows} | {opened:.1f} | {unclean:.1f} | {check:.1f}')
            path.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
