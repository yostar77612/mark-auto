"""Pure bounded provider receipt contract, shared by research and adapters."""

import copy
import math
import re
from quantlab.core import ValidationError, content_hash


def _validated_receipt_snapshot(snapshot, expected_descriptor):
    """Strict allowlisted audit envelope; no raw bodies/paths/credentials accepted."""
    if (type(snapshot) is not dict or set(snapshot) != {'version', 'provider_descriptor_hash', 'receipts'}
        or type(snapshot['version']) is not int or snapshot['version'] != 1
        or snapshot['provider_descriptor_hash'] != content_hash(expected_descriptor)):
        raise ValidationError('Provider receipt binding mismatch')
    receipts = snapshot['receipts']
    if type(receipts) is not list or len(receipts) > 100:
        raise ValidationError('Provider receipt snapshot exceeds bounds')
    fields = {'billing_route', 'paid_api_fallback', 'token_upper_bound_enforced',
              'spend_upper_bound_enforced', 'account_credit_policy', 'sequence',
              'request_hash', 'request_bytes', 'status', 'response_hash', 'token_usage',
              'received_bytes', 'elapsed_seconds'}
    statuses = {
        'completed', 'reserved_unknown', 'user_confirmed_consumed', 'failed_or_interrupted', 'eligibility_blocked',
        'quota_paused', 'transient_blocked', 'invalid_request', 'configuration_blocked',
        'credential_diagnosis', 'grant_blocked', 'remote_error', 'cancelled',
        'deadline_exceeded', 'http_transport_failed', 'invalid_json', 'duplicate_json_key',
        'nonfinite_json', 'json_depth', 'json_object_required', 'stream_byte_limit',
        'event_count', 'event_byte_limit', 'done_without_completion', 'ambiguous_event_type',
        'duplicate_event_type', 'invalid_utf8', 'invalid_stream_chunk', 'truncated_event',
        'invalid_terminal_status', 'ambiguous_terminal', 'missing_output', 'invalid_output',
        'tools_or_unknown_output', 'incomplete_message', 'refusal_or_unknown_content',
        'ambiguous_candidate', 'candidate_byte_limit', 'candidate_family_mismatch',
        'invalid_credential', 'compressed_response', 'redirect_rejected', 'invalid_content_type',
        'request_byte_limit', 'ambiguous_terminal', 'invalid_event', 'invalid_response_id',
        'response_id_mismatch', 'response_incomplete', 'refusal_or_tool_event',
        'eof_without_completion'}
    for sequence, receipt in enumerate(receipts, 1):
        if type(receipt) is not dict or set(receipt) != fields:
            raise ValidationError('Invalid provider receipt fields')
        if (receipt['billing_route'] != 'chatgpt_plan' or receipt['account_credit_policy'] != 'unverified_user_setting'
            or any(receipt[key] is not False for key in ('paid_api_fallback', 'token_upper_bound_enforced', 'spend_upper_bound_enforced'))
            or type(receipt['sequence']) is not int or receipt['sequence'] != sequence
            or receipt['status'] not in statuses):
            raise ValidationError('Invalid provider receipt claims')
        for key in ('request_hash', 'response_hash'):
            value = receipt[key]
            if key == 'response_hash' and value is None:
                continue
            if type(value) is not str or not re.fullmatch('[a-f0-9]{64}', value):
                raise ValidationError('Invalid provider receipt digest')
        if type(receipt['request_bytes']) is not int or not 1 <= receipt['request_bytes'] <= 65536:
            raise ValidationError('Invalid provider receipt byte count')
        received = receipt['received_bytes']
        if received is not None and (type(received) is not int or not 0 <= received <= 1048576 + 8192):
            raise ValidationError('Invalid provider receipt byte count')
        elapsed = receipt['elapsed_seconds']
        if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 3600):
            raise ValidationError('Invalid provider receipt runtime')
        usage = receipt['token_usage']
        if usage != 'unknown':
            if (type(usage) is not dict or set(usage) != {'input_tokens', 'output_tokens', 'total_tokens'}
                or any(type(value) is not int or not 0 <= value <= 2**53 for value in usage.values())
                or usage['input_tokens'] + usage['output_tokens'] != usage['total_tokens']):
                raise ValidationError('Invalid observed token usage')
    return copy.deepcopy(receipts)
