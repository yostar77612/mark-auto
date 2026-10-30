from quantlab.market import MarketSeries, MarketValidationError as MarketValidationError
from desktop_app.shell.theme import apply_market_theme
from desktop_app.strings.catalog import ui_text
from copy import deepcopy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QTableWidget, QHeaderView, QAbstractItemView
from desktop_app.features.market.chart_presenter import ChartPresenter
from desktop_app.features.market.indicator_controls import (
    _build_market_indicators,
    _build_market_panel_toggle,
    _build_market_tables,
    _build_market_trading_status,
    _build_market_workspace,
)
from desktop_app.features.market.indicator_presenter import DEFAULT_INDICATORS, IndicatorPresenter
from desktop_app.features.market.layout import (
    _build_market_cards,
    _build_market_chart,
    _build_market_diagnostics,
    _build_market_empty_actions,
    _build_market_header,
    _build_market_watchlist,
)
from desktop_app.features.market.preferences import MarketPreferences
from desktop_app.features.market.watchlist_presenter import MarketPresenter
from desktop_app.features.market.rows import MarketRows, _named


class MarketDashboard(QWidget):
    refresh_requested = Signal()
    sample_requested = Signal()
    selection_changed = Signal(str)
    series_rendered = Signal(str)
    preferences_changed = Signal()

    def __init__(self, parent=None):
        # Keep widget dependencies out of module startup.
        from desktop_app.components.widgets import PanelCard

        self.presenter = MarketPresenter(self)
        self.preference_presenter = MarketPreferences(self)
        self.indicator_presenter = IndicatorPresenter(self)
        self.rows = MarketRows(self)
        self.chart_presenter = ChartPresenter(self)
        super().__init__(parent)
        self.setObjectName('market_dashboard')
        apply_market_theme(self)
        self._series = {}
        self._quote_series = None
        self._quote_stale = False
        self._watch = []
        self._watch_initialized = False
        self._selected = ''
        self._timeframe = '1d'
        self._indicator_config = deepcopy(DEFAULT_INDICATORS)
        self._restoring = False
        self._stale = False
        self._error = ''
        self._indicator_widgets = {}
        self.drawing_store = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setObjectName('market_page_scroll')
        content = QWidget()
        self.page_scroll.setWidget(content)
        outer.addWidget(self.page_scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(12)
        header = _build_market_header(self, root)
        cards_widget = _build_market_cards(self, root, PanelCard)
        source_row = _build_market_diagnostics(self, root)
        _build_market_empty_actions(self, root)
        left = _build_market_watchlist(self, root)
        center = _build_market_chart(self)
        right_scroll, right, right_layout = _build_market_trading_status(self, source_row, PanelCard)
        _build_market_indicators(self, right_scroll, right, right_layout, PanelCard)
        _build_market_panel_toggle(self, right_scroll, header)
        _build_market_tables(self, root)
        _build_market_workspace(self, root, header, cards_widget, left, center)

    def closeEvent(self, event):
        self.popout.close()
        super().closeEvent(event)

    def _toggle_diagnostics(self, visible):
        self.diagnostics.setVisible(visible)
        self.diagnostics_button.setText(ui_text('market.toggle_diagnostics.expanded') if visible else ui_text('market.toggle_diagnostics.collapsed'))

    def _table(self, headers, name):
        label = {
            'market_positions': ui_text('access.market_positions'),
            'market_orders': ui_text('access.market_orders'),
            'market_fills': ui_text('access.market_fills'),
        }[name]
        table = _named(QTableWidget(0, len(headers)), name, label)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(False)
        return table

    def set_market_series(self, series, *, stale=False, error=''):
        return self.presenter.set_market_series(series, stale=stale, error=error)

    def set_quote_series(self, series, *, stale=False):
        return self.presenter.set_quote_series(series, stale=stale)

    def selected_series(self):
        return self.presenter.selected_series()

    def set_loading(self, loading):
        return self.presenter.set_loading(loading)

    def _fill_contracts(self):
        return self.presenter._fill_contracts()

    def _filter_catalog(self):
        return self.presenter._filter_catalog()

    def _render_watch(self):
        return self.presenter._render_watch()

    def _add_watch(self):
        return self.presenter._add_watch()

    def _remove_watch(self):
        return self.presenter._remove_watch()

    def _move_watch(self, delta):
        return self.presenter._move_watch(delta)

    def _watch_selected(self, item, previous):
        return self.presenter._watch_selected(item, previous)

    def _contract_changed(self, index):
        return self.presenter._contract_changed(index)

    def _timeframe_changed(self, index):
        return self.presenter._timeframe_changed(index)

    def _render_cards(self):
        return self.rows._render_cards()

    def _render_chart(self):
        return self.chart_presenter._render_chart()

    def _indicators_changed(self, *args):
        return self.indicator_presenter._indicators_changed(*args)

    def _restore_indicator_controls(self):
        return self.indicator_presenter._restore_indicator_controls()

    @staticmethod
    def _indicator_failure_text(failures):
        return ui_text('market.indicator_failure_text.calculation_limit').format(ui_text('market.indicator_failure_text.indicator_separator').join(failures))

    def _apply_indicators(self, config=None, *, reject_failures=()):
        return self.indicator_presenter._apply_indicators(config, reject_failures=reject_failures)

    def refresh_annotations(self):
        return self.indicator_presenter.refresh_annotations()

    def _annotation_preferences_changed(self):
        return self.indicator_presenter._annotation_preferences_changed()

    def preferences(self):
        return self.preference_presenter.preferences()

    def _prepare_chart_memory(self):
        return self.preference_presenter._prepare_chart_memory()

    def restore_preferences(self, payload):
        return self.preference_presenter.restore_preferences(payload)

    def set_trading_status(self, *, strategy=None, paper=None, risk=None):
        return self.rows.set_trading_status(strategy=strategy, paper=paper, risk=risk)

    def set_account_tables(self, *, positions=(), orders=(), fills=()):
        return self.rows.set_account_tables(positions=positions, orders=orders, fills=fills)


def sample_market_series():
    """Project the existing invented demo into daily display bars, in memory only."""
    # Load this operation-specific dependency only when requested.
    from datetime import datetime, timezone

    # Load this operation-specific dependency only when requested.
    from quantlab.reporting import synthetic_dataset

    # Load this operation-specific dependency only when requested.
    from quantlab.market import InstrumentRef, MarketBar, SourceProvenance

    data = synthetic_dataset(960)
    instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202601', '202601')
    days = sorted({bar.trade_date for bar in data.bars})
    bars = []
    for day in days:
        group = [bar for bar in data.bars if bar.trade_date == day]
        bars.append(
            MarketBar(
                instrument,
                day,
                'day',
                group[0].open,
                max(b.high for b in group),
                min(b.low for b in group),
                group[-1].close,
                sum(b.volume for b in group),
                interval='1d',
                source_id='synthetic-v1',
            )
        )
    provenance = SourceProvenance(
        'sample:synthetic-v1',
        data.manifest['source_hash'],
        ui_text('market.sample_label'),
        'sample:synthetic-v1',
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        days[-1],
        days[0],
        days[-1],
        mode='offline',
        warnings=(ui_text('market.sample_label'),),
    )
    return MarketSeries(instrument, tuple(bars), provenance)
