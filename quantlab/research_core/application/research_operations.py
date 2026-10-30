"""Existing research worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from decimal import Decimal
from quantlab.core import Dataset, StrategySpec, ValidationError, content_hash, to_dict
from quantlab.research_core.application.ui_operations.assistant import plan_provider
from quantlab.research_core.application.ui_operations.binding_policy import provider_binding_options
from quantlab.research_core.application.ui_operations.data import candidate_record


def campaign_generator(ports: UiOperationPorts, paths, options):
    """Only explicit deterministic fixtures use this non-subscription adapter."""
    from quantlab.research import FixtureGenerator

    if not isinstance(options, dict) or options != {'mode': 'fixture'}:
        raise ValidationError(ports.text('ui.campaign_generator.subscription_only'))
    ports.inputs.research_controls(paths)
    return FixtureGenerator()


def _handle_ui_backtest(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.strategies import builtin_strategies, validate_strategy
    from quantlab.backtest import run_backtest
    from quantlab.configuration import config_from_json

    data = ports.inputs._dataset(root, payload)
    config = config_from_json(payload['config'])
    specs = list(builtin_strategies())
    provenance = None
    if payload.get('candidate'):
        if payload.get('batch'):
            raise ValidationError(ports.text('ui.execute_ui_operation.mixed_candidate_batch'))
        spec, provenance = candidate_record(ports, root, payload['candidate'])
        source_hash = data.manifest.get('parent_data_hash', data.manifest['data_hash'])
        if provenance['source_data_hash'] != source_hash:
            raise ValidationError(ports.text('ui.execute_ui_operation.candidate_dataset_mismatch'))
        specs = [spec]
    elif not payload.get('batch'):
        spec = next((s for s in specs if s.family == payload['family']), None)
        if spec is None:
            raise ValidationError(ports.text('ui.execute_ui_operation.unknown_family'))
        spec = StrategySpec(spec.strategy_id, spec.family, payload.get('parameters', dict(spec.parameters)), dict(spec.rules))
        validate_strategy(spec)
        specs = [spec]
    if provenance:
        manifest = {**data.manifest, 'desktop_candidate_reference': provenance['reference']}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(data.bars, manifest, dict(data.quality))
    reports = []
    summary_metrics = {'net_pnl': Decimal('0'), 'trade_count': 0}
    for spec in specs:
        result = run_backtest(data, spec, config)
        summary_metrics['net_pnl'] += Decimal(str(result.metrics['net_pnl']))
        summary_metrics['trade_count'] += result.metrics.get('trade_count', result.metrics.get('closed_trades', 0))
        reports_root = root / 'reports'
        ports.files.mkdir(reports_root, exist_ok=True)
        with ports.files.TemporaryDirectory(prefix='.partial-', dir=reports_root) as staging:
            files = ports.repository.export_report(result, Path(staging))
            folder = Path(files['result']).parent
            ports.repository.write_json(folder / 'strategy.json', spec)
            if provenance:
                ports.repository.write_json(folder / 'candidate_provenance.json', provenance)
            destination = reports_root / files['result_hash']
            if ports.files.exists(destination):
                if content_hash(ports.repository.load_result(destination / 'result.json')) != files['result_hash'] or ports.repository.read_json(
                    destination / 'strategy.json'
                ) != to_dict(spec):
                    raise ValidationError(ports.text('ui.execute_ui_operation.incomplete_report'))
            else:
                ports.files._promote_report(folder, destination)
            files = {key: str(destination / Path(value).name) if key != 'result_hash' else value for key, value in files.items()}
        reports.append(files)
    ports.repository.write_json(root / 'active_result.json', {'result_hash': reports[-1]['result_hash']})
    return {'reports': reports, 'metrics': to_dict(summary_metrics), 'source_type': data.manifest['source_type'], 'scope': 'research_only'}


def _handle_ui_campaign(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.research import run_campaign, demo_campaign_config
    from quantlab.configuration import config_from_json

    data = ports.inputs._dataset(root, payload)
    config = payload.get('config') or demo_campaign_config(data, ports.repository.demo_config())
    if isinstance(config.get('backtest_config'), dict):
        config['backtest_config'] = config_from_json(config['backtest_config'])
    options = payload['provider']
    if options.get('mode') == 'chatgpt_plan':
        generator, plan_identity = plan_provider(ports, paths, data, config, options)
        options = {'mode': 'chatgpt_plan', 'binding': plan_identity}
    elif options.get('mode') == 'manual':
        if payload.get('manual_export'):
            request = ports.manual.export_request_file(data, config, Path(payload['manual_export']))
            return {'manual_export': payload['manual_export'], 'request': request, 'mode': 'manual_unverified'}
        if options.get('response_path'):
            generator = ports.manual.import_response_file(data, config, Path(options['response_path']))
        else:
            generator = ports.manual.import_response(data, config, options.get('response_text', ''))
        generator.preflight(data, config)
        ports.inputs.research_controls(paths)
        options = {'mode': 'manual', 'package': generator.model}
    else:
        generator = campaign_generator(ports, paths, options)
    name = content_hash({'dataset': data.manifest['data_hash'], 'config': config, 'provider': provider_binding_options(options)})
    return run_campaign(
        data,
        config=config,
        generator=generator,
        output_dir=root / 'campaigns' / name,
        holdout_registry_path=ports.inputs.research_controls(paths) / 'holdout-registry.sqlite3',
    )
