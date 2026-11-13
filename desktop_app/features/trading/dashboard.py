"""Read-only overview dashboard and existing stop-operation wiring.

Only renders dashboard_rows output; owns no financial or freshness calculations.
The hosting workspace provides scrolling and the existing command boundary.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QTableWidget, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, UiState
from desktop_app.features.trading import dashboard_rows as display
from desktop_app.features.trading.widgets import button, rows
from desktop_app.features.trading.page_help import HelpText


class DashboardWidget(QWidget):
    def __init__(self, command, parent=None):
        super().__init__(parent)
        self._identify(self, 'overview_dashboard', ui_text('v2.overview'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.red_summary = self._label('dashboard_red_summary', '')
        self.red_summary.setWordWrap(False)
        layout.addWidget(self.red_summary)
        title = self._label('dashboard_issues_title', ui_text('v2.pending_issues'))
        title.setText(ui_text('v2.pending_issues'))
        self.issues_title = title
        layout.addWidget(title)
        self.issue_details = QListWidget()
        self._identify(self.issue_details, 'pending_issue_details', ui_text('v2.pending_issues'))
        self.issue_details.setWordWrap(True)
        self.issue_details.setMinimumHeight(100)
        layout.addWidget(self.issue_details)
        operations = QGridLayout()
        self.operation_buttons = {}
        for index, (action, key, name) in enumerate(
            (
                (UiAction.STOP_NEW, 'v2.stop_new', 'overview_stop'),
                (UiAction.CANCEL_ENTRIES, 'v2.cancel_entries', 'overview_cancel_entries'),
                (UiAction.RECONCILE, 'v2.reconcile', 'overview_reconcile'),
            )
        ):
            control = button(key, name, role='secondary' if action is UiAction.RECONCILE else 'danger')
            control.clicked.connect(lambda checked=False, action=action: command(action))
            operations.addWidget(control, index // 2, index % 2)
            self.operation_buttons[action] = control
        layout.addLayout(operations)
        lights = QHBoxLayout()
        self.lights = {}
        for name, caption in (
            ('broker', ui_text('dashboard.status.broker').format(ui_text('watch.unknown'))),
            ('market', ui_text('dashboard.status.market').format(ui_text('watch.unknown'))),
            ('engine', ui_text('dashboard.status.engine').format(ui_text('watch.unknown'))),
            ('reconciliation', ui_text('dashboard.status.pending')),
        ):
            light = self._label('dashboard_light_' + name, caption)
            lights.addWidget(light)
            self.lights[name] = light
        layout.addLayout(lights)
        self.data_help = HelpText(ui_text('dashboard.data_status'), '', 'overview_status', self)
        self.status = self.data_help.summary
        layout.addWidget(self.data_help)
        self.today = self._label('dashboard_today', ui_text('dashboard.today'))
        layout.addWidget(self.today)
        self.strategy_summary = self._label('overview_strategy_summary', ui_text('v2.strategies'))
        layout.addWidget(self.strategy_summary)
        self.auto_summary = self._label('overview_auto_card', ui_text('m3.overview_card'))
        from desktop_app.features.trading.auto_strategy_rows import SHOW_AI_STRATEGY

        self.auto_summary.setVisible(SHOW_AI_STRATEGY)
        layout.addWidget(self.auto_summary)
        self.strategy_setup = button('m2t.empty_strategy', 'dashboard_new_strategy', role='primary')
        layout.addWidget(self.strategy_setup)
        self.strategies = self._table(
            'dashboard_strategies',
            ui_text('v2.strategies'),
            (
                ui_text('v2.name'),
                ui_text('v2.version'),
                ui_text('v2.state'),
                ui_text('dashboard.today.orders'),
                ui_text('dashboard.today.net_pnl'),
            ),
        )
        layout.addWidget(self.strategies)
        self.positions = self._table(
            'dashboard_positions',
            ui_text('v2.positions'),
            (
                ui_text('watch.instrument'),
                ui_text('v2.strategy_version'),
                ui_text('v2.direction'),
                ui_text('v2.quantity'),
                ui_text('v2.held_days'),
                ui_text('v2.exit_window'),
                ui_text('dashboard.today.unrealized_pnl'),
                ui_text('v2.quote_time'),
            ),
        )
        layout.addWidget(self.positions)
        self.events_toggle = button('v2.recent_events', 'dashboard_events_toggle')
        self.events_toggle.setCheckable(True)
        layout.addWidget(self.events_toggle)
        self.events = QListWidget()
        self._identify(self.events, 'recent_events', ui_text('v2.recent_events'))
        self.events.setMinimumHeight(160)
        self.events.hide()
        self.events_toggle.toggled.connect(self.events.setVisible)
        layout.addWidget(self.events)

    @staticmethod
    def _identify(widget, name, caption):
        widget.setObjectName(name)
        widget.setAccessibleName(caption)

    def _label(self, name, caption):
        widget = QLabel()
        self._identify(widget, name, caption)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setWordWrap(True)
        return widget

    def _table(self, name, caption, headers):
        widget = QTableWidget(0, len(headers))
        self._identify(widget, name, caption)
        widget.setHorizontalHeaderLabels(headers)
        widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        widget.setTabKeyNavigation(False)
        widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        widget.verticalHeader().hide()
        widget.setMinimumHeight(165)
        return widget

    def render_market(self, state: UiState, *, tables_current: bool = True) -> None:
        for light in display.status_lights(state):
            widget = self.lights[light.key]
            widget.setText(light.label)
            widget.setAccessibleName(light.label)
            widget.setProperty('level', light.level)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        text = display.red_summary_text(state)
        self.red_summary.setText(text)
        self.red_summary.setAccessibleName(text)
        self.red_summary.setVisible(bool(text))
        level = 'red' if text or state.issues or state.reconciliation else 'muted'
        for widget in (self.issues_title, self.issue_details):
            widget.setProperty('overviewLevel', level)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.issues_title.setText(
            ui_text('m2t.initial_check') if display.initial_local_reconciliation(state) and level == 'muted' else ui_text('v2.pending_issues')
        )
        short = (
            ui_text('m2t.facts_pending')
            if not state.financial_facts_verified
            else ui_text('m2t.local_data')
            if state.synthetic_data
            else ui_text('m2t.external_data')
        )
        self.data_help.set_content(short, display.data_status_text(state))
        self.today.setText(display.today_summary_text(state))
        if tables_current:
            # Same-context market revisions change quote cells, not row identities.
            for table, values, columns in (
                (self.strategies, display.strategy_rows(state), (4,)),
                (self.positions, display.position_rows(state), (6, 7)),
            ):
                for index, (_, cells) in enumerate(values):
                    for column in columns:
                        item = table.item(index, column)
                        if item.text() != cells[column]:
                            item.setText(cells[column])

    def render(self, state: UiState, *, state_changed: bool) -> None:
        from desktop_app.features.trading.auto_strategy_rows import summary_text

        self.auto_summary.setText(ui_text('forms.readable.named_value').format(ui_text('m3.overview_card'), summary_text(state.auto_strategies)))
        self.render_market(state, tables_current=not state_changed)
        rows(self.positions, display.position_rows(state))
        if not state_changed:
            return
        self.strategy_summary.setText(display.strategy_summary_text(state) if state.strategies else ui_text('m2t.empty_strategy_reason'))
        self.strategy_setup.setVisible(not state.strategies)
        rows(self.strategies, display.strategy_rows(state))
        self.issue_details.clear()
        self.issue_details.addItems(display.pending_issue_rows(state))
        self.events.clear()
        self.events.addItems(tuple(reversed(display.event_rows(state)[:100])))
