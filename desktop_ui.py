"""Native Traditional Chinese Qt workspace. No web server or live execution imports.

The GUI only schedules work. execute_ui_operation runs in the runtime's isolated
worker process; its inputs are data, never executable strategy source.
"""
from desktop_theme import apply_theme, set_status, set_theme_property, status_for_color
from desktop_strings import ui_text
from pathlib import Path
from quantlab.desktop_errors import error_message, exception_code
from quantlab.desktop_feedback import completion_summary, stop_presentation
import json
from datetime import datetime
from decimal import Decimal

from quantlab.core import (Dataset, StrategySpec, Instrument, ValidationError, canonical_json,
                   content_hash, to_dict)
from quantlab.reporting import (read_json, write_json, load_dataset, save_dataset, synthetic_dataset,
                        demo_config, export_report, load_result, comparison_rows,
                        save_selection, load_selection, saved_analysis_entries)

UI_OPERATIONS = frozenset('ui_' + op for op in (
    'analysis_preview', 'analysis_run', 'analysis_read', 'analysis_reconcile',
    'walk_forward_preview', 'walk_forward_run', 'walk_forward_read', 'walk_forward_reconcile',
    'demo', 'import', 'refresh', 'market_refresh', 'chatgpt_auth', 'chatgpt_usage', 'chatgpt_reconcile', 'backtest', 'campaign', 'compare', 'select', 'disable',
    'paper_snapshot', 'paper_reconcile', 'paper_kill', 'paper_replay', 'paper_submit', 'paper_cancel',
    'backup_create', 'backup_restore'))


def research_controls(paths):
    """Irreversible budget/holdout ledgers must never be rolled back with user state."""
    state = Path(paths.state)
    legacy = list((state / 'provider_budgets').glob('*'))
    legacy.extend((state / 'campaigns').glob('.holdout_registry.sqlite3*'))
    if any(path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in legacy):
        raise ValidationError(ui_text('ui.research_controls.text_1'))
    controls = Path(paths.controls)
    if controls.resolve().is_relative_to(state.resolve()):
        raise ValidationError(ui_text('ui.research_controls.text_2'))
    return controls


def provider_binding_options(options):
    # Preserve historical provider identities; these options cannot enable a removed provider.
    return {key: value for key, value in options.items()
            if key != 'network_opt_in' and not (options.get('mode') == 'local' and key == 'owner') and not (key == 'output_mode' and value == 'json_object')}


def campaign_generator(paths, options):
    """Only explicit deterministic fixtures use this non-subscription adapter."""
    from quantlab.research import FixtureGenerator
    if not isinstance(options, dict) or options != {'mode': 'fixture'}:
        raise ValidationError(ui_text('ui.campaign_generator.text_1'))
    research_controls(paths)
    return FixtureGenerator()


def connection_event_from_payload(payload):
    from desktop_chatgpt_ui import ConnectionEvent
    if not isinstance(payload, dict): raise ValidationError(ui_text('ui.connection_event_from_payload.text_1'))
    value = dict(payload)
    value['registrations'] = tuple(tuple(row) for row in value.get('registrations', ()))
    value['models'] = tuple(value.get('models', ()))
    for key in ('model_labels', 'account_labels'):
        if key in value:
            value[key] = tuple(tuple(row) for row in value[key])
    return ConnectionEvent(**value)


def plan_provider(paths, data, config, options, *, for_usage=False):
    """Fixed bootstrap/control identity, never workspace-relative or random."""
    from desktop_chatgpt_auth import OAuthCredentialReference
    from desktop_chatgpt_provider import ChatGPTPlanProvider
    from desktop_chatgpt_ui import SubscriptionOptions
    from dataclasses import asdict
    allowed = {'mode','registration','model','max_calls','timeout_seconds','network_opt_in',
               'included_usage_policy_confirmed','paid_api_fallback','expected_binding'}
    if not isinstance(options, dict) or set(options)-allowed: raise ValidationError(ui_text('ui.plan_provider.text_1'))
    raw = {key:value for key,value in options.items() if key != 'expected_binding'}
    if for_usage:
        if raw.get('network_opt_in') is not False or raw.get('included_usage_policy_confirmed') is not False:
            raise ValidationError(ui_text('ui.plan_provider.text_2'))
        validation = {**raw, 'network_opt_in':True, 'included_usage_policy_confirmed':True}
    else:
        validation = raw
    parsed = SubscriptionOptions(**validation)
    public = {key:value for key,value in asdict(parsed).items() if key not in ('network_opt_in','included_usage_policy_confirmed')}
    import hashlib
    source_root = Path(__file__).parent
    source_files = ('desktop_chatgpt_auth.py','desktop_chatgpt_provider.py','quantlab/core.py',
                    'quantlab/backtest.py','quantlab/research.py','quantlab/strategies.py',
                    'desktop_chatgpt_dependency_manifest.json')
    sources = {name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in source_files}
    identity = content_hash({'data_hash':data.manifest['data_hash'], 'config':config,
                             'provider':public, 'implementation_sources':sources})
    if not for_usage and options.get('expected_binding') != identity:
        raise ValidationError(ui_text('ui.plan_provider.text_3'))
    controls = research_controls(paths)
    reference = OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root), parsed.registration)
    provider = ChatGPTPlanProvider(model=parsed.model, credential_reference=reference,
        budget_path=controls/('chatgpt-plan-'+identity+'.sqlite3'), campaign_id=identity,
        network_opt_in=not for_usage, included_usage_policy_confirmed=not for_usage,
        max_calls=parsed.max_calls, timeout_seconds=parsed.timeout_seconds)
    return provider, identity


def candidate_record(root, reference):
    """Resolve a persisted, hash-bound DSL candidate and independent evaluation gate."""
    from quantlab.research import validate_dsl
    campaigns = (Path(root) / 'campaigns').resolve()
    folder = str(reference.get('campaign_folder', ''))
    if len(folder) != 64 or any(c not in '0123456789abcdef' for c in folder):
        raise ValidationError(ui_text('ui.candidate_record.text_1'))
    path = campaigns / folder / 'campaign.json'
    if not path.resolve().is_relative_to(campaigns): raise ValidationError(ui_text('ui.candidate_record.text_2'))
    state = read_json(path)
    # JSON is a review export; qualify only if it equals the authoritative journal.
    import sqlite3
    from contextlib import closing
    journal = path.with_name('campaign.sqlite3')
    if not journal.resolve().is_relative_to(campaigns) or not journal.is_file():
        raise ValidationError(ui_text('ui.candidate_record.text_3'))
    with closing(sqlite3.connect(journal.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as database:
        row = database.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if not row or canonical_json(json.loads(row[0])) != canonical_json(state):
        raise ValidationError(ui_text('ui.candidate_record.text_4'))
    if state.get('selection_hash') != content_hash(state.get('selected', [])):
        raise ValidationError(ui_text('ui.candidate_record.text_5'))
    if state.get('campaign_id') != content_hash(state.get('binding')):
        raise ValidationError(ui_text('ui.candidate_record.text_6'))
    attempt = next((a for a in state.get('attempts', []) if a.get('attempt_id') == reference.get('attempt_id')), None)
    if not attempt or attempt.get('status') != 'evaluated': raise ValidationError(ui_text('ui.candidate_record.text_7'))
    spec = validate_dsl(attempt.get('spec'))
    digest = content_hash(spec)
    if digest != attempt.get('strategy_hash') or digest != reference.get('strategy_hash'):
        raise ValidationError(ui_text('ui.candidate_record.text_8'))
    ranking = state['binding']['config']['ranking']
    selected = any(x.get('strategy_hash') == digest for x in state.get('selected', []))
    qualified = selected and state.get('status') == 'completed'
    evaluations = {}
    for split in ('oos', 'holdout'):
        row = next((r for r in state.get('evaluations', {}).get(split, []) if r.get('strategy_hash') == digest), {})
        metrics = row.get('metrics', {})
        trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
        passed = (row.get('status') == 'evaluated' and metrics.get('net_pnl') is not None
                  and Decimal(str(metrics['net_pnl'])) >= Decimal(str(ranking['minimum']))
                  and trades >= ranking['min_trades'])
        qualified = qualified and passed
        evaluations[split] = {'qualified':passed, 'evaluation':row}
    return spec, {'reference':reference, 'paper_qualified':bool(qualified), 'evaluations':evaluations,
                  'source_type':state.get('source_manifest', {}).get('source_type', 'unknown'),
                  'source_data_hash':state.get('source_manifest', {}).get('data_hash'),
                  'real_model_status':state.get('real_model_status', 'not_verified'),
                  'note':ui_text('ui.candidate_record.text_9')}


def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset(root, payload):
    data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
    start, end = payload.get('start_date'), payload.get('end_date')
    if start or end:
        if start and end and start > end:
            raise ValidationError(ui_text('ui._dataset.text_1'))
        bars = tuple(b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end))
        if not bars:
            raise ValidationError(ui_text('ui._dataset.text_2'))
        manifest = {**data.manifest, 'parent_data_hash': data.manifest['data_hash'],
                    'data_hash': content_hash(bars), 'date_filter': {'start': start, 'end': end}}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(data.quality))
    return data


def paper_risk_limits():
    """The same fixed enforced limits supply both brokers and the read-only UI."""
    from quantlab.paper import RiskLimits
    return RiskLimits(1, 1, Decimal('1000'), 30)


def _paper(root):
    from quantlab.paper import PaperBroker
    policy = read_json(root / 'paper_policy.json')
    return PaperBroker(root / 'paper.sqlite3', instrument=Instrument(policy['contract_id']),
                       costs=demo_config().costs, limits=paper_risk_limits(),
                       risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))


def analysis_plan(paths, request, *, emit=None):
    from quantlab.desktop_runtime import validate_analysis_request
    from quantlab.research_analysis import build_analysis_packet, make_analysis_plan
    from desktop_chatgpt_provider import implementation_provenance
    validate_analysis_request(request)
    research_controls(paths)
    if emit: emit('progress',message=ui_text('ui.analysis_plan.text_1'))
    from quantlab.saved_candidate_pool import load_original_dataset
    data=load_original_dataset(Path(request['original_dataset']['path']))
    packet=build_analysis_packet(source_campaign_dir=_root(paths)/'campaigns'/request['campaign_reference'],
        original_dataset=data,attempt_ids=request['attempt_ids'],task=request['task'],max_runtime_seconds=120)
    return make_analysis_plan(packet,model=request['model'],registration=request['registration'],
        provider_implementation=implementation_provenance(),timeout_seconds=request['timeout_seconds'])


def analysis_provider_for(paths, plan, *, authorized=False):
    from desktop_chatgpt_auth import OAuthCredentialReference
    from desktop_chatgpt_provider import analysis_provider
    reference=OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),plan['binding']['registration'])
    return analysis_provider(plan,reference,network_opt_in=authorized,included_usage_policy_confirmed=authorized)


ANALYSIS_NOTICE=ui_text('ui.labels.text_1')
ANALYSIS_WARNING=ui_text('ui.labels.text_2')
ANALYSIS_CHECKPOINT_STATUS=ui_text('ui.labels.text_3')
ANALYSIS_CHECKPOINT_NOTICE=(ui_text('ui.labels.text_4').format(ANALYSIS_CHECKPOINT_STATUS))
ANALYSIS_METRICS={'net_pnl':ui_text('ui.labels.text_5'),'realized_gross_pnl':ui_text('ui.labels.text_6'),'unrealized_pnl':ui_text('ui.labels.text_7'),
    'total_costs':ui_text('ui.labels.text_8'),'slippage_cost':ui_text('ui.labels.text_9'),'return':ui_text('ui.labels.text_10'),'max_drawdown':ui_text('ui.labels.text_11'),
    'max_drawdown_pct':ui_text('ui.labels.text_12'),'trade_count':ui_text('ui.labels.text_13'),'fill_count':ui_text('ui.labels.text_14'),'win_rate':ui_text('ui.labels.text_15'),
    'profit_factor':'Profit Factor','sharpe':'Sharpe','sharpe_observations':ui_text('ui.labels.text_16'),
    'sharpe_sample_count':ui_text('ui.labels.text_17'),'open_position':ui_text('ui.labels.text_18')}
ANALYSIS_KINDS={'market':ui_text('ui.labels.text_19'),'entry_exit':ui_text('ui.labels.text_20'),'backtest':ui_text('ui.labels.text_21'),'weakness':ui_text('ui.labels.text_22'),
    'risk':ui_text('ui.labels.text_23'),'improvement':ui_text('ui.labels.text_24'),'comparison':ui_text('ui.labels.text_25')}


def analysis_preview_text(plan):
    from quantlab.research_analysis import validate_analysis_plan
    validate_analysis_plan(plan)
    binding=plan['binding'];context=binding['packet']['context'];training=context['training']
    lines=[ANALYSIS_NOTICE,ANALYSIS_WARNING,
        ui_text('ui.analysis_preview_text.text_1'),
        ui_text('ui.analysis_preview_text.text_2').format(binding['model'], str(binding['timeout_seconds'])),
        ui_text('ui.analysis_preview_text.text_3').format(plan['analysis_id']),
        ui_text('ui.analysis_preview_text.text_4').format(str(training['window_count']), str(training['bar_count']))]
    for row in context['strategies']:
        lines.append(ui_text('ui.analysis_preview_text.text_5').format(row['strategy_hash'], row['spec']['family'], canonical_json(row['spec']['parameters'])))
    for row in context['evidence']:
        lines.append(ui_text('ui.analysis_preview_text.text_8').format(ui_text('ui.analysis_preview_text.text_6') if row['split']=='train' else ui_text('ui.analysis_preview_text.text_7'), row['strategy_hash'][:16]))
        lines.append(ui_text('ui.analysis_preview_text.text_9').join(ANALYSIS_METRICS.get(key,key)+'='+(ui_text('ui.analysis_preview_text.text_10') if value is None else str(value)) for key,value in row['metrics'].items()))
    lines.append(ui_text('ui.analysis_preview_text.text_11'))
    return '\n'.join(lines)


def analysis_record_text(record):
    # read_analysis/run_analysis already enforce record and evidence bindings.
    from quantlab.research_analysis import validate_analysis_plan, validate_analysis_response
    plan=validate_analysis_plan(record['plan']);context=plan['binding']['packet']['context']
    lines=[ANALYSIS_WARNING,ANALYSIS_NOTICE,ui_text('ui.analysis_record_text.text_1').format(plan['analysis_id']),ui_text('ui.analysis_record_text.text_6').format({'completed':ui_text('ui.analysis_record_text.text_2'),'blocked':ui_text('ui.analysis_record_text.text_3'),'running':ui_text('ui.analysis_record_text.text_4')}.get(record['status'],ui_text('ui.analysis_record_text.text_5')))]
    if record['status']!='completed':return '\n'.join(lines)
    response=validate_analysis_response(record['response'],context)
    evidence={row['evidence_id']:row for row in context['evidence']};training=context['training']
    for row in response['findings']:
        lines+=['',ui_text('ui.analysis_record_text.text_7').format(ANALYSIS_KINDS[row['kind']], row['text']),ui_text('ui.analysis_record_text.text_8').format(', '.join(value[:16] for value in row['strategy_hashes']))]
        if 'signal_parameter' in row:lines.append(ui_text('ui.analysis_record_text.text_9').format(row['signal_parameter']))
        for ref in row['evidence_refs']:
            if ref['evidence_id']==training['evidence_id']:
                lines.append(ui_text('ui.analysis_record_text.text_10').format(ref['field'], str(training['window_count'])))
            else:
                local=evidence[ref['evidence_id']];value=local['metrics'][ref['field']]
                split=ui_text('ui.analysis_record_text.text_13').format(ui_text('ui.analysis_record_text.text_11') if local['split']=='train' else ui_text('ui.analysis_record_text.text_12'), local['split'])
                lines.append(ui_text('ui.analysis_record_text.text_15').format(local['strategy_hash'][:16], split, ANALYSIS_METRICS.get(ref['field'],ref['field']), ui_text('ui.analysis_record_text.text_14') if value is None else str(value)))
    return '\n'.join(lines)


