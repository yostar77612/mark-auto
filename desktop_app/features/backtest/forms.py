"""desktop_app features backtest forms responsibilities."""

from desktop_app.strings.catalog import ui_text
from copy import deepcopy
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView
from quantlab.core import ValidationError, validate_date, validate_contract, to_dict
from desktop_app.components.form_values import required
from desktop_app.components.forms import _Form, _Rows


class BacktestForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('initial_cash', ui_text('forms.init.initial_cash')),
            ('max_position', ui_text('forms.init.max_position')),
            ('commission_per_side', ui_text('forms.init.commission')),
            ('tax_rate', ui_text('forms.init.tax_rate')),
            ('slippage_ticks', ui_text('forms.init.slippage')),
            ('effective_from', ui_text('forms.init.fee_date')),
            ('version', ui_text('forms.init.fee_source')),
            ('initial_margin_per_contract', ui_text('forms.init.initial_margin')),
            ('maintenance_margin_per_contract', ui_text('forms.init.maintenance_margin')),
            ('margin_version', ui_text('forms.init.margin_source')),
            ('seed', ui_text('forms.init.seed')),
            ('start_date', ui_text('forms.init.start_date')),
            ('end_date', ui_text('forms.init.end_date')),
        ):
            self.field(key, label)
        self.field(
            'tax_rounding',
            ui_text('forms.init.tax_rounding'),
            choices=[
                (ui_text('forms.init.round_half_up'), 'half_up_twd'),
                (ui_text('forms.init.round_down'), 'floor_twd'),
                (ui_text('forms.init.round_up'), 'ceiling_twd'),
                (ui_text('forms.init.no_rounding'), 'none'),
            ],
        )
        self.note(ui_text('forms.init.synthetic_cost_hint'))
        self.expiry_note = self.note(ui_text('forms.init.expiry_source_hint'))
        self.expiry_note.setObjectName('instrument_expiries_note')
        self.expiry_note.setTextFormat(Qt.TextFormat.PlainText)
        self.expiry_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.expiries = _Rows('instrument_expiries', [('contract_id', ui_text('forms.init.contract_code')), ('expiry_date', ui_text('forms.init.expiry_date'))])
        self.expiries.table.horizontalHeaderItem(0).setToolTip(ui_text('forms.init.explicit_contract'))
        self.expiries.table.horizontalHeaderItem(1).setToolTip(ui_text('forms.init.last_trading_date'))
        self.expiries.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.expiries.table.setAccessibleName(ui_text('forms.init.expiry_title'))
        self.outer.addWidget(self.expiries)
        from desktop_app.components.expiry_inputs import attach_expiry_table

        attach_expiry_table(self)
        from quantlab.core import BacktestConfig, CostSpec

        self.from_payload(
            {
                'config': to_dict(
                    BacktestConfig(
                        Decimal('1000000'),
                        CostSpec(Decimal('20'), Decimal('0.00002'), 1, 'half_up_twd', '2026-01-01', 'synthetic-assumption-v1'),
                        initial_margin_per_contract=Decimal('100000'),
                        margin_version='synthetic-assumption-v1',
                        maintenance_margin_per_contract=Decimal('80000'),
                    )
                ),
                'start_date': '',
                'end_date': '',
            }
        )

    def from_payload(self, payload):
        config = deepcopy(payload.get('config', payload))
        from quantlab.configuration import config_from_json

        parsed = config_from_json(config)
        config = {**to_dict(parsed), **config}
        self._config = config
        self.load(config)
        self.load(config['costs'])
        self.expiries.load([{'contract_id': contract, 'expiry_date': expiry} for contract, expiry in config['instrument_expiries'].items()])
        self.load({k: payload.get(k, '') for k in ('start_date', 'end_date')})
        return self

    def build_payload(self):
        config = deepcopy(self._config)
        expiries = {}
        for index, row in enumerate(self.expiries.values(), 1):
            contract, expiry = row['contract_id'], row['expiry_date']
            try:
                validate_contract(contract)
                validate_date(expiry)
            except ValidationError:
                raise ValidationError(ui_text('forms.build_payload.invalid_expiry_row').format(index)) from None
            if contract in expiries:
                raise ValidationError(ui_text('forms.build_payload.duplicate_expiry').format(index, contract))
            expiries[contract] = expiry
        config['instrument_expiries'] = expiries
        config['initial_cash'] = self.num('initial_cash')
        config['max_position'] = self.num('max_position', 1, 1000000, integer=True)
        config['seed'] = self.num('seed', 0, 2147483647, integer=True)
        for key in ('initial_margin_per_contract', 'maintenance_margin_per_contract'):
            config[key] = self.num(key, optional=True)
        config['margin_version'] = self.text('margin_version') or None
        costs = deepcopy(config['costs'])
        costs.update(
            commission_per_side=self.num('commission_per_side'),
            tax_rate=self.num('tax_rate', 0, 1),
            slippage_ticks=self.num('slippage_ticks', 0, 100000, integer=True),
            effective_from=self.text('effective_from'),
            version=required(self.text('version'), ui_text('forms.build_payload.fee_version')),
            tax_rounding=self.fields['tax_rounding'].currentData(),
        )
        config['costs'] = costs
        from quantlab.configuration import config_from_json

        config_from_json(config)
        start, end = self.text('start_date'), self.text('end_date')
        for value in (start, end):
            if value:
                validate_date(value, ui_text('forms.build_payload.trading_day'))
        if start and end and start > end:
            raise ValidationError(ui_text('forms.build_payload.reversed_dates'))
        return dict(config=config, start_date=start, end_date=end)
