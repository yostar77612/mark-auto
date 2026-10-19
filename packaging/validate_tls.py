"""Bounded standalone frozen Python TLS gate; no accounts, models or downloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_tls_smoke import safe_path, validate_report


def validate(executable, report):
    executable = safe_path(Path(executable), file=True)
    report = safe_path(Path(report))
    if report.exists():
        raise ValueError('Refusing stale or existing TLS evidence')
    # The executable contains no child-process launch for this dedicated path.
    # subprocess.run kills and joins the sole process on timeout.
    subprocess.run(
        [str(executable), '--tls-smoke', str(report)], check=True, timeout=30, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    report = safe_path(report, file=True)
    if report.stat().st_size > 65536:
        raise ValueError('TLS evidence exceeds byte bound')
    result = json.loads(report.read_text(encoding='utf-8'))
    validate_report(result, ROOT / 'packaging' / 'qt_notices' / 'manifest.json')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        validate(args.executable, args.report)
    except Exception as exc:
        print('Frozen TLS validation refused: ' + type(exc).__name__)
        return 1
    print('Frozen Python TLS fixture passed; public trust, accounts and models are not validated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
