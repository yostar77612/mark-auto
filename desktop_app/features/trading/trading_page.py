"""Trading-page presentation; accepted application state owns the environment."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QHeaderView, QLabel

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, UiState
from quantlab.trading.domain.models import Environment


LIVE_ORDER_ACTIONS = frozenset((UiAction.DEPLOY, UiAction.STEP, UiAction.RESUME, UiAction.CANCEL_ENTRIES, UiAction.FLATTEN))
_ORDER_BUTTONS = ('deploy_button', 'resume_button', 'cancel_entries_button', 'flatten_button', 'overview_cancel_entries')


def install_trading_environment(window, layout):
    window.trading_execution_page = layout.parentWidget()
    window.trading_execution_page.setObjectName('trading_execution_page')
    header = window.page_headers['trading']
    caption = QLabel(ui_text('v2.environment'))
    header.addWidget(caption)
    window.trading_environment = QComboBox()
    window.trading_environment.setObjectName('trading_environment')
    window.trading_environment.setAccessibleName(ui_text('v2.environment'))
    window.trading_environment.setToolTip(ui_text('m2t.environment_hint'))
    caption.setBuddy(window.trading_environment)
    for environment, text in (
        (Environment.LOCAL, ui_text('v2.local')),
        (Environment.BROKER_SIMULATION, ui_text('v2.broker_sim')),
        (Environment.LIVE, ui_text('v2.live')),
    ):
        window.trading_environment.addItem(text, environment)
    header.addWidget(window.trading_environment)
    window.trading_environment_notice = QLabel()
    window.trading_environment_notice.setObjectName('trading_environment_notice')
    window.trading_environment_notice.setTextFormat(Qt.TextFormat.PlainText)
    window.trading_environment_notice.setWordWrap(True)
    window.trading_environment_notice.setAccessibleName(ui_text('v2.environment'))
    layout.insertWidget(1, window.trading_environment_notice)
    window.trading_environment.currentIndexChanged.connect(
        lambda index: window.environment.setCurrentIndex(window.environment.findData(window.trading_environment.itemData(index)))
    )


def refresh_trading_environment(window, state: UiState):
    for selector in (window.environment, window.trading_environment):
        with QSignalBlocker(selector):
            selector.setCurrentIndex(selector.findData(state.environment))
    banners = {Environment.LOCAL: ui_text('m2t.local'), Environment.BROKER_SIMULATION: ui_text('m2t.simulation'), Environment.LIVE: ui_text('m2t.live')}
    window.trading_environment_notice.setText(banners[state.environment])
    for widget in (window.stop_button, window.overview_stop):
        widget.setText(ui_text('m2t.live_stop') if state.environment is Environment.LIVE else ui_text('v2.stop_new'))
        widget.setAccessibleName(widget.text())
        widget.setToolTip(ui_text('m2t.live_stop_hint') if state.environment is Environment.LIVE else ui_text('m2t.stop_hint'))
    for widget in (window.trading_execution_page, window.trading_environment_notice):
        if widget.property('executionEnvironment') != state.environment.value:
            widget.setProperty('executionEnvironment', state.environment.value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
    for name in _ORDER_BUTTONS:
        widget = getattr(window, name)
        widget.setEnabled(state.environment is not Environment.LIVE)
        widget.setToolTip(ui_text('m2t.orders_disabled') if state.environment is Environment.LIVE else widget.property('environmentTooltip'))


def configure_trading_actions(window):
    for name in ('stop_button', 'cancel_entries_button', 'flatten_button'):
        getattr(window, name).setProperty('role', 'danger')
    window.reconcile_button.setProperty('role', 'primary')
    for name, text in (
        ('stop_button', ui_text('m2t.stop_hint')),
        ('cancel_entries_button', ui_text('m2t.cancel_hint')),
        ('resume_button', ui_text('m2t.resume_hint')),
        ('reconcile_button', ui_text('m2t.reconcile_hint')),
        ('flatten_button', ui_text('m2t.flatten_hint')),
        ('transfer_button', ui_text('m2t.transfer_hint')),
        ('overview_cancel_entries', ui_text('m2t.cancel_hint')),
        ('overview_reconcile', ui_text('m2t.reconcile_hint')),
    ):
        widget = getattr(window, name)
        widget.setToolTip(text)
    for name in _ORDER_BUTTONS:
        widget = getattr(window, name)
        widget.setProperty('environmentTooltip', widget.toolTip())


def configure_trading_positions(widget):
    for column, text in (
        (1, ui_text('m2t.quantity')),
        (2, ui_text('m2t.sellable_units')),
        (3, ui_text('m2t.policy')),
        (5, ui_text('m2t.strategy')),
        (6, ui_text('m2t.entry')),
        (7, ui_text('m2t.held')),
        (8, ui_text('m2t.exit')),
        (9, ui_text('m2t.protection')),
        (10, ui_text('m2t.source')),
        (11, ui_text('m2t.quote')),
    ):
        header = widget.horizontalHeaderItem(column)
        header.setToolTip(header.text())
        header.setText(text)
    for column in range(widget.columnCount()):
        header = widget.horizontalHeaderItem(column)
        if not header.toolTip():
            header.setToolTip(header.text())
    header = widget.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(36)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setWordWrap(True)


def refresh_position_details(widget):
    for row in range(widget.rowCount()):
        for column in range(widget.columnCount()):
            item = widget.item(row, column)
            item.setToolTip(item.text())
            if column in (1, 2, 7):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    widget.resizeRowsToContents()


def confirm_trading_action(window, action):
    if action not in (UiAction.STOP_NEW, UiAction.CANCEL_ENTRIES):
        window.command(action)
        return
    state = window.state
    scope = (state.context_epoch, state.version, state.context_id, state.account_ref, state.environment)
    caption = window.stop_button.text() if action is UiAction.STOP_NEW else window.cancel_entries_button.text()
    detail = window.stop_button.toolTip() if action is UiAction.STOP_NEW else window.cancel_entries_button.toolTip()
    if not window._confirm(ui_text('m2t.confirm_operation').format(window._environment_label(state.environment), state.account_ref, caption, detail)):
        return
    current = window.state
    if scope != (current.context_epoch, current.version, current.context_id, current.account_ref, current.environment):
        window._feedback(ui_text('v2.state_conflict'))
        return
    window.command(action)


def position_quantity(value, unit):
    if value is None:
        return ui_text('watch.unknown')
    quantity = Decimal(value) / (1000 if unit.value == 'SHARE' else 1)
    text = f'{quantity:,.3f}'.rstrip('0').rstrip('.')
    return text + ' ' + (ui_text('m2t.lots') if unit.value == 'SHARE' else ui_text('v2.contracts'))


def position_time(value):
    if not value:
        return ui_text('watch.unknown')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return ui_text('watch.unknown')
    return parsed.astimezone(ZoneInfo('Asia/Taipei')).strftime('%m/%d %H:%M') if parsed.tzinfo is not None else ui_text('watch.unknown')
