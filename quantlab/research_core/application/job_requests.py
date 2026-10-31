"""Desktop job implementation extracted without changing safety control flow."""

from __future__ import annotations
from pathlib import Path
import re
import sys
import time
import uuid
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.runtime_support import validate_analysis_request


def _validate_idea_research_payload(payload):
    """Explicit per-run network and plan-usage consent; only bounded identity fields."""
    retry = 'retry_task_id' in payload
    if set(payload) != ({'retry_task_id', 'consent', 'registration', 'model'} if retry else {'request', 'registration', 'model'}):
        raise RuntimeSafetyError('Invalid idea research request')
    consent = payload['consent'] if retry else payload['request'].get('consent') if isinstance(payload['request'], dict) else None
    if consent != {'network': True, 'plan_usage': True}:
        raise RuntimeSafetyError('Explicit network and plan-usage consent required')
    if retry and (type(payload['retry_task_id']) is not str or not re.fullmatch(r'idea-[0-9a-f]{32}', payload['retry_task_id'])):
        raise RuntimeSafetyError('Invalid idea research request')
    if type(payload['model']) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', payload['model']):
        raise RuntimeSafetyError('Invalid idea research request')
    if type(payload['registration']) is not str or not re.fullmatch(r'[a-f0-9]{32}', payload['registration']):
        raise RuntimeSafetyError('Invalid idea research request')


def validate_walk_forward_request(plan_payload, saved_source=None):
    """Read-only desktop grammar; an unadmitted saved plan cannot carry DSL.

    The temporary builtin plan checks only chronology, costs and resource types.
    Its one-slot budget is never used to run an experiment or displayed as consent.
    The worker restores the explicit saved budget after authoritative admission.
    """
    # Keep operation-specific dependencies out of module startup.
    from quantlab.core import ValidationError

    # Keep operation-specific dependencies out of module startup.
    from quantlab.walk_forward import walk_forward_plan_from_dict

    if not isinstance(plan_payload, dict):
        raise ValidationError('Explicit walk-forward plan required')
    saved = plan_payload.get('pool_origin', 'exact_builtin_pool') == 'saved_campaign_pool'
    if not saved:
        if saved_source is not None:
            raise ValidationError('Built-in and saved pools cannot be mixed')
        return walk_forward_plan_from_dict(plan_payload)
    if 'candidate_pool' in plan_payload or 'pool_admission' in plan_payload:
        raise ValidationError('Saved candidates must be admitted from local source records')
    if (
        not isinstance(saved_source, dict)
        or set(saved_source) != {'campaign_reference', 'original_dataset'}
        or type(saved_source['campaign_reference']) is not str
        or not re.fullmatch(r'[0-9a-f]{64}', saved_source['campaign_reference'])
    ):
        raise ValidationError('Explicit immutable source campaign reference required')
    original = saved_source['original_dataset']
    if not isinstance(original, dict) or set(original) != {'kind', 'path'} or original['kind'] != 'local_dataset_file':
        raise ValidationError('Explicit local original dataset file reference required')
    path = original['path']
    if (
        type(path) is not str
        or not path
        or len(path) > 4096
        or '\0' in path
        or '://' in path
        or path.startswith(('//', '\\\\'))
        or not Path(path).is_absolute()
        or '..' in Path(path).parts
    ):
        raise ValidationError('Original dataset must be an explicitly selected local absolute file path')
    budget = plan_payload.get('max_evaluations')
    if type(budget) is not int or not 1 <= budget <= 620:
        raise ValidationError('Saved-pool evaluation budget must be explicitly set within 1..620')
    template = {**plan_payload, 'pool_origin': 'exact_builtin_pool', 'max_evaluations': 1}
    return walk_forward_plan_from_dict(template)


