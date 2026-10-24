"""Native Traditional Chinese Qt workspace. No web server or live execution imports.

The GUI only schedules work. execute_ui_operation runs in the runtime's isolated
worker process; its inputs are data, never executable strategy source.
"""

from desktop_theme import apply_theme, set_status, set_theme_property, status_for_color
from desktop_strings import ui_text
from desktop_presentation import research_controls, _dataset
from pathlib import Path
from quantlab.desktop_errors import error_message, exception_code
from quantlab.desktop_feedback import completion_summary, stop_presentation
import json
from datetime import datetime
from decimal import Decimal

from quantlab.core import Dataset, StrategySpec, Instrument, ValidationError, canonical_json, content_hash, to_dict
from quantlab.windows_paths import canonical_path as _canonical_path, native_path as _native_path, sqlite_uri as _sqlite_uri
from quantlab.reporting import (
    read_json,
    write_json,
    load_dataset,
    save_dataset,
    synthetic_dataset,
    demo_config,
    export_report,
    load_result,
    comparison_rows,
    save_selection,
    load_selection,
    saved_analysis_entries,
)

UI_OPERATIONS = frozenset(
    'ui_' + op
    for op in (
        'analysis_preview',
        'analysis_run',
        'analysis_read',
        'analysis_reconcile',
        'walk_forward_preview',
        'walk_forward_run',
        'walk_forward_read',
        'walk_forward_reconcile',
        'demo',
        'import',
        'refresh',
        'market_refresh',
        'chatgpt_auth',
        'chatgpt_usage',
        'chatgpt_reconcile',
        'backtest',
        'campaign',
        'compare',
        'select',
        'disable',
        'paper_snapshot',
        'paper_reconcile',
        'paper_kill',
        'paper_replay',
        'paper_submit',
        'paper_cancel',
        'paper_cancel_all',
        'capital_scenario',
        'idea_research',
        'idea_adopt',
        'backup_create',
        'backup_restore',
    )
)


def provider_binding_options(options):
    # Preserve historical provider identities; these options cannot enable a removed provider.
    return {
        key: value
        for key, value in options.items()
        if key != 'network_opt_in' and not (options.get('mode') == 'local' and key == 'owner') and not (key == 'output_mode' and value == 'json_object')
    }


def campaign_generator(paths, options):
    """Only explicit deterministic fixtures use this non-subscription adapter."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import FixtureGenerator

    if not isinstance(options, dict) or options != {'mode': 'fixture'}:
        raise ValidationError(ui_text('ui.campaign_generator.subscription_only'))
    research_controls(paths)
    return FixtureGenerator()


def connection_event_from_payload(payload):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_ui import ConnectionEvent, TestConnectionEvent, ReconciliationEvent

    if not isinstance(payload, dict):
        raise ValidationError(ui_text('ui.connection_event_from_payload.invalid_event_format'))
    value = dict(payload)
    value['registrations'] = tuple(tuple(row) for row in value.get('registrations', ()))
    value['models'] = tuple(value.get('models', ()))
    if value.get('test_usage') is not None:
        value['test_usage'] = tuple(value['test_usage'])
    for key in ('model_labels', 'account_labels'):
        if key in value:
            value[key] = tuple(tuple(row) for row in value[key])
    if 'reconciliation_action' in value:
        for key in ('inspection', 'account_status'):
            if value.get(key) is not None:
                value[key] = tuple(value[key])
        return ReconciliationEvent(**value)
    if 'test_usage' in value:
        return TestConnectionEvent(**value)
    return ConnectionEvent(**value)


def plan_provider(paths, data, config, options, *, for_usage=False):
    """Fixed bootstrap/control identity, never workspace-relative or random."""
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import ChatGPTPlanProvider

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_ui import SubscriptionOptions

    # Keep operation-specific dependencies out of module startup.
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
        raise ValidationError(ui_text('ui.plan_provider.unsupported_settings'))
    raw = {key: value for key, value in options.items() if key != 'expected_binding'}
    if for_usage:
        if raw.get('network_opt_in') is not False or raw.get('included_usage_policy_confirmed') is not False:
            raise ValidationError(ui_text('ui.plan_provider.reconciliation_not_authorization'))
        validation = {**raw, 'network_opt_in': True, 'included_usage_policy_confirmed': True}
    else:
        validation = raw
    parsed = SubscriptionOptions(**validation)
    public = {key: value for key, value in asdict(parsed).items() if key not in ('network_opt_in', 'included_usage_policy_confirmed')}
    # Keep operation-specific dependencies out of module startup.
    import hashlib

    source_root = Path(__file__).parent
    source_files = (
        'desktop_chatgpt_auth.py',
        'desktop_chatgpt_provider.py',
        'quantlab/core.py',
        'quantlab/backtest.py',
        'quantlab/research.py',
        'quantlab/strategies.py',
        'desktop_chatgpt_dependency_manifest.json',
    )
    sources = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in source_files}
    identity = content_hash({'data_hash': data.manifest['data_hash'], 'config': config, 'provider': public, 'implementation_sources': sources})
    if not for_usage and options.get('expected_binding') != identity:
        raise ValidationError(ui_text('ui.plan_provider.request_binding_changed'))
    controls = research_controls(paths)
    reference = OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), parsed.registration)
    provider = ChatGPTPlanProvider(
        model=parsed.model,
        credential_reference=reference,
        budget_path=controls / ('chatgpt-plan-' + identity + '.sqlite3'),
        campaign_id=identity,
        network_opt_in=not for_usage,
        included_usage_policy_confirmed=not for_usage,
        max_calls=parsed.max_calls,
        timeout_seconds=parsed.timeout_seconds,
    )
    return provider, identity


def candidate_record(root, reference):
    """Resolve a persisted, hash-bound DSL candidate and independent evaluation gate."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import validate_dsl

    campaigns = _native_path(Path(root) / 'campaigns').resolve()
    folder = str(reference.get('campaign_folder', ''))
    if len(folder) != 64 or any(c not in '0123456789abcdef' for c in folder):
        raise ValidationError(ui_text('ui.candidate_record.invalid_version_id'))
    path = _native_path(campaigns / folder / 'campaign.json')
    if not _canonical_path(path.resolve()).is_relative_to(_canonical_path(campaigns)):
        raise ValidationError(ui_text('ui.candidate_record.invalid_version_path'))
    state = read_json(path)
    # JSON is a review export; qualify only if it equals the authoritative journal.
    import sqlite3

    # Keep operation-specific dependencies out of module startup.
    from contextlib import closing

    journal = path.with_name('campaign.sqlite3')
    if not _canonical_path(journal.resolve()).is_relative_to(_canonical_path(campaigns)) or not journal.is_file():
        raise ValidationError(ui_text('ui.candidate_record.transaction_missing'))
    with closing(sqlite3.connect(_sqlite_uri(journal.resolve()) + '?mode=ro', uri=True, timeout=1)) as database:
        row = database.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if not row or canonical_json(json.loads(row[0])) != canonical_json(state):
        raise ValidationError(ui_text('ui.candidate_record.export_transaction_mismatch'))
    if state.get('selection_hash') != content_hash(state.get('selected', [])):
        raise ValidationError(ui_text('ui.candidate_record.selection_hash_mismatch'))
    if state.get('campaign_id') != content_hash(state.get('binding')):
        raise ValidationError(ui_text('ui.candidate_record.version_hash_mismatch'))
    attempt = next((a for a in state.get('attempts', []) if a.get('attempt_id') == reference.get('attempt_id')), None)
    if not attempt or attempt.get('status') != 'evaluated':
        raise ValidationError(ui_text('ui.candidate_record.evaluation_required'))
    spec = validate_dsl(attempt.get('spec'))
    digest = content_hash(spec)
    if digest != attempt.get('strategy_hash') or digest != reference.get('strategy_hash'):
        raise ValidationError(ui_text('ui.candidate_record.strategy_hash_mismatch'))
    ranking = state['binding']['config']['ranking']
    selected = any(x.get('strategy_hash') == digest for x in state.get('selected', []))
    qualified = selected and state.get('status') == 'completed'
    evaluations = {}
    for split in ('oos', 'holdout'):
        row = next((r for r in state.get('evaluations', {}).get(split, []) if r.get('strategy_hash') == digest), {})
        metrics = row.get('metrics', {})
        trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
        passed = (
            row.get('status') == 'evaluated'
            and metrics.get('net_pnl') is not None
            and Decimal(str(metrics['net_pnl'])) >= Decimal(str(ranking['minimum']))
            and trades >= ranking['min_trades']
        )
        qualified = qualified and passed
        evaluations[split] = {'qualified': passed, 'evaluation': row}
    return spec, {
        'reference': reference,
        'paper_qualified': bool(qualified),
        'evaluations': evaluations,
        'source_type': state.get('source_manifest', {}).get('source_type', 'unknown'),
        'source_data_hash': state.get('source_manifest', {}).get('data_hash'),
        'real_model_status': state.get('real_model_status', 'not_verified'),
        'note': ui_text('ui.candidate_record.synthetic_evidence_disclaimer'),
    }


