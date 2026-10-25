"""Atomic load evidence publication, independent of optional native Qt."""

import json
from pathlib import Path

from quantlab.runtime_support import atomic_write


def write_report(path: Path, value: dict[str, object]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))
