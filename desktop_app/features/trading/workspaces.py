"""Workspace composition; all actions delegate to the window command boundary."""

from desktop_app.features.trading.automatic_status import AutomaticControls
from desktop_app.features.trading.account_risk_controls import AccountRiskControls

from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QLayout,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.manual_actions import ManualActions
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment
from desktop_app.features.trading.widgets import button, combo, label, table
from desktop_app.features.trading.sinopac_ui import install_panel
from desktop_app.features.trading.dashboard import DashboardWidget
from desktop_app.features.trading.trading_page import (
    install_trading_environment,
    configure_trading_actions,
    configure_trading_positions,
    confirm_trading_action,
)
from desktop_app.features.trading.page_help import HelpText
from desktop_app.features.trading.strategy_controls import StrategyControls
from desktop_app.features.trading.trading_page_widgets import EmptyTableState, PositionColumns


PAGE_KEYS = {
    'overview': 'v2.overview',
    'strategy': 'v2.strategy',
    'market': 'v2.market',
    'trading': 'v2.trading',
    'performance': 'v2.performance',
    'settings': 'v2.settings',
}


def build(self) -> None:
    root = QWidget()
    outer = QVBoxLayout(root)
    outer.setContentsMargins(12, 10, 12, 10)
    self.context = QLabel()
    self.context.setTextFormat(Qt.TextFormat.PlainText)
    self.context.setObjectName('persistent_context')
    self.context.setWordWrap(True)
    self.context.setAccessibleName(ui_text('v2.persistent_context'))
    self.summary = QLabel()
    self.summary.setTextFormat(Qt.TextFormat.PlainText)
    self.summary.setWordWrap(True)
    self.summary.setObjectName('persistent_summary')
    self.notice = QLabel()
    self.notice.setTextFormat(Qt.TextFormat.PlainText)
    self.notice.setObjectName('trading_notice')
    self.notice.setWordWrap(True)
    header = QHBoxLayout()
    header.addWidget(self.context, 1)
    self.chatgpt_button = button('redesign.header.connection', 'unified_chatgpt_connection')
    self.chatgpt_button.setMaximumWidth(270)
    header.addWidget(self.chatgpt_button)
    outer.addLayout(header)
    self.research_job = QLabel()
    self.research_job.setTextFormat(Qt.TextFormat.PlainText)
    self.research_job.setObjectName('unified_research_job')
    self.research_job.setWordWrap(False)
    summary_row = QHBoxLayout()
    summary_row.addWidget(self.summary, 1)
    summary_row.addWidget(self.research_job)
    self.cancel_research_button = button('unified.cancel_research', 'unified_cancel_research')
    self.cancel_research_button.setToolTip(ui_text('unified.cancel_research_hint'))
    self.cancel_research_button.setEnabled(False)
    summary_row.addWidget(self.cancel_research_button)
    outer.addLayout(summary_row)
    outer.addWidget(self.notice)
    body = QHBoxLayout()
    self.navigation = QListWidget()
    self.navigation.setObjectName('trading_navigation')
    self.navigation.setAccessibleName(ui_text('v2.navigation'))
    self.navigation.setMaximumWidth(160)
    self.navigation.setMinimumWidth(105)
    self.navigation.addItems([ui_text(key) for key in PAGE_KEYS.values()])
    self.pages = QStackedWidget()
    self.pages.setObjectName('trading_workspaces')
    body.addWidget(self.navigation)
    body.addWidget(self.pages, 1)
    outer.addLayout(body, 1)
    self.setCentralWidget(root)
    _overview_page(self)
    _strategy_page(self)
    _market_page(self)
    _trading_page(self)
    _performance_page(self)
    _settings_page(self)
    self.automatic_controls = AutomaticControls(self, header)
    self.account_risk_controls = AccountRiskControls(self)
    self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
    self.navigation.itemClicked.connect(lambda item: self.pages.setCurrentIndex(self.navigation.row(item)))
    self.navigation.itemActivated.connect(lambda item: self.pages.setCurrentIndex(self.navigation.row(item)))

    def selected_workspace():
        # Accessibility selection changes do not necessarily move Qt's current
        # index. Keep the same read-only route authoritative for every input.
        selected = self.navigation.selectedItems()
        if len(selected) == 1:
            row = self.navigation.row(selected[0])
            if self.navigation.currentRow() != row:
                self.navigation.setCurrentRow(row)
            self.pages.setCurrentIndex(row)

    self.navigation.itemSelectionChanged.connect(selected_workspace)
    self.navigation.setCurrentRow(0)
    self.setStyleSheet('''
        QMainWindow {background:#f3f6fa; color:#152438;}
        QLabel {color:#152438;}
        QPushButton {padding:6px 10px; border:1px solid #b3c4d9; border-radius:5px; background:#ffffff;}
        QPushButton:hover {background:#e4efff;}
        QPushButton:focus {border:2px solid #185db8;}
        QPushButton:disabled {color:#697587; background:#eef1f5;}
        QListWidget {background:#132b48; color:#ffffff; border-radius:8px; padding:5px;}
        QListWidget::item {padding:14px 8px;}
        QListWidget::item:selected {background:#235fa8; border-radius:5px;}
        QTableWidget {background:#ffffff; alternate-background-color:#f0f5fb; gridline-color:#d9e2ee; border:1px solid #d9e2ee;}
        QHeaderView::section {background:#e5edf7; padding:7px; color:#152438;}
        QGroupBox {background:#ffffff; border:1px solid #d9e2ee; border-radius:6px; margin-top:12px; padding-top:14px;}
        QLineEdit,QComboBox,QSpinBox {padding:6px; border:1px solid #9eafc3; border-radius:4px; background:#ffffff;}
        QLabel#persistent_context {background:#132b48; color:white; padding:10px; border-radius:6px; font-weight:600;}
        QLabel#persistent_summary {padding:6px; font-weight:600;}
        QLabel#trading_notice {color:#8a3f04; padding:5px;}
    ''')


