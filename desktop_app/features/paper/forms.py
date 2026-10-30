"""desktop_app features paper forms responsibilities."""

from desktop_app.strings.catalog import ui_text
from desktop_app.components.timeinput import DateInput
from copy import deepcopy
import re
from PySide6.QtWidgets import QLineEdit, QCheckBox
from quantlab.core import ValidationError, validate_date, validate_contract
from desktop_app.components.form_values import required, utc
from desktop_app.components.forms import _Form
from desktop_app.components.result_tables import ResultTable, SummaryCard


class PaperIntentForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('client_order_id', ui_text('forms.init.order_id')),
            ('strategy_hash', ui_text('forms.init.strategy_hash')),
            ('contract_id', ui_text('forms.init.intent_contract')),
            ('quantity', ui_text('forms.init.order_quantity')),
            ('created_at', ui_text('forms.init.created_at')),
            ('limit_price', ui_text('forms.init.limit_price')),
        ):
            self.field(key, label)
        self.field('side', ui_text('forms.init.side'), choices=[(ui_text('forms.init.buy'), 'buy'), (ui_text('forms.init.sell'), 'sell')])
        self.field(
            'order_type',
            ui_text('forms.init.order_kind'),
            choices=[(ui_text('forms.init.market'), 'market'), (ui_text('forms.init.limit'), 'limit')],
        )
        self.note(ui_text('forms.init.intent_only_hint'))

    def from_payload(self, payload):
        allowed = {'client_order_id', 'strategy_hash', 'contract_id', 'quantity', 'created_at', 'limit_price', 'side', 'order_type'}
        if set(payload) - allowed:
            raise ValidationError(ui_text('forms.from_payload.unsupported_intent_fields'))
        for field in self.fields.values():
            if isinstance(field, (QLineEdit, DateInput)):
                field.clear()
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key: required(self.text(key), self.fields[key].accessibleName()) for key in ('client_order_id', 'strategy_hash', 'contract_id')}
        validate_contract(p['contract_id'])
        if not re.fullmatch('[0-9a-f]{64}', p['strategy_hash']):
            raise ValidationError(ui_text('forms.build_payload.invalid_strategy_hash'))
        p.update(
            quantity=self.num('quantity', 1, 1000000, integer=True),
            created_at=utc(self.text('created_at'), ui_text('forms.build_payload.created_at')),
            side=self.fields['side'].currentData(),
            order_type=self.fields['order_type'].currentData(),
        )
        if p['order_type'] == 'limit':
            p['limit_price'] = str(self.num('limit_price', 1, 1000000000, integer=True))
        elif self.text('limit_price'):
            raise ValidationError(ui_text('forms.build_payload.market_limit_forbidden'))
        return p


class PaperQuoteForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('account_id', ui_text('forms.init.account_id')),
            ('contract_id', ui_text('forms.init.quote_contract')),
            ('price', ui_text('forms.init.quote_price')),
            ('timestamp', ui_text('forms.init.quote_time')),
            ('trade_date', ui_text('forms.init.trading_day')),
            ('session_open', ui_text('forms.init.session_start')),
            ('session_end', ui_text('forms.init.session_end')),
            ('margin_per_contract', ui_text('forms.init.locked_initial_margin')),
        ):
            self.field(key, label)
        self.note(ui_text('forms.init.quote_source_hint'))

    def from_payload(self, payload):
        if set(payload) != set(self.fields):
            raise ValidationError(ui_text('forms.from_payload.invalid_quote_fields'))
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key: required(self.text(key), self.fields[key].accessibleName()) for key in ('account_id', 'contract_id', 'trade_date')}
        validate_contract(p['contract_id'])
        validate_date(p['trade_date'], ui_text('forms.build_payload.trading_day'))
        for key in ('timestamp', 'session_open', 'session_end'):
            p[key] = utc(self.text(key), self.fields[key].accessibleName())
        from quantlab.paper import _time

        if not _time(p['session_open']) <= _time(p['timestamp']) < _time(p['session_end']):
            raise ValidationError(ui_text('forms.build_payload.quote_outside_session'))
        p['price'] = str(self.num('price', 1, 1000000000, integer=True))
        p['margin_per_contract'] = self.num('margin_per_contract', '0.000000000001')
        return p


