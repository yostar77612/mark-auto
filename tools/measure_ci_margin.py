"""Opt-in measurement of the phases behind the fixed CI budgets (P3-01); changes no timeout."""

import argparse
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Fixed budgets used by the diagnostics and smoke tests; reported only to compute headroom.
BUDGETS = {'paper_diagnostics_seconds': 10.0, 'smoke_seconds': 40.0}
COMMITS = 120


def summarize(samples):
    """Median/min/max of non-empty numeric samples."""
    values = [float(value) for value in samples]
    if not values:
        raise ValueError('No samples')
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values), 'n': len(values)}


def headroom(median_seconds, budget_seconds):
    """How many times the budget exceeds one measured phase; None for unusable input."""
    if type(median_seconds) not in (int, float) or median_seconds <= 0:
        return None
    return budget_seconds / median_seconds


def timed(function):
    started = time.perf_counter()
    function()
    return time.perf_counter() - started


def python_start():
    subprocess.run([sys.executable, '-c', 'pass'], check=True)


def runtime_import():
    subprocess.run([sys.executable, '-c', 'import quantlab.desktop_runtime'], cwd=ROOT, check=True)


def sqlite_commits():
    with tempfile.TemporaryDirectory() as directory:
        db = sqlite3.connect(os.path.join(directory, 'probe.sqlite3'))
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE replay(id INTEGER PRIMARY KEY, cursor INTEGER)')
        db.commit()
        for index in range(COMMITS):
            with db:
                db.execute('INSERT OR REPLACE INTO replay VALUES (1, ?)', (index,))
        db.close()


def measure(repeats):
    phases = {'python_start': python_start, 'runtime_import': runtime_import, 'sqlite_120_full_sync_commits': sqlite_commits}
    report = {'platform': sys.platform, 'python': sys.version.split()[0], 'repeats': repeats, 'phases': {}}
    for name, function in phases.items():
        stats = summarize(timed(function) for _ in range(repeats))
        stats['headroom_vs_paper_budget'] = headroom(stats['median'], BUDGETS['paper_diagnostics_seconds'])
        report['phases'][name] = stats
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    print(json.dumps(measure(args.repeats), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
