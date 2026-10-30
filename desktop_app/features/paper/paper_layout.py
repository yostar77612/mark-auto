"""Paper workspace composition; the page retains all existing action handlers."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QSpinBox

from desktop_app.features.paper.forms import PaperIntentForm, PaperQuoteForm, PaperSnapshotForm
from desktop_app.features.paper.policy_form import PaperPolicyForm
from desktop_app.components.result_tables import SummaryCard
from desktop_app.components.formatting import display_number
from desktop_app.strings.catalog import ui_text
from desktop_app.components.timeinput import DateInput
from quantlab import strict_json
from quantlab.core import canonical_json
from desktop_app.components.design import card, section
from desktop_app.features.paper.paper_tabs import build_tabs
from desktop_app.features.paper.replay_controls import ReplayControls
from desktop_app.components.result_widgets import KpiCards
from desktop_app.components.widgets import PanelCard


def wrapped(layout, key, name=''):
    label = QLabel(ui_text(key))
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(label)
    return label


def build_paper(page, layout):
    conditions = card(layout, 'redesign.paper.conditions')
    conditions.setSpacing(8)
    page.readiness_selection = wrapped(conditions, 'redesign.paper.no_selection', 'paper_readiness_strategy')
    page.readiness_account = wrapped(conditions, 'redesign.paper.account_pending', 'paper_readiness_account')
    page.readiness_policy = wrapped(conditions, 'redesign.paper.policy_pending', 'paper_readiness_policy')
    conditions.removeWidget(page.readiness_account)
    conditions.removeWidget(page.readiness_policy)
    checks = QGridLayout()
    checks.addWidget(page.readiness_account, 0, 0)
    checks.addWidget(page.readiness_policy, 0, 1)
    checks.setColumnStretch(0, 1)
    checks.setColumnStretch(1, 2)
    conditions.addLayout(checks)
    page.readiness_next = wrapped(conditions, 'redesign.paper.next_empty', 'paper_readiness_next')
    page.readiness_next.setProperty('designNotice', True)
    action_grid = QGridLayout()
    conditions.addLayout(action_grid)
    action_cells = []
    for index in range(4):
        cell = QHBoxLayout()
        action_grid.addLayout(cell, index // 2, index % 2)
        action_cells.append(cell)
    for column in range(2):
        action_grid.setColumnStretch(column, 1)
    page._button(action_cells[0], ui_text('redesign.paper.open_preparation'), 'paper_prepare', lambda: open_preparation(page))
    page._button(action_cells[1], ui_text('ui.paper_page.load_account'), 'paper_snapshot', lambda: page.paper_job('snapshot'))
    page._button(
        action_cells[2],
        ui_text('ui.paper_page.reconcile'),
        'paper_reconcile',
        lambda: page.paper_job('reconcile', snapshot=page._payload(page.snapshot, page.snapshot_form.build_payload)),
    )
    page._button(
        action_cells[3],
        ui_text('paper.manual_unlock'),
        'paper_manual_unlock',
        lambda: page.paper_job('reconcile', snapshot=page._payload(page.snapshot, page.snapshot_form.build_payload), manual_order_lock=False),
    )

    session = card(layout, 'redesign.paper.session')
    session.setSpacing(8)
    replay_row = QHBoxLayout()
    session.addLayout(replay_row)
    bars_label = QLabel(ui_text('redesign.paper.bars'))
    replay_row.addWidget(bars_label)
    page.replay_bars = QSpinBox()
    page.replay_bars.setRange(1, 1000)
    page.replay_bars.setValue(100)
    page.replay_bars.setAccessibleName(ui_text('redesign.paper.bars'))
    bars_label.setBuddy(page.replay_bars)
    replay_row.addWidget(page.replay_bars)
    replay_session = QHBoxLayout()
    session.addLayout(replay_session)
    page.replay_controls = ReplayControls(page, replay_row, session_layout=replay_session)
    page.page_state.replay_controls = page.replay_controls
    page.paper_confirm = QCheckBox(ui_text('ui.paper_page.snapshot_consent'))
    page.paper_confirm.setAccessibleName(page.paper_confirm.text())
    session.addWidget(page.paper_confirm)
    actions = QHBoxLayout()
    session.addLayout(actions)
    page._button(
        actions,
        ui_text('ui.paper_page.replay_history'),
        'paper_replay',
        lambda: page.paper_job('replay', max_bars=page.replay_bars.value(), _paced=page.replay_controls.speed.currentData() is not None),
        role='primary',
    )
    page.kill_button = page._button(actions, ui_text('ui.paper_page.emergency_stop'), 'paper_kill', page.kill_paper, role='danger')
    page.kpis = KpiCards(('cash', 'positions', 'orders', 'fills', 'reconciliation_required', 'stop'))
    page.kpis.labels['stop'].setProperty('kpiValue', False)
    session.addWidget(page.kpis)
    page.account_tabs = build_tabs(page, session)
    page.account_tabs.setMinimumHeight(210)

    preparation = section(layout, 'redesign.paper.preparation', key='paper_preparation', state=page.state)
    wrapped(preparation, 'redesign.paper.scope')
    wrapped(preparation, 'ui.paper_page.reconciliation_hint')
    limits = page.host.callbacks['paper_risk_limits']()
    page.paper_risk_summary = wrapped(preparation, 'ui.paper_page.fixed_risk_limits', 'paper_fixed_risk_summary')
    page.paper_risk_summary.setText(
        ui_text('ui.paper_page.fixed_risk_limits').format(
            limits.max_position,
            limits.max_order_quantity,
            display_number(limits.max_daily_loss, 'cash'),
            limits.max_quote_age_seconds,
            limits.max_consecutive_losses,
            limits.window_seconds,
            limits.max_orders_per_window,
        )
    )
    policy_layout = page._advanced(preparation, ui_text('ui.paper_page.policy_advanced'))
    policy_panel = PanelCard(ui_text('ui.paper_page.policy_advanced'))
    policy_layout.addWidget(policy_panel)
    page.policy_form = PaperPolicyForm()
    policy_panel.content_layout().addWidget(page.policy_form)
    policy_actions = QHBoxLayout()
    preparation.addLayout(policy_actions)
    page._button(policy_actions, ui_text('ui.paper_page.load_policy'), 'load_policy_file', lambda: page.load_form_file(page.policy_form, page.paper_policy))
    page._button(policy_actions, ui_text('ui.paper_page.synthetic_policy'), 'demo_policy', page.demo_paper_policy)
    snapshot_layout = page._advanced(preparation, ui_text('ui.paper_page.snapshot_advanced'))
    snapshot_panel = PanelCard(ui_text('ui.paper_page.snapshot_advanced'))
    snapshot_layout.addWidget(snapshot_panel)
    page.snapshot_form = PaperSnapshotForm()
    snapshot_panel.content_layout().addWidget(page.snapshot_form)
    page._button(preparation, ui_text('ui.paper_page.load_snapshot'), 'load_snapshot_file', lambda: page.load_form_file(page.snapshot_form, page.snapshot))

    order_layout = page._advanced(layout, ui_text('ui.paper_page.order_advanced'))
    page.intent_form = PaperIntentForm()
    order_layout.addWidget(page.intent_form)
    page.quote_form = PaperQuoteForm()
    order_layout.addWidget(page.quote_form)
    time_label = wrapped(order_layout, 'timeinput.paper_clock')
    page.paper_time = DateInput('2026-01-05T01:00:00Z', timestamp=True)
    page.paper_time.setAccessibleName(ui_text('timeinput.paper_clock'))
    time_label.setBuddy(page.paper_time)
    order_layout.addWidget(page.paper_time)
    page._button(
        order_layout,
        ui_text('ui.paper_page.submit_order'),
        'paper_submit',
        lambda: page.paper_job(
            'submit',
            intent=page._payload(page.intent, page.intent_form.build_payload),
            quote=page._payload(page.quote, page.quote_form.build_payload),
            now=page.paper_time.text(),
        ),
        role='primary',
    )
    page.cancel_order = page._text(order_layout, ui_text('ui.paper_page.order_id'))
    page._button(
        order_layout,
        ui_text('ui.paper_page.cancel_order'),
        'paper_cancel',
        lambda: page.paper_job('cancel', order_id=page.cancel_order.text(), now=page.paper_time.text()),
        role='danger',
    )
    cancel_all = page._button(order_layout, ui_text('paper.cancel_all.button'), 'paper_cancel_all', page.cancel_all_paper, role='danger')
    cancel_all.setProperty('custom_confirmation', True)
    page._button(order_layout, ui_text('paper.manual_lock'), 'paper_manual_lock', lambda: page.paper_job('kill', manual_order_lock=True))

    advanced = page._advanced(layout)
    page.paper_policy = page._text(advanced, ui_text('ui.paper_page.policy_json'), '{}', True)
    page._remember(page.paper_policy)
    page.snapshot = page._text(
        advanced,
        ui_text('ui.paper_page.snapshot_json'),
        canonical_json({'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}),
        True,
    )
    page.snapshot_form.from_payload(strict_json.loads(page.snapshot.toPlainText()))
    page._remember(page.snapshot)
    page.intent = page._text(advanced, ui_text('ui.paper_page.intent_json'), '{}', True)
    page.quote = page._text(advanced, ui_text('ui.paper_page.quote_json'), '{}', True)
    page._remember(page.intent)
    page._remember(page.quote)
    page.paper_detail = QPlainTextEdit()
    page.paper_detail.setReadOnly(True)
    advanced.addWidget(page.paper_detail)
    page.paper_card = SummaryCard()
    advanced.addWidget(page.paper_card)
    layout.addStretch()


def open_preparation(page):
    page.state._section_toggles['paper_preparation'].setChecked(True)
    for index in range(page.state.stack.count()):
        container = page.state.stack.widget(index)
        if isinstance(container, QScrollArea) and container.widget() is page:
            QTimer.singleShot(0, page, lambda area=container: area.ensureWidgetVisible(page.paper_risk_summary))
            return
