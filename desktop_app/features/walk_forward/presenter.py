import json
from desktop_app.strings.catalog import ui_text
from quantlab.core import canonical_json
from quantlab import significance as _significance
from quantlab import verdict as _verdict
from quantlab.research_core.application.walk_forward_projection import oos_statistics_data

'Typed desktop boundary for the frozen, offline walk-forward protocol.\n\nNo provider calls, paper qualification/selection or final-holdout evaluation.\nPreview is read-only; a run revalidates every source/config binding before scoring.\n'

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
    data = state.get('oos_statistics') or oos_statistics_data(state)
    title = ui_text('walk_forward.statistics.title')
    if not data['available']:
        return title + '\n' + ui_text('walk_forward.verdict.run_unavailable')
    merged = data
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
        if merged['reason'] == 'no_evaluated_folds':
            return title + '\n' + reasons[merged['reason']]
        return title + '\n' + reasons[merged['reason']] + '\n' + ui_text('walk_forward.decline.line').format(reasons[merged['reason']])
    stats = data['stats']
    required = data['required']
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
    decline = data['decline']
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
            _verdict_text(data['verdict']),
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


def _verdict_text(conclusion):
    names = {
        _verdict.INSUFFICIENT: (ui_text('walk_forward.verdict.insufficient.name'), ui_text('walk_forward.verdict.insufficient.explanation')),
        _verdict.NEGATIVE_EXPECTANCY: (
            ui_text('walk_forward.verdict.negative_expectancy.name'),
            ui_text('walk_forward.verdict.negative_expectancy.explanation'),
        ),
        _verdict.LUCK_SUSPECTED: (ui_text('walk_forward.verdict.luck_suspected.name'), ui_text('walk_forward.verdict.luck_suspected.explanation')),
        _verdict.FRAGILE_EDGE: (ui_text('walk_forward.verdict.fragile_edge.name'), ui_text('walk_forward.verdict.fragile_edge.explanation')),
        _verdict.STATISTICAL_EDGE: (ui_text('walk_forward.verdict.statistical_edge.name'), ui_text('walk_forward.verdict.statistical_edge.explanation')),
    }
    name, explanation = names[conclusion['level']]
    lines = [ui_text('walk_forward.verdict.line').format(name, explanation), ui_text('walk_forward.verdict.scope')]
    if conclusion['recommended_observations'] is not None:
        lines.append(ui_text('walk_forward.verdict.recommended').format(conclusion['recommended_observations']))
    elif conclusion['level'] == _verdict.INSUFFICIENT:
        lines.append(ui_text('walk_forward.verdict.required_unavailable'))
    if 'severe_drawdown' in conclusion['reasons']:
        lines.append(ui_text('walk_forward.verdict.severe_drawdown'))
    return '\n'.join(lines)


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
                else {
                    'rejected': ui_text('walk_forward.preview_text.structure_rejected'),
                    'generated': ui_text('walk_forward.preview_text.unevaluated_candidate'),
                    'validated': ui_text('walk_forward.preview_text.incomplete_candidate'),
                    'failed': ui_text('walk_forward.preview_text.failed_candidate'),
                    'error': ui_text('walk_forward.preview_text.failed_candidate'),
                    'timed_out': ui_text('walk_forward.preview_text.timed_out_candidate'),
                }.get(status, ui_text('walk_forward.preview_text.invalid_candidate'))
            )
            if attempt['reason'] == 'source_duplicate_rejected':
                reason = ui_text('walk_forward.preview_text.duplicate_candidate')
            lines.append(
                ui_text('walk_forward.preview_text.attempt_row').format(attempt['sequence'], FAMILY_NAMES.get(attempt['family'], attempt['family']), reason)
            )
    lines.append(ui_text('walk_forward.preview_text.fixed_candidates'))
    for index, spec in enumerate(p['candidate_pool'], 1):
        params = ui_text('walk_forward.preview_text.cost_separator').join((PARAMETER_NAMES.get(k, k) + ' ' + str(v) for k, v in spec['parameters'].items()))
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
            ui_text('walk_forward.preview_text.cost_separator').join((labels[k] + ' ' + str(costs[k]) for k in labels))
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
                (
                    ui_text('walk_forward.preview_text.named_value').format(
                        label, str(value) + ' TWD' if value is not None else ui_text('walk_forward.preview_text.not_set')
                    )
                    for label, value in margins
                )
            )
        )
    )
    if config['cost_schedule'] or config['margin_schedule']:
        lines.append(ui_text('walk_forward.preview_text.policy_changes').format(len(config['cost_schedule']), len(config['margin_schedule'])))
    lines.append(ui_text('walk_forward.preview_text.advanced_hint'))
    return '\n'.join(lines)


def compact_walk_forward(state, reference):
    """Render the compact application projection for desktop evidence views."""
    # Load the application projection only for completed result rendering.
    from quantlab.research_core.application.walk_forward_projection import compact_walk_forward as project

    result = project(state, reference)
    return render_result(result)


def render_result(result):
    if 'oos_statistics' in result:
        result['oos_statistics_text'] = oos_statistics_text(result)
        del result['oos_statistics']
    return result


def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False, inputs):
    """Render application results at the Qt-free desktop operation boundary."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research_core.application.walk_forward_operations import execute_walk_forward as execute

    return render_result(execute(operation, payload, paths, descendants_stopped=descendants_stopped, inputs=inputs))
