"""Compact alert records and typed rule dialogs; no SDK/storage imports."""

from datetime import timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.alert_contracts import AlertActions
from quantlab.trading.domain.alerts import DEFAULT_PARAMS, SCANNER_KINDS, AlertKind, AlertRule
from quantlab.trading.domain.validation import DomainError


KIND_LABELS = {
    AlertKind.PRICE_CROSS: ui_text('alert.kind_price_cross'),
    AlertKind.CHANGE_PERCENT: ui_text('alert.kind_change_percent'),
    AlertKind.FAST_MOVE: ui_text('alert.kind_fast_move'),
    AlertKind.DAY_HIGH_LOW: ui_text('alert.kind_day_high_low'),
    AlertKind.PREV_DAY_BREAK: ui_text('alert.kind_prev_day_break'),
    AlertKind.VOLUME_SURGE: ui_text('alert.kind_volume_surge'),
    AlertKind.MA_CROSS: ui_text('alert.kind_ma_cross'),
    AlertKind.KD_CROSS: ui_text('alert.kind_kd_cross'),
    AlertKind.LIMIT_UP: ui_text('alert.kind_limit_up'),
    AlertKind.LIMIT_DOWN: ui_text('alert.kind_limit_down'),
    AlertKind.PRICE_JUMP: ui_text('alert.kind_price_jump'),
    AlertKind.VOLUME_BURST: ui_text('alert.kind_volume_burst'),
}
PARAM_LABELS = {
    'price': ui_text('alert.param_price'),
    'percent': ui_text('alert.param_percent'),
    'minutes': ui_text('alert.param_minutes'),
    'direction': ui_text('alert.param_direction'),
    'period': ui_text('alert.param_period'),
    'count': ui_text('alert.param_count'),
    'multiple': ui_text('alert.param_multiple'),
    'short': ui_text('alert.param_short'),
    'long': ui_text('alert.param_long'),
    'n': ui_text('alert.param_n'),
    'k_smoothing': ui_text('alert.param_k_smoothing'),
    'd_smoothing': ui_text('alert.param_d_smoothing'),
    'low': ui_text('alert.param_low'),
    'high': ui_text('alert.param_high'),
    'subtype': ui_text('alert.param_subtype'),
}
EVENT_LABELS = {
    AlertKind.PRICE_CROSS: ui_text('alert.event.price_cross'),
    AlertKind.CHANGE_PERCENT: ui_text('alert.event.change_percent'),
    AlertKind.FAST_MOVE: ui_text('alert.event.fast_move'),
    AlertKind.DAY_HIGH_LOW: ui_text('alert.event.day_high_low'),
    AlertKind.PREV_DAY_BREAK: ui_text('alert.event.prev_day_break'),
    AlertKind.VOLUME_SURGE: ui_text('alert.event.volume_surge'),
    AlertKind.MA_CROSS: ui_text('alert.event.ma_cross'),
    AlertKind.KD_CROSS: ui_text('alert.event.kd_cross'),
    AlertKind.LIMIT_UP: ui_text('alert.event.limit_up'),
    AlertKind.LIMIT_DOWN: ui_text('alert.event.limit_down'),
    AlertKind.PRICE_JUMP: ui_text('alert.event.price_jump'),
    AlertKind.VOLUME_BURST: ui_text('alert.event.volume_burst'),
}
WARNING_LABELS = {
    'alert.rules_corrupt': ui_text('alert.rules_corrupt'),
    'alert.scanner_gap': ui_text('alert.scanner_gap'),
}


