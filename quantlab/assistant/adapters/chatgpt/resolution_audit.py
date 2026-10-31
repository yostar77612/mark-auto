"""Resolution audit responsibility; original guards and ordering preserved."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
from quantlab.assistant.adapters.chatgpt.account_paths import _controls_for
from quantlab.assistant.adapters.chatgpt.account_paths import _reject_links
from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
from quantlab.assistant.domain.plan_protocol import ACKNOWLEDGEMENT_VERSION
from quantlab.assistant.domain.plan_protocol import _CONFIRMED_CONSUMED
from quantlab.assistant.domain.plan_protocol import _FINISHED_ACKNOWLEDGEMENT_VERSIONS
from quantlab.assistant.domain.plan_protocol import _FINISHED_UNKNOWN_STATUSES
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.core import content_hash
import re
import sqlite3


def _resolution_registration(db, schema, filename, receipt):
    """Only complete, matching local audit evidence makes a receipt final."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    if not _resolution_audit_triggers(db, schema):
        return None
    try:
        rows = db.execute(
            'SELECT request_hash,registration,previous_status,new_status,acknowledgement_version,'
            'official_usage_checked,no_refund_acknowledged,no_other_tool_acknowledged,confirmed_at_utc,implementation_hash '
            'FROM ' + schema + '.plan_resolutions WHERE filename=? AND sequence=? LIMIT 2',
            (filename, receipt[0]),
        ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) != 1:
        return None
    row = rows[0]
    if (
        row[0] != receipt[1]
        or type(row[1]) is not str
        or not re.fullmatch('[a-f0-9]{32}', row[1])
        or row[2:4] != ('reserved_unknown', _CONFIRMED_CONSUMED)
        or type(row[4]) is not int
        or row[4] != ACKNOWLEDGEMENT_VERSION
        or any(type(value) is not int or value != 1 for value in row[5:8])
        or type(row[8]) is not str
        or type(row[9]) is not str
        or not re.fullmatch('[a-f0-9]{64}', row[9])
    ):
        return None
    try:
        recorded = datetime.fromisoformat(row[8])
        if recorded.utcoffset() != timezone.utc.utcoffset(recorded):
            return None
    except ValueError:
        return None
    return row[1]


def _resolution_audit_triggers(db, schema='main'):
    """Require the append-only guards, including for an existing audit table."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    expected = {
        'plan_resolutions_no_' + operation.lower(): 'CREATE TRIGGER plan_resolutions_no_'
        + operation.lower()
        + ' BEFORE '
        + operation
        + " ON plan_resolutions BEGIN SELECT RAISE(ABORT,'append_only'); END"
        for operation in ('UPDATE', 'DELETE')
    }
    normalize = lambda sql: re.sub(r'\s+', '', sql).lower().replace('ifnotexists', '').rstrip(';')
    try:
        rows = db.execute(
            'SELECT name,sql FROM ' + schema + ".sqlite_master WHERE type='trigger' AND tbl_name='plan_resolutions' "
            "AND name IN ('plan_resolutions_no_update','plan_resolutions_no_delete')"
        ).fetchall()
        return len(rows) == 2 and all(type(sql) is str and normalize(sql) == normalize(expected[name]) for name, sql in rows)
    except sqlite3.Error:
        return False


_FINISHED_AUDIT_TABLE_SQL = (
    'CREATE TABLE IF NOT EXISTS plan_finished_resolutions ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,'
    'receipt_hash TEXT NOT NULL, registration TEXT NOT NULL,'
    'previous_status TEXT NOT NULL CHECK(previous_status IN ('
    + ','.join("'" + status + "'" for status in sorted(_FINISHED_UNKNOWN_STATUSES))
    + ')), new_status TEXT NOT NULL CHECK(new_status=\'user_confirmed_consumed\'), acknowledgement_version INTEGER NOT NULL,'
    'official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),'
    'no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),'
    'other_usage_acknowledged INTEGER NOT NULL CHECK(other_usage_acknowledged=1),'
    'confirmed_at_utc TEXT NOT NULL, implementation_hash TEXT NOT NULL, UNIQUE(filename,sequence))'
)


def _finished_audit_triggers_sql():
    return {
        'plan_finished_resolutions_no_' + operation.lower(): 'CREATE TRIGGER IF NOT EXISTS plan_finished_resolutions_no_'
        + operation.lower()
        + ' BEFORE '
        + operation
        + " ON plan_finished_resolutions BEGIN SELECT RAISE(ABORT,'append_only'); END"
        for operation in ('UPDATE', 'DELETE')
    }


def _normalized_sql(sql):
    return re.sub(r'\s+', '', sql).lower().replace('ifnotexists', '').rstrip(';')


def _finished_audit_valid(db, schema):
    """The exact K2 table and append-only triggers; a permissive table is never adopted."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    expected = {'plan_finished_resolutions': _FINISHED_AUDIT_TABLE_SQL, **_finished_audit_triggers_sql()}
    try:
        rows = db.execute(
            'SELECT name,sql FROM ' + schema + ".sqlite_master WHERE tbl_name='plan_finished_resolutions' AND type IN ('table','trigger')"
        ).fetchall()
    except sqlite3.Error:
        return False
    return len(rows) == len(expected) and all(
        name in expected and type(sql) is str and _normalized_sql(sql) == _normalized_sql(expected[name]) for name, sql in rows
    )


