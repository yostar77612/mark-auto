"""Typed desktop boundary for the frozen, offline walk-forward protocol.

No provider calls, paper qualification/selection or final-holdout evaluation.
Preview is read-only; a run revalidates every source/config binding before scoring.
"""

from desktop_strings import ui_text
from pathlib import Path
import json
import re
from quantlab import significance as _significance

from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.walk_forward import (
    _validate_source,
    walk_forward_plan_from_dict,
    walk_forward_binding,
    planned_evaluations,
    run_walk_forward,
    read_walk_forward_state,
    reconcile_interrupted_walk_forward,
)


METRICS = ('net_pnl', 'trade_count', 'max_drawdown_pct', 'max_drawdown', 'total_costs', 'realized_gross_pnl', 'unrealized_pnl', 'return', 'open_position')


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
    admitted = admit_saved_campaign_pool(
        source_campaign_dir=folder,
        source_campaign_ref=saved_source['campaign_reference'],
        original_dataset=original,
        original_dataset_ref=str(path),
        first_training_timestamp=data.bars[chronology.folds[0].train[0]].timestamp,
        authoritative_registry_path=registry,
    )
    pool, admission = admitted.candidate_pool, to_dict(admitted.admission)
    bound = len(chronology.folds) * (2 * len(pool) + 1)
    if plan_payload['max_evaluations'] > bound:
        return None, {
            'admission_status': 'rejected',
            'reason_code': 'evaluation_budget_exceeds_pool_bound',
            'candidate_count': len(pool),
            'fold_count': len(chronology.folds),
            'evaluation_limit': plan_payload['max_evaluations'],
            'planned_evaluations_upper_bound': bound,
            'pool_origin': 'saved_campaign_pool',
            'pool_admission': admission,
            'candidate_pool': [to_dict(spec) for spec in pool],
            'model_calls': 0,
        }
    plan = walk_forward_plan_from_dict({**plan_payload, 'candidate_pool': [to_dict(spec) for spec in pool], 'pool_admission': admission})
    return plan, None


def _range(data, bounds):
    start, end = bounds
    return {
        'start': start,
        'end': end,
        'start_time': data.bars[start].timestamp.isoformat(),
        'end_time': data.bars[end - 1].end.isoformat(),
        'bars': end - start,
    }


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
            return {'admission_status': 'rejected', 'reason_code': exc.reason_code, 'pool_origin': 'saved_campaign_pool', 'model_calls': 0}
        if rejection is not None:
            return rejection
    _validate_source(data, plan)
    binding = _binding(data, plan, registry)
    replay = plan.evidence_mode == 'historical_replay'
    return {
        'preview_identity': content_hash(binding),
        'plan': to_dict(plan),
        'source_identity': binding['source_identity'],
        'source_data_hash': binding['source_data_hash'],
        'source_type': data.manifest['source_type'],
        'source_hashes': binding['source_hashes'],
        'registry_identity': binding['registry_identity'],
        'bar_count': len(data.bars),
        'folds': [{'index': i, **{role: _range(data, getattr(fold, role)) for role in ('train', 'validation', 'oos')}} for i, fold in enumerate(plan.folds)],
        'final_holdout': _range(data, plan.final_holdout),
        'final_holdout_status': 'excluded_not_evaluated',
        'candidate_pool': [to_dict(spec) for spec in plan.candidate_pool],
        'ranking': to_dict(plan.ranking),
        'pool_origin': plan.pool_origin,
        'pool_admission': to_dict(plan.pool_admission) if plan.pool_admission is not None else None,
        'candidate_count': len(plan.candidate_pool),
        'admission_status': 'admitted',
        'evaluation_limit': plan.max_evaluations,
        'planned_evaluations_upper_bound': planned_evaluations(plan),
        'runtime_seconds': plan.max_runtime_seconds,
        'model_calls': 0,
        'evidence_mode': plan.evidence_mode,
        'exposure_status': 'unverified' if replay else 'synthetic_not_market_evidence',
        'independent_oos': False,
        'ranking_eligible': False,
        'paper_eligible': False,
    }


def _score(record):
    record = record or {}
    metrics = record.get('result', {}).get('metrics', {})
    return {'status': record.get('status', 'not_evaluated'), 'metrics': {key: metrics[key] for key in METRICS if key in metrics}}


