from desktop_app.features.market.samples import sample_market_series
from pathlib import Path
from PySide6.QtWidgets import QMessageBox
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.reporting import read_json, load_dataset, load_result, load_selection
from quantlab.desktop_errors import error_message, exception_code
from desktop_app.features.market.dashboard import MarketDashboard
from quantlab.chart_drawings import DrawingStore
from desktop_app.shell.host import PageHost


class MarketPage(MarketDashboard):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = getattr(host, 'state', host)
        settings_path = getattr(getattr(self.state, 'settings', None), 'path', None)
        if settings_path is not None:
            if isinstance(settings_path, (str, Path)):
                directory = Path(settings_path).parent / 'display_profile'
                self.drawing_store = DrawingStore(directory)
                self.workspace.configure_store(directory)
        mount = getattr(host, 'mount_market', None)
        if callable(mount):
            mount(self, ui_text('ui.dashboard.title'))
        self.market = self
        self.state.market = self
        if not hasattr(self.state, '_section_toggles'):
            self.state._section_toggles = {}
        self.state._section_toggles['market:diagnostics'] = self.diagnostics_button
        self.diagnostics_button.toggled.connect(lambda checked: host.safe(host.save_sections))
        self.refresh_requested.connect(lambda: host.safe(self.refresh_market))
        self.sample_requested.connect(lambda: host.safe(self.load_sample_market))
        self.preferences_changed.connect(lambda: host.safe(self.save_market_preferences))
        self.series_rendered.connect(lambda _: host.safe(self.bind_result_layers))

    def load_sample_market(self):
        """Read-only demo; do not persist or replace a research dataset/cache."""
        if self._series:
            return
        series = sample_market_series()
        self._selected = series.instrument.contract_id
        self.set_quote_series(series, stale=True)
        self.set_market_series(series, stale=True)

    def refresh_market(self):
        if self.state.jobs.active:
            raise ValidationError(ui_text('ui.refresh_market.job_busy'))
        answer = self.host.question(
            ui_text('ui.refresh_market.confirmation_title'),
            ui_text('ui.refresh_market.network_consent'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.host.start_job('ui_market_refresh', {'network_opt_in': True})

    def save_market_preferences(self):
        if self.state.settings is None:
            return
        value = self.state.settings.load()
        value['market'] = self.market.preferences()
        geometry = self.host.window_geometry()
        position = self.host.window_position()
        value['window'] = {'x': position.x(), 'y': position.y(), 'width': geometry.width(), 'height': geometry.height()}
        self.state.settings.save(value)

    def load_market_cache(self):
        # Load this operation-specific dependency only when requested.
        from quantlab.market_providers import load_cached

        # Load this operation-specific dependency only when requested.
        from desktop_app.components.expiry_inputs import show_research_dataset

        show_research_dataset(self.research_summary, None)
        research_path = self.state.root / 'dataset.json'
        if research_path.exists():
            try:
                show_research_dataset(self.research_summary, load_dataset(research_path))
            except (ValueError, KeyError, TypeError, OSError):
                pass
        series, errors, quotes = {}, [], []
        self.state._market_data_bindings = {}
        self.state._market_research_series = {}
        for provider in ('twse', 'taifex'):
            try:
                loaded = load_cached(provider, self.state.root / 'market_cache')
                series.update({x.instrument.contract_id: x for x in loaded.series})
                quotes.extend(loaded.series)
                outcome = self.state._market_outcomes.get(provider)
                if outcome and outcome.get('error'):
                    errors.append(ui_text('ui.load_market_cache.update_failed_cache_retained').format(provider.upper()))
            except ValueError:
                if (self.state.root / 'market_cache' / (provider + '.json')).exists():
                    errors.append(ui_text('ui.load_market_cache.invalid_cache').format(provider.upper()))
                if self.state._market_outcomes.get(provider, {}).get('error'):
                    errors.append(ui_text('ui.load_market_cache.update_failed_no_cache').format(provider.upper()))
        dataset_path, calendar_path = self.state.root / 'dataset.json', self.state.root / 'dataset_calendar.json'
        if dataset_path.exists() and calendar_path.exists():
            try:
                dataset = load_dataset(dataset_path)
                for item in self.host.dataset_market_series(dataset, read_json(calendar_path)):
                    series[item.instrument.contract_id] = item
                    quotes.append(item)
                    self.state._market_data_bindings[item.instrument.contract_id] = dataset.manifest['data_hash']
                    self.state._market_research_series[item.instrument.contract_id] = item
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(error_message(exception_code(exc)))
        try:
            # Load this operation-specific dependency only when requested.
            from quantlab.market_history import list_history

            histories = list_history(self.state.root / 'market_history')
            # Keep immutable imports separate; newest received snapshot wins per
            # exact contract. Do not blend policies or minute/daily observations.
            incoming = [item for loaded in histories for item in loaded.series]
            for item in sorted(incoming, key=lambda item: (item.provenance.received_at, item.provenance.sha256)):
                series[item.instrument.contract_id] = item
        except (ValueError, OSError) as exc:
            errors.append(error_message(exception_code(exc)))
        self.market.set_quote_series(self.host.latest_market_observations(quotes), stale=True)
        self.market.set_market_series(tuple(series.values()), stale=True, error=ui_text('ui.load_market_cache.warning_separator').join(errors))
        selection = self.state.root / 'selection.json'
        strategy = ui_text('ui.load_market_cache.inactive')
        if selection.exists():
            try:
                strategy = ui_text('ui.load_market_cache.active_version').format(load_selection(selection)['strategy_hash'][:16])
            except (ValueError, KeyError):
                strategy = ui_text('ui.load_market_cache.invalid_version')
        self.market.set_trading_status(strategy=strategy)
        if (self.state.root / 'paper.sqlite3').exists() and (self.state.root / 'paper_policy.json').exists():
            try:
                # Load this operation-specific dependency only when requested.
                from quantlab.paper import PaperBroker

                self.host.show_account(PaperBroker.read_snapshot(self.state.root / 'paper.sqlite3'), strategy=strategy)
            except Exception:
                self.market.chart.set_paper_snapshot(None, mode=None)
                self.market.set_trading_status(
                    strategy=strategy, paper=ui_text('ui.load_market_cache.account_read_failed'), risk=ui_text('ui.load_market_cache.stop_check_records')
                )
                self.market.set_account_tables()

    def bind_result_layers(self, result=None):
        """Only exact source, strategy and chart identities may carry result layers."""
        # Load this operation-specific dependency only when requested.
        from desktop_app.components.chart_annotations import ChartTrace, ChartMarker

        chart = self.market.chart
        bars = chart.bars
        old_overlays, old_panes, styles = dict(chart.overlays), dict(chart.panes), dict(chart.pane_styles)
        source, status = chart.source_label, chart.status_label
        chart.set_series(bars, source_label=source, status_label=status)
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        path = self.state.result_choice.currentData() if hasattr(self.state, 'result_choice') else None
        if not bars or not path or not (self.state.root / 'dataset.json').exists():
            return
        result = result or load_result(path)
        data = load_dataset(self.state.root / 'dataset.json')
        # Load this operation-specific dependency only when requested.
        from quantlab.reporting import validate_result_payload

        try:
            # Use the report loader's authoritative full dataset/provenance binding.
            validate_result_payload(to_dict(result), dataset=data)
        except (ValidationError, KeyError, TypeError, ValueError):
            return
        # Require the exact adapted market source, not merely matching price/date.
        selected = self.market.contract_combo.currentData()
        item = self.market.selected_series()
        if item is None or self.state._market_data_bindings.get(selected) != data.manifest['data_hash']:
            return
        if item != self.state._market_research_series.get(selected):
            return
        trace = ChartTrace(selected, content_hash(bars), result.manifest['spec_hash'], ui_text('ui.bind_result_layers.backtest'))
        markers = []
        # Load this operation-specific dependency only when requested.
        from bisect import bisect_left, bisect_right

        timed = [(i, b) for i, b in enumerate(bars) if b.timestamp is not None and b.end is not None]
        starts, ends = [b.timestamp for _, b in timed], [b.end for _, b in timed]

        def event_index(timestamp, at_close):
            position = bisect_left(ends, timestamp) if at_close else bisect_right(starts, timestamp) - 1
            if not 0 <= position < len(timed):
                return None
            i, bar = timed[position]
            return i if (bar.timestamp < timestamp <= bar.end if at_close else bar.timestamp <= timestamp < bar.end) else None

        for signal in result.signals:
            if signal.contract_id != selected:
                continue
            index = event_index(signal.timestamp, True)
            if index is not None:
                markers.append(
                    ChartMarker(
                        index,
                        'signal',
                        ui_text('ui.bind_result_layers.target_position').format(str(signal.target_position)),
                        reason=signal.reason,
                        timestamp=signal.timestamp,
                        target_position=signal.target_position,
                    )
                )
        for fill in result.fills:
            if fill.contract_id != selected:
                continue
            # Core timestamps are event availability; never infer intrabar execution time.
            index = event_index(fill.timestamp, fill.reason in ('stop', 'target'))
            if index is not None:
                markers.append(
                    ChartMarker(
                        index,
                        'fill',
                        ui_text('ui.bind_result_layers.buy') if fill.side == 'buy' else ui_text('ui.bind_result_layers.sell'),
                        price=fill.price,
                        quantity=fill.quantity,
                        cost=fill.commission + fill.tax,
                        reason=fill.reason,
                        timestamp=fill.timestamp,
                    )
                )
        chart.set_series(bars, trace=trace, source_label=source, status_label=ui_text('ui.bind_result_layers.backtest_layer_hint').format(status))
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        chart.set_markers(markers, trace=trace)
        chart.set_reference_lines(self.host.result_snapshot_lines(result, bars, selected), trace=trace)
