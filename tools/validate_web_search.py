"""Owner-run check: can this ChatGPT plan and model use hosted web_search?

Sends nothing unless --i-consent is given. --list-models then reads only the
model catalog (as the settings page does); otherwise exactly one minimal
streamed Responses request uses the same web_search settings as idea research.
Prints only a status or error code, counts, per-parameter acceptance and the
elapsed time: never tokens, account references, queries or response text.
This is a diagnostic, not product acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

# Allow direct invocation without installing this repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantlab.idea_search import SearchSession, build_search_request

TOPIC_TASK = {
    'instrument': 'TMF',
    'timeframe': '1d',
    'direction': {'family_hint': 'trend', 'text': 'moving average crossover'},
}
LIMITS = {'stall_seconds': 30, 'max_request_bytes': 16384, 'max_response_bytes': 4 * 1024 * 1024}


def summarize(session, *, ok, error=None, http_status=None, elapsed, include_seen):
    accepted = 'yes' if ok else ('no_or_unknown' if http_status == 400 else 'unknown')
    return {
        'status': 'ok' if ok else 'error',
        'error_code': error,
        'http_status': http_status,
        'searches': len(session.log()) if session else 0,
        'stop_reason': session.stop_reason if session else None,
        'sources': len(session.sources) if session else 0,
        'citations': len(session.citations) if session else 0,
        'parameters_accepted': {
            'web_search': accepted,
            'filters.blocked_domains': accepted,
            'user_location': accepted,
            'include.web_search_call.action.sources': ('yes' if include_seen else 'not_observed') if ok else accepted,
        },
        'elapsed_seconds': round(elapsed, 1),
        'scope': 'one minimal request; plan usage accounting is not reported by this tool',
    }


def _reference(registration, bootstrap):
    """The active (or given) sign-in reference and its local readiness; never a token."""
    from quantlab.assistant.adapters.chatgpt.auth import AuthSession, OAuthCredentialReference
    from quantlab.assistant.adapters.chatgpt.vault import DPAPIVault
    from quantlab.assistant.adapters.chatgpt.provider import read_account_status
    from quantlab.desktop_runtime import AppPaths

    root = Path(bootstrap) if bootstrap else AppPaths.discover().root
    registration = registration or AuthSession(DPAPIVault(str(root))).status_summary()['active_registration']
    if not registration:
        return None, {'error_code': 'not_signed_in'}
    reference = OAuthCredentialReference(str(root), registration)
    status = read_account_status(reference, root / 'control-v1')
    if status != {'state': 'ready', 'pending': False}:
        # Fixed local status codes only (for example quota_paused or reserved_unknown).
        error = {'error_code': 'account_not_ready', 'account_state': status.get('state'), 'pending_request': status.get('pending')}
        if status == {'state': 'user_confirmed_consumed', 'pending': False}:
            from quantlab.desktop_errors import error_message

            error['message'] = error_message('user_confirmed_consumed')
        return None, error
    return reference, None


def list_models(*, registration=None, bootstrap=None, reference=None, discover=None):
    """One model-catalog read, as the settings page does: no web search and no inference."""
    from quantlab.assistant.domain.plan_protocol import PlanError
    from quantlab.assistant.adapters.chatgpt.provider import discover_models

    if reference is None:
        reference, error = _reference(registration, bootstrap)
        if error:
            return {'status': 'error', **error, 'models': []}
    try:
        models = (discover or discover_models)(reference, network_opt_in=True)
    except PlanError as exc:
        return {'status': 'error', 'error_code': exc.remote_code or exc.code, 'http_status': exc.http_status, 'models': []}
    except Exception as exc:
        code = getattr(exc, 'code', None)
        return {'status': 'error', 'error_code': code if isinstance(code, str) and code.isidentifier() else type(exc).__name__, 'models': []}
    return {
        'status': 'ok',
        'models': [{'display_name': row['display_name'], 'model': row['slug']} for row in models],
        'scope': 'model catalog only; use a model value with --model for the search check',
    }


def run(model, *, registration=None, bootstrap=None, transport=None, reference=None, clock=time.monotonic):
    from quantlab.assistant.domain.plan_protocol import PlanError
    from quantlab.assistant.adapters.chatgpt.response_stream import SSEParser
    from quantlab.assistant.adapters.chatgpt.transport import PlanHTTPTransport

    if reference is None:
        reference, error = _reference(registration, bootstrap)
        if error:
            return {**summarize(None, ok=False, error=error['error_code'], elapsed=0, include_seen=False), **error}
    request = build_search_request(model, TOPIC_TASK)
    session = SearchSession(clock=clock)
    started = clock()
    include_seen = False
    stream = (transport or PlanHTTPTransport()).stream(reference, request, {**LIMITS, 'deadline': time.monotonic() + 90})
    parser = SSEParser(max_bytes=LIMITS['max_response_bytes'], max_event_bytes=1048576, max_events=8192)
    try:
        for chunk in stream:
            for event in parser.feed(chunk):
                item = event.get('item') if isinstance(event.get('item'), dict) else {}
                if item.get('type') == 'web_search_call' and isinstance(item.get('action'), dict) and 'sources' in item['action']:
                    include_seen = True
                if not session.feed(event):
                    return summarize(session, ok=session.completed or bool(session.stop_reason), elapsed=clock() - started, include_seen=include_seen)
        return summarize(
            session, ok=session.completed, error=None if session.completed else 'incomplete_stream', elapsed=clock() - started, include_seen=include_seen
        )
    except PlanError as exc:
        return summarize(
            session, ok=False, error=exc.remote_code or exc.code, http_status=exc.http_status, elapsed=clock() - started, include_seen=include_seen
        )
    except Exception as exc:
        code = getattr(exc, 'code', None) or getattr(exc, 'args', [None])[0]
        return summarize(
            session,
            ok=False,
            error=code if isinstance(code, str) and code.isidentifier() else type(exc).__name__,
            elapsed=clock() - started,
            include_seen=include_seen,
        )
    finally:
        stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='One consented web_search capability check (no secrets printed).')
    parser.add_argument('--model', help='Model value printed by --list-models')
    parser.add_argument('--list-models', action='store_true', help='Only read the model catalog (no web search, no inference)')
    parser.add_argument('--i-consent', action='store_true', help='Allow exactly one network request with your ChatGPT sign-in')
    parser.add_argument('--registration', help='Opaque sign-in reference; defaults to the active one')
    parser.add_argument('--bootstrap', help='MarkAuto data folder; defaults to the installed location')
    args = parser.parse_args(argv)
    if not args.list_models and not args.model:
        parser.error('--model is required unless --list-models is given')
    if not args.i_consent:
        print(json.dumps({'status': 'refused', 'error_code': 'consent_required', 'sent_requests': 0}))
        return 2
    if args.list_models:
        result = list_models(registration=args.registration, bootstrap=args.bootstrap)
    else:
        result = run(args.model, registration=args.registration, bootstrap=args.bootstrap)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
