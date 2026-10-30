"""Account store responsibility; original guards and ordering preserved."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from quantlab.assistant.adapters.chatgpt.account_paths import _controls_for
from quantlab.assistant.adapters.chatgpt.account_paths import _reject_links
from quantlab.assistant.adapters.chatgpt.campaign_receipts import _checked_campaign_rows
from quantlab.assistant.adapters.chatgpt.resolution_audit import _confirmed_registration
from quantlab.assistant.domain.plan_protocol import ERROR_STATES
from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.plan_protocol import _CONFIRMED_CONSUMED
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.windows_paths import sqlite_uri
import os
import re
import sqlite3
import time


_CONTROL_MARKER = b'markauto-chatgpt-plan-controls-v1\n'


def _open_account_controls(reference, *, initialize=False, readonly=True):
    """Fixed bootstrap existence marker distinguishes first use from lost audit.

    A crash during first initialization intentionally leaves a blocking marker.
    There is no implicit repair/reset, and no directory scan or workspace input.
    """
    controls = _controls_for(reference)
    marker = Path(reference.bootstrap) / 'chatgpt-plan-controls-v1.marker'
    account = controls / 'chatgpt-plan-account-controls.sqlite'
    _reject_links(marker)
    _reject_links(account)
    db = None
    try:
        if not marker.exists():
            if account.exists():
                _fail('account_control_marker_missing')
            if not initialize:
                return None
            controls.mkdir(parents=True, exist_ok=True)
            # Persist expectation BEFORE any DB creation; partial setup is blocked.
            with marker.open('xb') as output:
                output.write(_CONTROL_MARKER)
                output.flush()
                os.fsync(output.fileno())
            if os.name != 'nt':
                directory = os.open(marker.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            db = sqlite3.connect(sqlite_uri(account) + '?mode=rwc', uri=True, timeout=30)
            db.execute('PRAGMA synchronous=FULL')
            with db:
                db.execute('CREATE TABLE control_identity (id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER)')
                db.execute('INSERT INTO control_identity VALUES (1,1)')
                db.execute('CREATE TABLE plan_accounts (registration TEXT PRIMARY KEY,state TEXT,owner TEXT)')
                db.execute('CREATE TABLE plan_ledgers (filename TEXT PRIMARY KEY,binding TEXT,calls INTEGER)')
            db.close()
            db = None
        with marker.open('rb') as source:
            if source.read(len(_CONTROL_MARKER) + 1) != _CONTROL_MARKER:
                _fail('account_control_marker_invalid')
        if not account.is_file():
            _fail('account_controls_missing')
        db = sqlite3.connect(sqlite_uri(account) + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=5)
        if readonly:
            db.execute('BEGIN')
        if db.execute('SELECT version FROM control_identity WHERE id=1').fetchall() != [(1,)]:
            _fail('account_controls_invalid')
        db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 0')
        db.execute('SELECT filename,binding,calls FROM plan_ledgers LIMIT 0')
        return db
    except Exception as exc:
        if db is not None:
            db.close()
        if isinstance(exc, PlanError):
            raise
        raise PlanError('account_controls_unavailable') from None


def _persist_account_pause(credential_reference, status):
    if status not in set(ERROR_STATES.values()):
        _fail('invalid_pause_state')
    db = _open_account_controls(credential_reference, initialize=True, readonly=False)
    with closing(db), db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT state,owner FROM plan_accounts WHERE registration=?', (credential_reference.registration,)).fetchone()
        # A delayed known metadata error cannot downgrade a prior unknown
        # inference outcome into a user-clearable pause. Active owners remain
        # attached so a completed call can still retain a new known pause.
        if existing and existing[0] is not None:
            if existing[0] not in set(ERROR_STATES.values()) | {'reserved_unknown'}:
                return
            if existing[0] == 'reserved_unknown' and existing[1] is None:
                return
        db.execute(
            'INSERT INTO plan_accounts (registration,state) VALUES (?,?) ON CONFLICT(registration) DO UPDATE SET state=excluded.state',
            (credential_reference.registration, status),
        )


def _installation_barrier(db, controls, schema='main'):
    """Conservative local barrier across grants; never infer a human identity.

    The row owners and their receipt ledgers remain distinct. Public status does
    not reveal which other registration caused the installation-wide pause.
    """
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    try:
        expectations = db.execute('SELECT filename,binding,calls FROM ' + schema + '.plan_ledgers LIMIT 1025').fetchall()
        if len(expectations) > 1024:
            _fail('account_controls_invalid')
        unknown_receipt = False
        resolved_registrations = set()
        deadline = time.monotonic() + 5
        seen = set()
        for filename, binding, calls in expectations:
            if time.monotonic() >= deadline:
                _fail('account_controls_unavailable')
            if (
                type(filename) is not str
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', filename)
                or filename in ('.', '..', 'chatgpt-plan-account-controls.sqlite')
                or filename.casefold() in seen
                or type(binding) is not str
                or not re.fullmatch('[a-f0-9]{64}', binding)
                or type(calls) is not int
                or not 1 <= calls <= 100
            ):
                _fail('account_controls_invalid')
            seen.add(filename.casefold())
            path = controls / filename
            _reject_links(path)
            if not path.is_file():
                _fail('campaign_controls_missing')
            # The caller retains the global read/write transaction while each
            # indexed ledger is inspected. Every legitimate ledger mutation also
            # needs that global write transaction. No directory scan/identities.
            with closing(sqlite3.connect(sqlite_uri(path) + '?mode=ro', uri=True, timeout=min(1, max(0.001, deadline - time.monotonic())))) as ledger:
                ledger.execute('BEGIN')
                budget, receipts = _checked_campaign_rows(ledger, 'main', (binding, calls))
                for row in receipts:
                    if row[3] == _CONFIRMED_CONSUMED:
                        registration = _confirmed_registration(db, schema, filename, row, budget)
                        if registration is None:
                            unknown_receipt = True
                        else:
                            resolved_registrations.add(registration)
                    elif row[3] != 'completed' and row[3] not in set(ERROR_STATES.values()):
                        unknown_receipt = True
            if time.monotonic() >= deadline:
                _fail('account_controls_unavailable')
        rows = db.execute(
            'SELECT registration,state,owner FROM ' + schema + '.plan_accounts WHERE state IS NOT NULL OR owner IS NOT NULL LIMIT 1025'
        ).fetchall()
    except sqlite3.Error:
        raise PlanError('account_controls_unavailable') from None
    if unknown_receipt:
        return {'state': 'reserved_unknown', 'pending': True}
    if not rows:
        return {'state': 'ready', 'pending': False}
    if len(rows) > 1024:
        return {'state': 'blocked', 'pending': True}
    if any(owner is not None or state == 'reserved_unknown' for _, state, owner in rows):
        return {'state': 'reserved_unknown', 'pending': True}
    known = set(ERROR_STATES.values())
    if any(state == _CONFIRMED_CONSUMED and registration not in resolved_registrations for registration, state, _ in rows):
        return {'state': 'blocked', 'pending': True}
    known.add(_CONFIRMED_CONSUMED)
    if any(type(state) is not str or state not in known for _, state, _ in rows):
        return {'state': 'blocked', 'pending': True}
    # A deterministic known state is sufficient for admission; no identities or
    # details about other account registrations are returned to the UI.
    return {'state': sorted(state for _, state, _ in rows)[0], 'pending': False}
