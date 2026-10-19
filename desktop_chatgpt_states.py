"""Pure, fixed-code presentation; never interpret diagnostic prose."""

from desktop_strings import ui_text
from quantlab.desktop_errors import ERROR_LABELS

AUTH_CODES = frozenset(
    {
        'refresh_required',
        'reauthorization_required',
        'restore_refresh_failed',
        'credential_diagnosis',
        'invalid_credential',
        'registration_retry_required',
    }
)
QUOTA_CODES = frozenset({'quota_paused', 'models_http_rate_limited'})
SUCCESS_CODES = frozenset({'completed', 'success', 'plan_ready'})


def outcome_state(code):
    if type(code) is not str:
        return 'generic_failure'
    if code in AUTH_CODES:
        return 'auth_expired'
    if code in QUOTA_CODES:
        return 'quota_exhausted'
    if code in SUCCESS_CODES:
        return 'success'
    return 'generic_failure'


def outcome_presentation(code):
    state = outcome_state(code)
    # Literal catalog keys per state keep the string-key scan static.
    if state == 'success':
        return (ui_text('outcome.success.title'), ui_text('outcome.success.body'), None)
    if state == 'quota_exhausted':
        return (ui_text('outcome.quota_exhausted.title'), ui_text('outcome.quota_exhausted.body'), None)
    if state == 'auth_expired':
        return (ui_text('outcome.auth_expired.title'), ui_text('outcome.auth_expired.body'), 'reauthorize')
    return (ui_text('outcome.generic_failure.title'), ui_text('outcome.generic_failure.body'), None)


def outcome_message(code):
    title, body, _ = outcome_presentation(code)
    if outcome_state(code) == 'generic_failure' and type(code) is str and code != 'operation_failed':
        # Keep the specific fixed P0-05 text for known codes; unknown codes get the table's generic text.
        body = ERROR_LABELS.get(code, body)
    return title + '\n' + body


def campaign_outcome(result):
    """Use durable fixed receipt statuses, including failures returned as results."""
    if not isinstance(result, dict):
        return 'operation_failed'
    codes = [row.get('status') for row in result.get('provider_receipts', ()) if isinstance(row, dict)]
    for allowed in (QUOTA_CODES, AUTH_CODES):
        for code in codes:
            if type(code) is str and code in allowed:
                return code
    if any(code != 'completed' for code in codes):
        return 'operation_failed'
    return 'completed' if codes and result.get('status') == 'completed' else 'operation_failed'