def compact_walk_forward(state, reference):
    """Bounded IPC projection, never the potentially 16-MiB journal payload."""
    if state['experiment_id'] != reference:
        raise ValidationError('Walk-forward journal reference does not match its binding')
    plan = state['binding']['plan']
    pool = plan['candidate_pool']
    folds = []
    for fold in state['folds']:
        selection = fold['selection']
        folds.append(
            {
                'index': fold['index'],
                'status': fold['status'],
                'winner': selection['spec']['strategy_id'] if selection else None,
                'winner_hash': selection['strategy_hash'] if selection else None,
                'winner_pool_index': selection['pool_index'] if selection else None,
                'candidates': [
                    {
                        'strategy_id': pool[c['pool_index']]['strategy_id'],
                        'family': pool[c['pool_index']]['family'],
                        'pool_index': c['pool_index'],
                        'strategy_hash': c['strategy_hash'],
                        'train': _score(c.get('train')),
                        'validation': _score(c.get('validation')),
                    }
                    for c in fold['candidates']
                ],
                'oos': _score(fold.get('oos')),
            }
        )
    return {
        'reference': reference,
        'status': state['status'],
        'display_status': 'running_or_interrupted_no_stop_proof' if state['status'] == 'running' else state['status'],
        'source_identity': state['binding']['source_identity'],
        'source_type': state['source_manifest']['source_type'],
        'ranking': plan['ranking'],
        'pool_origin': plan.get('pool_origin', 'exact_builtin_pool'),
        'pool_admission': plan.get('pool_admission'),
        'summary': state['summary'],
        'folds': folds,
        'elapsed_seconds': state['elapsed_seconds'],
        'journal': 'walk_forward/' + reference + '/walk_forward.sqlite3',
        'oos_statistics_text': oos_statistics_text(state),
    }


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
            source_options = {
                'source_campaign_dir': source_campaign_folder(paths, source['campaign_reference']),
                'original_dataset': load_original_dataset(Path(source['original_dataset']['path'])),
            }
        paths.require_walk_forward_wal()
        state = run_walk_forward(
            data,
            plan=walk_forward_plan_from_dict(preview['plan']),
            output_dir=output,
            holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3',
            **source_options,
        )
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
            return {'reference': payload['reference'], 'status': 'stopped_before_journal', 'display_status': 'stopped_before_journal'}
        return compact_walk_forward(reconcile_interrupted_walk_forward(output_dir=folder, descendants_stopped=True), payload['reference'])
    raise ValidationError('Unsupported walk-forward operation')


FAMILY_NAMES = {
    'trend': ui_text('walk_forward.labels.trend'),
    'mean_reversion': ui_text('walk_forward.labels.mean_reversion'),
    'channel_breakout': ui_text('walk_forward.labels.breakout'),
    'momentum': ui_text('walk_forward.labels.momentum'),
    'volatility_compression': ui_text('walk_forward.labels.volatility'),
}
PARAMETER_NAMES = {
    'fast': ui_text('walk_forward.labels.fast_bars'),
    'slow': ui_text('walk_forward.labels.slow_bars'),
    'lookback': ui_text('walk_forward.labels.lookback_bars'),
    'entry_bps': ui_text('walk_forward.labels.entry_bps'),
    'threshold_bps': ui_text('walk_forward.labels.threshold_bps'),
    'max_holding_bars': ui_text('walk_forward.labels.max_holding_bars'),
    'max_range_bps': ui_text('walk_forward.labels.max_range_bps'),
    'quantity': ui_text('walk_forward.labels.quantity'),
    'stop_ticks': ui_text('walk_forward.labels.stop_ticks'),
    'target_ticks': ui_text('walk_forward.labels.target_ticks'),
}


