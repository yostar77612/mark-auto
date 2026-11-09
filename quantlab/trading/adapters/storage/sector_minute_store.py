"""Per-minute sector statistics (sector_minutes.sqlite3); 30 trading days, never blocks the board on failure."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import RLock

from quantlab.trading.domain.sector_alerts import MinuteStat
from quantlab.trading.domain.validation import DomainError

RETAIN_DAYS = 30
SCHEMA = '''
CREATE TABLE IF NOT EXISTS sector_minutes (
    trade_date TEXT NOT NULL, minute TEXT NOT NULL, group_id TEXT NOT NULL,
    amount INTEGER NOT NULL, cumulative INTEGER NOT NULL, amount_share_bps INTEGER NOT NULL,
    equal_pct_bps INTEGER NOT NULL, breadth_bps INTEGER NOT NULL,
    limit_up INTEGER NOT NULL, limit_down INTEGER NOT NULL, members INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    PRIMARY KEY (trade_date, minute, group_id));
'''
COLUMNS = 12


class SectorMinuteStore:
    def __init__(self, path: Path):
        if not path.is_absolute() or path.is_symlink():
            raise DomainError('validation_failed', 'absolute regular sector minute path required')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self._lock = path, RLock()
        self._db = sqlite3.connect(path, timeout=2, check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.executescript(SCHEMA)
        if len(self._db.execute('PRAGMA table_info(sector_minutes)').fetchall()) != COLUMNS:
            self._db.close()
            raise DomainError('sector_minutes_unavailable', 'unsupported sector minute schema')
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def append(self, stats: tuple[MinuteStat, ...], trade_date: date) -> None:
        rows = [
            (
                trade_date.isoformat(),
                item.minute.astimezone(timezone.utc).strftime('%H:%M'),
                item.group_id,
                item.amount,
                item.cumulative,
                item.share_bps,
                item.equal_pct_bps,
                item.breadth_bps,
                item.limit_up,
                item.limit_down,
                item.members,
                int(item.complete),
            )
            for item in stats
        ]
        try:
            with self._lock:
                self._db.executemany('INSERT OR REPLACE INTO sector_minutes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', rows)
                self._db.commit()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'append') from None

    def load_day(self, trade_date: date) -> tuple[MinuteStat, ...]:
        try:
            with self._lock:
                rows = self._db.execute('SELECT * FROM sector_minutes WHERE trade_date=? ORDER BY minute, group_id', (trade_date.isoformat(),)).fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'load') from None
        result = []
        for day, minute, group_id, amount, cumulative, share, pct, breadth, up, down, members, complete in rows:
            stamp = datetime.fromisoformat(f'{day}T{minute}:00+00:00')
            result.append(MinuteStat(stamp, group_id, amount, cumulative, share, pct, breadth, up, down, members, bool(complete)))
        return tuple(result)

    def purge(self, today: date) -> int:
        cutoff = (today - timedelta(days=RETAIN_DAYS)).isoformat()
        try:
            with self._lock:
                removed = self._db.execute('DELETE FROM sector_minutes WHERE trade_date < ?', (cutoff,)).rowcount
                self._db.commit()
            return removed
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'purge') from None