def _page(self, name: str) -> QVBoxLayout:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setObjectName(name + '_scroll')
    content = QWidget()
    content.setMinimumWidth(330)
    layout = QVBoxLayout(content)
    layout.setSpacing(12)
    title = label(PAGE_KEYS[name])
    title.setProperty('workspaceTitle', True)
    header = QHBoxLayout()
    header.addWidget(title)
    header.addStretch(1)
    if not hasattr(self, 'page_headers'):
        self.page_headers = {}
    self.page_headers[name] = header
    layout.addLayout(header)
    scroll.setWidget(content)
    self.pages.addWidget(scroll)
    return layout


def _buttons(self, layout, definitions: tuple[tuple[str, str, object], ...]) -> None:
    grid = QGridLayout()
    for index, (key, name, callback) in enumerate(definitions):
        widget = button(key, name)
        widget.clicked.connect(callback)
        grid.addWidget(widget, index // 2, index % 2)
        setattr(self, name, widget)
    layout.addLayout(grid)


def _overview_page(self) -> None:
    layout = _page(self, 'overview')
    self.dashboard = DashboardWidget(lambda action: confirm_trading_action(self, action), help_header=self.page_headers['overview'])
    self.dashboard.strategy_setup.clicked.connect(lambda: (self.navigation.setCurrentRow(1), self.new_strategy()))
    layout.addWidget(self.dashboard)
    self.overview_status = self.dashboard.status
    self.overview_deployments = self.dashboard.strategy_summary
    self.issue_details = self.dashboard.issue_details
    self.events = self.dashboard.events
    self.overview_stop = self.dashboard.operation_buttons[UiAction.STOP_NEW]
    self.overview_cancel_entries = self.dashboard.operation_buttons[UiAction.CANCEL_ENTRIES]
    self.overview_reconcile = self.dashboard.operation_buttons[UiAction.RECONCILE]
    layout.addWidget(HelpText(ui_text('m2t.overview_hint'), ui_text('v2.start_hint'), 'overview_start', header=self.page_headers['overview']))
    _buttons(
        self,
        layout,
        (
            ('v2.new_strategy', 'overview_new_strategy', lambda: (self.navigation.setCurrentRow(1), self.new_strategy())),
            ('v2.local_step', 'overview_step', lambda: self.command(UiAction.STEP)),
        ),
    )
    layout.addStretch()


def _strategy_page(self) -> None:
    layout = _page(self, 'strategy')
    self.strategy_tabs = QTabWidget()
    self.strategy_tabs.setObjectName('strategy_tabs')
    self.strategy_tabs.setAccessibleName(ui_text('v2.strategies'))
    listing, research = QWidget(), QWidget()
    listing_layout, research_layout = QVBoxLayout(listing), QVBoxLayout(research)
    _buttons(
        self,
        listing_layout,
        (
            ('v2.new_strategy', 'new_strategy_button', self.new_strategy),
            ('v2.new_version', 'version_button', self.new_version),
            ('v2.deploy', 'deploy_button', self.deploy_selected),
            ('u3.clone', 'clone_strategy_button', lambda: self.strategy_controls.manage(UiAction.CLONE_STRATEGY)),
            ('u3.disable', 'disable_strategy_button', lambda: self.strategy_controls.manage(UiAction.DISABLE_STRATEGY)),
            ('u3.delete', 'delete_strategy_button', lambda: self.strategy_controls.manage(UiAction.DELETE_STRATEGY)),
            ('u3.go_research', 'go_strategy_research', lambda: self.strategy_controls.research()),
        ),
    )
    for name in ('disable_strategy_button', 'delete_strategy_button'):
        getattr(self, name).setProperty('role', 'danger')
    listing_layout.addWidget(label('v2.version_hint'))
    self.strategies = table(
        (
            'v2.name',
            'v2.version',
            'v2.market',
            'v2.instrument',
            'v2.policy',
            'v2.state',
            'v2.account',
            'v2.evidence',
            'v2.environment',
            'dashboard.today.net_pnl',
            'u3.recent_signal',
        ),
        'strategies',
    )
    self.strategies.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    self.strategies.setWordWrap(False)
    self.strategies.setTextElideMode(Qt.TextElideMode.ElideRight)
    self.strategy_columns = PositionColumns(
        self.strategies,
        self.page_headers['strategy'],
        self._strategy_columns,
        self._save_strategy_columns,
        self._feedback,
        defaults=(0, 3, 4, 5, 8, 9),
        name='strategy_columns',
    )
    listing_layout.addWidget(self.strategies)
    self.strategies_empty = EmptyTableState(self.strategies, ui_text('m2t.empty_strategy_reason'), self.new_strategy)
    self.strategies_empty.next.setText(ui_text('v2.new_strategy'))
    self.strategies_empty.next.setAccessibleName(ui_text('v2.new_strategy'))
    _buttons(
        self,
        research_layout,
        (
            ('v2.validate', 'validate_button', lambda: self._strategy_action(UiAction.VALIDATE)),
            ('v2.research', 'research_button', lambda: self._strategy_action(UiAction.RESEARCH)),
            ('v2.legacy_research', 'legacy_research_button', lambda: self.legacy_requested.emit('strategy')),
            ('unified.page.assistant', 'ai_assistant_button', lambda: self.legacy_requested.emit('assistant')),
        ),
    )
    self.strategy_controls = StrategyControls(self, listing_layout, research_layout)
    listing_layout.addStretch()
    research_layout.addStretch()
    self.strategy_tabs.addTab(listing, ui_text('v2.strategies'))
    self.strategy_tabs.addTab(research, ui_text('v2.research'))
    layout.addWidget(self.strategy_tabs)


def _market_page(self) -> None:
    if self.market_watch is not None and self.market_watch.objectName() == 'market_terminal':
        content = QWidget()
        content.setObjectName('market_workspace')
        content.setAccessibleName(ui_text('terminal.title'))
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.market_watch, 1)
        self.pages.addWidget(content)
        # Retain the historical table/route API for the host's general renderer.
        self.market_refresh_button = button('v2.refresh_market', 'market_refresh_button')
        self.market_refresh_button.clicked.connect(self.refresh)
        self.market_archive = button('v2.markets', 'market_archive')
        self.market_archive.setCheckable(True)
        self.market_archive_content = QWidget(content)
        self.market_archive_content.hide()
        self.markets = table(('v2.instrument', 'v2.market', 'v2.unit', 'v2.price', 'v2.quote_time', 'v2.availability', 'v2.source'), 'markets')
        self.markets.setParent(self.market_archive_content)
        return
    layout = _page(self, 'market')
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    layout.addWidget(label('v2.market_data_hint'))
    self.market_refresh_button = button('v2.refresh_market', 'market_refresh_button')
    self.market_refresh_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    self.market_refresh_button.setToolTip(ui_text('v2.refresh_market_hint'))
    self.market_refresh_button.clicked.connect(self.refresh)
    layout.addWidget(self.market_refresh_button)
    if self.market_watch is not None:
        layout.addWidget(self.market_watch, 1)
    self.market_archive = button('v2.markets', 'market_archive')
    self.market_archive.setCheckable(True)
    self.market_archive.setChecked(False)
    self.market_archive_content = QWidget()
    self.market_archive_content.setObjectName('market_archive_content')
    self.market_archive_content.setAccessibleName(ui_text('v2.markets'))
    archive = QVBoxLayout(self.market_archive_content)
    self.markets = table(('v2.instrument', 'v2.market', 'v2.unit', 'v2.price', 'v2.quote_time', 'v2.availability', 'v2.source'), 'markets')
    archive.addWidget(self.markets)
    _buttons(
        self,
        archive,
        (
            ('v2.legacy_import', 'legacy_import_button', lambda: self.legacy_requested.emit('data')),
            ('v2.legacy_market', 'legacy_market_button', lambda: self.legacy_requested.emit('market')),
        ),
    )
    self.market_archive_content.setVisible(False)
    self.market_archive.toggled.connect(self.market_archive_content.setVisible)
    layout.addWidget(self.market_archive)
    layout.addWidget(self.market_archive_content)
    layout.addStretch()