ADMISSION_REASONS = {
    'source_duplicate_structure': ui_text('walk_forward.labels.duplicate_structure'),
    'source_not_completed': ui_text('walk_forward.labels.source_incomplete'),
    'source_producer_unsupported': ui_text('walk_forward.labels.unsupported_producer'),
    'source_dataset_mismatch': ui_text('walk_forward.labels.dataset_identity_mismatch'),
    'source_temporal_overlap': ui_text('walk_forward.labels.chronology_mismatch'),
    'source_journal_mismatch': ui_text('walk_forward.labels.transaction_mismatch'),
    'source_invalid_evidence': ui_text('walk_forward.labels.evidence_unverifiable'),
    'source_candidate_limit': ui_text('walk_forward.labels.pool_size_limit'),
    'source_no_evaluated_candidates': ui_text('walk_forward.labels.no_valid_candidates'),
    'source_missing_evidence': ui_text('walk_forward.labels.source_missing'),
    'source_provider_unsupported': ui_text('walk_forward.labels.unsupported_provider'),
    'source_manual_exchange_missing': ui_text('walk_forward.labels.manual_evidence_missing'),
    'source_provider_receipt_invalid': ui_text('walk_forward.labels.request_evidence_mismatch'),
    'source_provider_provenance_invalid': ui_text('walk_forward.labels.producer_unverifiable'),
    'source_provider_decimal_context_unsupported': ui_text('walk_forward.labels.decimal_context_missing'),
    'source_resource_limit': ui_text('walk_forward.labels.source_size_limit'),
    'source_registry_mismatch': ui_text('walk_forward.labels.registry_mismatch'),
}


STATUS_LABELS = {
    'running': ui_text('walk_forward.labels.running'),
    'training': ui_text('walk_forward.labels.training'),
    'selection_frozen': ui_text('walk_forward.labels.winner_locked'),
    'running_or_interrupted_no_stop_proof': ui_text('walk_forward.labels.stop_unconfirmed'),
    'completed': ui_text('walk_forward.labels.completed'),
    'completed_with_errors': ui_text('walk_forward.labels.completed_with_failures'),
    'evaluated': ui_text('walk_forward.labels.evaluated'),
    'not_evaluated': ui_text('walk_forward.labels.unevaluated'),
    'failed': ui_text('walk_forward.labels.evaluation_failed'),
    'evaluation_failed': ui_text('walk_forward.labels.evaluation_failed'),
    'timed_out': ui_text('walk_forward.labels.timed_out'),
    'interrupted': ui_text('walk_forward.labels.interrupted'),
    'cancelled': ui_text('walk_forward.labels.cancelled'),
    'budget_exhausted': ui_text('walk_forward.labels.budget_exhausted'),
    'blocked_interrupted': ui_text('walk_forward.labels.retry_blocked'),
    'blocked_registry_busy': ui_text('walk_forward.labels.registry_busy'),
    'blocked_previously_consumed_range': ui_text('walk_forward.labels.range_consumed'),
    'no_eligible_candidate': ui_text('walk_forward.labels.no_qualified_candidate'),
    'stopped_before_journal': ui_text('walk_forward.labels.stopped_before_record'),
    'not_verified': ui_text('walk_forward.labels.unverified'),
    'unverified': ui_text('walk_forward.labels.unverified'),
    'synthetic_not_market_evidence': ui_text('walk_forward.labels.synthetic_not_market'),
    'synthetic_validation': ui_text('walk_forward.labels.synthetic_only'),
    'historical_replay': ui_text('walk_forward.labels.historical_exposure_unverified'),
}


def status_label(value):
    """Display translation only; exact machine values stay in saved evidence."""
    return STATUS_LABELS.get(value, ui_text('walk_forward.status_label.no_confirmed_record'))


