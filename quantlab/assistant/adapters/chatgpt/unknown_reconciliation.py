"""Unknown reconciliation responsibility; original guards and ordering preserved."""

from __future__ import annotations

from contextlib import closing
from quantlab.assistant.adapters.chatgpt.account_store import _installation_barrier
from quantlab.assistant.adapters.chatgpt.campaign_receipts import _checked_campaign_rows
from quantlab.assistant.adapters.chatgpt.resolution_audit import _confirmed_registration
from quantlab.assistant.adapters.chatgpt.resolution_audit import _resolution_audit_triggers
from quantlab.assistant.domain.plan_protocol import ERROR_STATES
from quantlab.assistant.domain.plan_protocol import _CONFIRMED_CONSUMED
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.windows_paths import sqlite_uri
import sqlite3
import time


def _unknown_request_snapshot(db, controls, registration):
    """Read under the installation transaction; never regenerate old bindings."""
    barrier = _installation_barrier(db, controls)
    accounts = db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 1025').fetchall()
    if len(accounts) > 1024:
        _fail('account_controls_invalid')
    own = next((row for row in accounts if row[0] == registration and row[1] == 'reserved_unknown' and row[2] is not None), None)
    if own is None:
        other = any(state == 'reserved_unknown' and owner is not None for _, state, owner in accounts)
        kind = 'k1_other_registration' if other else 'k2_unresolvable' if barrier['pending'] else 'none'
        return kind, None
    matches = db.execute('SELECT filename,binding,calls FROM plan_ledgers WHERE binding=? LIMIT 2', (own[2],)).fetchall()
    if len(matches) != 1:
        _fail('campaign_controls_inconsistent')
    filename, binding, calls = matches[0]
    path = controls / filename
    with closing(sqlite3.connect(sqlite_uri(path) + '?mode=ro', uri=True, timeout=5)) as ledger:
        ledger.execute('BEGIN')
        budget, receipts = _checked_campaign_rows(ledger, 'main', (binding, calls))
    if budget[2] is not None or receipts[-1][0] != calls or receipts[-1][3] != 'reserved_unknown':
        _fail('no_resolvable_unknown_request')
    resolved_registrations = set()
    deadline = time.monotonic() + 5
    for other_filename, other_binding, other_calls in db.execute('SELECT filename,binding,calls FROM plan_ledgers').fetchall():
        if time.monotonic() >= deadline:
            _fail('account_controls_unavailable')
        with closing(sqlite3.connect(sqlite_uri(controls / other_filename) + '?mode=ro', uri=True, timeout=1)) as ledger:
            ledger.execute('BEGIN')
            other_budget, rows = _checked_campaign_rows(ledger, 'main', (other_binding, other_calls))
        for row in rows:
            if other_filename == filename and row[0] == calls:
                continue
            if row[3] == _CONFIRMED_CONSUMED:
                resolved = _confirmed_registration(db, 'main', other_filename, row, other_budget)
                if resolved is None:
                    _fail('active_or_unknown_request')
                resolved_registrations.add(resolved)
            elif row[3] != 'completed' and row[3] not in set(ERROR_STATES.values()):
                _fail('active_or_unknown_request')
    for account_registration, state, owner in accounts:
        if account_registration == registration:
            continue
        if owner is not None or state not in set(ERROR_STATES.values()) | {None, _CONFIRMED_CONSUMED}:
            _fail('active_or_unknown_request')
        if state == _CONFIRMED_CONSUMED and account_registration not in resolved_registrations:
            _fail('active_or_unknown_request')
    return 'k1_resolvable', (path, binding, calls, receipts[-1])


def _create_resolution_audit(db):
    # execute (not executescript) preserves the caller's cross-database transaction.
    db.execute(
        'CREATE TABLE IF NOT EXISTS plan_resolutions ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,'
        'registration TEXT NOT NULL, previous_status TEXT NOT NULL CHECK(previous_status=\'reserved_unknown\'),'
        'new_status TEXT NOT NULL CHECK(new_status=\'user_confirmed_consumed\'), acknowledgement_version INTEGER NOT NULL,'
        'official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),'
        'no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),'
        'no_other_tool_acknowledged INTEGER NOT NULL CHECK(no_other_tool_acknowledged=1),'
        'confirmed_at_utc TEXT NOT NULL, implementation_hash TEXT NOT NULL, UNIQUE(filename,sequence))'
    )
    for operation in ('UPDATE', 'DELETE'):
        db.execute(
            'CREATE TRIGGER IF NOT EXISTS plan_resolutions_no_'
            + operation.lower()
            + ' BEFORE '
            + operation
            + ' ON plan_resolutions BEGIN SELECT RAISE(ABORT,\'append_only\'); END'
        )
    if not _resolution_audit_triggers(db):
        _fail('account_controls_invalid')
