"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

import os
import time
from quantlab import __version__
from quantlab.runtime_support import atomic_write
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import _json_bytes


def _verify_replay_runtime(value):
    """Validate the shared WAL runtime requirement for replay and walk-forward."""
    if not {'sqlite_replay', 'sqlite_walk_forward'} & set(value):
        return
    # Keep operation-specific dependencies out of module startup.
    import sqlite3

    # Keep operation-specific dependencies out of module startup.
    from contextlib import closing

    with closing(sqlite3.connect(':memory:')) as connection:
        version = connection.execute('SELECT sqlite_version()').fetchone()[0]
    try:
        actual = tuple(int(part) for part in version.split('.'))
    except (ValueError, AttributeError):
        actual = ()
    if actual != sqlite3.sqlite_version_info or actual < (3, 51, 3):
        raise RuntimeSafetyError('This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)')


class RuntimeGuard:
    """Every startup and clock discontinuity requires explicit paper reconciliation."""

    def __init__(self, paths):
        self.paths = paths
        self.marker = paths.root / 'session.json'
        self.wall, self.mono = time.time(), time.monotonic()
        self.reconciliation_required = True

    def start(self):
        self.paths.ensure()
        unclean = self.marker.exists()
        atomic_write(self.marker, _json_bytes({'pid': os.getpid(), 'started_at': time.time(), 'version': __version__}))
        return unclean

    def check_clock(self):
        wall, mono = time.time(), time.monotonic()
        gap = mono - self.mono
        changed = gap > 15 or gap < 0 or abs((wall - self.wall) - gap) > 5
        self.wall, self.mono = wall, mono
        if changed:
            self.reconciliation_required = True
        return changed

    def finish(self):
        self.marker.unlink(missing_ok=True)
