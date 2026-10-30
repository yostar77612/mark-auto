"""Saved campaign evidence; no provider calls or credential access."""

from __future__ import annotations
import json
import math
import os
import re
import sqlite3
import stat
import time
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from quantlab.core import Bar, Dataset, canonical_json, content_hash
from quantlab.data import parse_timestamp, validate_dataset
from quantlab.windows_paths import canonical_path, native_path, sqlite_uri
from quantlab.research import _keys, _unique_keys
from quantlab.research_core.domain.saved_pool import SavedCandidatePoolError, _hash, _fail, _safe_boundary, MAX_AUDIT_BYTES, MAX_SOURCE_BARS


def _json_load(text):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.value_bounds import _exact_number

    def integer(value):
        if len(value) > 20:
            _fail('Source integer exceeds resource bounds')
        result = int(value)
        if result.bit_length() > 64:
            _fail('Source integer exceeds resource bounds')
        return result

    def number(value):
        _exact_number(value)
        result = float(value)
        if not math.isfinite(result):
            _fail('Source number exceeds resource bounds')
        return result

    try:
        value = json.loads(text, object_pairs_hook=_unique_keys, parse_int=integer, parse_float=number, parse_constant=lambda _: _fail('Nonfinite source JSON'))
    except (ValueError, RecursionError, TypeError) as exc:
        raise SavedCandidatePoolError('Invalid bounded source JSON') from exc
    return value


def _read_file(path):
    try:
        path = native_path(path)
        if not path.is_file():
            _fail('Missing or non-regular explicit source file')
        # Keep explicitly selected regular-file symlinks valid. Nonblocking open
        # plus fstat prevents a POSIX file-to-FIFO race from hanging the read.
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                _fail('Missing or non-regular explicit source file')
            if metadata.st_size > MAX_AUDIT_BYTES:
                _fail('Source file exceeds audit byte limit')
            raw = stream.read(MAX_AUDIT_BYTES + 1)
        if len(raw) > MAX_AUDIT_BYTES:
            _fail('Source file exceeds audit byte limit')
        return _json_load(raw.decode('utf-8'))
    except (OSError, UnicodeError) as exc:
        raise SavedCandidatePoolError('Missing or unreadable explicit source file', 'source_missing_evidence') from exc


def _audit_tree(value):
    """Bound untrusted journal nesting/numerics before canonical hashing.

    Engine summaries use 34-digit Decimal arithmetic and may carry fractional
    exponents below -32. These descriptive source values are never new ranking
    inputs; retain them within a finite 128-digit/exponent audit bound.
    """

    def source_number(value):
        parsed = Decimal(str(value))
        parts = parsed.as_tuple()
        if not parsed.is_finite() or abs(parts.exponent) > 128 or len(parts.digits) > 128 or parsed.copy_abs() > Decimal('1e15'):
            _fail('Source numeric value exceeds resource bounds')

    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        if count > 500000 or depth > 32:
            _fail('Source journal structure exceeds resource bounds')
        if type(item) is dict:
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > 16384:
                _fail('Source journal string exceeds resource bounds')
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', item):
                source_number(item)
        elif type(item) in (int, float):
            source_number(item)
        elif item is not None and type(item) is not bool:
            _fail('Invalid source journal value')

    visit(value)


def _validate_original_dataset(dataset):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.value_bounds import _bounded_value, _bounded_number

    if not isinstance(dataset, Dataset) or not 1 <= len(dataset.bars) <= MAX_SOURCE_BARS:
        _fail('Exact original Dataset within bar bounds required')
    _bounded_value(dataset.manifest)
    _bounded_value(dataset.quality)
    byte_count = 0
    for bar in dataset.bars:
        for number in (bar.open, bar.high, bar.low, bar.close):
            _bounded_number(number)
        if type(bar.volume) is not int or bar.volume.bit_length() > 64:
            _fail('Original bar volume exceeds resource bounds')
        if type(bar.source_id) is not str or len(bar.source_id) > 4096:
            _fail('Original bar source exceeds resource bounds')
        byte_count += len(bar.source_id.encode('utf-8'))
        if byte_count > 16777216:
            _fail('Original source identifiers exceed resource bounds')
        bar.__post_init__()
    validate_dataset(dataset)
    if dataset.quality.get('missing_intervals', 0):
        _fail('Original source has missing intervals')
    if any(a.end > b.timestamp for a, b in zip(dataset.bars, dataset.bars[1:])):
        _fail('Original source events are nonchronological or overlapping')


