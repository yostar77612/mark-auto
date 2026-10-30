"""desktop_app features strategy summary responsibilities."""

from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
import re
from desktop_app.features.walk_forward.presenter import STATUS_LABELS
from desktop_app.components.result_tables import RESULT_LABELS, SummaryCard
from desktop_app.features.backtest.summary import _report_number, _report_text


_CANDIDATE_EVALUATION_LABELS = STATUS_LABELS


def candidate_summary_text(values, *, private=False):
    """Bounded view of saved split records; never recalculate qualification."""

    def eligibility(value):
        return (
            ui_text('forms.eligibility.passed')
            if value is True
            else ui_text('forms.eligibility.failed')
            if value is False
            else ui_text('forms.eligibility.not_provided')
        )

    def metric(metrics, key):
        if private and key in _privacy.MONEY_FIELDS:
            return _privacy.mask_money(None)
        value = metrics.get(key)
        if value is None:
            return ui_text('forms.metric.undefined') if key in metrics and key in ('profit_factor', 'sharpe') else ui_text('forms.metric.not_provided')
        return _report_number(value, key)

    def reason(metrics, key):
        value, explanation = metrics.get(key), metrics.get(key + '_reason')
        if value is not None and _report_number(value) == ui_text('forms.reason.diagnostics_required'):
            return ui_text('forms.reason.unknown_metric')
        return ui_text('forms.reason.not_applicable') if explanation is None and value is not None else _report_text(explanation)

    name = values.get(ui_text('forms.candidate_summary_text.strategy'))
    if not isinstance(name, str):
        name = ui_text('forms.candidate_summary_text.not_provided')
    elif re.fullmatch('[0-9a-fA-F]{64}', name):
        name = ui_text('forms.candidate_summary_text.abbreviated_id').format(name[:12])
    else:
        name = ' '.join(name.split())[:80] + (ui_text('forms.candidate_summary_text.truncated_name') if len(name) > 80 else '')
    lines = [
        ui_text('forms.candidate_summary_text.candidate_strategy').format(name),
        ui_text('forms.candidate_summary_text.saved_paper_gate').format(eligibility(values.get(ui_text('forms.candidate_summary_text.paper_eligibility')))),
        ui_text('forms.candidate_summary_text.eligibility_disclaimer'),
    ]
    evaluations = values.get(ui_text('forms.candidate_summary_text.oos_holdout'))
    evaluations = evaluations if isinstance(evaluations, dict) else {}
    for split, title in (('oos', ui_text('forms.candidate_summary_text.out_of_sample')), ('holdout', ui_text('forms.candidate_summary_text.final_holdout'))):
        saved = evaluations.get(split)
        saved = saved if isinstance(saved, dict) else {}
        row = saved.get('evaluation')
        row = row if isinstance(row, dict) else {}
        state = row.get('status')
        status = (
            ui_text('forms.candidate_summary_text.no_saved_evaluation')
            if not row
            else ui_text('forms.candidate_summary_text.not_provided')
            if state is None
            else _CANDIDATE_EVALUATION_LABELS.get(state, ui_text('forms.candidate_summary_text.unknown_status'))
            if isinstance(state, str)
            else ui_text('forms.candidate_summary_text.unknown_status')
        )
        metrics = row.get('metrics')
        metrics = metrics if isinstance(metrics, dict) else {}
        headline = ['net_pnl'] + (['max_drawdown'] if 'max_drawdown' in metrics else []) + ['max_drawdown_pct']
        headline.append('closed_trades' if 'trade_count' not in metrics and 'closed_trades' in metrics else 'trade_count')
        lines.extend(
            (
                '',
                ui_text('forms.candidate_summary_text.segment_status').format(title, status, eligibility(saved.get("qualified"))),
                ui_text('forms.candidate_summary_text.field_separator').join(
                    ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], metric(metrics, key)) for key in headline
                ),
            )
        )
        for key in ('profit_factor', 'sharpe'):
            lines.append(ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], metric(metrics, key)))
            if key in metrics or key + '_reason' in metrics:
                lines.append(ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key + '_reason'], reason(metrics, key)))
            if key == 'profit_factor' and key in metrics:
                lines.append(ui_text('forms.candidate_summary_text.profit_factor_basis').format(_report_text(metrics.get('profit_factor_basis'))))
        if 'sharpe' in metrics:
            lines.append(
                ui_text('forms.candidate_summary_text.field_separator').join(
                    ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_number(metrics.get(key)))
                    for key in ('sharpe_observations', 'sharpe_sample_count')
                )
            )
            assumptions = metrics.get('annualization')
            if isinstance(assumptions, dict):
                lines.append(
                    ui_text('forms.candidate_summary_text.field_separator').join(
                        ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_number(assumptions.get(key), key))
                        for key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                    )
                )
                lines.append(
                    ui_text('forms.candidate_summary_text.item_separator').join(
                        ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_text(assumptions.get(key)))
                        for key in ('return_frequency', 'first_return', 'missing_dates', 'standard_deviation')
                    )
                )
            else:
                lines.append(ui_text('forms.candidate_summary_text.annualization_missing'))
            lines.append(ui_text('forms.candidate_summary_text.sharpe_limitations').format(_report_text(metrics.get('sharpe_note'))))
    lines.append(ui_text('forms.candidate_summary_text.advanced_hint'))
    return '\n'.join(lines)


class CandidateSummaryCard(SummaryCard):
    """Only the generated-candidate pane; qualification stays host-owned."""

    def set_values(self, values):
        _privacy.bind_text(self.label, lambda: self.label.setText(candidate_summary_text(values, private=_privacy.enabled(self.label))))
