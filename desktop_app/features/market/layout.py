from desktop_app.components.fields import named_field
from desktop_app.shell.theme import set_status
from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QComboBox, QListWidget, QSplitter, QCheckBox, QPlainTextEdit
from quantlab.chart_data import TIMEFRAMES
from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.rows import _label


def _build_market_header(self, root):
    header = QHBoxLayout()
    title = _label(ui_text('market.init.title'), 'market_title')
    header.addWidget(title)
    header.addStretch()
    header.addWidget(_label(ui_text('market.init.historical_market'), 'market_safety'))
    self.refresh_button = named_field(QPushButton(ui_text('market.init.update_official')), 'market_refresh', ui_text('market.init.update_official'))
    self.refresh_button.setToolTip(ui_text('market.init.consent_hint'))
    self.refresh_button.clicked.connect(self.refresh_requested.emit)
    header.addWidget(self.refresh_button)
    root.addLayout(header)
    self.research_summary = _label('', 'market_research_summary')
    self.research_summary.hide()
    root.addWidget(self.research_summary)
    return header


def _build_market_cards(self, root, PanelCard):
    cards_widget = QWidget()
    cards = QHBoxLayout(cards_widget)
    cards.setContentsMargins(0, 0, 0, 0)
    self.cards = {}
    for key, title in [
        ('TAIEX', ui_text('market.init.weighted_index')),
        ('TX', ui_text('market.init.index_futures')),
        ('MXF', ui_text('market.init.mini_futures')),
        ('TMF', ui_text('market.init.micro_futures')),
    ]:
        group = PanelCard(title)
        layout = group.content_layout()
        layout.setContentsMargins(8, 8, 8, 6)
        value = _label(ui_text('market.init.no_data'), 'market_card_' + key)
        layout.addWidget(value)
        cards.addWidget(group)
        self.cards[key] = value
    root.addWidget(cards_widget)
    return cards_widget


def _build_market_diagnostics(self, root):
    self.source_status = _label(ui_text('market.init.offline'), 'market_source_status')
    source_row = QHBoxLayout()
    source_row.addWidget(self.source_status, 1)
    self.diagnostics_button = named_field(
        QPushButton(ui_text('market.init.diagnostics_collapsed')), 'market_diagnostics_toggle', ui_text('market.init.expand_diagnostics')
    )
    self.diagnostics_button.setCheckable(True)
    source_row.addWidget(self.diagnostics_button)
    root.addLayout(source_row)
    self.diagnostics = named_field(QPlainTextEdit(), 'market_diagnostics', ui_text('market.init.full_diagnostics'))
    self.diagnostics.setReadOnly(True)
    self.diagnostics.setMaximumHeight(160)
    self.diagnostics.hide()
    self.diagnostics_button.toggled.connect(self._toggle_diagnostics)
    root.addWidget(self.diagnostics)
    self.converge_annotations = named_field(
        QCheckBox(ui_text('market.converge_annotations')), 'market_converge_annotations', ui_text('market.converge_annotations')
    )
    self.converge_annotations.setToolTip(ui_text('market.converge_annotations_hint'))
    self.converge_annotations.setChecked(True)
    self.converge_annotations.hide()
    self.diagnostics_button.toggled.connect(self.converge_annotations.setVisible)
    self.converge_annotations.toggled.connect(self._annotation_preferences_changed)
    self.series_rendered.connect(lambda _: self.refresh_annotations())
    root.addWidget(self.converge_annotations)
    return source_row


def _build_market_empty_actions(self, root):
    self.message = _label(ui_text('market.init.contract_hint'), 'market_message')
    set_status(self.message, 'warning')
    root.addWidget(self.message)
    self.empty_actions = QWidget()
    actions = QHBoxLayout(self.empty_actions)
    actions.setContentsMargins(0, 0, 0, 0)
    self.sample_button = named_field(QPushButton(ui_text('market.load_sample')), 'market_load_sample', ui_text('market.load_sample'))
    self.sample_button.setToolTip(ui_text('market.sample_label'))
    self.sample_button.clicked.connect(self.sample_requested.emit)
    actions.addWidget(self.sample_button)
    self.official_button = named_field(QPushButton(ui_text('market.download_official')), 'market_download_official', ui_text('market.download_official'))
    self.official_button.setToolTip(ui_text('market.official_consent'))
    self.official_button.clicked.connect(self.refresh_requested.emit)
    actions.addWidget(self.official_button)
    root.addWidget(self.empty_actions)
    self.refresh_button.hide()


def _build_market_watchlist(self, root):
    self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
    root.addWidget(self.main_splitter, 1)
    left = QWidget()
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 4, 0)
    left_layout.addWidget(_label(ui_text('market.init.watch_title'), 'market_watch_title'))
    self.search = named_field(QLineEdit(), 'market_search', ui_text('market.init.search_accessible_name'))
    self.search.setPlaceholderText(ui_text('market.init.search_placeholder'))
    self.search.textChanged.connect(self._filter_catalog)
    left_layout.addWidget(self.search)
    self.catalog_combo = named_field(QComboBox(), 'market_catalog', ui_text('market.init.available_contracts'))
    left_layout.addWidget(self.catalog_combo)
    self.add_button = named_field(QPushButton(ui_text('market.init.add_watch')), 'market_add', ui_text('market.init.add_watch_accessible_name'))
    self.add_button.clicked.connect(self._add_watch)
    left_layout.addWidget(self.add_button)
    self.watchlist = named_field(QListWidget(), 'market_watchlist', ui_text('market.init.watchlist'))
    self.watchlist.currentItemChanged.connect(self._watch_selected)
    left_layout.addWidget(self.watchlist, 1)
    row = QHBoxLayout()
    self.remove_button = named_field(QPushButton(ui_text('market.init.remove_watch')), 'market_remove', ui_text('market.init.remove_watch_accessible_name'))
    self.remove_button.clicked.connect(self._remove_watch)
    row.addWidget(self.remove_button)
    for text, delta, name in [('↑', -1, 'up'), ('↓', 1, 'down')]:
        button = named_field(
            QPushButton(text), 'market_watch_' + name, ui_text('market.init.move_watch_up') if delta < 0 else ui_text('market.init.move_watch_down')
        )
        button.clicked.connect(lambda checked=False, d=delta: self._move_watch(d))
        row.addWidget(button)
    left_layout.addLayout(row)
    self.main_splitter.addWidget(left)
    return left


def _build_market_chart(self):
    center = QWidget()
    center_layout = QVBoxLayout(center)
    center_layout.setContentsMargins(4, 0, 4, 0)
    control = QHBoxLayout()
    self.contract_combo = named_field(QComboBox(), 'market_contract', ui_text('market.init.chart_contract'))
    self.contract_combo.currentIndexChanged.connect(self._contract_changed)
    control.addWidget(self.contract_combo, 1)
    self.timeframe_combo = named_field(QComboBox(), 'market_timeframe', ui_text('market.init.timeframe'))
    for text, value in zip(
        (
            ui_text('market.init.minute_one'),
            ui_text('market.init.minute_three'),
            ui_text('market.init.minute_five'),
            ui_text('market.init.minute_fifteen'),
            ui_text('market.init.minute_thirty'),
            ui_text('market.init.minute_sixty'),
            ui_text('market.init.daily'),
            ui_text('market.init.weekly'),
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
    return center