def _trading_page(self) -> None:
    layout = _page(self, 'trading')
    install_trading_environment(self, layout, self.pages.widget(3).widget())
    layout.addWidget(HelpText(ui_text('m2t.trading_hint'), ui_text('v2.control_hint'), 'trading_control', header=self.page_headers['trading']))
    _buttons(
        self,
        layout,
        (
            ('v2.stop_new', 'stop_button', lambda: confirm_trading_action(self, UiAction.STOP_NEW)),
            ('v2.cancel_entries', 'cancel_entries_button', lambda: confirm_trading_action(self, UiAction.CANCEL_ENTRIES)),
            ('v2.resume', 'resume_button', lambda: self.manual_controls.resume()),
            ('v2.reconcile', 'reconcile_button', lambda: self.command(UiAction.RECONCILE)),
            ('v2.flatten', 'flatten_button', self.flatten_selected),
            ('v2.transfer', 'transfer_button', self.transfer_selected),
        ),
    )
    configure_trading_actions(self)
    layout.addWidget(label('v2.positions'))
    self.positions = table(
        (
            'v2.instrument',
            'v2.quantity',
            'v2.sellable',
            'v2.policy',
            'v2.account',
            'v2.strategy_version',
            'v2.entry_day',
            'v2.policy_held_days',
            'v2.exit_window',
            'v2.protection',
            'v2.source',
            'v2.quote_time',
        ),
        'positions',
    )
    configure_trading_positions(self.positions)
    self.position_columns = PositionColumns(self.positions, self.page_headers['trading'], self._position_columns, self._save_position_columns, self._feedback)
    layout.addWidget(self.positions)
    self.positions_empty = EmptyTableState(self.positions, ui_text('m2t.empty_positions'), lambda: self.manual_controls.next_step())
    layout.addWidget(label('v2.orders'))
    self.orders = table(('v2.instrument', 'v2.direction', 'v2.quantity', 'v2.filled', 'v2.state', 'v2.order_scope', 'v2.account'), 'orders')
    self.order_columns = PositionColumns(
        self.orders,
        self.page_headers['trading'],
        self._order_columns,
        self._save_order_columns,
        self._feedback,
        defaults=(0, 1, 2, 3, 4, 5),
        name='order_columns',
        caption=ui_text('m2m.order_columns'),
        hint=ui_text('m2m.order_columns_hint'),
    )
    layout.addWidget(self.orders)
    self.orders_empty = EmptyTableState(self.orders, ui_text('m2t.empty_orders'), lambda: self.manual_controls.next_step())
    self.manual_controls = ManualActions(self, layout)
    _reconciliation_panel(self, layout)
    layout.addStretch()


