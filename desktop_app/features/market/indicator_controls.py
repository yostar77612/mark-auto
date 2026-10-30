from desktop_app.strings.catalog import ui_text
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QCheckBox, QSpinBox, QDoubleSpinBox, QScrollArea, QTabWidget
from desktop_app.features.market.indicator_presenter import DEFAULT_INDICATORS
from desktop_app.features.market.rows import _label, _named


def _build_market_trading_status(self, source_row, PanelCard):
    right_scroll = QScrollArea()
    right_scroll.setWidgetResizable(True)
    right_scroll.setMinimumWidth(175)
    right = QWidget()
    right_layout = QVBoxLayout(right)
    self.trading_labels = {}
    state = PanelCard(ui_text('market.init.trading_title'))
    state_layout = state.content_layout()
    for key, title in [('strategy', ui_text('market.init.strategy')), ('paper', ui_text('market.init.paper')), ('risk', ui_text('market.init.risk'))]:
        label = _label(ui_text('market.init.unknown_status').format(title), 'market_state_' + key)
        state_layout.addWidget(label)
        self.trading_labels[key] = label
    source_row.addWidget(_label(ui_text('market.init.research_paper'), 'market_live_disabled'))
    state_layout.addWidget(_label(ui_text('market.init.research_paper'), 'market_live_disabled_detail'))
    right_layout.addWidget(state)
    return (right_scroll, right, right_layout)


def _build_market_indicators(self, right_scroll, right, right_layout, PanelCard):
    group = PanelCard(ui_text('market.init.indicators_title'))
    grid = QGridLayout()
    group.content_layout().addLayout(grid)
    row = 0
    for key, config in DEFAULT_INDICATORS.items():
        check = _named(QCheckBox(key), 'market_indicator_' + key, ui_text('market.init.indicator_name').format(key))
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
                spin = QDoubleSpinBox() if param in ('deviations', 'multiplier', 'step', 'maximum', 'percent') else QSpinBox()
                spin.setRange(
                    0.01 if param in ('step', 'maximum') else 0.1 if param in ('deviations', 'multiplier', 'percent') else 1,
                    1 if param in ('step', 'maximum') else 1000,
                )
                spin.setValue(number)
                field = f'{param}_{index}' if isinstance(value, list) else param
                _named(spin, f'market_{key}_{field}', ui_text('access.indicator_parameter').format(key, field))
                grid.addWidget(
                    _label(
                        ui_text('market.init.moving_average').format(str(index + 1))
                        if param == 'periods'
                        else {
                            'multiplier': ui_text('market.indicator.multiplier'),
                            'step': ui_text('market.indicator.step'),
                            'maximum': ui_text('market.indicator.maximum'),
                            'percent': ui_text('market.indicator.percent'),
                            'period': ui_text('market.init.periods'),
                            'fast': ui_text('market.init.fast'),
                            'slow': ui_text('market.init.slow'),
                            'signal': ui_text('market.init.signal'),
                            'k_period': ui_text('market.init.k_smoothing'),
                            'd_period': ui_text('market.init.d_smoothing'),
                            'deviations': ui_text('market.init.standard_deviations'),
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
    right_layout.addWidget(_label(ui_text('market.init.vwap_hint'), 'market_vwap_disclosure'))
    right_layout.addStretch()
    right_scroll.setWidget(right)
    self.main_splitter.addWidget(right_scroll)


def _build_market_panel_toggle(self, right_scroll, header):
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


def _build_market_tables(self, root):
    self.tables = QTabWidget()
    self.tables.setMaximumHeight(180)
    self.tables.setMinimumHeight(95)
    self.positions_table = self._table(
        (ui_text('market.init.position_contract'), ui_text('market.init.position_quantity'), ui_text('market.init.average_price')), 'market_positions'
    )
    self.orders_table = self._table(
        (
            ui_text('market.init.order_id'),
            ui_text('market.init.order_contract'),
            ui_text('market.init.order_side'),
            ui_text('market.init.order_quantity'),
            ui_text('market.init.order_status'),
        ),
        'market_orders',
    )
    self.fills_table = self._table(
        (
            ui_text('market.init.fill_id'),
            ui_text('market.init.fill_contract'),
            ui_text('market.init.fill_side'),
            ui_text('market.init.fill_quantity'),
            ui_text('market.init.fill_price'),
        ),
        'market_fills',
    )
    for title, table in [
        (ui_text('market.init.positions'), self.positions_table),
        (ui_text('market.init.orders'), self.orders_table),
        (ui_text('market.init.fills'), self.fills_table),
    ]:
        self.tables.addTab(table, title)
    root.addWidget(self.tables)


def _build_market_workspace(self, root, header, cards_widget, left, center):
    from desktop_app.features.market.workspace import MarketWorkspace

    self.workspace = MarketWorkspace(self, root, header, cards_widget, left, center)
    from desktop_app.features.market.chart_popout import PopoutController

    self.popout = PopoutController(self)
