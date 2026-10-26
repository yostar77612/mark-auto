"""Workspace composition; all actions delegate to the window command boundary."""

from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from desktop_strings import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment
from .widgets import button, combo, label, table
from .broker_panel import BrokerPanel


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
    self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
    self.navigation.itemClicked.connect(lambda item: self.pages.setCurrentIndex(self.navigation.row(item)))
    self.navigation.itemActivated.connect(lambda item: self.pages.setCurrentIndex(self.navigation.row(item)))
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
    title.setStyleSheet('font-size:20px;font-weight:600;')
    layout.addWidget(title)
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
    layout.addWidget(label('v2.start_hint'))
    _buttons(
        self,
        layout,
        (
            ('v2.new_strategy', 'overview_new_strategy', self.new_strategy),
            ('v2.local_step', 'overview_step', lambda: self.command(UiAction.STEP)),
            ('v2.stop_new', 'overview_stop', lambda: self.command(UiAction.STOP_NEW)),
            ('v2.reconcile', 'overview_reconcile', lambda: self.command(UiAction.RECONCILE)),
        ),
    )
    self.overview_status = QLabel()
    self.overview_status.setTextFormat(Qt.TextFormat.PlainText)
    self.overview_status.setWordWrap(True)
    layout.addWidget(self.overview_status)
    self.overview_deployments = QLabel()
    self.overview_deployments.setTextFormat(Qt.TextFormat.PlainText)
    self.overview_deployments.setWordWrap(True)
    self.overview_deployments.setObjectName('overview_strategy_summary')
    layout.addWidget(self.overview_deployments)
    layout.addWidget(label('v2.pending_issues'))
    self.issue_details = QListWidget()
    self.issue_details.setObjectName('pending_issue_details')
    self.issue_details.setAccessibleName(ui_text('v2.pending_issues'))
    self.issue_details.setMinimumHeight(90)
    self.issue_details.setWordWrap(True)
    layout.addWidget(self.issue_details)
    self.events = QListWidget()
    self.events.setObjectName('recent_events')
    self.events.setAccessibleName(ui_text('v2.recent_events'))
    self.events.setMinimumHeight(160)
    layout.addWidget(label('v2.recent_events'))
    layout.addWidget(self.events)
    layout.addStretch()


def _strategy_page(self) -> None:
    layout = _page(self, 'strategy')
    _buttons(
        self,
        layout,
        (
            ('v2.new_strategy', 'new_strategy_button', self.new_strategy),
            ('v2.new_version', 'version_button', self.new_version),
            ('v2.validate', 'validate_button', lambda: self._strategy_action(UiAction.VALIDATE)),
            ('v2.research', 'research_button', lambda: self._strategy_action(UiAction.RESEARCH)),
            ('v2.deploy', 'deploy_button', self.deploy_selected),
            ('v2.legacy_research', 'legacy_research_button', lambda: self.legacy_requested.emit('strategy')),
            ('unified.page.assistant', 'ai_assistant_button', lambda: self.legacy_requested.emit('assistant')),
        ),
    )
    layout.addWidget(label('v2.version_hint'))
    self.strategies = table(('v2.name', 'v2.version', 'v2.market', 'v2.instrument', 'v2.policy', 'v2.state', 'v2.account', 'v2.evidence'), 'strategies')
    layout.addWidget(self.strategies)
    layout.addStretch()


def _market_page(self) -> None:
    layout = _page(self, 'market')
    layout.addWidget(label('v2.market_data_hint'))
    self.market_refresh_button = button('v2.refresh_market', 'market_refresh_button')
    self.market_refresh_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    self.market_refresh_button.setToolTip(ui_text('v2.refresh_market_hint'))
    self.market_refresh_button.clicked.connect(self.refresh)
    layout.addWidget(self.market_refresh_button)
    self.markets = table(('v2.instrument', 'v2.market', 'v2.unit', 'v2.price', 'v2.quote_time', 'v2.availability', 'v2.source'), 'markets')
    layout.addWidget(self.markets)
    _buttons(
        self,
        layout,
        (
            ('v2.legacy_import', 'legacy_import_button', lambda: self.legacy_requested.emit('data')),
            ('v2.legacy_market', 'legacy_market_button', lambda: self.legacy_requested.emit('market')),
        ),
    )
    layout.addStretch()


def _trading_page(self) -> None:
    layout = _page(self, 'trading')
    layout.addWidget(label('v2.control_hint'))
    _buttons(
        self,
        layout,
        (
            ('v2.stop_new', 'stop_button', lambda: self.command(UiAction.STOP_NEW)),
            ('v2.cancel_entries', 'cancel_entries_button', lambda: self.command(UiAction.CANCEL_ENTRIES)),
            ('v2.resume', 'resume_button', lambda: self.command(UiAction.RESUME)),
            ('v2.reconcile', 'reconcile_button', lambda: self.command(UiAction.RECONCILE)),
            ('v2.flatten', 'flatten_button', self.flatten_selected),
            ('v2.transfer', 'transfer_button', self.transfer_selected),
        ),
    )
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
    layout.addWidget(self.positions)
    layout.addWidget(label('v2.orders'))
    self.orders = table(('v2.instrument', 'v2.direction', 'v2.quantity', 'v2.filled', 'v2.state', 'v2.order_scope', 'v2.account'), 'orders')
    layout.addWidget(self.orders)
    _reconciliation_panel(self, layout)
    layout.addStretch()


def _reconciliation_panel(self, layout) -> None:
    layout.addWidget(label('v2.reconciliation_title'))
    layout.addWidget(label('v2.reconciliation_hint'))
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
    layout.addWidget(label('v2.performance_hint'))
    layout.addWidget(label('v2.performance_valuation_hint'))
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
    _buttons(
        self,
        layout,
        (
            ('v2.context_add_profile', 'add_context_button', self.add_context),
            ('v2.connect_readonly', 'connect_read_only_button', self.connect_read_only),
        ),
    )
    layout.addWidget(label('v2.context_navigation_hint'))
    layout.addWidget(label('v2.external_hint'))
    self.accounts = table(('v2.account', 'v2.environment', 'v2.market', 'v2.allocation', 'v2.availability'), 'accounts')
    layout.addWidget(self.accounts)
    self.broker_panel = BrokerPanel()
    self.broker_panel.save_requested.connect(lambda settings: self.command(UiAction.SAVE_BROKER_SETTINGS, broker_settings=settings))
    self.broker_panel.check_requested.connect(lambda: self.command(UiAction.CHECK_READINESS))
    layout.addWidget(self.broker_panel)
    self.advanced = QGroupBox(ui_text('v2.advanced'))
    self.advanced.setCheckable(True)
    self.advanced.setChecked(False)
    advanced_layout = QVBoxLayout(self.advanced)
    self.advanced_content = QWidget()
    fields = QFormLayout(self.advanced_content)
    fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
    fields.addRow(label('v2.settings_hint'))
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
