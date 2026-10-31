import sqlite3
import time
from quantlab.errors import ERROR_LABELS
from quantlab.assistant.domain.connection_errors import exception_code
from quantlab.assistant.application.connection_contracts import ConnectionEvent, ConnectionRequest, RECONCILIATION_ACTIONS, ReconciliationEvent


def _safe_error_code(exc):
    """Map an exception to a fixed allowlisted code; never expose its text."""
    code = exception_code(exc)
    if code not in ('operation_failed', 'validation_failed', 'operation_failed_local'):
        return code
    names = tuple((c.__name__ for c in type(exc).__mro__))
    if 'PlanError' in names:
        local = getattr(exc, 'code', None)
        if local == 'remote_error':
            status = getattr(exc, 'http_status', None)
            if status == 400:
                return 'models_http_bad_request'
            if status == 404:
                return 'models_http_not_found'
            if status == 429:
                return 'models_http_rate_limited'
            if type(status) is int and 500 <= status <= 599:
                return 'models_http_server_error'
            return 'models_http_other'
        return local if local in ERROR_LABELS else 'operation_failed_plan'
    if 'AuthError' in names:
        return 'operation_failed_auth'
    if isinstance(exc, (OSError, sqlite3.Error)):
        return 'operation_failed_local'
    return 'operation_failed'