@_safe_boundary
def load_original_dataset(path: Path) -> Dataset:
    """Load only the explicitly selected local dataset, bounding BEFORE hashing.

    This does not follow any filename or URL found in a campaign manifest.
    """
    # Keep operation-specific dependencies out of module startup.
    from quantlab.value_bounds import _bounded_value, _exact_number

    envelope = _read_file(path)
    _keys(envelope, ('kind', 'sha256', 'payload'))
    if envelope['kind'] != 'quantlab_dataset_v1' or not _hash(envelope['sha256']):
        _fail('Expected exact original quantlab_dataset_v1 envelope')
    payload = envelope['payload']
    _keys(payload, ('bars', 'manifest', 'quality'))
    if type(payload['bars']) is not list or not 1 <= len(payload['bars']) <= MAX_SOURCE_BARS:
        _fail('Original dataset exceeds bar bounds')
    _bounded_value(payload['manifest'])
    _bounded_value(payload['quality'])
    bars = []
    source_bytes = 0
    try:
        for item in payload['bars']:
            _keys(item, ('timestamp', 'end', 'trade_date', 'session', 'contract_id', 'open', 'high', 'low', 'close', 'volume', 'source_id'))
            _bounded_value(item)
            row = dict(item)
            for key in ('open', 'high', 'low', 'close'):
                row[key] = _exact_number(row[key])
            for key in ('timestamp', 'end'):
                row[key] = parse_timestamp(row[key])
            if type(row['source_id']) is not str or len(row['source_id']) > 4096:
                _fail('Original bar source exceeds resource bounds')
            source_bytes += len(row['source_id'].encode('utf-8'))
            if source_bytes > 16777216:
                _fail('Original source identifiers exceed resource bounds')
            bars.append(Bar(**row))
        if content_hash(payload) != envelope['sha256']:
            _fail('Original dataset envelope hash mismatch')
        dataset = Dataset(tuple(bars), payload['manifest'], payload['quality'])
        _validate_original_dataset(dataset)
        return dataset
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise SavedCandidatePoolError('Invalid bounded original dataset', 'source_dataset_mismatch') from exc


def _prepare_bounded_read(db, tables):
    """Known real tables only; lock waits and query execution are both bounded."""
    deadline = time.monotonic() + 2
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_AUDIT_BYTES)
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    for table, expected in tables.items():
        metadata = db.execute('SELECT type, sql FROM sqlite_master WHERE name=?', (table,)).fetchmany(2)
        if len(metadata) != 1 or metadata[0][0] != 'table' or type(metadata[0][1]) is not str or not metadata[0][1].lstrip().upper().startswith('CREATE TABLE'):
            _fail('Source SQLite evidence requires the audited real table schema')
        columns = db.execute('PRAGMA table_xinfo(' + table + ')').fetchmany(len(expected) + 1)
        if [tuple(row[1:]) for row in columns] != expected:
            _fail('Source SQLite evidence has unsupported table columns')
        if db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND tbl_name=? LIMIT 1', ('trigger', table)).fetchone() is not None:
            _fail('Source SQLite evidence contains unaudited table triggers')


