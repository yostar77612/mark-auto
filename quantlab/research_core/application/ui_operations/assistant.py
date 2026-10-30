"""Existing assistant worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from quantlab.core import ValidationError, content_hash
from quantlab.research_core.application.ui_operations.binding_policy import provider_binding_options


def connection_event_from_payload(ports: UiOperationPorts, payload):
    if not isinstance(payload, dict):
        raise ValidationError(ports.text('ui.connection_event_from_payload.invalid_event_format'))
    value = dict(payload)
    value['registrations'] = tuple((tuple(row) for row in value.get('registrations', ())))
    value['models'] = tuple(value.get('models', ()))
    if value.get('test_usage') is not None:
        value['test_usage'] = tuple(value['test_usage'])
    for key in ('model_labels', 'account_labels'):
        if key in value:
            value[key] = tuple((tuple(row) for row in value[key]))
    if 'reconciliation_action' in value:
        for key in ('inspection', 'account_status'):
            if value.get(key) is not None:
                value[key] = tuple(value[key])
        return ports.connection.ReconciliationEvent(**value)
    if 'test_usage' in value:
        return ports.connection.TestConnectionEvent(**value)
    return ports.connection.ConnectionEvent(**value)


def plan_provider(ports: UiOperationPorts, paths, data, config, options, *, for_usage=False):
    """Fixed bootstrap/control identity, never workspace-relative or random."""
    from dataclasses import asdict

    allowed = {
        'mode',
        'registration',
        'model',
        'max_calls',
        'timeout_seconds',
        'network_opt_in',
        'included_usage_policy_confirmed',
        'paid_api_fallback',
        'expected_binding',
    }
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValidationError(ports.text('ui.plan_provider.unsupported_settings'))
    raw = {key: value for key, value in options.items() if key != 'expected_binding'}
    if for_usage:
        if raw.get('network_opt_in') is not False or raw.get('included_usage_policy_confirmed') is not False:
            raise ValidationError(ports.text('ui.plan_provider.reconciliation_not_authorization'))
        validation = {**raw, 'network_opt_in': True, 'included_usage_policy_confirmed': True}
    else:
        validation = raw
    parsed = ports.connection.SubscriptionOptions(**validation)
    public = {key: value for key, value in asdict(parsed).items() if key not in ('network_opt_in', 'included_usage_policy_confirmed')}
    sources = ports.inputs.implementation_sources()
    identity = content_hash({'data_hash': data.manifest['data_hash'], 'config': config, 'provider': public, 'implementation_sources': sources})
    if not for_usage and options.get('expected_binding') != identity:
        raise ValidationError(ports.text('ui.plan_provider.request_binding_changed'))
    controls = ports.inputs.research_controls(paths)
    reference = ports.auth.OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), parsed.registration)
    provider = ports.subscription.ChatGPTPlanProvider(
        model=parsed.model,
        credential_reference=reference,
        budget_path=controls / ('chatgpt-plan-' + identity + '.sqlite3'),
        campaign_id=identity,
        network_opt_in=not for_usage,
        included_usage_policy_confirmed=not for_usage,
        max_calls=parsed.max_calls,
        timeout_seconds=parsed.timeout_seconds,
    )
    return (provider, identity)


def _handle_ui_chatgpt_auth(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from dataclasses import asdict

    if set(payload) != {'request'} or not isinstance(payload['request'], dict):
        raise ValidationError(ports.text('ui.execute_ui_operation.invalid_connection_fields'))
    request = ports.connection.ConnectionRequest(**payload['request'])

    def private_event(event):
        if emit is None:
            raise ValidationError(ports.text('ui.private_event.managed_private_channel_required'))
        emit('auth_progress', auth_event=asdict(event))

    if request.action in ('begin', 'first_sign_in', 'enable_plan') and emit is None:
        raise ValidationError(ports.text('ui.execute_ui_operation.managed_process_required'))
    result = ports.connection.run_connection_request(
        request, bootstrap=str(getattr(paths, 'bootstrap', None) or paths.root), emit=private_event, cancelled=lambda: False
    )
    if result.authorization_url is not None:
        raise ValidationError(ports.text('ui.execute_ui_operation.authorization_url_private'))
    return {'auth_event': asdict(result)}


def _handle_ui_chatgpt_reconcile(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.research import reconcile_interrupted_campaign
    from quantlab.configuration import config_from_json

    if descendants_stopped is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.subprocess_stop_unconfirmed'))
    if set(payload) != {'config', 'provider', 'binding', 'stopped_job_id'}:
        raise ValidationError(ports.text('ui.execute_ui_operation.unsupported_recovery_fields'))
    data = ports.inputs._dataset(root, {})
    config = dict(payload['config'])
    config['backtest_config'] = config_from_json(config['backtest_config'])
    generator, identity = plan_provider(ports, paths, data, config, payload['provider'], for_usage=True)
    if identity != payload['binding']:
        raise ValidationError(ports.text('ui.execute_ui_operation.research_identity_mismatch'))
    name = content_hash(
        {'dataset': data.manifest['data_hash'], 'config': config, 'provider': provider_binding_options({'mode': 'chatgpt_plan', 'binding': identity})}
    )
    state = reconcile_interrupted_campaign(output_dir=root / 'campaigns' / name, generator=generator, descendants_stopped=True)
    return {'binding': identity, 'state': state['status']}


def _handle_ui_chatgpt_usage(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    if set(payload) - {'registration', 'provider', 'config'}:
        raise ValidationError(ports.text('ui.execute_ui_operation.unsupported_reconciliation_fields'))
    reference = ports.auth.OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), payload['registration'])
    status = ports.subscription.read_account_status(reference, ports.inputs.research_controls(paths))
    result = {'registration': payload['registration'], 'account_status': status}
    if 'provider' in payload:
        from quantlab.configuration import config_from_json

        data = ports.inputs._dataset(root, {})
        config = dict(payload['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        provider, identity = plan_provider(ports, paths, data, config, payload['provider'], for_usage=True)
        if provider.credential_reference.registration != payload['registration']:
            raise ValidationError(ports.text('ui.execute_ui_operation.account_record_mismatch'))
        receipts = provider.read_receipt_snapshot()['receipts']
        if len(receipts) > 10000:
            raise ValidationError(ports.text('ui.execute_ui_operation.records_display_limit'))
        result.update(
            receipts=[{'sequence': row['sequence'], 'status': row['status']} for row in receipts],
            binding=identity,
            account_status=ports.subscription.read_account_status(reference, ports.inputs.research_controls(paths)),
        )
    return result
