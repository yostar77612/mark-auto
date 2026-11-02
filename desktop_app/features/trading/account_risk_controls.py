"""Account-scoped risk drafts; polling never overwrites edited values."""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLineEdit, QSpinBox

from desktop_app.features.trading.automatic_status import error_next, plain_label
from desktop_app.features.trading.widgets import button
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, AccountRiskLimits
from quantlab.trading.domain.validation import DomainError


class AccountRiskControls:
    def __init__(self, window):
        self.window = window
        self.key = None
        self.drafts = {}
        self.rendering = False
        group = QGroupBox(ui_text('u4.risk_settings'))
        layout = QFormLayout(group)
        self.account = QComboBox()
        self.daily, self.order = QLineEdit(), QLineEdit()
        self.positions = QSpinBox()
        self.positions.setRange(1, 1000000)
        for widget, key, caption in (
            (self.account, 'risk_account', ui_text('u4.risk_account')),
            (self.daily, 'daily_limit', ui_text('u4.daily_limit')),
            (self.order, 'order_limit', ui_text('u4.order_limit')),
            (self.positions, 'max_positions', ui_text('u4.max_positions')),
        ):
            widget.setObjectName(key)
            widget.setAccessibleName(caption)
            layout.addRow(caption, widget)
        self.details = plain_label('account_risk_details')
        layout.addRow(self.details)
        self.save = button('u4.save_risk', 'save_account_risk')
        self.save.clicked.connect(self.submit)
        layout.addRow(self.save)
        self.account.currentIndexChanged.connect(lambda: self.render(window.state))
        self.daily.textEdited.connect(self.dirty)
        self.order.textEdited.connect(self.dirty)
        self.positions.valueChanged.connect(self.dirty)
        window.pages.widget(5).widget().layout().insertWidget(2, group)

    def dirty(self):
        if not self.rendering and self.key is not None:
            self.drafts[self.key] = self.daily.text(), self.order.text(), self.positions.value()

    def render(self, state):
        self.rendering = True
        references = tuple(item.account_ref for item in state.account_risks)
        wanted = self.account.currentData()
        with QSignalBlocker(self.account):
            self.account.clear()
            for reference in references:
                self.account.addItem(reference, reference)
            self.account.setCurrentIndex(max(0, self.account.findData(wanted or state.account_ref)))
        reference = self.account.currentData()
        self.key = (state.context_id, state.context_epoch, state.environment, reference)
        view = next((item for item in state.account_risks if item.account_ref == reference), None)
        self.save.setEnabled(view is not None)
        if view is not None:
            limits = view.limits
            values = self.drafts.get(self.key, (str(limits.daily_loss_fraction * 100), str(limits.max_order_notional), limits.max_positions))
            self.daily.setText(values[0])
            self.order.setText(values[1])
            self.positions.setValue(values[2])
            self.details.setText(
                ui_text('u4.account_limits').format(f'{view.daily_loss_limit:,.0f}', view.position_count)
                + '\n'
                + '\n'.join(error_next(code, self.window) for code in view.reasons)
            )
        else:
            self.daily.clear()
            self.order.clear()
            self.details.setText(ui_text('u4.no_risk_account'))
        self.rendering = False

    def submit(self):
        reference = self.account.currentData()
        if reference is None:
            return
        try:
            limits = AccountRiskLimits(reference, Decimal(self.daily.text()) / 100, Decimal(self.order.text()), self.positions.value())
        except (DomainError, InvalidOperation):
            self.window._feedback(ui_text('v2.form_invalid'))
            return
        self.window.command(UiAction.SAVE_ACCOUNT_RISK, account_ref=reference, account_risk=limits)

    def received(self, command, state, receipt):
        if command is not None and command.action is UiAction.SAVE_ACCOUNT_RISK and receipt is not None and receipt.accepted:
            self.drafts.pop((command.context_id, command.context_epoch or 0, state.environment, command.account_ref), None)
