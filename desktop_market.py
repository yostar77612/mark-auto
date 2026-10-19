"""Read-only market dashboard. Host owns fetching, persistence and trading state.

No network, timers, broker imports or embedded observations. refresh_requested is
an intent only; host must perform its existing consent/background-job workflow.
"""

from desktop_theme import apply_market_theme, set_status, set_financial_label
from desktop_strings import ui_text
from desktop_timeinput import DateInput, history_utc_hint
from copy import deepcopy
from quantlab.desktop_errors import error_message, exception_code
from decimal import Decimal, InvalidOperation
import re
from PySide6.QtCore import Qt, Signal, QTime, QSignalBlocker
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QGroupBox,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QPlainTextEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QTimeEdit,
    QFormLayout,
)
from quantlab.market import MarketSeries, QuoteSnapshot, MarketValidationError
from quantlab.chart_data import TIMEFRAMES, aggregate_bars
from quantlab import indicators
from desktop_charts import CandlestickChart

DEFAULT_INDICATORS = {
    'MA': {'enabled': True, 'periods': [5, 10, 20, 60]},
    'EMA': {'enabled': False, 'period': 20},
    'RSI': {'enabled': False, 'period': 14},
    'MACD': {'enabled': False, 'fast': 12, 'slow': 26, 'signal': 9},
    'KD': {'enabled': False, 'period': 9, 'k_period': 3, 'd_period': 3},
    'Bollinger': {'enabled': False, 'period': 20, 'deviations': 2},
    'VWAP': {'enabled': False},
}


def _identity(value):
    return isinstance(value, str) and (value == 'TWSE:TAIEX' or bool(re.fullmatch(r'TAIFEX:(?:TX|MTX|TMF):\d{4}(?:0[1-9]|1[0-2])(?:W[1-5])?', value)))


def _friendly_contract(key):
    if key == 'TWSE:TAIEX':
        return ui_text('market._friendly_contract.text_1')
    parts = key.split(':')
    if len(parts) != 3:
        return key
    product = {
        'TX': ui_text('market._friendly_contract.text_2'),
        'MTX': ui_text('market._friendly_contract.text_3'),
        'TMF': ui_text('market._friendly_contract.text_4'),
    }.get(parts[1], parts[1])
    expiry = parts[2]
    month = expiry[:4] + '/' + expiry[4:6]
    if len(expiry) > 6:
        month += ui_text('market._friendly_contract.text_5').format(expiry[-1])
    return product + ' ' + month


def _friendly_source(instrument):
    return ui_text('market._friendly_source.text_1') if instrument.exchange == 'TWSE' else ui_text('market._friendly_source.text_2')


