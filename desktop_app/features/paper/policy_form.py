"""desktop_app features paper policy_form responsibilities."""

from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError, validate_date, validate_contract
from desktop_app.components.form_values import number, utc
from desktop_app.components.forms import _Form, _Rows


class PaperPolicyForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('contract_id', ui_text('forms.init.locked_contract'))
        self.note(ui_text('forms.init.policy_source_hint'))
        self.sessions = _Rows(
            'risk_sessions',
            [
                ('open', ui_text('forms.init.policy_session_start')),
                ('end', ui_text('forms.init.policy_session_end')),
                ('trade_date', ui_text('forms.init.policy_trading_day')),
                ('source', ui_text('forms.init.policy_source')),
                ('session', ui_text('forms.init.session_kind')),
            ],
        )
        self.outer.addWidget(self.sessions)
        self.margins = _Rows(
            'margin_schedule',
            [
                ('effective_from', ui_text('forms.init.margin_effective_day')),
                ('margin_per_contract', ui_text('forms.init.margin_amount')),
                ('version', ui_text('forms.init.margin_version')),
            ],
        )
        self.outer.addWidget(self.margins)

    def from_payload(self, payload):
        if set(payload) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
            raise ValidationError(ui_text('forms.from_payload.invalid_policy_fields'))
        self.load(payload)
        self.sessions.load(payload['risk_sessions'])
        self.margins.load(payload['margin_schedule'])
        return self

    def build_payload(self):
        contract = self.text('contract_id')
        validate_contract(contract)
        sessions, margins = self.sessions.values(), self.margins.values()
        if not sessions or not margins:
            raise ValidationError(ui_text('forms.build_payload.explicit_policy_required'))
        for row in sessions:
            utc(row['open'], ui_text('forms.build_payload.session_start'))
            utc(row['end'], ui_text('forms.build_payload.session_end'))
            validate_date(row['trade_date'], ui_text('forms.build_payload.trading_day'))
        for row in margins:
            row['margin_per_contract'] = number(row['margin_per_contract'], ui_text('forms.build_payload.margin'), '0.000000000001')
        # Invoke the existing pure policy validator without opening a journal.
        from quantlab.paper import PaperBroker
        from quantlab.core import Instrument

        broker = object.__new__(PaperBroker)
        broker.instrument = Instrument(contract)
        broker._risk_sessions = sessions
        broker._margin_schedule = margins
        broker._validate_policy()
        return dict(contract_id=contract, risk_sessions=sessions, margin_schedule=margins)
