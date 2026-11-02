"""Additive official daily/event tables in the existing M1 SQLite connection."""

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import sqlite3
import json
from collections.abc import Callable

from quantlab.trading.domain.stock_history import CashDividendAction, CorporateAction, DailyStockBar, valid_digest
from quantlab.trading.domain.validation import DomainError, aware, identity, trading_date
from quantlab.trading.ports.stock_history import OfficialPayload, OfficialStockBatch, OfficialStockManifest


MAX_HISTORY_SOURCES = 242
MAX_ACTIVE_MANIFESTS = 242
MAX_HISTORY_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024


class DailyStockStorage:
    def __init__(self, db, lock, *, arrival_clock: Callable[[], datetime] | None = None):
        self.db, self.lock = db, lock
        self.arrival_clock = arrival_clock if arrival_clock is not None else lambda: datetime.now(timezone.utc)
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
            CREATE TABLE IF NOT EXISTS stock_cash_entitlements (
                instrument_id TEXT NOT NULL, ex_date TEXT NOT NULL,
                cash_per_share TEXT NOT NULL, payment_date TEXT NOT NULL,
                source_digest TEXT NOT NULL, facts_digest TEXT NOT NULL,
                PRIMARY KEY(instrument_id,ex_date));
            CREATE TABLE IF NOT EXISTS official_stock_payloads (
                source_url TEXT NOT NULL, digest TEXT NOT NULL, raw BLOB NOT NULL,
                PRIMARY KEY(source_url,digest));
            CREATE TABLE IF NOT EXISTS official_stock_batches (
                instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, sources TEXT NOT NULL,
                PRIMARY KEY(instrument_id,start_date,end_date));
            CREATE TABLE IF NOT EXISTS official_stock_manifest_archive (
                archive_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL, sources TEXT NOT NULL,
                arrived_at TEXT, source_digest TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS official_stock_manifest_digest ON official_stock_manifest_archive(source_digest);
            CREATE TABLE IF NOT EXISTS official_stock_coverage (
                instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                PRIMARY KEY(instrument_id,start_date,end_date));
        ''')
        for table in ('official_stock_payloads', 'official_stock_batches'):
            if 'arrived_at' not in {row[1] for row in self.db.execute(f'PRAGMA table_info({table})')}:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN arrived_at TEXT')
        self.db.commit()
        self._revision = 0
        self._version = self.db.execute('PRAGMA data_version').fetchone()[0]
        self._schema = self.db.execute('PRAGMA schema_version').fetchone()[0]
        self._known_changes = self.db.total_changes

    @property
    def revision(self) -> int:
        try:
            with self.lock:
                self._observe_revision()
                return self._revision
        except sqlite3.DatabaseError:
            raise DomainError('official_stock_invalid', 'official cache revision unavailable') from None

    @property
    def verification_revision(self) -> int:
        if not self.lock.acquire(blocking=False):
            raise DomainError('official_stock_invalid', 'official cache is being updated')
        try:
            timeout = self.db.execute('PRAGMA busy_timeout').fetchone()[0]
            self.db.execute('PRAGMA busy_timeout=0')
            try:
                self._observe_revision()
                return self._revision
            finally:
                self.db.execute(f'PRAGMA busy_timeout={timeout}')
        except sqlite3.DatabaseError:
            raise DomainError('official_stock_invalid', 'official cache revision unavailable') from None
        finally:
            self.lock.release()

    def _observe_revision(self):
        version = self.db.execute('PRAGMA data_version').fetchone()[0]
        schema = self.db.execute('PRAGMA schema_version').fetchone()[0]
        changes = self.db.total_changes
        if version != self._version or schema != self._schema or changes != self._known_changes:
            self._revision += 1
        self._version, self._schema, self._known_changes = version, schema, changes

    def _record_changes(self, count, *, changed=False):
        self._known_changes += count
        if changed:
            self._revision += 1

    def _write(self, sql, parameters=()):
        result = self.db.execute(sql, parameters)
        self._record_changes(result.rowcount)
        return result

    def _write_many(self, sql, parameters):
        result = self.db.executemany(sql, parameters)
        self._record_changes(result.rowcount)
        return result

    def import_daily(self, batch: OfficialStockBatch) -> None:
        identity(batch.instrument_id)
        trading_date(batch.start)
        trading_date(batch.end)
        if batch.start >= batch.end or not batch.bars or not batch.payloads:
            raise DomainError('official_stock_invalid', 'nonempty dated official import required')
        payloads = {(p.source_url, p.digest): p for p in batch.payloads}
        if len(payloads) != len(batch.payloads) or len(payloads) > MAX_HISTORY_SOURCES:
            raise DomainError('official_stock_invalid', 'duplicate or excessive payloads')
        for item in batch.payloads:
            if not 0 < len(item.raw) <= 8 * 1024 * 1024 or sha256(item.raw).hexdigest() != item.digest:
                raise DomainError('official_stock_invalid', 'source payload hash mismatch')
            if not item.source_url.startswith(('https://www.twse.com.tw/', 'https://www.tpex.org.tw/')):
                raise DomainError('official_stock_invalid', 'official HTTPS source required')
        if len(json.dumps(sorted(payloads)).encode()) > MAX_MANIFEST_BYTES:
            raise DomainError('official_stock_invalid', 'official manifest byte limit')
        digests = {p.digest for p in batch.payloads}
        for items, attr in ((batch.bars, 'trade_date'), (batch.events, 'ex_date')):
            days = [getattr(item, attr) for item in items]
            if len(days) != len(set(days)) or any(not batch.start <= day < batch.end for day in days):
                raise DomainError('official_stock_invalid', 'duplicate or out-of-range observation')
            if any(item.instrument_id != batch.instrument_id or item.source_digest not in digests for item in items):
                raise DomainError('official_stock_invalid', 'observation source mismatch')
        if any((e.source_url, e.source_digest) not in payloads for e in batch.events):
            raise DomainError('official_stock_invalid', 'event source mismatch')
        if any(type(e) not in (CorporateAction, CashDividendAction) for e in batch.events):
            raise DomainError('official_stock_invalid', 'unsupported economic event facts')
        try:
            self._publish(batch, payloads)
        except (ValueError, TypeError, ArithmeticError, sqlite3.DatabaseError):
            raise DomainError('official_stock_invalid', 'daily import failed; original data retained') from None

    def _publish(self, batch, payloads):
        with self.lock:
            self._observe_revision()
            with self.db:
                arrived = aware(self.arrival_clock()).astimezone(timezone.utc).isoformat(timespec='microseconds')
                self._write_many(
                    'INSERT OR IGNORE INTO official_stock_payloads(source_url,digest,raw,arrived_at) VALUES(?,?,?,?)',
                    [(p.source_url, p.digest, p.raw, arrived) for p in batch.payloads],
                )
                self._write_many(
                    'UPDATE official_stock_payloads SET arrived_at=? WHERE source_url=? AND digest=?',
                    [(arrived, p.source_url, p.digest) for p in batch.payloads],
                )
                old_rows = self.db.execute(
                    'SELECT instrument_id,start_date,end_date,sources,arrived_at FROM official_stock_batches '
                    'WHERE instrument_id=? AND start_date>=? AND end_date<=?',
                    (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat()),
                )
                for row in old_rows:
                    self._archive_manifest(row)
                self._archive_manifest((batch.instrument_id, batch.start.isoformat(), batch.end.isoformat(), json.dumps(sorted(payloads)), arrived))
                self._write(
                    'DELETE FROM official_stock_batches WHERE instrument_id=? AND start_date>=? AND end_date<=?',
                    (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat()),
                )
                # A fully validated refresh replaces only its own half-open interval.
                # DELETE/INSERT share one transaction; any failure rolls everything back.
                for table, column in (('bars_1d', 'trade_date'), ('corporate_actions', 'ex_date'), ('stock_cash_entitlements', 'ex_date')):
                    self._write(
                        f'DELETE FROM {table} WHERE instrument_id=? AND {column}>=? AND {column}<?',
                        (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat()),
                    )
                self._write_many(
                    'INSERT INTO bars_1d VALUES(?,?,?,?,?,?,?,?,?)',
                    [
                        (b.instrument_id, b.trade_date.isoformat(), *(str(v) for v in (b.open, b.high, b.low, b.close)), b.volume, b.source_digest, b.source)
                        for b in batch.bars
                    ],
                )
                self._write_many(
                    'INSERT INTO corporate_actions VALUES(?,?,?,?,?,?)',
                    [
                        (e.instrument_id, e.ex_date.isoformat(), str(e.previous_close), str(e.reference_price), e.source_digest, e.source_url)
                        for e in batch.events
                    ],
                )
                self._write_many(
                    'INSERT INTO stock_cash_entitlements VALUES(?,?,?,?,?,?)',
                    [
                        (e.instrument_id, e.ex_date.isoformat(), str(e.cash_per_share), e.payment_date.isoformat(), e.source_digest, _cash_binding(e))
                        for e in batch.events
                        if isinstance(e, CashDividendAction)
                    ],
                )
                self._write(
                    'INSERT OR REPLACE INTO official_stock_batches(instrument_id,start_date,end_date,sources,arrived_at) VALUES(?,?,?,?,?)',
                    (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat(), json.dumps(sorted(payloads)), arrived),
                )
                count = self.db.execute('SELECT COUNT(*) FROM official_stock_batches WHERE instrument_id=?', (batch.instrument_id,)).fetchone()[0]
                if count > MAX_ACTIVE_MANIFESTS:
                    raise DomainError('official_stock_invalid', 'active official manifest limit')
                self._source_metadata(self._selected_sources(batch.instrument_id, batch.start, batch.end))
                ranges = self.db.execute(
                    'SELECT start_date,end_date FROM official_stock_coverage WHERE instrument_id=? AND end_date>=? AND start_date<=?',
                    (batch.instrument_id, batch.start.isoformat(), batch.end.isoformat()),
                ).fetchall()
                first = min([batch.start.isoformat(), *(row[0] for row in ranges)])
                last = max([batch.end.isoformat(), *(row[1] for row in ranges)])
                self._write('DELETE FROM official_stock_coverage WHERE instrument_id=? AND end_date>=? AND start_date<=?', (batch.instrument_id, first, last))
                self._write('INSERT INTO official_stock_coverage VALUES(?,?,?)', (batch.instrument_id, first, last))

            self._revision += 1

    def _archive_manifest(self, row):
        self._write('INSERT OR IGNORE INTO official_stock_manifest_archive VALUES(?,?,?,?,?,?,?)', _manifest_record(row))

    def official_manifest_archive(self, source_digest: str) -> tuple[OfficialStockManifest, ...]:
        """Resolve individual archived source sets, never guess opaque unions of sets."""
        if not valid_digest(source_digest):
            raise DomainError('official_stock_invalid', 'official source-set digest required')
        try:
            with self.lock:
                rows = self.db.execute(
                    'SELECT archive_id,instrument_id,start_date,end_date,sources,arrived_at,source_digest '
                    'FROM official_stock_manifest_archive WHERE source_digest=? ORDER BY instrument_id,start_date,end_date,arrived_at,archive_id',
                    (source_digest,),
                ).fetchall()
                result = []
                for row in rows:
                    if _manifest_record(row[1:6]) != row:
                        raise ValueError('archived manifest integrity mismatch')
                    result.append(
                        OfficialStockManifest(
                            row[0],
                            row[1],
                            date.fromisoformat(row[2]),
                            date.fromisoformat(row[3]),
                            tuple(tuple(pair) for pair in json.loads(row[4])),
                            _arrival(row[5]),
                            row[6],
                        )
                    )
                return tuple(result)
        except (ValueError, TypeError, ArithmeticError, sqlite3.DatabaseError):
            raise DomainError('official_stock_invalid', 'archived official manifest invalid') from None

    def _selected_sources(self, instrument_id, start, end):
        manifests = self.db.execute(
            'SELECT rowid,length(CAST(sources AS BLOB)) FROM official_stock_batches WHERE instrument_id=? AND start_date<? AND end_date>? LIMIT ?',
            (instrument_id, end.isoformat(), start.isoformat(), MAX_ACTIVE_MANIFESTS + 1),
        ).fetchall()
        if len(manifests) > MAX_ACTIVE_MANIFESTS:
            raise DomainError('official_stock_invalid', 'overlapping official manifest limit')
        sources = set()
        for rowid, size in manifests:
            if size > MAX_MANIFEST_BYTES:
                raise DomainError('official_stock_invalid', 'official manifest byte limit')
            raw = self.db.execute('SELECT sources FROM official_stock_batches WHERE rowid=?', (rowid,)).fetchone()[0]
            pairs = json.loads(raw)
            if type(pairs) is not list or len(pairs) > MAX_HISTORY_SOURCES:
                raise DomainError('official_stock_invalid', 'official manifest source limit')
            for pair in pairs:
                if type(pair) is not list or len(pair) != 2 or any(type(value) is not str for value in pair):
                    raise DomainError('official_stock_invalid', 'invalid official manifest source')
                sources.add(tuple(pair))
            if len(sources) > MAX_HISTORY_SOURCES:
                raise DomainError('official_stock_invalid', 'selected official source limit')
        return sources

    def _source_metadata(self, sources):
        result, size = [], 0
        for url, digest in sorted(sources):
            row = self.db.execute(
                'SELECT length(CAST(raw AS BLOB)),arrived_at FROM official_stock_payloads WHERE source_url=? AND digest=?', (url, digest)
            ).fetchone()
            if row is None or not 0 < row[0] <= 8 * 1024 * 1024:
                raise DomainError('official_stock_invalid', 'missing or oversized official payload')
            size += row[0]
            if size > MAX_HISTORY_BYTES:
                raise DomainError('official_stock_invalid', 'selected official payload byte limit')
            result.append((url, digest, row[1]))
        return result

    def official_payload(self, source_url: str, digest: str) -> OfficialPayload:
        """Historical evidence resolves immutable payloads after later corrections."""
        with self.lock:
            row = self.db.execute('SELECT raw FROM official_stock_payloads WHERE source_url=? AND digest=?', (source_url, digest)).fetchone()
        if row is None or sha256(row[0]).hexdigest() != digest:
            raise DomainError('official_stock_invalid', 'historical source missing or corrupt')
        return OfficialPayload(source_url, digest, row[0])

    def official_payload_arrival(self, source_url: str, digest: str) -> datetime | None:
        with self.lock:
            row = self.db.execute('SELECT arrived_at FROM official_stock_payloads WHERE source_url=? AND digest=?', (source_url, digest)).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return _arrival(row[0])
        except (ValueError, TypeError, DomainError):
            raise DomainError('official_stock_invalid', 'invalid stored official arrival') from None

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
                cash_rows = self.db.execute(
                    'SELECT ex_date,cash_per_share,payment_date,source_digest,facts_digest FROM stock_cash_entitlements '
                    'WHERE instrument_id=? AND ex_date>=? AND ex_date<?',
                    args,
                ).fetchall()
                events = _events(event_rows, cash_rows)
                sources = self._selected_sources(instrument_id, start, end)
                metadata = self._source_metadata(sources)
                arrivals = tuple(_arrival(row[2]) for row in metadata)
                arrived_at = max(arrivals) if arrivals and all(value is not None for value in arrivals) else None
                payloads = tuple(
                    OfficialPayload(
                        *self.db.execute('SELECT source_url,digest,raw FROM official_stock_payloads WHERE source_url=? AND digest=?', (url, digest)).fetchone()
                    )
                    for url, digest, _ in metadata
                )
            digests = {b.source_digest for b in bars} | {e.source_digest for e in events}
            if (
                not digests <= {p.digest for p in payloads}
                or {(p.source_url, p.digest) for p in payloads} != sources
                or any(sha256(p.raw).hexdigest() != p.digest for p in payloads)
            ):
                raise ValueError('missing/corrupt official provenance')
            return OfficialStockBatch(instrument_id, start, end, bars, events, payloads, arrived_at)
        except (ValueError, TypeError, ArithmeticError, sqlite3.DatabaseError):
            raise DomainError('official_stock_invalid', 'cached daily data/provenance invalid') from None


def _manifest_record(row):
    instrument_id, first, end, sources, arrived_at = row
    identity(instrument_id)
    if date.fromisoformat(first) >= date.fromisoformat(end) or len(sources.encode()) > MAX_MANIFEST_BYTES:
        raise ValueError('invalid archived manifest range or byte bound')
    pairs = json.loads(sources)
    if (
        type(pairs) is not list
        or len(pairs) > MAX_HISTORY_SOURCES
        or any(type(pair) is not list or len(pair) != 2 or any(type(value) is not str for value in pair) for pair in pairs)
    ):
        raise ValueError('invalid archived manifest source references')
    _arrival(arrived_at)
    canonical = json.dumps(sorted({tuple(pair) for pair in pairs}), separators=(',', ':'), ensure_ascii=True)
    digest = sha256(canonical.encode()).hexdigest()
    key = sha256(json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return key, instrument_id, first, end, sources, arrived_at, digest


def _arrival(value):
    if value is None:
        return None
    try:
        return aware(datetime.fromisoformat(value))
    except (ValueError, TypeError, DomainError):
        raise ValueError('invalid official arrival') from None


def _events(event_rows, cash_rows):
    """Rejoin additive facts without upgrading historical unknown actions."""
    cash = {row[0]: row[1:] for row in cash_rows}
    if not cash.keys() <= {row[1] for row in event_rows}:
        raise ValueError('orphan cash facts')
    result = []
    for row in event_rows:
        values = row[0], date.fromisoformat(row[1]), Decimal(row[2]), Decimal(row[3]), row[4], row[5]
        if row[1] in cash:
            amount, payment, digest, binding = cash[row[1]]
            if digest != row[4]:
                raise ValueError('cash source binding mismatch')
            event = CashDividendAction(*values, Decimal(amount), date.fromisoformat(payment))
            if binding != _cash_binding(event):
                raise ValueError('cash facts binding mismatch')
            result.append(event)
        else:
            result.append(CorporateAction(*values))
    return tuple(result)


def _cash_binding(event):
    """Disk integrity of trusted source-adapter facts, not a source attestation."""
    values = (
        event.instrument_id,
        event.ex_date.isoformat(),
        str(event.previous_close),
        str(event.reference_price),
        event.source_url,
        event.source_digest,
        str(event.cash_per_share),
        event.payment_date.isoformat(),
    )
    return sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()