def _label(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _named(widget, name, label):
    widget.setObjectName(name)
    widget.setAccessibleName(label)
    return widget


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


def _series_source(item):
    return ui_text('market.sample_label') if item.provenance.source_url == 'sample:synthetic-v1' else _friendly_source(item.instrument)


class MarketDashboard(QWidget):
    refresh_requested = Signal()
    sample_requested = Signal()
    selection_changed = Signal(str)
    series_rendered = Signal(str)
    preferences_changed = Signal()

    def __init__(self, parent=None):
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setObjectName('market_page_scroll')
        content = QWidget()
        self.page_scroll.setWidget(content)
        outer.addWidget(self.page_scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 8, 10, 8)
        header = QHBoxLayout()
        title = _label(ui_text('market.__init__.text_1'), 'market_title')
        header.addWidget(title)
        header.addStretch()
        header.addWidget(_label(ui_text('market.__init__.text_2'), 'market_safety'))
        self.refresh_button = _named(QPushButton(ui_text('market.__init__.text_3')), 'market_refresh', ui_text('market.__init__.text_4'))
        self.refresh_button.setToolTip(ui_text('market.__init__.text_5'))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        root.addLayout(header)
        self.research_summary = _label('', 'market_research_summary')
        self.research_summary.hide()
        root.addWidget(self.research_summary)
        cards = QHBoxLayout()
        self.cards = {}
        for key, title in [
            ('TAIEX', ui_text('market.__init__.text_6')),
            ('TX', ui_text('market.__init__.text_7')),
            ('MXF', ui_text('market.__init__.text_8')),
            ('TMF', ui_text('market.__init__.text_9')),
        ]:
            group = QGroupBox(title)
            group.setProperty('themePart', 'marketCard')
            layout = QVBoxLayout(group)
            layout.setContentsMargins(8, 8, 8, 6)
            value = _label(ui_text('market.__init__.text_10'), 'market_card_' + key)
            layout.addWidget(value)
            cards.addWidget(group)
            self.cards[key] = value
        root.addLayout(cards)
        self.source_status = _label(ui_text('market.__init__.text_11'), 'market_source_status')
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_status, 1)
        self.diagnostics_button = _named(QPushButton(ui_text('market.__init__.text_12')), 'market_diagnostics_toggle', ui_text('market.__init__.text_13'))
        self.diagnostics_button.setCheckable(True)
        source_row.addWidget(self.diagnostics_button)
        root.addLayout(source_row)
        self.diagnostics = _named(QPlainTextEdit(), 'market_diagnostics', ui_text('market.__init__.text_14'))
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(160)
        self.diagnostics.hide()
        self.diagnostics_button.toggled.connect(self._toggle_diagnostics)
        root.addWidget(self.diagnostics)
        self.message = _label(ui_text('market.__init__.text_15'), 'market_message')
        set_status(self.message, 'warning')
        root.addWidget(self.message)
        self.empty_actions = QWidget()
        actions = QHBoxLayout(self.empty_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        self.sample_button = _named(QPushButton(ui_text('market.load_sample')), 'market_load_sample', ui_text('market.load_sample'))
        self.sample_button.setToolTip(ui_text('market.sample_label'))
        self.sample_button.clicked.connect(self.sample_requested.emit)
        actions.addWidget(self.sample_button)
        self.official_button = _named(QPushButton(ui_text('market.download_official')), 'market_download_official', ui_text('market.download_official'))
        self.official_button.setToolTip(ui_text('market.official_consent'))
        self.official_button.clicked.connect(self.refresh_requested.emit)
        actions.addWidget(self.official_button)
        root.addWidget(self.empty_actions)
        self.refresh_button.hide()
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.main_splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.addWidget(_label(ui_text('market.__init__.text_16'), 'market_watch_title'))
        self.search = _named(QLineEdit(), 'market_search', ui_text('market.__init__.text_17'))
        self.search.setPlaceholderText(ui_text('market.__init__.text_18'))
        self.search.textChanged.connect(self._filter_catalog)
        left_layout.addWidget(self.search)
        self.catalog_combo = _named(QComboBox(), 'market_catalog', ui_text('market.__init__.text_19'))
        left_layout.addWidget(self.catalog_combo)
        self.add_button = _named(QPushButton(ui_text('market.__init__.text_20')), 'market_add', ui_text('market.__init__.text_21'))
        self.add_button.clicked.connect(self._add_watch)
        left_layout.addWidget(self.add_button)
        self.watchlist = _named(QListWidget(), 'market_watchlist', ui_text('market.__init__.text_22'))
        self.watchlist.currentItemChanged.connect(self._watch_selected)
        left_layout.addWidget(self.watchlist, 1)
        row = QHBoxLayout()
        self.remove_button = _named(QPushButton(ui_text('market.__init__.text_23')), 'market_remove', ui_text('market.__init__.text_24'))
        self.remove_button.clicked.connect(self._remove_watch)
        row.addWidget(self.remove_button)
        for text, delta, name in [('↑', -1, 'up'), ('↓', 1, 'down')]:
            button = _named(QPushButton(text), 'market_watch_' + name, ui_text('market.__init__.text_25') if delta < 0 else ui_text('market.__init__.text_26'))
            button.clicked.connect(lambda checked=False, d=delta: self._move_watch(d))
            row.addWidget(button)
        left_layout.addLayout(row)
        self.main_splitter.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 0, 4, 0)
        control = QHBoxLayout()
        self.contract_combo = _named(QComboBox(), 'market_contract', ui_text('market.__init__.text_27'))
        self.contract_combo.currentIndexChanged.connect(self._contract_changed)
        control.addWidget(self.contract_combo, 1)
        self.timeframe_combo = _named(QComboBox(), 'market_timeframe', ui_text('market.__init__.text_28'))
        for text, value in zip(
            (
                ui_text('market.__init__.text_29'),
                ui_text('market.__init__.text_30'),
                ui_text('market.__init__.text_31'),
                ui_text('market.__init__.text_32'),
                ui_text('market.__init__.text_33'),
                ui_text('market.__init__.text_34'),
                ui_text('market.__init__.text_35'),
                ui_text('market.__init__.text_36'),
            ),
            TIMEFRAMES,
        ):
            self.timeframe_combo.addItem(text, value)
        self.timeframe_combo.setCurrentIndex(6)
        self.timeframe_combo.currentIndexChanged.connect(self._timeframe_changed)
        control.addWidget(self.timeframe_combo)
        center_layout.addLayout(control)
        self.chart = CandlestickChart()
        self.chart.setObjectName('market_candles')
        center_layout.addWidget(self.chart, 1)
        self.indicator_summary = _label('', 'market_indicator_summary')
        center_layout.addWidget(self.indicator_summary)
        self.main_splitter.addWidget(center)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(175)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.trading_labels = {}
        state = QGroupBox(ui_text('market.__init__.text_37'))
        state_layout = QVBoxLayout(state)
        for key, title in [
            ('strategy', ui_text('market.__init__.text_38')),
            ('paper', ui_text('market.__init__.text_39')),
            ('risk', ui_text('market.__init__.text_40')),
        ]:
            label = _label(ui_text('market.__init__.text_41').format(title), 'market_state_' + key)
            state_layout.addWidget(label)
            self.trading_labels[key] = label
        state_layout.addWidget(_label(ui_text('market.__init__.text_42'), 'market_live_disabled'))
        right_layout.addWidget(state)
        group = QGroupBox(ui_text('market.__init__.text_43'))
        grid = QGridLayout(group)
        row = 0
        for key, config in DEFAULT_INDICATORS.items():
            check = _named(QCheckBox(key), 'market_indicator_' + key, ui_text('market.__init__.text_44').format(key))
            check.setChecked(config['enabled'])
            grid.addWidget(check, row, 0, 1, 2)
            row += 1
            controls = {}
            self._indicator_widgets[key] = (check, controls)
            for param, value in config.items():
                if param == 'enabled':
                    continue
                values = value if isinstance(value, list) else [value]
                for index, number in enumerate(values):
                    spin = QDoubleSpinBox() if param == 'deviations' else QSpinBox()
                    spin.setRange(0.1 if param == 'deviations' else 1, 1000)
                    spin.setValue(number)
                    field = f'{param}_{index}' if isinstance(value, list) else param
                    _named(spin, f'market_{key}_{field}', f'{key} {field}')
                    grid.addWidget(
                        _label(
                            (ui_text('market.__init__.text_45').format(str(index + 1)))
                            if param == 'periods'
                            else {
                                'period': ui_text('market.__init__.text_46'),
                                'fast': ui_text('market.__init__.text_47'),
                                'slow': ui_text('market.__init__.text_48'),
                                'signal': ui_text('market.__init__.text_49'),
                                'k_period': ui_text('market.__init__.text_50'),
                                'd_period': ui_text('market.__init__.text_51'),
                                'deviations': ui_text('market.__init__.text_52'),
                            }[param],
                            'label_' + key + field,
                        ),
                        row,
                        0,
                    )
                    grid.addWidget(spin, row, 1)
                    row += 1
                    controls[field] = spin
                    spin.valueChanged.connect(self._indicators_changed)
            check.toggled.connect(self._indicators_changed)
        right_layout.addWidget(group)
        right_layout.addWidget(_label(ui_text('market.__init__.text_53'), 'market_vwap_disclosure'))
        right_layout.addStretch()
        right_scroll.setWidget(right)
        self.main_splitter.addWidget(right_scroll)
        # Load this operation-specific dependency only when requested.
        from PySide6.QtWidgets import QToolButton

        self.right_panel = right_scroll
        self.panel_toggle = QToolButton()
        self.panel_toggle.setObjectName('market_panel_toggle')
        self.panel_toggle.setText(ui_text('market.panel_toggle'))
        self.panel_toggle.setAccessibleName(ui_text('market.panel_toggle'))
        self.panel_toggle.setToolTip(ui_text('market.panel_toggle'))
        self.panel_toggle.setCheckable(True)
        self.panel_toggle.setChecked(True)
        self.panel_toggle.toggled.connect(right_scroll.setVisible)
        header.insertWidget(1, self.panel_toggle)
        self.main_splitter.setSizes([190, 740, 230])
        self.main_splitter.setCollapsible(1, False)
        self.tables = QTabWidget()
        self.tables.setMaximumHeight(180)
        self.tables.setMinimumHeight(95)
        self.positions_table = self._table(
            (ui_text('market.__init__.text_54'), ui_text('market.__init__.text_55'), ui_text('market.__init__.text_56')), 'market_positions'
        )
        self.orders_table = self._table(
            (
                ui_text('market.__init__.text_57'),
                ui_text('market.__init__.text_58'),
                ui_text('market.__init__.text_59'),
                ui_text('market.__init__.text_60'),
                ui_text('market.__init__.text_61'),
            ),
            'market_orders',
        )
        self.fills_table = self._table(
            (
                ui_text('market.__init__.text_62'),
                ui_text('market.__init__.text_63'),
                ui_text('market.__init__.text_64'),
                ui_text('market.__init__.text_65'),
                ui_text('market.__init__.text_66'),
            ),
            'market_fills',
        )
        for title, table in [
            (ui_text('market.__init__.text_67'), self.positions_table),
            (ui_text('market.__init__.text_68'), self.orders_table),
            (ui_text('market.__init__.text_69'), self.fills_table),
        ]:
            self.tables.addTab(table, title)
        root.addWidget(self.tables)

    def _toggle_diagnostics(self, visible):
        self.diagnostics.setVisible(visible)
        self.diagnostics_button.setText(ui_text('market._toggle_diagnostics.text_1') if visible else ui_text('market._toggle_diagnostics.text_2'))

    def _table(self, headers, name):
        table = _named(QTableWidget(0, len(headers)), name, name)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(False)
        return table

    def set_market_series(self, series, *, stale=False, error=''):
        """Replace a validated snapshot atomically; called by host on GUI thread."""
        items = (series,) if isinstance(series, MarketSeries) else tuple(series)
        if any(not isinstance(item, MarketSeries) for item in items) or len(items) > 1000 or type(stale) is not bool or not isinstance(error, str):
            raise ValueError('invalid market snapshot')
        ids = [item.instrument.contract_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate contract')
        self._series = dict(zip(ids, items))
        self._stale = stale
        self._error = error[:1000]
        if not self._selected and ids:
            self._selected = ids[0]
        if not self._watch_initialized and ids:
            self._watch = [self._selected] if self._selected in ids else [ids[0]]
            self._watch_initialized = True
        self._fill_contracts()
        self._filter_catalog()
        self._render_watch()
        self._render_cards()
        self._render_chart()

    def set_quote_series(self, series, *, stale=False):
        """Set independent card observations; historical chart selection is untouched.

        The host supplies its latest verified snapshot. An empty tuple clears cards
        rather than falling back to an older research chart. No reference prices
        are invented and explicit contract identity remains mandatory.
        """
        items = (series,) if isinstance(series, MarketSeries) else tuple(series)
        if any(not isinstance(item, MarketSeries) for item in items) or len(items) > 1000 or type(stale) is not bool:
            raise ValueError('invalid market-card snapshot')
        ids = [item.instrument.contract_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate market-card contract')
        self._quote_series = dict(zip(ids, items))
        self._quote_stale = stale
        self._render_cards()

    def selected_series(self):
        """Immutable source snapshot for host provenance checks, or None."""
        return self._series.get(self._selected)

    def set_loading(self, loading):
        if type(loading) is not bool:
            raise ValueError('loading must be boolean')
        self.refresh_button.setEnabled(not loading)
        self.refresh_button.setText(ui_text('market.set_loading.text_1') if loading else ui_text('market.set_loading.text_2'))

    def _fill_contracts(self):
        self.contract_combo.blockSignals(True)
        self.contract_combo.clear()
        for key, item in self._series.items():
            self.contract_combo.addItem(_friendly_contract(key), key)
        self.contract_combo.setCurrentIndex(self.contract_combo.findData(self._selected))
        self.contract_combo.blockSignals(False)

    def _filter_catalog(self):
        terms = self.search.text().upper().split()
        self.catalog_combo.clear()
        for key, item in self._series.items():
            label = _friendly_contract(key)
            searchable = f'{label} {item.instrument.symbol} {key}'
            if all(term in searchable.upper() for term in terms):
                self.catalog_combo.addItem(label, key)
        self.add_button.setEnabled(self.catalog_combo.count() > 0)

    def _render_watch(self):
        self.watchlist.blockSignals(True)
        self.watchlist.clear()
        for key in self._watch:
            text = _friendly_contract(key) + (ui_text('market._render_watch.text_1') if key not in self._series else '')
            item = QListWidgetItem(text)
            item.setToolTip(key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.watchlist.addItem(item)
            if key == self._selected:
                self.watchlist.setCurrentItem(item)
        self.watchlist.blockSignals(False)

    def _add_watch(self):
        key = self.catalog_combo.currentData()
        if key and key not in self._watch and len(self._watch) < 100:
            self._watch.append(key)
            self._render_watch()
            self.preferences_changed.emit()

    def _remove_watch(self):
        row = self.watchlist.currentRow()
        if row >= 0:
            self._watch.pop(row)
            self._render_watch()
            self.preferences_changed.emit()

    def _move_watch(self, delta):
        row = self.watchlist.currentRow()
        target = row + delta
        if 0 <= row < len(self._watch) and 0 <= target < len(self._watch):
            self._watch[row], self._watch[target] = self._watch[target], self._watch[row]
            self._render_watch()
            self.watchlist.setCurrentRow(target)
            self.preferences_changed.emit()

    def _watch_selected(self, item, previous):
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            if key in self._series:
                self.contract_combo.setCurrentIndex(self.contract_combo.findData(key))
            else:
                self.message.setText(ui_text('market._watch_selected.text_1'))

    def _contract_changed(self, index):
        key = self.contract_combo.itemData(index)
        if key:
            self._selected = key
            self._render_chart()
            self._render_cards()
            self.selection_changed.emit(key)
            self.preferences_changed.emit()

    def _timeframe_changed(self, index):
        value = self.timeframe_combo.itemData(index)
        current = self._series.get(self._selected)
        if current and value.endswith('m') and any(not bar.interval.endswith('m') for bar in current.bars):
            self.timeframe_combo.blockSignals(True)
            self.timeframe_combo.setCurrentIndex(self.timeframe_combo.findData(self._timeframe))
            self.timeframe_combo.blockSignals(False)
            self.message.setText(ui_text('market._timeframe_changed.text_1'))
            return
        self._timeframe = value
        self._render_chart()
        self.preferences_changed.emit()

    def _render_cards(self):
        sources = self._series if self._quote_series is None else self._quote_series
        stale = self._stale if self._quote_series is None else self._quote_stale
        for symbol, label in self.cards.items():
            choices = [x for x in sources.values() if x.instrument.symbol == symbol]
            item = next((x for x in choices if x.instrument.contract_id == self._selected), choices[0] if choices else None)
            if not item:
                label.setText(ui_text('market._render_cards.text_1'))
                set_financial_label(label, None)
                label.setToolTip('')
                continue
            quote = QuoteSnapshot.from_series(item, stale=stale)
            change = quote.change
            delta = ui_text('market._render_cards.text_2') if change is None else f'{change:+f}'
            label.setText(
                f'{_friendly_contract(item.instrument.contract_id)}\n{quote.last:,.2f}  {delta}\n{quote.trade_date} · '
                + (ui_text('market._render_cards.text_3') if stale else ui_text('market._render_cards.text_4'))
                + ' · '
                + ui_text('market.not_realtime')
                + (' · ' + ui_text('market.sample_label') if item.provenance.source_url == 'sample:synthetic-v1' else '')
            )
            label.setToolTip(
                ui_text('market._render_cards.text_5').format(
                    item.instrument.contract_id,
                    item.instrument.symbol,
                    item.provenance.attribution,
                    item.provenance.source_url,
                    item.provenance.timestamp_basis,
                    quote.received_at.isoformat(),
                )
            )
            set_financial_label(label, change)

    def _render_chart(self):
        item = self._series.get(self._selected)
        self.empty_actions.setVisible(not self._series)
        self.refresh_button.setVisible(bool(self._series))
        if item is None:
            self.chart.set_series(())
            self._display_bars = ()
            self._apply_indicators()
            self.source_status.setText(ui_text('market._render_chart.text_1').format(' · ' + self._error if self._error else ''))
            return
        provenance = item.provenance
        # This dashboard consumes historical bar snapshots, never a streaming quote entitlement.
        status = (
            ui_text('market._render_chart.text_2')
            if self._stale
            else ui_text('market._render_chart.text_3')
            if provenance.mode == 'history'
            else ui_text('market._render_chart.text_4')
            if provenance.mode == 'eod'
            else ui_text('market._render_chart.text_5')
        )
        self.source_status.setText(ui_text('market.data_date').format(_series_source(item), provenance.as_of, ui_text('market.not_realtime')))
        try:
            result = aggregate_bars(item.bars, timeframe=self._timeframe)
        except (ValueError, TypeError) as exc:
            self.chart.set_series(())
            self._display_bars = ()
            self.message.setText(error_message('market_data_invalid'))
            return
        self._display_bars = result.bars
        self.chart.set_series(result.bars, source_label=_friendly_contract(item.instrument.contract_id) + ' · ' + _series_source(item), status_label=status)
        warnings = list(provenance.warnings) + list(result.warnings)
        if any(bar.partial for bar in result.bars):
            warnings.insert(0, ui_text('market._render_chart.text_7'))
        if self._error:
            warnings.insert(0, self._error)
        details = ui_text('market._render_chart.text_8').format(
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
        self.diagnostics.setPlainText(details)
        self.source_status.setToolTip(details)
        self.message.setToolTip('\n'.join(warnings))
        message = ui_text('market._render_chart.text_9') if warnings else ui_text('market._render_chart.text_10')
        if provenance.mode == 'history' and ui_text('market._render_chart.text_11') in provenance.timestamp_basis:
            message = ui_text('market._render_chart.text_12').format(message)
        if self._error:
            message = ui_text('market._render_chart.text_13').format(message)
        self.message.setText(message)
        self._indicator_message_base = message
        self._apply_indicators()
        self.series_rendered.emit(self._selected)

    def _indicators_changed(self, *args):
        if self._restoring:
            return
        config = {}
        for key, (check, controls) in self._indicator_widgets.items():
            value = {'enabled': check.isChecked()}
            if key == 'MA':
                value['periods'] = [controls[f'periods_{i}'].value() for i in range(4)]
            else:
                value.update({name: spin.value() for name, spin in controls.items()})
            config[key] = value
        if config['MACD']['fast'] >= config['MACD']['slow']:
            self._restore_indicator_controls()
            self.message.setText(ui_text('market._indicators_changed.text_1'))
            return
        changed = {key for key in config if config[key] != self._indicator_config[key]}
        failures = self._apply_indicators(config, reject_failures=changed)
        if failures:
            self._restore_indicator_controls()
            self.message.setText(ui_text('market._indicators_changed.text_2').format(self._indicator_failure_text(failures)))
            return
        self._indicator_config = config
        self.preferences_changed.emit()

    def _restore_indicator_controls(self):
        # Block every widget signal during rollback, including external observers.
        widgets = [widget for check, controls in self._indicator_widgets.values() for widget in (check, *controls.values())]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            for key, (check, controls) in self._indicator_widgets.items():
                check.setChecked(self._indicator_config[key]['enabled'])
                for name, spin in controls.items():
                    value = self._indicator_config[key]['periods'][int(name[-1])] if name.startswith('periods_') else self._indicator_config[key][name]
                    spin.setValue(value)
        finally:
            for blocker in blockers:
                blocker.unblock()

    @staticmethod
    def _indicator_failure_text(failures):
        return ui_text('market._indicator_failure_text.text_2').format(ui_text('market._indicator_failure_text.text_1').join(failures))

    def _apply_indicators(self, config=None, *, reject_failures=()):
        bars = getattr(self, '_display_bars', ())
        closes = []
        highs = []
        lows = []
        keep = []
        for index, bar in enumerate(bars):
            previous = bars[index - 1] if index else None
            if (
                previous is not None
                and bar.interval.endswith('m')
                and (bar.trade_date, bar.session, bar.session_open) == (previous.trade_date, previous.session, previous.session_open)
                and bar.timestamp > previous.end
            ):
                closes.append(None)
                highs.append(None)
                lows.append(None)
            keep.append(len(closes))
            closes.append(bar.close)
            highs.append(bar.high)
            lows.append(bar.low)
        overlays = {}
        panels = {}
        names = []
        failures = []
        for key, options in (self._indicator_config if config is None else config).items():
            if not options['enabled']:
                continue
            names.append(key)
            kwargs = {k: v for k, v in options.items() if k != 'enabled'}
            try:
                if key == 'MA':
                    for period in kwargs['periods']:
                        overlays[f'MA{period}'] = indicators.sma(closes, period=period)
                elif key == 'EMA':
                    overlays['EMA'] = indicators.ema(closes, **kwargs)
                elif key == 'RSI':
                    panels['RSI'] = {'RSI': indicators.rsi(closes, **kwargs)}
                elif key == 'MACD':
                    panels['MACD'] = indicators.macd(closes, **kwargs)
                elif key == 'KD':
                    panels['KD'] = indicators.kd(highs, lows, closes, **kwargs)
                elif key == 'Bollinger':
                    overlays.update({'BB ' + k: v for k, v in indicators.bollinger(closes, **kwargs).items()})
                elif key == 'VWAP':
                    overlays[ui_text('market._apply_indicators.text_1')] = indicators.session_vwap(bars)
            except indicators.IndicatorResourceLimitError:
                failures.append(key)
        rejected = tuple(key for key in failures if key in reject_failures)
        if rejected:
            return rejected
        summary = ' / '.join(name + (ui_text('market._apply_indicators.text_2') if name in failures else '') for name in names) or ui_text(
            'market._apply_indicators.text_3'
        )
        self.indicator_summary.setText(ui_text('market._apply_indicators.text_4').format(summary))
        overlays = {name: values if name == ui_text('market._apply_indicators.text_5') else tuple(values[i] for i in keep) for name, values in overlays.items()}
        panes = {f'{panel} {key}': tuple(values[i] for i in keep) for panel, entries in panels.items() for key, values in entries.items()}
        if 'MACD histogram' in panes:
            panes['MACD histogram 1×'] = panes.pop('MACD histogram')
        self.chart.set_overlays(overlays, panes=panes, pane_styles={'MACD histogram 1×': 'histogram'} if 'MACD histogram 1×' in panes else {})
        message = getattr(self, '_indicator_message_base', ui_text('market._apply_indicators.text_6'))
        self.message.setText(message + (ui_text('market._apply_indicators.text_7').format(self._indicator_failure_text(failures)) if failures else ''))
        return ()

    def preferences(self):
        return {
            'version': 1,
            'watchlist': list(self._watch),
            'selected': self._selected,
            'timeframe': self._timeframe,
            'indicators': deepcopy(self._indicator_config),
            'theme': 'dark',
        }

    def restore_preferences(self, payload):
        if (
            not isinstance(payload, dict)
            or set(payload) - {'version', 'watchlist', 'selected', 'timeframe', 'indicators', 'theme'}
            or type(payload.get('version')) is not int
            or payload.get('version') != 1
        ):
            raise ValueError('unsupported preferences')
        watch = payload.get('watchlist', [])
        selected = payload.get('selected', '')
        timeframe = payload.get('timeframe', '1d')
        config = deepcopy(payload.get('indicators', DEFAULT_INDICATORS))
        if not isinstance(watch, list) or len(watch) > 100 or any(not _identity(x) for x in watch) or len(set(watch)) != len(watch):
            raise ValueError('invalid watchlist')
        if (selected and not _identity(selected)) or not isinstance(selected, str) or timeframe not in TIMEFRAMES or payload.get('theme', 'dark') != 'dark':
            raise ValueError('invalid selection/theme')
        if not isinstance(config, dict) or set(config) != set(DEFAULT_INDICATORS):
            raise ValueError('invalid indicators')
        for key, default in DEFAULT_INDICATORS.items():
            entry = config[key]
            if not isinstance(entry, dict) or set(entry) != set(default) or type(entry['enabled']) is not bool:
                raise ValueError('invalid indicator shape')
            for param, value in entry.items():
                if param == 'enabled':
                    continue
                values = value if param == 'periods' and isinstance(value, list) else [value]
                if param == 'periods' and (not isinstance(value, list) or len(value) != 4):
                    raise ValueError('four MA periods required')
                if any(
                    type(v) not in ((int, float) if param == 'deviations' else (int,)) or not (0.1 if param == 'deviations' else 1) <= v <= 1000 for v in values
                ):
                    raise ValueError('invalid indicator period')
        if config['MACD']['fast'] >= config['MACD']['slow']:
            raise ValueError('invalid MACD periods')
        self._watch = list(watch)
        self._watch_initialized = True
        self._selected = selected
        self._timeframe = timeframe
        self._indicator_config = config
        self._restoring = True
        try:
            self.timeframe_combo.blockSignals(True)
            self.timeframe_combo.setCurrentIndex(self.timeframe_combo.findData(timeframe))
            self.timeframe_combo.blockSignals(False)
            for key, (check, controls) in self._indicator_widgets.items():
                check.setChecked(config[key]['enabled'])
                for name, spin in controls.items():
                    spin.setValue(config[key]['periods'][int(name[-1])] if name.startswith('periods_') else config[key][name])
        finally:
            self._restoring = False
        self._fill_contracts()
        self._render_watch()
        self._render_chart()

    def set_trading_status(self, *, strategy=None, paper=None, risk=None):
        values = {'strategy': strategy, 'paper': paper, 'risk': risk}
        if any(value is not None and (not isinstance(value, str) or len(value) > 500) for value in values.values()):
            raise ValueError('invalid host status')
        for key, title in [
            ('strategy', ui_text('market.set_trading_status.text_1')),
            ('paper', ui_text('market.set_trading_status.text_2')),
            ('risk', ui_text('market.set_trading_status.text_3')),
        ]:
            self.trading_labels[key].setText(
                ui_text('market.set_trading_status.text_5').format(
                    title, values[key] if values[key] is not None else ui_text('market.set_trading_status.text_4')
                )
            )

    def set_account_tables(self, *, positions=(), orders=(), fills=()):
        """Validated display-only snapshots. Never produces an order or fills blanks."""
        prepared = []
        for rows, table, columns in [
            (positions, self.positions_table, ('contract_id', 'quantity', 'average_price')),
            (orders, self.orders_table, ('order_id', 'contract_id', 'side', 'quantity', 'status')),
            (fills, self.fills_table, ('fill_id', 'contract_id', 'side', 'quantity', 'price')),
        ]:
            if not isinstance(rows, (list, tuple)) or len(rows) > 10000:
                raise ValueError('bounded table rows required')
            output = []
            for row in rows:
                if not isinstance(row, dict) or not _identity(row.get('contract_id')) or type(row.get('quantity')) is not int:
                    raise ValueError('invalid host account row')
                if table is not self.positions_table and (row['quantity'] <= 0 or row.get('side') not in ('buy', 'sell')):
                    raise ValueError('invalid direction/quantity')
                cells = []
                for key in columns:
                    value = row.get(key)
                    if value is None:
                        cells.append('—')
                        continue
                    if key in ('average_price', 'price'):
                        try:
                            number = Decimal(str(value))
                        except InvalidOperation:
                            raise ValueError('invalid price') from None
                        if not number.is_finite() or number < 0:
                            raise ValueError('invalid price')
                    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool) or len(str(value)) > 500:
                        raise ValueError('invalid display value')
                    # Load this operation-specific dependency only when requested.
                    from desktop_presentation import display_value

                    cells.append(display_value(value, key))
                output.append(cells)
            prepared.append((table, output))
        for table, rows in prepared:
            table.setRowCount(len(rows))
            for r, cells in enumerate(rows):
                for c, value in enumerate(cells):
                    table.setItem(r, c, QTableWidgetItem(value))


class MarketHistoryDialog(QDialog):
    """Typed, local-only import request. Dates are never inferred from a clock/calendar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(ui_text('market.__init__.text_70'))
        self.resize(800, 720)
        self.sessions = []
        self._payload = None
        layout = QVBoxLayout(self)
        layout.addWidget(_label(ui_text('market.__init__.text_71'), 'history_disclosure'))
        self.path = _named(QLineEdit(), 'history_path', ui_text('market.__init__.text_72'))
        self.path.setPlaceholderText(ui_text('market.__init__.text_73'))
        file_row = QHBoxLayout()
        file_row.addWidget(self.path)
        self.browse = _named(QPushButton(ui_text('market.__init__.text_74')), 'history_browse', ui_text('market.__init__.text_75'))
        self.browse.clicked.connect(self.choose_file)
        file_row.addWidget(self.browse)
        layout.addLayout(file_row)
        form = QFormLayout()
        layout.addLayout(form)
        self.product = _named(QComboBox(), 'history_product', ui_text('market.__init__.text_76'))
        for label, value in [
            (ui_text('market.__init__.text_77'), 'TX'),
            (ui_text('market.__init__.text_78'), 'MTX'),
            (ui_text('market.__init__.text_79'), 'TMF'),
        ]:
            self.product.addItem(label, value)
        form.addRow(ui_text('market.__init__.text_80'), self.product)
        self.month = _named(QLineEdit(), 'history_month', ui_text('market.__init__.text_81'))
        self.month.setPlaceholderText(ui_text('market.__init__.text_82'))
        form.addRow(ui_text('market.__init__.text_83'), self.month)
        self.expiry_type = _named(QComboBox(), 'history_expiry_type', ui_text('market.__init__.text_84'))
        self.expiry_type.addItem(ui_text('market.__init__.text_85'), 'monthly')
        self.expiry_type.addItem(ui_text('market.__init__.text_86'), 'weekly')
        self.week = _named(QSpinBox(), 'history_week', ui_text('market.__init__.text_87'))
        self.week.setRange(1, 5)
        self.week.setEnabled(False)
        expiry_row = QHBoxLayout()
        expiry_row.addWidget(self.expiry_type)
        expiry_row.addWidget(self.week)
        form.addRow(ui_text('market.__init__.text_88'), expiry_row)
        self.trade_date = _named(DateInput(), 'history_trade_date', ui_text('market.__init__.text_89'))
        self.trade_date.setPlaceholderText(ui_text('market.__init__.text_90'))
        form.addRow(ui_text('market.__init__.text_91'), self.trade_date)
        self.session = _named(QComboBox(), 'history_session', ui_text('market.__init__.text_92'))
        self.session.addItem(ui_text('market.__init__.text_93'), 'day')
        self.session.addItem(ui_text('market.__init__.text_94'), 'night')
        form.addRow(ui_text('market.__init__.text_95'), self.session)
        self.open_date = _named(DateInput(), 'history_open_date', ui_text('market.__init__.text_96'))
        self.open_date.setPlaceholderText('YYYY-MM-DD')
        self.end_date = _named(DateInput(), 'history_end_date', ui_text('market.__init__.text_97'))
        self.end_date.setPlaceholderText(ui_text('market.__init__.text_98'))
        self.open_time = _named(QTimeEdit(QTime(8, 45)), 'history_open_time', ui_text('market.__init__.text_99'))
        self.end_time = _named(QTimeEdit(QTime(13, 45)), 'history_end_time', ui_text('market.__init__.text_100'))
        for widget in (self.open_time, self.end_time):
            widget.setDisplayFormat('HH:mm')
        for title, date_widget, time_widget in [
            (ui_text('market.__init__.text_101'), self.open_date, self.open_time),
            (ui_text('market.__init__.text_102'), self.end_date, self.end_time),
        ]:
            row = QHBoxLayout()
            row.addWidget(date_widget)
            row.addWidget(time_widget)
            row.addWidget(history_utc_hint(date_widget, time_widget, self))
            form.addRow(title, row)
        self.include_end = _named(QCheckBox(ui_text('market.__init__.text_103')), 'history_include_end', ui_text('market.__init__.text_104'))
        form.addRow(self.include_end)
        self.source = _label('', 'history_product_source')
        layout.addWidget(self.source)
        layout.addWidget(_label(ui_text('market.__init__.text_105'), 'history_policy_disclosure'))
        self.confirm = _named(QCheckBox(ui_text('market.__init__.text_106')), 'history_confirm', ui_text('market.__init__.text_107'))
        layout.addWidget(self.confirm)
        row = QHBoxLayout()
        self.add = _named(QPushButton(ui_text('market.__init__.text_108')), 'history_add_session', ui_text('market.__init__.text_109'))
        self.add.clicked.connect(self.add_session)
        row.addWidget(self.add)
        self.remove = _named(QPushButton(ui_text('market.__init__.text_110')), 'history_remove_session', ui_text('market.__init__.text_111'))
        self.remove.clicked.connect(self.remove_session)
        row.addWidget(self.remove)
        layout.addLayout(row)
        self.session_list = _named(QListWidget(), 'history_sessions', ui_text('market.__init__.text_112'))
        layout.addWidget(self.session_list)
        self.error = _label('', 'history_error')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ui_text('market.__init__.text_113'))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(ui_text('market.__init__.text_114'))
        self.buttons.accepted.connect(self.accept_import)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for widget in (self.month, self.trade_date, self.open_date, self.end_date):
            widget.textChanged.connect(self._unconfirm)
        for widget in (self.product, self.expiry_type):
            widget.currentIndexChanged.connect(self._unconfirm)
        self.week.valueChanged.connect(self._unconfirm)
        for widget in (self.open_time, self.end_time):
            widget.timeChanged.connect(self._unconfirm)
        self.include_end.toggled.connect(self._unconfirm)
        self.session.currentIndexChanged.connect(self._session_defaults)
        self.expiry_type.currentIndexChanged.connect(lambda: self.week.setEnabled(self.expiry_type.currentData() == 'weekly'))
        self.product.currentIndexChanged.connect(self._source_label)
        self._source_label()
        # Load this operation-specific dependency only when requested.
        from desktop_expiry_inputs import attach_history_picker

        attach_history_picker(self, form)

    def _unconfirm(self, *args):
        self.confirm.setChecked(False)

    def _source_label(self, *args):
        # Load this operation-specific dependency only when requested.
        from quantlab.market_history import PRODUCT_SOURCES

        self.source.setText(ui_text('market._source_label.text_1').format(PRODUCT_SOURCES[self.product.currentData()]))

    def _session_defaults(self, *args):
        night = self.session.currentData() == 'night'
        self.open_time.setTime(QTime(15, 0) if night else QTime(8, 45))
        self.end_time.setTime(QTime(5, 0) if night else QTime(13, 45))
        self._unconfirm()

    def choose_file(self):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('market.choose_file.text_1'), '', 'TAIFEX CSV / RPT (*.csv *.rpt *.CSV *.RPT)')
        if name:
            self.path.setText(name)

    def session_payload(self):
        # Load this operation-specific dependency only when requested.
        from datetime import date, datetime, timezone, timedelta

        # Load this operation-specific dependency only when requested.
        from quantlab.market_history import PRODUCT_SOURCES, session_from_dict

        if not self.confirm.isChecked():
            raise ValueError('history_confirmation_required')
        month = self.month.text().strip()
        if not re.fullmatch(r'\d{4}(?:0[1-9]|1[0-2])', month):
            raise ValueError('history_expiry_invalid')
        expiry = month + ('W' + str(self.week.value()) if self.expiry_type.currentData() == 'weekly' else '')

        def local_time(field, clock):
            value = field.text().strip()
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('history_date_invalid')
            try:
                day = date.fromisoformat(value)
            except ValueError:
                raise ValueError('history_date_invalid') from None
            return (
                datetime(day.year, day.month, day.day, clock.time().hour(), clock.time().minute(), tzinfo=timezone(timedelta(hours=8)))
                .astimezone(timezone.utc)
                .isoformat()
            )

        product = self.product.currentData()
        value = dict(
            contract_id=f'TAIFEX:{product}:{expiry}',
            trade_date=self.trade_date.text().strip(),
            session=self.session.currentData(),
            open=local_time(self.open_date, self.open_time),
            end=local_time(self.end_date, self.end_time),
            include_end=self.include_end.isChecked(),
            source=PRODUCT_SOURCES[product],
        )
        try:
            session_from_dict(value)
        except (ValueError, TypeError, KeyError):
            raise ValueError('history_session_invalid') from None
        return value

    def add_session(self):
        try:
            if len(self.sessions) >= 128:
                raise ValueError('history_session_limit')
            value = self.session_payload()
            if value in self.sessions:
                raise ValueError('history_session_duplicate')
            # Reject overlap before starting a worker; module revalidates every request.
            from datetime import datetime

            for existing in self.sessions:
                if existing['contract_id'] != value['contract_id']:
                    continue
                if (existing['trade_date'], existing['session']) == (value['trade_date'], value['session']):
                    raise ValueError('history_session_day_overlap')
                a, b = datetime.fromisoformat(existing['open']), datetime.fromisoformat(existing['end'])
                c, d = datetime.fromisoformat(value['open']), datetime.fromisoformat(value['end'])
                if max(a, c) < min(b, d) or (b == c and existing['include_end']) or (d == a and value['include_end']):
                    raise ValueError('history_session_overlap')
            self.sessions.append(value)
            label = ui_text('market.add_session.text_3').format(
                value['contract_id'],
                value['trade_date'],
                value['session'],
                self.open_date.text(),
                self.open_time.text(),
                self.end_date.text(),
                self.end_time.text(),
                ui_text('market.add_session.text_1') if value['include_end'] else ui_text('market.add_session.text_2'),
            )
            self.session_list.addItem(label)
            self.confirm.setChecked(False)
            self.error.clear()
        except (ValueError, TypeError, KeyError) as exc:
            self.error.setText(error_message(exception_code(exc)))

    def remove_session(self):
        row = self.session_list.currentRow()
        if row >= 0:
            self.sessions.pop(row)
            self.session_list.takeItem(row)

    def request_payload(self):
        # Load this operation-specific dependency only when requested.
        from pathlib import Path

        path = self.path.text().strip()
        if not path or Path(path).suffix.lower() not in ('.csv', '.rpt'):
            raise ValueError('history_file_required')
        if not self.sessions:
            raise ValueError('history_sessions_required')
        return {'history_import': True, 'local_path': path, 'sessions': deepcopy(self.sessions), 'dated_policy_confirmed': True}

    def accept_import(self):
        try:
            self._payload = self.request_payload()
        except ValueError as exc:
            self.error.setText(error_message(exception_code(exc)))
            return
        self.accept()

    def payload(self):
        if self._payload is None:
            raise ValueError(ui_text('market.payload.text_1'))
        return deepcopy(self._payload)