def _read_campaign(folder):
    folder = native_path(folder).resolve()
    journal, export = folder / 'campaign.sqlite3', folder / 'campaign.json'
    if not journal.is_file() or not export.is_file() or not journal.resolve().is_relative_to(folder) or not export.resolve().is_relative_to(folder):
        _fail('Missing or escaping source campaign journal/export')
    try:
        with closing(sqlite3.connect(sqlite_uri(journal) + '?mode=ro', uri=True, timeout=1)) as db:
            _prepare_bounded_read(db, {'state': [('id', 'INTEGER', 0, None, 1, 0), ('payload', 'TEXT', 1, None, 0, 0)]})
            metadata = db.execute('SELECT id, typeof(payload), length(CAST(payload AS BLOB)) FROM state').fetchmany(2)
            if len(metadata) != 1 or metadata[0][0] != 1 or metadata[0][1] != 'text' or not 0 < metadata[0][2] <= MAX_AUDIT_BYTES:
                _fail('Invalid source campaign journal or audit size')
            state = _json_load(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            exported = _read_file(export)
            _audit_tree(state)
            _audit_tree(exported)
            if canonical_json(state) != canonical_json(exported):
                _fail('Source campaign journal/export mismatch')
            return state
    except (sqlite3.Error, OSError) as exc:
        raise SavedCandidatePoolError('Unreadable authoritative source campaign journal', 'source_missing_evidence') from exc


def _lexical_registry_path(value):
    # A persisted path is untrusted evidence. Do not resolve or open it.
    if type(value) is not str or not value or len(value) > 4096 or '\x00' in value or not os.path.isabs(value):
        _fail('Source registry requires an absolute persisted local identity')
    return os.path.normcase(os.path.normpath(canonical_path(value)))


def _validate_source_registry(state, holdout, selected_path):
    """Check ONLY the selected authority, read-only, against source reservation.

    Local path/row consistency cannot detect a coherent full-database rollback.
    """
    evidence = state.get('holdout_registry')
    if selected_path is None or type(evidence) is not dict:
        _fail('Source registry proof and explicit authoritative registry required')
    source_identity = _lexical_registry_path(evidence.get('registry_path'))
    selected = native_path(selected_path).resolve()
    if source_identity != _lexical_registry_path(str(selected)):
        _fail('Source registry differs from selected authoritative registry')
    coverage = {}
    for bar in holdout.bars:
        start = bar.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = bar.end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        old = coverage.get(bar.contract_id, (start, end))
        coverage[bar.contract_id] = (min(old[0], start), max(old[1], end))
    bar_hash = content_hash(holdout.bars)
    reservation_id = content_hash({'bars_hash': bar_hash, 'coverage': coverage})
    if (
        evidence.get('reservation_id') != reservation_id
        or evidence.get('holdout_hash') != bar_hash
        or evidence.get('status') != 'reserved_consumed'
        or evidence.get('conflicts') != []
    ):
        _fail('Source registry reservation proof is invalid')
    try:
        if not selected.is_file() or selected.stat().st_size > MAX_AUDIT_BYTES:
            _fail('Source registry is missing or exceeds audit byte limit')
        with closing(sqlite3.connect(sqlite_uri(selected) + '?mode=ro', uri=True, timeout=1)) as db:
            _prepare_bounded_read(
                db,
                {
                    'reservations': [
                        ('reservation_id', 'TEXT', 0, None, 1, 0),
                        ('holdout_hash', 'TEXT', 1, None, 0, 0),
                        ('campaign_id', 'TEXT', 1, None, 0, 0),
                        ('selection_hash', 'TEXT', 1, None, 0, 0),
                        ('source_directory', 'TEXT', 1, None, 0, 0),
                    ],
                    'coverage': [
                        ('reservation_id', 'TEXT', 1, None, 1, 0),
                        ('contract_id', 'TEXT', 1, None, 2, 0),
                        ('start', 'TEXT', 1, None, 0, 0),
                        ('end', 'TEXT', 1, None, 0, 0),
                    ],
                },
            )
            expected = (reservation_id, bar_hash, state['campaign_id'], state['selection_hash'])
            rows = db.execute(
                'SELECT reservation_id, holdout_hash, campaign_id, selection_hash, source_directory FROM reservations WHERE reservation_id=?', (reservation_id,)
            ).fetchmany(2)
            observed = db.execute('SELECT contract_id, start, end FROM coverage WHERE reservation_id=? ORDER BY contract_id', (reservation_id,)).fetchmany(
                len(coverage) + 1
            )
            if (
                len(rows) != 1
                or rows[0][:4] != expected
                or type(rows[0][4]) is not str
                or not rows[0][4]
                or len(rows[0][4]) > 4096
                or observed != [(contract, *bounds) for contract, bounds in sorted(coverage.items())]
            ):
                _fail('Source registry no longer contains its exact consumed reservation and coverage')
    except (sqlite3.Error, OSError) as exc:
        raise SavedCandidatePoolError('Source registry is unavailable or inconsistent', 'source_registry_mismatch') from exc
    return {'resolved_path': source_identity, 'reservation_id': reservation_id, 'agreement_policy': 'persisted_source_reservation_matches_selected_authority'}