def _prepare_walk_forward_job(self, operation, payload):
    deadline = None
    walk_forward_reference = None
    walk_forward_result_reference = None
    reconciliation_admitted = False
    allowed = {
        'ui_walk_forward_preview': {'plan'},
        'ui_walk_forward_run': {'plan', 'preview_identity'},
        'ui_walk_forward_read': {'reference'},
        'ui_walk_forward_reconcile': {'reference', 'stopped_job_id'},
    }[operation]
    if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run') and 'saved_source' in payload:
        if not isinstance(payload.get('plan'), dict) or payload['plan'].get('pool_origin') != 'saved_campaign_pool':
            raise RuntimeSafetyError('Built-in and saved pools cannot be mixed')
        allowed = allowed | {'saved_source'}
    if set(payload) != allowed:
        raise RuntimeSafetyError('Unsupported walk-forward job parameters')
    if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run'):
        if not isinstance(payload['plan'], dict):
            raise RuntimeSafetyError('Explicit walk-forward plan required')
        # Keep operation-specific dependencies out of module startup.
        from quantlab.core import ValidationError

        try:
            plan = validate_walk_forward_request(payload['plan'], payload.get('saved_source'))
        except (ValidationError, TypeError, KeyError) as exc:
            raise RuntimeSafetyError('Invalid bounded walk-forward plan') from exc
        if operation == 'ui_walk_forward_run':
            walk_forward_reference = payload['preview_identity']
            walk_forward_result_reference = walk_forward_reference
            deadline = time.monotonic() + plan.max_runtime_seconds + 10
    else:
        walk_forward_result_reference = payload['reference']
    if operation != 'ui_walk_forward_preview':
        if not isinstance(walk_forward_result_reference, str) or not re.fullmatch(r'[0-9a-f]{64}', walk_forward_result_reference):
            raise RuntimeSafetyError('Invalid walk-forward reference')
    if operation == 'ui_walk_forward_run':
        journal = self.paths.state / 'walk_forward' / walk_forward_reference / 'walk_forward.sqlite3'
        if journal.exists() or journal.is_symlink():
            # A new reader's process stop is not proof about an older
            # journal writer. Never mint recovery authority by reopening.
            raise RuntimeSafetyError('Existing walk-forward journals are read-only; use read')
    if operation == 'ui_walk_forward_reconcile':
        if not self._quiesced_walk_forward or (payload['stopped_job_id'], payload['reference']) != self._quiesced_walk_forward:
            raise RuntimeSafetyError('Matching walk-forward subtree stop proof required')
        self._check_walk_forward_owner(payload['stopped_job_id'], payload['reference'])
        reconciliation_admitted = True
    if deadline is None:
        deadline = time.monotonic() + 60
    return deadline, walk_forward_reference, walk_forward_result_reference, reconciliation_admitted


def _prepare_analysis_job(self, operation, payload):
    analysis_job_identity = None
    analysis_result_reference = None
    approved_analysis_plan = None
    helper_nonce = None
    reconciliation_admitted = False
    request = None
    allowed = {
        'ui_analysis_preview': {'request'},
        'ui_analysis_run': {'request', 'expected_analysis_id', 'expected_plan_hash', 'user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'},
        'ui_analysis_read': {'analysis_id'},
        'ui_analysis_reconcile': {'analysis_id', 'registration', 'stopped_job_id'},
    }[operation]
    if operation == 'ui_analysis_run' and 'approved_plan' in payload:
        allowed = allowed | {'approved_plan'}
    if operation == 'ui_analysis_reconcile' and 'recovery_launch_id' in payload:
        allowed = {'analysis_id', 'registration', 'recovery_launch_id'}
    if set(payload) != allowed:
        raise RuntimeSafetyError('Invalid analysis job fields')
    if operation in ('ui_analysis_preview', 'ui_analysis_run'):
        request = validate_analysis_request(payload['request'])
        deadline = time.monotonic() + 120 + 10 + (request['timeout_seconds'] if operation == 'ui_analysis_run' else 0)
    else:
        deadline = time.monotonic() + 60
    if operation != 'ui_analysis_preview':
        reference = payload['expected_analysis_id'] if operation == 'ui_analysis_run' else payload['analysis_id']
        if type(reference) is not str or not re.fullmatch('[a-f0-9]{64}', reference):
            raise RuntimeSafetyError('Invalid analysis identity')
        analysis_result_reference = reference
    if operation == 'ui_analysis_run':
        if type(payload['expected_plan_hash']) is not str or not re.fullmatch('[a-f0-9]{64}', payload['expected_plan_hash']):
            raise RuntimeSafetyError('Invalid immutable analysis plan hash')
        if any(payload[key] is not True for key in ('user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed')):
            raise RuntimeSafetyError('Explicit one-call analysis consent required')
        analysis_job_identity = (reference, request['registration'])
        if 'approved_plan' in payload or sys.platform == 'win32':
            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery import plan_bindings

            # Keep operation-specific dependencies out of module startup.
            from quantlab.core import content_hash as content_hash

            approved_analysis_plan = payload.get('approved_plan')
            bindings = plan_bindings(approved_analysis_plan)
            if (
                bindings['analysis_id'] != reference
                or bindings['plan_hash'] != payload['expected_plan_hash']
                or any(bindings[key] != request[key] for key in ('registration', 'model', 'timeout_seconds'))
            ):
                raise RuntimeSafetyError('Original approved analysis plan differs')
        if sys.platform == 'win32':
            helper_nonce = uuid.uuid4().hex
    if operation == 'ui_analysis_reconcile':
        if 'recovery_launch_id' in payload:
            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery import validate_stop_receipt, supports_durable_recovery

            if not supports_durable_recovery():
                raise RuntimeSafetyError('Durable analysis recovery requires Windows')
            launch = validate_stop_receipt(self.paths, payload['recovery_launch_id'])
            if launch['analysis_id'] != reference or launch['registration'] != payload['registration']:
                raise RuntimeSafetyError('Original durable analysis binding differs')
        else:
            if self._quiesced_analysis != (payload['stopped_job_id'], reference, payload['registration']):
                raise RuntimeSafetyError('Matching analysis subtree stop proof required')
            reconciliation_admitted = True
    return (deadline, analysis_job_identity, analysis_result_reference, approved_analysis_plan, helper_nonce, reconciliation_admitted, request)


