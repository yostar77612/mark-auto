"""Durable one-minute market cache; coverage describes successful queries, not bars."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from .daily_stock_store import DailyStockStorage
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer, trading_date


def _utc(value: datetime) -> str:
    return aware(value).astimezone(timezone.utc).isoformat(timespec='microseconds')


def _range(instrument_id: str, start: datetime, end: datetime) -> tuple[str, str, str]:
    identity(instrument_id)
    first, last = _utc(start), _utc(end)
    if first >= last:
        raise DomainError('validation_failed', 'empty history range')
    return instrument_id, first, last


def _bar_row(bar: LiveBar, source: str) -> tuple:
    identity(bar.instrument_id)
    identity(bar.session, 'session')
    trading_date(bar.trade_date)
    start, end = _utc(bar.start), _utc(bar.end)
    if bar.end - bar.start != timedelta(minutes=1) or bar.start.second or bar.start.microsecond or not bar.final or bar.incomplete:
        raise DomainError('validation_failed', 'only complete final minute bars may be cached')
    values = tuple(decimal_value(value, 'OHLC', nonnegative=True) for value in (bar.open, bar.high, bar.low, bar.close))
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
        raise DomainError('validation_failed', 'OHLC ordering')
    integer(bar.volume, 'volume')
    return (bar.instrument_id, start, end, bar.trade_date.isoformat(), bar.session, *(str(value) for value in values), bar.volume, source)


def _decode(row: tuple) -> LiveBar:
    try:
        bar = LiveBar(
            row[0],
            datetime.fromisoformat(row[1]),
            datetime.fromisoformat(row[2]),
            date.fromisoformat(row[3]),
            row[4],
            *(Decimal(value) for value in row[5:9]),
            row[9],
            final=True,
        )
        if row[10] not in ('SHIOAJI_KBARS', 'LIVE_TICKS'):
            raise ValueError('source')
        _bar_row(bar, row[10])
        return bar
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise DomainError('kline_store_unavailable', 'invalid cached minute') from None


class KlineStore:
    """Thread-safe SQLite cache with official-history precedence and preserved recovery."""

    def __init__(self, path: Path, *, arrival_clock=None):
        if sqlite3.sqlite_version_info < (3, 53, 0):
            raise DomainError('validation_failed', 'patched SQLite runtime required')
        if not path.is_absolute() or path.is_symlink():
            raise DomainError('validation_failed', 'absolute regular K-line path required')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = RLock()
        self.warning_code = ''
        self._arrival_clock = arrival_clock
        self.recovered_path: Path | None = None
        try:
            self._open()
        except (sqlite3.DatabaseError, DomainError) as exc:
            if isinstance(exc, sqlite3.OperationalError):
                self._db.close()
                raise DomainError('kline_store_unavailable', 'cache is temporarily unavailable') from None
            self._db.close()
            suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
            preserved = path.with_name(path.name + '.bad-' + suffix)
            # Keep the WAL beside the preserved database too: it may contain user data.
            for ending in ('', '-wal', '-shm'):
                original = Path(str(path) + ending)
                if original.exists():
                    original.rename(Path(str(preserved) + ending))
            self.recovered_path = preserved
            self.warning_code = 'kline_store_unavailable'
            self._open()

    def _open(self) -> None:
        self._db = sqlite3.connect(self.path, timeout=2, check_same_thread=False)
        if self._db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise DomainError('kline_store_unavailable', 'database integrity')
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        if self._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
            if self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall() != [('1',)]:
                raise DomainError('kline_store_unavailable', 'unsupported cache schema')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS bars_1m (
                instrument_id TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
                trade_date TEXT NOT NULL, session TEXT NOT NULL,
                open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
                volume INTEGER NOT NULL, source TEXT NOT NULL, PRIMARY KEY(instrument_id,start_utc));
            CREATE TABLE IF NOT EXISTS coverage (
                instrument_id TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL, PRIMARY KEY(instrument_id,start_utc));
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES('schema_version','1');
        ''')
        if self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall() != [('1',)]:
            raise DomainError('kline_store_unavailable', 'unsupported cache schema')
        for table, expected in (('bars_1m', 11), ('coverage', 3), ('meta', 2)):
            if len(self._db.execute(f'PRAGMA table_info({table})').fetchall()) != expected:
                raise DomainError('kline_store_unavailable', 'invalid cache schema')
        self._db.commit()
        self.daily = DailyStockStorage(self._db, self._lock, arrival_clock=self._arrival_clock)

    @property
    def revision(self) -> int:
        return self.daily.revision

    @property
    def verification_revision(self) -> int:
        return self.daily.verification_revision

    def import_daily(self, batch) -> None:
        self.daily.import_daily(batch)

    def official_payload_arrival(self, source_url, digest):
        return self.daily.official_payload_arrival(source_url, digest)

    def official_manifest_archive(self, source_digest):
        return self.daily.official_manifest_archive(source_digest)

    def official_payload(self, source_url, digest):
        return self.daily.official_payload(source_url, digest)

    def daily_history(self, instrument_id, start, end):
        return self.daily.daily_history(instrument_id, start, end)

    def daily_coverage(self, instrument_id, start, end):
        return self.daily.daily_coverage(instrument_id, start, end)

    def upsert(self, bars: tuple[LiveBar, ...], *, source: str = 'SHIOAJI_KBARS') -> None:
        if source not in ('SHIOAJI_KBARS', 'LIVE_TICKS'):
            raise DomainError('validation_failed', 'unknown minute source')
        rows = tuple(_bar_row(bar, source) for bar in bars)
        with self._lock, self._db:
            self.daily._observe_revision()
            result = self._db.executemany(
                '''
                INSERT INTO bars_1m VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id,start_utc) DO UPDATE SET
                end_utc=excluded.end_utc,trade_date=excluded.trade_date,session=excluded.session,
                open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,source=excluded.source
                WHERE bars_1m.source!='SHIOAJI_KBARS' OR excluded.source='SHIOAJI_KBARS'
            ''',
                rows,
            )
            self.daily._record_changes(result.rowcount, changed=bool(rows))

    def mark_coverage(self, instrument_id: str, start: datetime, end: datetime) -> None:
        instrument_id, first, last = _range(instrument_id, start, end)
        with self._lock, self._db:
            self.daily._observe_revision()
            ranges = self._db.execute(
                'SELECT start_utc,end_utc FROM coverage WHERE instrument_id=? AND end_utc>=? AND start_utc<=?', (instrument_id, first, last)
            ).fetchall()
            first = min([first, *(row[0] for row in ranges)])
            last = max([last, *(row[1] for row in ranges)])
            removed = self._db.execute('DELETE FROM coverage WHERE instrument_id=? AND end_utc>=? AND start_utc<=?', (instrument_id, first, last))
            inserted = self._db.execute('INSERT INTO coverage VALUES(?,?,?)', (instrument_id, first, last))
            self.daily._record_changes(removed.rowcount + inserted.rowcount)

    def missing_ranges(self, instrument_id: str, start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
        instrument_id, first, last = _range(instrument_id, start, end)
        with self._lock:
            rows = self._db.execute(
                'SELECT start_utc,end_utc FROM coverage WHERE instrument_id=? AND end_utc>? AND start_utc<? ORDER BY start_utc', (instrument_id, first, last)
            ).fetchall()
        missing = []
        for left, right in rows:
            if left > first:
                missing.append((datetime.fromisoformat(first), datetime.fromisoformat(min(left, last))))
            first = max(first, right)
        if first < last:
            missing.append((datetime.fromisoformat(first), datetime.fromisoformat(last)))
        return tuple(missing)

    def read(self, instrument_id: str, start: datetime, end: datetime) -> tuple[LiveBar, ...]:
        instrument_id, first, last = _range(instrument_id, start, end)
        with self._lock:
            rows = self._db.execute(
                'SELECT * FROM bars_1m WHERE instrument_id=? AND start_utc>=? AND start_utc<? ORDER BY start_utc', (instrument_id, first, last)
            ).fetchall()
        return tuple(_decode(row) for row in rows)

    def last_bar(self, instrument_id: str) -> LiveBar | None:
        identity(instrument_id)
        with self._lock:
            row = self._db.execute('SELECT * FROM bars_1m WHERE instrument_id=? ORDER BY start_utc DESC LIMIT 1', (instrument_id,)).fetchone()
        return _decode(row) if row is not None else None

    def queried_bars(self, day: date) -> int:
        with self._lock:
            row = self._db.execute('SELECT value FROM meta WHERE key=?', ('queried_bars:' + day.isoformat(),)).fetchone()
        return int(row[0]) if row else 0

    def instrument_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(row[0] for row in self._db.execute('SELECT instrument_id FROM bars_1m UNION SELECT instrument_id FROM bars_1d ORDER BY instrument_id'))

    def record_queried_bars(self, day: date, count: int) -> None:
        integer(count, 'queried bars')
        with self._lock, self._db:
            self.daily._observe_revision()
            result = self._db.execute(
                'INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+?',
                ('queried_bars:' + day.isoformat(), str(count), count),
            )
            self.daily._record_changes(result.rowcount)

    def close(self) -> None:
        with self._lock:
            self._db.close()
