"""Typed desktop boundary for the frozen, offline walk-forward protocol.

No provider calls, paper qualification/selection or final-holdout evaluation.
Preview is read-only; a run revalidates every source/config binding before scoring.
"""
from desktop_strings import ui_text
from pathlib import Path
import json
import re

from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.walk_forward import (_validate_source, walk_forward_plan_from_dict,
    walk_forward_binding, planned_evaluations,
    run_walk_forward, read_walk_forward_state, reconcile_interrupted_walk_forward)


METRICS = ('net_pnl', 'trade_count', 'max_drawdown_pct', 'max_drawdown',
           'total_costs', 'realized_gross_pnl', 'unrealized_pnl', 'return', 'open_position')


def _folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Walk-forward reference must be an immutable SHA-256 identity')
    state_root = Path(paths.state).resolve()
    base = (state_root / 'walk_forward').resolve()
    if not base.is_relative_to(state_root):
        raise ValidationError('Walk-forward state directory escapes the workspace')
    folder = base / reference
    if not folder.resolve().is_relative_to(base):
        raise ValidationError('Walk-forward reference escapes its state directory')
    return folder


def _binding(data, plan, registry):
    return walk_forward_binding(data, plan, registry)


def source_campaign_folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Source campaign reference must be an immutable SHA-256 identity')
    root = Path(paths.state).resolve()
    base = (root / 'campaigns').resolve()
    folder = base / reference
    if not base.is_relative_to(root) or not folder.resolve().is_relative_to(base):
        raise ValidationError('Source campaign reference escapes the workspace')
    return folder


def _prepare_saved_plan(data, plan_payload, paths, saved_source, registry):
    # Load the optional UI adapter only when this operation is requested.
    from quantlab.desktop_runtime import validate_walk_forward_request
    # Keep operation-specific dependencies out of module startup.
    from quantlab.saved_candidate_pool import admit_saved_campaign_pool, load_original_dataset
    chronology = validate_walk_forward_request(plan_payload, saved_source)
    # Validate the new data before indexing its first training timestamp.
    _validate_source(data, chronology)
    folder = source_campaign_folder(paths, saved_source['campaign_reference'])
    path = Path(saved_source['original_dataset']['path'])
    original = load_original_dataset(path)
    admitted = admit_saved_campaign_pool(source_campaign_dir=folder,
        source_campaign_ref=saved_source['campaign_reference'], original_dataset=original,
        original_dataset_ref=str(path), first_training_timestamp=data.bars[chronology.folds[0].train[0]].timestamp,
        authoritative_registry_path=registry)
    pool, admission = admitted.candidate_pool, to_dict(admitted.admission)
    bound = len(chronology.folds) * (2 * len(pool) + 1)
    if plan_payload['max_evaluations'] > bound:
        return None, {'admission_status': 'rejected', 'reason_code': 'evaluation_budget_exceeds_pool_bound',
            'candidate_count': len(pool), 'fold_count': len(chronology.folds),
            'evaluation_limit': plan_payload['max_evaluations'], 'planned_evaluations_upper_bound': bound,
            'pool_origin': 'saved_campaign_pool', 'pool_admission': admission,
            'candidate_pool': [to_dict(spec) for spec in pool], 'model_calls': 0}
    plan = walk_forward_plan_from_dict({**plan_payload,
        'candidate_pool': [to_dict(spec) for spec in pool], 'pool_admission': admission})
    return plan, None


def _range(data, bounds):
    start, end = bounds
    return {'start': start, 'end': end, 'start_time': data.bars[start].timestamp.isoformat(),
            'end_time': data.bars[end - 1].end.isoformat(), 'bars': end - start}


