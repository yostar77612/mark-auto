"""desktop_app features backtest summary responsibilities."""

from quantlab.shared.time import aware_iso_utc

from desktop_app.components.tables import resize_columns

from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
from decimal import Decimal
from desktop_app.components.formatting import display_value, display_number, finite_decimal
from desktop_app.components.result_tables import RESULT_LABELS, ResultTable, SummaryCard


_REPORT_TEXT = {
    'no closed lots': ui_text('forms.labels.no_closed_lots'),
    'no losing closed lots': ui_text('forms.labels.zero_loss_denominator'),
    'closed FIFO lot net PnL after allocated entry/exit costs; open lots excluded': ui_text('forms.labels.fifo_net_basis'),
    'missing or nonpositive daily equity; no observations discarded': ui_text('forms.labels.invalid_daily_equity'),
    'at least 2 daily returns required for sample standard deviation': ui_text('forms.labels.insufficient_returns'),
    'zero daily-return sample variance': ui_text('forms.labels.zero_return_variance'),
    'between last supplied equity per exchange trading date; gaps may span multiple days': ui_text('forms.labels.daily_equity_frequency'),
    'initial cash to first supplied trading-date equity': ui_text('forms.labels.initial_cash_basis'),
    'supplied trading dates only; no imputation': ui_text('forms.labels.provided_dates_only'),
    'sample (ddof=1)': ui_text('forms.labels.sample_standard_deviation'),
    'Descriptive only. Two returns is a mathematical minimum, not evidence of reliability; short samples do not establish strategy quality. The 252-period convention is assumed, not a validated annual trading calendar; gaps may span multiple days.': ui_text(
        'forms.labels.descriptive_sharpe_warning'
    ),
}


def _report_text(value):
    if value is None:
        return ui_text('forms.report_text.not_provided')
    return (
        _REPORT_TEXT.get(value, ui_text('forms.report_text.unknown_explanation'))
        if isinstance(value, str)
        else ui_text('forms.report_text.unknown_explanation')
    )


def _report_number(value, key=""):
    if value is None:
        return ui_text('forms.report_number.not_provided')
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return ui_text('forms.report_number.diagnostics_required')
    if finite_decimal(value) is None:
        return ui_text('forms.report_number.diagnostics_required')
    return display_number(value, key)


def backtest_summary_text(values, *, private=False):
    """Bounded Traditional Chinese presentation, preserving exact scalar values."""

    def metric(key):
        if private and key in _privacy.MONEY_FIELDS:
            return _privacy.mask_money(None)
        value = values.get(key)
        if value is None:
            return (
                ui_text('forms.metric.undefined') if key in values and key in ('profit_factor', 'sharpe', 'win_rate') else ui_text('forms.metric.not_provided')
            )
        return _report_number(value, key)

    def fields(*keys):
        return ui_text('forms.fields.field_separator').join(ui_text('forms.fields.named_value').format(RESULT_LABELS[key], metric(key)) for key in keys)

    def reason(key, metric_key):
        value = values.get(key)
        metric_value = values.get(metric_key)
        if metric_value is not None and _report_number(metric_value) == ui_text('forms.reason.diagnostics_required'):
            text = ui_text('forms.reason.unknown_metric')
        else:
            text = ui_text('forms.reason.not_applicable') if value is None and metric_value is not None else _report_text(value)
        return ui_text('forms.reason.named_value').format(RESULT_LABELS[key], text)

    lines = [
        fields('net_pnl', 'return'),
        fields('initial_cash', 'final_equity'),
        fields('max_drawdown', 'max_drawdown_pct'),
        fields('total_costs', 'slippage_cost'),
        fields('realized_gross_pnl', 'unrealized_pnl'),
        fields('fill_count', 'closed_lots', 'open_position'),
        fields('trade_count', 'win_rate'),
        reason('win_rate_reason', 'win_rate'),
        '',
        fields('profit_factor'),
        reason('profit_factor_reason', 'profit_factor'),
        ui_text('forms.backtest_summary_text.profit_factor_basis').format(_report_text(values.get('profit_factor_basis'))),
        '',
        fields('sharpe'),
        reason('sharpe_reason', 'sharpe'),
        fields('sharpe_observations', 'sharpe_sample_count'),
    ]
    assumptions = values.get('annualization')
    if isinstance(assumptions, dict):
        for keys in (
            ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations'),
            ('return_frequency',),
            ('first_return',),
            ('missing_dates', 'standard_deviation'),
        ):
            lines.append(
                ui_text('forms.backtest_summary_text.field_separator').join(
                    ui_text('forms.backtest_summary_text.named_value').format(
                        RESULT_LABELS[key],
                        _report_number(assumptions.get(key), key)
                        if key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                        else _report_text(assumptions.get(key)),
                    )
                    for key in keys
                )
            )
    else:
        lines.append(ui_text('forms.backtest_summary_text.annualization_missing'))
    lines.extend(
        (
            ui_text('forms.backtest_summary_text.sharpe_limitations').format(_report_text(values.get('sharpe_note'))),
            ui_text('forms.backtest_summary_text.advanced_hint'),
        )
    )
    return '\n'.join(lines)


