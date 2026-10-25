"""Append-only hash chained state events and fenced single writer in SQLite."""

from datetime import datetime
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import Fence, StoredEvent


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
            INSERT INTO metadata SELECT 2 WHERE NOT EXISTS(SELECT 1 FROM metadata);
            CREATE TABLE IF NOT EXISTS owner(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, generation INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, digest TEXT NOT NULL);
        ''')
        if self._db.execute('SELECT schema_version FROM metadata').fetchall() != [(2,)]:
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
        if not kind or type(payload) is not str or len(payload.encode()) > 4 * 1024 * 1024:
            raise DomainError('validation_failed', 'invalid journal event')
        self._begin()
        try:
            self._validate(now)
            row = self._db.execute('SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            sequence, previous = (row[0] + 1, row[1]) if row else (1, '0' * 64)
            if sequence != expected_sequence + 1:
                raise DomainError('state_conflict', 'journal version changed')
            digest = sha256(f'{sequence}\n{kind}\n{previous}\n{payload}'.encode()).hexdigest()
            self._db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (sequence, kind, payload, previous, digest))
            self._db.commit()
            return StoredEvent(sequence, kind, payload, previous, digest)
        except BaseException:
            self._db.rollback()
            raise

    def replay(self) -> tuple[StoredEvent, ...]:
        result = []
        previous = '0' * 64
        for row in self._db.execute('SELECT seq,kind,payload,previous_hash,digest FROM events ORDER BY seq'):
            item = StoredEvent(*row)
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
