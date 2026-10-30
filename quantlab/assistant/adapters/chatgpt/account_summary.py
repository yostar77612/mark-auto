"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

from quantlab.assistant.ports.auth import AuthStatusSourcePort
from quantlab.assistant.domain.auth_protocol import _validate_record
import hashlib


def status_summary(source: AuthStatusSourcePort):
    """One local, locked snapshot for account UI after restart.

    Returns only opaque references and derived status. No implicit host
    initialization, refresh, token resolution or network requests. Invalid
    vaults fail closed rather than appearing to be a new installation.
    This does not change the in-memory authorization-attempt state.
    """
    with source.vault.lock():
        record = source.vault.load()
        if record is None:
            return {'registrations': [], 'active_registration': None, 'state': 'host_initialization_required'}
        record = _validate_record(record)
        summaries = []
        active_state = 'disconnected'
        for ref, row in record['registrations'].items():
            state = 'reauthorization_required' if row['operation'] or row['tokens'] is None else source._state(row['tokens'])
            digest = hashlib.sha256((row['identity']['issuer'] + '\0' + row['identity']['subject']).encode()).hexdigest()[-8:]
            summaries.append({'registration': ref, 'state': state, 'account_label': '已驗證帳戶 ••••' + digest + '（電子郵件未提供）'})
            if ref == record['active']:
                active_state = state
        summaries.extend({'registration': ref, 'state': 'registration_retry_required'} for ref in record['registration_retries'])
        return {'registrations': summaries, 'active_registration': record['active'], 'state': active_state}
