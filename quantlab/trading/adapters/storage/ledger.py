"""Append-only hash chained state events and fenced single writer in SQLite."""

from datetime import datetime
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
import zlib
from uuid import uuid4

from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import Fence, StoredEvent


SCHEMA_VERSION = 3  # 2: every payload is plain text; 3: large payloads may be stored compressed
COMPRESSED = b'MAZ1'
COMPRESS_FROM_BYTES = 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def pack(payload: str):
    """Large payloads are stored zlib-compressed; the hash chain always covers the plain text."""
    raw = payload.encode('utf-8')
    return COMPRESSED + zlib.compress(raw, 6) if len(raw) >= COMPRESS_FROM_BYTES else payload


def unpack(stored) -> str:
    if type(stored) is str:
        return stored  # schema-2 rows and small payloads
    if type(stored) is bytes and stored.startswith(COMPRESSED):
        inflater = zlib.decompressobj()
        raw = inflater.decompress(stored[len(COMPRESSED) :], MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES or inflater.unconsumed_tail or not inflater.eof:
            raise ValueError('compressed payload size')
        return raw.decode('utf-8')
    raise ValueError('unknown payload encoding')


class Ledger:
    """All mutations commit ownership validation and event append atomically.

    Lease time is supplied by an injectable clock. A new generation permanently
    fences an expired owner, including after that owner's process resumes.
    """

    def __init__(self, path: Path, scope: str, now: datetime, *, lease_seconds: int = 30):
        if sqlite3.sqlite_version_info < (3, 53, 0):
            raise DomainError('validation_failed', 'patched SQLite runtime required')
        if not path.is_absolute() or path.is_symlink() or not scope or lease_seconds < 1:
            raise DomainError('validation_failed', 'ledger path/scope/lease')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.scope, self.lease_seconds = path, scope, lease_seconds
        self.fail_writes = False
        self._db = sqlite3.connect(path, timeout=2, isolation_level=None, check_same_thread=False)
        try:
            self._initialize(now)
        except BaseException:
            self._db.close()
            raise

    def _initialize(self, now: datetime) -> None:
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS metadata(schema_version INTEGER NOT NULL);
            INSERT INTO metadata SELECT 3 WHERE NOT EXISTS(SELECT 1 FROM metadata);
            CREATE TABLE IF NOT EXISTS owner(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, generation INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, digest TEXT NOT NULL);
        ''')
        found = self._db.execute('SELECT schema_version FROM metadata').fetchall()
        if found == [(2,)]:
            # Old rows stay as they are; only new large rows are compressed. Builds that predate version 3
            # refuse this file with 'unsupported ledger schema' instead of misreading it.
            self._db.execute('UPDATE metadata SET schema_version=3')
        elif found != [(SCHEMA_VERSION,)]:
            raise DomainError('validation_failed', 'unsupported ledger schema')
        self.fence = self._acquire(now)

    @staticmethod
    def _epoch(now: datetime) -> float:
        if now.tzinfo is None or now.utcoffset() is None:
            raise DomainError('validation_failed', 'naive ledger clock')
        return now.timestamp()

    def _begin(self) -> None:
        if self.fail_writes:
            raise DomainError('journal_failed', 'injected storage failure')
        self._db.execute('BEGIN IMMEDIATE')

    def _acquire(self, now: datetime) -> Fence:
        epoch = self._epoch(now)
        self._begin()
        try:
            prior = self._db.execute('SELECT owner,generation,expires FROM owner WHERE scope=?', (self.scope,)).fetchone()
            if prior and prior[2] > epoch:
                raise DomainError('ownership_conflict', 'another active writer')
            generation = prior[1] + 1 if prior else 1
            owner = uuid4().hex
            self._db.execute('INSERT OR REPLACE INTO owner VALUES(?,?,?,?)', (self.scope, owner, generation, epoch + self.lease_seconds))
            self._db.commit()
            return Fence(self.scope, owner, generation)
        except BaseException:
            self._db.rollback()
            raise

    def _validate(self, now: datetime) -> None:
        epoch = self._epoch(now)
        row = self._db.execute('SELECT owner,generation,expires FROM owner WHERE scope=?', (self.scope,)).fetchone()
        if row is None or row[:2] != (self.fence.owner, self.fence.generation) or row[2] <= epoch:
            raise DomainError('ownership_conflict', 'expired or fenced writer')
        self._db.execute('UPDATE owner SET expires=? WHERE scope=?', (epoch + self.lease_seconds, self.scope))

    def heartbeat(self, now: datetime) -> None:
        self._begin()
        try:
            self._validate(now)
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def append(self, kind: str, payload: str, now: datetime, *, expected_sequence: int) -> StoredEvent:
        if not kind or type(payload) is not str or len(payload.encode()) > MAX_PAYLOAD_BYTES:
            raise DomainError('validation_failed', 'invalid journal event')
        self._begin()
        try:
            self._validate(now)
            row = self._db.execute('SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            sequence, previous = (row[0] + 1, row[1]) if row else (1, '0' * 64)
            if sequence != expected_sequence + 1:
                raise DomainError('state_conflict', 'journal version changed')
            digest = sha256(f'{sequence}\n{kind}\n{previous}\n{payload}'.encode()).hexdigest()
            self._db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (sequence, kind, pack(payload), previous, digest))
            self._db.commit()
            return StoredEvent(sequence, kind, payload, previous, digest)
        except BaseException:
            self._db.rollback()
            raise

    def replay(self) -> tuple[StoredEvent, ...]:
        result = []
        previous = '0' * 64
        for row in self._db.execute('SELECT seq,kind,payload,previous_hash,digest FROM events ORDER BY seq'):
            try:
                item = StoredEvent(row[0], row[1], unpack(row[2]), row[3], row[4])
            except (ValueError, zlib.error):
                raise DomainError('journal_failed', 'journal integrity mismatch') from None
            expected = sha256(f'{item.sequence}\n{item.kind}\n{previous}\n{item.payload}'.encode()).hexdigest()
            if item.sequence != len(result) + 1 or item.previous_hash != previous or item.digest != expected:
                raise DomainError('journal_failed', 'journal integrity mismatch')
            result.append(item)
            previous = item.digest
        return tuple(result)

    def backup(self, destination: Path) -> None:
        if not destination.is_absolute() or destination.exists() or destination == self.path:
            raise DomainError('validation_failed', 'fresh backup path required')
        with closing(sqlite3.connect(destination)) as other:
            self._db.backup(other)
            # A consistent backup contains durable events, never a live lease.
            # On restore a new generation/owner must reconcile before execution.
            other.execute('DELETE FROM owner')
            other.commit()
            other.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def close(self) -> None:
        try:
            self._db.execute('DELETE FROM owner WHERE scope=? AND owner=? AND generation=?', (self.scope, self.fence.owner, self.fence.generation))
        finally:
            self._db.close()

    def abandon(self) -> None:
        """Crash simulation: leave lease intact, close handle only."""
        self._db.close()
