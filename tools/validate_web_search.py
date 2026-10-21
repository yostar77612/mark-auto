"""Owner-run check: can this ChatGPT plan and model use hosted web_search?

Sends nothing unless --i-consent is given; then exactly one minimal streamed
Responses request with the same web_search tool settings as idea research.
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


def run(model, *, registration=None, bootstrap=None, transport=None, reference=None, clock=time.monotonic):
    from desktop_chatgpt_provider import PlanError, SSEParser, read_account_status, PlanHTTPTransport

    if reference is None:
        from desktop_chatgpt_auth import AuthSession, DPAPIVault, OAuthCredentialReference
        from quantlab.desktop_runtime import AppPaths

        root = Path(bootstrap) if bootstrap else AppPaths.discover().root
        registration = registration or AuthSession(DPAPIVault(str(root))).status_summary()['active_registration']
        if not registration:
            return summarize(None, ok=False, error='not_signed_in', elapsed=0, include_seen=False)
        reference = OAuthCredentialReference(str(root), registration)
        if read_account_status(reference, root / 'control-v1') != {'state': 'ready', 'pending': False}:
            return summarize(None, ok=False, error='account_not_ready', elapsed=0, include_seen=False)
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
    parser.add_argument('--model', required=True, help='Model slug shown in the MarkAuto settings page')
    parser.add_argument('--i-consent', action='store_true', help='Send exactly one request using your ChatGPT plan, including web search')
    parser.add_argument('--registration', help='Opaque sign-in reference; defaults to the active one')
    parser.add_argument('--bootstrap', help='MarkAuto data folder; defaults to the installed location')
    args = parser.parse_args(argv)
    if not args.i_consent:
        print(json.dumps({'status': 'refused', 'error_code': 'consent_required', 'sent_requests': 0}))
        return 2
    result = run(args.model, registration=args.registration, bootstrap=args.bootstrap)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
