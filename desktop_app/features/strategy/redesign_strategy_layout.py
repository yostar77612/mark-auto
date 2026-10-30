"""Task focused presentation using the existing strategy page and controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_app.components.forms import StrategyForm, CampaignForm, ResultTable, CandidateSummaryCard
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.theme import set_theme_property
from quantlab.desktop_errors import error_message
from desktop_app.components.design import card, section
from desktop_app.features.strategy.strategy_tabs import candidate_analysis_layout


def note(layout, key):
    label = QLabel(ui_text(key))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    layout.addWidget(label)
    return label


def go_backtest(page):
    state = page.state
    target = getattr(state, 'backtest_page', None)
    if target is None:
        return
    for index in range(state.stack.count()):
        if state.stack.widget(index).isAncestorOf(target):
            state.navigation.setCurrentRow(index)
            return


def adopt_candidate(page):
    """Navigation belongs to the user action; restoration reuses use_candidate."""
    page.use_candidate()
    go_backtest(page)
    page.host.form_feedback(page.state.backtest_form, ui_text('ui.use_candidate.immutable_candidate_applied'))


class ConnectionLabel(QLabel):
    """The settings controller already updates this label on every state change."""

    def __init__(self, page):
        super().__init__(ui_text('settings.connection_hint'))
        self.page = page
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)

    def setText(self, text):
        super().setText(text)
        if hasattr(self, 'page'):
            refresh_connection(self.page)


def refresh_connection(page):
    controller = getattr(page.state, 'chatgpt_controller', None)
    panel = getattr(page.state, 'chatgpt_panel', None)
    if controller is None or panel is None:
        return
    if not getattr(page, '_connection_bound', False):
        bind_connection(page, controller, panel)
    from desktop_app.features.assistant.connection import CONNECTED_STATES

    connected = bool(controller.active_registration and controller.state in CONNECTED_STATES)
    page.chatgpt_sign_in_entry.setVisible(not connected)
    if not connected and controller.message == ui_text('chatgpt_ui.init.unchecked_connection'):
        QLabel.setText(page.connection_status, ui_text('redesign.strategy.connection_hint'))
    elif controller.message:
        QLabel.setText(page.connection_status, controller.message)
    model = page.research_model
    model.blockSignals(True)
    model.clear()
    for index in range(panel.model.count()):
        model.addItem(panel.model.itemText(index), panel.model.itemData(index))
    model.setCurrentIndex(panel.model.currentIndex())
    model.blockSignals(False)
    model.setEnabled(panel.model.isEnabled())
    for mirror, original in ((page.research_consent, panel.consent), (page.research_usage_consent, panel.included_usage_only)):
        mirror.blockSignals(True)
        mirror.setChecked(original.isChecked())
        mirror.setText(original.text())
        mirror.setToolTip(original.toolTip() or original.text())
        mirror.setEnabled(original.isEnabled())
        mirror.blockSignals(False)
    page.research_usage.setText(panel.usage.text() or ui_text('redesign.strategy.usage_unknown'))


def bind_connection(page, controller, panel):
    if getattr(page, '_connection_bound', False):
        return
    page._connection_bound = True
    controller.changed.connect(lambda: refresh_connection(page))
    page.research_model.currentIndexChanged.connect(lambda _: panel.model.setCurrentIndex(panel.model.findData(page.research_model.currentData())))
    panel.model.currentIndexChanged.connect(lambda _: refresh_connection(page))
    for mirror, original in ((page.research_consent, panel.consent), (page.research_usage_consent, panel.included_usage_only)):
        mirror.toggled.connect(original.setChecked)
        original.toggled.connect(lambda _, source=original, target=mirror: target.setChecked(source.isChecked()))
    refresh_connection(page)


def choose_mode(page, mode):
    page.strategy_mode = mode
    page.idea_workspace.setVisible(mode == 'ideas')
    page.manual_workspace.setVisible(mode == 'manual')
    page.connection_workspace.setVisible(mode in ('ideas', 'research'))
    page.tabs.setCurrentIndex({'ideas': 0, 'manual': 0, 'research': 1, 'walk_forward': 2}[mode])
    page.mode_group.setExclusive(False)
    for key, button in page.mode_buttons.items():
        button.setChecked(mode == key)
        set_theme_property(button, 'role', 'taskChoice')
    page.mode_group.setExclusive(True)
    refresh_connection(page)


def compact_campaign(form):
    """Rearrange the same validated fields; no second configuration source."""
    rows = {}
    for key, widget in form.fields.items():
        result = form.form.takeRow(widget)
        rows[key] = (result.labelItem.widget(), result.fieldItem.widget())
    grid = QGridLayout()
    form.outer.insertLayout(0, grid)
    grid.addWidget(QLabel(ui_text('redesign.strategy.range_start')), 0, 1)
    grid.addWidget(QLabel(ui_text('redesign.strategy.range_end')), 0, 2)
    for row, (split, key) in enumerate(
        (
            ('train', 'forms.init.training'),
            ('validation', 'forms.init.validation'),
            ('oos', 'forms.init.out_of_sample'),
            ('holdout', 'forms.init.final_holdout'),
        ),
        1,
    ):
        grid.addWidget(QLabel(ui_text(key)), row, 0)
        for column, suffix in ((1, '_start'), (2, '_end')):
            caption, widget = rows.pop(split + suffix)
            caption.deleteLater()
            grid.addWidget(widget, row, column)
    common = QGridLayout()
    form.outer.insertLayout(1, common)
    for index, key in enumerate(('max_trials', 'max_improvements', 'minimum', 'min_trades')):
        caption, widget = rows.pop(key)
        row, column = divmod(index, 2)
        common.addWidget(caption, row, column * 2)
        common.addWidget(widget, row, column * 2 + 1)
    more = section(form.outer, 'redesign.strategy.more_conditions')
    extra = QFormLayout()
    more.addLayout(extra)
    for caption, widget in rows.values():
        extra.addRow(caption, widget)
    for box in form.families.values():
        form.outer.removeWidget(box)
        more.addWidget(box)


def build_strategy(page, outer, settings, research, walk_forward):
    subtitle = note(outer, 'redesign.strategy.subtitle')
    outer.removeWidget(subtitle)
    outer.insertWidget(1, subtitle)
    selector = QHBoxLayout()
    outer.insertLayout(2, selector)
    page.mode_buttons = {}
    group = QButtonGroup(page)
    group.setExclusive(True)
    page.mode_group = group
    for mode, key in (('ideas', 'redesign.strategy.ideas'), ('research', 'redesign.strategy.research'), ('manual', 'redesign.strategy.manual')):
        button = QPushButton(ui_text(key))
        button.setCheckable(True)
        button.setObjectName('strategy_mode_' + mode)
        button.setAccessibleName(button.text())
        button.setMinimumHeight(42)
        button.clicked.connect(lambda checked=False, value=mode: choose_mode(page, value))
        group.addButton(button)
        selector.addWidget(button, 1)
        page.mode_buttons[mode] = button
    page.host.button(selector, ui_text('redesign.strategy.walk_forward'), 'strategy_walk_forward_entry', lambda: choose_mode(page, 'walk_forward'))
    page.tabs.tabBar().hide()
    page.connection_workspace = QWidget()
    connection = QHBoxLayout(page.connection_workspace)
    connection.setContentsMargins(0, 0, 0, 0)
    page.connection_status = ConnectionLabel(page)
    connection.addWidget(page.connection_status, 1)
    outer.insertWidget(3, page.connection_workspace)
    page.state.chatgpt_connection_status = page.connection_status
    page.idea_dialog = None
    page.idea_workspace = QWidget()
    idea = QVBoxLayout(page.idea_workspace)
    idea.setContentsMargins(0, 0, 0, 0)
    settings.addWidget(page.idea_workspace)
    content = card(idea, 'redesign.strategy.idea_title')
    note(content, 'redesign.strategy.idea_hint')
    page.idea_research_entry = page.host.button(content, ui_text('redesign.strategy.idea_next'), 'idea_research_entry', page.open_idea_research, role='primary')
    page.manual_workspace = QWidget()
    manual = QVBoxLayout(page.manual_workspace)
    manual.setContentsMargins(0, 0, 0, 0)
    settings.addWidget(page.manual_workspace)
    content = card(manual, 'redesign.strategy.manual_title')
    note(content, 'redesign.strategy.manual_hint')
    page.strategy_form = StrategyForm()
    content.addWidget(page.strategy_form)
    actions = QHBoxLayout()
    content.addLayout(actions)
    page.host.button(actions, ui_text('redesign.strategy.to_backtest'), 'strategy_to_backtest', lambda: go_backtest(page), role='primary')
    page.host.button(actions, ui_text('ui.strategy_page.use_builtin'), 'use_builtin', page.use_builtin)
    advanced = page.host.advanced(manual)
    from quantlab.strategies import builtin_strategies

    page.family = QComboBox()
    page.family.addItems([spec.family for spec in builtin_strategies()])
    advanced.addWidget(page.family)
    page.parameters = page.host.text(advanced, ui_text('ui.strategy_page.strategy_json'), '{}', True)
    page.strategy_detail = QPlainTextEdit()
    page.strategy_detail.setReadOnly(True)
    page.strategy_detail.setMaximumHeight(220)
    advanced.addWidget(page.strategy_detail)
    page.family.currentIndexChanged.connect(page._family_changed)
    page._family_changed()
    page.strategy_form.family.currentIndexChanged.connect(lambda: page.family.setCurrentIndex(page.strategy_form.family.currentIndex()))
    page.host.advanced(walk_forward, ui_text('ui.strategy_page.walk_forward_advanced'))
    list(page.state._section_toggles.values())[-1].hide()
    page._walk_forward_section(walk_forward)
    build_research(page, research)
    choose_mode(page, 'ideas')


def build_research(page, research):
    content = card(research, 'redesign.strategy.research_title')
    note(content, 'redesign.strategy.research_hint')
    form = QFormLayout()
    content.addLayout(form)
    page.research_model = QComboBox()
    page.research_model.setObjectName('strategy_research_model')
    page.research_model.setToolTip(ui_text('redesign.strategy.model_hint'))
    page.research_model.setPlaceholderText(ui_text('redesign.strategy.model_missing'))
    form.addRow(ui_text('redesign.strategy.model'), page.research_model)
    page.research_usage = note(content, 'redesign.strategy.usage_unknown')
    page.research_usage.setObjectName('strategy_research_usage')
    page.research_consent = QCheckBox()
    page.research_consent.setObjectName('strategy_research_consent')
    page.research_usage_consent = QCheckBox()
    page.research_usage_consent.setObjectName('strategy_research_usage_consent')
    content.addWidget(page.research_consent)
    content.addWidget(page.research_usage_consent)
    page.host.button(content, ui_text('ui.strategy_page.generate_reopen'), 'run_campaign', page.run_campaign, role='primary')
    page.campaign_form = CampaignForm()
    compact_campaign(page.campaign_form)
    conditions = QLabel()
    conditions.setTextFormat(Qt.TextFormat.PlainText)
    conditions.setWordWrap(True)
    conditions.setObjectName('strategy_research_conditions')
    content.addWidget(conditions)
    limits = QLabel()
    limits.setTextFormat(Qt.TextFormat.PlainText)
    limits.setWordWrap(True)
    content.addWidget(limits)
    configure = section(content, 'redesign.strategy.research_limits')
    configure.addWidget(page.campaign_form)

    def conditions_changed():
        fields = page.campaign_form.fields
        preview = {
            'splits': {split: [fields[split + suffix].text() or '—' for suffix in ('_start', '_end')] for split in ('train', 'validation', 'oos', 'holdout')},
            'max_trials': fields['max_trials'].text() or '—',
            'max_improvements': fields['max_improvements'].text() or '—',
            'ranking': {key: fields[key].text() or '—' for key in ('minimum', 'min_trades')},
        }
        try:
            payload = page.host.payload(page.campaign_config, lambda: preview) if hasattr(page, 'campaign_config') else preview
            values = [value for split in ('train', 'validation', 'oos', 'holdout') for value in payload['splits'][split]]
            conditions.setText(ui_text('redesign.strategy.conditions_summary').format(*values))
            limits.setText(
                ui_text('redesign.strategy.limits_summary').format(
                    payload['max_trials'], payload['max_improvements'], payload['ranking']['minimum'], payload['ranking']['min_trades']
                )
            )
        except (ValueError, TypeError, KeyError, IndexError):
            conditions.setText(error_message('validation_failed'))
            limits.clear()

    for field in page.campaign_form.fields.values():
        field.textChanged.connect(conditions_changed)
    conditions_changed()
    page.source_summary = note(content, 'redesign.strategy.source_summary')
    tools = page.host.advanced(research, ui_text('ui.strategy_page.research_advanced'))
    page.chatgpt_sign_in_entry = page.host.button(tools, ui_text('ui.strategy_page.chatgpt_sign_in'), 'chatgpt_sign_in_entry', page.host.show_sign_in)
    page.campaign_config = page.host.text(tools, ui_text('ui.strategy_page.research_json'), '', True)
    page.host.remember(page.campaign_config)
    page.campaign_config.textChanged.connect(conditions_changed)
    source = QFormLayout()
    tools.addLayout(source)
    page.provider_mode = QComboBox()
    for key, value in (
        ('ui.strategy_page.chatgpt_source', 'chatgpt_plan'),
        ('ui.strategy_page.fixture_source', 'fixture'),
        ('ui.strategy_page.manual_source', 'manual'),
    ):
        page.provider_mode.addItem(ui_text(key), value)
    source.addRow(ui_text('redesign.strategy.research_source'), page.provider_mode)
    fixture = note(tools, 'ui.strategy_page.fixture_disclaimer')
    manual = QWidget()
    manual_layout = QVBoxLayout(manual)
    tools.addWidget(manual)
    page.manual_path = page.host.text(manual_layout, ui_text('ui.strategy_page.manual_response_path'))
    page.host.button(manual_layout, ui_text('ui.strategy_page.browse_manual_response'), 'browse_manual_response', lambda: page.host.browse(page.manual_path))
    page.manual_response = page.host.text(manual_layout, ui_text('ui.strategy_page.paste_manual_response'), '', True)
    page.host.button(manual_layout, ui_text('ui.strategy_page.export_manual_request'), 'export_manual_request', page.export_manual_request)
    page.host.button(tools, ui_text('ui.strategy_page.reconcile_request_record'), 'chatgpt_campaign_usage', page.host.inspect_plan_usage)

    def source_changed():
        mode = page.provider_mode.currentData()
        manual.setVisible(mode == 'manual')
        fixture.setVisible(mode == 'fixture')
        page.research_model.setVisible(mode == 'chatgpt_plan')
        page.research_consent.setVisible(mode == 'chatgpt_plan')
        page.research_usage_consent.setVisible(mode == 'chatgpt_plan')
        page.research_usage.setVisible(mode == 'chatgpt_plan')
        page.source_summary.setText(ui_text('redesign.strategy.source_summary').format(page.provider_mode.currentText()))

    page.provider_mode.currentIndexChanged.connect(source_changed)
    source_changed()
    candidates = card(research, 'redesign.strategy.candidates')
    page.candidate_choice = QComboBox()
    page.candidate_choice.setObjectName('candidate_choice')
    page.candidate_choice.currentIndexChanged.connect(page.inspect_candidate)
    candidates.addWidget(page.candidate_choice)
    page.candidate_notice = note(candidates, 'redesign.strategy.candidate_empty')
    page.candidate_notice.setObjectName('strategy_candidate_notice')
    page.candidate_card = CandidateSummaryCard()
    candidates.addWidget(page.candidate_card)
    page.candidate_card.hide()
    page.use_candidate_button = page.host.button(
        candidates, ui_text('redesign.strategy.adopt_backtest'), 'use_candidate', lambda: adopt_candidate(page), role='primary'
    )
    page.use_candidate_button.setEnabled(False)
    details = section(candidates, 'redesign.strategy.candidate_details')
    page.candidate_detail = QPlainTextEdit()
    page.candidate_detail.setReadOnly(True)
    page.candidate_detail.setMaximumHeight(260)
    details.addWidget(page.candidate_detail)
    evidence = page.host.advanced(research, ui_text('ui.strategy_page.candidate_history_advanced'))
    page.history = QPlainTextEdit()
    page.history.setReadOnly(True)
    page.history.setMaximumHeight(220)
    evidence.addWidget(page.history)
    page.history_table = ResultTable()
    evidence.addWidget(page.history_table)
    evidence.addWidget(QLabel(ui_text('ui.strategy_page.saved_evaluations')))
    page.evaluation_table = ResultTable()
    evidence.addWidget(page.evaluation_table)
    page.analysis_layout = candidate_analysis_layout(research)
