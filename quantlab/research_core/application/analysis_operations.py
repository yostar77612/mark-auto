"""Existing analysis worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from quantlab.core import ValidationError, canonical_json, content_hash


def analysis_plan(ports: UiOperationPorts, paths, request, *, emit=None):
    from quantlab.research_core.application.job_requests import validate_analysis_request
    from quantlab.research_analysis import build_analysis_packet, make_analysis_plan

    validate_analysis_request(request)
    ports.inputs.research_controls(paths)
    if emit:
        emit('progress', message=ports.text('ui.analysis_plan.recomputing_training_evidence'))
    from quantlab.research_core.adapters.saved_pool_source import load_original_dataset

    data = load_original_dataset(Path(request['original_dataset']['path']))
    packet = build_analysis_packet(
        source_campaign_dir=ports.files._root(paths) / 'campaigns' / request['campaign_reference'],
        original_dataset=data,
        attempt_ids=request['attempt_ids'],
        task=request['task'],
        max_runtime_seconds=120,
    )
    return make_analysis_plan(
        packet,
        model=request['model'],
        registration=request['registration'],
        provider_implementation=ports.subscription.implementation_provenance(),
        timeout_seconds=request['timeout_seconds'],
    )


def analysis_provider_for(ports: UiOperationPorts, paths, plan, *, authorized=False):
    reference = ports.auth.OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), plan['binding']['registration'])
    return ports.subscription.analysis_provider(plan, reference, network_opt_in=authorized, included_usage_policy_confirmed=authorized)


def _handle_ui_analysis_preview(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    allowed = {'request'}
    if set(payload) != allowed:
        raise ValidationError(ports.text('ui.execute_ui_operation.invalid_analysis_fields'))
    plan = analysis_plan(ports, paths, payload['request'], emit=emit)
    provider = analysis_provider_for(ports, paths, plan)
    reference = ports.auth.OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), plan['binding']['registration'])
    snapshot = provider.read_receipt_snapshot()
    account = ports.subscription.read_account_status(reference, ports.inputs.research_controls(paths))
    return {'analysis_id': plan['analysis_id'], 'plan': plan, 'receipt_snapshot': snapshot, 'account_status': account}


def _handle_ui_analysis_read(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.research_analysis import read_analysis

    output = root / 'analyses'
    expected = {'analysis_id'}
    durable = False
    if durable:
        if not ports.recovery.supports_durable_recovery():
            raise ValidationError(ports.text('ui.execute_ui_operation.windows_stop_evidence_only'))
    if durable:
        expected = {'analysis_id', 'registration', 'recovery_launch_id'}
    if set(payload) != expected:
        raise ValidationError(ports.text('ui.execute_ui_operation.invalid_saved_analysis_fields'))
    record = read_analysis(output, payload['analysis_id'])
    return {'analysis_id': payload['analysis_id'], 'record': record, 'cache_hit': True}


def _handle_ui_analysis_reconcile(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.research_analysis import reconcile_analysis, _read_analysis_journal

    output = root / 'analyses'
    expected = {'analysis_id', 'registration', 'stopped_job_id'}
    durable = 'recovery_launch_id' in payload
    if durable:
        if not ports.recovery.supports_durable_recovery():
            raise ValidationError(ports.text('ui.execute_ui_operation.windows_stop_evidence_only'))
    if durable:
        expected = {'analysis_id', 'registration', 'recovery_launch_id'}
    if set(payload) != expected:
        raise ValidationError(ports.text('ui.execute_ui_operation.invalid_saved_analysis_fields'))
    if not durable and descendants_stopped is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.process_still_running'))
    record = _read_analysis_journal(output, payload['analysis_id'])
    if record['plan']['binding']['registration'] != payload['registration']:
        raise ValidationError(ports.text('ui.execute_ui_operation.original_account_mismatch'))
    if durable:
        launch = ports.recovery.validate_stop_receipt(paths, payload['recovery_launch_id'], record=record)
        if launch['analysis_id'] != payload['analysis_id'] or launch['registration'] != payload['registration']:
            raise ValidationError(ports.text('ui.execute_ui_operation.stop_evidence_mismatch'))
    record = reconcile_analysis(
        output_root=output,
        analysis_id=payload['analysis_id'],
        provider=analysis_provider_for(ports, paths, record['plan']),
        descendants_stopped=descendants_stopped is True,
        recovery=(paths, payload['recovery_launch_id']) if durable else None,
    )
    return {'analysis_id': payload['analysis_id'], 'record': record, 'cache_hit': True}


def _handle_ui_analysis_run(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.research_analysis import run_analysis

    output = root / 'analyses'
    allowed = {'request', 'expected_analysis_id', 'expected_plan_hash', 'user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'}
    if 'approved_plan' in payload:
        allowed = allowed | {'approved_plan'}
    if set(payload) != allowed:
        raise ValidationError(ports.text('ui.execute_ui_operation.invalid_analysis_fields'))
    if any((payload[key] is not True for key in ('user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'))):
        raise ValidationError(ports.text('ui.execute_ui_operation.consent_required'))
    plan = analysis_plan(ports, paths, payload['request'], emit=emit)
    if payload['expected_analysis_id'] != plan['analysis_id'] or payload['expected_plan_hash'] != content_hash(plan):
        raise ValidationError(ports.text('ui.execute_ui_operation.preview_binding_changed'))
    if 'approved_plan' in payload and canonical_json(payload['approved_plan']) != canonical_json(plan):
        raise ValidationError(ports.text('ui.execute_ui_operation.approved_plan_mismatch'))
    if emit:
        emit('progress', message=ports.text('ui.execute_ui_operation.sending_single_request'))
    result = run_analysis(
        output_root=output,
        plan=plan,
        provider=analysis_provider_for(ports, paths, plan, authorized=True),
        expected_analysis_id=payload['expected_analysis_id'],
        user_confirmed=True,
    )
    return {'analysis_id': plan['analysis_id'], **result}