def oos_statistics_text(state):
    """Qt-free, worker-only derived text; never project raw daily returns to IPC."""
    merged = _significance.merge_oos_daily_returns(state)
    title = ui_text('walk_forward.statistics.title')
    if merged['reason']:
        reasons = {
            'holdout_status_unconfirmed': ui_text('walk_forward.statistics.holdout_unconfirmed'),
            'fold_limit_exceeded': ui_text('walk_forward.statistics.fold_limit'),
            'fold_index_invalid': ui_text('walk_forward.statistics.fold_index'),
            'daily_returns_missing': ui_text('walk_forward.statistics.missing'),
            'daily_returns_invalid': ui_text('walk_forward.statistics.invalid'),
            'dates_not_strictly_increasing': ui_text('walk_forward.statistics.overlap'),
            'no_evaluated_folds': ui_text('walk_forward.statistics.no_folds'),
        }
        return title + '\n' + reasons[merged['reason']] + '\n' + ui_text('walk_forward.decline.line').format(reasons[merged['reason']])
    stats = _significance.mean_positive_test(merged['returns'])
    required = _significance.required_observations(merged['returns'])
    reasons = {
        _significance.MISSING: ui_text('walk_forward.statistics.missing_value'),
        _significance.NONFINITE: ui_text('walk_forward.statistics.nonfinite'),
        _significance.OUT_OF_RANGE: ui_text('walk_forward.statistics.range'),
        _significance.TOO_FEW: ui_text('walk_forward.statistics.too_few'),
        _significance.ZERO_VARIANCE: ui_text('walk_forward.statistics.zero_variance'),
        _significance.TEST_RANGE: ui_text('walk_forward.statistics.test_range'),
        _significance.BOOTSTRAP_INVALID: ui_text('walk_forward.statistics.bootstrap_invalid'),
        _significance.NONPOSITIVE: ui_text('walk_forward.statistics.nonpositive'),
        _significance.REQUIRED_CAP: ui_text('walk_forward.statistics.required_cap'),
        'fewer_than_two_evaluated_folds': ui_text('walk_forward.decline.too_few_folds'),
    }
    decline = _significance.oos_decline_test(state)
    decline_labels = {
        'significant_decline': ui_text('walk_forward.decline.significant_decline'),
        'significant_increase': ui_text('walk_forward.decline.significant_increase'),
        'no_significant_difference': ui_text('walk_forward.decline.no_significant_difference'),
    }
    decline_text = decline_labels[decline['classification']] if decline['classification'] else reasons[decline['reason']]

    def value(key):
        return str(stats[key]) if stats[key] is not None else reasons[stats[key + '_reason']]

    return '\n'.join(
        (
            title,
            ui_text('walk_forward.statistics.source'),
            ui_text('walk_forward.statistics.days').format(value('n')),
            ui_text('walk_forward.statistics.mean').format(value('mean')),
            ui_text('walk_forward.statistics.p_values').format(value('p_value_t'), value('p_value_bootstrap')),
            ui_text('walk_forward.statistics.interval').format(value('ci_lower'), value('ci_upper')),
            ui_text('walk_forward.statistics.required').format(
                value('n'), required['required_observations'] or reasons[required['required_observations_reason']]
            ),
            ui_text('walk_forward.statistics.draws').format(value('n_bootstrap_actual'), merged['skipped_folds']),
            ui_text('walk_forward.statistics.explanation'),
            ui_text('walk_forward.decline.line').format(decline_text),
        )
    )


