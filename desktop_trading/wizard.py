"""Six explicit choices; policy validation belongs to Application, never Qt."""

from decimal import Decimal, InvalidOperation
import json

from PySide6.QtCore import QTimer, Qt

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from desktop_strings import ui_text
from quantlab.trading.application.contracts import StrategyForm, UiState
from quantlab.trading.domain.models import HoldingKind, Market, Side

from .labels import state_label
from .widgets import combo, fit_available_screen, label


MARKETS = (('v2.stock', Market.STOCK), ('v2.index_future', Market.INDEX_FUTURE), ('v2.stock_future', Market.STOCK_FUTURE))
POLICIES = (
    ('v2.swing', HoldingKind.SWING),
    ('v2.intraday', HoldingKind.INTRADAY),
    ('v2.week', HoldingKind.CUSTOM),
    ('v2.position', HoldingKind.POSITION),
    ('v2.custom', HoldingKind.CUSTOM),
)


class StrategyWizard(QWizard):
    def __init__(self, state: UiState, parent=None, *, parent_strategy_id: str = ''):
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        font = parent.font() if parent is not None else self.font()
        font.setPointSize(max(11, font.pointSize()))
        self.setFont(font)
        self.state = state
        self.parent_strategy_id = parent_strategy_id
        self._screen_hooked = False
        self.setObjectName('trading_strategy_wizard')
        self.setWindowTitle(ui_text('v2.wizard_title'))
        self.setMinimumSize(480, 300)
        self.resize(680, 520)
        self.setButtonText(QWizard.WizardButton.NextButton, ui_text('v2.next'))
        self.setButtonText(QWizard.WizardButton.BackButton, ui_text('v2.back'))
        self.setButtonText(QWizard.WizardButton.FinishButton, ui_text('v2.create_draft'))
        self.setButtonText(QWizard.WizardButton.CancelButton, ui_text('v2.cancel'))
        self._build_choices(state)
        self._build_expiry()
        self._build_pages()
        self._bind()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._screen_hooked and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(lambda _screen: fit_available_screen(self))
            self._screen_hooked = True
        QTimer.singleShot(0, lambda: fit_available_screen(self))

    def _build_choices(self, state: UiState) -> None:
        self.market = combo(MARKETS, 'market')
        self.policy = combo(POLICIES, 'policy')
        self.direction = combo((('v2.long', Side.BUY), ('v2.short', Side.SELL)), 'direction')
        self.minimum = QSpinBox()
        self.maximum = QSpinBox()
        for widget, name, value in ((self.minimum, 'minimum_days', 3), (self.maximum, 'maximum_days', 5)):
            widget.setRange(0, 2500)
            widget.setValue(value)
            widget.setObjectName(name)
            widget.setAccessibleName(ui_text('v2.' + name))
        self.instrument = QComboBox()
        self.instrument.setObjectName('strategy_instrument')
        self.instrument.setAccessibleName(ui_text('v2.instrument'))
        self.account = QComboBox()
        self.account.setObjectName('strategy_account')
        self.account.setAccessibleName(ui_text('v2.account'))
        self.name = QLineEdit(ui_text('v2.default_strategy_name'))
        self.name.setObjectName('strategy_name')
        self.name.setAccessibleName(ui_text('v2.name'))
        self.allocation = QLineEdit(str(state.allocated_cash))
        self.allocation.setObjectName('strategy_allocation')
        self.allocation.setAccessibleName(ui_text('v2.allocation'))
        self.risk = combo((('v2.risk_2', Decimal('0.02')), ('v2.risk_3', Decimal('0.03'))), 'risk')
        self.rules = combo((('v2.rule_ma', 'MA_CROSS'), ('v2.rule_breakout', 'BREAKOUT'), ('v2.rule_json', 'STRUCTURED_JSON')), 'rules')
        self.draft = QPlainTextEdit()
        self.draft.setObjectName('strategy_draft_json')
        self.draft.setAccessibleName(ui_text('v2.draft_json'))
        self.draft.setPlaceholderText(ui_text('v2.draft_hint'))
        self.draft.setMinimumHeight(150)
        self.draft_hint = label('v2.draft_hint')

    def _build_expiry(self) -> None:
        self.expiry_group = QGroupBox(ui_text('v2.expiry_advanced'))
        self.expiry_group.setCheckable(True)
        self.expiry_group.setChecked(False)
        expiry_layout = QVBoxLayout(self.expiry_group)
        self.expiry_content = QWidget()
        expiry_fields = QFormLayout(self.expiry_content)
        expiry_fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.expiry_action = QComboBox()
        self.expiry_action.setObjectName('strategy_expiry_action')
        self.expiry_action.setAccessibleName(ui_text('v2.expiry_action'))
        self.expiry_action.addItem(ui_text('v2.expiry_exit'), 'EXIT')
        self.expiry_action.addItem(ui_text('v2.expiry_roll'), 'ROLL')
        self.roll_contract = QComboBox()
        self.roll_contract.setObjectName('strategy_roll_contract')
        self.roll_contract.setAccessibleName(ui_text('v2.roll_contract'))
        expiry_fields.addRow(ui_text('v2.expiry_action'), self.expiry_action)
        expiry_fields.addRow(ui_text('v2.roll_contract'), self.roll_contract)
        expiry_fields.addRow(label('v2.roll_hint'))
        expiry_layout.addWidget(self.expiry_content)
        self.expiry_content.setVisible(False)
        self.expiry_group.toggled.connect(self.expiry_content.setVisible)

    def _build_pages(self) -> None:
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setObjectName('wizard_error')
        self._page('v2.step_market', ((ui_text('v2.market'), self.market),), 'v2.market_hint')
        self._page(
            'v2.step_policy',
            (
                (ui_text('v2.policy'), self.policy),
                (ui_text('v2.minimum_days'), self.minimum),
                (ui_text('v2.maximum_days'), self.maximum),
                ('', self.expiry_group),
            ),
            'v2.policy_hint',
        )
        self._page('v2.step_direction', ((ui_text('v2.direction'), self.direction),), 'v2.direction_hint')
        self._page('v2.step_instrument', ((ui_text('v2.instrument'), self.instrument),), 'v2.instrument_hint')
        self._page(
            'v2.step_budget',
            ((ui_text('v2.account'), self.account), (ui_text('v2.allocation'), self.allocation), (ui_text('v2.risk'), self.risk)),
            'v2.budget_hint',
        )
        self._page(
            'v2.step_rules',
            (
                (ui_text('v2.name'), self.name),
                (ui_text('v2.rules'), self.rules),
                ('', self.draft_hint),
                (ui_text('v2.draft_json'), self.draft),
                ('', self.summary),
                ('', self.error),
            ),
            'v2.rules_hint',
        )

    def _bind(self) -> None:
        self.market.currentIndexChanged.connect(self._candidates)
        self.account.currentIndexChanged.connect(self._account_selected)
        self.policy.currentIndexChanged.connect(self._policy_changed)
        self.rules.currentIndexChanged.connect(self._rules_changed)
        self.instrument.currentIndexChanged.connect(self._roll_targets)
        self.expiry_action.currentIndexChanged.connect(self._expiry_changed)
        self.currentIdChanged.connect(self._summary)
        self.currentIdChanged.connect(lambda _page: QTimer.singleShot(0, lambda: fit_available_screen(self)))
        self._candidates()
        self._rules_changed()
        self._roll_targets()

    def _page(self, title_key: str, controls: tuple, hint_key: str) -> None:
        page = QWizardPage()
        page.setTitle(ui_text(title_key))
        page_layout = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(label(hint_key))
        for text, control in controls:
            form.addRow(text, control)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        self.addPage(page)

    def _candidates(self) -> None:
        self.instrument.clear()
        self.account.clear()
        market = self.market.currentData()
        for instrument in self.state.markets:
            if instrument.market == market:
                self.instrument.addItem(instrument.instrument_id, instrument.instrument_id)
        for account in self.state.accounts:
            if account.environment == self.state.environment and (account.market == market or market != Market.STOCK and account.market != Market.STOCK):
                self.account.addItem(account.account_ref + ' · ' + state_label(account.readiness), account.account_ref)
                if account.account_ref == self.state.account_ref:
                    self.account.setCurrentIndex(self.account.count() - 1)

    def _policy_changed(self) -> None:
        policy = self.policy.currentData()
        default = (
            (0, 0) if policy == HoldingKind.INTRADAY else (20, 250) if policy == HoldingKind.POSITION else (5, 5) if self.policy.currentIndex() == 2 else (3, 5)
        )
        self.minimum.setValue(default[0])
        self.maximum.setValue(default[1])
        self.minimum.setEnabled(policy != HoldingKind.INTRADAY)
        self.maximum.setEnabled(policy != HoldingKind.INTRADAY)

    def _account_selected(self) -> None:
        account = next((item for item in self.state.accounts if item.account_ref == self.account.currentData()), None)
        if account is not None:
            self.allocation.setText(str(account.allocation))

    def _roll_targets(self) -> None:
        self.roll_contract.clear()
        source = next((item for item in self.state.markets if item.instrument_id == self.instrument.currentData()), None)
        futures = source is not None and source.market != Market.STOCK
        self.expiry_group.setVisible(futures)
        self.expiry_action.setEnabled(futures)
        if not futures:
            self.expiry_action.setCurrentIndex(0)
        elif source.underlying and source.delivery_month:
            for target in self.state.markets:
                if target.market == source.market and target.underlying == source.underlying and target.delivery_month > source.delivery_month:
                    self.roll_contract.addItem(target.instrument_id, target.instrument_id)
        self._expiry_changed()

    def _expiry_changed(self) -> None:
        self.roll_contract.setEnabled(self.expiry_action.currentData() == 'ROLL')

    def _rules_changed(self) -> None:
        structured = self.rules.currentData() == 'STRUCTURED_JSON'
        self.draft.setVisible(structured)
        self.draft_hint.setVisible(structured)
        if structured and not self.draft.toPlainText():
            self.draft.setPlainText(
                json.dumps(
                    {
                        'schema_version': 2,
                        'strategy_id': 'local-draft',
                        'version': 1,
                        'market': self.market.currentData(),
                        'holding_policy': {
                            'kind': self.policy.currentData(),
                            'min_days': self.minimum.value(),
                            'max_days': self.maximum.value(),
                            'night_enabled': False,
                            'expiry_action': self.expiry_action.currentData(),
                        },
                        'bar_interval': '1d',
                        'direction': 'LONG_ONLY' if self.direction.currentData() == Side.BUY else 'SHORT_ONLY',
                        'entry': [{'field': 'close', 'operator': 'GT', 'value': '0'}],
                        'exit': [{'field': 'close', 'operator': 'LT', 'value': '0'}],
                        'cost_version': self.state.cost_version,
                        'risk_ref': self.state.risk_version,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

    def form(self) -> StrategyForm:
        amount = Decimal(self.allocation.text())
        if not amount.is_finite() or amount <= 0 or not self.name.text().strip() or not self.instrument.currentData() or not self.account.currentData():
            raise ValueError('invalid strategy form')
        draft_json = self.draft.toPlainText() if self.rules.currentData() == 'STRUCTURED_JSON' else ''
        if self.rules.currentData() == 'STRUCTURED_JSON' and (not draft_json or len(draft_json.encode('utf-8')) > 65536):
            raise ValueError('draft size')
        expiry_action = self.expiry_action.currentData() if self.market.currentData() != Market.STOCK else 'EXIT'
        roll_contract_id = self.roll_contract.currentData() or '' if expiry_action == 'ROLL' else ''
        if expiry_action == 'ROLL' and not roll_contract_id:
            raise ValueError('explicit roll contract required')
        return StrategyForm(
            self.name.text().strip(),
            Market(self.market.currentData()),
            HoldingKind(self.policy.currentData()),
            self.minimum.value(),
            self.maximum.value(),
            Side(self.direction.currentData()),
            self.instrument.currentData(),
            self.account.currentData(),
            self.state.environment,
            amount,
            self.risk.currentData(),
            self.rules.currentData(),
            self.parent_strategy_id,
            draft_json=draft_json,
            expiry_action=expiry_action,
            roll_contract_id=roll_contract_id,
        )

    def _summary(self) -> None:
        self.summary.setText(
            ui_text('v2.wizard_summary').format(
                self.market.currentText(),
                self.policy.currentText(),
                self.minimum.value(),
                self.maximum.value(),
                self.state.environment.value,
                self.account.currentData() or '',
                self.allocation.text(),
                self.risk.currentText(),
            )
            + '\n'
            + ui_text('v2.expiry_summary').format(
                self.expiry_action.currentText(),
                self.roll_contract.currentData() if self.expiry_action.currentData() == 'ROLL' else ui_text('v2.no_roll_target'),
            )
        )

    def accept(self) -> None:
        try:
            self.form()
        except (InvalidOperation, ValueError):
            self.error.setText(ui_text('v2.form_invalid'))
            return
        super().accept()
