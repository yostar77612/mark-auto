"""Atomic append-only minute receipts, independent of execution journals."""

from hashlib import sha256
from pathlib import Path
import sqlite3

from quantlab.trading.domain.validation import DomainError


MAX_RECEIPT_BYTES = 4 * 1024 * 1024


class EncodedMinuteReceiptStore:
    def __init__(self, path: Path):
        if not path.is_absolute() or path.is_symlink() or sqlite3.sqlite_version_info < (3, 53, 0):
            raise DomainError('validation_failed', 'absolute receipt path and patched SQLite required')
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=0.25, isolation_level=None)
        try:
            if self._db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise DomainError('journal_failed', 'unsupported minute receipt schema')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)')
            self._db.execute('PRAGMA user_version=1')
            count, highest = self._db.execute('SELECT count(*),coalesce(max(seq),0) FROM receipts').fetchone()
            if count != highest:
                raise DomainError('journal_failed', 'minute receipt sequence mismatch')
            self.sequence = count
            self.payloads = tuple(self.read(index) for index in range(max(1, count - 31), count + 1))
        except BaseException:
            self._db.close()
            raise

    def read(self, sequence: int):
        """Read one durable receipt; the in-memory recent view is limited to32."""
        row = self._db.execute('SELECT length(CAST(payload AS BLOB)) FROM receipts WHERE seq=?', (sequence,)).fetchone()
        if row is None or row[0] > MAX_RECEIPT_BYTES:
            raise DomainError('journal_failed', 'missing or oversized minute receipt')
        payload, digest = self._db.execute('SELECT payload,digest FROM receipts WHERE seq=?', (sequence,)).fetchone()
        if type(payload) is not str or sha256(payload.encode()).hexdigest() != digest:
            raise DomainError('journal_failed', 'minute receipt integrity mismatch')
        return payload

    def append(self, payload: str, *, before_commit=lambda: None):
        if type(payload) is not str or len(payload.encode()) > MAX_RECEIPT_BYTES:
            raise DomainError('validation_failed', 'bounded encoded minute receipt required')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            count = self._db.execute('SELECT count(*) FROM receipts').fetchone()[0]
            if count != self.sequence:
                raise DomainError('state_conflict', 'minute receipt writer changed')
            self._db.execute('INSERT INTO receipts VALUES(?,?,?)', (count + 1, payload, sha256(payload.encode()).hexdigest()))
            before_commit()  # Cancellation/deadline or changed host state rolls back.
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        self.sequence += 1
        self.payloads = (*self.payloads[-31:], payload)
        return self.sequence

    def close(self):
        self._db.close()
