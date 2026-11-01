"""Read-only SinoPac market-data probe for the M1 spec's open questions.

Run it yourself. It reads the API key pair stored by tools/store_sinopac_key.py,
logs in without trade reports, never touches CA, accounts or orders, queries
usage and a few days of 1-minute K-bars, then logs out. Secrets are never
printed or written; results go to the console and build/m1_probe_result.json.
"""

from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TARGET = 'MarkAuto/v2/broker/sinopac'
CODES = ('IX0001', 'IX0043', '2330', '6104')
OUT = Path(__file__).resolve().parents[1] / 'build' / 'm1_probe_result.json'


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]


def read_keys() -> tuple[str, str]:
    advapi = ctypes.windll.advapi32
    pointer = ctypes.POINTER(_Credential)()
    if not advapi.CredReadW(TARGET, 1, 0, ctypes.byref(pointer)):
        raise SystemExit(f'找不到 {TARGET}，請先執行 tools/store_sinopac_key.py')
    try:
        cred = pointer.contents
        value = json.loads(bytes(cred.CredentialBlob[: cred.CredentialBlobSize]).decode('utf-8'))
    finally:
        advapi.CredFree(pointer)
    return value['api_key'], value['secret_key']


def usage(api) -> dict:
    raw = api.usage()
    return {name: getattr(raw, name, None) for name in ('connections', 'bytes', 'limit_bytes', 'remaining_bytes')}


def kbars(api, code: str, start: date, end: date) -> dict:
    contract = api.contracts.get(code)
    if contract is None:
        return {'found': False}
    bars = api.kbars(contract, start=start.isoformat(), end=end.isoformat())
    stamps = list(bars.ts)
    days = sorted({datetime.fromtimestamp(ts / 1e9, timezone.utc).date().isoformat() for ts in stamps})
    return {
        'found': True,
        'name': getattr(contract, 'name', ''),
        'bars': len(stamps),
        'days': days,
        'first_close': str(bars.Close[0]) if stamps else None,
        'last_close': str(bars.Close[-1]) if stamps else None,
    }


def probe(simulation: bool, keys: tuple[str, str], start: date, end: date) -> dict:
    import shioaji as sj

    api = sj.Shioaji(simulation=simulation)
    result: dict = {'sdk': sj.__version__, 'scanner_api': hasattr(api, 'subscribe_scanner')}
    try:
        api.login(api_key=keys[0], secret_key=keys[1], subscribe_trade=False)
    except Exception as exc:
        result['login'] = f'失敗：{type(exc).__name__}'
        return result
    result['login'] = '成功'
    try:
        result['usage_before'] = usage(api)
        result['kbars'] = {}
        for code in CODES:
            try:
                result['kbars'][code] = kbars(api, code, start, end)
            except Exception as exc:
                result['kbars'][code] = {'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
        result['usage_after'] = usage(api)
    finally:
        api.logout()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('sim', 'live', 'both'), default='both', help='sim=模擬環境、live=正式行情（仍不下單）')
    parser.add_argument('--days', type=int, default=5, help='查詢最近幾個日曆天的 1 分 K（1–29）')
    args = parser.parse_args()
    end = date.today()
    start = end - timedelta(days=min(max(args.days, 1), 29) - 1)
    keys = read_keys()
    modes = {'sim': (True,), 'live': (False,), 'both': (True, False)}[args.mode]
    report = {'run_at': datetime.now(timezone.utc).isoformat(), 'range': [start.isoformat(), end.isoformat()]}
    for simulation in modes:
        label = 'simulation' if simulation else 'live'
        print(f'== {label} ==')
        report[label] = probe(simulation, keys, start, end)
        print(json.dumps(report[label], ensure_ascii=False, indent=2))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'結果已存到 {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