def preview_walk_forward(data, plan_payload, paths, saved_source=None):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_presentation import research_controls
    # Load the optional UI adapter only when this operation is requested.
    from quantlab.desktop_runtime import validate_walk_forward_request
    validate_walk_forward_request(plan_payload, saved_source)
    registry = research_controls(paths) / 'holdout-registry.sqlite3'
    if saved_source is None:
        plan = walk_forward_plan_from_dict(plan_payload)
    else:
        # Keep operation-specific dependencies out of module startup.
        from quantlab.saved_candidate_pool import SavedCandidatePoolError
        try:
            plan, rejection = _prepare_saved_plan(data, plan_payload, paths, saved_source, registry)
        except SavedCandidatePoolError as exc:
            return {'admission_status': 'rejected', 'reason_code': exc.reason_code,
                'pool_origin': 'saved_campaign_pool', 'model_calls': 0}
        if rejection is not None: return rejection
    _validate_source(data, plan)
    binding = _binding(data, plan, registry)
    replay = plan.evidence_mode == 'historical_replay'
    return {'preview_identity': content_hash(binding), 'plan': to_dict(plan),
        'source_identity': binding['source_identity'], 'source_data_hash': binding['source_data_hash'],
        'source_type': data.manifest['source_type'], 'source_hashes': binding['source_hashes'],
        'registry_identity': binding['registry_identity'], 'bar_count': len(data.bars),
        'folds': [{'index': i, **{role: _range(data, getattr(fold, role)) for role in ('train', 'validation', 'oos')}} for i, fold in enumerate(plan.folds)],
        'final_holdout': _range(data, plan.final_holdout), 'final_holdout_status': 'excluded_not_evaluated',
        'candidate_pool': [to_dict(spec) for spec in plan.candidate_pool], 'ranking': to_dict(plan.ranking),
        'pool_origin': plan.pool_origin, 'pool_admission': to_dict(plan.pool_admission) if plan.pool_admission is not None else None,
        'candidate_count': len(plan.candidate_pool), 'admission_status': 'admitted',
        'evaluation_limit': plan.max_evaluations, 'planned_evaluations_upper_bound': planned_evaluations(plan),
        'runtime_seconds': plan.max_runtime_seconds, 'model_calls': 0,
        'evidence_mode': plan.evidence_mode, 'exposure_status': 'unverified' if replay else 'synthetic_not_market_evidence',
        'independent_oos': False, 'ranking_eligible': False, 'paper_eligible': False}


def _score(record):
    record = record or {}
    metrics = record.get('result', {}).get('metrics', {})
    return {'status': record.get('status', 'not_evaluated'),
            'metrics': {key: metrics[key] for key in METRICS if key in metrics}}


def compact_walk_forward(state, reference):
    """Bounded IPC projection, never the potentially 16-MiB journal payload."""
    if state['experiment_id'] != reference:
        raise ValidationError('Walk-forward journal reference does not match its binding')
    plan = state['binding']['plan']
    pool = plan['candidate_pool']
    folds = []
    for fold in state['folds']:
        selection = fold['selection']
        folds.append({'index': fold['index'], 'status': fold['status'],
            'winner': selection['spec']['strategy_id'] if selection else None,
            'winner_hash': selection['strategy_hash'] if selection else None,
            'winner_pool_index': selection['pool_index'] if selection else None,
            'candidates': [{'strategy_id': pool[c['pool_index']]['strategy_id'], 'family': pool[c['pool_index']]['family'],
                'pool_index': c['pool_index'], 'strategy_hash': c['strategy_hash'],
                'train': _score(c.get('train')), 'validation': _score(c.get('validation'))} for c in fold['candidates']],
            'oos': _score(fold.get('oos'))})
    return {'reference': reference, 'status': state['status'],
        'display_status': 'running_or_interrupted_no_stop_proof' if state['status'] == 'running' else state['status'],
        'source_identity': state['binding']['source_identity'],
        'source_type': state['source_manifest']['source_type'], 'ranking': plan['ranking'],
        'pool_origin': plan.get('pool_origin', 'exact_builtin_pool'),
        'pool_admission': plan.get('pool_admission'),
        'summary': state['summary'], 'folds': folds,
        'elapsed_seconds': state['elapsed_seconds'], 'journal': 'walk_forward/' + reference + '/walk_forward.sqlite3'}