class BacktestSummaryCard(SummaryCard):
    """A report-only view; other summary cards retain their original contract."""

    def set_values(self, values):
        _privacy.bind_text(self.label, lambda: self.label.setText(backtest_summary_text(values, private=_privacy.enabled(self.label))))


_FILL_REASONS = {
    'target_open': ui_text('forms.labels.target_entry'),
    'target_close': ui_text('forms.labels.target_exit'),
    'gap_stop': ui_text('forms.labels.gap_stop'),
    'gap_target': ui_text('forms.labels.gap_target'),
    'stop': ui_text('forms.labels.stop_hit'),
    'target': ui_text('forms.labels.target_hit'),
    'maintenance_liquidation': ui_text('forms.labels.maintenance_liquidation'),
    'roll_close': ui_text('forms.labels.roll_close'),
    'roll_open': ui_text('forms.labels.roll_open'),
    'final_settlement': ui_text('forms.labels.expiry_settlement'),
}


class BacktestFillsTable(ResultTable):
    """Readable fills first; exact IDs remain in cell tooltips and diagnostics."""

    _columns = ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax', 'reason')
    _labels = (
        ui_text('forms.labels.fill_time'),
        ui_text('forms.labels.contract'),
        ui_text('forms.labels.side'),
        ui_text('forms.labels.quantity'),
        ui_text('forms.labels.price'),
        ui_text('forms.labels.commission'),
        ui_text('forms.labels.tax'),
        ui_text('forms.labels.fill_reason'),
    )

    def set_rows(self, rows, columns=None):
        from datetime import datetime, timezone

        display = []
        for row in rows:
            shown = {key: row.get(key) for key in self._columns}
            side, reason = row.get('side'), row.get('reason')
            shown['side'] = display_value(side, 'side') if side in ('buy', 'sell') else ui_text('forms.set_rows.unknown_value')
            shown['reason'] = (
                _FILL_REASONS.get(reason, ui_text('forms.set_rows.other_value'))
                if isinstance(reason, str) and reason
                else ui_text('forms.set_rows.not_provided')
                if reason is None or reason == ''
                else ui_text('forms.set_rows.other_value')
            )
            timestamp = row.get('timestamp')
            try:
                parsed = timestamp if isinstance(timestamp, datetime) else aware_iso_utc(timestamp)
                if parsed.tzinfo is None:
                    raise ValueError('timezone required')
                shown['timestamp'] = parsed.astimezone(timezone.utc).isoformat(sep=' ', timespec='seconds').removesuffix('+00:00')
            except (ValueError, TypeError, AttributeError):
                shown['timestamp'] = ui_text('forms.set_rows.time_missing')
            display.append(shown)
        super().set_rows(display, self._columns)
        self.setHorizontalHeaderLabels(self._labels)
        for index, row in enumerate(rows):
            detail = ui_text('forms.set_rows.fill_order_ids').format(
                str(row.get('fill_id', ui_text('forms.set_rows.not_provided'))), str(row.get('order_id', ui_text('forms.set_rows.not_provided')))
            )
            for column in range(self.columnCount()):
                item = self.item(index, column)
                _privacy.item_tooltip(self, item, str(row.get(self._columns[column], ui_text('forms.set_rows.not_provided'))) + '\n' + detail)
        resize_columns(self)