def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError(ui_text('ui.execute_ui_operation.text_1'))
    if operation == 'ui_campaign' and (not isinstance(payload.get('provider'), dict)
        or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')):
        raise ValidationError(ui_text('ui.execute_ui_operation.text_2'))
    root = _root(paths)
    if operation.startswith('ui_analysis_'):
        from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal
        from desktop_chatgpt_auth import OAuthCredentialReference
        from desktop_chatgpt_provider import read_account_status
        output=root/'analyses'
        if operation in ('ui_analysis_preview','ui_analysis_run'):
            allowed={'request'} if operation=='ui_analysis_preview' else {'request','expected_analysis_id','expected_plan_hash','user_confirmed','network_opt_in','included_usage_policy_confirmed'}
            if operation=='ui_analysis_run' and 'approved_plan' in payload:allowed=allowed|{'approved_plan'}
            if set(payload)!=allowed:raise ValidationError(ui_text('ui.execute_ui_operation.text_3'))
            if operation=='ui_analysis_run' and any(payload[key] is not True for key in ('user_confirmed','network_opt_in','included_usage_policy_confirmed')):
                raise ValidationError(ui_text('ui.execute_ui_operation.text_4'))
            plan=analysis_plan(paths,payload['request'],emit=emit)
            if operation=='ui_analysis_preview':
                provider=analysis_provider_for(paths,plan)
                reference=OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),plan['binding']['registration'])
                snapshot=provider.read_receipt_snapshot()
                account=read_account_status(reference,research_controls(paths))
                return {'analysis_id':plan['analysis_id'],'plan':plan,'receipt_snapshot':snapshot,'account_status':account}
            if payload['expected_analysis_id']!=plan['analysis_id'] or payload['expected_plan_hash']!=content_hash(plan):raise ValidationError(ui_text('ui.execute_ui_operation.text_5'))
            if 'approved_plan' in payload and canonical_json(payload['approved_plan'])!=canonical_json(plan):raise ValidationError(ui_text('ui.execute_ui_operation.text_6'))
            if emit:emit('progress',message=ui_text('ui.execute_ui_operation.text_7'))
            result=run_analysis(output_root=output,plan=plan,provider=analysis_provider_for(paths,plan,authorized=True),
                expected_analysis_id=payload['expected_analysis_id'],user_confirmed=True)
            return {'analysis_id':plan['analysis_id'],**result}
        expected={'analysis_id'} if operation=='ui_analysis_read' else {'analysis_id','registration','stopped_job_id'}
        durable=operation=='ui_analysis_reconcile' and 'recovery_launch_id' in payload
        if durable:
            from quantlab.analysis_recovery import supports_durable_recovery
            if not supports_durable_recovery():raise ValidationError(ui_text('ui.execute_ui_operation.text_8'))
        if durable:expected={'analysis_id','registration','recovery_launch_id'}
        if set(payload)!=expected:raise ValidationError(ui_text('ui.execute_ui_operation.text_9'))
        if operation=='ui_analysis_reconcile' and not durable and descendants_stopped is not True:raise ValidationError(ui_text('ui.execute_ui_operation.text_10'))
        if operation=='ui_analysis_reconcile':
            record=_read_analysis_journal(output,payload['analysis_id'])
            if record['plan']['binding']['registration']!=payload['registration']:raise ValidationError(ui_text('ui.execute_ui_operation.text_11'))
            if durable:
                from quantlab.analysis_recovery import validate_stop_receipt
                launch=validate_stop_receipt(paths,payload['recovery_launch_id'],record=record)
                if launch['analysis_id']!=payload['analysis_id'] or launch['registration']!=payload['registration']:raise ValidationError(ui_text('ui.execute_ui_operation.text_12'))
            record=reconcile_analysis(output_root=output,analysis_id=payload['analysis_id'],
                provider=analysis_provider_for(paths,record['plan']),descendants_stopped=descendants_stopped is True,
                recovery=(paths,payload['recovery_launch_id']) if durable else None)
        else:
            record=read_analysis(output,payload['analysis_id'])
        return {'analysis_id':payload['analysis_id'],'record':record,'cache_hit':True}
    if operation.startswith('ui_walk_forward_'):
        from desktop_walk_forward import execute_walk_forward
        return execute_walk_forward(operation, payload, paths, descendants_stopped=descendants_stopped)
    if operation == 'ui_chatgpt_auth':
        from desktop_chatgpt_ui import ConnectionRequest, run_connection_request
        from dataclasses import asdict
        if set(payload) != {'request'} or not isinstance(payload['request'], dict): raise ValidationError(ui_text('ui.execute_ui_operation.text_13'))
        request = ConnectionRequest(**payload['request'])
        def private_event(event):
            if emit is None: raise ValidationError(ui_text('ui.private_event.text_1'))
            emit('auth_progress', auth_event=asdict(event))
        if request.action in ('begin', 'first_sign_in', 'enable_plan') and emit is None: raise ValidationError(ui_text('ui.execute_ui_operation.text_14'))
        result = run_connection_request(request, bootstrap=str(getattr(paths,'bootstrap',None) or paths.root),
            emit=private_event, cancelled=lambda:False)
        if result.authorization_url is not None: raise ValidationError(ui_text('ui.execute_ui_operation.text_15'))
        return {'auth_event':asdict(result)}
    if operation == 'ui_chatgpt_reconcile':
        from quantlab.research import reconcile_interrupted_campaign
        from quantlab.__main__ import config_from_json
        if descendants_stopped is not True: raise ValidationError(ui_text('ui.execute_ui_operation.text_16'))
        if set(payload) != {'config','provider','binding','stopped_job_id'}: raise ValidationError(ui_text('ui.execute_ui_operation.text_17'))
        data = _dataset(root,{})
        config = dict(payload['config']); config['backtest_config'] = config_from_json(config['backtest_config'])
        generator, identity = plan_provider(paths,data,config,payload['provider'],for_usage=True)
        if identity != payload['binding']: raise ValidationError(ui_text('ui.execute_ui_operation.text_18'))
        name = content_hash({'dataset':data.manifest['data_hash'],'config':config,
            'provider':provider_binding_options({'mode':'chatgpt_plan','binding':identity})})
        # This operation is dispatched only after JobManager's subtree proof.
        state = reconcile_interrupted_campaign(output_dir=root/'campaigns'/name,
            generator=generator,descendants_stopped=True)
        return {'binding':identity,'state':state['status']}
    if operation == 'ui_chatgpt_usage':
        from desktop_chatgpt_auth import OAuthCredentialReference
        from desktop_chatgpt_provider import read_account_status
        if set(payload)-{'registration','provider','config'}: raise ValidationError(ui_text('ui.execute_ui_operation.text_19'))
        reference = OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),payload['registration'])
        status = read_account_status(reference, research_controls(paths))
        result = {'registration':payload['registration'], 'account_status':status}
        if 'provider' in payload:
            from quantlab.__main__ import config_from_json
            data = _dataset(root, {})
            config = dict(payload['config']);config['backtest_config'] = config_from_json(config['backtest_config'])
            provider, identity = plan_provider(paths, data, config, payload['provider'], for_usage=True)
            if provider.credential_reference.registration != payload['registration']: raise ValidationError(ui_text('ui.execute_ui_operation.text_20'))
            receipts = provider.read_receipt_snapshot()['receipts']
            if len(receipts)>10000: raise ValidationError(ui_text('ui.execute_ui_operation.text_21'))
            result.update(receipts=[{'sequence':row['sequence'],'status':row['status']} for row in receipts], binding=identity,
                          account_status=read_account_status(reference,research_controls(paths)))
        return result
    if operation in ('ui_backup_create', 'ui_backup_restore'):
        from quantlab.desktop_runtime import BackupManager
        manager = BackupManager(paths)
        if operation == 'ui_backup_restore':
            manager.restore(Path(payload['path']))
            return {'restored': True, 'reconciliation_required': True}
        return {'backup': str(manager.create(Path(payload['path'])))}
    if operation == 'ui_market_refresh' and 'history_import' in payload:
        if payload.get('history_import') is not True or set(payload) != {'history_import','local_path','sessions','dated_policy_confirmed'}:
            raise ValidationError(ui_text('ui.execute_ui_operation.text_22'))
        from quantlab.market_history import import_history, session_from_dict
        if payload.get('dated_policy_confirmed') is not True:
            raise ValidationError(ui_text('ui.execute_ui_operation.text_23'))
        records = payload.get('sessions')
        if not isinstance(records, list) or not 1 <= len(records) <= 128:
            raise ValidationError(ui_text('ui.execute_ui_operation.text_24'))
        if emit is not None: emit('progress', message=ui_text('ui.execute_ui_operation.text_25'))
        result = import_history(Path(payload['local_path']), root / 'market_history',
                                sessions=tuple(session_from_dict(row) for row in records))
        return {'mode': 'local_unverified_history', 'cache_id': result.cache_id,
                'source_hash': result.source_hash, 'policy_hash': result.policy_hash,
                'counters': dict(result.counters), 'warnings': list(result.warnings),
                'contracts': len(result.series), 'bars': sum(len(x.bars) for x in result.series)}
    if operation == 'ui_market_refresh':
        from quantlab.market_providers import refresh_daily, import_daily, MAX_BYTES
        # File imports use the same fixed official schema and atomic cache path.
        local = payload.get('local_path')
        if not local and payload.get('network_opt_in') is not True:
            raise ValidationError(ui_text('ui.execute_ui_operation.text_26'))
        providers = (payload.get('provider'),) if local else ('twse', 'taifex')
        outcomes = {}
        for provider in providers:
            if provider not in ('twse', 'taifex'): raise ValidationError(ui_text('ui.execute_ui_operation.text_27'))
            try:
                kwargs = {}
                if local:
                    path = Path(local)
                    if path.stat().st_size > MAX_BYTES: raise ValidationError(ui_text('ui.execute_ui_operation.text_28'))
                    with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES: raise ValidationError(ui_text('ui.execute_ui_operation.text_29'))
                    result = import_daily(provider, root / 'market_cache', raw, format=payload.get('format', 'json'))
                else:
                    result = refresh_daily(provider, root / 'market_cache', network_enabled=True, **kwargs)
                outcomes[provider] = {'stale': result.stale, 'error': result.error,
                    'contracts': len(result.series), 'bars': sum(len(x.bars) for x in result.series)}
            except Exception as exc:
                outcomes[provider] = {'stale': True, 'error': exception_code(exc), 'contracts': None, 'bars': None}
        return {'providers': outcomes, 'mode': 'official_local_import' if local else 'official_explicit_refresh'}
    if operation == 'ui_demo':
        data = synthetic_dataset(payload.get('bars', 960))
        save_dataset(data, root / 'dataset.json')
        return {'dataset': str(root / 'dataset.json'), 'source_type': 'synthetic', 'bars': len(data.bars)}
    if operation == 'ui_import':
        from quantlab.data import SessionCalendar, import_taifex
        cal = read_json(Path(payload['calendar']))
        if payload['kind'] == 'validated_dataset':
            data = load_dataset(Path(payload['path']))
            dataset_market_series(data, cal)
        else:
            data = import_taifex(Path(payload['path']), kind=payload['kind'],
                                calendar=SessionCalendar(cal['sessions'], version=cal['version']),
                                contract_id=payload.get('contract') or None, encoding=payload.get('encoding'))
        save_dataset(data, root / 'dataset.json')
        write_json(root / 'dataset_calendar.json', cal)
        return {'dataset': str(root / 'dataset.json'), 'bars':len(data.bars), 'manifest': to_dict(data.manifest), 'quality': to_dict(data.quality)}
    if operation == 'ui_refresh':
        if payload.get('network_opt_in') is not True:
            raise ValidationError(ui_text('ui.execute_ui_operation.text_30'))
        from quantlab.downloads import refresh
        return refresh(Path(paths.cache), days=payload.get('days', 1), kind=payload.get('format', 'csv'))
    if operation == 'ui_backtest':
        from quantlab.strategies import builtin_strategies, validate_strategy
        from quantlab.backtest import run_backtest
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = config_from_json(payload['config'])
        specs = list(builtin_strategies())
        provenance = None
        if payload.get('candidate'):
            if payload.get('batch'): raise ValidationError(ui_text('ui.execute_ui_operation.text_31'))
            spec, provenance = candidate_record(root, payload['candidate'])
            source_hash = data.manifest.get('parent_data_hash', data.manifest['data_hash'])
            if provenance['source_data_hash'] != source_hash: raise ValidationError(ui_text('ui.execute_ui_operation.text_32'))
            specs = [spec]
        elif not payload.get('batch'):
            spec = next((s for s in specs if s.family == payload['family']), None)
            if spec is None:
                raise ValidationError(ui_text('ui.execute_ui_operation.text_33'))
            spec = StrategySpec(spec.strategy_id, spec.family, payload.get('parameters', dict(spec.parameters)), dict(spec.rules))
            validate_strategy(spec)
            specs = [spec]
        if provenance:
            manifest = {**data.manifest, 'desktop_candidate_reference': provenance['reference']}
            manifest['manifest_hash'] = content_hash({k:v for k,v in manifest.items() if k not in ('imported_at','manifest_hash')})
            data = Dataset(data.bars, manifest, dict(data.quality))
        reports = []
        summary_metrics = {'net_pnl': Decimal('0'), 'trade_count': 0}
        for spec in specs:
            result = run_backtest(data, spec, config)
            summary_metrics['net_pnl'] += Decimal(str(result.metrics['net_pnl']))
            summary_metrics['trade_count'] += result.metrics.get('trade_count', result.metrics.get('closed_trades', 0))
            # Publish a complete immutable report folder, never a half-written result.
            import tempfile
            reports_root = root / 'reports'; reports_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.partial-', dir=reports_root) as staging:
                files = export_report(result, Path(staging))
                folder = Path(files['result']).parent
                write_json(folder / 'strategy.json', spec)
                if provenance: write_json(folder / 'candidate_provenance.json', provenance)
                destination = reports_root / files['result_hash']
                if destination.exists():
                    if content_hash(load_result(destination / 'result.json')) != files['result_hash'] or read_json(destination / 'strategy.json') != to_dict(spec):
                        raise ValidationError(ui_text('ui.execute_ui_operation.text_34'))
                else: folder.rename(destination)
                files = {key: str(destination / Path(value).name) if key != 'result_hash' else value for key, value in files.items()}
            reports.append(files)
        write_json(root / 'active_result.json', {'result_hash': reports[-1]['result_hash']})
        return {'reports': reports, 'metrics': to_dict(summary_metrics), 'source_type': data.manifest['source_type'], 'scope': 'research_only'}
    if operation == 'ui_campaign':
        from quantlab.research import FixtureGenerator, run_campaign, demo_campaign_config
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = payload.get('config') or demo_campaign_config(data, demo_config())
        if isinstance(config.get('backtest_config'), dict):
            config['backtest_config'] = config_from_json(config['backtest_config'])
        options = payload['provider']
        if options.get('mode') == 'chatgpt_plan':
            generator, plan_identity = plan_provider(paths, data, config, options)
            options = {'mode':'chatgpt_plan','binding':plan_identity}
        elif options.get('mode') == 'manual':
            from quantlab.manual_exchange import export_request_file, import_response, import_response_file
            if payload.get('manual_export'):
                request = export_request_file(data, config, Path(payload['manual_export']))
                return {'manual_export': payload['manual_export'], 'request': request, 'mode': 'manual_unverified'}
            if options.get('response_path'):
                generator = import_response_file(data, config, Path(options['response_path']))
            else:
                generator = import_response(data, config, options.get('response_text', ''))
            generator.preflight(data, config)
            research_controls(paths)
            options = {'mode': 'manual', 'package': generator.model}
        else:
            generator = campaign_generator(paths, options)
        name = content_hash({'dataset': data.manifest['data_hash'], 'config': config, 'provider': provider_binding_options(options)})
        return run_campaign(data, config=config, generator=generator, output_dir=root / 'campaigns' / name,
                            holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3')
    if operation == 'ui_compare':
        if not payload.get('results'): raise ValidationError(ui_text('ui.execute_ui_operation.text_35'))
        return {'rows': comparison_rows([load_result(p) for p in payload['results']])}
    if operation == 'ui_select':
        folder = Path(payload['result']).parent
        result = load_result(folder / 'result.json')
        reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
        if reference:
            spec, provenance = candidate_record(root, reference)
            if not provenance['paper_qualified']: raise ValidationError(ui_text('ui.execute_ui_operation.text_36'))
            if content_hash(spec) != result.manifest.get('spec_hash'): raise ValidationError(ui_text('ui.execute_ui_operation.text_37'))
        return save_selection(read_json(folder / 'strategy.json'), result, root / 'selection.json')
    if operation == 'ui_disable':
        selection = root / 'selection.json'
        if selection.exists():
            archive = root / 'disabled_selections'
            archive.mkdir(exist_ok=True)
            value = read_json(selection)
            write_json(archive / (content_hash(value) + '.json'), value)
            selection.unlink()
        if (root / 'paper_policy.json').exists():
            _paper(root).set_kill_switch(True)
        return {'selection': 'disabled', 'scope': 'research_and_paper_only'}
    if operation.startswith('ui_paper_'):
        # Explicit policy is required; never infer an official calendar from prices.
        if 'policy' in payload:
            policy = payload['policy']
            existing = root / 'paper_policy.json'
            if existing.exists() and read_json(existing) != policy:
                raise ValidationError(ui_text('ui.execute_ui_operation.text_38'))
            if not existing.exists():
                from quantlab.paper import PaperBroker
                if not isinstance(policy, dict) or set(policy) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
                    raise ValidationError(ui_text('ui.execute_ui_operation.text_39'))
                # Validate in a disposable journal first: invalid policy cannot poison startup.
                import tempfile
                with tempfile.TemporaryDirectory(prefix='policy-', dir=root) as staging:
                    PaperBroker(Path(staging) / 'validation.sqlite3', instrument=Instrument(policy['contract_id']),
                                costs=demo_config().costs, limits=paper_risk_limits(),
                                risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))
                write_json(existing, policy)
        broker = _paper(root)
        replay_state = None
        if operation == 'ui_paper_reconcile':
            broker.reconcile(payload['snapshot'])
        elif operation == 'ui_paper_kill':
            broker.set_kill_switch(True)
        elif operation == 'ui_paper_submit':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError(ui_text('ui.execute_ui_operation.text_40'))
            broker.reconcile(payload['snapshot'])
            selection = load_selection(root / 'selection.json')
            if payload['intent'].get('strategy_hash') != selection['strategy_hash']:
                raise ValidationError(ui_text('ui.execute_ui_operation.text_41'))
            broker.set_kill_switch(False)
            broker.submit(payload['intent'], quote=payload['quote'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_cancel':
            broker.cancel(payload['order_id'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_replay':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError(ui_text('ui.execute_ui_operation.text_42'))
            broker.reconcile(payload['snapshot'])
            from quantlab.paper_replay import PaperReplay
            data = _dataset(root, payload)
            selection = load_selection(root / 'selection.json')
            binding = content_hash([data.manifest['data_hash'], selection['strategy_hash']])
            paths.require_replay_wal()
            replay = PaperReplay(root / 'replays' / (binding + '.sqlite3'), dataset=data,
                                 strategy=StrategySpec(**selection['strategy']), broker=broker,
                                 margin_schedule=broker._margin_schedule, storage_profile="wal_full")
            replay.start()
            cursor_before = replay.snapshot()['cursor']
            fills_before = len(broker.snapshot()['fills'])
            try:
                replay.step(max_bars=payload.get('max_bars', 100))
            finally:
                replay.stop()
            replay_state = replay.snapshot()
            replay_state['processed_bars'] = replay_state['cursor'] - cursor_before
            replay_state['new_fills'] = len(broker.snapshot()['fills']) - fills_before
        state = broker.snapshot()
        journal = broker.journal_events()
        write_json(root / 'paper_snapshot.json', state)
        write_json(root / 'paper_journal_export.json', journal)
        if replay_state is not None:
            return {'replay': replay_state, 'account': state}
        return {'account': state, 'journal_tail': journal[-20:], 'journal_file': str(root / 'paper_journal_export.json')}
    raise ValidationError(ui_text('ui.execute_ui_operation.text_43'))



def latest_market_observations(series):
    """Choose observed contract history, never infer a live or executable quote.

    Date/session ordering is explicit. Same-session sources without event times
    are not time-comparable: retain the first source (official daily cache).
    """
    chosen = {}
    session_order = {'night': 0, 'day': 1, 'combined': 2}
    for item in series:
        key = item.instrument.contract_id
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = item
            continue
        latest, old = item.bars[-1], previous.bars[-1]
        rank = (latest.trade_date, session_order[latest.session])
        old_rank = (old.trade_date, session_order[old.session])
        if rank > old_rank or (rank == old_rank and latest.end is not None and old.end is not None and latest.end > old.end):
            chosen[key] = item
    return tuple(chosen.values())


def dataset_market_series(dataset, calendar_payload):
    """Adapt only validated one-minute official history with hash-bound calendar."""
    from quantlab.data import validate_dataset, SessionCalendar
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance, bar_key
    validate_dataset(dataset)
    manifest = dataset.manifest
    if manifest['source_type'] != 'official_local' or manifest.get('bar_granularity') != 'minute' or manifest.get('timeframe_minutes', 1) != 1:
        raise ValidationError(ui_text('ui.dataset_market_series.text_1'))
    calendar = SessionCalendar(calendar_payload['sessions'], version=calendar_payload['version'])
    if calendar.hash != manifest.get('calendar_hash'): raise ValidationError(ui_text('ui.dataset_market_series.text_2'))
    grouped = {}
    for bar in dataset.bars:
        instrument = InstrumentRef('TAIFEX', 'TMF', bar.contract_id, bar.contract_id.split(':')[-1])
        session = calendar.lookup(bar.timestamp, bar.contract_id)
        value = MarketBar(instrument, bar.trade_date, bar.session, bar.open, bar.high, bar.low, bar.close, bar.volume,
            interval='1m', timestamp=bar.timestamp, end=bar.end, session_open=session['open'], session_end=session['end'], source_id=bar.source_id)
        grouped.setdefault(instrument, []).append(value)
    result = []
    for instrument, bars in grouped.items():
        bars.sort(key=bar_key); dates = [b.trade_date for b in bars]
        provenance = SourceProvenance(manifest['source_url'], manifest['source_hash'],
            ui_text('ui.dataset_market_series.text_3').format(manifest['data_hash']),
            'https://www.taifex.com.tw', datetime.fromisoformat(manifest['imported_at'].replace('Z', '+00:00')),
            max(dates), min(dates), max(dates), mode='history', timestamp_basis='hash-bound explicit session calendar; one-minute source',
            warnings=tuple(str(x) for x in dataset.quality.get('warnings', ())))
        result.append(MarketSeries(instrument, tuple(bars), provenance))
    return tuple(result)

from PySide6.QtCore import Qt, QTimer, QPointF, QUrl, QPropertyAnimation
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF, QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QStackedWidget, QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QFormLayout, QScrollArea,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QApplication, QGroupBox,
    QGraphicsOpacityEffect)


class EquityPlot(QWidget):
    """Small native paint widget; no browser or extra plotting dependency."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(180)
        self.setAccessibleName(ui_text('ui.__init__.text_1'))

    def set_values(self, rows):
        self.values = [float(row['equity']) for row in rows]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#172230'))
        painter.setPen(QColor('#dbe4ef'))
        if not self.values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, ui_text('ui.paintEvent.text_1'))
            return
        lo, hi = min(self.values), max(self.values)
        painter.drawText(8, 18, ui_text('ui.paintEvent.text_2').format(lo, hi))
        points = QPolygonF([QPointF(16 + i * (self.width()-32) / max(1, len(self.values)-1),
                       self.height()-20-(v-lo) * (self.height()-55) / max(1, hi-lo)) for i, v in enumerate(self.values)])
        painter.setPen(QPen(QColor('#2563eb'), 2))
        painter.drawPolyline(points)


from desktop_presentation import display_number, display_status, result_name
from desktop_market import MarketDashboard, MarketHistoryDialog
from desktop_forms import (StrategyForm, BacktestForm, CampaignForm, WalkForwardForm, PaperPolicyForm,
    PaperIntentForm, PaperQuoteForm, PaperSnapshotForm, ResultTable, SummaryCard, BacktestSummaryCard, BacktestFillsTable, CandidateSummaryCard)


class MainWindow(QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None):
        super().__init__()
        from desktop_icon import application_icon
        self.setWindowIcon(application_icon(QApplication.instance()))
        self.paths, self.jobs, self.settings, self.backups, self.guard = paths, jobs, settings, backups, guard
        self.root = _root(paths)
        self.actions = []
        self.last_operation = None
        self._ui_job_id = None
        self._wf_preview = None
        self._wf_request_key = None
        self._wf_launch = None
        self._wf_pending_reconcile = False
        self._wf_source_stamp = None
        self.active_candidate = None
        self._advanced_values = {}
        self._section_toggles = {}
        self._market_outcomes = {}
        self._campaign_data_hash = None
        self._chatgpt_job_request = None
        self._chatgpt_job_id = None
        self._plan_usage_binding = None
        self._subscription_campaign = False
        self._plan_launch = None
        self._pending_plan_reconcile = False
        self._pending_usage_refresh = False
        self._pending_chatgpt_restore = False
        self._analysis_preview = None
        self._analysis_request_key = None
        self._analysis_launch = None
        self._analysis_running = False
        self._pending_analysis_reconcile = False
        self.setWindowTitle(ui_text('ui.__init__.text_2'))
        self.resize(1366, 768)
        apply_theme()
        body = QWidget(); outer = QVBoxLayout(body)
        banner = QCheckBox(ui_text('ui.__init__.text_3'))
        banner.setObjectName('research_mode_status')
        outer.addWidget(banner)
        explanation = QLabel(ui_text('ui.__init__.text_4'))
        explanation.setObjectName('research_mode_explanation'); explanation.setWordWrap(True)
        outer.addWidget(explanation); explanation.hide(); banner.toggled.connect(explanation.setVisible)
        horizontal = QHBoxLayout(); outer.addLayout(horizontal, 1)
        self.navigation = QListWidget(); self.navigation.setObjectName('navigation'); self.navigation.setMaximumWidth(180)
        self.stack = QStackedWidget(); horizontal.addWidget(self.navigation); horizontal.addWidget(self.stack, 1)
        self.status = QLabel(ui_text('ui.__init__.text_5')); self.status.setObjectName('status'); self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.notification = QLabel(''); self.notification.setObjectName('local_notification'); self.notification.setWordWrap(True); self.notification.hide(); outer.addWidget(self.notification)
        self.notification.setTextFormat(Qt.TextFormat.RichText)
        self.notification.linkActivated.connect(self._notification_link)
        self.notification_timer = QTimer(self); self.notification_timer.setSingleShot(True)
        self.notification_opacity = QGraphicsOpacityEffect(self.notification)
        self.notification.setGraphicsEffect(self.notification_opacity)
        self.notification_fade = QPropertyAnimation(self.notification_opacity, b'opacity', self)
        self.notification_fade.setDuration(300); self.notification_fade.setStartValue(1.0); self.notification_fade.setEndValue(0.0)
        self.notification_fade.finished.connect(self.notification.hide)
        self.notification_timer.timeout.connect(self.notification_fade.start)
        progress = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.cancel_button = QPushButton(ui_text('ui.__init__.text_6')); self.cancel_button.setObjectName('cancel_job')
        self.cancel_button.clicked.connect(self.cancel_job); self.cancel_button.setEnabled(False)
        progress.addWidget(self.progress); progress.addWidget(self.cancel_button); outer.addLayout(progress)
        self.setCentralWidget(body)
        self._dashboard(); self._data_page(); self._strategy_page(); self._backtest_page(); self._compare_page(); self._paper_page(); self._settings_page()
        self.chatgpt_panel.model.currentIndexChanged.connect(self._invalidate_analysis_preview)
        self.chatgpt_panel.timeout.valueChanged.connect(self._invalidate_analysis_preview)
        self.chatgpt_panel.account.currentIndexChanged.connect(self._invalidate_analysis_preview)
        self._connect_walk_forward_inputs()
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.itemSelectionChanged.connect(self._navigate_selected_page)
        self.navigation.setCurrentRow(0)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_jobs); self.timer.start(150)
        self._safe(self.refresh_views)
        self._safe(self.load_settings)
        self._busy(False)
        from desktop_ui_polish import install_polish
        install_polish(self)

    def _navigate_selected_page(self):
        # Accessibility selection may not update QListWidget's current item.
        selected = self.navigation.selectedItems()
        if len(selected) == 1:
            self.navigation.setCurrentRow(self.navigation.row(selected[0]))

    def _page(self, label):
        self.navigation.addItem(label)
        page = QWidget(); layout = QVBoxLayout(page)
        title = QLabel(label); title.setProperty('themePart', 'pageTitle'); layout.addWidget(title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page); self.stack.addWidget(scroll)
        return layout

    def _button(self, layout, text, name, callback, role='secondary'):
        button = QPushButton(text); button.setObjectName(name); button.clicked.connect(lambda checked=False: self._safe(lambda: self._confirm_button(button, callback)))
        if role not in ('primary', 'secondary', 'danger'):
            raise ValueError('Unknown button role')
        button.setProperty('role', role)
        row = QHBoxLayout(); row.addWidget(button); row.addStretch()
        layout.addRow(row) if isinstance(layout, QFormLayout) else layout.addLayout(row)
        self.actions.append(button)
        return button

    def _confirm_button(self, button, callback):
        if button.property('role') == 'danger':
            answer = QMessageBox.question(self, ui_text('ui._confirm_button.text_1'), ui_text('ui._confirm_button.text_2').format(button.text()),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        return callback()

    def _text(self, layout, label, value='', multiline=False):
        layout.addWidget(QLabel(label))
        field = QPlainTextEdit(value) if multiline else QLineEdit(value)
        if multiline: field.setMaximumHeight(150)
        layout.addWidget(field)
        return field

    def _advanced(self, layout, title=ui_text('ui.advanced.default_title')):
        title = title if title.startswith(ui_text('ui._advanced.text_1')) else ui_text('ui._advanced.text_2').format(title)
        key = str(self.stack.count()) + ':' + title
        toggle = QCheckBox(title); toggle.setObjectName('advanced_' + str(len(self._section_toggles)))
        self._section_toggles[key] = toggle
        layout.addWidget(toggle)
        box = QWidget(); inner = QVBoxLayout(box); inner.setContentsMargins(0,0,0,0)
        layout.addWidget(box); box.hide(); toggle.toggled.connect(box.setVisible)
        toggle.toggled.connect(lambda checked: self._safe(self._save_section_preferences))
        return inner

    def _save_section_preferences(self):
        if self.settings is None or getattr(self, '_restoring_sections', False): return
        value = self.settings.load()
        value['advanced_sections'] = {key: toggle.isChecked() for key, toggle in self._section_toggles.items()}
        self.settings.save(value)

    def _payload(self, editor, build):
        text = editor.toPlainText()
        if text != self._advanced_values.get(editor, text):
            return json.loads(text)
        return build()

    def _remember(self, editor):
        self._advanced_values[editor] = editor.toPlainText()

    def _dashboard(self):
        self.navigation.addItem(ui_text('ui._dashboard.text_1'))
        self.market = MarketDashboard(); self.stack.addWidget(self.market)
        self._section_toggles['market:diagnostics'] = self.market.diagnostics_button
        self.market.diagnostics_button.toggled.connect(lambda checked: self._safe(self._save_section_preferences))
        self.market.refresh_requested.connect(lambda: self._safe(self.refresh_market))
        self.market.preferences_changed.connect(lambda: self._safe(self.save_market_preferences))
        self.market.series_rendered.connect(lambda _: self._safe(self.bind_result_layers))
        # Compatibility diagnostics remain available on the data page, not the landing page.
        self.overview = QLabel(); self.data_card = QLabel()
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True)

    def refresh_market(self):
        if self.jobs.active: raise ValidationError(ui_text('ui.refresh_market.text_1'))
        answer = QMessageBox.question(self, ui_text('ui.refresh_market.text_2'),
            ui_text('ui.refresh_market.text_3'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.start_job('ui_market_refresh', {'network_opt_in': True})

    def import_market_file(self):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('ui.import_market_file.text_1'), '', 'JSON / CSV (*.json *.csv)')
        if name:
            provider, format_name = self.market_provider.currentData()
            self.start_job('ui_market_refresh', {'provider': provider, 'format': format_name, 'local_path': name})

    def import_market_history(self):
        if self.jobs.active: raise ValidationError(ui_text('ui.import_market_history.text_1'))
        if getattr(self, '_closing', False):
            raise ValidationError(ui_text('ui.import_market_history.text_2'))
        existing = getattr(self, '_history_dialog', None)
        if existing is not None:
            existing.raise_(); existing.activateWindow(); return
        dialog = MarketHistoryDialog(self)
        self._history_dialog = dialog
        def accepted():
            if not getattr(self, '_closing', False):
                self._safe(lambda: self.start_job('ui_market_refresh', dialog.payload()))
        def finished(_):
            if self._history_dialog is dialog: self._history_dialog = None
            dialog.deleteLater()
        dialog.accepted.connect(accepted)
        dialog.finished.connect(finished)
        dialog.open()

    def save_market_preferences(self):
        if self.settings is None: return
        value = self.settings.load()
        value['market'] = self.market.preferences()
        geometry = self.geometry()
        value['window'] = {'x': self.x(), 'y': self.y(), 'width': geometry.width(), 'height': geometry.height()}
        self.settings.save(value)

    def _data_page(self):
        layout = self._page(ui_text('ui._data_page.text_1'))
        layout.addWidget(self.overview)
        self.market_provider = QComboBox(); self.market_provider.addItem(ui_text('ui._data_page.text_2'), ('twse', 'json')); self.market_provider.addItem(ui_text('ui._data_page.text_3'), ('taifex', 'json')); self.market_provider.addItem(ui_text('ui._data_page.text_4'), ('taifex', 'csv')); layout.addWidget(self.market_provider)
        self._button(layout, ui_text('ui._data_page.text_5'), 'import_market_file', self.import_market_file)
        self._button(layout, ui_text('ui._data_page.text_6'), 'import_market_history', self.import_market_history)
        self.import_path = self._text(layout, ui_text('ui._data_page.text_7'))
        self._button(layout, ui_text('ui._data_page.text_8'), 'browse_data', lambda: self._browse(self.import_path))
        self.calendar_path = self._text(layout, ui_text('ui._data_page.text_9'))
        self._button(layout, ui_text('ui._data_page.text_10'), 'browse_calendar', lambda: self._browse(self.calendar_path))
        self.import_kind = QComboBox(); self.import_kind.addItems(['validated_dataset', 'ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json', 'synthetic_bars', 'synthetic_ticks', 'proxy_bars', 'proxy_ticks']); layout.addWidget(self.import_kind)
        self.contract = self._text(layout, ui_text('ui._data_page.text_11'), 'TAIFEX:TMF:202601')
        self._button(layout, ui_text('ui._data_page.text_12'), 'import_data', self.import_data, role='primary')
        self.bars = QSpinBox(); self.bars.setRange(120, 10000); self.bars.setValue(960); layout.addWidget(self.bars)
        self._button(layout, ui_text('ui._data_page.text_13'), 'create_demo', lambda: self.start_job('ui_demo', {'bars': self.bars.value()}))
        self.network_data = QCheckBox(ui_text('ui._data_page.text_14')); layout.addWidget(self.network_data)
        self.days = QSpinBox(); self.days.setRange(1, 30); layout.addWidget(self.days)
        self._button(layout, ui_text('ui._data_page.text_15'), 'refresh_data', self.download_data)
        details = self._advanced(layout)
        self.data_detail = QPlainTextEdit(); self.data_detail.setReadOnly(True); details.addWidget(self.data_detail); details.addWidget(self.summary)

    def _strategy_page(self):
        from quantlab.strategies import builtin_strategies
        layout = self._page(ui_text('ui._strategy_page.text_1'))
        self.chatgpt_sign_in_entry = self._button(layout, ui_text('ui._strategy_page.text_2'), 'chatgpt_sign_in_entry', self.show_chatgpt_sign_in)
        layout.addWidget(QLabel(ui_text('ui._strategy_page.text_3')))
        self.strategy_form = StrategyForm(); layout.addWidget(self.strategy_form)
        advanced = self._advanced(layout)
        self.family = QComboBox(); self.family.addItems([s.family for s in builtin_strategies()]); advanced.addWidget(self.family)
        self.parameters = self._text(advanced, ui_text('ui._strategy_page.text_4'), '{}', True)
        self.strategy_detail = QPlainTextEdit(); self.strategy_detail.setReadOnly(True); advanced.addWidget(self.strategy_detail)
        self.family.currentIndexChanged.connect(self._family_changed); self._family_changed()
        self._walk_forward_section(self._advanced(layout, ui_text('ui._strategy_page.text_5')))
        layout.addWidget(QLabel(ui_text('ui._strategy_page.text_6')))
        self.strategy_form.family.currentIndexChanged.connect(lambda: self.family.setCurrentIndex(self.strategy_form.family.currentIndex()))
        research_parameters = self._advanced(layout, ui_text('ui._strategy_page.text_7'))
        self.campaign_form = CampaignForm(); research_parameters.addWidget(self.campaign_form)
        self.campaign_config = self._text(advanced, ui_text('ui._strategy_page.text_8'), '', True)
        self._remember(self.campaign_config)
        self.provider_mode = QComboBox(); self.provider_mode.addItem(ui_text('ui._strategy_page.text_9'), 'chatgpt_plan'); self.provider_mode.addItem(ui_text('ui._strategy_page.text_10'), 'fixture'); self.provider_mode.addItem(ui_text('ui._strategy_page.text_11'), 'manual'); layout.addWidget(self.provider_mode)
        manual = QWidget(); manual_layout = QVBoxLayout(manual); layout.addWidget(manual); manual.hide()
        self.provider_mode.currentIndexChanged.connect(lambda: manual.setVisible(self.provider_mode.currentData() == 'manual'))
        self.manual_path = self._text(manual_layout, ui_text('ui._strategy_page.text_12'))
        self._button(manual_layout, ui_text('ui._strategy_page.text_13'), 'browse_manual_response', lambda: self._browse(self.manual_path))
        self.manual_response = self._text(manual_layout, ui_text('ui._strategy_page.text_14'), '', True)
        self._button(manual_layout, ui_text('ui._strategy_page.text_15'), 'export_manual_request', self.export_manual_request)
        self._button(layout, ui_text('ui._strategy_page.text_16'), 'chatgpt_campaign_usage', self.inspect_plan_usage)
        self._button(layout, ui_text('ui._strategy_page.text_17'), 'run_campaign', self.run_campaign, role='primary')
        self.candidate_choice = QComboBox(); self.candidate_choice.setObjectName('candidate_choice'); self.candidate_choice.currentIndexChanged.connect(self.inspect_candidate); layout.addWidget(self.candidate_choice)
        self.candidate_detail = QPlainTextEdit(); self.candidate_detail.setReadOnly(True); advanced.addWidget(self.candidate_detail)
        evidence = self._advanced(layout, ui_text('ui._strategy_page.text_18'))
        self.candidate_card = CandidateSummaryCard(); evidence.addWidget(self.candidate_card)
        self.use_candidate_button = self._button(layout, ui_text('ui._strategy_page.text_19'), 'use_candidate', self.use_candidate)
        self._button(layout, ui_text('ui._strategy_page.text_20'), 'use_builtin', self.use_builtin)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); advanced.addWidget(self.history)
        self.history_table = ResultTable(); evidence.addWidget(self.history_table)
        evidence.addWidget(QLabel(ui_text('ui._strategy_page.text_21')))
        self.evaluation_table = ResultTable(); evidence.addWidget(self.evaluation_table)

    def _walk_forward_section(self, layout):
        section = QGroupBox(ui_text('ui._walk_forward_section.text_1'))
        content = QVBoxLayout(section); layout.addWidget(section)
        self.walk_forward_form = WalkForwardForm(); content.addWidget(self.walk_forward_form)
        self.walk_forward_saved_controls = QWidget(); saved = QFormLayout(self.walk_forward_saved_controls)
        self.walk_forward_campaign = QComboBox(); self.walk_forward_campaign.setObjectName('walk_forward_campaign')
        self.walk_forward_campaign.addItem(ui_text('ui._walk_forward_section.text_2'), None)
        saved.addRow(ui_text('ui._walk_forward_section.text_3'), self.walk_forward_campaign)
        self.walk_forward_original = QLineEdit(); self.walk_forward_original.setReadOnly(True)
        self.walk_forward_original.setObjectName('walk_forward_original_dataset')
        self.walk_forward_original.setPlaceholderText(ui_text('ui._walk_forward_section.text_4'))
        saved.addRow(ui_text('ui._walk_forward_section.text_5'), self.walk_forward_original)
        self._button(saved, ui_text('ui._walk_forward_section.text_6'), 'pick_walk_forward_original', self.pick_walk_forward_original)
        notice = QLabel(ui_text('ui._walk_forward_section.text_7'))
        notice.setWordWrap(True); saved.addRow(notice); content.addWidget(self.walk_forward_saved_controls)
        self.walk_forward_saved_controls.setEnabled(False)
        self._button(content, ui_text('ui._walk_forward_section.text_8'), 'preview_walk_forward', self.preview_walk_forward)
        self.walk_forward_preview = QPlainTextEdit(); self.walk_forward_preview.setReadOnly(True)
        self.walk_forward_preview.setObjectName('walk_forward_preview'); self.walk_forward_preview.setMinimumHeight(410)
        content.addWidget(self.walk_forward_preview)
        self.walk_forward_advanced_group = QGroupBox(ui_text('ui._walk_forward_section.text_9'))
        self.walk_forward_advanced_group.setCheckable(True); self.walk_forward_advanced_group.setChecked(False)
        self._section_toggles['strategy:walk_forward_evidence'] = self.walk_forward_advanced_group
        self.walk_forward_advanced_group.toggled.connect(lambda checked: self._safe(self._save_section_preferences))
        advanced = QVBoxLayout(self.walk_forward_advanced_group)
        self.walk_forward_advanced = QPlainTextEdit(); self.walk_forward_advanced.setReadOnly(True)
        self.walk_forward_advanced.setObjectName('walk_forward_advanced'); self.walk_forward_advanced.hide()
        advanced.addWidget(self.walk_forward_advanced)
        self.walk_forward_advanced_group.toggled.connect(self.walk_forward_advanced.setVisible)
        content.addWidget(self.walk_forward_advanced_group)
        self.walk_forward_consent = QCheckBox(ui_text('ui._walk_forward_section.text_10'))
        self.walk_forward_consent.setObjectName('walk_forward_consent'); content.addWidget(self.walk_forward_consent)
        self.walk_forward_start = self._button(content, ui_text('ui._walk_forward_section.text_11'), 'run_walk_forward', self.run_walk_forward)
        self.walk_forward_choice = QComboBox(); self.walk_forward_choice.setObjectName('walk_forward_choice'); content.addWidget(self.walk_forward_choice)
        self._button(content, ui_text('ui._walk_forward_section.text_12'), 'read_walk_forward', self.read_walk_forward)
        self.walk_forward_status = QLabel(ui_text('ui._walk_forward_section.text_13'))
        self.walk_forward_status.setWordWrap(True); content.addWidget(self.walk_forward_status)
        self.walk_forward_results = ResultTable(); content.addWidget(self.walk_forward_results)

    def _connect_walk_forward_inputs(self):
        for form in (self.walk_forward_form, self.backtest_form):
            for field in form.fields.values():
                signal = field.currentIndexChanged if isinstance(field, QComboBox) else field.textChanged
                signal.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_form.fields['pool_origin'].currentIndexChanged.connect(self._walk_forward_origin_changed)
        self.walk_forward_campaign.currentIndexChanged.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_original.textChanged.connect(self._invalidate_walk_forward_preview)
        self.backtest_form.expiries.table.itemChanged.connect(self._invalidate_walk_forward_preview)
        model = self.backtest_form.expiries.table.model()
        model.rowsInserted.connect(self._invalidate_walk_forward_preview)
        model.rowsRemoved.connect(self._invalidate_walk_forward_preview)
        self.config.textChanged.connect(self._invalidate_walk_forward_preview)

    def _walk_forward_origin_changed(self, *args):
        saved = self.walk_forward_form.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        self.walk_forward_saved_controls.setEnabled(saved)
        self._invalidate_walk_forward_preview()

    def pick_walk_forward_original(self):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('ui.pick_walk_forward_original.text_1'), '', ui_text('ui.pick_walk_forward_original.text_2'))
        if not name: return
        if '://' in name or name.startswith(('//', '\\\\')) or not Path(name).is_absolute():
            raise ValidationError(ui_text('ui.pick_walk_forward_original.text_3'))
        path = Path(name).resolve(strict=True)
        if not path.is_file(): raise ValidationError(ui_text('ui.pick_walk_forward_original.text_4'))
        self.walk_forward_original.setText(str(path))
        self.form_feedback(self.walk_forward_original, ui_text('ui.pick_walk_forward_original.text_5'))

    def _walk_forward_saved_source(self):
        if self.walk_forward_form.fields['pool_origin'].currentData() != 'saved_campaign_pool': return None
        reference = self.walk_forward_campaign.currentData()
        if not reference: raise ValidationError(ui_text('ui._walk_forward_saved_source.text_1'))
        path = self.walk_forward_original.text()
        if not path: raise ValidationError(ui_text('ui._walk_forward_saved_source.text_2'))
        return {'campaign_reference': reference, 'original_dataset': {'kind': 'local_dataset_file', 'path': path}}

    def _invalidate_walk_forward_preview(self, *args):
        self._wf_preview = None
        self.walk_forward_consent.setChecked(False)
        self.walk_forward_start.setEnabled(False)
        self.walk_forward_preview.setPlainText(ui_text('ui._invalidate_walk_forward_preview.text_1'))
        self.walk_forward_status.setText(ui_text('ui._invalidate_walk_forward_preview.text_2'))
        self.walk_forward_advanced.clear()

    def _walk_forward_input_key(self):
        path = self.root / 'dataset.json'
        stat = path.stat()
        typed = self.backtest_form.build_payload()
        config = self._payload(self.config, lambda: typed['config'])
        plan = self.walk_forward_form.build_payload(config)
        # Worker checks full data/manifest and engine hashes again before running;
        # this cheap UI key only discards stale asynchronous preview responses.
        source = self._walk_forward_saved_source()
        inputs = {'plan': plan, 'source': [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]}
        if source is not None:
            from quantlab.desktop_runtime import validate_walk_forward_request
            validate_walk_forward_request(plan, source)
            from desktop_walk_forward import source_campaign_folder
            folder = source_campaign_folder(self.paths, source['campaign_reference'])
            files = (folder / 'campaign.json', folder / 'campaign.sqlite3', Path(source['original_dataset']['path']))
            inputs['saved_source'] = source
            inputs['saved_files'] = [[p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns] for p in files]
        return content_hash(inputs), plan

    def preview_walk_forward(self):
        self._invalidate_walk_forward_preview()
        self.walk_forward_results.set_rows([])
        key, plan = self._walk_forward_input_key()
        payload = {'plan': plan}
        source = self._walk_forward_saved_source()
        if source is not None: payload['saved_source'] = source
        self.start_job('ui_walk_forward_preview', payload)
        self._wf_request_key = key
        self.walk_forward_preview.setPlainText(ui_text('ui.preview_walk_forward.text_1'))
        self.walk_forward_status.setText(ui_text('ui.preview_walk_forward.text_2'))

    def run_walk_forward(self):
        if self._wf_preview is None or not self.walk_forward_consent.isChecked():
            raise ValidationError(ui_text('ui.run_walk_forward.text_1'))
        key, plan = self._walk_forward_input_key()
        if key != self._wf_request_key:
            self._invalidate_walk_forward_preview()
            raise ValidationError(ui_text('ui.run_walk_forward.text_2'))
        identity = self._wf_preview['preview_identity']
        if (self.root / 'walk_forward' / identity / 'walk_forward.sqlite3').exists():
            self.start_job('ui_walk_forward_read', {'reference': identity})
            self.walk_forward_consent.setChecked(False)
            return
        payload = {'plan': plan, 'preview_identity': identity}
        source = self._walk_forward_saved_source()
        if source is not None: payload['saved_source'] = source
        job = self.start_job('ui_walk_forward_run', payload)
        self._wf_launch = {'reference': identity, 'stopped_job_id': job}
        self.walk_forward_consent.setChecked(False)

    def read_walk_forward(self):
        reference = self.walk_forward_choice.currentData()
        if not reference: raise ValidationError(ui_text('ui.read_walk_forward.text_1'))
        self.start_job('ui_walk_forward_read', {'reference': reference})

    def _refresh_walk_forward_references(self):
        previous = self.walk_forward_choice.currentData()
        self.walk_forward_choice.clear()
        for path in sorted((self.root / 'walk_forward').glob('*/walk_forward.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_choice.addItem(ui_text('ui._refresh_walk_forward_references.text_1').format(name[:12]), name)
        index = self.walk_forward_choice.findData(previous)
        if index >= 0: self.walk_forward_choice.setCurrentIndex(index)
        selected = self.walk_forward_campaign.currentData()
        self.walk_forward_campaign.blockSignals(True)
        self.walk_forward_campaign.clear(); self.walk_forward_campaign.addItem(ui_text('ui._refresh_walk_forward_references.text_2'), None)
        for path in sorted((self.root / 'campaigns').glob('*/campaign.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_campaign.addItem(ui_text('ui._refresh_walk_forward_references.text_3').format(name[:12]), name)
        index = self.walk_forward_campaign.findData(selected)
        self.walk_forward_campaign.setCurrentIndex(max(0, index))
        self.walk_forward_campaign.blockSignals(False)
        if selected != self.walk_forward_campaign.currentData(): self._invalidate_walk_forward_preview()

    def _walk_forward_event(self, event):
        operation = self.last_operation or ''
        if not operation.startswith('ui_walk_forward_'): return False
        kind = event.get('type')
        if kind == 'progress':
            self.status.setText(ui_text('ui._walk_forward_event.text_1'))
            return True
        if kind not in ('result', 'error', 'cancelled'): return True
        self.record_event(operation, kind)
        if kind == 'result':
            result = event['result']
            if operation == 'ui_walk_forward_preview':
                try: current = self._walk_forward_input_key()[0]
                except (ValueError, OSError): current = None
                if current != self._wf_request_key:
                    self._invalidate_walk_forward_preview()
                    self.status.setText(ui_text('ui._walk_forward_event.text_2'))
                    return True
                from desktop_walk_forward import preview_text
                self.walk_forward_preview.setPlainText(preview_text(result))
                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                if result.get('admission_status') == 'rejected':
                    self._wf_preview = None
                    self.walk_forward_consent.setChecked(False)
                    self.walk_forward_start.setEnabled(False)
                    self.walk_forward_status.setText(ui_text('ui._walk_forward_event.text_3'))
                    self.status.setText(ui_text('ui._walk_forward_event.text_4'))
                    return True
                self._wf_preview = result
                self.walk_forward_status.setText(ui_text('ui._walk_forward_event.text_5'))
                self.status.setText(ui_text('ui._walk_forward_event.text_6'))
            else:
                from desktop_walk_forward import result_rows, status_label, preview_text
                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                summary = result.get('summary', {})
                self.walk_forward_results.set_rows(result_rows(result))
                self.walk_forward_status.setText(
                    ui_text('ui._walk_forward_event.text_10').format(status_label(result.get('display_status', result['status'])), status_label(summary.get('evidence_mode')), status_label(summary.get('exposure_status')), ui_text('ui._walk_forward_event.text_8').format(summary.get('evaluations_reserved', 0), summary.get('evaluation_limit', ui_text('ui._walk_forward_event.text_7')), summary.get('evaluated_oos_folds', 0)), ui_text('ui._walk_forward_event.text_9').format(status_label(result['pool_admission']['real_model_status'])) if result.get('pool_admission') else '', str(result.get('reference', ''))[:12]))
                self.status.setText(ui_text('ui._walk_forward_event.text_11'))
                self._refresh_walk_forward_references()
                if operation in ('ui_walk_forward_run', 'ui_walk_forward_reconcile'):
                    self._wf_launch = None
        else:
            if operation == 'ui_walk_forward_preview':
                self.walk_forward_status.setText(ui_text('ui._walk_forward_event.text_12'))
            self.status.setText(error_message('operation_failed'))
            if operation == 'ui_walk_forward_run': self._wf_pending_reconcile = self._wf_launch is not None
        return True

    def _backtest_page(self):
        layout = self._page(ui_text('ui._backtest_page.text_1'))
        layout.addWidget(QLabel(ui_text('ui._backtest_page.text_2')))
        parameters = self._advanced(layout, ui_text('ui._backtest_page.text_3'))
        self.backtest_form = BacktestForm(); parameters.addWidget(self.backtest_form)
        self.start_date = self.backtest_form.fields['start_date']; self.end_date = self.backtest_form.fields['end_date']
        advanced = self._advanced(layout)
        self.config = self._text(advanced, ui_text('ui._backtest_page.text_4'), canonical_json(demo_config()), True)
        self._remember(self.config)
        self.batch = QCheckBox(ui_text('ui._backtest_page.text_5')); layout.addWidget(self.batch)
        self.run_button = self._button(layout, ui_text('ui._backtest_page.text_6'), 'run_backtest', self.run_backtest, role='primary')
        self.result_choice = QComboBox(); self.result_choice.currentIndexChanged.connect(self.show_result); layout.addWidget(self.result_choice)
        self.plot = EquityPlot(); layout.addWidget(self.plot)
        self.result_detail = QPlainTextEdit(); self.result_detail.setReadOnly(True); advanced.addWidget(self.result_detail)
        self.result_card = BacktestSummaryCard(); layout.addWidget(self.result_card)
        self.fills_table = BacktestFillsTable(); layout.addWidget(self.fills_table)
        for kind, caption in (('signal', ui_text('ui._backtest_page.text_7')), ('fill', ui_text('ui._backtest_page.text_8'))):
            toggle = QCheckBox(caption); toggle.setChecked(True); layout.addWidget(toggle)
            toggle.toggled.connect(lambda value, layer=kind: self.market.chart.set_layer_visible(layer, value))

    def _compare_page(self):
        layout = self._page(ui_text('ui._compare_page.text_1'))
        layout.addWidget(QLabel(ui_text('ui._compare_page.text_2')))
        self.comparison_list = QListWidget(); self.comparison_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection); layout.addWidget(self.comparison_list)
        self._button(layout, ui_text('ui._compare_page.text_3'), 'compare_results', lambda: self.start_job('ui_compare', {'results': [i.data(Qt.ItemDataRole.UserRole) for i in self.comparison_list.selectedItems()]}), role='primary')
        self.comparison = QPlainTextEdit(); self.comparison.setReadOnly(True); self._advanced(layout).addWidget(self.comparison)
        self.comparison_table = ResultTable(); layout.addWidget(self.comparison_table)
        self.select_button = self._button(layout, ui_text('ui._compare_page.text_4'), 'select_strategy', self.select_strategy)
        self._button(layout, ui_text('ui._compare_page.text_5'), 'disable_strategy', lambda: self.start_job('ui_disable', {}))
        self.selection_status = QLabel(); self.selection_status.setWordWrap(True); layout.addWidget(self.selection_status)
        self._analysis_section(layout)

    def _analysis_section(self, layout):
        title=QLabel(ui_text('ui._analysis_section.text_1'));layout.addWidget(title)
        warning=QLabel(ANALYSIS_WARNING+'\n'+ANALYSIS_NOTICE);warning.setWordWrap(True);layout.addWidget(warning)
        self.analysis_candidates=QListWidget();self.analysis_candidates.setObjectName('analysis_candidates')
        self.analysis_candidates.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);layout.addWidget(self.analysis_candidates)
        self.analysis_original=QLineEdit();self.analysis_original.setReadOnly(True);self.analysis_original.setObjectName('analysis_original_dataset')
        self.analysis_original.setPlaceholderText(ui_text('ui._analysis_section.text_2'));layout.addWidget(self.analysis_original)
        self._button(layout,ui_text('ui._analysis_section.text_3'),'pick_analysis_original',self.pick_analysis_original)
        self._button(layout,ui_text('ui._analysis_section.text_4'),'preview_candidate_analysis',lambda:self.preview_analysis('critique'))
        self._button(layout,ui_text('ui._analysis_section.text_5'),'preview_candidate_comparison',lambda:self.preview_analysis('compare'))
        self.analysis_preview=QPlainTextEdit();self.analysis_preview.setReadOnly(True);self.analysis_preview.setObjectName('analysis_preview');layout.addWidget(self.analysis_preview)
        self.analysis_evidence=QPlainTextEdit();self.analysis_evidence.setReadOnly(True);self.analysis_evidence.setObjectName('analysis_evidence');self._advanced(layout).addWidget(self.analysis_evidence)
        self.analysis_consent=QCheckBox(ui_text('ui._analysis_section.text_6'))
        self.analysis_consent.setObjectName('analysis_one_call_consent');layout.addWidget(self.analysis_consent)
        note=QLabel(ui_text('ui._analysis_section.text_7'))
        note.setWordWrap(True);layout.addWidget(note)
        self.analysis_start=self._button(layout,ui_text('ui._analysis_section.text_8'),'run_candidate_analysis',self.run_analysis)
        self.analysis_start.setEnabled(False)
        self.analysis_saved=QComboBox();self.analysis_saved.setObjectName('analysis_saved');layout.addWidget(self.analysis_saved)
        self._analysis_checkpoint_ids=set()
        self.analysis_checkpoint_notice=QLabel();self.analysis_checkpoint_notice.setObjectName('analysis_checkpoint_notice')
        self.analysis_checkpoint_notice.setWordWrap(True);layout.addWidget(self.analysis_checkpoint_notice)
        self._button(layout,ui_text('ui._analysis_section.text_9'),'read_candidate_analysis',self.read_analysis)
        self.analysis_recovery_notice=QLabel();self.analysis_recovery_notice.setWordWrap(True)
        self.analysis_recovery_notice.setObjectName('analysis_recovery_notice');layout.addWidget(self.analysis_recovery_notice)
        self.analysis_recover=self._button(layout,ui_text('ui._analysis_section.text_10'),'reconcile_saved_analysis',self.reconcile_saved_analysis)
        self.analysis_recover.setEnabled(False)
        self.analysis_findings=QPlainTextEdit();self.analysis_findings.setReadOnly(True);self.analysis_findings.setObjectName('analysis_findings');layout.addWidget(self.analysis_findings)
        self.analysis_saved.currentIndexChanged.connect(self._analysis_saved_changed)
        self.analysis_candidates.itemSelectionChanged.connect(self._invalidate_analysis_preview)
        self.analysis_original.textChanged.connect(self._invalidate_analysis_preview)

    def _invalidate_analysis_preview(self, *args):
        self._analysis_preview=None;self._analysis_request_key=None
        if hasattr(self,'analysis_consent'):
            self.analysis_consent.setChecked(False);self.analysis_start.setEnabled(False)
            self.analysis_preview.clear();self.analysis_evidence.clear()

    def pick_analysis_original(self):
        name,_=QFileDialog.getOpenFileName(self,ui_text('ui.pick_analysis_original.text_1'),'','JSON (*.json)')
        if not name:return
        if '://' in name or name.startswith(('//',chr(92)*2)) or not Path(name).is_absolute():raise ValidationError(ui_text('ui.pick_analysis_original.text_2'))
        path=Path(name).resolve(strict=True)
        if not path.is_file():raise ValidationError(ui_text('ui.pick_analysis_original.text_3'))
        self.analysis_original.setText(str(path))
        self.form_feedback(self.analysis_original, ui_text('ui.pick_analysis_original.text_4'))

    def _analysis_request(self, task):
        from quantlab.desktop_runtime import validate_analysis_request
        refs=[item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        if not refs or len({ref['campaign_folder'] for ref in refs})!=1:raise ValidationError(ui_text('ui._analysis_request.text_1'))
        c=self.chatgpt_controller;p=self.chatgpt_panel
        if c.busy or c.state!='plan_ready' or not c.active_registration or p.model.currentData() not in c.models:raise ValidationError(ui_text('ui._analysis_request.text_2'))
        request={'campaign_reference':refs[0]['campaign_folder'],'original_dataset':{'kind':'local_dataset_file','path':self.analysis_original.text()},
            'attempt_ids':sorted(ref['attempt_id'] for ref in refs),'task':task,'registration':c.active_registration,
            'model':p.model.currentData(),'timeout_seconds':p.timeout.value()}
        validate_analysis_request(request);return request

    def preview_analysis(self, task):
        request=self._analysis_request(task)
        self._invalidate_analysis_preview();self._analysis_request_key=content_hash(request)
        self.start_job('ui_analysis_preview',{'request':request})

    def run_analysis(self):
        from desktop_chatgpt_ui import SubscriptionOptions
        preview=self._analysis_preview
        if preview is None or not self.analysis_consent.isChecked():raise ValidationError(ui_text('ui.run_analysis.text_1'))
        plan=preview['plan'];request=self._analysis_request(plan['binding']['packet']['context']['task'])
        if content_hash(request)!=self._analysis_request_key:raise ValidationError(ui_text('ui.run_analysis.text_2'))
        c=self.chatgpt_controller;p=self.chatgpt_panel
        if (not c.account_status_known or c.account_paused or c.account_pending
            or preview['receipt_snapshot']['receipts']):raise ValidationError(ui_text('ui.run_analysis.text_3'))
        if (not p.consent.isChecked() or not p.included_usage_only.isChecked()
            or p._included_usage_registration!=request['registration'] or p.account.currentData()!=request['registration']):
            raise ValidationError(ui_text('ui.run_analysis.text_4'))
        SubscriptionOptions(request['registration'],request['model'],1,request['timeout_seconds'],network_opt_in=True,included_usage_policy_confirmed=True)
        import copy
        payload={'request':request,'approved_plan':copy.deepcopy(plan),'expected_analysis_id':plan['analysis_id'],'expected_plan_hash':content_hash(plan),'user_confirmed':True,
            'network_opt_in':True,'included_usage_policy_confirmed':True}
        self.analysis_consent.setChecked(False);p.consent.setChecked(False);p._reset_included_usage()
        job_id=self.start_job('ui_analysis_run',payload)
        self._analysis_launch={'analysis_id':plan['analysis_id'],'registration':request['registration'],'stopped_job_id':job_id}
        self._analysis_running=True;self._analysis_preview=None
        c.invalidate_campaign_usage();self._plan_usage_binding=None

    def read_analysis(self):
        reference=self.analysis_saved.currentData()
        if not reference:raise ValidationError(ui_text('ui.read_analysis.text_1'))
        self._invalidate_analysis_preview()
        if reference in self._analysis_checkpoint_ids:
            self._analysis_saved_changed()
            return
        self.start_job('ui_analysis_read',{'analysis_id':reference})

    def _analysis_saved_changed(self, *args):
        self.analysis_checkpoint_notice.clear()
        if self.analysis_saved.currentData() in self._analysis_checkpoint_ids:
            self._invalidate_analysis_preview()
            self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText(ANALYSIS_CHECKPOINT_NOTICE)
            self.status.setText(ANALYSIS_CHECKPOINT_STATUS)
        elif self.status.text()==ANALYSIS_CHECKPOINT_STATUS:
            self.status.setText(ui_text('ui._analysis_saved_changed.text_1'))
        self._refresh_recovery_controls(force=True)

    def _selected_recovery_launch(self, disposition=None):
        from quantlab.analysis_recovery import inspect_recovery, validate_stop_receipt, supports_durable_recovery, RecoveryError
        if not supports_durable_recovery():return None
        reference=self.analysis_saved.currentData()
        if not reference:return None
        display_only=disposition is not None
        disposition=disposition or inspect_recovery(self.paths)
        for launch in disposition.workspace_stopped:
            if launch['analysis_id']!=reference:continue
            if display_only:return launch  # Current validated snapshot; presentation only.
            try:return validate_stop_receipt(self.paths,launch['job_id'])
            except RecoveryError:return None
        return None

    def reconcile_saved_analysis(self):
        if self.jobs.active:raise ValidationError(ui_text('ui.reconcile_saved_analysis.text_1'))
        launch=self._selected_recovery_launch()
        if launch is None:raise ValidationError(ui_text('ui.reconcile_saved_analysis.text_2'))
        self._invalidate_analysis_preview()
        self.start_job('ui_analysis_reconcile',{'analysis_id':launch['analysis_id'],
            'registration':launch['registration'],'recovery_launch_id':launch['job_id']})

    def _recovery_display_fingerprint(self):
        # Metadata is presentation invalidation only, never stop/admission proof.
        # lstat does not follow a newly substituted link or open its target.
        bootstrap=self.paths.bootstrap or self.paths.root
        database=self.paths.controls/'analysis-recovery-v1.sqlite3'
        result=[]
        for path in (bootstrap,self.paths.controls,self.paths.root,
                     bootstrap/'.analysis-recovery-v1.json',database,
                     Path(str(database)+'-journal'),Path(str(database)+'-wal'),Path(str(database)+'-shm')):
            try:
                info=path.lstat()
                result.append((info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns))
            except OSError as exc:result.append((type(exc).__name__,exc.errno))
        return tuple(result)

    def _refresh_recovery_controls(self, *, force=False):
        """Cache presentation only; every dispatch and explicit repair revalidates."""
        if not hasattr(self,'analysis_recover'):return
        import time
        from quantlab.analysis_recovery import inspect_recovery, RecoveryError
        now=time.monotonic();cached=getattr(self,'_recovery_display',None)
        refresh=force or cached is None
        if not refresh and now-cached[0]>=2:
            refresh=self._recovery_display_fingerprint()!=self._recovery_display_metadata
            if not refresh:
                cached=(now,*cached[1:]);self._recovery_display=cached
        if refresh:
            self._recovery_display_metadata=self._recovery_display_fingerprint()
            failed=False;launch=None
            try:
                disposition=inspect_recovery(self.paths)
                source_blocked=bool(disposition.unresolved)
                workspace_blocked=bool(disposition.workspace_unresolved)
                if not self.jobs.active:launch=self._selected_recovery_launch(disposition)
            except (RecoveryError,OSError):
                failed=True;source_blocked=workspace_blocked=True
            if failed:
                message=ui_text('ui._refresh_recovery_controls.text_1')
            elif workspace_blocked:
                message=ui_text('ui._refresh_recovery_controls.text_2')
            elif source_blocked:
                message=ui_text('ui._refresh_recovery_controls.text_3')
            elif launch is not None:
                message=ui_text('ui._refresh_recovery_controls.text_4')
            else:message=''
            cached=(now,source_blocked,workspace_blocked,launch is not None,message)
            self._recovery_display=cached
        _,source_blocked,workspace_blocked,eligible,message=cached
        # Reapply cached restrictions even when _busy(False) just reset buttons.
        if source_blocked:
            for name in ('create_demo','import_data','refresh_data','market_refresh','import_market_file','import_market_history',
                         'run_campaign','run_walk_forward','preview_candidate_analysis','preview_candidate_comparison',
                         'run_candidate_analysis','restore_backup'):
                button=self.findChild(QPushButton,name)
                if button is not None:button.setEnabled(False)
        if workspace_blocked:
            button=self.findChild(QPushButton,'create_backup')
            if button is not None:button.setEnabled(False)
        self.analysis_recover.setEnabled(eligible and not self.jobs.active)
        self.analysis_recovery_notice.setText(message)

    def _analysis_event(self, event):
        if self.last_operation not in ('ui_analysis_preview','ui_analysis_run','ui_analysis_read','ui_analysis_reconcile'):return False
        kind=event.get('type')
        if kind=='progress':self.status.setText(str(event.get('message',ui_text('ui._analysis_event.text_1'))));return True
        if kind not in ('result','error','failed','cancelled','canceled'):return True
        operation=self.last_operation
        self.record_event(operation,kind)
        if operation=='ui_analysis_run':
            self._analysis_running=False;self._pending_analysis_reconcile=self._analysis_launch is not None
            self.chatgpt_controller.account_status_known=False;self.chatgpt_controller.invalidate_campaign_usage()
            self._pending_usage_refresh=True
        if kind=='result':
            result=event['result']
            if operation=='ui_analysis_preview':
                plan=result['plan'];task=plan['binding']['packet']['context']['task']
                if content_hash(self._analysis_request(task))!=self._analysis_request_key:
                    self._invalidate_analysis_preview();self.status.setText(ui_text('ui._analysis_event.text_2'));return True
                if result['analysis_id']!=plan['analysis_id']:raise ValidationError(ui_text('ui._analysis_event.text_3'))
                self._analysis_preview=result
                self.chatgpt_controller.set_account_status(plan['binding']['registration'],result['account_status'])
                self.analysis_preview.setPlainText(analysis_preview_text(plan))
                self.analysis_evidence.setPlainText(canonical_json(plan['binding']['packet']['context']))
                self.analysis_start.setEnabled(not result['receipt_snapshot']['receipts'])
                self._refresh_recovery_controls(force=True)
                self.status.setText(ui_text('ui._analysis_event.text_4'))
            else:
                self._refresh_analysis_saved(preferred_reference=result['analysis_id'])
                if result['analysis_id'] in self._analysis_checkpoint_ids:return True
                if self.analysis_saved.currentData()!=result['analysis_id']:
                    self.analysis_findings.clear();self.analysis_evidence.clear()
                    self.status.setText(ui_text('ui._analysis_event.text_5'))
                    return True
                self.analysis_findings.setPlainText(analysis_record_text(result['record']))
                self.analysis_evidence.setPlainText(canonical_json(result['record']['plan']['binding']['packet']['context']))
                self.status.setText(ui_text('ui._analysis_event.text_6'))
        else:
            self.analysis_consent.setChecked(False)
            self.status.setText(error_message('operation_failed'))
        return True

    def _refresh_analysis_saved(self, *, preferred_reference=None):
        old=preferred_reference or self.analysis_saved.currentData();failed=False
        try:entries=saved_analysis_entries(self.root/'analyses')
        except (OSError, ValidationError):entries=();failed=True
        self._analysis_checkpoint_ids={name for name,checkpoint in entries if checkpoint}
        blocked=self.analysis_saved.blockSignals(True)
        try:
            self.analysis_saved.clear()
            for name,checkpoint in entries:
                label=ANALYSIS_CHECKPOINT_STATUS+' · '+name if checkpoint else name
                self.analysis_saved.addItem(label,name)
            index=self.analysis_saved.findData(old)
            if index>=0:self.analysis_saved.setCurrentIndex(index)
        finally:self.analysis_saved.blockSignals(blocked)
        self._analysis_saved_changed()
        if failed:
            self._invalidate_analysis_preview();self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText(ui_text('ui._refresh_analysis_saved.text_1'))

    def _paper_page(self):
        layout = self._page(ui_text('ui._paper_page.text_1'))
        note = QLabel(ui_text('ui._paper_page.text_2')); note.setWordWrap(True); layout.addWidget(note)
        limits = paper_risk_limits()
        self.paper_risk_summary = QLabel(
            ui_text('ui._paper_page.text_3').format(limits.max_position, limits.max_order_quantity, display_number(limits.max_daily_loss, "cash"), limits.max_quote_age_seconds, limits.max_consecutive_losses, limits.window_seconds, limits.max_orders_per_window))
        self.paper_risk_summary.setObjectName('paper_fixed_risk_summary')
        self.paper_risk_summary.setWordWrap(True); layout.addWidget(self.paper_risk_summary)
        advanced = self._advanced(layout)
        policy_layout = self._advanced(layout, ui_text('ui._paper_page.text_4'))
        self.policy_form = PaperPolicyForm(); policy_layout.addWidget(self.policy_form)
        self.paper_policy = self._text(advanced, ui_text('ui._paper_page.text_5'), '{}', True)
        self._remember(self.paper_policy)
        self._button(layout, ui_text('ui._paper_page.text_6'), 'load_policy_file', lambda: self.load_form_file(self.policy_form, self.paper_policy))
        self._button(layout, ui_text('ui._paper_page.text_7'), 'demo_policy', self.demo_paper_policy)
        self._button(layout, ui_text('ui._paper_page.text_8'), 'paper_snapshot', lambda: self.paper_job('snapshot'))
        snapshot_layout = self._advanced(layout, ui_text('ui._paper_page.text_9'))
        self.snapshot_form = PaperSnapshotForm(); snapshot_layout.addWidget(self.snapshot_form)
        self.snapshot = self._text(advanced, ui_text('ui._paper_page.text_10'), canonical_json({'account_id':'paper-demo','cash':'1000000','positions':{},'orders':{},'fills':{}}), True)
        self.snapshot_form.from_payload(json.loads(self.snapshot.toPlainText())); self._remember(self.snapshot)
        self._button(layout, ui_text('ui._paper_page.text_11'), 'load_snapshot_file', lambda: self.load_form_file(self.snapshot_form, self.snapshot))
        self._button(layout, ui_text('ui._paper_page.text_12'), 'paper_reconcile', lambda: self.paper_job('reconcile', snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload)))
        self.kill_button = self._button(layout, ui_text('ui._paper_page.text_13'), 'paper_kill', self.kill_paper, role='danger')
        self.replay_bars = QSpinBox(); self.replay_bars.setRange(1, 1000); self.replay_bars.setValue(100); layout.addWidget(self.replay_bars)
        self.paper_confirm = QCheckBox(ui_text('ui._paper_page.text_14')); layout.addWidget(self.paper_confirm)
        self._button(layout, ui_text('ui._paper_page.text_15'), 'paper_replay', lambda: self.paper_job('replay', max_bars=self.replay_bars.value()))
        order_layout = self._advanced(layout, ui_text('ui._paper_page.text_16'))
        self.intent_form = PaperIntentForm(); order_layout.addWidget(self.intent_form)
        self.quote_form = PaperQuoteForm(); order_layout.addWidget(self.quote_form)
        self.intent = self._text(advanced, ui_text('ui._paper_page.text_17'), '{}', True)
        self.quote = self._text(advanced, ui_text('ui._paper_page.text_18'), '{}', True)
        self._remember(self.intent); self._remember(self.quote)
        self.paper_time = self._text(layout, ui_text('ui._paper_page.text_19'), '2026-01-05T01:00:00Z')
        self._button(layout, ui_text('ui._paper_page.text_20'), 'paper_submit', lambda: self.paper_job('submit', intent=self._payload(self.intent, self.intent_form.build_payload), quote=self._payload(self.quote, self.quote_form.build_payload), now=self.paper_time.text()), role='primary')
        self.cancel_order = self._text(layout, ui_text('ui._paper_page.text_21'))
        self._button(layout, ui_text('ui._paper_page.text_22'), 'paper_cancel', lambda: self.paper_job('cancel', order_id=self.cancel_order.text(), now=self.paper_time.text()), role='danger')
        self.paper_detail = QPlainTextEdit(); self.paper_detail.setReadOnly(True); advanced.addWidget(self.paper_detail)
        self.paper_card = SummaryCard(); layout.insertWidget(2, self.paper_card)

    def _settings_page(self):
        layout = self._page(ui_text('ui._settings_page.text_1'))
        layout.addWidget(QLabel(ui_text('ui._settings_page.text_2').format(str(self.paths.root))))
        layout.addWidget(QLabel(ui_text('ui._settings_page.text_3').format(str(self.root))))
        layout.addWidget(QLabel(ui_text('ui._settings_page.text_4')))
        layout.addWidget(QLabel(ui_text('ui._settings_page.text_5').format(str(self.paths.logs))))
        self.workspace_path = self._text(layout, ui_text('ui._settings_page.text_6'), str(self.paths.root))
        self._button(layout, ui_text('ui._settings_page.text_7'), 'configure_workspace', self.configure_workspace)
        from desktop_chatgpt_ui import ChatGPTConnectionPanel, ConnectionController
        self.chatgpt_controller = ConnectionController(self)
        self.chatgpt_panel = ChatGPTConnectionPanel(self.chatgpt_controller); layout.addWidget(self.chatgpt_panel)
        self.chatgpt_controller.set_host_available(True)
        self.chatgpt_controller.quiesce_requested.connect(self._chatgpt_quiesce)
        self.chatgpt_controller.request_ready.connect(self._chatgpt_dispatch)
        self.chatgpt_controller.cancel_requested.connect(self._chatgpt_cancel)
        self.chatgpt_controller.browser_requested.connect(self._chatgpt_open_browser)
        self.persist_logs = QCheckBox(ui_text('ui._settings_page.text_8')); self.persist_logs.setChecked(True); layout.addWidget(self.persist_logs)
        self.local_notifications = QCheckBox(ui_text('ui._settings_page.text_9')); self.local_notifications.setChecked(True); layout.addWidget(self.local_notifications)
        self._button(layout, ui_text('ui._settings_page.text_10'), 'save_settings', self.save_settings, role='primary')
        self.backup_path = self._text(layout, ui_text('ui._settings_page.text_11'))
        self._button(layout, ui_text('ui._settings_page.text_12'), 'create_backup', lambda: self.backup(False))
        self.restore_confirm = QCheckBox(ui_text('ui._settings_page.text_13')); layout.addWidget(self.restore_confirm)
        self._button(layout, ui_text('ui._settings_page.text_14'), 'restore_backup', lambda: self.backup(True), role='danger')
        from desktop_automatic_backup import AutomaticBackupPanel
        self.automatic_backup_panel = AutomaticBackupPanel(self); layout.addWidget(self.automatic_backup_panel)
        from quantlab import __version__
        self.version_label = QLabel(ui_text('ui._settings_page.text_15').format(__version__))
        self.version_label.setWordWrap(True); layout.addWidget(self.version_label)
        layout.addWidget(QLabel(ui_text('ui._settings_page.text_16')))
        self._button(layout, ui_text('ui._settings_page.text_17'), 'open_releases', self.open_releases)
        self._button(layout, ui_text('ui._settings_page.text_18'), 'read_logs', self.read_logs)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setPlaceholderText(ui_text('ui._settings_page.text_19')); layout.addWidget(self.log_view)
        layout.addStretch()

    def _safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            message = error_message(exception_code(exc))
            self.status.setText(message)
            self.notify_local(message, error=True, completion=True)
            return None

    def _browse(self, target):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('ui._browse.text_1'))
        if name:
            target.setText(name)
            self.form_feedback(target, ui_text('ui._browse.text_2'))

    def load_form_file(self, form, editor):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('ui.load_form_file.text_1'), '', 'JSON (*.json)')
        if not name: return
        path = Path(name)
        if path.stat().st_size > 4 * 1024 * 1024: raise ValidationError(ui_text('ui.load_form_file.text_2'))
        value = read_json(path)
        form.from_payload(value)
        editor.setPlainText(canonical_json(value)); self._remember(editor)
        self.paper_confirm.setChecked(False)
        self.form_feedback(form, ui_text('ui.load_form_file.text_3'))

    def _family_changed(self):
        self.active_candidate = None
        if hasattr(self, 'candidate_choice'): (self.root / 'active_candidate.json').unlink(missing_ok=True)
        self.parameters.setReadOnly(False)
        from quantlab.strategies import builtin_strategies
        spec = builtin_strategies()[self.family.currentIndex()]
        self.parameters.setPlainText(canonical_json(spec.parameters)); self._remember(self.parameters)
        self.strategy_form.family.blockSignals(True)
        try: self.strategy_form.from_payload(to_dict(spec))
        finally: self.strategy_form.family.blockSignals(False)
        self.strategy_form.setEnabled(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy': spec, 'sha256': content_hash(spec), 'scope': 'research_and_paper_only'}))

    def import_data(self):
        if not self.import_path.text().strip() or not self.calendar_path.text().strip():
            raise ValidationError(ui_text('ui.import_data.text_1'))
        self.start_job('ui_import', {'path': self.import_path.text(), 'calendar': self.calendar_path.text(), 'kind': self.import_kind.currentText(), 'contract': self.contract.text()})

    def download_data(self):
        if not self.network_data.isChecked(): raise ValidationError(ui_text('ui.download_data.text_1'))
        self.start_job('ui_refresh', {'days':self.days.value(), 'network_opt_in':True})
        self.network_data.setChecked(False)

    def run_backtest(self):
        typed = self.backtest_form.build_payload()
        config = self._payload(self.config, lambda: typed['config'])
        spec = self.strategy_form.build_payload() if self.active_candidate is None else None
        parameters = self._payload(self.parameters, lambda: spec['parameters']) if spec else json.loads(self.parameters.toPlainText())
        self.start_job('ui_backtest', {'family': self.family.currentText(), 'parameters': parameters,
            'config': config, 'start_date': typed['start_date'], 'end_date': typed['end_date'],
            'batch': self.batch.isChecked(), 'candidate': self.active_candidate})

    def run_campaign(self):
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        options = {'mode':self.provider_mode.currentData()}
        if options['mode'] not in ('chatgpt_plan', 'fixture', 'manual'):
            raise ValidationError(ui_text('ui.run_campaign.text_1'))
        if options['mode'] == 'chatgpt_plan':
            from dataclasses import asdict
            options = asdict(self.chatgpt_panel.build_plan_options())
            options['expected_binding'] = self._plan_usage_binding
            from quantlab.__main__ import config_from_json
            checked = dict(config); checked['backtest_config'] = config_from_json(checked['backtest_config'])
            plan_provider(self.paths, _dataset(self.root, {}), checked, options)
        if options['mode'] == 'manual':
            options.update(response_path=self.manual_path.text().strip(), response_text=self.manual_response.toPlainText())
        subscription_campaign = options['mode'] == 'chatgpt_plan'
        launched_job = self.start_job('ui_campaign', {'config':config, 'provider':options})
        self._subscription_campaign = subscription_campaign
        if self._subscription_campaign:
            local_options = {**options,'network_opt_in':False,'included_usage_policy_confirmed':False}
            self._plan_launch = json.loads(canonical_json({'config':config,'provider':local_options,'binding':options['expected_binding'],'stopped_job_id':launched_job}))
            self.chatgpt_controller.invalidate_campaign_usage()

    def export_manual_request(self):
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        if config.get('max_improvements') != 0:
            raise ValidationError(ui_text('ui.export_manual_request.text_1'))
        name, _ = QFileDialog.getSaveFileName(self, ui_text('ui.export_manual_request.text_2'), 'manual-ai-request.json', 'JSON (*.json)')
        if name:
            if Path(name).exists(): raise ValidationError(ui_text('ui.export_manual_request.text_3'))
            self.start_job('ui_campaign', {'config': config, 'provider': {'mode':'manual'}, 'manual_export': name})

    def select_strategy(self):
        path = self.result_choice.currentData()
        if not path: raise ValidationError(ui_text('ui.select_strategy.text_1'))
        self.start_job('ui_select', {'result':path})

    def demo_paper_policy(self):
        data = load_dataset(self.root / 'dataset.json')
        if data.manifest['source_type'] != 'synthetic': raise ValidationError(ui_text('ui.demo_paper_policy.text_1'))
        sessions = []
        for day in sorted({b.trade_date for b in data.bars}):
            bars = [b for b in data.bars if b.trade_date == day]
            sessions.append({'open':bars[0].timestamp.isoformat(), 'end':bars[-1].end.isoformat(), 'trade_date':day, 'session':bars[0].session, 'contract_id':bars[0].contract_id, 'source':'explicit synthetic demonstration'})
        policy = {'contract_id':data.bars[0].contract_id,'risk_sessions':sessions,'margin_schedule':[{'effective_from':'2026-01-01','margin_per_contract':'100000','version':'synthetic-assumption-v1'}]}
        self.paper_policy.setPlainText(canonical_json(policy)); self.policy_form.from_payload(policy); self._remember(self.paper_policy)
        self.form_feedback(self.policy_form.sessions, ui_text('ui.demo_paper_policy.text_2').format(len(sessions)))

    def form_feedback(self, widget, message):
        self.status.setText(message)
        scroll = widget.parentWidget()
        while scroll is not None and not isinstance(scroll, QScrollArea):
            scroll = scroll.parentWidget()
        if scroll is not None: scroll.ensureWidgetVisible(widget)
        original = widget.property('feedback')
        set_theme_property(widget, 'feedback', True)
        QTimer.singleShot(1800, widget, lambda: set_theme_property(widget, 'feedback', original))

    def paper_job(self, op, **payload):
        if op in ('submit', 'replay'):
            if not self.paper_confirm.isChecked(): raise ValidationError(ui_text('ui.paper_job.text_1'))
            payload.update(snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload), reconcile_confirmed=True)
        payload['policy'] = self._payload(self.paper_policy, self.policy_form.build_payload)
        self.start_job('ui_paper_' + op, payload)
        self.paper_confirm.setChecked(False)

    def kill_paper(self):
        self.freeze_paper(ui_text('ui.kill_paper.text_1'))
        self.status.setText(ui_text('ui.kill_paper.text_2'))

    def auto_restore_chatgpt(self):
        """Startup only: reload the saved ChatGPT login once background work is idle."""
        self._pending_chatgpt_restore = True

    def show_chatgpt_sign_in(self):
        """One research entry to the existing official connection panel."""
        self.provider_mode.setCurrentIndex(self.provider_mode.findData('chatgpt_plan'))
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if page.isAncestorOf(self.chatgpt_panel):
                self.navigation.setCurrentRow(index)
                self.chatgpt_panel.primary_sign_in.setFocus()
                # The panel is taller than one viewport: show its title and
                # consent disclosure, rather than centering a clipped widget.
                page.verticalScrollBar().setValue(self.chatgpt_panel.mapTo(page.widget(), self.chatgpt_panel.rect().topLeft()).y())
                page.horizontalScrollBar().setValue(0)
                self.status.setText(ui_text('ui.show_chatgpt_sign_in.text_1'))
                self.chatgpt_panel.primary_sign_in.click()
                return
        raise ValidationError(ui_text('ui.show_chatgpt_sign_in.text_2'))

    def _chatgpt_quiesce(self, request):
        try:
            self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # The original analysis tree is joined, but its local evidence
                # reconciliation owns the slot. This auth request was never
                # dispatched: fail it explicitly rather than strand or queue it.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self.status.setText(ui_text('ui._chatgpt_quiesce.text_1'))
                return
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=not self.jobs.active)
        except Exception:
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=False)

    def _chatgpt_dispatch(self, request):
        try:
            if self.jobs.active:
                self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # Primary sign-in starts with local list (no quiesce signal).
                # It must not remain busy after reconciliation takes the slot.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request=None;self._chatgpt_job_id=None
                self.status.setText(ui_text('ui._chatgpt_dispatch.text_1'))
                return
            self._chatgpt_job_request = request
            self._chatgpt_job_id = self.start_job('ui_chatgpt_auth', {'request':request.payload()})
        except Exception:
            self.chatgpt_controller.worker_joined(request.request_id, joined=not self.jobs.active, terminal_received=False)
            self._chatgpt_job_request = None
            self.status.setText(ui_text('ui._chatgpt_dispatch.text_2'))

    def _chatgpt_cancel(self, request_id):
        self.chatgpt_panel.abandon_primary_sign_in()
        self._pending_usage_refresh = False
        if self.jobs.active: self.jobs.cancel()
        if self.jobs.active: return
        # Drain old packets before another operation may own the single manager.
        self.poll_jobs()
        self.chatgpt_controller.worker_joined(request_id, joined=True, terminal_received=False)
        self._chatgpt_job_request = None
        self._chatgpt_job_id = None
        self.chatgpt_panel.consent.setChecked(False)

    def _chatgpt_open_browser(self, url):
        if getattr(self, '_closing', False) or not self.chatgpt_controller.host_available:
            return
        from desktop_chatgpt_ui import official_authorization_url
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(official_authorization_url(url))):
            self.status.setText(ui_text('ui._chatgpt_open_browser.text_1'))

    def _plan_usage_request(self):
        c = self.chatgpt_controller; panel = self.chatgpt_panel
        if c.state != 'plan_ready' or not c.active_registration or panel.model.currentData() not in c.models:
            raise ValidationError(ui_text('ui._plan_usage_request.text_1'))
        options = {'mode':'chatgpt_plan','registration':c.active_registration,
            'model':panel.model.currentData(),'max_calls':panel.max_calls.value(),
            'timeout_seconds':panel.timeout.value(),'network_opt_in':False,
            'included_usage_policy_confirmed':False,'paid_api_fallback':False}
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        return {'registration':c.active_registration,'provider':options,'config':config}

    def _current_plan_binding(self):
        from quantlab.__main__ import config_from_json
        payload = self._plan_usage_request()
        config = dict(payload['config']); config['backtest_config'] = config_from_json(config['backtest_config'])
        return plan_provider(self.paths, _dataset(self.root, {}), config, payload['provider'], for_usage=True)[1]

    def inspect_plan_usage(self):
        self._invalidate_analysis_preview()
        if self.chatgpt_controller.busy: raise ValidationError(ui_text('ui.inspect_plan_usage.text_1'))
        payload = self._plan_usage_request()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        self.start_job('ui_chatgpt_usage', payload)

    def _record_connection_error(self, code):
        from quantlab.desktop_errors import ERROR_TABLE
        from quantlab.desktop_runtime import RedactedEventLog
        fixed = code if code in ERROR_TABLE else 'operation_failed'
        RedactedEventLog(self.paths.logs / 'desktop-events.jsonl').append(
            'ui_chatgpt_auth', 'error', error_code=fixed)

    def _chatgpt_event(self, event):
        operation = self.last_operation
        if operation not in ('ui_chatgpt_auth','ui_chatgpt_usage','ui_chatgpt_reconcile'): return False
        kind = event.get('type')
        if operation == 'ui_chatgpt_reconcile':
            if kind in ('result','completed','success','error','failed','cancelled','canceled'):
                self.chatgpt_controller.account_status_known = False
                self.chatgpt_controller.invalidate_campaign_usage()
                self._pending_usage_refresh = True
                self.status.setText(ui_text('ui._chatgpt_event.text_1') if kind == 'result' else ui_text('ui._chatgpt_event.text_2'))
            return True
        if operation == 'ui_chatgpt_auth':
            request = self._chatgpt_job_request
            if request is None: return True
            if self._chatgpt_job_id is not None and event.get('job_id') not in (None,self._chatgpt_job_id): return True
            if kind == 'auth_progress':
                connection = connection_event_from_payload(event['auth_event'])
                if connection.kind == 'error':
                    self._record_connection_error(connection.error_code)
                self.chatgpt_controller.apply_event(connection)
            elif kind in ('result','completed','success','error','failed','cancelled','canceled'):
                received = False
                if kind in ('result','completed','success'):
                    connection = connection_event_from_payload(event['result']['auth_event'])
                    if connection.kind == 'error':
                        self._record_connection_error(connection.error_code)
                    received = self.chatgpt_controller.apply_event(connection)
                joined = not self.jobs.active
                self.chatgpt_controller.worker_joined(request.request_id, joined=joined, terminal_received=received)
                if joined:
                    self._chatgpt_job_request = None; self._chatgpt_job_id = None
                    self._pending_usage_refresh = bool(received and self.chatgpt_controller.active_registration)
            return True
        if kind in ('result','completed','success'):
            result = event['result']; c = self.chatgpt_controller
            if result.get('registration') != c.active_registration: return True
            c.set_account_status(result['registration'],result['account_status'])
            if 'receipts' in result:
                if result.get('binding') != self._current_plan_binding():
                    c.invalidate_campaign_usage(); self._plan_usage_binding = None
                    self.status.setText(ui_text('ui._chatgpt_event.text_3'))
                else:
                    c.set_usage(result['registration'],result['receipts'],account_status=result['account_status'])
                    self._plan_usage_binding = result['binding']
                    self.status.setText(ui_text('ui._chatgpt_event.text_4'))
        elif kind in ('error','failed','cancelled','canceled'):
            self.chatgpt_controller.account_status_known = False
            self.chatgpt_controller.invalidate_campaign_usage()
            self.status.setText(ui_text('ui._chatgpt_event.text_5'))
        return True

    def start_job(self, operation, payload):
        from quantlab.analysis_recovery import require_operation
        require_operation(self.paths,operation)
        if operation not in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
            self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active: raise ValidationError(ui_text('ui.start_job.text_1'))
        job_id = self.jobs.start(operation, payload)
        self.last_operation = operation
        self._ui_job_id = job_id
        self.status.setText(ui_text('ui.start_job.text_2'))
        self._busy(True)
        return job_id

    def _busy(self, active, *, refresh_recovery=False):
        for button in self.actions: button.setEnabled(not active)
        self.market.set_loading(active)
        self.kill_button.setEnabled(True)
        self.cancel_button.setEnabled(active)
        self.cancel_button.setVisible(active); self.progress.setVisible(active)
        self.progress.setRange(0, 0 if active else 100)
        if not active:
            self.progress.setValue(0)
            self.run_button.setEnabled(bool(getattr(self, '_dataset_ready', False)))
            self.use_candidate_button.setEnabled(bool(getattr(self, '_candidate_valid', False)))
            self.select_button.setEnabled(bool(getattr(self, '_selection_allowed', False)))
            self.walk_forward_start.setEnabled(self._wf_preview is not None)
            self.analysis_start.setEnabled(self._analysis_preview is not None and not self._analysis_preview['receipt_snapshot']['receipts'])
        self._refresh_recovery_controls(force=active or refresh_recovery)

    def cancel_job(self):
        def cancel_and_recover():
            self.freeze_paper(ui_text('ui.cancel_and_recover.text_1'))
            self.status.setText(ui_text('ui.cancel_and_recover.text_2'))
        self._safe(cancel_and_recover)

    def poll_jobs(self):
        try:
            recovery_changed=False
            for event in self.jobs.poll():
                if event.get('job_id') is not None and self._ui_job_id is not None and event['job_id'] != self._ui_job_id:
                    continue  # A joined old worker can never overwrite a newer view.
                recovery_changed = recovery_changed or event.get('type') in ('result','error','failed','cancelled','canceled')
                self.automatic_backup_panel.handle_job_event(event)
                if self._walk_forward_event(event): continue
                if self._analysis_event(event): continue
                kind = event.get('type', '')
                if self._chatgpt_event(event): continue
                if self._subscription_campaign and kind in ('result','error','failed','cancelled'):
                    self.chatgpt_controller.invalidate_campaign_usage()
                    self.chatgpt_controller.account_status_known = False
                    self._pending_plan_reconcile = self._plan_launch is not None
                    self._pending_usage_refresh = True
                    self._subscription_campaign = False
                self.record_event(self.last_operation, kind)
                if kind in ('result', 'completed', 'success'):
                    result = event.get('result', {})
                    if isinstance(result, list): result = {'downloads':result}
                    text = canonical_json(result)
                    self.summary.setPlainText(text)
                    if self.last_operation == 'ui_compare':
                        self.comparison.setPlainText(text); self.comparison_table.set_rows(result.get('rows', []))
                    if result.get('manual_export'):
                        self.status.setText(ui_text('ui.poll_jobs.text_1'))
                    if self.last_operation == 'ui_market_refresh': self._market_outcomes = result.get('providers', {})
                    if self.last_operation and self.last_operation.startswith('ui_paper_'):
                        self.paper_detail.setPlainText(text)
                        if 'account' in result: self._show_account(result['account'])
                    if self.last_operation == 'ui_backup_restore': self.freeze_paper(ui_text('ui.poll_jobs.text_2'))
                    if self.last_operation in ('ui_paper_replay', 'ui_paper_kill') and 'account' in result:
                        self._remember_stop(result['account'], 'replay' if self.last_operation == 'ui_paper_replay' else 'user')
                    self.refresh_views()
                    message = completion_summary(self.last_operation, result)
                    if self.last_operation == 'ui_market_refresh' and any(v.get('error') for v in self._market_outcomes.values()):
                        message += ui_text('ui.poll_jobs.text_3')
                    self.status.clear()
                    self.notify_local(message, error=any(v.get('error') for v in result.get('providers', {}).values()), completion=True)
                elif kind in ('error', 'failed'):
                    if self.last_operation == 'ui_backup_restore':
                        self.freeze_paper(ui_text('ui.poll_jobs.text_4'))
                    self.status.clear()
                    self.notify_local(error_message('operation_failed'), error=True, completion=True)
                elif kind in ('cancelled', 'canceled'):
                    self.freeze_paper(ui_text('ui.poll_jobs.text_5'))
                    self.status.setText(ui_text('ui.poll_jobs.text_6'))
                else:
                    self.status.setText(str(event.get('message', ui_text('ui.poll_jobs.text_7'))))
            if not self.jobs.active:
                self._busy(False,refresh_recovery=recovery_changed)
                if self._wf_pending_reconcile and self._wf_launch is not None:
                    self._wf_pending_reconcile = False
                    self.start_job('ui_walk_forward_reconcile', self._wf_launch)
                    return
                if self._pending_analysis_reconcile and self._analysis_launch is not None:
                    self._pending_analysis_reconcile=False
                    self.start_job('ui_analysis_reconcile',dict(self._analysis_launch))
                    return
                if getattr(self,'_close_after_reconcile',False):
                    self._close_after_reconcile = False
                    self.close()
                    return
                if self._pending_plan_reconcile and not self.chatgpt_controller.busy and not getattr(self,'_closing',False):
                    self._pending_plan_reconcile = False
                    self.start_job('ui_chatgpt_reconcile', self._plan_launch)
                if not self.jobs.active and self._pending_chatgpt_restore and not self.chatgpt_controller.busy and not getattr(self, '_closing', False):
                    self._pending_chatgpt_restore = False
                    self.chatgpt_panel.start_auto_restore()
                if not self.jobs.active and self._pending_usage_refresh and not self.chatgpt_controller.busy and not getattr(self, '_closing', False):
                    self._pending_usage_refresh = False
                    reference = self.chatgpt_controller.active_registration
                    if reference: self.start_job('ui_chatgpt_usage', {'registration':reference})
                if not self.jobs.active and getattr(self, '_kill_pending', False):
                    self._kill_pending = False
                    self.paper_job('kill')
        except Exception as exc:
            self.status.setText(error_message(exception_code(exc)))

    def load_market_cache(self):
        from quantlab.market_providers import load_cached
        series, errors, quotes = {}, [], []
        self._market_data_bindings = {}
        self._market_research_series = {}
        for provider in ('twse', 'taifex'):
            try:
                loaded = load_cached(provider, self.root / 'market_cache')
                series.update({x.instrument.contract_id: x for x in loaded.series}); quotes.extend(loaded.series)
                outcome = self._market_outcomes.get(provider)
                if outcome and outcome.get('error'): errors.append(ui_text('ui.load_market_cache.text_1').format(provider.upper()))
            except ValueError:
                if (self.root / 'market_cache' / (provider + '.json')).exists(): errors.append(ui_text('ui.load_market_cache.text_2').format(provider.upper()))
                if self._market_outcomes.get(provider, {}).get('error'):
                    errors.append(ui_text('ui.load_market_cache.text_3').format(provider.upper()))
        dataset_path, calendar_path = self.root / 'dataset.json', self.root / 'dataset_calendar.json'
        if dataset_path.exists() and calendar_path.exists():
            try:
                dataset = load_dataset(dataset_path)
                for item in dataset_market_series(dataset, read_json(calendar_path)):
                    series[item.instrument.contract_id] = item
                    quotes.append(item)
                    self._market_data_bindings[item.instrument.contract_id] = dataset.manifest['data_hash']
                    self._market_research_series[item.instrument.contract_id] = item
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(error_message(exception_code(exc)))
        try:
            from quantlab.market_history import list_history
            histories = list_history(self.root / 'market_history')
            # Keep immutable imports separate; newest received snapshot wins per
            # exact contract. Do not blend policies or minute/daily observations.
            incoming = [item for loaded in histories for item in loaded.series]
            for item in sorted(incoming, key=lambda item: (item.provenance.received_at, item.provenance.sha256)):
                series[item.instrument.contract_id] = item
        except (ValueError, OSError) as exc:
            errors.append(error_message(exception_code(exc)))
        self.market.set_quote_series(latest_market_observations(quotes), stale=True)
        self.market.set_market_series(tuple(series.values()), stale=True, error=ui_text('ui.load_market_cache.text_4').join(errors))
        selection = self.root / 'selection.json'
        strategy = ui_text('ui.load_market_cache.text_5')
        if selection.exists():
            try: strategy = ui_text('ui.load_market_cache.text_6').format(load_selection(selection)['strategy_hash'][:16])
            except (ValueError, KeyError): strategy = ui_text('ui.load_market_cache.text_7')
        self.market.set_trading_status(strategy=strategy)
        if (self.root / 'paper.sqlite3').exists() and (self.root / 'paper_policy.json').exists():
            try:
                from quantlab.paper import PaperBroker
                self._show_account(PaperBroker.read_snapshot(self.root / 'paper.sqlite3'), strategy=strategy)
            except Exception:
                self.market.set_trading_status(strategy=strategy, paper=ui_text('ui.load_market_cache.text_8'), risk=ui_text('ui.load_market_cache.text_9'))
                self.market.set_account_tables()

    def _show_account(self, account, strategy=None):
        values = {k: account.get(k) for k in ('account_id','cash','reconciliation_required')}
        if not account.get('account_id'): values['cash'] = None
        values.update({ui_text('ui._show_account.text_1'):len(account.get('positions', {})),
                       ui_text('ui._show_account.text_2'):len(account.get('orders', {})),
                       ui_text('ui._show_account.text_3'):len(account.get('fills', {})),
                       ui_text('ui._show_account.text_4'):account.get('positions', {})})
        reason = None
        marker = self.root / 'paper_stop_display.json'
        try:
            saved = read_json(marker) if marker.exists() else {}
            if saved.get('account_hash') == content_hash(account): reason = saved.get('reason')
        except (OSError, ValueError): pass
        stop_text, color = stop_presentation(account, reason)
        values[ui_text('ui._show_account.text_5')] = stop_text
        self.paper_card.set_values(values)
        set_status(self.paper_card.label, status_for_color(color))
        positions = [{'contract_id': key, 'quantity': value} for key, value in account.get('positions', {}).items()]
        orders = []
        for key, value in account.get('orders', {}).items():
            row = {**value.get('intent', {}), **value, 'order_id': key}
            if 'quantity' in row and 'contract_id' in row: orders.append(row)
        fills = []
        for key, value in account.get('fills', {}).items():
            intent = account.get('orders', {}).get(value.get('order_id'), {}).get('intent', {})
            fills.append({**intent, **value, 'fill_id': key})
        self.market.set_account_tables(positions=positions, orders=orders, fills=fills)
        if strategy is None:
            selection = self.root / 'selection.json'
            strategy = (ui_text('ui._show_account.text_6').format(load_selection(selection)['strategy_hash'][:16])) if selection.exists() else ui_text('ui._show_account.text_7')
        self.market.set_trading_status(strategy=strategy,
            paper=(ui_text('ui._show_account.text_8').format(str(account['account_id']))) if account.get('account_id') else ui_text('ui._show_account.text_9'),
            risk=stop_text)

    def _remember_stop(self, account, reason):
        write_json(self.root / 'paper_stop_display.json', {'account_hash':content_hash(account), 'reason':reason})

    def refresh_views(self):
        self._refresh_walk_forward_references()
        self._refresh_analysis_saved()
        path = self.root / 'dataset.json'
        data = None
        if path.exists():
            try:
                data = load_dataset(path)
                self.overview.setText(ui_text('ui.refresh_views.text_1').format(display_status(data.manifest['source_type']), len(data.bars)))
                self.data_card.setText(ui_text('ui.refresh_views.text_3').format(display_status(data.manifest['source_type']), ui_text('ui.refresh_views.text_2').format(len(data.bars))))
                self.data_detail.setPlainText(canonical_json({'manifest':data.manifest, 'quality':data.quality}))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.overview.setText(error_message(exception_code(exc)))
        else:
            self.overview.setText(ui_text('ui.refresh_views.text_4'))
        stamp = content_hash(to_dict(data.manifest)) if data is not None else None
        if stamp != self._wf_source_stamp:
            first_source = self._wf_source_stamp is None
            self._wf_source_stamp = stamp
            if data is not None and first_source:
                self.walk_forward_form.defaults_for_bars(len(data.bars))
            self._invalidate_walk_forward_preview()
        self._dataset_ready = data is not None
        self.load_market_cache()
        if data is not None and self._campaign_data_hash != data.manifest['data_hash']:
            from quantlab.research import demo_campaign_config
            self.campaign_form.from_payload(to_dict(demo_campaign_config(data, demo_config())))
            self._campaign_data_hash = data.manifest['data_hash']
        self.run_button.setEnabled(data is not None and not self.jobs.active)
        old = self.result_choice.currentData()
        active = self.root / 'active_result.json'
        if self.last_operation == 'ui_backtest' and active.exists():
            digest = read_json(active).get('result_hash', '')
            if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest): old = str(self.root / 'reports' / digest / 'result.json')
        self.result_choice.blockSignals(True); self.result_choice.clear(); self.comparison_list.clear()
        names = {}
        for result_path in sorted((self.root / 'reports').glob('*/result.json')):
            try:
                label = result_name(load_result(result_path), result_path.stat().st_ctime)
            except (ValueError, KeyError, TypeError, OSError):
                label = ui_text('ui.refresh_views.text_5')
            names[label] = names.get(label, 0) + 1
            if names[label] > 1: label += ui_text('ui.refresh_views.text_6').format(names[label])
            self.result_choice.addItem(label, str(result_path))
            self.result_choice.setItemData(self.result_choice.count()-1, result_path.parent.name, Qt.ItemDataRole.ToolTipRole)
            self.comparison_list.addItem(label); self.comparison_list.item(self.comparison_list.count()-1).setData(Qt.ItemDataRole.UserRole, str(result_path))
            self.comparison_list.item(self.comparison_list.count()-1).setToolTip(result_path.parent.name)
        index = self.result_choice.findData(old)
        if index >= 0: self.result_choice.setCurrentIndex(index)
        self.result_choice.blockSignals(False); self.show_result()
        selection = self.root / 'selection.json'
        self.selection_status.setText(ui_text('ui.refresh_views.text_7') if selection.exists() else ui_text('ui.refresh_views.text_8'))
        self.selection_status.setToolTip(load_selection(selection)['strategy_hash'] if selection.exists() else '')
        policy = self.root / 'paper_policy.json'
        if policy.exists():
            policy_value = read_json(policy); self.paper_policy.setPlainText(canonical_json(policy_value))
            self.policy_form.from_payload(policy_value); self._remember(self.paper_policy)
        history = []
        for p in sorted((self.root / 'campaigns').glob('*/*.json'))[:100]:
            history.append({'file':str(p), 'content':read_json(p)})
        self.history.setPlainText(canonical_json(history) if history else ui_text('ui.refresh_views.text_9'))
        self.history_table.set_rows([{'family': a.get('family'), 'sequence': a.get('sequence'), 'status': a.get('status'), 'strategy_hash': a.get('strategy_hash')} for entry in history for a in entry['content'].get('attempts', [])])
        self.evaluation_table.set_rows([{ui_text('ui.refresh_views.text_10'): split, 'status': row.get('status'), 'strategy_hash': row.get('strategy_hash'), **row.get('metrics', {})} for entry in history for split, rows in entry['content'].get('evaluations', {}).items() for row in rows])
        selected_analysis=[item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        self.analysis_candidates.blockSignals(True);self.analysis_candidates.clear()
        selected_ref = self.candidate_choice.currentData()
        self.candidate_choice.blockSignals(True); self.candidate_choice.clear()
        for entry in history:
            state = entry['content']
            if not isinstance(state, dict): continue
            for attempt in state.get('attempts', []):
                ref = {'campaign_folder':Path(entry['file']).parent.name, 'attempt_id':attempt.get('attempt_id'), 'strategy_hash':attempt.get('strategy_hash')}
                label = f"{state.get('campaign_id','')[:10]} · {display_status(attempt.get('family','?'))} · v{attempt.get('sequence','?')} · {display_status(attempt.get('status','?'))}"
                self.candidate_choice.addItem(label, ref)
                if attempt.get('status')=='evaluated' and Path(entry['file']).name=='campaign.json':
                    family=attempt.get('spec',{}).get('family',attempt.get('family',ui_text('ui.refresh_views.text_11')))
                    family={'trend':ui_text('ui.refresh_views.text_12'),'mean_reversion':ui_text('ui.refresh_views.text_13'),'breakout':ui_text('ui.refresh_views.text_14'),'momentum':ui_text('ui.refresh_views.text_15'),'volatility':ui_text('ui.refresh_views.text_16')}.get(family,family)
                    self.analysis_candidates.addItem(ui_text('ui.refresh_views.text_17').format(state.get('campaign_id','')[:10], family, str(attempt.get('strategy_hash',''))[:12]))
                    item=self.analysis_candidates.item(self.analysis_candidates.count()-1);item.setData(Qt.ItemDataRole.UserRole,ref)
                    item.setSelected(ref in selected_analysis)
        index = self.candidate_choice.findData(selected_ref)
        if index >= 0: self.candidate_choice.setCurrentIndex(index)
        self.candidate_choice.blockSignals(False); self.inspect_candidate()
        self.analysis_candidates.blockSignals(False)
        active_candidate = self.root / 'active_candidate.json'
        if self.active_candidate is None and active_candidate.exists():
            reference = read_json(active_candidate)
            index = self.candidate_choice.findData(reference)
            if index >= 0:
                self.candidate_choice.setCurrentIndex(index); self.use_candidate()
        self._refresh_recovery_controls(force=True)

    def show_result(self, index=None):
        self.market.chart.set_reference_lines(())
        path = self.result_choice.currentData()
        self._selection_allowed = False
        if not path: self.plot.set_values([]); self.result_detail.setPlainText(ui_text('ui.show_result.text_1')); return
        try:
            result = load_result(path)
            self.plot.set_values(result.equity)
            self.result_card.set_values(dict(result.metrics))
            self.fills_table.set_rows([to_dict(x) for x in result.fills])
            self.bind_result_layers(result)
            self._selection_allowed = True
            reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
            if reference:
                _, provenance = candidate_record(self.root, reference)
                self._selection_allowed = provenance['paper_qualified']
            self.select_button.setEnabled(self._selection_allowed and not self.jobs.active)
            self.result_detail.setPlainText(canonical_json({'metrics':result.metrics, 'warnings':result.warnings, 'manifest':result.manifest, 'fills':result.fills, 'rejects':result.rejects}))
        except Exception as exc: self.status.setText(error_message(exception_code(exc)))

    def bind_result_layers(self, result=None):
        """Only exact source, strategy and chart identities may carry result layers."""
        from desktop_charts import ChartTrace, ChartMarker
        chart = self.market.chart
        bars = chart.bars
        old_overlays, old_panes, styles = dict(chart.overlays), dict(chart.panes), dict(chart.pane_styles)
        source, status = chart.source_label, chart.status_label
        chart.set_series(bars, source_label=source, status_label=status)
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        path = self.result_choice.currentData() if hasattr(self, 'result_choice') else None
        if not bars or not path or not (self.root / 'dataset.json').exists(): return
        result = result or load_result(path)
        data = load_dataset(self.root / 'dataset.json')
        from quantlab.reporting import validate_result_payload
        try:
            # Use the report loader's authoritative full dataset/provenance binding.
            validate_result_payload(to_dict(result), dataset=data)
        except (ValidationError, KeyError, TypeError, ValueError):
            return
        # Require the exact adapted market source, not merely matching price/date.
        selected = self.market.contract_combo.currentData()
        item = self.market.selected_series()
        if item is None or self._market_data_bindings.get(selected) != data.manifest['data_hash']: return
        if item != self._market_research_series.get(selected): return
        trace = ChartTrace(selected, content_hash(bars), result.manifest['spec_hash'], ui_text('ui.bind_result_layers.text_1'))
        markers = []
        from bisect import bisect_left, bisect_right
        timed = [(i,b) for i,b in enumerate(bars) if b.timestamp is not None and b.end is not None]
        starts, ends = [b.timestamp for _,b in timed], [b.end for _,b in timed]
        def event_index(timestamp, at_close):
            position = bisect_left(ends, timestamp) if at_close else bisect_right(starts, timestamp)-1
            if not 0 <= position < len(timed): return None
            i, bar = timed[position]
            return i if (bar.timestamp < timestamp <= bar.end if at_close else bar.timestamp <= timestamp < bar.end) else None
        for signal in result.signals:
            if signal.contract_id != selected: continue
            index = event_index(signal.timestamp, True)
            if index is not None:
                markers.append(ChartMarker(index, 'signal', ui_text('ui.bind_result_layers.text_2').format(str(signal.target_position)),
                    reason=signal.reason, timestamp=signal.timestamp, target_position=signal.target_position))
        for fill in result.fills:
            if fill.contract_id != selected: continue
            # Core timestamps are event availability; never infer intrabar execution time.
            index = event_index(fill.timestamp, fill.reason in ('stop', 'target'))
            if index is not None:
                markers.append(ChartMarker(index, 'fill', ui_text('ui.bind_result_layers.text_3') if fill.side == 'buy' else ui_text('ui.bind_result_layers.text_4'),
                    price=fill.price, quantity=fill.quantity, cost=fill.commission+fill.tax,
                    reason=fill.reason, timestamp=fill.timestamp))
        chart.set_series(bars, trace=trace, source_label=source, status_label=ui_text('ui.bind_result_layers.text_5').format(status))
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        chart.set_markers(markers, trace=trace)
        chart.set_reference_lines(self._result_snapshot_lines(result, bars, selected), trace=trace)

    @staticmethod
    def _result_snapshot_lines(result, bars, selected):
        """Read the final actual open-lot snapshot, never derive a fill from a signal.

        Range endpoints preserve the existing whole-position conservative policy:
        every original-entry lot can trigger; the most adverse triggered level
        wins (with existing gap handling). An average-price stop is not that rule.
        No line is projected back through historical candles or beyond this event.
        """
        from desktop_charts import ReferenceLine
        from decimal import Context, InvalidOperation, ROUND_HALF_EVEN, localcontext
        if not result.equity: return ()
        row = result.equity[-1]
        lots = result.metrics.get('open_lots', ())
        position = result.metrics.get('open_position')
        if not lots or type(position) is not int or not position: return ()
        if row.get('contract_id') != selected or row.get('position') != position: return ()
        def timestamp(value):
            return datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        try:
            as_of = timestamp(row['timestamp'])
            indices = [i for i,bar in enumerate(bars) if bar.contract_id==selected and bar.end==as_of]
            if len(indices)!=1: return ()  # No nearest-time or date-only guess.
            side = 1 if position>0 else -1
            fills = {fill.fill_id: fill for fill in result.fills}
            if len(fills)!=len(result.fills) or any(fill.timestamp>as_of for fill in result.fills): return ()
            opening = {fid: fill for fid,fill in fills.items() if fill.reason in ('target_open','roll_open')}
            remaining = {fid: fill.quantity for fid,fill in opening.items()}
            exit_quantities = {}
            configuration = result.manifest['config']
            configured = {content_hash(event): event for event in configuration['settlement_events']}
            applied = {}
            available = {(timestamp(event['timestamp']),event['contract_id']) for event in result.equity}
            for settlement in result.metrics['settlements']:
                event = settlement['event']
                event_id = content_hash(event)
                if (event_id not in configured or settlement['event_id']!=event_id or event_id in applied
                        or settlement['kind']!=event.get('kind','daily')
                        or timestamp(event['timestamp'])>as_of
                        or (timestamp(event['timestamp']),event['contract_id']) not in available): return ()
                applied[event_id] = event
            with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
                # Reconcile full opening quantities against every closed FIFO match.
                # Several residual fragments may legitimately refer to one opening fill.
                for match in result.ledger:
                    fill = opening.get(match['entry_fill_id'])
                    quantity = match['quantity']
                    if (fill is None or type(quantity) is not int or quantity<=0
                            or match['contract_id']!=fill.contract_id
                            or match['side']!=('long' if fill.side=='buy' else 'short')
                            or Decimal(str(match['entry_price']))!=fill.price
                            or timestamp(match['entry_timestamp'])!=fill.timestamp
                            or not fill.timestamp<=timestamp(match['exit_timestamp'])<=as_of): return ()
                    exit_id = match['exit_fill_id']
                    if exit_id is not None:
                        exit_fill = fills.get(exit_id)
                        if (exit_fill is None or exit_id in opening or exit_fill.contract_id!=fill.contract_id
                                or exit_fill.side==fill.side or exit_fill.timestamp!=timestamp(match['exit_timestamp'])
                                or exit_fill.price!=Decimal(str(match['exit_price']))): return ()
                        exit_quantities[exit_id] = exit_quantities.get(exit_id,0)+quantity
                    else:
                        event = applied.get(match['exit_event_id'])
                        if (event is None or event.get('kind')!='final' or match['exit_event_type']!='final_settlement'
                                or event['contract_id']!=fill.contract_id
                                or timestamp(event['timestamp'])!=timestamp(match['exit_timestamp'])
                                or Decimal(str(event['price']))!=Decimal(str(match['exit_price']))): return ()
                    remaining[fill.fill_id] -= quantity
                    if remaining[fill.fill_id]<0: return ()
                if any(exit_quantities.get(fid,0)!=fill.quantity for fid,fill in fills.items() if fid not in opening): return ()
                expected = {fid: quantity for fid,quantity in remaining.items() if quantity}
                entries, bases, quantities, observed = [], [], [], {}
                for lot in lots:
                    quantity = lot['quantity']
                    entry, basis = Decimal(str(lot['price'])), Decimal(str(lot['basis_price']))
                    if type(quantity) is not int or quantity<=0 or lot['side']!=side or lot['contract_id']!=selected: return ()
                    if not entry.is_finite() or not basis.is_finite() or min(entry,basis)<=0: return ()
                    fill = opening.get(lot['fill_id'])
                    if (fill is None or fill.contract_id!=selected or fill.price!=entry
                            or fill.side!=('buy' if side>0 else 'sell') or quantity>fill.quantity
                            or timestamp(lot['timestamp'])!=fill.timestamp or fill.timestamp>as_of): return ()
                    observed[fill.fill_id] = observed.get(fill.fill_id,0)+quantity
                    expected_basis = entry
                    # Settlement at the opening timestamp belongs to the prior bar,
                    # before this next-open fill, so the boundary is strictly greater.
                    events = sorted((event for event in configured.values()
                                     if event['contract_id']==selected and fill.timestamp<timestamp(event['timestamp'])<=as_of),
                                    key=lambda event: timestamp(event['timestamp']))
                    for event in events:
                        if (content_hash(event) not in applied or event.get('kind','daily')!='daily'
                                or configuration['settlement_mode']!='daily_mtm'): return ()
                        expected_basis = Decimal(str(event['price']))
                    if basis!=expected_basis: return ()
                    entries.append(entry); bases.append(basis); quantities.append(quantity)
                if observed!=expected or sum(quantities)!=abs(position): return ()
                index = indices[0]
                lines = [ReferenceLine(ui_text('ui._result_snapshot_lines.text_1'),sum((p*q for p,q in zip(entries,quantities)),Decimal(0))/abs(position),index,as_of),
                         ReferenceLine(ui_text('ui._result_snapshot_lines.text_2'),sum((p*q for p,q in zip(bases,quantities)),Decimal(0))/abs(position),index,as_of)]
                if result.manifest.get('protective_scope')=='whole position at most adverse triggered original-entry lot level':
                    parameters = result.manifest['strategy']['parameters']
                    for key,label,direction in (('stop_ticks',ui_text('ui._result_snapshot_lines.text_3'),-side),('target_ticks',ui_text('ui._result_snapshot_lines.text_4'),side)):
                        if key not in parameters: continue
                        offset = parameters[key]
                        if type(offset) is not int or offset<=0: return ()
                        levels = [price+direction*offset for price in entries]
                        lower, upper = min(levels),max(levels)
                        lines.append(ReferenceLine(label+(ui_text('ui._result_snapshot_lines.text_5') if lower!=upper else ''),lower,index,as_of))
                        if lower!=upper: lines.append(ReferenceLine(ui_text('ui._result_snapshot_lines.text_6').format(label),upper,index,as_of))
                return tuple(lines)
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return ()  # Legacy/incomplete snapshots do not invent reference prices.

    def inspect_candidate(self, index=None):
        self._candidate_valid = False
        reference = self.candidate_choice.currentData()
        if not reference:
            self.candidate_detail.setPlainText(ui_text('ui.inspect_candidate.text_1'))
        else:
            try:
                spec, provenance = candidate_record(self.root, reference)
                self.candidate_detail.setPlainText(canonical_json({'strategy':spec, **provenance}))
                self.candidate_card.set_values({ui_text('ui.inspect_candidate.text_2'): spec.strategy_id, ui_text('ui.inspect_candidate.text_3'): provenance['paper_qualified'], ui_text('ui.inspect_candidate.text_4'): provenance['evaluations']})
                self._candidate_valid = True
            except Exception:
                self.candidate_detail.setPlainText(ui_text('ui.inspect_candidate.text_5'))
        self.use_candidate_button.setEnabled(self._candidate_valid and not self.jobs.active)

    def use_candidate(self):
        reference = self.candidate_choice.currentData()
        spec, provenance = candidate_record(self.root, reference)
        self.family.setCurrentText(spec.family)
        self.active_candidate = reference
        write_json(self.root / 'active_candidate.json', reference)
        self.parameters.setPlainText(canonical_json(spec.parameters)); self.parameters.setReadOnly(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy':spec, **provenance}))
        self.strategy_form.setEnabled(False)
        self.batch.setChecked(False)
        self.form_feedback(self.strategy_form, ui_text('ui.use_candidate.text_1'))

    def use_builtin(self):
        self._family_changed()
        self.form_feedback(self.strategy_form, ui_text('ui.use_builtin.text_1'))

    def save_settings(self):
        if self.settings is None: raise ValidationError(ui_text('ui.save_settings.text_1'))
        value = self.settings.load()
        # Preserve legacy provider settings as inert historical data. They are
        # never read into executable provider options or overwritten on save.
        value.update({'persist_logs':self.persist_logs.isChecked(),
                      'local_notifications':self.local_notifications.isChecked()})
        value['market'] = self.market.preferences()
        value['window'] = {'x': self.x(), 'y': self.y(), 'width': self.width(), 'height': self.height()}
        self.settings.save(value)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.chatgpt_panel.consent.setChecked(False)
        self.status.setText(ui_text('ui.save_settings.text_2'))

    def load_settings(self):
        if self.settings is None: return
        value = self.settings.load()
        self._restoring_sections = True
        for key, toggle in self._section_toggles.items():
            toggle.blockSignals(True); toggle.setChecked(value.get('advanced_sections', {}).get(key) is True); toggle.blockSignals(False)
            # Visibility must follow restored state even while signals are blocked.
            toggle.toggled.emit(toggle.isChecked())
        self._restoring_sections = False
        self.persist_logs.setChecked(value.get('persist_logs', True) is True)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.local_notifications.setChecked(value.get('local_notifications', True) is True)
        try:
            if 'market' in value: self.market.restore_preferences(value['market'])
            size = value.get('window', {})
            x, y = int(size.get('x', self.x())), int(size.get('y', self.y()))
            available = [screen.availableGeometry() for screen in QApplication.screens()]
            screen = next((rect for rect in available if rect.contains(x, y)), self.screen().availableGeometry())
            self.resize(min(max(int(size.get('width', self.width())), 800), screen.width()), min(max(int(size.get('height', self.height())), 600), screen.height()))
            self.move(max(screen.left(), min(x, screen.right()-self.width()+1)), max(screen.top(), min(y, screen.bottom()-self.height()+1)))
        except (ValueError, TypeError, KeyError, OverflowError):
            self.status.setText(ui_text('ui.load_settings.text_1'))
        self.read_logs()

    def configure_workspace(self):
        self.chatgpt_panel.abandon_primary_sign_in()
        from quantlab.desktop_runtime import WorkspaceLocator
        if self.jobs.active: raise ValidationError(ui_text('ui.configure_workspace.text_1'))
        self.chatgpt_panel.consent.setChecked(False)
        self._invalidate_analysis_preview()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        root = WorkspaceLocator(getattr(self.paths, 'bootstrap', None) or self.paths.root).configure(Path(self.workspace_path.text().strip()))
        self.status.setText(ui_text('ui.configure_workspace.text_2').format(str(root)))

    def open_releases(self):
        # Verified repository Releases destination; never invent latest version or assets.
        if not QDesktopServices.openUrl(QUrl('https://github.com/yostar77612/mark-auto/releases')):
            raise ValidationError(ui_text('ui.open_releases.text_1'))
        self.status.setText(ui_text('ui.open_releases.text_2'))

    def notify_local(self, message, *, error=False, completion=False):
        from html import escape
        if not completion and not self.local_notifications.isChecked(): return
        self.notification_timer.stop()
        self.notification_fade.stop(); self.notification_opacity.setOpacity(1.0)
        self._notification_operation = self.last_operation
        self.notification.setText(ui_text('ui.notify_local.text_1').format(escape(message)))
        set_status(self.notification, 'danger' if error else 'neutral')
        self.notification.show()
        if not error: self.notification_timer.start(5000)
        if self.local_notifications.isChecked(): QApplication.alert(self, 1500)

    def _notification_link(self, link):
        if link == 'close':
            self.notification_timer.stop(); self.notification_fade.stop(); self.notification.hide(); return
        operation = self._notification_operation or ''
        page = 5 if operation.startswith('ui_paper_') else 3 if operation == 'ui_backtest' else 4 if operation in ('ui_compare', 'ui_select', 'ui_disable') else 2 if operation.startswith(('ui_analysis_', 'ui_walk_forward_')) or operation == 'ui_campaign' else 6 if operation.startswith(('ui_backup_', 'ui_chatgpt_')) else 1
        self.navigation.setCurrentRow(page)
        target = self.paper_card if page == 5 else self.result_card if page == 3 and hasattr(self, 'result_card') else self.stack.widget(page).widget()
        self.stack.widget(page).ensureWidgetVisible(target)

    def record_event(self, operation, kind):
        from quantlab.desktop_runtime import RedactedEventLog
        # Runtime owns redacted persistence; UI never appends the same event twice.
        self.log_view.appendPlainText((operation if operation in UI_OPERATIONS else 'background') + ' · ' + (kind if kind in ('progress','result','error','cancelled') else 'status'))

    def read_logs(self):
        from quantlab.desktop_runtime import RedactedEventLog
        self.log_view.setPlainText('\n'.join(RedactedEventLog(self.paths.logs / 'desktop-events.jsonl').tail()))

    def backup(self, restore):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.backups is None: raise ValidationError(ui_text('ui.backup.text_1'))
        if not self.backup_path.text().strip(): raise ValidationError(ui_text('ui.backup.text_2'))
        if restore and not self.restore_confirm.isChecked(): raise ValidationError(ui_text('ui.backup.text_3'))
        if self.jobs.active: raise ValidationError(ui_text('ui.backup.text_4'))
        self.start_job('ui_backup_restore' if restore else 'ui_backup_create', {'path':self.backup_path.text()})
        self.restore_confirm.setChecked(False)

    def _quiesce_and_recover(self, *, preserve_primary_sign_in=False):
        if not preserve_primary_sign_in:
            self.chatgpt_panel.abandon_primary_sign_in()
        # Never create state files until the writer has exited and pending swaps recover.
        if self.jobs.active: self.jobs.cancel()
        if self.jobs.active: raise ValidationError(ui_text('ui._quiesce_and_recover.text_1'))
        from quantlab.analysis_recovery import admission, inspect_recovery, recover_control_journal, RecoveryError
        with admission(self.paths) as token:
            try:
                recover_control_journal(self.paths,admission=token)
                disposition=inspect_recovery(self.paths)
            except RecoveryError:
                disposition=None
            if disposition is None or disposition.unresolved:
                if (not self.paths.state.is_dir() or any(path.exists() or path.is_symlink() for path in (
                    self.paths.root/'state-v1.rollback',self.paths.root/'restore-transaction.json',
                    self.paths.state/'.restore-transaction'))):
                    raise RecoveryError(ui_text('ui._quiesce_and_recover.text_2'))
                return  # Intact analysis-only state; allow independent bookkeeping/close.
            if self.backups is not None:
                self.backups.recover()
            else:
                from quantlab.desktop_runtime import BackupManager
                BackupManager(self.paths).recover()

    def freeze_paper(self, reason):
        self._quiesce_and_recover()
        self.chatgpt_panel.consent.setChecked(False)
        self._pending_usage_refresh = False
        if self._chatgpt_job_request:
            self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
            self._chatgpt_job_request = None
        self.chatgpt_controller.account_status_known = False
        self.chatgpt_controller.invalidate_campaign_usage()
        self.paper_confirm.setChecked(False)
        if self.guard is not None: self.guard.reconciliation_required = True
        write_json(self.root / 'desktop_safety.json', {'reconciliation_required':True, 'reason':str(reason)})
        if (self.root / 'paper_policy.json').exists():
            broker = _paper(self.root)
            broker.set_kill_switch(True)
            self._remember_stop(broker.snapshot(), 'user' if ui_text('ui.freeze_paper.text_1') in str(reason) else 'freeze')
            self._show_account(broker.snapshot())
        self.status.setText(ui_text('ui.freeze_paper.text_2').format(str(reason)))

    def closeEvent(self, event):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active and QMessageBox.question(self, ui_text('ui.closeEvent.text_1'), ui_text('ui.closeEvent.text_2'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        try:
            self._closing = True
            self.chatgpt_controller.set_host_available(False)
            self.chatgpt_panel.consent.setChecked(False)
            self.jobs.close()
            self._quiesce_and_recover()
            if (self.last_operation == 'ui_walk_forward_run' or self._wf_pending_reconcile) and self._wf_launch is not None:
                self._wf_pending_reconcile = False
                self.jobs.poll()
                self.start_job('ui_walk_forward_reconcile', self._wf_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if (self._analysis_running or self._pending_analysis_reconcile) and self._analysis_launch is not None:
                self._analysis_running=False;self._pending_analysis_reconcile=False
                self.jobs.poll()
                self.start_job('ui_analysis_reconcile',dict(self._analysis_launch))
                self._close_after_reconcile=True
                event.ignore();return
            if (self._subscription_campaign or self._pending_plan_reconcile) and self._plan_launch is not None:
                self._subscription_campaign = False
                self._pending_plan_reconcile = False
                self.jobs.poll()  # joined old terminal packets cannot own the new worker
                self.start_job('ui_chatgpt_reconcile', self._plan_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if self._chatgpt_job_request:
                self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request = None
            if self.guard is not None: self.guard.finish()
        except Exception:
            self._closing = False
            self.chatgpt_controller.set_host_available(True)
            event.ignore(); self.status.setText(ui_text('ui.closeEvent.text_3')); return
        self._safe(self.save_market_preferences)
        self.chatgpt_controller.set_host_available(False)
        self.timer.stop(); event.accept()


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    return MainWindow(paths, jobs, settings, backups, guard)