def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False):
    # Load the optional UI adapter only when this operation is requested.
    from desktop_presentation import _dataset, research_controls
    if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run'):
        required = {'plan'} if operation.endswith('_preview') else {'plan', 'preview_identity'}
        if 'saved_source' in payload:
            if not isinstance(payload.get('plan'), dict) or payload['plan'].get('pool_origin') != 'saved_campaign_pool':
                raise ValidationError('Built-in and saved pools cannot be mixed')
            required = required | {'saved_source'}
        if set(payload) != required:
            raise ValidationError('Unsupported walk-forward request fields')
        data = _dataset(Path(paths.state), {})
        preview = preview_walk_forward(data, payload['plan'], paths, payload.get('saved_source'))
        if operation.endswith('_preview'):
            return preview
        if preview.get('admission_status') == 'rejected':
            raise ValidationError('Saved pool admission changed or failed; preview again before starting')
        identity = preview['preview_identity']
        if payload['preview_identity'] != identity:
            raise ValidationError('Walk-forward source/config/pool changed; preview again before starting')
        output = _folder(paths, identity)
        # Reopening any journal is read-only. In particular, a stale running
        # journal cannot trigger the core's implicit interrupted reconciliation.
        if (output / 'walk_forward.sqlite3').exists():
            return compact_walk_forward(read_walk_forward_state(output), identity)
        source_options = {}
        if payload.get('saved_source') is not None:
            # Keep operation-specific dependencies out of module startup.
            from quantlab.saved_candidate_pool import load_original_dataset
            source = payload['saved_source']
            source_options = {'source_campaign_dir': source_campaign_folder(paths, source['campaign_reference']),
                'original_dataset': load_original_dataset(Path(source['original_dataset']['path']))}
        paths.require_walk_forward_wal()
        state = run_walk_forward(data, plan=walk_forward_plan_from_dict(preview['plan']),
            output_dir=output, holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3', **source_options)
        return compact_walk_forward(state, identity)
    if operation == 'ui_walk_forward_read':
        if set(payload) != {'reference'}:
            raise ValidationError('Unsupported walk-forward read fields')
        return compact_walk_forward(read_walk_forward_state(_folder(paths, payload['reference'])), payload['reference'])
    if operation == 'ui_walk_forward_reconcile':
        if set(payload) != {'reference', 'stopped_job_id'} or descendants_stopped is not True:
            raise ValidationError('Exact stopped walk-forward subtree proof required')
        folder = _folder(paths, payload['reference'])
        if not (folder / 'walk_forward.sqlite3').exists():
            # Cancellation before the worker created its journal has nothing to
            # reconcile. No evaluation or registry reservation is manufactured.
            return {'reference': payload['reference'], 'status': 'stopped_before_journal',
                    'display_status': 'stopped_before_journal'}
        return compact_walk_forward(reconcile_interrupted_walk_forward(output_dir=folder,
            descendants_stopped=True), payload['reference'])
    raise ValidationError('Unsupported walk-forward operation')


FAMILY_NAMES = {'trend': ui_text('walk_forward.labels.text_1'), 'mean_reversion': ui_text('walk_forward.labels.text_2'), 'channel_breakout': ui_text('walk_forward.labels.text_3'),
                'momentum': ui_text('walk_forward.labels.text_4'), 'volatility_compression': ui_text('walk_forward.labels.text_5')}
PARAMETER_NAMES = {'fast': ui_text('walk_forward.labels.text_6'), 'slow': ui_text('walk_forward.labels.text_7'), 'lookback': ui_text('walk_forward.labels.text_8'),
    'entry_bps': ui_text('walk_forward.labels.text_9'), 'threshold_bps': ui_text('walk_forward.labels.text_10'), 'max_holding_bars': ui_text('walk_forward.labels.text_11'),
    'max_range_bps': ui_text('walk_forward.labels.text_12'), 'quantity': ui_text('walk_forward.labels.text_13'), 'stop_ticks': ui_text('walk_forward.labels.text_14'), 'target_ticks': ui_text('walk_forward.labels.text_15')}


ADMISSION_REASONS = {
    'source_duplicate_structure': ui_text('walk_forward.labels.text_16'),
    'source_not_completed': ui_text('walk_forward.labels.text_17'),
    'source_producer_unsupported': ui_text('walk_forward.labels.text_18'),
    'source_dataset_mismatch': ui_text('walk_forward.labels.text_19'),
    'source_temporal_overlap': ui_text('walk_forward.labels.text_20'),
    'source_journal_mismatch': ui_text('walk_forward.labels.text_21'),
    'source_invalid_evidence': ui_text('walk_forward.labels.text_22'),
    'source_candidate_limit': ui_text('walk_forward.labels.text_23'),
    'source_no_evaluated_candidates': ui_text('walk_forward.labels.text_24'),
    'source_missing_evidence': ui_text('walk_forward.labels.text_25'),
    'source_provider_unsupported': ui_text('walk_forward.labels.text_26'),
    'source_manual_exchange_missing': ui_text('walk_forward.labels.text_27'),
    'source_provider_receipt_invalid': ui_text('walk_forward.labels.text_28'),
    'source_provider_provenance_invalid': ui_text('walk_forward.labels.text_29'),
    'source_provider_decimal_context_unsupported': ui_text('walk_forward.labels.text_30'),
    'source_resource_limit': ui_text('walk_forward.labels.text_31'),
    'source_registry_mismatch': ui_text('walk_forward.labels.text_32'),
}


STATUS_LABELS = {
    'running': ui_text('walk_forward.labels.text_33'), 'training': ui_text('walk_forward.labels.text_34'), 'selection_frozen': ui_text('walk_forward.labels.text_35'),
    'running_or_interrupted_no_stop_proof': ui_text('walk_forward.labels.text_36'),
    'completed': ui_text('walk_forward.labels.text_37'), 'completed_with_errors': ui_text('walk_forward.labels.text_38'),
    'evaluated': ui_text('walk_forward.labels.text_39'), 'not_evaluated': ui_text('walk_forward.labels.text_40'), 'failed': ui_text('walk_forward.labels.text_41'),
    'evaluation_failed': ui_text('walk_forward.labels.text_42'), 'timed_out': ui_text('walk_forward.labels.text_43'), 'interrupted': ui_text('walk_forward.labels.text_44'),
    'cancelled': ui_text('walk_forward.labels.text_45'), 'budget_exhausted': ui_text('walk_forward.labels.text_46'),
    'blocked_interrupted': ui_text('walk_forward.labels.text_47'), 'blocked_registry_busy': ui_text('walk_forward.labels.text_48'),
    'blocked_previously_consumed_range': ui_text('walk_forward.labels.text_49'),
    'no_eligible_candidate': ui_text('walk_forward.labels.text_50'), 'stopped_before_journal': ui_text('walk_forward.labels.text_51'),
    'not_verified': ui_text('walk_forward.labels.text_52'), 'unverified': ui_text('walk_forward.labels.text_53'),
    'synthetic_not_market_evidence': ui_text('walk_forward.labels.text_54'),
    'synthetic_validation': ui_text('walk_forward.labels.text_55'), 'historical_replay': ui_text('walk_forward.labels.text_56'),
}


def status_label(value):
    """Display translation only; exact machine values stay in saved evidence."""
    return STATUS_LABELS.get(value, ui_text('walk_forward.status_label.text_1'))


def preview_text(preview, *, advanced=False):
    """Plain-language review by default; exact raw bindings are opt-in details."""
    p = preview
    if advanced:
        return ui_text('walk_forward.preview_text.text_1').format(json.dumps(json.loads(canonical_json(p)), ensure_ascii=False, indent=2))
    if p.get('admission_status') == 'rejected':
        if p.get('reason_code') == 'evaluation_budget_exceeds_pool_bound':
            return (ui_text('walk_forward.preview_text.text_2').format(p['fold_count'], p['candidate_count'], p['planned_evaluations_upper_bound'], p['evaluation_limit'], p['planned_evaluations_upper_bound']))
        reason = ADMISSION_REASONS.get(p.get('reason_code'), ui_text('walk_forward.preview_text.text_3'))
        return ui_text('walk_forward.preview_text.text_4').format(reason)
    saved = p.get('pool_origin', 'exact_builtin_pool') == 'saved_campaign_pool'
    evidence = status_label(p['evidence_mode'])
    mode = ui_text('walk_forward.preview_text.text_5') if p['plan']['mode'] == 'rolling' else ui_text('walk_forward.preview_text.text_6')
    lines = [ui_text('walk_forward.preview_text.text_7').format(mode, evidence, p['bar_count']),
        (ui_text('walk_forward.preview_text.text_8') if saved else ui_text('walk_forward.preview_text.text_9')) + ui_text('walk_forward.preview_text.text_10').format(len(p['candidate_pool'])),
        ui_text('walk_forward.preview_text.text_11'),
        ui_text('walk_forward.preview_text.text_12'),
        ui_text('walk_forward.preview_text.text_13').format(p['evaluation_limit'], len(p['folds']), len(p['candidate_pool']), p['planned_evaluations_upper_bound']),
        ui_text('walk_forward.preview_text.text_14').format(p['runtime_seconds']),
    ]
    if saved:
        provider = p['pool_admission'].get('provider_mode')
        label = {'fixture': ui_text('walk_forward.preview_text.text_15'), 'openai_compatible': ui_text('walk_forward.preview_text.text_16'), 'chatgpt_plan': ui_text('walk_forward.preview_text.text_17')}.get(provider, ui_text('walk_forward.preview_text.text_18'))
        lines.insert(2, ui_text('walk_forward.preview_text.text_19').format(label, status_label(p['pool_admission']['real_model_status'])))
    lines.append(ui_text('walk_forward.preview_text.text_20'))
    for fold in p['folds']:
        lines.append(ui_text('walk_forward.preview_text.text_21').format(str(fold['index'] + 1)))
        for role, label in (('train', ui_text('walk_forward.preview_text.text_22')), ('validation', ui_text('walk_forward.preview_text.text_23')), ('oos', ui_text('walk_forward.preview_text.text_24'))):
            bounds = fold[role]
            lines.append(f"  {label}: [{bounds['start']}, {bounds['end']}) · {bounds['start_time']} → {bounds['end_time']}")
    b = p['final_holdout']
    lines.append(ui_text('walk_forward.preview_text.text_25').format(b['start'], b['end'], b['start_time'], b['end_time']))
    lines.extend([
        ui_text('walk_forward.preview_text.text_26'),
        ui_text('walk_forward.preview_text.text_27').format(str(p['ranking']['minimum']), str(p['ranking']['min_trades']), str(p['ranking']['max_drawdown_pct'])),
        ui_text('walk_forward.preview_text.text_28'),
        ui_text('walk_forward.preview_text.text_29')
    ])
    if saved:
        admission = p['pool_admission']
        lines.extend([ui_text('walk_forward.preview_text.text_30').format(status_label(admission['real_model_status'])),
            ui_text('walk_forward.preview_text.text_31')])
        lines.append(ui_text('walk_forward.preview_text.text_32'))
        for attempt in admission['attempts']:
            status = attempt['source_status']
            reason = ui_text('walk_forward.preview_text.text_33') if attempt['admitted'] else ({
                'rejected': ui_text('walk_forward.preview_text.text_34'),
                'generated': ui_text('walk_forward.preview_text.text_35'),
                'validated': ui_text('walk_forward.preview_text.text_36'),
                'failed': ui_text('walk_forward.preview_text.text_37'),
                'error': ui_text('walk_forward.preview_text.text_38'),
                'timed_out': ui_text('walk_forward.preview_text.text_39')}.get(status, ui_text('walk_forward.preview_text.text_40')))
            if attempt['reason'] == 'source_duplicate_rejected':
                reason = ui_text('walk_forward.preview_text.text_41')
            lines.append(ui_text('walk_forward.preview_text.text_42').format(attempt['sequence'], FAMILY_NAMES.get(attempt['family'], attempt['family']), reason))
    lines.append(ui_text('walk_forward.preview_text.text_43'))
    for index, spec in enumerate(p['candidate_pool'], 1):
        params = ui_text('walk_forward.preview_text.text_44').join(PARAMETER_NAMES.get(k, k) + ' ' + str(v) for k, v in spec['parameters'].items())
        lines.append(f"{index}. {FAMILY_NAMES.get(spec['family'], spec['family'])} · {params}")
    config = p['plan']['backtest_config']; costs = config['costs']
    labels = {'commission_per_side': ui_text('walk_forward.preview_text.text_45'), 'slippage_ticks': ui_text('walk_forward.preview_text.text_46'), 'tax_rate': ui_text('walk_forward.preview_text.text_47')}
    lines.append(ui_text('walk_forward.preview_text.text_49').format(ui_text('walk_forward.preview_text.text_48').join(labels[k] + ' ' + str(costs[k]) for k in labels)))
    lines.append(ui_text('walk_forward.preview_text.text_50').format(str(config['initial_cash']), str(config['max_position'])))
    margins = [(ui_text('walk_forward.preview_text.text_51'), config['initial_margin_per_contract']), (ui_text('walk_forward.preview_text.text_52'), config['maintenance_margin_per_contract'])]
    lines.append(ui_text('walk_forward.preview_text.text_56').format(ui_text('walk_forward.preview_text.text_53').join(ui_text('walk_forward.preview_text.text_55').format(label, str(value) + ' TWD' if value is not None else ui_text('walk_forward.preview_text.text_54')) for label, value in margins)))
    if config['cost_schedule'] or config['margin_schedule']:
        lines.append(ui_text('walk_forward.preview_text.text_57').format(len(config['cost_schedule']), len(config['margin_schedule'])))
    lines.append(ui_text('walk_forward.preview_text.text_58'))
    return '\n'.join(lines)


def result_rows(result):
    rows = []
    for fold in result.get('folds', []):
        for candidate in fold['candidates']:
            winner = (ui_text('walk_forward.result_rows.text_1').format(str(fold['winner_pool_index'] + 1))) if fold.get('winner_pool_index') is not None else (ui_text('walk_forward.result_rows.text_2') if fold['winner'] else ui_text('walk_forward.result_rows.text_3'))
            row = {ui_text('walk_forward.result_rows.text_4'): fold['index'] + 1, ui_text('walk_forward.result_rows.text_5'): status_label(fold['status']), ui_text('walk_forward.result_rows.text_6'): winner,
                   ui_text('walk_forward.result_rows.text_7'): candidate['pool_index'] + 1, ui_text('walk_forward.result_rows.text_8'): FAMILY_NAMES.get(candidate.get('family'), ui_text('walk_forward.result_rows.text_9'))}
            for role, label in (('train', ui_text('walk_forward.result_rows.text_10')), ('validation', ui_text('walk_forward.result_rows.text_11'))):
                score = candidate[role]; row[ui_text('walk_forward.result_rows.text_12').format(label)] = status_label(score['status'])
                for key, caption in (('net_pnl', ui_text('walk_forward.result_rows.text_13')), ('trade_count', ui_text('walk_forward.result_rows.text_14')), ('max_drawdown_pct', ui_text('walk_forward.result_rows.text_15'))):
                    row[label + caption] = score['metrics'].get(key)
            if candidate.get('strategy_hash') is not None and candidate['strategy_hash'] == fold.get('winner_hash'):
                row[ui_text('walk_forward.result_rows.text_16')] = status_label(fold['oos']['status'])
                names = {'net_pnl': ui_text('walk_forward.result_rows.text_17'), 'trade_count': ui_text('walk_forward.result_rows.text_18'), 'max_drawdown_pct': ui_text('walk_forward.result_rows.text_19'),
                    'max_drawdown': ui_text('walk_forward.result_rows.text_20'), 'total_costs': ui_text('walk_forward.result_rows.text_21'), 'realized_gross_pnl': ui_text('walk_forward.result_rows.text_22'),
                    'unrealized_pnl': ui_text('walk_forward.result_rows.text_23'), 'return': ui_text('walk_forward.result_rows.text_24'), 'open_position': ui_text('walk_forward.result_rows.text_25')}
                for key, value in fold['oos']['metrics'].items(): row[ui_text('walk_forward.result_rows.text_26').format(names[key])] = value
            rows.append(row)
        if not fold['candidates']:
            rows.append({ui_text('walk_forward.result_rows.text_27'): fold['index'] + 1, ui_text('walk_forward.result_rows.text_28'): status_label(fold['status']), ui_text('walk_forward.result_rows.text_29'): ui_text('walk_forward.result_rows.text_30')})
    return rows
