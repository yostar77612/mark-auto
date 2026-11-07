"""Shared irreversible authority for E1 plans, source capture and completion.

E1 rows and the legacy reservations/coverage rows commit in one SQLite transaction.
The database lives in bootstrap controls, never in restorable research output.
"""

from contextlib import closing, contextmanager
import sqlite3
import time

from quantlab.core import canonical_json, content_hash
from quantlab.trading.runtime.e1_protocol import calendar_for, decode, is_hash, refuse, reservation_values, text_time, timestamp
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.windows_paths import native_path, sqlite_uri

SCHEMA = {
    'reservations': 'CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, holdout_hash TEXT NOT NULL, campaign_id TEXT NOT NULL, selection_hash TEXT NOT NULL, source_directory TEXT NOT NULL)',
    'coverage': 'CREATE TABLE IF NOT EXISTS coverage (reservation_id TEXT NOT NULL, contract_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY(reservation_id,contract_id))',
    'e1_plans': 'CREATE TABLE IF NOT EXISTS e1_plans (reference TEXT PRIMARY KEY, workspace TEXT NOT NULL, plan TEXT NOT NULL, status TEXT NOT NULL, dataset_binding TEXT, receipt TEXT, reserved_at TEXT)',
    'e1_captures': 'CREATE TABLE IF NOT EXISTS e1_captures (reference TEXT NOT NULL, slot INTEGER NOT NULL, payload TEXT NOT NULL, captured_at TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(reference,slot))',
}
COLUMNS = {
    'reservations': ('reservation_id', 'holdout_hash', 'campaign_id', 'selection_hash', 'source_directory'),
    'coverage': ('reservation_id', 'contract_id', 'start', 'end'),
    'e1_plans': ('reference', 'workspace', 'plan', 'status', 'dataset_binding', 'receipt', 'reserved_at'),
    'e1_captures': ('reference', 'slot', 'payload', 'captured_at', 'digest'),
}


def safe_paths(workspace, registry):
    workspace, registry = native_path(workspace).absolute(), native_path(registry).absolute()
    for target in (workspace, registry):
        for part in (target, *target.parents):
            if part.is_symlink():
                refuse()
    workspace, registry = workspace.resolve(), registry.resolve()
    if not workspace.is_dir() or registry.is_relative_to(workspace):
        refuse()
    return workspace, registry


def validate_schema(db):
    for name, expected in COLUMNS.items():
        row = db.execute('SELECT type, sql FROM sqlite_master WHERE name=?', (name,)).fetchall()
        if len(row) != 1 or row[0][0] != 'table' or 'VIRTUAL' in row[0][1].upper():
            refuse()
        if tuple(item[1] for item in db.execute('PRAGMA table_xinfo(' + name + ')')) != expected:
            refuse()
        if db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND tbl_name=?', ('trigger', name)).fetchone():
            refuse()


@contextmanager
def connection(registry, *, write=False, create=False):
    if not create and not registry.is_file():
        refuse()
    if create:
        registry.parent.mkdir(parents=True, exist_ok=True)
    mode = 'rwc' if create else 'rw' if write else 'ro'
    with closing(sqlite3.connect(sqlite_uri(registry) + '?mode=' + mode, uri=True, timeout=0)) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_000_000)
        deadline = time.monotonic() + 5
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA busy_timeout=0')
        if not write:
            db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            if create:
                for sql in SCHEMA.values():
                    db.execute(sql)
            validate_schema(db)
            yield db
            if write:
                db.commit()
        finally:
            if db.in_transaction:
                db.rollback()


def reserve(registry, workspace, plan):
    reference = content_hash(plan)
    values, coverage = reservation_values(reference, plan)
    contract, start, end = coverage
    with connection(registry, write=True, create=True) as db:
        if db.execute('SELECT 1 FROM coverage WHERE contract_id=? AND start < ? AND end > ? LIMIT 1', (contract, end, start)).fetchone():
            refuse()
        db.execute('INSERT INTO reservations VALUES (?,?,?,?,?)', values)
        db.execute('INSERT INTO coverage VALUES (?,?,?,?)', (values[0], *coverage))
        if protocol.utc_now() >= min(row['open'] for row in calendar_for(plan).sessions):
            refuse()
        db.execute('INSERT INTO e1_plans VALUES (?,?,?,?,?,?,?)', (reference, str(workspace), canonical_json(plan), 'committing', None, None, None))
    # Observe the clock AFTER durable reservation. A crash here is an unknown,
    # consumed attempt, never resumable. Late commits can never become eligible.
    confirmed = protocol.utc_now()
    with connection(registry, write=True) as db:
        if confirmed >= min(row['open'] for row in calendar_for(plan).sessions):
            db.execute("UPDATE e1_plans SET status='failed' WHERE reference=?", (reference,))
        else:
            db.execute("UPDATE e1_plans SET status='reserved',reserved_at=? WHERE reference=? AND status='committing'", (text_time(confirmed), reference))
    if confirmed >= min(row['open'] for row in calendar_for(plan).sessions):
        refuse()
    return reference


def load(db, reference, workspace):
    if not is_hash(reference):
        refuse()
    rows = db.execute(
        'SELECT plan,status,dataset_binding,receipt,reserved_at FROM e1_plans WHERE reference=? AND workspace=?', (reference, str(workspace))
    ).fetchmany(2)
    if len(rows) != 1:
        refuse()
    plan, status, binding, receipt, reserved_at = rows[0]
    plan = decode(plan)
    if content_hash(plan) != reference:
        refuse()
    verify_reservation(db, reference, plan)
    if reserved_at is None:
        if status not in ('committing', 'failed'):
            refuse()
    elif not timestamp(plan['created_at']) <= timestamp(reserved_at) < min(row['open'] for row in calendar_for(plan).sessions):
        refuse()
    return plan, status, decode(binding) if binding is not None else None, decode(receipt) if receipt is not None else None


def verify_reservation(db, reference, plan):
    values, coverage = reservation_values(reference, plan)
    if db.execute('SELECT * FROM reservations WHERE reservation_id=?', (values[0],)).fetchall() != [values]:
        refuse()
    if db.execute('SELECT contract_id,start,end FROM coverage WHERE reservation_id=?', (values[0],)).fetchall() != [coverage]:
        refuse()


def terminate(registry, workspace, reference, status):
    if status not in ('failed', 'cancelled'):
        refuse()
    with connection(registry, write=True) as db:
        load(db, reference, workspace)
        db.execute("UPDATE e1_plans SET status=? WHERE reference=? AND status IN ('reserved','captured','capturing','evaluating')", (status, reference))