def _prepare_other_job(self, operation, payload):
    deadline = None
    auth_request_id = None
    reconciliation_admitted = False
    if operation == 'ui_chatgpt_auth':
        request = payload.get('request')
        if set(payload) != {'request'} or not isinstance(request, dict):
            raise RuntimeSafetyError('Invalid authentication request')
        allowed = {'request_id', 'action', 'registration', 'max_runtime_seconds', 'user_confirmed'}
        # ConnectionRequest always serializes the connection-test model (None for other actions).
        if (
            not allowed <= set(request) <= allowed | {'model', 'acknowledgement_version', 'expected_sequence', 'expected_calls', 'expected_outcome'}
            or request.get('model') is not None
            and (type(request['model']) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request['model']))
            or type(request['request_id']) is not int
            or request['request_id'] < 1
            or type(request['max_runtime_seconds']) is not int
            or not 1 <= request['max_runtime_seconds'] <= 600
        ):
            raise RuntimeSafetyError('Invalid bounded authentication request')
        version = request.get('acknowledgement_version')
        if request.get('action') in ('resolve_unknown', 'resolve_finished_unknown'):
            if type(version) is not int or version != 1 or request.get('user_confirmed') is not True:
                raise RuntimeSafetyError('Invalid resolution acknowledgement')
        elif version is not None:
            raise RuntimeSafetyError('Unexpected resolution acknowledgement')
        expected = tuple(request.get(key) for key in ('expected_sequence', 'expected_calls', 'expected_outcome'))
        if request.get('action') == 'resolve_finished_unknown':
            if (
                any(type(value) is not int or not 1 <= value <= 100 for value in expected[:2])
                or type(expected[2]) is not str
                or not re.fullmatch(r'[a-z_]{1,64}', expected[2])
            ):
                raise RuntimeSafetyError('Invalid finished resolution target')
        elif expected != (None, None, None):
            raise RuntimeSafetyError('Unexpected finished resolution target')
        if request.get('action') in ('inspect_unknown', 'resolve_unknown', 'resolve_finished_unknown') and (
            type(request.get('registration')) is not str or not re.fullmatch(r'[a-f0-9]{32}', request['registration'])
        ):
            raise RuntimeSafetyError('Invalid reconciliation registration')
        auth_request_id = request['request_id']
        deadline = time.monotonic() + request['max_runtime_seconds'] + 5
    elif operation in ('ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
        if operation == 'ui_chatgpt_reconcile' and (not self._quiesced_subscription_id or payload.get('stopped_job_id') != self._quiesced_subscription_id):
            raise RuntimeSafetyError('Subscription subtree stop proof required')
        reconciliation_admitted = operation == 'ui_chatgpt_reconcile'
        deadline = time.monotonic() + 60
    elif operation == 'ui_idea_research':
        _validate_idea_research_payload(payload)
        # 150 s research budget plus the same 10 s worker margin as other plan calls.
        deadline = time.monotonic() + 150 + 10
    elif operation == 'ui_idea_adopt':
        if set(payload) != {'task_id', 'candidate_id', 'config'} or not isinstance(payload['config'], dict):
            raise RuntimeSafetyError('Invalid idea adoption request')
        if type(payload['task_id']) is not str or not re.fullmatch(r'idea-[0-9a-f]{32}', payload['task_id']):
            raise RuntimeSafetyError('Invalid idea adoption request')
        if type(payload['candidate_id']) is not str or not re.fullmatch(r'c[1-3]', payload['candidate_id']):
            raise RuntimeSafetyError('Invalid idea adoption request')
    elif operation == 'ui_campaign' and payload.get('provider', {}).get('mode') == 'chatgpt_plan':
        seconds = payload.get('config', {}).get('max_runtime_seconds')
        if type(seconds) is not int or not 1 <= seconds <= 7200:
            raise RuntimeSafetyError('Explicit bounded subscription campaign required')
        deadline = time.monotonic() + seconds + 10
    return deadline, auth_request_id, reconciliation_admitted
