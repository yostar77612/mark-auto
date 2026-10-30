"""Finished reconciliation responsibility; original guards and ordering preserved."""

from __future__ import annotations

from contextlib import closing
from quantlab.assistant.adapters.chatgpt.account_store import _installation_barrier
from quantlab.assistant.adapters.chatgpt.campaign_receipts import _checked_campaign_rows
from quantlab.assistant.adapters.chatgpt.resolution_audit import _FINISHED_AUDIT_TABLE_SQL
from quantlab.assistant.adapters.chatgpt.resolution_audit import _confirmed_registration
from quantlab.assistant.adapters.chatgpt.resolution_audit import _finished_audit_triggers_sql
from quantlab.assistant.adapters.chatgpt.resolution_audit import _finished_audit_valid
from quantlab.assistant.domain.plan_protocol import ERROR_STATES
from quantlab.assistant.domain.plan_protocol import _CONFIRMED_CONSUMED
from quantlab.assistant.domain.plan_protocol import _FINISHED_UNKNOWN_STATUSES
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.windows_paths import sqlite_uri
import sqlite3
import time


def _finished_request_snapshot(db, controls, registration):
    """Map one K2 receipt to one registration from existing data, or refuse."""
    barrier = _installation_barrier(db, controls)
    if not barrier['pending']:
        return 'none', None
    accounts = db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 1025').fetchall()
    if len(accounts) > 1024:
        _fail('account_controls_invalid')
    if any(owner is not None or state == 'reserved_unknown' for _, state, owner in accounts):
        return 'k2_unresolvable', None
    known = set(ERROR_STATES.values())
    candidates = []
    resolved_registrations = set()
    deadline = time.monotonic() + 5
    for filename, binding, calls in db.execute('SELECT filename,binding,calls FROM plan_ledgers').fetchall():
        if time.monotonic() >= deadline:
            _fail('account_controls_unavailable')
        path = controls / filename
        with closing(sqlite3.connect(sqlite_uri(path) + '?mode=ro', uri=True, timeout=1)) as ledger:
            ledger.execute('BEGIN')
            budget, rows = _checked_campaign_rows(ledger, 'main', (binding, calls))
        for row in rows:
            if row[3] == 'completed' or row[3] in known:
                continue
            if row[3] == _CONFIRMED_CONSUMED:
                resolved = _confirmed_registration(db, 'main', filename, row, budget)
                if resolved is None:
                    return 'k2_unresolvable', None
                resolved_registrations.add(resolved)
            elif row[3] in _FINISHED_UNKNOWN_STATUSES:
                candidates.append((path, binding, calls, budget, rows, row))
            else:
                return 'k2_unresolvable', None
    if len(candidates) != 1:
        return 'k2_unresolvable', None
    path, binding, calls, budget, rows, receipt = candidates[0]
    if (
        receipt[0] != calls
        or budget[1] != calls
        or any(row[3] != 'completed' for row in rows[:-1])
        or budget[2] != receipt[3]
        or receipt[4] is not None
        or receipt[5] != '"unknown"'
    ):
        return 'k2_unresolvable', None
    unresolved = []
    for account_registration, state, _ in accounts:
        if state is None or state in known:
            continue
        if state == _CONFIRMED_CONSUMED:
            if account_registration not in resolved_registrations:
                return 'k2_unresolvable', None
            continue
        unresolved.append((account_registration, state))
    if len(unresolved) != 1 or unresolved[0][1] != receipt[3]:
        return 'k2_unresolvable', None
    if unresolved[0][0] != registration:
        return 'k2_other_registration', None
    return 'k2_resolvable', (path, binding, calls, budget, receipt)


def _create_finished_resolution_audit(db):
    # execute (not executescript) preserves the caller's cross-database transaction.
    db.execute(_FINISHED_AUDIT_TABLE_SQL)
    for sql in _finished_audit_triggers_sql().values():
        db.execute(sql)
    if not _finished_audit_valid(db, 'main'):
        _fail('account_controls_invalid')
