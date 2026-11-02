"""Additive official daily/event tables in the existing M1 SQLite connection."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
import sqlite3
import json

from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError, identity, trading_date
from quantlab.trading.ports.stock_history import OfficialPayload, OfficialStockBatch


class DailyStockStorage:
    def __init__(self, db, lock):
        self.db, self.lock = db, lock
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS bars_1d (
                instrument_id TEXT NOT NULL, trade_date TEXT NOT NULL,
                open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
                volume INTEGER NOT NULL, source_digest TEXT NOT NULL, source TEXT NOT NULL CHECK(source='OFFICIAL'),
                PRIMARY KEY(instrument_id,trade_date));
            CREATE TABLE IF NOT EXISTS corporate_actions (
                instrument_id TEXT NOT NULL, ex_date TEXT NOT NULL, previous_close TEXT NOT NULL,
                reference_price TEXT NOT NULL, source_digest TEXT NOT NULL, source_url TEXT NOT NULL,
                PRIMARY KEY(instrument_id,ex_date));
            CREATE TABLE IF NOT EXISTS official_stock_payloads (
                source_url TEXT NOT NULL, digest TEXT NOT NULL, raw BLOB NOT NULL,
                PRIMARY KEY(source_url,digest));
            CREATE TABLE IF NOT EXISTS official_stock_batches (
                instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, sources TEXT NOT NULL,
                PRIMARY KEY(instrument_id,start_date,end_date));
            CREATE TABLE IF NOT EXISTS official_stock_coverage (
                instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                PRIMARY KEY(instrument_id,start_date,end_date));
        ''')
        self.db.commit()

    def import_daily(self, batch: OfficialStockBatch) -> None:
        identity(batch.instrument_id)
        trading_date(batch.start)
        trading_date(batch.end)
        if batch.start >= batch.end or not batch.bars or not batch.payloads:
            raise DomainError('official_stock_invalid', 'nonempty dated official import required')
        payloads = {(p.source_url, p.digest): p for p in batch.payloads}
        if len(payloads) != len(batch.payloads) or len(payloads) > 242:
            raise DomainError('official_stock_invalid', 'duplicate or excessive payloads')
        for item in batch.payloads:
            if not 0 < len(item.raw) <= 8 * 1024 * 1024 or sha256(item.raw).hexdigest() != item.digest:
                raise DomainError('official_stock_invalid', 'source payload hash mismatch')
            if not item.source_url.startswith(('https://www.twse.com.tw/', 'https://www.tpex.org.tw/')):
                raise DomainError('official_stock_invalid', 'official HTTPS source required')
        digests = {p.digest for p in batch.payloads}
        for items, attr in ((batch.bars, 'trade_date'), (batch.events, 'ex_date')):
            days = [getattr(item, attr) for item in items]
            if len(days) != len(set(days)) or any(not batch.start <= day < batch.end for day in days):
                raise DomainError('official_stock_invalid', 'duplicate or out-of-range observation')
            if any(item.instrument_id != batch.instrument_id or item.source_digest not in digests for item in items):
                raise DomainError('official_stock_invalid', 'observation source mismatch')
        if any((e.source_url, e.source_digest) not in payloads for e in batch.events):
            raise DomainError('official_stock_invalid', 'event source mismatch')
        try:
            self._publish(batch, payloads)
        except sqlite3.DatabaseError:
            raise DomainError('official_stock_invalid', 'daily import failed; original data retained') from None

    def _publish(self, batch, payloads):
        with self.lock, self.db:
            self.db.executemany('INSERT OR IGNORE INTO official_stock_payloads VALUES(?,?,?)', [(p.source_url, p.digest, p.raw) for p in batch.payloads])
            # A fully validated refresh replaces only its own half-open interval.
            # DELETE/INSERT share one transaction; any failure rolls everything back.
            for table, column in (('bars_1d', 'trade_date'), ('corporate_actions', 'ex_date')):
                self.db.execute(
                    f'DELETE FROM {table} WHERE instrument_id=? AND {column}>=? AND {column}<?',
                    (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat()),
                )
            self.db.executemany(
                'INSERT INTO bars_1d VALUES(?,?,?,?,?,?,?,?,?)',
                [
                    (b.instrument_id, b.trade_date.isoformat(), *(str(v) for v in (b.open, b.high, b.low, b.close)), b.volume, b.source_digest, b.source)
                    for b in batch.bars
                ],
            )
            self.db.executemany(
                'INSERT INTO corporate_actions VALUES(?,?,?,?,?,?)',
                [(e.instrument_id, e.ex_date.isoformat(), str(e.previous_close), str(e.reference_price), e.source_digest, e.source_url) for e in batch.events],
            )
            self.db.execute(
                'INSERT OR REPLACE INTO official_stock_batches VALUES(?,?,?,?)',
                (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat(), json.dumps(sorted(payloads))),
            )
            self.db.execute(
                'INSERT OR IGNORE INTO official_stock_coverage VALUES(?,?,?)', (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat())
            )

    def official_payload(self, source_url: str, digest: str) -> OfficialPayload:
        """Historical evidence resolves immutable payloads after later corrections."""
        with self.lock:
            row = self.db.execute('SELECT raw FROM official_stock_payloads WHERE source_url=? AND digest=?', (source_url, digest)).fetchone()
        if row is None or sha256(row[0]).hexdigest() != digest:
            raise DomainError('official_stock_invalid', 'historical source missing or corrupt')
        return OfficialPayload(source_url, digest, row[0])

    def daily_coverage(self, instrument_id: str, start: date, end: date) -> bool:
        identity(instrument_id)
        trading_date(start)
        trading_date(end)
        if end <= start:
            raise DomainError('validation_failed', 'daily range')
        with self.lock:
            ranges = self.db.execute(
                'SELECT start_date,end_date FROM official_stock_coverage WHERE instrument_id=? ORDER BY start_date', (instrument_id,)
            ).fetchall()
        cursor = start.isoformat()
        for first, last in ranges:
            if first > cursor:
                break
            cursor = max(cursor, last)
            if cursor >= end.isoformat():
                return True
        return False

    def daily_history(self, instrument_id: str, start: date, end: date) -> OfficialStockBatch:
        identity(instrument_id)
        trading_date(start)
        trading_date(end)
        if start >= end:
            raise DomainError('validation_failed', 'daily range')
        args = instrument_id, start.isoformat(), end.isoformat()
        try:
            with self.lock:
                rows = self.db.execute('SELECT * FROM bars_1d WHERE instrument_id=? AND trade_date>=? AND trade_date<? ORDER BY trade_date', args).fetchall()
                event_rows = self.db.execute(
                    'SELECT * FROM corporate_actions WHERE instrument_id=? AND ex_date>=? AND ex_date<? ORDER BY ex_date', args
                ).fetchall()
                bars = tuple(DailyStockBar(row[0], date.fromisoformat(row[1]), *(Decimal(v) for v in row[2:6]), row[6], row[7], row[8]) for row in rows)
                events = tuple(CorporateAction(row[0], date.fromisoformat(row[1]), Decimal(row[2]), Decimal(row[3]), row[4], row[5]) for row in event_rows)
                manifests = self.db.execute(
                    'SELECT sources FROM official_stock_batches WHERE instrument_id=? AND start_date<? AND end_date>?',
                    (instrument_id, end.isoformat(), start.isoformat()),
                ).fetchall()
                sources = {tuple(pair) for row in manifests for pair in json.loads(row[0])}
                payloads = tuple(
                    OfficialPayload(*row)
                    for source in sorted(sources)
                    for row in self.db.execute('SELECT source_url,digest,raw FROM official_stock_payloads WHERE source_url=? AND digest=?', source)
                )
            digests = {b.source_digest for b in bars} | {e.source_digest for e in events}
            if (
                not digests <= {p.digest for p in payloads}
                or {(p.source_url, p.digest) for p in payloads} != sources
                or any(sha256(p.raw).hexdigest() != p.digest for p in payloads)
            ):
                raise ValueError('missing/corrupt official provenance')
            return OfficialStockBatch(instrument_id, start, end, bars, events, payloads)
        except (ValueError, TypeError, ArithmeticError, sqlite3.DatabaseError):
            raise DomainError('official_stock_invalid', 'cached daily data/provenance invalid') from None
