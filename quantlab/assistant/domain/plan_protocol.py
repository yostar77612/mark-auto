"""Plan protocol responsibility; original guards and ordering preserved."""

from __future__ import annotations

from quantlab.core import ValidationError
import json
import math
import re


MODELS_URL = 'https://api.openai.com/v1/models'


MODELS_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


RESPONSES_URL = 'https://api.openai.com/v1/responses'


ACKNOWLEDGEMENT_VERSION = 1


_CONFIRMED_CONSUMED = 'user_confirmed_consumed'


_RESOLUTION_MIN_AGE_SECONDS = 300


_FINISHED_UNKNOWN_STATUSES = frozenset(
    (
        'ambiguous_candidate',
        'ambiguous_event_type',
        'ambiguous_terminal',
        'cancelled',
        'candidate_byte_limit',
        'candidate_family_mismatch',
        'compressed_response',
        'deadline_exceeded',
        'done_without_completion',
        'duplicate_event_type',
        'duplicate_json_key',
        'eof_without_completion',
        'event_byte_limit',
        'event_count',
        'failed_or_interrupted',
        'http_transport_failed',
        'incomplete_message',
        'invalid_content_type',
        'invalid_credential',
        'invalid_event',
        'invalid_json',
        'invalid_output',
        'invalid_response_id',
        'invalid_stream_chunk',
        'invalid_terminal_status',
        'invalid_utf8',
        'json_depth',
        'json_object_required',
        'missing_output',
        'nonfinite_json',
        'redirect_rejected',
        'refusal_or_tool_event',
        'refusal_or_unknown_content',
        'remote_error',
        'request_byte_limit',
        'response_id_mismatch',
        'response_incomplete',
        'stream_byte_limit',
        'tools_or_unknown_output',
        'truncated_event',
    )
)


FINISHED_ACKNOWLEDGEMENT_VERSION = 1


_FINISHED_ACKNOWLEDGEMENT_VERSIONS = frozenset((1,))


ERROR_STATES = {
    'subscription_sharing_user_not_eligible': 'eligibility_blocked',
    'subscription_sharing_usage_limit_exceeded': 'quota_paused',
    'subscription_sharing_usage_unavailable': 'transient_blocked',
    'subscription_sharing_user_unavailable': 'transient_blocked',
    'subscription_sharing_unsupported_capability': 'invalid_request',
    'subscription_sharing_route_not_supported': 'configuration_blocked',
    'subscription_sharing_invalid_user': 'credential_diagnosis',
    'chatpass_v2_scope_not_authorized': 'grant_blocked',
    'chatpass_v2_invalid_authorization_context': 'grant_blocked',
}


class PlanError(ValidationError):
    """Fixed allowlisted local codes only, never remote text or tokens."""

    def __init__(self, code, *, http_status=None, remote_code=None):
        self.code = code
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.remote_code = remote_code if isinstance(remote_code, str) and remote_code in ERROR_STATES else None
        super().__init__(code)


def _fail(code):
    raise PlanError(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('duplicate_json_key')
        result[key] = value
    return result


def _json(text):
    try:
        value = json.loads(text, object_pairs_hook=_unique, parse_constant=lambda _: _fail('nonfinite_json'))

        def walk(item, depth=0):
            if depth > 24:
                _fail('json_depth')
            if isinstance(item, float) and not math.isfinite(item):
                _fail('nonfinite_json')
            if isinstance(item, dict):
                for v in item.values():
                    walk(v, depth + 1)
            elif isinstance(item, list):
                for v in item:
                    walk(v, depth + 1)

        walk(value)
        if type(value) is not dict:
            _fail('json_object_required')
        return value
    except (ValueError, UnicodeError, RecursionError):
        _fail('invalid_json')


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('invalid_limit')
    return value


def _remote_error(value, *, http_status=None):
    # Admission `detail` is diagnostic prose, never a stable machine code.
    # Retain only safe status and documented codes; no remote prose or URLs.
    error = value.get('error') if isinstance(value, dict) else None
    code = error.get('code') if isinstance(error, dict) else None
    code = code if isinstance(code, str) and code in ERROR_STATES else None
    fallback = {401: 'credential_diagnosis', 403: 'grant_blocked', 503: 'transient_blocked'}.get(http_status, 'remote_error')
    raise PlanError(ERROR_STATES.get(code, fallback), http_status=http_status, remote_code=code)


def parse_models(value):
    """Return only visible slugs/display names, preserving official ordering."""
    if not isinstance(value, dict) or not isinstance(value.get('models'), list):
        _fail('invalid_catalog')
    if not 1 <= len(value['models']) <= 1024:
        _fail('invalid_catalog')
    result, seen = [], set()
    for item in value['models']:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get('slug'), str)
            or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', item['slug'])
            or not isinstance(item.get('display_name'), str)
            or not 1 <= len(item['display_name']) <= 256
            or any(ord(c) < 32 for c in item['display_name'])
            or not isinstance(item.get('visibility'), str)
            or not item['visibility']
        ):
            _fail('invalid_catalog')
        if item['slug'] in seen:
            _fail('duplicate_model')
        seen.add(item['slug'])
        if item['visibility'] == 'list':
            result.append({'slug': item['slug'], 'display_name': item['display_name']})
    if not result:
        _fail('empty_catalog')
    return result