def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def paper_risk_limits():
    """The same fixed enforced limits supply both brokers and the read-only UI."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.paper import RiskLimits

    return RiskLimits(1, 1, Decimal('1000'), 30)


def _paper(root):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.paper import PaperBroker

    policy = read_json(root / 'paper_policy.json')
    return PaperBroker(
        root / 'paper.sqlite3',
        instrument=Instrument(policy['contract_id']),
        costs=demo_config().costs,
        limits=paper_risk_limits(),
        risk_sessions=tuple(policy['risk_sessions']),
        margin_schedule=tuple(policy['margin_schedule']),
    )


def analysis_plan(paths, request, *, emit=None):
    # Load the optional UI adapter only when this operation is requested.
    from quantlab.desktop_runtime import validate_analysis_request

    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import build_analysis_packet, make_analysis_plan

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import implementation_provenance

    validate_analysis_request(request)
    research_controls(paths)
    if emit:
        emit('progress', message=ui_text('ui.analysis_plan.recomputing_training_evidence'))
    # Keep operation-specific dependencies out of module startup.
    from quantlab.saved_candidate_pool import load_original_dataset

    data = load_original_dataset(Path(request['original_dataset']['path']))
    packet = build_analysis_packet(
        source_campaign_dir=_root(paths) / 'campaigns' / request['campaign_reference'],
        original_dataset=data,
        attempt_ids=request['attempt_ids'],
        task=request['task'],
        max_runtime_seconds=120,
    )
    return make_analysis_plan(
        packet,
        model=request['model'],
        registration=request['registration'],
        provider_implementation=implementation_provenance(),
        timeout_seconds=request['timeout_seconds'],
    )


def analysis_provider_for(paths, plan, *, authorized=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import analysis_provider

    reference = OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), plan['binding']['registration'])
    return analysis_provider(plan, reference, network_opt_in=authorized, included_usage_policy_confirmed=authorized)


ANALYSIS_NOTICE = ui_text('ui.labels.recalculated_evidence')
ANALYSIS_WARNING = ui_text('ui.labels.unverified_ai_advice')
ANALYSIS_CHECKPOINT_STATUS = ui_text('ui.labels.interrupted_checkpoint')
ANALYSIS_CHECKPOINT_NOTICE = ui_text('ui.labels.missing_result_export').format(ANALYSIS_CHECKPOINT_STATUS)
ANALYSIS_METRICS = {
    'net_pnl': ui_text('ui.labels.net_pnl'),
    'realized_gross_pnl': ui_text('ui.labels.realized_gross_pnl'),
    'unrealized_pnl': ui_text('ui.labels.unrealized_pnl'),
    'total_costs': ui_text('ui.labels.total_cost'),
    'slippage_cost': ui_text('ui.labels.slippage_cost'),
    'return': ui_text('ui.labels.return_ratio'),
    'max_drawdown': ui_text('ui.labels.max_drawdown'),
    'max_drawdown_pct': ui_text('ui.labels.max_drawdown_ratio'),
    'trade_count': ui_text('ui.labels.trade_count'),
    'fill_count': ui_text('ui.labels.fill_count'),
    'win_rate': ui_text('ui.labels.win_rate'),
    'profit_factor': 'Profit Factor',
    'sharpe': 'Sharpe',
    'sharpe_observations': ui_text('ui.labels.sharpe_observations'),
    'sharpe_sample_count': ui_text('ui.labels.sharpe_samples'),
    'open_position': ui_text('ui.labels.open_positions'),
}
ANALYSIS_KINDS = {
    'market': ui_text('ui.labels.market_interpretation'),
    'entry_exit': ui_text('ui.labels.entry_exit_logic'),
    'backtest': ui_text('ui.labels.backtest_interpretation'),
    'weakness': ui_text('ui.labels.weaknesses'),
    'risk': ui_text('ui.labels.risk_reminders'),
    'improvement': ui_text('ui.labels.research_improvements'),
    'comparison': ui_text('ui.labels.candidate_comparison'),
}


def analysis_preview_text(plan):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import validate_analysis_plan

    validate_analysis_plan(plan)
    binding = plan['binding']
    context = binding['packet']['context']
    training = context['training']
    lines = [
        ANALYSIS_NOTICE,
        ANALYSIS_WARNING,
        ui_text('ui.analysis_preview_text.training_only_payload'),
        ui_text('ui.analysis_preview_text.request_limit').format(binding['model'], str(binding['timeout_seconds'])),
        ui_text('ui.analysis_preview_text.preview_id').format(plan['analysis_id']),
        ui_text('ui.analysis_preview_text.training_window').format(str(training['window_count']), str(training['bar_count'])),
    ]
    for row in context['strategies']:
        lines.append(
            ui_text('ui.analysis_preview_text.candidate_parameters').format(
                row['strategy_hash'], row['spec']['family'], canonical_json(row['spec']['parameters'])
            )
        )
    for row in context['evidence']:
        lines.append(
            ui_text('ui.analysis_preview_text.local_metrics').format(
                ui_text('ui.analysis_preview_text.training') if row['split'] == 'train' else ui_text('ui.analysis_preview_text.validation'),
                row['strategy_hash'][:16],
            )
        )
        lines.append(
            ui_text('ui.analysis_preview_text.metric_separator').join(
                ANALYSIS_METRICS.get(key, key) + '=' + (ui_text('ui.analysis_preview_text.unavailable') if value is None else str(value))
                for key, value in row['metrics'].items()
            )
        )
    lines.append(ui_text('ui.analysis_preview_text.evidence_hint'))
    return '\n'.join(lines)


def analysis_record_text(record):
    # read_analysis/run_analysis already enforce record and evidence bindings.
    from quantlab.research_analysis import validate_analysis_plan, validate_analysis_response

    plan = validate_analysis_plan(record['plan'])
    context = plan['binding']['packet']['context']
    lines = [
        ANALYSIS_WARNING,
        ANALYSIS_NOTICE,
        ui_text('ui.analysis_record_text.saved_id').format(plan['analysis_id']),
        ui_text('ui.analysis_record_text.status').format(
            {
                'completed': ui_text('ui.analysis_record_text.complete_not_acceptance'),
                'blocked': ui_text('ui.analysis_record_text.blocked_no_resend'),
                'running': ui_text('ui.analysis_record_text.interrupted_unknown'),
            }.get(record['status'], ui_text('ui.analysis_record_text.unknown'))
        ),
    ]
    if record['status'] != 'completed':
        return '\n'.join(lines)
    response = validate_analysis_response(record['response'], context)
    evidence = {row['evidence_id']: row for row in context['evidence']}
    training = context['training']
    for row in response['findings']:
        lines += [
            '',
            ui_text('ui.analysis_record_text.named_value').format(ANALYSIS_KINDS[row['kind']], row['text']),
            ui_text('ui.analysis_record_text.candidate').format(', '.join(value[:16] for value in row['strategy_hashes'])),
        ]
        if 'signal_parameter' in row:
            lines.append(ui_text('ui.analysis_record_text.signal_parameters').format(row['signal_parameter']))
        for ref in row['evidence_refs']:
            if ref['evidence_id'] == training['evidence_id']:
                lines.append(ui_text('ui.analysis_record_text.training_window').format(ref['field'], str(training['window_count'])))
            else:
                local = evidence[ref['evidence_id']]
                value = local['metrics'][ref['field']]
                split = ui_text('ui.analysis_record_text.parenthesized_value').format(
                    ui_text('ui.analysis_record_text.training') if local['split'] == 'train' else ui_text('ui.analysis_record_text.validation'), local['split']
                )
                lines.append(
                    ui_text('ui.analysis_record_text.candidate_metric').format(
                        local['strategy_hash'][:16],
                        split,
                        ANALYSIS_METRICS.get(ref['field'], ref['field']),
                        ui_text('ui.analysis_record_text.unavailable') if value is None else str(value),
                    )
                )
    return '\n'.join(lines)


def _prepare_paper_operation(payload, paths, root, *, emit=None, descendants_stopped=False):
    if 'policy' in payload:
        policy = payload['policy']
        existing = root / 'paper_policy.json'
        if existing.exists() and read_json(existing) != policy:
            raise ValidationError(ui_text('ui.execute_ui_operation.paper_policy_locked'))
        if not existing.exists():
            # Keep operation-specific dependencies out of module startup.
            from quantlab.paper import PaperBroker

            if not isinstance(policy, dict) or set(policy) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
                raise ValidationError(ui_text('ui.execute_ui_operation.paper_policy_fields'))
            # Keep operation-specific dependencies out of module startup.
            import tempfile

            with tempfile.TemporaryDirectory(prefix='policy-', dir=root) as staging:
                PaperBroker(
                    Path(staging) / 'validation.sqlite3',
                    instrument=Instrument(policy['contract_id']),
                    costs=demo_config().costs,
                    limits=paper_risk_limits(),
                    risk_sessions=tuple(policy['risk_sessions']),
                    margin_schedule=tuple(policy['margin_schedule']),
                )
            write_json(existing, policy)
    broker = _paper(root)
    return broker


def _finish_paper_operation(root, broker, replay_state=None):
    state = broker.snapshot()
    journal = broker.journal_events()
    write_json(root / 'paper_snapshot.json', state)
    write_json(root / 'paper_journal_export.json', journal)
    if replay_state is not None:
        return {'replay': replay_state, 'account': state}
    return {'account': state, 'journal_tail': journal[-20:], 'journal_file': str(root / 'paper_journal_export.json')}


def _handle_ui_analysis_preview(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import read_account_status

    output = root / 'analyses'
    allowed = {'request'}
    if set(payload) != allowed:
        raise ValidationError(ui_text('ui.execute_ui_operation.invalid_analysis_fields'))
    plan = analysis_plan(paths, payload['request'], emit=emit)
    provider = analysis_provider_for(paths, plan)
    reference = OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), plan['binding']['registration'])
    snapshot = provider.read_receipt_snapshot()
    account = read_account_status(reference, research_controls(paths))
    return {'analysis_id': plan['analysis_id'], 'plan': plan, 'receipt_snapshot': snapshot, 'account_status': account}


def _handle_ui_analysis_read(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import read_account_status

    output = root / 'analyses'
    expected = {'analysis_id'}
    durable = False
    if durable:
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import supports_durable_recovery

        if not supports_durable_recovery():
            raise ValidationError(ui_text('ui.execute_ui_operation.windows_stop_evidence_only'))
    if durable:
        expected = {'analysis_id', 'registration', 'recovery_launch_id'}
    if set(payload) != expected:
        raise ValidationError(ui_text('ui.execute_ui_operation.invalid_saved_analysis_fields'))
    record = read_analysis(output, payload['analysis_id'])
    return {'analysis_id': payload['analysis_id'], 'record': record, 'cache_hit': True}


def _handle_ui_analysis_reconcile(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import read_account_status

    output = root / 'analyses'
    expected = {'analysis_id', 'registration', 'stopped_job_id'}
    durable = 'recovery_launch_id' in payload
    if durable:
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import supports_durable_recovery

        if not supports_durable_recovery():
            raise ValidationError(ui_text('ui.execute_ui_operation.windows_stop_evidence_only'))
    if durable:
        expected = {'analysis_id', 'registration', 'recovery_launch_id'}
    if set(payload) != expected:
        raise ValidationError(ui_text('ui.execute_ui_operation.invalid_saved_analysis_fields'))
    if not durable and descendants_stopped is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.process_still_running'))
    record = _read_analysis_journal(output, payload['analysis_id'])
    if record['plan']['binding']['registration'] != payload['registration']:
        raise ValidationError(ui_text('ui.execute_ui_operation.original_account_mismatch'))
    if durable:
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import validate_stop_receipt

        launch = validate_stop_receipt(paths, payload['recovery_launch_id'], record=record)
        if launch['analysis_id'] != payload['analysis_id'] or launch['registration'] != payload['registration']:
            raise ValidationError(ui_text('ui.execute_ui_operation.stop_evidence_mismatch'))
    record = reconcile_analysis(
        output_root=output,
        analysis_id=payload['analysis_id'],
        provider=analysis_provider_for(paths, record['plan']),
        descendants_stopped=descendants_stopped is True,
        recovery=(paths, payload['recovery_launch_id']) if durable else None,
    )
    return {'analysis_id': payload['analysis_id'], 'record': record, 'cache_hit': True}


def _handle_ui_analysis_run(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import read_account_status

    output = root / 'analyses'
    allowed = {'request', 'expected_analysis_id', 'expected_plan_hash', 'user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'}
    if 'approved_plan' in payload:
        allowed = allowed | {'approved_plan'}
    if set(payload) != allowed:
        raise ValidationError(ui_text('ui.execute_ui_operation.invalid_analysis_fields'))
    if any((payload[key] is not True for key in ('user_confirmed', 'network_opt_in', 'included_usage_policy_confirmed'))):
        raise ValidationError(ui_text('ui.execute_ui_operation.consent_required'))
    plan = analysis_plan(paths, payload['request'], emit=emit)
    if payload['expected_analysis_id'] != plan['analysis_id'] or payload['expected_plan_hash'] != content_hash(plan):
        raise ValidationError(ui_text('ui.execute_ui_operation.preview_binding_changed'))
    if 'approved_plan' in payload and canonical_json(payload['approved_plan']) != canonical_json(plan):
        raise ValidationError(ui_text('ui.execute_ui_operation.approved_plan_mismatch'))
    if emit:
        emit('progress', message=ui_text('ui.execute_ui_operation.sending_single_request'))
    result = run_analysis(
        output_root=output,
        plan=plan,
        provider=analysis_provider_for(paths, plan, authorized=True),
        expected_analysis_id=payload['expected_analysis_id'],
        user_confirmed=True,
    )
    return {'analysis_id': plan['analysis_id'], **result}


def _promote_report(folder, destination):
    # Retry only report promotion during bounded Windows reader contention.
    from quantlab.runtime_support import replace_file

    return replace_file(folder, destination)


def _handle_ui_backtest(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.strategies import builtin_strategies, validate_strategy

    # Keep operation-specific dependencies out of module startup.
    from quantlab.backtest import run_backtest

    # Keep operation-specific dependencies out of module startup.
    from quantlab.__main__ import config_from_json

    data = _dataset(root, payload)
    config = config_from_json(payload['config'])
    specs = list(builtin_strategies())
    provenance = None
    if payload.get('candidate'):
        if payload.get('batch'):
            raise ValidationError(ui_text('ui.execute_ui_operation.mixed_candidate_batch'))
        spec, provenance = candidate_record(root, payload['candidate'])
        source_hash = data.manifest.get('parent_data_hash', data.manifest['data_hash'])
        if provenance['source_data_hash'] != source_hash:
            raise ValidationError(ui_text('ui.execute_ui_operation.candidate_dataset_mismatch'))
        specs = [spec]
    elif not payload.get('batch'):
        spec = next((s for s in specs if s.family == payload['family']), None)
        if spec is None:
            raise ValidationError(ui_text('ui.execute_ui_operation.unknown_family'))
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
        # Keep operation-specific dependencies out of module startup.
        import tempfile

        reports_root = root / 'reports'
        reports_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.partial-', dir=reports_root) as staging:
            files = export_report(result, Path(staging))
            folder = Path(files['result']).parent
            write_json(folder / 'strategy.json', spec)
            if provenance:
                write_json(folder / 'candidate_provenance.json', provenance)
            destination = reports_root / files['result_hash']
            if destination.exists():
                if content_hash(load_result(destination / 'result.json')) != files['result_hash'] or read_json(destination / 'strategy.json') != to_dict(spec):
                    raise ValidationError(ui_text('ui.execute_ui_operation.incomplete_report'))
            else:
                _promote_report(folder, destination)
            files = {key: str(destination / Path(value).name) if key != 'result_hash' else value for key, value in files.items()}
        reports.append(files)
    write_json(root / 'active_result.json', {'result_hash': reports[-1]['result_hash']})
    return {'reports': reports, 'metrics': to_dict(summary_metrics), 'source_type': data.manifest['source_type'], 'scope': 'research_only'}


def _handle_ui_backup_create(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from quantlab.desktop_runtime import BackupManager

    manager = BackupManager(paths)
    return {'backup': str(manager.create(Path(payload['path'])))}


def _handle_ui_backup_restore(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from quantlab.desktop_runtime import BackupManager

    manager = BackupManager(paths)
    manager.restore(Path(payload['path']))
    return {'restored': True, 'reconciliation_required': True}


def _handle_ui_campaign(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import FixtureGenerator, run_campaign, demo_campaign_config

    # Keep operation-specific dependencies out of module startup.
    from quantlab.__main__ import config_from_json

    data = _dataset(root, payload)
    config = payload.get('config') or demo_campaign_config(data, demo_config())
    if isinstance(config.get('backtest_config'), dict):
        config['backtest_config'] = config_from_json(config['backtest_config'])
    options = payload['provider']
    if options.get('mode') == 'chatgpt_plan':
        generator, plan_identity = plan_provider(paths, data, config, options)
        options = {'mode': 'chatgpt_plan', 'binding': plan_identity}
    elif options.get('mode') == 'manual':
        # Keep operation-specific dependencies out of module startup.
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
    return run_campaign(
        data,
        config=config,
        generator=generator,
        output_dir=root / 'campaigns' / name,
        holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3',
    )


def _handle_ui_chatgpt_auth(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_ui import ConnectionRequest, run_connection_request

    # Keep operation-specific dependencies out of module startup.
    from dataclasses import asdict

    if set(payload) != {'request'} or not isinstance(payload['request'], dict):
        raise ValidationError(ui_text('ui.execute_ui_operation.invalid_connection_fields'))
    request = ConnectionRequest(**payload['request'])

    def private_event(event):
        if emit is None:
            raise ValidationError(ui_text('ui.private_event.managed_private_channel_required'))
        emit('auth_progress', auth_event=asdict(event))

    if request.action in ('begin', 'first_sign_in', 'enable_plan') and emit is None:
        raise ValidationError(ui_text('ui.execute_ui_operation.managed_process_required'))
    result = run_connection_request(request, bootstrap=str(getattr(paths, 'bootstrap', None) or paths.root), emit=private_event, cancelled=lambda: False)
    if result.authorization_url is not None:
        raise ValidationError(ui_text('ui.execute_ui_operation.authorization_url_private'))
    return {'auth_event': asdict(result)}


def _handle_ui_chatgpt_reconcile(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import reconcile_interrupted_campaign

    # Keep operation-specific dependencies out of module startup.
    from quantlab.__main__ import config_from_json

    if descendants_stopped is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.subprocess_stop_unconfirmed'))
    if set(payload) != {'config', 'provider', 'binding', 'stopped_job_id'}:
        raise ValidationError(ui_text('ui.execute_ui_operation.unsupported_recovery_fields'))
    data = _dataset(root, {})
    config = dict(payload['config'])
    config['backtest_config'] = config_from_json(config['backtest_config'])
    generator, identity = plan_provider(paths, data, config, payload['provider'], for_usage=True)
    if identity != payload['binding']:
        raise ValidationError(ui_text('ui.execute_ui_operation.research_identity_mismatch'))
    name = content_hash(
        {'dataset': data.manifest['data_hash'], 'config': config, 'provider': provider_binding_options({'mode': 'chatgpt_plan', 'binding': identity})}
    )
    state = reconcile_interrupted_campaign(output_dir=root / 'campaigns' / name, generator=generator, descendants_stopped=True)
    return {'binding': identity, 'state': state['status']}


def _handle_ui_chatgpt_usage(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import read_account_status

    if set(payload) - {'registration', 'provider', 'config'}:
        raise ValidationError(ui_text('ui.execute_ui_operation.unsupported_reconciliation_fields'))
    reference = OAuthCredentialReference(str(getattr(paths, 'bootstrap', None) or paths.root), payload['registration'])
    status = read_account_status(reference, research_controls(paths))
    result = {'registration': payload['registration'], 'account_status': status}
    if 'provider' in payload:
        # Keep operation-specific dependencies out of module startup.
        from quantlab.__main__ import config_from_json

        data = _dataset(root, {})
        config = dict(payload['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        provider, identity = plan_provider(paths, data, config, payload['provider'], for_usage=True)
        if provider.credential_reference.registration != payload['registration']:
            raise ValidationError(ui_text('ui.execute_ui_operation.account_record_mismatch'))
        receipts = provider.read_receipt_snapshot()['receipts']
        if len(receipts) > 10000:
            raise ValidationError(ui_text('ui.execute_ui_operation.records_display_limit'))
        result.update(
            receipts=[{'sequence': row['sequence'], 'status': row['status']} for row in receipts],
            binding=identity,
            account_status=read_account_status(reference, research_controls(paths)),
        )
    return result


def _handle_ui_compare(payload, paths, root, *, emit=None, descendants_stopped=False):
    if not payload.get('results'):
        raise ValidationError(ui_text('ui.execute_ui_operation.results_required'))
    return {'rows': comparison_rows([load_result(p) for p in payload['results']])}


def _handle_ui_demo(payload, paths, root, *, emit=None, descendants_stopped=False):
    data = synthetic_dataset(payload.get('bars', 960))
    destination = root / ('synthetic-demo-dataset.json' if payload.get('synthetic_quick_start') is True else 'dataset.json')
    save_dataset(data, destination)
    return {'dataset': str(destination), 'source_type': 'synthetic', 'bars': len(data.bars)}


def _handle_ui_disable(payload, paths, root, *, emit=None, descendants_stopped=False):
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


def _handle_ui_import(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.data import SessionCalendar, import_taifex

    # Gap projection is needed only for the import operation.
    from quantlab.data_gap_report import reject_invalid_import

    cal = read_json(Path(payload['calendar']))
    if payload['kind'] == 'validated_dataset':
        data = load_dataset(Path(payload['path']))
        reject_invalid_import(data, emit)
        dataset_market_series(data, cal)
    else:
        data = import_taifex(
            Path(payload['path']),
            kind=payload['kind'],
            calendar=SessionCalendar(cal['sessions'], version=cal['version']),
            contract_id=payload.get('contract') or None,
            encoding=payload.get('encoding'),
        )
    reject_invalid_import(data, emit)
    save_dataset(data, root / 'dataset.json')
    write_json(root / 'dataset_calendar.json', cal)
    return {'dataset': str(root / 'dataset.json'), 'bars': len(data.bars), 'manifest': to_dict(data.manifest), 'quality': to_dict(data.quality)}


def _handle_ui_market_refresh(payload, paths, root, *, emit=None, descendants_stopped=False):
    if 'history_import' in payload:
        if payload.get('history_import') is not True or set(payload) != {'history_import', 'local_path', 'sessions', 'dated_policy_confirmed'}:
            raise ValidationError(ui_text('ui.execute_ui_operation.invalid_history_import_fields'))
        # Keep operation-specific dependencies out of module startup.
        from quantlab.market_history import import_history, session_from_dict

        if payload.get('dated_policy_confirmed') is not True:
            raise ValidationError(ui_text('ui.execute_ui_operation.session_confirmation_required'))
        records = payload.get('sessions')
        if not isinstance(records, list) or not 1 <= len(records) <= 128:
            raise ValidationError(ui_text('ui.execute_ui_operation.session_count_limit'))
        if emit is not None:
            emit('progress', message=ui_text('ui.execute_ui_operation.importing_local_history'))
        result = import_history(Path(payload['local_path']), root / 'market_history', sessions=tuple((session_from_dict(row) for row in records)))
        return {
            'mode': 'local_unverified_history',
            'cache_id': result.cache_id,
            'source_hash': result.source_hash,
            'policy_hash': result.policy_hash,
            'counters': dict(result.counters),
            'warnings': list(result.warnings),
            'contracts': len(result.series),
            'bars': sum((len(x.bars) for x in result.series)),
        }
    # Keep operation-specific dependencies out of module startup.
    from quantlab.market_providers import refresh_daily, import_daily, MAX_BYTES

    local = payload.get('local_path')
    if not local and payload.get('network_opt_in') is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.market_consent_required'))
    providers = (payload.get('provider'),) if local else ('twse', 'taifex')
    outcomes = {}
    for provider in providers:
        if provider not in ('twse', 'taifex'):
            raise ValidationError(ui_text('ui.execute_ui_operation.unsupported_official_source'))
        try:
            kwargs = {}
            if local:
                path = Path(local)
                if path.stat().st_size > MAX_BYTES:
                    raise ValidationError(ui_text('ui.execute_ui_operation.official_file_too_large'))
                with path.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValidationError(ui_text('ui.execute_ui_operation.official_file_too_large'))
                result = import_daily(provider, root / 'market_cache', raw, format=payload.get('format', 'json'))
            else:
                result = refresh_daily(provider, root / 'market_cache', network_enabled=True, **kwargs)
            outcomes[provider] = {
                'stale': result.stale,
                'error': result.error,
                'contracts': len(result.series),
                'bars': sum((len(x.bars) for x in result.series)),
            }
        except Exception as exc:
            outcomes[provider] = {'stale': True, 'error': exception_code(exc), 'contracts': None, 'bars': None}
    return {'providers': outcomes, 'mode': 'official_local_import' if local else 'official_explicit_refresh'}


def _handle_ui_paper_cancel(payload, paths, root, *, emit=None, descendants_stopped=False):
    if payload.get('action') == 'amend':
        # Load the offline amend adapter only for this paper worker action.
        from quantlab.paper_amend import execute as _execute_amend

        return _execute_amend(
            payload, root, prepare=lambda: _prepare_paper_operation(payload, paths, root), finish=lambda broker: _finish_paper_operation(root, broker)
        )
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    broker.cancel(payload['order_id'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_paper_cancel_all(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    now = datetime.fromisoformat(payload['now'].replace('Z', '+00:00'))
    targets = sorted(order_id for order_id, row in broker.snapshot()['orders'].items() if row['status'] not in ('filled', 'cancelled', 'rejected'))
    report = {'cancelled_order_ids': [], 'failed_order_ids': [], 'errors': {}}
    for order_id in targets:
        try:
            broker.cancel(order_id, now=now)
        except Exception as exc:
            report['failed_order_ids'].append(order_id)
            report['errors'][order_id] = exception_code(exc)
        else:
            report['cancelled_order_ids'].append(order_id)
    result = _finish_paper_operation(root, broker)
    result['cancel_all_report'] = report
    return result


def _handle_ui_paper_kill(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    if 'manual_order_lock' in payload:
        broker.set_manual_order_lock(payload['manual_order_lock'])
    else:
        broker.set_kill_switch(True)
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_paper_reconcile(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    broker.reconcile(payload['snapshot'])
    if 'manual_order_lock' in payload:
        broker.set_manual_order_lock(payload['manual_order_lock'])
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_paper_replay(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    if payload.get('reconcile_confirmed') is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.replay_confirmation_required'))
    broker.reconcile(payload['snapshot'])
    if broker.snapshot().get('manual_order_lock', False):
        error = ValidationError(ui_text('paper.lock.rejected'))
        error.code = 'paper_manual_order_lock'
        raise error
    # Keep operation-specific dependencies out of module startup.
    from quantlab.paper_replay import PaperReplay

    data = _dataset(root, payload)
    selection = load_selection(root / 'selection.json')
    binding = content_hash([data.manifest['data_hash'], selection['strategy_hash']])
    paths.require_replay_wal()
    replay = PaperReplay(
        root / 'replays' / (binding + '.sqlite3'),
        dataset=data,
        strategy=StrategySpec(**selection['strategy']),
        broker=broker,
        margin_schedule=broker._margin_schedule,
        storage_profile='wal_full',
    )
    if 'replay_action' in payload:
        # Keep pacing controls out of module startup and the public UI oracle.
        import quantlab.replay_pacing as _replay_pacing

        try:
            replay_state = _replay_pacing.control(replay, payload['replay_action'])
            return _finish_paper_operation(root, broker, replay_state)
        except BaseException:
            replay.stop()
            raise
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
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_paper_snapshot(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_paper_submit(payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(payload, paths, root)
    replay_state = None
    if payload.get('reconcile_confirmed') is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.snapshot_confirmation_required'))
    broker.reconcile(payload['snapshot'])
    selection = load_selection(root / 'selection.json')
    if payload['intent'].get('strategy_hash') != selection['strategy_hash']:
        raise ValidationError(ui_text('ui.execute_ui_operation.order_strategy_mismatch'))
    broker.set_kill_switch(False)
    broker.submit(payload['intent'], quote=payload['quote'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
    return _finish_paper_operation(root, broker, replay_state)


def _handle_ui_refresh(payload, paths, root, *, emit=None, descendants_stopped=False):
    if payload.get('network_opt_in') is not True:
        raise ValidationError(ui_text('ui.execute_ui_operation.taifex_consent_required'))
    if 'auto_import' in payload:
        # Load the download/import composition only for this explicit operation.
        from quantlab.download_import import download_and_import

        return download_and_import(Path(paths.cache), root, payload, emit=emit)
    # Keep operation-specific dependencies out of module startup.
    from quantlab.downloads import refresh

    return refresh(Path(paths.cache), days=payload.get('days', 1), kind=payload.get('format', 'csv'))


def _handle_ui_select(payload, paths, root, *, emit=None, descendants_stopped=False):
    folder = Path(payload['result']).parent
    result = load_result(folder / 'result.json')
    reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
    if reference:
        spec, provenance = candidate_record(root, reference)
        if not provenance['paper_qualified']:
            raise ValidationError(ui_text('ui.execute_ui_operation.candidate_not_paper_eligible'))
        if content_hash(spec) != result.manifest.get('spec_hash'):
            raise ValidationError(ui_text('ui.execute_ui_operation.candidate_backtest_mismatch'))
    return save_selection(read_json(folder / 'strategy.json'), result, root / 'selection.json')


def _handle_ui_capital_scenario(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep the derived-data reader out of startup.
    import desktop_capital_scenario as _capital

    return _capital.execute(payload, paths)


def _idea_event_caller(reference, transport):
    """Stream one Responses call through the shared transport; yield parsed SSE events."""
    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_provider import PlanError, SSEParser

    # Keep authentication exception handling local to this network operation.
    from desktop_chatgpt_auth import AuthError

    # Translate only fixed diagnostics into the research domain boundary.
    from quantlab.idea_search import RemoteFailure

    def call(request, limits, cancelled):
        # Search events carry source lists; allow larger single events than candidate calls.
        parser = SSEParser(max_bytes=limits['max_response_bytes'], max_event_bytes=1048576, max_events=8192)
        stream = transport.stream(reference, request, limits, cancelled)
        try:
            for chunk in stream:
                for event in parser.feed(chunk):
                    kind = event.get('type')
                    response = event.get('response') or {}
                    error = event.get('error') if kind == 'error' else response.get('error')
                    if kind == 'error' and not isinstance(error, dict):
                        error = event
                    if kind in ('response.failed', 'response.incomplete', 'error') and not (isinstance(error, dict) and error.get('code')):
                        codes = {
                            'response.failed': 'idea_stream_failed_uncoded',
                            'response.incomplete': 'idea_stream_incomplete',
                            'error': 'idea_stream_error_uncoded',
                        }
                        raise RemoteFailure(codes[kind])
                    yield event
            parser.finish()
        except AuthError as exc:
            code = 'idea_auth_refresh_required' if exc.args == ('refresh_required',) else 'idea_auth_unavailable'
            raise RemoteFailure(code) from None
        except PlanError as exc:
            codes = {
                408: 'idea_http_timeout',
                429: 'idea_http_rate_limited',
                500: 'idea_http_server_error',
                502: 'idea_http_bad_gateway',
                504: 'idea_http_gateway_timeout',
            }
            if exc.code == 'remote_error' and exc.http_status in codes:
                raise RemoteFailure(codes[exc.http_status]) from None
            raise
        finally:
            stream.close()

    return call


def _handle_ui_idea_research(payload, paths, root, *, emit=None, descendants_stopped=False, transport=None, fetcher=None):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.idea_research import IdeaResearch, IdeaStore, new_task

    # Load the optional UI adapter only when this operation is requested.
    from desktop_chatgpt_auth import OAuthCredentialReference

    # Reuse the existing verified-TLS, no-redirect, bounded transport by import only.
    from desktop_chatgpt_provider import PlanHTTPTransport, _persist_account_pause, read_account_status

    retry = 'retry_task_id' in payload
    if set(payload) != ({'retry_task_id', 'consent', 'registration', 'model'} if retry else {'request', 'registration', 'model'}):
        raise ValidationError(ui_text('idea.invalid_request'))
    if (payload['consent'] if retry else payload['request'].get('consent')) != {'network': True, 'plan_usage': True}:
        raise ValidationError(ui_text('idea.consent_required'))
    bootstrap = str(getattr(paths, 'bootstrap', None) or paths.root)
    reference = OAuthCredentialReference(bootstrap, payload['registration'])
    if transport is None:
        if read_account_status(reference, Path(bootstrap) / 'control-v1') != {'state': 'ready', 'pending': False}:
            raise ValidationError(ui_text('idea.account_not_ready'))
        transport = PlanHTTPTransport()
    store = IdeaStore(root)
    task = store.load(payload['retry_task_id']) if retry else new_task(payload['request'])

    messages = {
        'task': ui_text('idea.progress.task'),
        'search': ui_text('idea.progress.search'),
        'urls': ui_text('idea.progress.urls'),
        'source': ui_text('idea.progress.source'),
        'extracting': ui_text('idea.progress.extracting'),
        'candidates': ui_text('idea.progress.candidates'),
        'status': ui_text('idea.progress.status'),
    }

    def progress(kind, **values):
        if emit is not None:
            event = values.get('idea_event') or {}
            emit(kind, **{**values, 'message': messages.get(event.get('kind'), messages['status'])})

    research = IdeaResearch(task, caller=_idea_event_caller(reference, transport), model=payload['model'], root=root, emit=progress, fetcher=fetcher)
    record = research.retry_failed() if retry else research.run()
    if record['status'] == 'quota_paused':
        _persist_account_pause(reference, 'quota_paused')
    return {
        'task_id': record['task_id'],
        'status': record['status'],
        'stop_reason': record['stop_reason'],
        'searches': len(record['searches']),
        'sources': len(record['sources']),
        'candidates': len(record['candidates']),
        'backtestable': sum(1 for c in record['candidates'] if c.get('backtestable')),
    }


def _handle_ui_idea_adopt(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.idea_research import IdeaStore, adoption_candidate, adoption_config, manual_response

    # Keep operation-specific dependencies out of module startup.
    from quantlab.manual_exchange import export_request

    # Keep operation-specific dependencies out of module startup.
    from quantlab.__main__ import config_from_json

    if set(payload) != {'task_id', 'candidate_id', 'config'}:
        raise ValidationError(ui_text('idea.invalid_request'))
    candidate = adoption_candidate(IdeaStore(root).load(payload['task_id']), payload['candidate_id'])
    config = adoption_config(payload['config'], candidate['family'])
    checked = dict(config)
    if isinstance(checked.get('backtest_config'), dict):
        checked['backtest_config'] = config_from_json(checked['backtest_config'])
    response = manual_response(export_request(_dataset(root, {}), checked), candidate)
    # The existing manual campaign path seals, evaluates and saves; nothing existing is replaced.
    state = _handle_ui_campaign({'config': config, 'provider': {'mode': 'manual', 'response_text': response}}, paths, root, emit=emit)
    return state


def _handle_ui_walk_forward_preview(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_walk_forward import execute_walk_forward

    return execute_walk_forward('ui_walk_forward_preview', payload, paths, descendants_stopped=descendants_stopped)


def _handle_ui_walk_forward_read(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_walk_forward import execute_walk_forward

    return execute_walk_forward('ui_walk_forward_read', payload, paths, descendants_stopped=descendants_stopped)


def _handle_ui_walk_forward_reconcile(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_walk_forward import execute_walk_forward

    return execute_walk_forward('ui_walk_forward_reconcile', payload, paths, descendants_stopped=descendants_stopped)


def _handle_ui_walk_forward_run(payload, paths, root, *, emit=None, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_walk_forward import execute_walk_forward

    return execute_walk_forward('ui_walk_forward_run', payload, paths, descendants_stopped=descendants_stopped)


_UI_OPERATION_HANDLERS = {
    'ui_capital_scenario': _handle_ui_capital_scenario,
    'ui_idea_research': _handle_ui_idea_research,
    'ui_idea_adopt': _handle_ui_idea_adopt,
    'ui_analysis_preview': _handle_ui_analysis_preview,
    'ui_analysis_read': _handle_ui_analysis_read,
    'ui_analysis_reconcile': _handle_ui_analysis_reconcile,
    'ui_analysis_run': _handle_ui_analysis_run,
    'ui_backtest': _handle_ui_backtest,
    'ui_backup_create': _handle_ui_backup_create,
    'ui_backup_restore': _handle_ui_backup_restore,
    'ui_campaign': _handle_ui_campaign,
    'ui_chatgpt_auth': _handle_ui_chatgpt_auth,
    'ui_chatgpt_reconcile': _handle_ui_chatgpt_reconcile,
    'ui_chatgpt_usage': _handle_ui_chatgpt_usage,
    'ui_compare': _handle_ui_compare,
    'ui_demo': _handle_ui_demo,
    'ui_disable': _handle_ui_disable,
    'ui_import': _handle_ui_import,
    'ui_market_refresh': _handle_ui_market_refresh,
    'ui_paper_cancel': _handle_ui_paper_cancel,
    'ui_paper_cancel_all': _handle_ui_paper_cancel_all,
    'ui_paper_kill': _handle_ui_paper_kill,
    'ui_paper_reconcile': _handle_ui_paper_reconcile,
    'ui_paper_replay': _handle_ui_paper_replay,
    'ui_paper_snapshot': _handle_ui_paper_snapshot,
    'ui_paper_submit': _handle_ui_paper_submit,
    'ui_refresh': _handle_ui_refresh,
    'ui_select': _handle_ui_select,
    'ui_walk_forward_preview': _handle_ui_walk_forward_preview,
    'ui_walk_forward_read': _handle_ui_walk_forward_read,
    'ui_walk_forward_reconcile': _handle_ui_walk_forward_reconcile,
    'ui_walk_forward_run': _handle_ui_walk_forward_run,
}


def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError(ui_text('ui.execute_ui_operation.unknown_operation'))
    if operation == 'ui_capital_scenario' and type(payload) is not dict:
        raise ValidationError(ui_text('capital.invalid'))
    if operation == 'ui_campaign' and (
        not isinstance(payload.get('provider'), dict) or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')
    ):
        raise ValidationError(ui_text('ui.execute_ui_operation.subscription_only'))
    root = _root(paths)
    if payload.get('synthetic_quick_start') is True:
        if operation not in ('ui_demo', 'ui_backtest'):
            raise ValidationError(ui_text('ui.execute_ui_operation.unknown_operation'))
        root = root / 'synthetic-quick-start'
        root.mkdir(exist_ok=True)
        if operation == 'ui_backtest':
            payload = {**payload, 'dataset': str(root / 'synthetic-demo-dataset.json')}
    return _UI_OPERATION_HANDLERS[operation](payload, paths, root, emit=emit, descendants_stopped=descendants_stopped)


# Register after the executor definition, before GUI startup and smoke dispatch.
from quantlab.desktop_runtime import (
    register_operation_executor as _register_operation_executor,
    register_operation_executor_factory as _register_operation_executor_factory,
)

OPERATION_REGISTRAR = 'desktop_ui:execute_ui_operation'
_register_operation_executor(execute_ui_operation)
_register_operation_executor_factory(OPERATION_REGISTRAR)


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
    # Keep operation-specific dependencies out of module startup.
    from quantlab.data import validate_dataset, SessionCalendar

    # Keep operation-specific dependencies out of module startup.
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance, bar_key

    validate_dataset(dataset)
    manifest = dataset.manifest
    if manifest['source_type'] != 'official_local' or manifest.get('bar_granularity') != 'minute' or manifest.get('timeframe_minutes', 1) != 1:
        raise ValidationError(ui_text('ui.dataset_market_series.minute_history_required'))
    calendar = SessionCalendar(calendar_payload['sessions'], version=calendar_payload['version'])
    if calendar.hash != manifest.get('calendar_hash'):
        raise ValidationError(ui_text('ui.dataset_market_series.calendar_hash_mismatch'))
    grouped = {}
    for bar in dataset.bars:
        instrument = InstrumentRef('TAIFEX', 'TMF', bar.contract_id, bar.contract_id.split(':')[-1])
        session = calendar.lookup(bar.timestamp, bar.contract_id)
        value = MarketBar(
            instrument,
            bar.trade_date,
            bar.session,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            interval='1m',
            timestamp=bar.timestamp,
            end=bar.end,
            session_open=session['open'],
            session_end=session['end'],
            source_id=bar.source_id,
        )
        grouped.setdefault(instrument, []).append(value)
    result = []
    for instrument, bars in grouped.items():
        bars.sort(key=bar_key)
        dates = [b.trade_date for b in bars]
        provenance = SourceProvenance(
            manifest['source_url'],
            manifest['source_hash'],
            ui_text('ui.dataset_market_series.taifex_source_hash').format(manifest['data_hash']),
            'https://www.taifex.com.tw',
            datetime.fromisoformat(manifest['imported_at'].replace('Z', '+00:00')),
            max(dates),
            min(dates),
            max(dates),
            mode='history',
            timestamp_basis='hash-bound explicit session calendar; one-minute source',
            warnings=tuple(str(x) for x in dataset.quality.get('warnings', ())),
        )
        result.append(MarketSeries(instrument, tuple(bars), provenance))
    return tuple(result)


from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QUrl, QPropertyAnimation
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow,
    QFrame as _QFrame,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QStackedWidget,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QProgressBar,
    QFileDialog,
    QFormLayout,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QMessageBox,
    QApplication,
    QGroupBox,
    QSizePolicy as _QSizePolicy,
    QLayout as _QLayout,
    QGraphicsOpacityEffect,
)


from desktop_pages import PageHost, PageState, MarketPage, DataPage, StrategyPage, BacktestPage
from desktop_pages.equity import EquityPlot
from desktop_pages.result_layers import result_snapshot_lines

from desktop_presentation import display_number, display_status, result_name
from desktop_market import MarketDashboard, MarketHistoryDialog
from desktop_forms import (
    StrategyForm,
    BacktestForm,
    CampaignForm,
    WalkForwardForm,
    PaperPolicyForm,
    PaperIntentForm,
    PaperQuoteForm,
    PaperSnapshotForm,
    ResultTable,
    SummaryCard,
    BacktestSummaryCard,
    BacktestFillsTable,
    CandidateSummaryCard,
)


from desktop_pages.bindings import SharedStateBindings
from desktop_pages.mount import mount_pages
import desktop_pages.job_progress as _job_progress
import desktop_pages.app_header as _app_header


def _install_window_support(window):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_ui_polish import install_polish

    apply_theme(window)
    install_polish(window)
    # Load the optional UI adapter only when this operation is requested.
    from desktop_help import install_page_help

    install_page_help(window)
    # Load the optional UI adapter only when this operation is requested.
    from desktop_pages.shortcuts import install_shortcuts

    # Load the optional UI adapter only when this operation is requested.
    from desktop_accessibility import install_accessibility

    install_shortcuts(window)
    install_accessibility(window)
    window.app_header.refresh()


# fmt: off
import desktop_pages.notifications as _notifications


class MainWindow(SharedStateBindings, QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None):
        super().__init__()
        self.page_state = PageState()
        # Load the optional UI adapter only when this operation is requested.
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
        self.setWindowTitle(ui_text('ui.init.window_title'))
        # Load the optional UI adapter only when this operation is requested.
        from desktop_theme import MINIMUM_WINDOW_SIZE
        self.setMinimumSize(*MINIMUM_WINDOW_SIZE)
        self.resize(1366, 768)
        apply_theme(self)
        body = QWidget(); outer = QVBoxLayout(body)
        _app_header.install_header(self, outer, paper_risk_limits().max_quote_age_seconds)
        horizontal = QHBoxLayout(); outer.addLayout(horizontal, 1)
        self.navigation = QListWidget(); self.navigation.setObjectName('navigation'); self.navigation.setMaximumWidth(180)
        self.stack = QStackedWidget()
        # Keep display persistence outside the shell.
        from desktop_pages.preferences import install_sidebar
        install_sidebar(self, horizontal)
        self.status = QLabel(ui_text('ui.init.ready')); self.status.setObjectName('status'); self.status.setWordWrap(True)
        outer.addWidget(self.status)
        _notifications.install_notifications(self, outer)
        _job_progress.install_progress(self, outer)
        self.setCentralWidget(body)
        self.page_state._section_toggles = self._section_toggles
        self.page_state._advanced_values = self._advanced_values
        self.page_state.paths = self.paths
        self.page_state.jobs = self.jobs
        self.page_state.settings = self.settings
        self.page_state.root = self.root
        self.page_state.status = self.status
        self.page_host = PageHost(
            state=self.page_state,
            callbacks={}, find_child=self.findChild, window_screen=self.screen,
            resize_window=self.resize, move_window=self.move,
            question=lambda *a: QMessageBox.question(self, *a),
            open_file=lambda *a: QFileDialog.getOpenFileName(self, *a),
            save_file=lambda *a: QFileDialog.getSaveFileName(self, *a),
            market_history_dialog=lambda: MarketHistoryDialog(self),
            mount_market=lambda *a, **kw: self._mount_market(*a, **kw), mount_page=lambda *a, **kw: self._mount_page(*a, **kw),
            advanced=lambda *a, **kw: self._advanced(*a, **kw),
            bind_result_layers=lambda *a, **kw: self.market_page.bind_result_layers(*a, **kw),
            browse=lambda *a, **kw: self._browse(*a, **kw),
            button=lambda *a, **kw: self._button(*a, **kw),
            candidate_record=candidate_record,
            dataset=_dataset,
            dataset_market_series=dataset_market_series,
            form_feedback=lambda *a, **kw: self.form_feedback(*a, **kw),
            inspect_plan_usage=lambda *a, **kw: self.inspect_plan_usage(*a, **kw),
            latest_market_observations=latest_market_observations,
            payload=lambda *a, **kw: self._payload(*a, **kw),
            plan_provider=plan_provider,
            record_event=lambda *a, **kw: self.record_event(*a, **kw),
            remember=lambda *a, **kw: self._remember(*a, **kw),
            result_snapshot_lines=lambda *a, **kw: self._result_snapshot_lines(*a, **kw),
            safe=lambda *a, **kw: self._safe(*a, **kw),
            save_sections=lambda *a, **kw: self._save_section_preferences(*a, **kw),
            show_account=lambda *a, **kw: self._show_account(*a, **kw),
            show_sign_in=lambda *a, **kw: self.show_chatgpt_sign_in(*a, **kw),
            start_job=lambda *a, **kw: self.start_job(*a, **kw),
            text=lambda *a, **kw: self._text(*a, **kw),
            window_geometry=lambda *a, **kw: self.geometry(*a, **kw),
            window_position=lambda: QPoint(self.x(), self.y()),
            window_minimum_size=lambda: (self.minimumWidth(), self.minimumHeight()),
        )
        self.page_state.save_sections = lambda: self.page_host.safe(self.page_host.save_sections)
        mount_pages(self)
        self.strategy_page.bind_connection(self.chatgpt_controller, self.chatgpt_panel)
        self.app_header.bind_controls()
        self.privacy.attach_previews()
        # Load the optional UI adapter only when this operation is requested.
        from desktop_pages.onboarding import install_onboarding
        install_onboarding(self)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.itemSelectionChanged.connect(self._navigate_selected_page)
        self.navigation.setCurrentRow(0)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_jobs); self.timer.start(150)
        self._safe(self.refresh_views)
        self._safe(self.load_settings)
        self._busy(False)
        self.onboarding.refresh()
        self.onboarding.restore_visibility()
        _install_window_support(self)

    def page_services(self):
        return {
            'ui_operations': UI_OPERATIONS,
            'paper_risk_limits': lambda *a, **kw: paper_risk_limits(*a, **kw),
            '_paper': lambda *a, **kw: _paper(*a, **kw),
            '_dataset': lambda *a, **kw: _dataset(*a, **kw),
            'plan_provider': lambda *a, **kw: plan_provider(*a, **kw),
            'connection_event_from_payload': lambda *a, **kw: connection_event_from_payload(*a, **kw),
            'analysis_preview_text': lambda *a, **kw: analysis_preview_text(*a, **kw),
            'analysis_record_text': lambda *a, **kw: analysis_record_text(*a, **kw),
            'saved_analysis_entries': lambda *a, **kw: saved_analysis_entries(*a, **kw),
            'load_result': lambda *a, **kw: load_result(*a, **kw),
            'result_name': lambda *a, **kw: result_name(*a, **kw),
            'write_json': lambda *a, **kw: write_json(*a, **kw),
            'read_json': lambda *a, **kw: read_json(*a, **kw),
            'load_dataset': lambda *a, **kw: load_dataset(*a, **kw),
        }

    def _mount_market(self, page, label):
        self.navigation.addItem(label)
        self.stack.addWidget(page)

    def _mount_page(self, page, label):
        self.navigation.addItem(label)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        title = QLabel(label); title.setProperty('themePart', 'pageTitle'); layout.addWidget(title)
        scroll = QScrollArea(); scroll.setFrameShape(_QFrame.Shape.NoFrame); scroll.setWidgetResizable(True); scroll.setWidget(page); self.stack.addWidget(scroll)
        if type(page).__name__ == 'StrategyPage':
            page.setSizePolicy(_QSizePolicy.Policy.Expanding, _QSizePolicy.Policy.Ignored)
            layout.setSizeConstraint(_QLayout.SizeConstraint.SetNoConstraint)
            layout.setAlignment(Qt.AlignmentFlag(0))
        return layout

    def _navigate_selected_page(self):
        # Accessibility selection may not update QListWidget's current item.
        selected = self.navigation.selectedItems()
        if len(selected) == 1:
            self.navigation.setCurrentRow(self.navigation.row(selected[0]))

    def _safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            message = error_message(exception_code(exc))
            self.status.setText(message)
            self.notify_local(message, error=True, completion=True)
            return None

    def form_feedback(self, widget, message):
        self.status.setText(message)
        scroll = widget.parentWidget()
        while scroll is not None and not isinstance(scroll, QScrollArea):
            scroll = scroll.parentWidget()
        if scroll is not None: scroll.ensureWidgetVisible(widget)
        original = widget.property('feedback')
        set_theme_property(widget, 'feedback', True)
        QTimer.singleShot(1800, widget, lambda: set_theme_property(widget, 'feedback', original))

    def start_job(self, operation, payload):
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import require_operation
        require_operation(self.paths,operation)
        if operation not in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
            self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active: raise ValidationError(ui_text('ui.start_job.job_busy'))
        job_id = self.jobs.start(operation, payload)
        self.last_operation = operation
        self._ui_job_id = job_id
        self.job_feedback.begin(job_id)
        self.status.setText(ui_text('ui.start_job.running'))
        self._busy(True)
        return job_id

    def _busy(self, active, *, refresh_recovery=False):
        controller = getattr(self, 'chatgpt_controller', None)
        if controller is not None:
            controller.set_background_busy(bool(active))
        panel = getattr(getattr(self, 'strategy_page', None), 'result_panel', None)
        if panel is not None: panel.set_scenario_busy(active)
        for button in self.actions: button.setEnabled(not active)
        self.data_page.next_button.setEnabled(bool(getattr(self, '_dataset_ready', False)) and not active)
        self.market.set_loading(active)
        self.kill_button.setEnabled(True)
        self.job_progress.set_running(active and not self.job_feedback.terminal)
        if not active:
            self.progress.setValue(0)
            self.run_button.setEnabled(bool(getattr(self, '_dataset_ready', False)))
            self.use_candidate_button.setEnabled(bool(getattr(self, '_candidate_valid', False)))
            self.select_button.setEnabled(bool(getattr(self, '_selection_allowed', False)))
            self.walk_forward_start.setEnabled(self._wf_preview is not None and self.walk_forward_consent.isChecked())
            self.analysis_start.setEnabled(self._analysis_preview is not None and not self._analysis_preview['receipt_snapshot']['receipts'])
            if getattr(self, 'paper_page', None) is not None: self.paper_page._apply_order_lock()
        self._refresh_recovery_controls(force=active or refresh_recovery)

    def cancel_job(self):
        if not _job_progress.cancel_allowed(self): return
        def cancel_and_recover():
            self.freeze_paper(ui_text('ui.cancel_and_recover.user_cancel'))
            self.status.setText(ui_text('job.cancel_notice'))
        self._safe(cancel_and_recover)

    def poll_jobs(self):
        try:
            recovery_changed=False
            for event in self.jobs.poll():
                if event.get('job_id') is not None and self._ui_job_id is not None and event['job_id'] != self._ui_job_id:
                    continue  # A joined old worker can never overwrite a newer view.
                _notifications.begin_event(self)
                if not self.job_feedback.accept(self, event): continue
                _notifications.record_event(self, event)
                recovery_changed = recovery_changed or event.get('type') in ('result','error','failed','cancelled','canceled')
                self.automatic_backup_panel.handle_job_event(event)
                # Keep operation-specific presentation out of the shell.
                import desktop_capital_scenario as _capital
                if _capital.event(self, event): continue
                # Keep operation-specific presentation out of the shell.
                import desktop_pages.idea_research as _ideas
                if _ideas.event(self, event): continue
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
                    result = self.views_page.render_result(event)
                    message = completion_summary(self.last_operation, result)
                    if self.job_feedback.campaign_code is not None: message = self.chatgpt_controller.message
                    if self.last_operation == 'ui_market_refresh' and any(v.get('error') for v in self._market_outcomes.values()):
                        message += ui_text('ui.poll_jobs.cache_retained')
                    self.status.clear()
                    self.notify_local(message, error=self.job_feedback.result_failed(result), completion=True)
                elif kind in ('error', 'failed'):
                    if self.last_operation == 'ui_backup_restore':
                        self.freeze_paper(ui_text('ui.poll_jobs.restore_incomplete'))
                    self.status.clear()
                    self.notify_local(_job_progress.failure_notice(self, event), error=True, completion=True)
                elif kind in ('cancelled', 'canceled'):
                    self.freeze_paper(ui_text('ui.poll_jobs.cancelled_title'))
                    self.status.setText(ui_text('ui.poll_jobs.cancelled_files_retained'))
                else:
                    self.status.setText(_job_progress.progress_status(self, event))
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
        finally:
            _notifications.end_event(self)

    def notify_local(self, message, *, error=False, completion=False):
        _notifications.notify_local(self, message, error=error, completion=completion)

    def _notification_link(self, link):
        if link == 'close':
            _notifications.close_banner(self); return
        if link != 'result': return
        operation = self._notification_operation or ''
        page = 4 if operation.startswith('ui_paper_') else 2 if operation == 'ui_backtest' else 3 if operation in ('ui_compare', 'ui_select', 'ui_disable') else 1 if operation.startswith(('ui_analysis_', 'ui_walk_forward_')) or operation == 'ui_campaign' else 6 if operation.startswith(('ui_backup_', 'ui_chatgpt_')) else 0
        self.navigation.setCurrentRow(page)
        target = self.paper_card if page == 4 else self.result_card if page == 2 and hasattr(self, 'result_card') else self.stack.widget(page).widget()
        self.stack.widget(page).ensureWidgetVisible(target)

    def _quiesce_and_recover(self, *, preserve_primary_sign_in=False):
        if getattr(self.page_state, 'replay_controls', None): self.page_state.replay_controls.cancel()
        if not preserve_primary_sign_in:
            self.chatgpt_panel.abandon_primary_sign_in()
        # Never create state files until the writer has exited and pending swaps recover.
        if self.jobs.active: self.jobs.cancel()
        if self.jobs.active: raise ValidationError(ui_text('ui.quiesce_and_recover.process_stop_required'))
        # Keep operation-specific dependencies out of module startup.
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
                    raise RecoveryError(ui_text('ui.quiesce_and_recover.unknown_stop_evidence'))
                return  # Intact analysis-only state; allow independent bookkeeping/close.
            if self.backups is not None:
                self.backups.recover()
            else:
                # Load the optional UI adapter only when this operation is requested.
                from quantlab.desktop_runtime import BackupManager
                BackupManager(self.paths).recover()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_poll_rearmed', False):
            # Re-arm once on first show so a slow construction cannot let the first poll tick fire
            # before the user (or a test harness) has had a full interval with the window visible.
            self._poll_rearmed = True; self.timer.start(150)

    def closeEvent(self, event):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active and QMessageBox.question(self, ui_text('ui.close_event.job_unfinished'), ui_text('ui.close_event.cancel_close_question'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
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
            event.ignore(); self.status.setText(ui_text('ui.close_event.stop_unconfirmed')); return
        self._safe(self.save_market_preferences)
        self.market.popout.close()
        self.chatgpt_controller.set_host_available(False)
        self.timer.stop(); self.app_header.timer.stop(); event.accept()

    _result_snapshot_lines = staticmethod(result_snapshot_lines)
# fmt: on


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    return MainWindow(paths, jobs, settings, backups, guard)
