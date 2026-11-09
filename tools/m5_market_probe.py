"""Read-only SinoPac market-data probe for the M5 spec's M5-0 questions.

Run it yourself during trading hours. It reuses the credential reader of
tools/m1_market_probe.py, logs in without trade reports, never touches CA,
accounts or orders, measures full-market snapshot timing, the industry
`category` codes and the snapshot `tick_type` values, then logs out.
Secrets are never printed or written; results go to the console and
build/m5_probe_result.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from m1_market_probe import read_keys

OUT = Path(__file__).resolve().parents[1] / 'build' / 'm5_probe_result.json'
BATCH = 500


def stock_contracts(api) -> list:
    contracts = []
    for market in (api.Contracts.Stocks.TSE, api.Contracts.Stocks.OTC):
        contracts.extend(c for c in market if len(c.code) == 4 and c.code.isdigit() and not c.code.startswith('00'))
    return contracts


def snapshot_rounds(api, contracts: list, rounds: int) -> dict:
    timings: list[float] = []
    tick_types: Counter = Counter()
    change_types: Counter = Counter()
    rows = 0
    for _ in range(rounds):
        started = time.monotonic()
        rows = 0
        for index in range(0, len(contracts), BATCH):
            for snap in api.snapshots(contracts[index : index + BATCH]):
                rows += 1
                tick_types[str(snap.tick_type)] += 1
                change_types[str(snap.change_type)] += 1
        timings.append(time.monotonic() - started)
    return {
        'contracts': len(contracts),
        'batches': -(-len(contracts) // BATCH),
        'rows_last_round': rows,
        'seconds_per_round': [round(value, 2) for value in timings],
        'seconds_median': round(statistics.median(timings), 2),
        'tick_type_counts': dict(tick_types),
        'change_type_counts': dict(change_types),
    }


def probe(simulation: bool, keys: tuple[str, str], rounds: int) -> dict:
    import shioaji as sj

    api = sj.Shioaji(simulation=simulation)
    result: dict = {'sdk': sj.__version__}
    try:
        api.login(api_key=keys[0], secret_key=keys[1], subscribe_trade=False)
    except Exception as exc:
        result['login'] = f'失敗：{type(exc).__name__}'
        return result
    result['login'] = '成功'
    try:
        contracts = stock_contracts(api)
        result['categories'] = dict(Counter(getattr(c, 'category', '') for c in contracts).most_common())
        result['category_samples'] = {c.code: getattr(c, 'category', '') for c in contracts if c.code in ('2330', '2317', '3017', '6669')}
        result['snapshots'] = snapshot_rounds(api, contracts, rounds)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
    finally:
        api.logout()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('sim', 'live', 'both'), default='live', help='sim=模擬環境、live=正式行情（仍不下單）')
    parser.add_argument('--rounds', type=int, default=3, help='全市場快照重複輪數（1–10）')
    args = parser.parse_args()
    keys = read_keys()
    modes = {'sim': (True,), 'live': (False,), 'both': (True, False)}[args.mode]
    report = {'run_at': datetime.now(timezone.utc).isoformat()}
    for simulation in modes:
        label = 'simulation' if simulation else 'live'
        print(f'== {label} ==')
        report[label] = probe(simulation, keys, min(max(args.rounds, 1), 10))
        print(json.dumps(report[label], ensure_ascii=False, indent=2))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'結果已存到 {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