def preview_text(preview, *, advanced=False):
    """Plain-language review by default; exact raw bindings are opt-in details."""
    p = preview
    if advanced:
        return ui_text('walk_forward.preview_text.full_source_evidence').format(json.dumps(json.loads(canonical_json(p)), ensure_ascii=False, indent=2))
    if p.get('admission_status') == 'rejected':
        if p.get('reason_code') == 'evaluation_budget_exceeds_pool_bound':
            return ui_text('walk_forward.preview_text.budget_adjustment_required').format(
                p['fold_count'], p['candidate_count'], p['planned_evaluations_upper_bound'], p['evaluation_limit'], p['planned_evaluations_upper_bound']
            )
        reason = ADMISSION_REASONS.get(p.get('reason_code'), ui_text('walk_forward.preview_text.source_evidence_invalid'))
        return ui_text('walk_forward.preview_text.pool_rejected').format(reason)
    saved = p.get('pool_origin', 'exact_builtin_pool') == 'saved_campaign_pool'
    evidence = status_label(p['evidence_mode'])
    mode = ui_text('walk_forward.preview_text.rolling_window') if p['plan']['mode'] == 'rolling' else ui_text('walk_forward.preview_text.anchored_window')
    lines = [
        ui_text('walk_forward.preview_text.training_window').format(mode, evidence, p['bar_count']),
        (ui_text('walk_forward.preview_text.saved_pool') if saved else ui_text('walk_forward.preview_text.builtin_pool'))
        + ui_text('walk_forward.preview_text.candidate_count').format(len(p['candidate_pool'])),
        ui_text('walk_forward.preview_text.irreversible_consumption'),
        ui_text('walk_forward.preview_text.holdout_excluded'),
        ui_text('walk_forward.preview_text.evaluation_budget').format(
            p['evaluation_limit'], len(p['folds']), len(p['candidate_pool']), p['planned_evaluations_upper_bound']
        ),
        ui_text('walk_forward.preview_text.time_budget').format(p['runtime_seconds']),
    ]
    if saved:
        provider = p['pool_admission'].get('provider_mode')
        label = {
            'fixture': ui_text('walk_forward.preview_text.fixture_generator'),
            'openai_compatible': ui_text('walk_forward.preview_text.compatible_provider'),
            'chatgpt_plan': ui_text('walk_forward.preview_text.chatgpt_source'),
        }.get(provider, ui_text('walk_forward.preview_text.saved_source'))
        lines.insert(2, ui_text('walk_forward.preview_text.generator_model_status').format(label, status_label(p['pool_admission']['real_model_status'])))
    lines.append(ui_text('walk_forward.preview_text.precise_ranges'))
    for fold in p['folds']:
        lines.append(ui_text('walk_forward.preview_text.fold_number').format(str(fold['index'] + 1)))
        for role, label in (
            ('train', ui_text('walk_forward.preview_text.training')),
            ('validation', ui_text('walk_forward.preview_text.validation')),
            ('oos', ui_text('walk_forward.preview_text.forward_oos')),
        ):
            bounds = fold[role]
            lines.append(f"  {label}: [{bounds['start']}, {bounds['end']}) · {bounds['start_time']} → {bounds['end_time']}")
    b = p['final_holdout']
    lines.append(ui_text('walk_forward.preview_text.holdout_range').format(b['start'], b['end'], b['start_time'], b['end_time']))
    lines.extend(
        [
            ui_text('walk_forward.preview_text.exposure_warning'),
            ui_text('walk_forward.preview_text.validation_thresholds').format(
                str(p['ranking']['minimum']), str(p['ranking']['min_trades']), str(p['ranking']['max_drawdown_pct'])
            ),
            ui_text('walk_forward.preview_text.winner_selection'),
            ui_text('walk_forward.preview_text.split_warmup'),
        ]
    )
    if saved:
        admission = p['pool_admission']
        lines.extend(
            [
                ui_text('walk_forward.preview_text.source_model_status').format(status_label(admission['real_model_status'])),
                ui_text('walk_forward.preview_text.local_consistency_only'),
            ]
        )
        lines.append(ui_text('walk_forward.preview_text.source_attempts'))
        for attempt in admission['attempts']:
            status = attempt['source_status']
            reason = (
                ui_text('walk_forward.preview_text.included_candidate')
                if attempt['admitted']
                else (
                    {
                        'rejected': ui_text('walk_forward.preview_text.structure_rejected'),
                        'generated': ui_text('walk_forward.preview_text.unevaluated_candidate'),
                        'validated': ui_text('walk_forward.preview_text.incomplete_candidate'),
                        'failed': ui_text('walk_forward.preview_text.failed_candidate'),
                        'error': ui_text('walk_forward.preview_text.failed_candidate'),
                        'timed_out': ui_text('walk_forward.preview_text.timed_out_candidate'),
                    }.get(status, ui_text('walk_forward.preview_text.invalid_candidate'))
                )
            )
            if attempt['reason'] == 'source_duplicate_rejected':
                reason = ui_text('walk_forward.preview_text.duplicate_candidate')
            lines.append(
                ui_text('walk_forward.preview_text.attempt_row').format(attempt['sequence'], FAMILY_NAMES.get(attempt['family'], attempt['family']), reason)
            )
    lines.append(ui_text('walk_forward.preview_text.fixed_candidates'))
    for index, spec in enumerate(p['candidate_pool'], 1):
        params = ui_text('walk_forward.preview_text.cost_separator').join(PARAMETER_NAMES.get(k, k) + ' ' + str(v) for k, v in spec['parameters'].items())
        lines.append(f"{index}. {FAMILY_NAMES.get(spec['family'], spec['family'])} · {params}")
    config = p['plan']['backtest_config']
    costs = config['costs']
    labels = {
        'commission_per_side': ui_text('walk_forward.preview_text.commission'),
        'slippage_ticks': ui_text('walk_forward.preview_text.slippage'),
        'tax_rate': ui_text('walk_forward.preview_text.tax_rate'),
    }
    lines.append(
        ui_text('walk_forward.preview_text.explicit_costs').format(
            ui_text('walk_forward.preview_text.cost_separator').join(labels[k] + ' ' + str(costs[k]) for k in labels)
        )
    )
    lines.append(ui_text('walk_forward.preview_text.initial_cash_position').format(str(config['initial_cash']), str(config['max_position'])))
    margins = [
        (ui_text('walk_forward.preview_text.initial_margin'), config['initial_margin_per_contract']),
        (ui_text('walk_forward.preview_text.maintenance_margin'), config['maintenance_margin_per_contract']),
    ]
    lines.append(
        ui_text('walk_forward.preview_text.per_contract').format(
            ui_text('walk_forward.preview_text.cost_separator').join(
                ui_text('walk_forward.preview_text.named_value').format(
                    label, str(value) + ' TWD' if value is not None else ui_text('walk_forward.preview_text.not_set')
                )
                for label, value in margins
            )
        )
    )
    if config['cost_schedule'] or config['margin_schedule']:
        lines.append(ui_text('walk_forward.preview_text.policy_changes').format(len(config['cost_schedule']), len(config['margin_schedule'])))
    lines.append(ui_text('walk_forward.preview_text.advanced_hint'))
    return '\n'.join(lines)