def _reconciliation_panel(self, layout) -> None:
    layout.addWidget(label('v2.reconciliation_title'))
    layout.addWidget(
        HelpText(ui_text('m2t.reconciliation_hint'), ui_text('v2.reconciliation_hint'), 'trading_reconciliation', header=self.page_headers['trading'])
    )
    self.reconciliation_status = label('v2.reconciliation_unknown')
    self.reconciliation_status.setObjectName('reconciliation_status')
    layout.addWidget(self.reconciliation_status)
    self.reconciliation = table(
        (
            'v2.account',
            'v2.instrument',
            'v2.reconciliation_kind',
            'v2.reconciliation_local',
            'v2.reconciliation_broker',
            'v2.reconciliation_delta',
            'v2.sellable',
            'v2.reconciliation_order_ref',
            'v2.state',
            'v2.reconciliation_as_of',
        ),
        'reconciliation_differences',
    )
    self.reconciliation.itemSelectionChanged.connect(lambda: self.positions.clearSelection() if self.reconciliation.selectedItems() else None)
    self.positions.itemSelectionChanged.connect(lambda: self.reconciliation.clearSelection() if self.positions.selectedItems() else None)
    layout.addWidget(self.reconciliation)


def _performance_page(self) -> None:
    layout = _page(self, 'performance')
    layout.addWidget(
        HelpText(
            ui_text('m2t.performance_hint'),
            ui_text('v2.performance_hint') + '\n\n' + ui_text('v2.performance_valuation_hint'),
            'performance_explanation',
            header=self.page_headers['performance'],
        )
    )
    self.performance = table(
        (
            'v2.strategy_version',
            'v2.market',
            'v2.policy',
            'v2.environment',
            'v2.net_pnl',
            'v2.unrealized',
            'v2.costs',
            'v2.attributed_pnl',
            'v2.drawdown_recorded',
            'v2.held_days',
            'v2.drawdown_coverage',
            'v2.drawdown_as_of',
        ),
        'performance_rows',
    )
    self.performance.horizontalHeaderItem(7).setToolTip(ui_text('v2.attributed_pnl_hint'))
    self.performance.horizontalHeaderItem(8).setToolTip(ui_text('v2.drawdown') + '\n' + ui_text('v2.performance_valuation_hint'))
    self.performance.horizontalHeaderItem(7).setText(ui_text('m2t.adjusted_pnl'))
    self.performance.horizontalHeaderItem(8).setText(ui_text('m2t.recorded_drawdown'))
    layout.addWidget(self.performance)
    _buttons(
        self,
        layout,
        (
            ('v2.legacy_backtest', 'legacy_backtest_button', lambda: self.legacy_requested.emit('backtest')),
            ('v2.legacy_compare', 'legacy_compare_button', lambda: self.legacy_requested.emit('compare')),
        ),
    )
    layout.addStretch()


