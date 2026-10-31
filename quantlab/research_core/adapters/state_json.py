"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

import json
from quantlab.windows_paths import native_path
from quantlab.shared.runtime_errors import RuntimeSafetyError


STATE_VERSION = 1


MAX_JSON = 1024 * 1024


def _json_bytes(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_JSON:
        raise RuntimeSafetyError('JSON size limit exceeded')
    return raw


def _read_json(path):
    path = native_path(path)
    if path.stat().st_size > MAX_JSON:
        raise RuntimeSafetyError('JSON size limit exceeded')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeSafetyError('Invalid JSON; original file preserved') from exc