def result_rows(result):
    rows = []
    for fold in result.get('folds', []):
        for candidate in fold['candidates']:
            winner = (
                (ui_text('walk_forward.result_rows.candidate_number').format(str(fold['winner_pool_index'] + 1)))
                if fold.get('winner_pool_index') is not None
                else (ui_text('walk_forward.result_rows.selected') if fold['winner'] else ui_text('walk_forward.result_rows.none'))
            )
            row = {
                ui_text('walk_forward.result_rows.fold'): fold['index'] + 1,
                ui_text('walk_forward.result_rows.status'): status_label(fold['status']),
                ui_text('walk_forward.result_rows.winner'): winner,
                ui_text('walk_forward.result_rows.candidate_index'): candidate['pool_index'] + 1,
                ui_text('walk_forward.result_rows.candidate'): FAMILY_NAMES.get(candidate.get('family'), ui_text('walk_forward.result_rows.saved_candidate')),
            }
            for role, label in (('train', ui_text('walk_forward.result_rows.training')), ('validation', ui_text('walk_forward.result_rows.validation'))):
                score = candidate[role]
                row[ui_text('walk_forward.result_rows.segment_status').format(label)] = status_label(score['status'])
                for key, caption in (
                    ('net_pnl', ui_text('walk_forward.result_rows.net_pnl')),
                    ('trade_count', ui_text('walk_forward.result_rows.closed_lots')),
                    ('max_drawdown_pct', ui_text('walk_forward.result_rows.max_drawdown_ratio')),
                ):
                    row[label + caption] = score['metrics'].get(key)
            if candidate.get('strategy_hash') is not None and candidate['strategy_hash'] == fold.get('winner_hash'):
                row[ui_text('walk_forward.result_rows.forward_status')] = status_label(fold['oos']['status'])
                names = {
                    'net_pnl': ui_text('walk_forward.result_rows.net_pnl'),
                    'trade_count': ui_text('walk_forward.result_rows.closed_lots'),
                    'max_drawdown_pct': ui_text('walk_forward.result_rows.max_drawdown_ratio'),
                    'max_drawdown': ui_text('walk_forward.result_rows.max_drawdown'),
                    'total_costs': ui_text('walk_forward.result_rows.total_cost'),
                    'realized_gross_pnl': ui_text('walk_forward.result_rows.realized_gross_pnl'),
                    'unrealized_pnl': ui_text('walk_forward.result_rows.unrealized_pnl'),
                    'return': ui_text('walk_forward.result_rows.return_ratio'),
                    'open_position': ui_text('walk_forward.result_rows.open_quantity'),
                }
                for key, value in fold['oos']['metrics'].items():
                    row[ui_text('walk_forward.result_rows.forward_fold').format(names[key])] = value
            rows.append(row)
        if not fold['candidates']:
            rows.append(
                {
                    ui_text('walk_forward.result_rows.fold'): fold['index'] + 1,
                    ui_text('walk_forward.result_rows.status'): status_label(fold['status']),
                    ui_text('walk_forward.result_rows.winner'): ui_text('walk_forward.result_rows.none'),
                }
            )
    return rows
