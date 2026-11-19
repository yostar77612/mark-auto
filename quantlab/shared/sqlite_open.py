"""The single `sqlite_uri(path) + '?mode=…'` SQLite open used by non-G3 stores (OPT-1 P4)."""

import sqlite3

from quantlab.windows_paths import sqlite_uri


def open_sqlite(path, *, mode: str, timeout: float) -> sqlite3.Connection:
    """Exactly `sqlite3.connect(sqlite_uri(path) + '?mode=' + mode, uri=True, timeout=timeout)`.

    `mode` is SQLite's own URI open mode ('ro', 'rw' or 'rwc'); no other URI option, isolation level,
    factory or VFS is introduced, so callers keep their exact former connection behaviour.
    """
    return sqlite3.connect(sqlite_uri(path) + '?mode=' + mode, uri=True, timeout=timeout)
