from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QWidget,
    QTableWidget,
    QVBoxLayout,
)
from desktop_app.strings.catalog import ui_text
from desktop_app.components.design import section
from desktop_app.features.strategy.idea_labels import COLUMNS, COLUMN_TEXT, DISCOVERY_TEXT, FAMILIES, FAMILY_TEXT, TIMEFRAME_TEXT
from desktop_app.features.strategy.idea_links import open_url


def _build_idea_workspaces(self):
    self.setObjectName('idea_research_dialog')
    self.setWindowTitle(ui_text('idea.dialog_title'))
    self.resize(980, 700)
    layout = QVBoxLayout(self)
    self.workspaces = QTabWidget()
    self.workspaces.setObjectName('idea_workspaces')
    layout.addWidget(self.workspaces, 1)
    contents = []
    for key in ('redesign.strategy.idea_conditions', 'redesign.strategy.idea_results', 'redesign.strategy.idea_sources'):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(body)
        self.workspaces.addTab(scroll, ui_text(key))
        contents.append(inner)
    conditions, results, source_layout = contents
    return (layout, conditions, results, source_layout)


def _build_idea_filters(self, conditions):
    form = QFormLayout()
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    conditions.addLayout(form)
    self.market = QComboBox()
    self.market.addItem(ui_text('idea.market_tmf'), 'TMF')
    form.addRow(ui_text('idea.market'), self.market)
    scope = QLabel(ui_text('idea.market_scope_note'))
    scope.setWordWrap(True)
    form.addRow(scope)
    self.timeframe = QComboBox()
    for value in ('1d', '1h', '5m'):
        self.timeframe.addItem(ui_text(TIMEFRAME_TEXT[value]), value)
    form.addRow(ui_text('idea.timeframe'), self.timeframe)
    self.family = QComboBox()
    self.family.addItem(ui_text('idea.direction_any'), None)
    for family in FAMILIES:
        self.family.addItem(ui_text(FAMILY_TEXT[family]), family)
    form.addRow(ui_text('idea.direction_family'), self.family)
    self.direction = QLineEdit()
    self.direction.setMaxLength(40)
    self.direction.setObjectName('idea_direction_text')
    form.addRow(ui_text('idea.direction_text'), self.direction)
    return form


def _build_idea_discovery(self, form):
    self.discovery = QButtonGroup(self)
    discovery = QHBoxLayout()
    for index, value in enumerate(('web_search', 'fixed_sources', 'user_urls')):
        button = QRadioButton(ui_text(DISCOVERY_TEXT[value]))
        button.setObjectName('idea_discovery_' + value)
        button.setProperty('discovery', value)
        button.setChecked(index == 0)
        self.discovery.addButton(button, index)
        discovery.addWidget(button)
    form.addRow(ui_text('idea.discovery'), discovery)
    self.urls = QPlainTextEdit()
    self.urls.setPlaceholderText(ui_text('idea.urls_placeholder'))
    self.urls.setObjectName('idea_user_urls')
    self.urls.setMaximumHeight(90)
    form.addRow(self.urls)
    self.discovery.buttonToggled.connect(lambda *_: self.urls.setVisible(self.discovery_mode() == 'user_urls'))
    self.urls.setVisible(False)


def _build_idea_consent(self, conditions):
    self.model_summary = QLabel()
    self.model_summary.setTextFormat(Qt.TextFormat.PlainText)
    self.model_summary.setWordWrap(True)
    conditions.addWidget(self.model_summary)
    self._refresh_model_summary()
    panel = getattr(self.state, 'chatgpt_panel', None)
    if panel is not None and hasattr(panel, 'model'):
        panel.model.currentIndexChanged.connect(self._refresh_model_summary)
    self.consent_network = QCheckBox(ui_text('idea.consent_network'))
    self.consent_network.setObjectName('idea_consent_network')
    self.consent_plan = QCheckBox(ui_text('idea.consent_plan'))
    self.consent_plan.setObjectName('idea_consent_plan')
    conditions.addWidget(self.consent_network)
    conditions.addWidget(self.consent_plan)