def _receipt_digest(row):
    """One digest over the exact 8-column plan_calls tuple, used by writer and verifier."""
    return content_hash(list(row))


def _confirmed_registration(db, schema, filename, receipt, budget):
    """Exactly one valid R1 or R2 audit row makes a consumed receipt final."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    try:
        tables = {
            name
            for (name,) in db.execute(
                'SELECT name FROM ' + schema + ".sqlite_master WHERE type='table' AND name IN ('plan_resolutions','plan_finished_resolutions')"
            ).fetchall()
        }
        k1 = []
        k2 = []
        if 'plan_resolutions' in tables:
            k1 = db.execute('SELECT 1 FROM ' + schema + '.plan_resolutions WHERE filename=? AND sequence=? LIMIT 2', (filename, receipt[0])).fetchall()
        if 'plan_finished_resolutions' in tables:
            k2 = db.execute(
                'SELECT request_hash,receipt_hash,registration,previous_status,new_status,acknowledgement_version,'
                'official_usage_checked,no_refund_acknowledged,other_usage_acknowledged,confirmed_at_utc,implementation_hash '
                'FROM ' + schema + '.plan_finished_resolutions WHERE filename=? AND sequence=? LIMIT 2',
                (filename, receipt[0]),
            ).fetchall()
    except sqlite3.Error:
        return None
    if len(k1) + len(k2) != 1:
        return None
    if k1:
        # A genuine R1 resolution always records blocked=user_confirmed_consumed.
        if budget[2] != _CONFIRMED_CONSUMED:
            return None
        return _resolution_registration(db, schema, filename, receipt)
    if not _finished_audit_valid(db, schema):
        return None
    row = k2[0]
    original = (*receipt[:3], row[3], *receipt[4:])
    if (
        row[0] != receipt[1]
        or type(row[1]) is not str
        or row[1] != _receipt_digest(original)
        or type(row[2]) is not str
        or not re.fullmatch('[a-f0-9]{32}', row[2])
        or row[3] not in _FINISHED_UNKNOWN_STATUSES
        or row[3] != budget[2]
        or row[4] != _CONFIRMED_CONSUMED
        or receipt[0] != budget[1]
        or receipt[4] is not None
        or receipt[5] != '"unknown"'
        or type(row[5]) is not int
        or row[5] not in _FINISHED_ACKNOWLEDGEMENT_VERSIONS
        or any(type(value) is not int or value != 1 for value in row[6:9])
        or type(row[9]) is not str
        or type(row[10]) is not str
        or not re.fullmatch('[a-f0-9]{64}', row[10])
    ):
        return None
    try:
        recorded = datetime.fromisoformat(row[9])
        if recorded.utcoffset() != timezone.utc.utcoffset(recorded):
            return None
    except ValueError:
        return None
    return row[2]


def _resolution_controls(credential_reference, controls_path):
    if type(credential_reference) is not OAuthCredentialReference:
        _fail('oauth_reference_required')
    controls = _controls_for(credential_reference)
    try:
        supplied = Path(controls_path)
    except (TypeError, ValueError):
        _fail('installation_controls_path_required')
    if supplied != controls:
        _fail('installation_controls_path_required')
    _reject_links(supplied)
    return controls
