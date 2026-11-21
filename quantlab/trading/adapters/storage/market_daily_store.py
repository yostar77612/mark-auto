"""Market-wide daily quotes (market_daily.sqlite3): one row per stock and trading day plus a ledger of what was fetched.

A separate file from the K-line store on purpose: it holds about 2,000 rows a day, and keeping it out of klines.sqlite3
keeps that store's integrity check as short as it was. Prices are stored as Decimal text, volumes in lots, amounts in NT$.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator

from quantlab.trading.domain.market_daily import MARKETS, DailyQuote, DailyRow
from quantlab.trading.domain.validation import DomainError, identity

RETAIN_DAYS = 500
SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    trade_date TEXT NOT NULL, code TEXT NOT NULL,
    open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
    volume INTEGER NOT NULL, amount INTEGER NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (trade_date, code));
CREATE INDEX IF NOT EXISTS daily_by_code ON daily (code, trade_date);
CREATE TABLE IF NOT EXISTS ledger (
    trade_date TEXT NOT NULL, market TEXT NOT NULL, url TEXT NOT NULL, rows INTEGER NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, market));
"""
_UPSERT = """
INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT (trade_date, code) DO UPDATE SET
    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
    volume=excluded.volume, amount=excluded.amount, source=excluded.source
WHERE excluded.source = 'OFFICIAL' OR daily.source <> 'OFFICIAL'
"""


class MarketDailyStore:
    def __init__(self, path: Path):
        if not path.is_absolute() or path.is_symlink():
            raise DomainError('validation_failed', 'absolute regular market daily path required')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self._lock = path, RLock()
        self.warning = ''
        self.revision = 0  # advances on every write, so readers can tell when a cached summary is stale
        try:
            self._open()
        except (sqlite3.DatabaseError, DomainError):
            # Set the unreadable file aside (the official data can be fetched again) and start a fresh one.
            try:
                self._db.close()
            except (AttributeError, sqlite3.Error):
                pass
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            try:
                path.rename(path.with_name(path.name + '.bad-' + stamp))
            except OSError:
                raise DomainError('market_daily_unavailable', 'cannot set the damaged file aside') from None
            self.warning = 'market_daily_corrupt'
            self._open()

    def _open(self) -> None:
        self._db = sqlite3.connect(self.path, timeout=2, check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.executescript(SCHEMA)
        if len(self._db.execute('PRAGMA table_info(daily)').fetchall()) != 9 or len(self._db.execute('PRAGMA table_info(ledger)').fetchall()) != 5:
            self._db.close()
            raise DomainError('market_daily_unavailable', 'unsupported market daily schema')
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def upsert(self, quotes: tuple[DailyQuote, ...]) -> None:
        """Official rows replace anything; a snapshot-derived row never replaces an official one."""
        rows = [
            (
                quote.trade_date.isoformat(),
                quote.code,
                str(quote.open),
                str(quote.high),
                str(quote.low),
                str(quote.close),
                quote.volume,
                quote.amount,
                quote.source,
            )
            for quote in quotes
        ]
        with self._lock, self._db:
            self._db.executemany(_UPSERT, rows)
            self.revision += 1

    def mark(self, trade_date: date, market: str, url: str, rows: int, at: datetime) -> None:
        """Record that one market's day was fetched (rows = 0 for a holiday), with the URL it came from."""
        if market not in MARKETS:
            raise DomainError('validation_failed', 'market')
        identity(url)
        with self._lock, self._db:
            self._db.execute(
                'INSERT OR REPLACE INTO ledger VALUES (?,?,?,?,?)', (trade_date.isoformat(), market, url, rows, at.astimezone(timezone.utc).isoformat())
            )
            self.revision += 1

    def fetched(self, trade_date: date) -> dict[str, int]:
        """market -> rows for the markets already fetched on that day."""
        with self._lock:
            return dict(self._db.execute('SELECT market, rows FROM ledger WHERE trade_date=?', (trade_date.isoformat(),)).fetchall())

    def trade_days(self, before: date, limit: int) -> tuple[date, ...]:
        """The latest `limit` trading days strictly before a date, ascending. A trading day is one with rows."""
        with self._lock:
            found = self._db.execute(
                'SELECT trade_date FROM ledger WHERE rows>0 AND trade_date<? GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?', (before.isoformat(), limit)
            ).fetchall()
        return tuple(date.fromisoformat(row[0]) for row in reversed(found))

    def history(self, before: date, days: int) -> Iterator[tuple[str, list[DailyRow]]]:
        """Each stock's rows over the latest `days` trading days before a date, ascending; one stock in memory at a time.

        The store is locked while the generator runs: finish it, do not leave it half consumed."""
        trading = self.trade_days(before, days)
        if not trading:
            return
        with self._lock:
            cursor = self._db.execute(
                'SELECT code, trade_date, high, volume, amount FROM daily WHERE trade_date>=? AND trade_date<? ORDER BY code, trade_date',
                (trading[0].isoformat(), before.isoformat()),
            )
            code, rows = None, []
            for row_code, row_date, high, volume, amount in cursor:
                if row_code != code and rows:
                    yield code, rows
                    rows = []
                code = row_code
                rows.append(DailyRow(date.fromisoformat(row_date), Decimal(high), volume, amount))
            if rows:
                yield code, rows

    def purge(self, today: date) -> int:
        cutoff = (today - timedelta(days=RETAIN_DAYS)).isoformat()
        with self._lock, self._db:
            removed = self._db.execute('DELETE FROM daily WHERE trade_date<?', (cutoff,)).rowcount
            self._db.execute('DELETE FROM ledger WHERE trade_date<?', (cutoff,))
            if removed:
                self.revision += 1
        return removed