def _settings_page(self) -> None:
    layout = _page(self, 'settings')
    self.environment = combo((('v2.local', Environment.LOCAL), ('v2.broker_sim', Environment.BROKER_SIMULATION), ('v2.live', Environment.LIVE)), 'environment')
    self.account = QComboBox()
    self.account.setObjectName('account_context')
    self.account.setAccessibleName(ui_text('v2.account'))
    form = QFormLayout()
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.addRow(ui_text('v2.environment'), self.environment)
    form.addRow(ui_text('v2.account'), self.account)
    layout.addLayout(form)
    self.environment.currentIndexChanged.connect(self._environment_selected)
    self.account.currentIndexChanged.connect(self._switch_context)
    layout.addWidget(
        HelpText(
            ui_text('m2.connection.context_hint'),
            ui_text('m2.connection.context_help') + '\n\n' + ui_text('v2.external_hint'),
            'settings_context',
            header=self.page_headers['settings'],
        )
    )
    self.accounts = table(('v2.account', 'v2.environment', 'v2.market', 'v2.allocation', 'v2.availability'), 'accounts')
    install_panel(self, layout)
    self.advanced = QGroupBox(ui_text('v2.advanced'))
    self.advanced.setCheckable(True)
    self.advanced.setChecked(False)
    advanced_layout = QVBoxLayout(self.advanced)
    self.advanced_content = QWidget()
    fields = QFormLayout(self.advanced_content)
    fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    fields.addRow(self.accounts)
    self.add_context_button = button('m2.connection.legacy_import', 'add_context_button')
    self.add_context_button.clicked.connect(self.add_context)
    fields.addRow(self.add_context_button)
    self.stock_budget = QLineEdit()
    self.futures_budget = QLineEdit()
    self.setting_risk = combo((('v2.risk_2', Decimal('0.02')), ('v2.risk_3', Decimal('0.03'))), 'risk')
    for widget, name in ((self.stock_budget, 'stock_budget'), (self.futures_budget, 'futures_budget')):
        widget.setObjectName(name)
        widget.setAccessibleName(ui_text('v2.' + name))
        widget.textEdited.connect(self._dirty_settings)
        fields.addRow(ui_text('v2.' + name), widget)
    self.setting_risk.currentIndexChanged.connect(self._dirty_settings)
    fields.addRow(ui_text('v2.risk'), self.setting_risk)
    fields.addRow(HelpText(ui_text('m2t.settings_hint'), ui_text('v2.settings_hint'), 'settings_limits', header=self.page_headers['settings']))
    save = button('v2.save_settings', 'save_settings_button')
    save.clicked.connect(self.save_settings)
    fields.addRow(save)
    self.diagnostics = QLabel()
    self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
    self.diagnostics.setWordWrap(True)
    fields.addRow(self.diagnostics)
    advanced_layout.addWidget(self.advanced_content)
    self.advanced_content.setVisible(False)
    self.advanced.toggled.connect(self.advanced_content.setVisible)
    layout.addWidget(self.advanced)
    _buttons(
        self,
        layout,
        (
            ('v2.legacy_recovery', 'legacy_recovery_button', lambda: self.legacy_requested.emit('settings')),
            ('v2.close_engine', 'shutdown_button', self.shutdown_engine),
            ('v2.close_ui', 'close_ui_button', self.close),
        ),
    )
    layout.addStretch()
