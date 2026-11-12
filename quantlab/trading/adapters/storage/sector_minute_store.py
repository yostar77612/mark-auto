"""Per-minute sector statistics (sector_minutes.sqlite3); 30 trading days, never blocks the board on failure."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import RLock
from zoneinfo import ZoneInfo

from quantlab.trading.domain.sector_alerts import MinuteStat
from quantlab.trading.domain.validation import DomainError

RETAIN_DAYS = 30
TAIPEI = ZoneInfo('Asia/Taipei')
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
# Last alert per (kind, group, direction) of a trading day, so a restart keeps the cooldown. A separate table:
# builds that predate it only check sector_minutes and keep working on the same file.
MARKS = '''
CREATE TABLE IF NOT EXISTS sector_alert_marks (
    trade_date TEXT NOT NULL, kind TEXT NOT NULL, group_id TEXT NOT NULL, direction TEXT NOT NULL, minute TEXT NOT NULL,
    PRIMARY KEY (trade_date, kind, group_id, direction));
'''


class SectorMinuteStore:
    def __init__(self, path: Path):
        if not path.is_absolute() or path.is_symlink():
            raise DomainError('validation_failed', 'absolute regular sector minute path required')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self._lock = path, RLock()
        self.warning = ''
        try:
            self._open()
        except (sqlite3.DatabaseError, DomainError):
            # Set the unreadable file aside (it may hold history) and start a fresh one.
            try:
                self._db.close()
            except (AttributeError, sqlite3.Error):
                pass
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            try:
                path.rename(path.with_name(path.name + '.bad-' + stamp))
            except OSError:
                raise DomainError('sector_minutes_unavailable', 'cannot set the damaged file aside') from None
            self.warning = 'sector_minutes_corrupt'
            self._open()

    def _open(self) -> None:
        self._db = sqlite3.connect(self.path, timeout=2, check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.executescript(SCHEMA + MARKS)
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
                item.minute.astimezone(TAIPEI).strftime('%H:%M'),
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
            stamp = datetime.fromisoformat(f'{day}T{minute}:00+08:00')
            result.append(MinuteStat(stamp, group_id, amount, cumulative, share, pct, breadth, up, down, members, bool(complete)))
        return tuple(result)

    def purge(self, today: date) -> int:
        cutoff = (today - timedelta(days=RETAIN_DAYS)).isoformat()
        try:
            with self._lock:
                removed = self._db.execute('DELETE FROM sector_minutes WHERE trade_date < ?', (cutoff,)).rowcount
                self._db.execute('DELETE FROM sector_alert_marks WHERE trade_date < ?', (today.isoformat(),))
                self._db.commit()
            return removed
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'purge') from None

    def mark_alert(self, trade_date: date, kind: str, group_id: str, direction: str, minute: datetime) -> None:
        row = (trade_date.isoformat(), kind, group_id, direction, minute.astimezone(TAIPEI).strftime('%H:%M'))
        try:
            with self._lock:
                self._db.execute('INSERT OR REPLACE INTO sector_alert_marks VALUES (?,?,?,?,?)', row)
                self._db.commit()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'mark') from None

    def alert_marks(self, trade_date: date, kind: str) -> dict[tuple[str, str], datetime]:
        try:
            with self._lock:
                rows = self._db.execute(
                    'SELECT group_id, direction, minute FROM sector_alert_marks WHERE trade_date=? AND kind=?', (trade_date.isoformat(), kind)
                ).fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'marks') from None
        day = trade_date.isoformat()
        return {(group_id, direction): datetime.fromisoformat(f'{day}T{minute}:00+08:00') for group_id, direction, minute in rows}

    def share_baseline(self, before: date, minute: str, days: int = 5) -> dict[str, tuple[int, int]]:
        """Average cumulative share (bps) per group at `minute` (HH:MM) over the latest `days` stored trading days
        before `before`; each day contributes its last stored minute at or before `minute`. -> {group: (bps, days)}"""
        query = '''
            WITH days AS (
                SELECT DISTINCT trade_date FROM sector_minutes WHERE trade_date < ? ORDER BY trade_date DESC LIMIT ?
            ), last AS (
                SELECT trade_date, group_id, MAX(minute) AS minute FROM sector_minutes
                WHERE trade_date IN (SELECT trade_date FROM days) AND minute <= ? AND amount_share_bps > 0
                GROUP BY trade_date, group_id
            )
            SELECT s.group_id, AVG(s.amount_share_bps), COUNT(*) FROM sector_minutes s
            JOIN last l ON s.trade_date = l.trade_date AND s.group_id = l.group_id AND s.minute = l.minute
            GROUP BY s.group_id
        '''
        try:
            with self._lock:
                rows = self._db.execute(query, (before.isoformat(), days, minute)).fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'baseline') from None
        return {group_id: (round(average), count) for group_id, average, count in rows}

    def trade_days(self) -> tuple[date, ...]:
        """Stored trading days, newest first."""
        try:
            with self._lock:
                rows = self._db.execute('SELECT DISTINCT trade_date FROM sector_minutes ORDER BY trade_date DESC').fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'days') from None
        return tuple(date.fromisoformat(day) for (day,) in rows)

    def day_minutes(self, trade_date: date) -> tuple[str, ...]:
        """Stored minutes (HH:MM, Taipei) of one day in order."""
        try:
            with self._lock:
                rows = self._db.execute('SELECT DISTINCT minute FROM sector_minutes WHERE trade_date=? ORDER BY minute', (trade_date.isoformat(),)).fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'minutes') from None
        return tuple(minute for (minute,) in rows)

    def load_minute(self, trade_date: date, minute: str) -> tuple[MinuteStat, ...]:
        try:
            with self._lock:
                rows = self._db.execute(
                    'SELECT * FROM sector_minutes WHERE trade_date=? AND minute=? ORDER BY group_id', (trade_date.isoformat(), minute)
                ).fetchall()
        except sqlite3.Error:
            raise DomainError('sector_minutes_unavailable', 'minute') from None
        return tuple(
            MinuteStat(datetime.fromisoformat(f'{day}T{hhmm}:00+08:00'), group_id, amount, cumulative, share, pct, breadth, up, down, members, bool(complete))
            for day, hhmm, group_id, amount, cumulative, share, pct, breadth, up, down, members, complete in rows
        )