def _build_idea_actions(self, layout, conditions, source_layout):
    actions = QHBoxLayout()
    conditions.addLayout(actions)
    self.start_button = self._button(actions, 'idea.start', 'idea_start', self.start)
    self.start_button.setProperty('role', 'primary')
    persistent_actions = QHBoxLayout()
    self.cancel_button = self._button(persistent_actions, 'idea.cancel', 'idea_cancel', self.cancel)
    self.retry_button = self._button(persistent_actions, 'idea.retry_failed', 'idea_retry', self.retry)
    tools = section(source_layout, 'redesign.strategy.idea_tools')
    self.clear_button = self._button(tools, 'idea.clear_temp', 'idea_clear_temp', self.clear_temp)
    self.status = QLabel('')
    self.status.setTextFormat(Qt.TextFormat.PlainText)
    self.status.setObjectName('idea_status')
    self.status.setWordWrap(True)
    layout.addWidget(self.status)
    layout.addLayout(persistent_actions)
    self.fallback = QLabel(ui_text('idea.unavailable'))
    self.fallback.setWordWrap(True)
    fallback = QHBoxLayout()
    self.use_fixed = self._button(fallback, 'idea.use_fixed', 'idea_use_fixed', lambda: self._choose('fixed_sources'))
    self.use_urls = self._button(fallback, 'idea.use_urls', 'idea_use_urls', lambda: self._choose('user_urls'))
    conditions.addWidget(self.fallback)
    conditions.addLayout(fallback)
    self._set_fallback(False)
    tools.addWidget(QLabel(ui_text('idea.search_log')))
    self.search_log = QListWidget()
    self.search_log.setObjectName('idea_search_log')
    self.search_log.setMaximumHeight(110)
    tools.addWidget(self.search_log)


def _build_idea_sources(self, source_layout):
    source_layout.addWidget(QLabel(ui_text('idea.sources')))
    self.sources = QTableWidget(0, len(COLUMNS))
    self.sources.setObjectName('idea_sources')
    self.sources.setHorizontalHeaderLabels([ui_text(COLUMN_TEXT[c]) for c in COLUMNS])
    self.sources.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    self.sources.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.sources.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.sources.itemSelectionChanged.connect(self.show_source)
    self.sources.cellDoubleClicked.connect(lambda row, column: column == COLUMNS.index('url') and open_url(self._row_url(row)))
    self.sources.setMinimumHeight(180)
    source_layout.addWidget(self.sources)
    source_layout.addWidget(QLabel(ui_text('idea.reader')))
    self.reader = QPlainTextEdit()
    self.reader.setObjectName('idea_reader')
    self.reader.setReadOnly(True)
    self.reader.setMinimumHeight(180)
    source_layout.addWidget(self.reader)


def _build_idea_candidates(self, results):
    results.addWidget(QLabel(ui_text('idea.candidates')))
    self.candidates = QListWidget()
    self.candidates.setObjectName('idea_candidates')
    self.candidates.currentRowChanged.connect(self.show_candidate)
    self.candidates.setMaximumHeight(160)
    results.addWidget(self.candidates)
    self.candidate_summary = QLabel(ui_text('redesign.strategy.idea_empty'))
    self.candidate_summary.setTextFormat(Qt.TextFormat.PlainText)
    self.candidate_summary.setWordWrap(True)
    results.addWidget(self.candidate_summary)
    self.candidate_detail = QPlainTextEdit()
    self.candidate_detail.setObjectName('idea_candidate_detail')
    self.candidate_detail.setReadOnly(True)
    details = section(results, 'redesign.strategy.idea_detail')
    self.candidate_detail.setMinimumHeight(180)
    details.addWidget(self.candidate_detail)
    adopt = QHBoxLayout()
    results.addLayout(adopt)
    self.adopt_button = self._button(adopt, 'idea.adopt', 'idea_adopt', self.adopt)
    self.adopt_button.setProperty('role', 'primary')


def configure_idea_dialog(self):
    layout, conditions, results, source_layout = _build_idea_workspaces(self)
    form = _build_idea_filters(self, conditions)
    _build_idea_discovery(self, form)
    _build_idea_consent(self, conditions)
    _build_idea_actions(self, layout, conditions, source_layout)
    _build_idea_sources(self, source_layout)
    _build_idea_candidates(self, results)
    self.refresh_controls()
