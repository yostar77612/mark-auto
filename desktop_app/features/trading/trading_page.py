"""Trading-page presentation; accepted application state owns the environment."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QLabel

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, UiState
from quantlab.trading.domain.models import Environment


LIVE_ORDER_ACTIONS = frozenset((UiAction.DEPLOY, UiAction.STEP, UiAction.RESUME, UiAction.CANCEL_ENTRIES, UiAction.FLATTEN))
_ORDER_BUTTONS = ('deploy_button', 'resume_button', 'cancel_entries_button', 'flatten_button', 'overview_cancel_entries')


def install_trading_environment(window, layout):
    window.trading_execution_page = layout.parentWidget()
    window.trading_execution_page.setObjectName('trading_execution_page')
    title = layout.takeAt(0).widget()
    header = QHBoxLayout()
    header.addWidget(title, 1)
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
    layout.insertLayout(0, header)
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
        (2, ui_text('m2t.sellable')),
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
    widget.resizeRowsToContents()
