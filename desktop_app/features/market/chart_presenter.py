from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message
from quantlab.chart_data import aggregate_bars
from desktop_app.features.market.rows import _friendly_contract, _series_source


class ChartPresenter:
    def __init__(self, view):
        self.view = view

    def _render_chart(self):
        memory = self.view._prepare_chart_memory()
        if memory.active == f'{self.view._selected}/{self.view._timeframe}':
            memory.capture(self.view)
        item = self.view._series.get(self.view._selected)
        self.view.empty_actions.setVisible(not self.view._series)
        self.view.refresh_button.setVisible(bool(self.view._series))
        if item is None:
            self.view.chart.set_series(())
            self.view._display_bars = ()
            self.view._apply_indicators()
            self.view.source_status.setText(ui_text('market.render_chart.offline').format(' · ' + self.view._error if self.view._error else ''))
            self.view.chart.display_changed.emit()
            return
        provenance = item.provenance
        status = (
            ui_text('market.render_chart.stale_cache')
            if self.view._stale
            else ui_text('market.render_chart.historical')
            if provenance.mode == 'history'
            else ui_text('market.render_chart.post_session')
            if provenance.mode == 'eod'
            else ui_text('market.render_chart.historical_snapshot')
        )
        self.view.source_status.setText(ui_text('market.data_date').format(_series_source(item), provenance.as_of, ui_text('market.not_realtime')))
        try:
            result = aggregate_bars(item.bars, timeframe=self.view._timeframe)
        except (ValueError, TypeError):
            self.view.chart.set_series(())
            self.view._display_bars = ()
            self.view.message.setText(error_message('market_data_invalid'))
            self.view.chart.display_changed.emit()
            return
        self.view._display_bars = result.bars
        self.view.chart.set_series(
            result.bars, source_label=_friendly_contract(item.instrument.contract_id) + ' · ' + _series_source(item), status_label=status
        )
        memory.restore(self.view)
        warnings = list(provenance.warnings) + list(result.warnings)
        if any((bar.partial for bar in result.bars)):
            warnings.insert(0, ui_text('market.render_chart.incomplete_bars'))
        if self.view._error:
            warnings.insert(0, self.view._error)
        details = ui_text('market.render_chart.source_details').format(
            item.instrument.contract_id,
            item.instrument.symbol,
            provenance.attribution,
            provenance.source_url,
            provenance.license_url,
            provenance.sha256,
            provenance.timestamp_basis,
            provenance.received_at.isoformat(),
            provenance.omitted_rows,
        ) + '\n'.join(warnings)
        self.view.diagnostics.setPlainText(details)
        self.view.source_status.setToolTip(details)
        self.view.message.setToolTip('\n'.join(warnings))
        message = ui_text('market.render_chart.integrity_warning') if warnings else ui_text('market.render_chart.historical_not_live')
        if provenance.mode == 'history' and ui_text('market.render_chart.policy_hash_prefix') in provenance.timestamp_basis:
            message = ui_text('market.render_chart.local_sessions_unverified').format(message)
        if self.view._error:
            message = ui_text('market.render_chart.update_failed').format(message)
        self.view.message.setText(message)
        self.view._indicator_message_base = message
        self.view._apply_indicators()
        self.view.series_rendered.emit(self.view._selected)
