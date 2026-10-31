"""Read immutable pre-removal security evidence without importing legacy code.

A full repository checkout is required, as for quality_gate --history. Missing
objects fail the tests; there is no skip or fallback to a mutable source tree.
"""

from functools import cache
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = '909fc49'
PREFIX = 'archives/legacy_autotrading/'


@cache
def historical_bytes(path):
    path = str(path)
    if not path.startswith(PREFIX):
        path = PREFIX + path
    return subprocess.check_output(['git', 'show', f'{REVISION}:{path}'], cwd=ROOT)


def historical_text(path):
    return historical_bytes(path).decode('utf-8')


def historical_python_paths():
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', REVISION, '--', PREFIX + 'trader/'], cwd=ROOT).decode('utf-8').splitlines()
    result = tuple(path for path in paths if path.endswith('.py'))
    assert result, 'Historical security evidence must not be empty'
    return result
