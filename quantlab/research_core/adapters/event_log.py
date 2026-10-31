"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.domain.job_protocol import OPERATIONS
from .state_json import _json_bytes


class RedactedEventLog:
    """Bounded local status log: only approved operation/status codes, never payloads."""

    MAX_BYTES = 128 * 1024
    EVENTS = frozenset({'started', 'progress', 'result', 'error', 'cancelled'})

    def __init__(self, path, *, error_codes):
        self.path = Path(path)
        self.error_codes = error_codes

    def append(self, operation, event_type, *, error_code=None):
        # Load the optional UI adapter only when this operation is requested.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        # Defer the adapter until this operation runs in its owning process.
        ERROR_TABLE = self.error_codes

        if error_code is not None and (type(error_code) is not str or error_code not in ERROR_TABLE):
            raise RuntimeSafetyError('Only fixed error codes can be logged')
        if operation not in OPERATIONS or event_type not in self.EVENTS:
            raise RuntimeSafetyError('Only fixed operation and event codes can be logged')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            BackupManager._check_regular_path(self.path)
            if self.path.stat().st_size >= self.MAX_BYTES:
                previous = self.path.with_suffix(self.path.suffix + '.1')
                if previous.exists():
                    BackupManager._check_regular_path(previous)
                os.replace(self.path, previous)
        record = {'time': round(time.time(), 3), 'operation': operation, 'event': event_type}
        if error_code is not None:
            record['error_code'] = error_code
        with self.path.open('ab') as stream:
            stream.write(_json_bytes(record) + b'\n')

    def tail(self, limit=200):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        if type(limit) is not int or not 1 <= limit <= 1000:
            raise RuntimeSafetyError('Log limit must be 1..1000')
        if not self.path.exists():
            return []
        BackupManager._check_regular_path(self.path)
        with self.path.open('rb') as stream:
            stream.seek(max(0, self.path.stat().st_size - self.MAX_BYTES))
            lines = stream.read(self.MAX_BYTES + 256).splitlines()
        result = []
        for raw in lines[-limit:]:
            try:
                value = json.loads(raw)
                if not isinstance(value, dict) or set(value) not in ({'time', 'operation', 'event'}, {'time', 'operation', 'event', 'error_code'}):
                    continue
                # Load the optional UI adapter only when this operation is requested.
                ERROR_TABLE = self.error_codes

                if 'error_code' in value and (type(value['error_code']) is not str or value['error_code'] not in ERROR_TABLE):
                    continue
                if value['operation'] not in OPERATIONS or value['event'] not in self.EVENTS or type(value['time']) not in (int, float):
                    continue
                result.append(json.dumps(value, ensure_ascii=False))
            except (ValueError, TypeError):
                continue
        return result