class PaperSnapshotForm(_Form):
    """Edit account/cash; retain imported position/order/fill records exactly.

    Existing nested records are review-only: never fabricate or clear them to
    force reconciliation. Initial empty records still require action consent.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('account_id', ui_text('forms.init.reference_account'))
        self.field('cash', ui_text('forms.init.reference_cash'))
        self._snapshot = {'positions': {}, 'orders': {}, 'fills': {}}
        self.records = SummaryCard()
        self.outer.addWidget(self.records)
        self.record_tables = {}
        for key, label in (
            ('positions', ui_text('forms.init.reference_positions')),
            ('orders', ui_text('forms.init.reference_orders')),
            ('fills', ui_text('forms.init.reference_fills')),
        ):
            self.note(ui_text('forms.init.readonly_value').format(label))
            table = ResultTable()
            table.setObjectName('snapshot_' + key)
            table.setMaximumHeight(160)
            self.record_tables[key] = table
            self.outer.addWidget(table)
        self.note(ui_text('forms.init.reconciliation_hint'))
        self._show_records()

    def _show_records(self):
        self.records.set_values(
            {
                ui_text('forms.show_records.position_items'): len(self._snapshot['positions']),
                ui_text('forms.show_records.order_count'): len(self._snapshot['orders']),
                ui_text('forms.show_records.fill_count'): len(self._snapshot['fills']),
            }
        )
        for key, table in self.record_tables.items():
            table.set_rows(
                [
                    {
                        ui_text('forms.show_records.identifier'): identifier,
                        **(value if isinstance(value, dict) else {ui_text('forms.show_records.quantity'): value}),
                    }
                    for identifier, value in self._snapshot[key].items()
                ]
            )

    def from_payload(self, payload):
        for key in ('positions', 'orders', 'fills'):
            if not isinstance(payload.get(key), dict):
                raise ValidationError(ui_text('forms.from_payload.complete_snapshot_required'))
        self._snapshot = deepcopy(payload)
        self.load(payload)
        self._show_records()
        return self

    def build_payload(self):
        p = deepcopy(self._snapshot)
        p.update(account_id=required(self.text('account_id'), ui_text('forms.build_payload.account_id')), cash=self.num('cash'))
        return p


class PaperActionForm(_Form):
    """Per-action controls; restored input never restores consent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('now', ui_text('forms.init.event_time'))
        self.field('order_id', ui_text('forms.init.cancel_order_id'))
        self.field('max_bars', ui_text('forms.init.replay_limit'), '100')
        self.confirm = QCheckBox(ui_text('forms.init.snapshot_consent'))
        self.confirm.setObjectName('paper_action_confirm')
        self.outer.addWidget(self.confirm)
        self.note(ui_text('forms.init.fixed_risk_limits'))

    def from_payload(self, payload):
        self.load(payload)
        self.clear_confirmation()
        return self

    def clear_confirmation(self):
        self.confirm.setChecked(False)

    def build_payload(self, action):
        if action not in ('snapshot', 'reconcile', 'submit', 'replay', 'cancel', 'kill'):
            raise ValidationError(ui_text('forms.build_payload.unknown_operation'))
        if action in ('snapshot', 'kill'):
            return {}
        if action == 'cancel':
            return {
                'now': utc(self.text('now'), ui_text('forms.build_payload.cancel_time')),
                'order_id': required(self.text('order_id'), ui_text('forms.build_payload.order_id')),
            }
        if not self.confirm.isChecked():
            raise ValidationError(ui_text('forms.build_payload.snapshot_consent_required'))
        p = {'reconcile_confirmed': True}
        if action == 'submit':
            p['now'] = utc(self.text('now'), ui_text('forms.build_payload.event_time'))
        if action == 'replay':
            p['max_bars'] = self.num('max_bars', 1, 1000, integer=True)
        return p
