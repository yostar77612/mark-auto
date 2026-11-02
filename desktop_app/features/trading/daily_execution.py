"""Read-only saved daily signals from the merged next-session View contract."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLabel, QTableWidget, QVBoxLayout, QWidget

from desktop_app.features.trading.trading_page import position_time
from desktop_app.features.trading.trading_page_widgets import EmptyTableState
from desktop_app.features.trading.widgets import rows
from desktop_app.strings.catalog import ui_text


def phase_text(phase):
    keys = {
        'READY': ui_text('u4.daily_ready'),
        'CLAIMED': ui_text('u4.daily_claimed'),
        'UNKNOWN': ui_text('u4.daily_unknown'),
        'DISPATCHED': ui_text('u4.daily_dispatched'),
        'KNOWN_NO_ORDER': ui_text('u4.daily_no_order'),
        'EXPIRED': ui_text('u4.daily_expired'),
        'INVALIDATED': ui_text('u4.daily_invalid'),
    }
    return keys.get(phase, ui_text('watch.unknown'))


class DailyExecution(QWidget):
    def __init__(self, window, name):
        super().__init__(window)
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel()
        self.summary.setObjectName(name + '_next_session')
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setToolTip(ui_text('u4.daily_pending'))
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName(name + '_daily_intents')
        self.table.setAccessibleName(ui_text('u4.daily_title'))
        self.table.setHorizontalHeaderLabels(
            (
                ui_text('v2.name'),
                ui_text('v2.instrument'),
                ui_text('u4.daily_action'),
                ui_text('u4.daily_target_day'),
                ui_text('u4.daily_window'),
                ui_text('v2.state'),
            )
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(165)
        layout.addWidget(self.table)
        self.empty = EmptyTableState(self.table, ui_text('u4.daily_empty'), lambda: window.navigation.setCurrentRow(1))

    def render(self, state):
        automatic = state.automatic
        next_time = position_time(automatic.next_session_at.isoformat()) if automatic.next_session_at is not None else ui_text('watch.unknown')
        self.summary.setText(ui_text('u4.daily_next').format(next_time))
        values, details = [], []
        for intent in automatic.daily_intents:
            strategy = next((row for row in state.strategies if (row.strategy_id, row.version) == (intent.strategy_id, intent.version)), None)
            action = {'ENTRY': ui_text('u4.daily_entry'), 'EXIT': ui_text('u4.daily_exit')}.get(intent.action, ui_text('watch.unknown'))
            identity = f'{intent.strategy_id}:{intent.version}:{intent.action}:{intent.lot_id}:{intent.bar_end.isoformat()}'
            values.append(
                (
                    identity,
                    (
                        f'{strategy.name} v{intent.version}' if strategy is not None else ui_text('watch.unknown'),
                        intent.instrument_id,
                        action,
                        intent.target_trade_date.replace('-', '/'),
                        position_time(intent.not_before.isoformat()) + ' ~ ' + position_time(intent.deadline.isoformat()),
                        phase_text(intent.phase),
                    ),
                )
            )
            error = ' '.join(self.window.strategy_error_texts.get(intent.code, (ui_text('watch.unknown'),))) if intent.code else ''
            details.append(
                ui_text('u4.daily_details').format(
                    position_time(intent.bar_end.isoformat()), position_time(intent.evaluated_at.isoformat()), intent.order_id or ui_text('u4.no_order'), error
                )
            )
        rows(self.table, tuple(values))
        for row, detail in enumerate(details):
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                item.setToolTip(item.text() + '\n' + detail)
        self.empty.setVisible(not automatic.daily_intents)