class AlertRuleDialog(QDialog):
    def __init__(self, instrument_id: str, parent=None):
        super().__init__(parent)
        self.instrument_id, self.rule = instrument_id, None
        self.setWindowTitle(ui_text('alert.add'))
        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)
        self.kind = QComboBox()
        self.kind.setObjectName('alert_kind')
        self.kind.setAccessibleName(ui_text('alert.kind'))
        for kind, label in KIND_LABELS.items():
            self.kind.addItem(label, kind)
        form.addRow(ui_text('alert.kind'), self.kind)
        self.scope = QComboBox()
        self.scope.setObjectName('alert_scope')
        self.scope.setAccessibleName(ui_text('alert.scope'))
        form.addRow(ui_text('alert.scope'), self.scope)
        self.fields_widget = QWidget()
        self.fields = QFormLayout(self.fields_widget)
        form.addRow(self.fields_widget)
        self.cooldown = QSpinBox()
        self.cooldown.setObjectName('alert_cooldown')
        self.cooldown.setRange(10, 3600)
        self.cooldown.setValue(60)
        self.cooldown.setAccessibleName(ui_text('alert.cooldown'))
        form.addRow(ui_text('alert.cooldown'), self.cooldown)
        self.error = QLabel()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox()
        create = buttons.addButton(ui_text('alert.create'), QDialogButtonBox.ButtonRole.AcceptRole)
        create.setAccessibleName(ui_text('alert.create'))
        cancel = buttons.addButton(ui_text('alert.cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setAccessibleName(ui_text('alert.cancel'))
        buttons.accepted.connect(self.create_rule)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self.change_kind)
        self.change_kind()

    def change_kind(self):
        while self.fields.rowCount():
            self.fields.removeRow(0)
        self.editors = {}
        self.field_errors = {}
        kind = self.kind.currentData()
        self.scope.clear()
        self.scope.addItem(ui_text('alert.scope_instrument'), 'INSTRUMENT')
        self.scope.addItem(ui_text('alert.scope_watchlist'), 'WATCHLIST')
        if kind in SCANNER_KINDS:
            self.scope.addItem(ui_text('alert.scope_market'), 'MARKET')
        choices = {
            'direction': (('UP', ui_text('alert.direction_up')), ('DOWN', ui_text('alert.direction_down')), ('ANY', ui_text('alert.direction_any'))),
            'subtype': (('NEAR', ui_text('alert.subtype_near')), ('TOUCH', ui_text('alert.subtype_touch')), ('OPEN', ui_text('alert.subtype_open'))),
        }
        for key, value in DEFAULT_PARAMS[kind].items():
            if key == 'period':
                editor = QComboBox()
                for period, label in (
                    ('1m', ui_text('alert.period_1m')),
                    ('5m', ui_text('alert.period_5m')),
                    ('15m', ui_text('alert.period_15m')),
                    ('1d', ui_text('alert.period_1d')),
                ):
                    if period != '1d' or kind != AlertKind.VOLUME_SURGE:
                        editor.addItem(label, period)
                editor.setCurrentIndex(editor.findData(value))
            elif key in choices:
                editor = QComboBox()
                for code, label in choices[key]:
                    editor.addItem(label, code)
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor = QLineEdit(str(value))
            editor.setObjectName('alert_param_' + key)
            editor.setAccessibleName(PARAM_LABELS[key])
            field = QWidget()
            row = QHBoxLayout(field)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(editor)
            error = QLabel()
            error.setObjectName('alert_error_' + key)
            error.setWordWrap(True)
            row.addWidget(error)
            self.field_errors[key] = error
            self.fields.addRow(PARAM_LABELS[key], field)
            self.editors[key] = editor
        self.error.clear()

    def create_rule(self):
        for error in self.field_errors.values():
            error.clear()
        values = {key: editor.currentData() if isinstance(editor, QComboBox) else editor.text() for key, editor in self.editors.items()}
        try:
            self.rule = AlertRule(
                str(uuid4()), AlertKind(self.kind.currentData()), self.scope.currentData(), self.instrument_id, values, cooldown_seconds=self.cooldown.value()
            )
        except DomainError as exc:
            self.error.setText(ui_text('alert.invalid'))
            for name in exc.detail.split('/'):
                if name in self.field_errors:
                    self.field_errors[name].setText(ui_text('alert.invalid'))
                    self.editors[name].setFocus()
            return
        self.accept()


class AlertPanel(QWidget):
    latest_changed = Signal(str)

    def __init__(self, service: AlertActions, current_instrument, select_instrument, parent=None, *, instrument_name=None, notify=None, rise_fall_colors=None):
        super().__init__(parent)
        self.service, self.current_instrument, self.select_instrument = service, current_instrument, select_instrument
        self.instrument_name = instrument_name or (lambda key: key)
        self.notify = notify
        self.rise_fall_colors = rise_fall_colors or (lambda: ('#ff6575', '#35cf9b'))
        self.setObjectName('terminal_alert_panel')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        for label, name, callback in (
            (ui_text('alert.add'), 'alert_add', self.add_rule),
            (ui_text('alert.manage'), 'alert_manage', self.manage_rules),
            (ui_text('alert.clear'), 'alert_clear', self.clear_events),
        ):
            button = QPushButton(label)
            button.setObjectName(name)
            button.setAccessibleName(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.warning = QLabel(WARNING_LABELS[service.warning] if service.warning else '')
        self.warning.setWordWrap(True)
        self.warning.setVisible(bool(service.warning))
        layout.addWidget(self.warning)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('alert_events')
        self.table.setAccessibleName(ui_text('alert.alert'))
        self.table.setHorizontalHeaderLabels(
            [ui_text('alert.time'), ui_text('alert.code'), ui_text('alert.name'), ui_text('alert.alert'), ui_text('alert.content')]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemClicked.connect(self.select_event)
        self.table.itemActivated.connect(self.select_event)
        layout.addWidget(self.table)
        self._latest = self.service.events[-1].event_id if self.service.events else None
        self.refresh()

    def add_rule(self):
        dialog = AlertRuleDialog(self.current_instrument(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._mutate(lambda: self.service.add_rule(dialog.rule))

    def _mutate(self, action):
        try:
            action()
        except DomainError:
            self.warning.setText(ui_text('alert.unavailable'))
            self.warning.show()
        self.refresh()

    def manage_rules(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(ui_text('alert.manage'))
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(self.service.rules), 5)
        table.setObjectName('alert_rules')
        table.setAccessibleName(ui_text('alert.manage'))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setHorizontalHeaderLabels(
            [ui_text('alert.kind'), ui_text('alert.scope'), ui_text('alert.params'), ui_text('alert.enabled'), ui_text('alert.delete')]
        )
        for row, rule in enumerate(self.service.rules):
            for col, value in enumerate(
                (
                    KIND_LABELS[rule.kind],
                    rule.instrument_id
                    if rule.scope == 'INSTRUMENT'
                    else ui_text('alert.scope_watchlist')
                    if rule.scope == 'WATCHLIST'
                    else ui_text('alert.scope_market'),
                    ', '.join(PARAM_LABELS[key] + '=' + str(value) for key, value in rule.params.items()),
                )
            ):
                table.setItem(row, col, QTableWidgetItem(value))
            enabled = QCheckBox(ui_text('alert.enabled'))
            enabled.setAccessibleName(ui_text('alert.enabled'))
            enabled.setChecked(rule.enabled)
            enabled.toggled.connect(lambda checked, key=rule.rule_id: self._mutate(lambda: self.service.set_enabled(key, checked)))
            table.setCellWidget(row, 3, enabled)
            delete = QPushButton(ui_text('alert.delete'))
            delete.setAccessibleName(ui_text('alert.delete'))
            delete.clicked.connect(
                lambda checked=False, key=rule.rule_id, button=delete: (self._mutate(lambda: self.service.delete_rule(key)), button.setEnabled(False))
            )
            table.setCellWidget(row, 4, delete)
        table.resizeColumnsToContents()
        layout.addWidget(table)
        dialog.resize(800, 350)
        dialog.exec()

    def clear_events(self):
        self.service.clear_events()
        self.refresh()

    def refresh(self):
        if self.service.warning:
            self.warning.setText(WARNING_LABELS[self.service.warning])
            self.warning.show()
        events = tuple(reversed(self.service.events))
        self.table.setRowCount(len(events))
        rise, fall = self.rise_fall_colors()
        for row, event in enumerate(events):
            detail = EVENT_LABELS[event.kind].format(*event.message_args)
            values = (
                event.occurred_at.astimezone(ZoneInfo('Asia/Taipei')).strftime('%H:%M:%S'),
                event.instrument_id.split(':')[-1],
                self.instrument_name(event.instrument_id),
                KIND_LABELS[event.kind],
                detail,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, event)
                direction = event.message_args[1] if len(event.message_args) > 1 else 'ANY'
                if direction in ('UP', 'DOWN'):
                    item.setForeground(QColor(rise if direction == 'UP' else fall))
                self.table.setItem(row, col, item)
        if events and events[0].event_id != self._latest:
            event = events[0]
            text = EVENT_LABELS[event.kind].format(*event.message_args)
            self._latest = event.event_id
            self.latest_changed.emit(text)
            if self.notify is not None:
                self.notify(text)

    def select_event(self, item):
        event = item.data(Qt.ItemDataRole.UserRole)
        self.select_instrument(event.instrument_id, event.occurred_at.astimezone(timezone.utc))
