from desktop_app.strings.catalog import ui_text
from quantlab.core import canonical_json


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
                (
                    ANALYSIS_METRICS.get(key, key) + '=' + (ui_text('ui.analysis_preview_text.unavailable') if value is None else str(value))
                    for key, value in row['metrics'].items()
                )
            )
        )
    lines.append(ui_text('ui.analysis_preview_text.evidence_hint'))
    return '\n'.join(lines)


def analysis_record_text(record):
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
            ui_text('ui.analysis_record_text.candidate').format(', '.join((value[:16] for value in row['strategy_hashes']))),
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
