"""Typed strategy inputs and labelled estimates from the accepted product list."""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QMessageBox, QSpinBox

from desktop_app.features.trading.labels import state_label
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import StrategyParameters, strategy_defaults
from quantlab.trading.domain.models import HoldingKind, Market


class StrategyOptions:
    def __init__(self, wizard, state):
        self.wizard, self.state = wizard, state
        self.stock_confirmed = False
        self.stock_intraday = QCheckBox(ui_text('u3.stock_intraday'))
        self.stock_intraday.setObjectName('strategy_stock_intraday')
        self.stock_intraday.setAccessibleName(ui_text('u3.stock_intraday'))
        self.stock_intraday.setToolTip(ui_text('u3.stock_qualification'))
        self.interval = QComboBox()
        self.stop = QLineEdit()
        self.entry_amount = QLineEdit(str(state.allocated_cash))
        self.contracts = QSpinBox()
        self.contracts.setRange(1, 5)
        self.contracts.setValue(1)
        self.instrument_rule = QComboBox()
        self.instrument_rule.addItem(ui_text('u3.near_month'), 'TMF_NEAR')
        self.instrument_rule.addItem(ui_text('u3.exact_contract'), 'EXACT')
        for widget, name, text in (
            (self.interval, 'strategy_interval', ui_text('u3.interval')),
            (self.stop, 'strategy_stop_fraction', ui_text('u3.stop')),
            (self.entry_amount, 'strategy_entry_amount', ui_text('u3.entry_amount')),
            (self.contracts, 'strategy_contracts', ui_text('u3.contracts')),
            (self.instrument_rule, 'strategy_instrument_rule', ui_text('u3.instrument_rule')),
        ):
            widget.setObjectName(name)
            widget.setAccessibleName(text)
        self.size_hint = QLabel()
        self.size_hint.setObjectName('strategy_size_hint')
        self.size_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.size_hint.setWordWrap(True)
        self.stock_intraday.toggled.connect(self.stock_changed)
        wizard.instrument.currentIndexChanged.connect(self.refresh_size)
        wizard.allocation.textChanged.connect(self.refresh_size)
        self.entry_amount.textChanged.connect(self.refresh_size)
        self.contracts.valueChanged.connect(self.refresh_size)

    def products(self):
        kind = self.wizard.policy.currentData()
        return tuple(
            item
            for item in self.state.strategy_products
            if kind in item.holding_kinds or kind == HoldingKind.INTRADAY and item.stock_intraday_optional and self.stock_intraday.isChecked()
        )

    def policy_changed(self):
        wizard = self.wizard
        defaults = strategy_defaults(wizard.policy.currentData())
        self.stock_confirmed = False
        with QSignalBlocker(self.stock_intraday):
            self.stock_intraday.setChecked(False)
        self.stock_intraday.setVisible(defaults.kind == HoldingKind.INTRADAY)
        wizard.minimum.setValue(defaults.min_days or 0)
        wizard.maximum.setValue(defaults.max_days or 0)
        wizard.minimum.setEnabled(defaults.kind != HoldingKind.INTRADAY)
        wizard.maximum.setEnabled(defaults.kind != HoldingKind.INTRADAY)
        self.interval.clear()
        for interval in defaults.intervals:
            self.interval.addItem({'1m': ui_text('u3.minute'), '5m': ui_text('u3.five_minutes'), '1d': ui_text('u3.daily')}[interval], interval)
        self.interval.setCurrentIndex(self.interval.findData(defaults.bar_interval))
        self.stop.setText('' if defaults.stop_fraction is None else str(defaults.stop_fraction * 100))
        self.refresh_markets()

    def stock_changed(self, checked):
        self.stock_confirmed = False
        if checked:
            box = QMessageBox(
                QMessageBox.Icon.Question,
                ui_text('u3.stock_intraday'),
                ui_text('u3.stock_confirm'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                self.wizard,
            )
            box.button(QMessageBox.StandardButton.Yes).setText(ui_text('v2.confirm'))
            box.button(QMessageBox.StandardButton.Cancel).setText(ui_text('v2.cancel'))
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            box.setTextFormat(Qt.TextFormat.PlainText)
            self.stock_confirmed = box.exec() == QMessageBox.StandardButton.Yes
            if not self.stock_confirmed:
                with QSignalBlocker(self.stock_intraday):
                    self.stock_intraday.setChecked(False)
        self.refresh_markets()

    def refresh_markets(self):
        wizard = self.wizard
        wanted = wizard.market.currentData()
        available = {item.market for item in self.products()}
        with QSignalBlocker(wizard.market):
            wizard.market.clear()
            for market, caption in ((Market.STOCK, ui_text('v2.stock')), (Market.INDEX_FUTURE, ui_text('v2.index_future'))):
                if market in available:
                    wizard.market.addItem(caption, market)
            wizard.market.setCurrentIndex(max(0, wizard.market.findData(wanted)))
        self.candidates()
        wizard._market_availability()

    def candidates(self):
        wizard = self.wizard
        wanted = wizard.instrument.currentData()
        wizard.instrument.clear()
        wizard.account.clear()
        market = wizard.market.currentData()
        for product in self.products():
            if product.market == market:
                wizard.instrument.addItem(product.instrument_id, product.instrument_id)
        wizard.instrument.setCurrentIndex(max(0, wizard.instrument.findData(wanted)))
        for account in self.state.accounts:
            if (
                market is not None
                and account.environment is self.state.environment
                and (account.market == market or market != Market.STOCK and account.market is not Market.STOCK)
            ):
                wizard.account.addItem(account.account_ref + ' · ' + state_label(account.readiness), account.account_ref)
                if account.account_ref == self.state.account_ref:
                    wizard.account.setCurrentIndex(wizard.account.count() - 1)
        self.contracts.setEnabled(market == Market.INDEX_FUTURE)
        self.instrument_rule.setEnabled(market == Market.INDEX_FUTURE)
        self.refresh_size()

    def parameters(self) -> StrategyParameters:
        if self.wizard.policy.currentData() == HoldingKind.CUSTOM and self.wizard.maximum.value() == 0:
            raise ValueError('custom holding days required')
        return StrategyParameters(
            self.interval.currentData(),
            Decimal(self.stop.text()) / 100,
            Decimal(self.entry_amount.text()),
            self.contracts.value(),
            self.stock_intraday.isChecked(),
            self.stock_confirmed,
            self.instrument_rule.currentData() if self.wizard.market.currentData() == Market.INDEX_FUTURE else 'EXACT',
        )

    def refresh_size(self):
        wizard = self.wizard
        try:
            amount, allocation = Decimal(self.entry_amount.text()), Decimal(wizard.allocation.text())
            if not amount.is_finite() or not allocation.is_finite() or min(amount, allocation) <= 0:
                raise InvalidOperation
        except InvalidOperation:
            self.size_hint.setText(ui_text('u3.invalid_budget'))
            return
        identity = wizard.instrument.currentData()
        if not identity:
            self.size_hint.setText(ui_text('u3.no_products'))
        elif wizard.market.currentData() == Market.STOCK:
            quote = next((item for item in self.state.markets if item.instrument_id == identity), None)
            if quote is None or quote.price is None:
                self.size_hint.setText(ui_text('u3.stock_size_unknown'))
            else:
                lots = int(min(amount, allocation) // (quote.price * 1000))
                self.size_hint.setText(ui_text('u3.stock_size').format(lots) + ' ' + ui_text('u3.whole_lot_only'))
        else:
            instrument = next((item for item in self.state.manual.instruments if item.instrument_id == identity), None)
            margin = instrument.margin_per_contract if instrument is not None else None
            source = ui_text('u3.margin_reference') if margin is not None else ui_text('u3.conservative_margin')
            # Display-only M2 reference; authoritative admission stays in the backend.
            required = (margin if margin is not None else Decimal('50000')) * self.contracts.value()
            self.size_hint.setText(
                ui_text('u3.futures_size').format(
                    self.contracts.value(),
                    f'{required:,.0f}',
                    source,
                    ui_text('u3.margin_enough') if required <= allocation else ui_text('u3.margin_insufficient'),
                )
            )