def run_connection_request(request, *, bootstrap, emit, cancelled, session_factory=None, clock=time.monotonic):
    """Worker-only adapter. Parent MUST enforce process deadline/terminate/join.

    No unbounded work on the GUI thread. The parent fixes bootstrap, never accepts
    it from user/model JSON, and forwards only ConnectionEvent through private IPC.
    The official URL is transient IPC, never a log/result/history field.
    """
    if not isinstance(request, ConnectionRequest):
        raise ValueError('typed connection request required')
    if request.action in RECONCILIATION_ACTIONS:
        from pathlib import Path
        from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
        from quantlab.assistant.adapters.chatgpt.provider import inspect_unknown_request, resolve_unknown_request
        from quantlab.assistant.adapters.chatgpt.provider import inspect_finished_unknown_request, resolve_finished_unknown_request
        from quantlab.assistant.adapters.chatgpt.provider import read_account_status

        event_fields = {'reconciliation_action': request.action, 'reconciliation_registration': request.registration}
        try:
            if cancelled():
                raise ValueError('active_or_unknown_request')
            reference = OAuthCredentialReference(str(bootstrap), request.registration)
            controls = Path(bootstrap) / 'control-v1'
            if request.action == 'inspect_unknown':
                result = inspect_unknown_request(reference, controls)
                outcome = None
                if result['kind'] == 'k2_unresolvable':
                    result = inspect_finished_unknown_request(reference, controls)
                    outcome = result['outcome']
                return ReconciliationEvent(
                    request.request_id,
                    'result',
                    inspection=tuple((result[key] for key in ('kind', 'sequence', 'calls', 'max_age_ok'))),
                    inspection_outcome=outcome,
                    **event_fields,
                )
            if request.action == 'resolve_finished_unknown':
                resolve_finished_unknown_request(
                    reference,
                    controls,
                    user_confirmed=request.user_confirmed,
                    acknowledgement_version=request.acknowledgement_version,
                    expected_sequence=request.expected_sequence,
                    expected_calls=request.expected_calls,
                    expected_outcome=request.expected_outcome,
                )
            else:
                resolve_unknown_request(reference, controls, user_confirmed=request.user_confirmed, acknowledgement_version=request.acknowledgement_version)
            try:
                status = read_account_status(reference, controls)
            except Exception:
                return ReconciliationEvent(request.request_id, 'result', **event_fields)
            return ReconciliationEvent(request.request_id, 'result', account_status=(status['state'], status['pending']), **event_fields)
        except Exception as exc:
            return ReconciliationEvent(request.request_id, 'error', error_code=_safe_error_code(exc), **event_fields)
    if request.action == 'test':
        from quantlab.assistant.adapters.chatgpt.connection_probe import run_probe

        return run_probe(request, bootstrap, cancelled, clock=clock)
    session = None
    deadline = clock() + request.max_runtime_seconds

    def snapshot(state=None, kind='result', **extra):
        summary = session.status_summary()
        rows = tuple(((row['registration'], row['state']) for row in summary['registrations']))
        return ConnectionEvent(
            request.request_id,
            kind,
            state or summary['state'],
            rows,
            summary['active_registration'],
            account_labels=tuple(((row['registration'], row['account_label']) for row in summary['registrations'] if 'account_label' in row)),
            **extra,
        )

    try:
        if session_factory is None:
            from quantlab.assistant.adapters.chatgpt.auth import AuthSession
            from quantlab.assistant.adapters.chatgpt.vault import DPAPIVault

            session_factory = lambda: AuthSession(DPAPIVault(str(bootstrap)))
        session = session_factory()
        if cancelled():
            session.cancel()
            return ConnectionEvent(request.request_id, 'result', 'cancelled')
        if request.action == 'initialize':
            session.initialize_host()
            return snapshot()
        if request.action == 'list':
            return snapshot()
        if request.action == 'restore':
            summary = session.status_summary()
            if summary['active_registration'] is not None and summary['state'] == 'refresh_required':
                try:
                    session.refresh(summary['active_registration'])
                except Exception:
                    return snapshot(state='reauthorization_required', kind='error', error_code='restore_refresh_failed')
            return snapshot()
        if request.action in ('begin', 'first_sign_in', 'enable_plan'):
            if request.action == 'first_sign_in':
                session.initialize_host(first_use_only=True)
            url = session.begin(request.registration, enable_plan=True) if request.action == 'enable_plan' else session.begin(request.registration)
            emit(ConnectionEvent(request.request_id, 'authorization', 'authorizing', authorization_url=url))
            while session.state in ('authorizing', 'validating'):
                if cancelled():
                    session.cancel()
                    return snapshot(state=session.state)
                if clock() >= deadline:
                    session.cancel()
                    return ConnectionEvent(request.request_id, 'error', 'timeout', error_code='authorization_timeout')
                session.poll(timeout=0.1)
            if session.state == 'authorization_failed':
                code = getattr(session, 'authorization_error_code', None)
                if code not in (
                    'authorization_exchange_failed',
                    'authorization_identity_failed',
                    'authorization_tokens_failed',
                    'authorization_storage_failed',
                ):
                    code = 'authorization_failed'
                return snapshot(state='authorization_failed', kind='error', error_code=code)
            return snapshot(state=session.state)
        if request.action == 'select':
            session.select(request.registration)
            return snapshot()
        if request.action == 'refresh':
            session.refresh(request.registration)
            return snapshot()
        if request.action == 'sign_out':
            return snapshot(revocation_confirmed=session.sign_out(request.registration))
        if request.action in ('models', 'clear_pause'):
            from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
            from quantlab.assistant.adapters.chatgpt.provider import discover_models
            from quantlab.assistant.adapters.chatgpt.provider import clear_account_pause, read_account_status
            from pathlib import Path

            reference = OAuthCredentialReference(str(bootstrap), request.registration)
            if request.action == 'models':
                status = read_account_status(reference, Path(bootstrap) / 'control-v1')
                if status != {'state': 'ready', 'pending': False}:
                    raise ValueError('account_paused')
                models = discover_models(
                    reference, network_opt_in=request.user_confirmed, timeout_seconds=min(request.max_runtime_seconds, 120), cancelled=cancelled
                )
                return snapshot(models=tuple((row['slug'] for row in models)), model_labels=tuple(((row['slug'], row['display_name']) for row in models)))
            clear_account_pause(reference, Path(bootstrap) / 'control-v1', user_confirmed=request.user_confirmed)
            return snapshot()
    except Exception as exc:
        code = _safe_error_code(exc)
        return ConnectionEvent(request.request_id, 'error', 'unknown', error_code=code)
    finally:
        if request.action in ('begin', 'first_sign_in', 'enable_plan') and session is not None and (session.state in ('authorizing', 'validating')):
            try:
                session.cancel()
            except Exception:
                emit(ConnectionEvent(request.request_id, 'error', 'unknown', error_code='authorization_cleanup_failed'))
