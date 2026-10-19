"""Small, data-only Traditional Chinese Qt forms for the existing worker API.

Forms never start work or connect to brokers. ``from_payload`` loads a detached
copy; ``build_payload`` validates without changing external state. Embed these
widgets in the desktop page's QScrollArea. Exact decimal strings avoid float or
QDoubleSpinBox rounding. Backend validation remains authoritative.
"""

from desktop_strings import ui_text
from desktop_timeinput import DateInput, DATE_KEYS, TIME_KEYS, install_date_columns, open_date_editors
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QPushButton,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
)

from quantlab.core import ValidationError, StrategySpec, validate_date, validate_contract, to_dict
from quantlab.strategies import DEFAULTS, FAMILIES, validate_strategy

FAMILY_LABELS = dict(
    zip(
        FAMILIES,
        (
            ui_text('forms.labels.text_1'),
            ui_text('forms.labels.text_2'),
            ui_text('forms.labels.text_3'),
            ui_text('forms.labels.text_4'),
            ui_text('forms.labels.text_5'),
        ),
    )
)
PARAM_LABELS = {
    'fast': ui_text('forms.labels.text_6'),
    'slow': ui_text('forms.labels.text_7'),
    'lookback': ui_text('forms.labels.text_8'),
    'entry_bps': ui_text('forms.labels.text_9'),
    'threshold_bps': ui_text('forms.labels.text_10'),
    'max_holding_bars': ui_text('forms.labels.text_11'),
    'max_range_bps': ui_text('forms.labels.text_12'),
    'quantity': ui_text('forms.labels.text_13'),
    'stop_ticks': ui_text('forms.labels.text_14'),
    'target_ticks': ui_text('forms.labels.text_15'),
}


def number(text, label, minimum=0, maximum='1e12', *, integer=False, optional=False):
    """Strict bounded decimal input; never silently clamp, round, or default."""
    text = str(text).strip()
    if not text and optional:
        return None
    if len(text) > 128 or not text:
        raise ValidationError(ui_text('forms.number.text_1').format(label))
    try:
        value = Decimal(text)
        if not value.is_finite() or value < Decimal(str(minimum)) or value > Decimal(str(maximum)):
            raise ValueError()
        # Bound exponent as well as magnitude to avoid enormous decimal expansion.
        if abs(value.as_tuple().exponent) > 32:
            raise ValueError()
        if integer and (not re.fullmatch(r'[+-]?\d+', text) or value != value.to_integral_value()):
            raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValidationError(
            ui_text('forms.number.text_2').format(label, minimum, maximum) + (ui_text('forms.number.text_3') if integer else ui_text('forms.number.text_4'))
        ) from None
    return int(value) if integer else format(value, 'f')


def required(text, label):
    text = text.strip()
    if not text or len(text) > 256:
        raise ValidationError(ui_text('forms.required.text_1').format(label))
    return text


def utc(text, label):
    from quantlab.paper import _time

    value = required(text, label)
    try:
        _time(value, label)
    except ValidationError:
        raise ValidationError(ui_text('forms.utc.text_1').format(label)) from None
    return value


class _Form(QWidget):
    """Shared label/field plumbing only; each payload is explicit below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        self.outer = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.outer.addLayout(self.form)

    def note(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        self.outer.addWidget(label)
        return label

    def field(self, key, label, value='', choices=None):
        if choices is None:
            widget = DateInput(str(value), timestamp=key in TIME_KEYS) if key in DATE_KEYS | TIME_KEYS else QLineEdit(str(value))
        else:
            widget = QComboBox()
            for caption, data in choices:
                widget.addItem(caption, data)
        widget.setObjectName(key)
        widget.setAccessibleName(label)
        caption = QLabel(label)
        caption.setBuddy(widget)
        self.form.addRow(caption, widget)
        self.fields[key] = widget
        return widget

    def text(self, key):
        return self.fields[key].text().strip()

    def num(self, key, minimum=0, maximum='1e12', **kwargs):
        return number(self.text(key), self.fields[key].accessibleName(), minimum, maximum, **kwargs)

    def load(self, values):
        for key, value in values.items():
            if key not in self.fields:
                continue
            field = self.fields[key]
            if isinstance(field, QComboBox):
                index = field.findData(value)
                if index < 0:
                    raise ValidationError(ui_text('forms.load.text_1').format(field.accessibleName()))
                field.setCurrentIndex(index)
            else:
                field.setText('' if value is None else str(value))
        return self


class StrategyForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.family = self.field('family', ui_text('forms.__init__.text_1'), choices=[(FAMILY_LABELS[f], f) for f in FAMILIES])
        self.parameter_form = QFormLayout()
        self.outer.addLayout(self.parameter_form)
        self._spec = None
        self.family.currentIndexChanged.connect(self._family_changed)
        self._family_changed()
        self.note(ui_text('forms.__init__.text_2'))

    def _family_changed(self):
        while self.parameter_form.rowCount():
            self.parameter_form.removeRow(0)
        self.fields = {'family': self.family}
        family = self.family.currentData()
        self._spec = {'strategy_id': f'{family}-v1', 'family': family, 'parameters': dict(DEFAULTS[family]), 'rules': {}, 'schema_version': 1}
        for key, value in {**DEFAULTS[family], 'quantity': '', 'stop_ticks': '', 'target_ticks': ''}.items():
            widget = QLineEdit(str(value))
            widget.setObjectName(key)
            widget.setAccessibleName(PARAM_LABELS[key])
            label = QLabel(PARAM_LABELS[key])
            label.setBuddy(widget)
            self.parameter_form.addRow(label, widget)
            self.fields[key] = widget

    def from_payload(self, payload):
        spec = StrategySpec(**deepcopy(payload))
        validate_strategy(spec)
        if spec.rules:
            raise ValidationError(ui_text('forms.from_payload.text_1'))
        self.family.setCurrentIndex(self.family.findData(spec.family))
        self._family_changed()
        self._spec = to_dict(spec)
        self.load(spec.parameters)
        return self

    def build_payload(self):
        p = {}
        for key in self.fields:
            if key == 'family':
                continue
            optional = key in ('quantity', 'stop_ticks', 'target_ticks')
            if optional and not self.text(key):
                continue
            p[key] = self.num(key, integer=not key.endswith('_bps'))
        spec = StrategySpec(self._spec['strategy_id'], self.family.currentData(), p, {}, self._spec['schema_version'])
        validate_strategy(spec)
        return to_dict(spec)


class BacktestForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('initial_cash', ui_text('forms.__init__.text_3')),
            ('max_position', ui_text('forms.__init__.text_4')),
            ('commission_per_side', ui_text('forms.__init__.text_5')),
            ('tax_rate', ui_text('forms.__init__.text_6')),
            ('slippage_ticks', ui_text('forms.__init__.text_7')),
            ('effective_from', ui_text('forms.__init__.text_8')),
            ('version', ui_text('forms.__init__.text_9')),
            ('initial_margin_per_contract', ui_text('forms.__init__.text_10')),
            ('maintenance_margin_per_contract', ui_text('forms.__init__.text_11')),
            ('margin_version', ui_text('forms.__init__.text_12')),
            ('seed', ui_text('forms.__init__.text_13')),
            ('start_date', ui_text('forms.__init__.text_14')),
            ('end_date', ui_text('forms.__init__.text_15')),
        ):
            self.field(key, label)
        self.field(
            'tax_rounding',
            ui_text('forms.__init__.text_16'),
            choices=[
                (ui_text('forms.__init__.text_17'), 'half_up_twd'),
                (ui_text('forms.__init__.text_18'), 'floor_twd'),
                (ui_text('forms.__init__.text_19'), 'ceiling_twd'),
                (ui_text('forms.__init__.text_20'), 'none'),
            ],
        )
        self.note(ui_text('forms.__init__.text_21'))
        self.expiry_note = self.note(ui_text('forms.__init__.text_22'))
        self.expiry_note.setObjectName('instrument_expiries_note')
        self.expiry_note.setTextFormat(Qt.TextFormat.PlainText)
        self.expiry_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.expiries = _Rows('instrument_expiries', [('contract_id', ui_text('forms.__init__.text_23')), ('expiry_date', ui_text('forms.__init__.text_24'))])
        self.expiries.table.horizontalHeaderItem(0).setToolTip(ui_text('forms.__init__.text_25'))
        self.expiries.table.horizontalHeaderItem(1).setToolTip(ui_text('forms.__init__.text_26'))
        self.expiries.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.expiries.table.setAccessibleName(ui_text('forms.__init__.text_27'))
        self.outer.addWidget(self.expiries)
        from desktop_expiry_inputs import attach_expiry_table

        attach_expiry_table(self)
        from quantlab.reporting import demo_config

        self.from_payload({'config': to_dict(demo_config()), 'start_date': '', 'end_date': ''})

    def from_payload(self, payload):
        config = deepcopy(payload.get('config', payload))
        from quantlab.__main__ import config_from_json

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
                raise ValidationError(ui_text('forms.build_payload.text_1').format(index)) from None
            if contract in expiries:
                raise ValidationError(ui_text('forms.build_payload.text_2').format(index, contract))
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
            version=required(self.text('version'), ui_text('forms.build_payload.text_3')),
            tax_rounding=self.fields['tax_rounding'].currentData(),
        )
        config['costs'] = costs
        from quantlab.__main__ import config_from_json

        config_from_json(config)
        start, end = self.text('start_date'), self.text('end_date')
        for value in (start, end):
            if value:
                validate_date(value, ui_text('forms.build_payload.text_4'))
        if start and end and start > end:
            raise ValidationError(ui_text('forms.build_payload.text_5'))
        return dict(config=config, start_date=start, end_date=end)


class CampaignForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self.note(ui_text('forms.__init__.text_28'))
        for split, label in (
            ('train', ui_text('forms.__init__.text_29')),
            ('validation', ui_text('forms.__init__.text_30')),
            ('oos', ui_text('forms.__init__.text_31')),
            ('holdout', ui_text('forms.__init__.text_32')),
        ):
            self.field(split + '_start', ui_text('forms.__init__.text_33').format(label))
            self.field(split + '_end', ui_text('forms.__init__.text_34').format(label))
        for key, label, value in (
            ('max_trials', ui_text('forms.__init__.text_35'), 15),
            ('max_improvements', ui_text('forms.__init__.text_36'), 2),
            ('seed', ui_text('forms.__init__.text_37'), 0),
            ('max_runtime_seconds', ui_text('forms.__init__.text_38'), 300),
            ('max_bars', ui_text('forms.__init__.text_39'), 100000),
            ('purge_bars', ui_text('forms.__init__.text_40'), 0),
            ('minimum', ui_text('forms.__init__.text_41'), 0),
            ('min_trades', ui_text('forms.__init__.text_42'), 0),
        ):
            self.field(key, label, value)
        self.families = {}
        for family in FAMILIES:
            box = QCheckBox(FAMILY_LABELS[family])
            box.setObjectName('campaign_' + family)
            box.setChecked(True)
            box.setAccessibleName(ui_text('forms.__init__.text_43').format(FAMILY_LABELS[family]))
            self.outer.addWidget(box)
            self.families[family] = box

    def from_payload(self, payload):
        families = payload.get('families')
        if not isinstance(families, list) or not families or len(set(families)) != len(families) or any(f not in FAMILIES for f in families):
            raise ValidationError(ui_text('forms.from_payload.text_2'))
        self._config = deepcopy(payload)
        self.load(payload)
        self.load(payload['ranking'])
        for split, bounds in payload['splits'].items():
            self.load({split + '_start': bounds[0], split + '_end': bounds[1]})
        for family, box in self.families.items():
            box.setChecked(family in payload['families'])
        return self

    def build_payload(self, backtest_config=None):
        if self._config is None and backtest_config is None:
            raise ValidationError(ui_text('forms.build_payload.text_6'))
        config = deepcopy(self._config or {})
        if backtest_config is not None:
            config['backtest_config'] = deepcopy(backtest_config)
        bounds = {
            'max_trials': (1, 15),
            'max_improvements': (0, 2),
            'seed': (0, 2147483647),
            'max_runtime_seconds': (1, 7200),
            'max_bars': (1, 100000),
            'purge_bars': (0, 1000),
        }
        for key, (low, high) in bounds.items():
            config[key] = self.num(key, low, high, integer=True)
        config['splits'] = {}
        previous = 0
        for split in ('train', 'validation', 'oos', 'holdout'):
            start = self.num(split + '_start', 0, config['max_bars'], integer=True)
            end = self.num(split + '_end', 0, config['max_bars'], integer=True)
            if start < previous or end <= start + config['purge_bars']:
                raise ValidationError(ui_text('forms.build_payload.text_7'))
            config['splits'][split] = [start, end]
            previous = end
        config['families'] = [f for f, b in self.families.items() if b.isChecked()]
        if not config['families']:
            raise ValidationError(ui_text('forms.build_payload.text_8'))
        config['ranking'] = dict(metric='net_pnl', minimum=self.num('minimum', '-1e12'), min_trades=self.num('min_trades', 0, 1000000, integer=True))
        from quantlab.__main__ import config_from_json

        config_from_json(config['backtest_config'])
        return config


class WalkForwardForm(_Form):
    """Typed chronology editor; saved pools are admitted only by the worker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field(
            'pool_origin',
            ui_text('forms.__init__.text_44'),
            choices=[(ui_text('forms.__init__.text_45'), 'exact_builtin_pool'), (ui_text('forms.__init__.text_46'), 'saved_campaign_pool')],
        )
        self.field(
            'mode',
            ui_text('forms.__init__.text_47'),
            choices=[(ui_text('forms.__init__.text_48'), 'rolling'), (ui_text('forms.__init__.text_49'), 'expanding')],
        )
        self.field(
            'evidence_mode',
            ui_text('forms.__init__.text_50'),
            choices=[(ui_text('forms.__init__.text_51'), 'synthetic_validation'), (ui_text('forms.__init__.text_52'), 'historical_replay')],
        )
        for key, label, value in (
            ('start', ui_text('forms.__init__.text_53'), 0),
            ('train_bars', ui_text('forms.__init__.text_54'), 240),
            ('validation_bars', ui_text('forms.__init__.text_55'), 120),
            ('oos_bars', ui_text('forms.__init__.text_56'), 120),
            ('fold_count', ui_text('forms.__init__.text_57'), 3),
            ('step_bars', ui_text('forms.__init__.text_58'), 120),
            ('gap_bars', ui_text('forms.__init__.text_59'), 0),
            ('final_holdout_start', ui_text('forms.__init__.text_60'), 720),
            ('final_holdout_end', ui_text('forms.__init__.text_61'), 960),
            ('max_evaluations', ui_text('forms.__init__.text_62'), 33),
            ('max_runtime_seconds', ui_text('forms.__init__.text_63'), 300),
            ('minimum', ui_text('forms.__init__.text_64'), '0'),
            ('min_trades', ui_text('forms.__init__.text_65'), 1),
            ('max_drawdown_percent', ui_text('forms.__init__.text_66'), '10.00'),
        ):
            self.field(key, label, value)
        self._plan = None
        self.fields['pool_origin'].currentIndexChanged.connect(self._pool_origin_changed)
        self._pool_origin_changed()
        self.note(ui_text('forms.__init__.text_67'))
        self.note(ui_text('forms.__init__.text_68'))

    def _pool_origin_changed(self):
        saved = self.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        cap = 620 if saved else 220
        label = ui_text('forms._pool_origin_changed.text_1').format(cap)
        self.form.labelForField(self.fields['max_evaluations']).setText(label)
        self.fields['max_evaluations'].setAccessibleName(label)

    def defaults_for_bars(self, count):
        if type(count) is not int or count < 8:
            raise ValidationError(ui_text('forms.defaults_for_bars.text_1'))
        train, width = max(1, count // 4), max(1, count // 8)
        values = dict(
            start=0,
            train_bars=train,
            validation_bars=width,
            oos_bars=width,
            fold_count=3,
            step_bars=width,
            gap_bars=0,
            final_holdout_start=train + 4 * width,
            final_holdout_end=count,
        )
        if self.fields['pool_origin'].currentData() == 'exact_builtin_pool':
            values['max_evaluations'] = 33
        self.load(values)
        return self

    def from_payload(self, payload):
        from quantlab.walk_forward import walk_forward_plan_from_dict
        from decimal import localcontext

        plan = walk_forward_plan_from_dict(deepcopy(payload))
        if plan.pool_origin != 'exact_builtin_pool':
            raise ValidationError(ui_text('forms.from_payload.text_3'))
        self._plan = to_dict(plan)
        first, second = plan.folds[:2]
        values = dict(
            pool_origin=plan.pool_origin,
            mode=plan.mode,
            evidence_mode=plan.evidence_mode,
            start=first.train[0],
            train_bars=first.train[1] - first.train[0],
            validation_bars=first.validation[1] - first.validation[0],
            oos_bars=first.oos[1] - first.oos[0],
            fold_count=len(plan.folds),
            step_bars=second.train[1] - first.train[1],
            gap_bars=plan.gap_bars,
            final_holdout_start=plan.final_holdout[0],
            final_holdout_end=plan.final_holdout[1],
            max_evaluations=plan.max_evaluations,
            max_runtime_seconds=plan.max_runtime_seconds,
            minimum=plan.ranking['minimum'],
            min_trades=plan.ranking['min_trades'],
        )
        with localcontext() as context:
            context.prec = 80
            values['max_drawdown_percent'] = format(Decimal(str(plan.ranking['max_drawdown_pct'])) * 100, 'f')
        self.load(values)
        # This editor promises a uniform step. Reject arbitrary variable-step
        # imported plans rather than silently changing their declared chronology.
        if to_dict(walk_forward_plan_from_dict(self.build_payload())) != self._plan:
            raise ValidationError(ui_text('forms.from_payload.text_4'))
        return self

    def build_payload(self, backtest_config=None):
        from quantlab.__main__ import config_from_json
        from quantlab.walk_forward import build_walk_forward_plan
        from decimal import localcontext

        stored = deepcopy(self._plan or {})
        config = backtest_config if backtest_config is not None else stored.get('backtest_config')
        if config is None:
            raise ValidationError(ui_text('forms.build_payload.text_9'))
        values = {}
        for key in ('start', 'train_bars', 'validation_bars', 'oos_bars', 'step_bars'):
            values[key] = self.num(key, 0 if key == 'start' else 1, 100000, integer=True)
        saved = self.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        for key, low, high in (('fold_count', 2, 20), ('gap_bars', 0, 1000), ('max_evaluations', 1, 620 if saved else 220), ('max_runtime_seconds', 1, 7200)):
            values[key] = self.num(key, low, high, integer=True)
        with localcontext() as context:
            context.prec = 80
            cap = format(Decimal(self.num('max_drawdown_percent', 0, 100)) / 100, 'f')
        values.update(
            mode=self.fields['mode'].currentData(),
            evidence_mode=self.fields['evidence_mode'].currentData(),
            final_holdout=(self.num('final_holdout_start', 0, 100000, integer=True), self.num('final_holdout_end', 1, 100000, integer=True)),
            ranking=dict(
                metric='net_pnl', minimum=self.num('minimum', '-1e12'), min_trades=self.num('min_trades', 1, 1000000, integer=True), max_drawdown_pct=cap
            ),
        )
        for key in ('max_bars', 'process_start_method', 'worker_memory_mb', 'max_ipc_bytes', 'schema_version'):
            if key in stored:
                values[key] = stored[key]
        if not saved:
            return to_dict(build_walk_forward_plan(backtest_config=config_from_json(deepcopy(config)), **values))
        # Validate chronology independently of the still-unadmitted pool. The
        # user's exact budget is restored unchanged; no budget is auto-raised.
        budget = values['max_evaluations']
        template = to_dict(build_walk_forward_plan(backtest_config=config_from_json(deepcopy(config)), **{**values, 'max_evaluations': 1}))
        template.pop('candidate_pool', None)
        template.pop('pool_admission', None)
        template.update(pool_origin='saved_campaign_pool', max_evaluations=budget)
        return template


class PaperIntentForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('client_order_id', ui_text('forms.__init__.text_69')),
            ('strategy_hash', ui_text('forms.__init__.text_70')),
            ('contract_id', ui_text('forms.__init__.text_71')),
            ('quantity', ui_text('forms.__init__.text_72')),
            ('created_at', ui_text('forms.__init__.text_73')),
            ('limit_price', ui_text('forms.__init__.text_74')),
        ):
            self.field(key, label)
        self.field('side', ui_text('forms.__init__.text_75'), choices=[(ui_text('forms.__init__.text_76'), 'buy'), (ui_text('forms.__init__.text_77'), 'sell')])
        self.field(
            'order_type',
            ui_text('forms.__init__.text_78'),
            choices=[(ui_text('forms.__init__.text_79'), 'market'), (ui_text('forms.__init__.text_80'), 'limit')],
        )
        self.note(ui_text('forms.__init__.text_81'))

    def from_payload(self, payload):
        allowed = {'client_order_id', 'strategy_hash', 'contract_id', 'quantity', 'created_at', 'limit_price', 'side', 'order_type'}
        if set(payload) - allowed:
            raise ValidationError(ui_text('forms.from_payload.text_5'))
        for field in self.fields.values():
            if isinstance(field, (QLineEdit, DateInput)):
                field.clear()
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key: required(self.text(key), self.fields[key].accessibleName()) for key in ('client_order_id', 'strategy_hash', 'contract_id')}
        validate_contract(p['contract_id'])
        if not re.fullmatch('[0-9a-f]{64}', p['strategy_hash']):
            raise ValidationError(ui_text('forms.build_payload.text_10'))
        p.update(
            quantity=self.num('quantity', 1, 1000000, integer=True),
            created_at=utc(self.text('created_at'), ui_text('forms.build_payload.text_11')),
            side=self.fields['side'].currentData(),
            order_type=self.fields['order_type'].currentData(),
        )
        if p['order_type'] == 'limit':
            p['limit_price'] = str(self.num('limit_price', 1, 1000000000, integer=True))
        elif self.text('limit_price'):
            raise ValidationError(ui_text('forms.build_payload.text_12'))
        return p


class PaperQuoteForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('account_id', ui_text('forms.__init__.text_82')),
            ('contract_id', ui_text('forms.__init__.text_83')),
            ('price', ui_text('forms.__init__.text_84')),
            ('timestamp', ui_text('forms.__init__.text_85')),
            ('trade_date', ui_text('forms.__init__.text_86')),
            ('session_open', ui_text('forms.__init__.text_87')),
            ('session_end', ui_text('forms.__init__.text_88')),
            ('margin_per_contract', ui_text('forms.__init__.text_89')),
        ):
            self.field(key, label)
        self.note(ui_text('forms.__init__.text_90'))

    def from_payload(self, payload):
        if set(payload) != set(self.fields):
            raise ValidationError(ui_text('forms.from_payload.text_6'))
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key: required(self.text(key), self.fields[key].accessibleName()) for key in ('account_id', 'contract_id', 'trade_date')}
        validate_contract(p['contract_id'])
        validate_date(p['trade_date'], ui_text('forms.build_payload.text_13'))
        for key in ('timestamp', 'session_open', 'session_end'):
            p[key] = utc(self.text(key), self.fields[key].accessibleName())
        from quantlab.paper import _time

        if not _time(p['session_open']) <= _time(p['timestamp']) < _time(p['session_end']):
            raise ValidationError(ui_text('forms.build_payload.text_14'))
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
        self.field('account_id', ui_text('forms.__init__.text_91'))
        self.field('cash', ui_text('forms.__init__.text_92'))
        self._snapshot = {'positions': {}, 'orders': {}, 'fills': {}}
        self.records = SummaryCard()
        self.outer.addWidget(self.records)
        self.record_tables = {}
        for key, label in (
            ('positions', ui_text('forms.__init__.text_93')),
            ('orders', ui_text('forms.__init__.text_94')),
            ('fills', ui_text('forms.__init__.text_95')),
        ):
            self.note(ui_text('forms.__init__.text_96').format(label))
            table = ResultTable()
            table.setObjectName('snapshot_' + key)
            table.setMaximumHeight(160)
            self.record_tables[key] = table
            self.outer.addWidget(table)
        self.note(ui_text('forms.__init__.text_97'))
        self._show_records()

    def _show_records(self):
        self.records.set_values(
            {
                ui_text('forms._show_records.text_1'): len(self._snapshot['positions']),
                ui_text('forms._show_records.text_2'): len(self._snapshot['orders']),
                ui_text('forms._show_records.text_3'): len(self._snapshot['fills']),
            }
        )
        for key, table in self.record_tables.items():
            table.set_rows(
                [
                    {
                        ui_text('forms._show_records.text_4'): identifier,
                        **(value if isinstance(value, dict) else {ui_text('forms._show_records.text_5'): value}),
                    }
                    for identifier, value in self._snapshot[key].items()
                ]
            )

    def from_payload(self, payload):
        for key in ('positions', 'orders', 'fills'):
            if not isinstance(payload.get(key), dict):
                raise ValidationError(ui_text('forms.from_payload.text_7'))
        self._snapshot = deepcopy(payload)
        self.load(payload)
        self._show_records()
        return self

    def build_payload(self):
        p = deepcopy(self._snapshot)
        p.update(account_id=required(self.text('account_id'), ui_text('forms.build_payload.text_15')), cash=self.num('cash'))
        return p


class PaperActionForm(_Form):
    """Per-action controls; restored input never restores consent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('now', ui_text('forms.__init__.text_98'))
        self.field('order_id', ui_text('forms.__init__.text_99'))
        self.field('max_bars', ui_text('forms.__init__.text_100'), '100')
        self.confirm = QCheckBox(ui_text('forms.__init__.text_101'))
        self.confirm.setObjectName('paper_action_confirm')
        self.outer.addWidget(self.confirm)
        self.note(ui_text('forms.__init__.text_102'))

    def from_payload(self, payload):
        self.load(payload)
        self.clear_confirmation()
        return self

    def clear_confirmation(self):
        self.confirm.setChecked(False)

    def build_payload(self, action):
        if action not in ('snapshot', 'reconcile', 'submit', 'replay', 'cancel', 'kill'):
            raise ValidationError(ui_text('forms.build_payload.text_16'))
        if action in ('snapshot', 'kill'):
            return {}
        if action == 'cancel':
            return {
                'now': utc(self.text('now'), ui_text('forms.build_payload.text_17')),
                'order_id': required(self.text('order_id'), ui_text('forms.build_payload.text_18')),
            }
        if not self.confirm.isChecked():
            raise ValidationError(ui_text('forms.build_payload.text_19'))
        p = {'reconcile_confirmed': True}
        if action == 'submit':
            p['now'] = utc(self.text('now'), ui_text('forms.build_payload.text_20'))
        if action == 'replay':
            p['max_bars'] = self.num('max_bars', 1, 1000, integer=True)
        return p


class _Rows(QWidget):
    """Plain typed table for bounded policy rows, with keyboard-accessible buttons."""

    def __init__(self, name, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self._original = []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(columns))
        self.table.setObjectName(name)
        self.table.setHorizontalHeaderLabels([label for _, label in columns])
        layout.addWidget(self.table)
        install_date_columns(self.table, columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.resizeColumnsToContents()
        for index, (_, label) in enumerate(columns):
            self.table.horizontalHeaderItem(index).setToolTip(label)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        add = QPushButton(ui_text('forms.__init__.text_103'))
        add.setObjectName(name + '_add')
        add.clicked.connect(self.add_row)
        remove = QPushButton(ui_text('forms.__init__.text_104'))
        remove.setObjectName(name + '_remove')
        remove.setProperty('role', 'danger')
        remove.clicked.connect(self.remove_row)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()

    def add_row(self):
        self.table.insertRow(self.table.rowCount())
        self._original.append({})
        open_date_editors(self.table, self.columns, self.table.rowCount() - 1)

    def remove_row(self):
        row = self.table.currentRow()
        if (
            row >= 0
            and QMessageBox.question(
                self,
                ui_text('forms.remove_row.text_1'),
                ui_text('forms.remove_row.text_2'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.table.removeRow(row)
            self._original.pop(row)

    def load(self, rows):
        self.table.setRowCount(len(rows))
        self._original = deepcopy(rows)
        for i, row in enumerate(rows):
            for j, (key, _) in enumerate(self.columns):
                self.table.setItem(i, j, QTableWidgetItem(str(row.get(key, ''))))
            open_date_editors(self.table, self.columns, i)

    def values(self):
        rows = deepcopy(self._original)
        for i, row in enumerate(rows):
            for j, (key, label) in enumerate(self.columns):
                item = self.table.item(i, j)
                row[key] = required(item.text() if item else '', label)
        return rows


class PaperPolicyForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('contract_id', ui_text('forms.__init__.text_105'))
        self.note(ui_text('forms.__init__.text_106'))
        self.sessions = _Rows(
            'risk_sessions',
            [
                ('open', ui_text('forms.__init__.text_107')),
                ('end', ui_text('forms.__init__.text_108')),
                ('trade_date', ui_text('forms.__init__.text_109')),
                ('source', ui_text('forms.__init__.text_110')),
                ('session', ui_text('forms.__init__.text_111')),
            ],
        )
        self.outer.addWidget(self.sessions)
        self.margins = _Rows(
            'margin_schedule',
            [
                ('effective_from', ui_text('forms.__init__.text_112')),
                ('margin_per_contract', ui_text('forms.__init__.text_113')),
                ('version', ui_text('forms.__init__.text_114')),
            ],
        )
        self.outer.addWidget(self.margins)

    def from_payload(self, payload):
        if set(payload) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
            raise ValidationError(ui_text('forms.from_payload.text_8'))
        self.load(payload)
        self.sessions.load(payload['risk_sessions'])
        self.margins.load(payload['margin_schedule'])
        return self

    def build_payload(self):
        contract = self.text('contract_id')
        validate_contract(contract)
        sessions, margins = self.sessions.values(), self.margins.values()
        if not sessions or not margins:
            raise ValidationError(ui_text('forms.build_payload.text_21'))
        for row in sessions:
            utc(row['open'], ui_text('forms.build_payload.text_22'))
            utc(row['end'], ui_text('forms.build_payload.text_23'))
            validate_date(row['trade_date'], ui_text('forms.build_payload.text_24'))
        for row in margins:
            row['margin_per_contract'] = number(row['margin_per_contract'], ui_text('forms.build_payload.text_25'), '0.000000000001')
        # Invoke the existing pure policy validator without opening a journal.
        from quantlab.paper import PaperBroker
        from quantlab.core import Instrument

        broker = object.__new__(PaperBroker)
        broker.instrument = Instrument(contract)
        broker._risk_sessions = sessions
        broker._margin_schedule = margins
        broker._validate_policy()
        return dict(contract_id=contract, risk_sessions=sessions, margin_schedule=margins)


from desktop_presentation import display_value, display_number, STATUS_LABELS


RESULT_LABELS = {
    'net_pnl': ui_text('forms.labels.text_16'),
    'gross_pnl': ui_text('forms.labels.text_17'),
    'trade_count': ui_text('forms.labels.text_18'),
    'closed_trades': ui_text('forms.labels.text_19'),
    'fill_count': ui_text('forms.labels.text_20'),
    'max_drawdown': ui_text('forms.labels.text_21'),
    'max_drawdown_pct': ui_text('forms.labels.text_22'),
    'win_rate': ui_text('forms.labels.text_23'),
    'profit_factor': ui_text('forms.labels.text_24'),
    'source_type': ui_text('forms.labels.text_25'),
    'strategy_hash': ui_text('forms.labels.text_26'),
    'result_hash': ui_text('forms.labels.text_27'),
    'warnings': ui_text('forms.labels.text_28'),
    'equity_samples': ui_text('forms.labels.text_29'),
    'status': ui_text('forms.labels.text_30'),
    'family': ui_text('forms.labels.text_31'),
    'sequence': ui_text('forms.labels.text_32'),
    'strategy_id': ui_text('forms.labels.text_33'),
    'account_id': ui_text('forms.labels.text_34'),
    'cash': ui_text('forms.labels.text_35'),
    'reconciliation_required': ui_text('forms.labels.text_36'),
    'kill_switch': ui_text('forms.labels.text_37'),
    'initial_cash': ui_text('forms.labels.text_38'),
    'final_equity': ui_text('forms.labels.text_39'),
    'realized_gross_pnl': ui_text('forms.labels.text_40'),
    'unrealized_pnl': ui_text('forms.labels.text_41'),
    'total_costs': ui_text('forms.labels.text_42'),
    'slippage_cost': ui_text('forms.labels.text_43'),
    'return': ui_text('forms.labels.text_44'),
    'closed_lots': ui_text('forms.labels.text_45'),
    'open_position': ui_text('forms.labels.text_46'),
    'sharpe': ui_text('forms.labels.text_47'),
    'sharpe_reason': ui_text('forms.labels.text_48'),
    'win_rate_reason': ui_text('forms.labels.text_49'),
    'annualization': ui_text('forms.labels.text_50'),
    'profit_factor_reason': ui_text('forms.labels.text_51'),
    'profit_factor_basis': ui_text('forms.labels.text_52'),
    'sharpe_observations': ui_text('forms.labels.text_53'),
    'sharpe_note': ui_text('forms.labels.text_54'),
    'sharpe_sample_count': ui_text('forms.labels.text_55'),
    'periods_per_year': ui_text('forms.labels.text_56'),
    'annual_risk_free_rate': ui_text('forms.labels.text_57'),
    'return_frequency': ui_text('forms.labels.text_58'),
    'first_return': ui_text('forms.labels.text_59'),
    'missing_dates': ui_text('forms.labels.text_60'),
    'standard_deviation': ui_text('forms.labels.text_61'),
    'minimum_observations': ui_text('forms.labels.text_62'),
    'created_at': ui_text('forms.labels.text_63'),
    'side': ui_text('forms.labels.text_64'),
    'quantity': ui_text('forms.labels.text_65'),
    'price': ui_text('forms.labels.text_66'),
    'order_type': ui_text('forms.labels.text_67'),
    'filled_quantity': ui_text('forms.labels.text_68'),
    'commission': ui_text('forms.labels.text_69'),
    'tax': ui_text('forms.labels.text_70'),
}


def readable(value, key=""):
    if value is None:
        return ui_text('forms.readable.text_1')
    if isinstance(value, bool):
        return ui_text('forms.readable.text_2') if value else ui_text('forms.readable.text_3')
    if isinstance(value, dict):
        return ui_text('forms.readable.text_4').join(ui_text('forms.readable.text_5').format(RESULT_LABELS.get(k, k), readable(v, k)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ui_text('forms.readable.text_6').join(readable(v) for v in value) or ui_text('forms.readable.text_7')
    return display_value(value, key)


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('result_table')
        self.setAccessibleName(ui_text('forms.__init__.text_115'))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

    def set_rows(self, rows, columns=None):
        columns = columns or list(dict.fromkeys(key for row in rows for key in row))
        self.setSortingEnabled(False)
        self.clear()
        self.setColumnCount(len(columns))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels([RESULT_LABELS.get(key, key) for key in columns])
        for i, row in enumerate(rows):
            for j, key in enumerate(columns):
                text = readable(row.get(key), key)
                item = QTableWidgetItem(text)
                item.setToolTip(str(row.get(key)))
                self.setItem(i, j, item)
        self.resizeColumnsToContents()
        for j in range(len(columns)):
            self.setColumnWidth(j, min(self.columnWidth(j), 340))
        # Stringified decimal metrics deliberately remain in backend-provided order.


class SummaryCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.label.setObjectName('summary_card')
        layout.addWidget(self.label)

    def set_values(self, values):
        self.label.setText('\n'.join(ui_text('forms.set_values.text_1').format(RESULT_LABELS.get(k, k), readable(v, k)) for k, v in values.items()))


# These adapters only present verified report fields. Raw records remain in the
# host's existing advanced result_detail; no metric or report identity is changed.
_REPORT_TEXT = {
    'no closed lots': ui_text('forms.labels.text_71'),
    'no losing closed lots': ui_text('forms.labels.text_72'),
    'closed FIFO lot net PnL after allocated entry/exit costs; open lots excluded': ui_text('forms.labels.text_73'),
    'missing or nonpositive daily equity; no observations discarded': ui_text('forms.labels.text_74'),
    'at least 2 daily returns required for sample standard deviation': ui_text('forms.labels.text_75'),
    'zero daily-return sample variance': ui_text('forms.labels.text_76'),
    'between last supplied equity per exchange trading date; gaps may span multiple days': ui_text('forms.labels.text_77'),
    'initial cash to first supplied trading-date equity': ui_text('forms.labels.text_78'),
    'supplied trading dates only; no imputation': ui_text('forms.labels.text_79'),
    'sample (ddof=1)': ui_text('forms.labels.text_80'),
    'Descriptive only. Two returns is a mathematical minimum, not evidence of reliability; short samples do not establish strategy quality. The 252-period convention is assumed, not a validated annual trading calendar; gaps may span multiple days.': ui_text(
        'forms.labels.text_81'
    ),
}


def _report_text(value):
    if value is None:
        return ui_text('forms._report_text.text_1')
    return _REPORT_TEXT.get(value, ui_text('forms._report_text.text_2')) if isinstance(value, str) else ui_text('forms._report_text.text_3')


def _report_number(value, key=""):
    if value is None:
        return ui_text('forms._report_number.text_1')
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return ui_text('forms._report_number.text_2')
    if len(str(value)) > 128:
        return ui_text('forms._report_number.text_3')
    try:
        if not Decimal(str(value)).is_finite():
            return ui_text('forms._report_number.text_4')
    except (InvalidOperation, ValueError):
        return ui_text('forms._report_number.text_5')
    return display_number(value, key)


def backtest_summary_text(values):
    """Bounded Traditional Chinese presentation, preserving exact scalar values."""

    def metric(key):
        value = values.get(key)
        if value is None:
            return ui_text('forms.metric.text_1') if key in values and key in ('profit_factor', 'sharpe', 'win_rate') else ui_text('forms.metric.text_2')
        return _report_number(value, key)

    def fields(*keys):
        return ui_text('forms.fields.text_1').join(ui_text('forms.fields.text_2').format(RESULT_LABELS[key], metric(key)) for key in keys)

    def reason(key, metric_key):
        value = values.get(key)
        metric_value = values.get(metric_key)
        if metric_value is not None and _report_number(metric_value) == ui_text('forms.reason.text_1'):
            text = ui_text('forms.reason.text_2')
        else:
            text = ui_text('forms.reason.text_3') if value is None and metric_value is not None else _report_text(value)
        return ui_text('forms.reason.text_4').format(RESULT_LABELS[key], text)

    lines = [
        fields('net_pnl', 'return'),
        fields('initial_cash', 'final_equity'),
        fields('max_drawdown', 'max_drawdown_pct'),
        fields('total_costs', 'slippage_cost'),
        fields('realized_gross_pnl', 'unrealized_pnl'),
        fields('fill_count', 'closed_lots', 'open_position'),
        fields('trade_count', 'win_rate'),
        reason('win_rate_reason', 'win_rate'),
        '',
        fields('profit_factor'),
        reason('profit_factor_reason', 'profit_factor'),
        ui_text('forms.backtest_summary_text.text_1').format(_report_text(values.get('profit_factor_basis'))),
        '',
        fields('sharpe'),
        reason('sharpe_reason', 'sharpe'),
        fields('sharpe_observations', 'sharpe_sample_count'),
    ]
    assumptions = values.get('annualization')
    if isinstance(assumptions, dict):
        for keys in (
            ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations'),
            ('return_frequency',),
            ('first_return',),
            ('missing_dates', 'standard_deviation'),
        ):
            lines.append(
                ui_text('forms.backtest_summary_text.text_2').join(
                    ui_text('forms.backtest_summary_text.text_3').format(
                        RESULT_LABELS[key],
                        _report_number(assumptions.get(key), key)
                        if key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                        else _report_text(assumptions.get(key)),
                    )
                    for key in keys
                )
            )
    else:
        lines.append(ui_text('forms.backtest_summary_text.text_4'))
    lines.extend((ui_text('forms.backtest_summary_text.text_5').format(_report_text(values.get('sharpe_note'))), ui_text('forms.backtest_summary_text.text_6')))
    return '\n'.join(lines)


class BacktestSummaryCard(SummaryCard):
    """A report-only view; other summary cards retain their original contract."""

    def set_values(self, values):
        self.label.setText(backtest_summary_text(values))


_FILL_REASONS = {
    'target_open': ui_text('forms.labels.text_82'),
    'target_close': ui_text('forms.labels.text_83'),
    'gap_stop': ui_text('forms.labels.text_84'),
    'gap_target': ui_text('forms.labels.text_85'),
    'stop': ui_text('forms.labels.text_86'),
    'target': ui_text('forms.labels.text_87'),
    'maintenance_liquidation': ui_text('forms.labels.text_88'),
    'roll_close': ui_text('forms.labels.text_89'),
    'roll_open': ui_text('forms.labels.text_90'),
    'final_settlement': ui_text('forms.labels.text_91'),
}


class BacktestFillsTable(ResultTable):
    """Readable fills first; exact IDs remain in cell tooltips and diagnostics."""

    _columns = ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax', 'reason')
    _labels = (
        ui_text('forms.labels.text_92'),
        ui_text('forms.labels.text_93'),
        ui_text('forms.labels.text_94'),
        ui_text('forms.labels.text_95'),
        ui_text('forms.labels.text_96'),
        ui_text('forms.labels.text_97'),
        ui_text('forms.labels.text_98'),
        ui_text('forms.labels.text_99'),
    )

    def set_rows(self, rows, columns=None):
        from datetime import datetime, timezone

        display = []
        for row in rows:
            shown = {key: row.get(key) for key in self._columns}
            side, reason = row.get('side'), row.get('reason')
            shown['side'] = display_value(side, 'side') if side in ('buy', 'sell') else ui_text('forms.set_rows.text_1')
            shown['reason'] = (
                _FILL_REASONS.get(reason, ui_text('forms.set_rows.text_2'))
                if isinstance(reason, str) and reason
                else ui_text('forms.set_rows.text_3')
                if reason is None or reason == ''
                else ui_text('forms.set_rows.text_4')
            )
            timestamp = row.get('timestamp')
            try:
                parsed = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError('timezone required')
                shown['timestamp'] = parsed.astimezone(timezone.utc).isoformat(sep=' ', timespec='seconds').removesuffix('+00:00')
            except (ValueError, TypeError, AttributeError):
                shown['timestamp'] = ui_text('forms.set_rows.text_5')
            display.append(shown)
        super().set_rows(display, self._columns)
        self.setHorizontalHeaderLabels(self._labels)
        for index, row in enumerate(rows):
            detail = ui_text('forms.set_rows.text_8').format(
                str(row.get('fill_id', ui_text('forms.set_rows.text_6'))), str(row.get('order_id', ui_text('forms.set_rows.text_7')))
            )
            for column in range(self.columnCount()):
                item = self.item(index, column)
                item.setToolTip(str(row.get(self._columns[column], ui_text('forms.set_rows.text_9'))) + '\n' + detail)
        self.resizeColumnsToContents()
        for column in range(self.columnCount()):
            self.setColumnWidth(column, min(self.columnWidth(column), 340))


_CANDIDATE_EVALUATION_LABELS = STATUS_LABELS


def candidate_summary_text(values):
    """Bounded view of saved split records; never recalculate qualification."""

    def eligibility(value):
        return (
            ui_text('forms.eligibility.text_1')
            if value is True
            else ui_text('forms.eligibility.text_2')
            if value is False
            else ui_text('forms.eligibility.text_3')
        )

    def metric(metrics, key):
        value = metrics.get(key)
        if value is None:
            return ui_text('forms.metric.text_3') if key in metrics and key in ('profit_factor', 'sharpe') else ui_text('forms.metric.text_4')
        return _report_number(value, key)

    def reason(metrics, key):
        value, explanation = metrics.get(key), metrics.get(key + '_reason')
        if value is not None and _report_number(value) == ui_text('forms.reason.text_5'):
            return ui_text('forms.reason.text_6')
        return ui_text('forms.reason.text_7') if explanation is None and value is not None else _report_text(explanation)

    name = values.get(ui_text('forms.candidate_summary_text.text_1'))
    if not isinstance(name, str):
        name = ui_text('forms.candidate_summary_text.text_2')
    elif re.fullmatch('[0-9a-fA-F]{64}', name):
        name = ui_text('forms.candidate_summary_text.text_3').format(name[:12])
    else:
        name = ' '.join(name.split())[:80] + (ui_text('forms.candidate_summary_text.text_4') if len(name) > 80 else '')
    lines = [
        ui_text('forms.candidate_summary_text.text_5').format(name),
        ui_text('forms.candidate_summary_text.text_7').format(eligibility(values.get(ui_text('forms.candidate_summary_text.text_6')))),
        ui_text('forms.candidate_summary_text.text_8'),
    ]
    evaluations = values.get(ui_text('forms.candidate_summary_text.text_9'))
    evaluations = evaluations if isinstance(evaluations, dict) else {}
    for split, title in (('oos', ui_text('forms.candidate_summary_text.text_10')), ('holdout', ui_text('forms.candidate_summary_text.text_11'))):
        saved = evaluations.get(split)
        saved = saved if isinstance(saved, dict) else {}
        row = saved.get('evaluation')
        row = row if isinstance(row, dict) else {}
        state = row.get('status')
        status = (
            ui_text('forms.candidate_summary_text.text_12')
            if not row
            else ui_text('forms.candidate_summary_text.text_13')
            if state is None
            else _CANDIDATE_EVALUATION_LABELS.get(state, ui_text('forms.candidate_summary_text.text_14'))
            if isinstance(state, str)
            else ui_text('forms.candidate_summary_text.text_15')
        )
        metrics = row.get('metrics')
        metrics = metrics if isinstance(metrics, dict) else {}
        headline = ['net_pnl'] + (['max_drawdown'] if 'max_drawdown' in metrics else []) + ['max_drawdown_pct']
        headline.append('closed_trades' if 'trade_count' not in metrics and 'closed_trades' in metrics else 'trade_count')
        lines.extend(
            (
                '',
                ui_text('forms.candidate_summary_text.text_16').format(title, status, eligibility(saved.get("qualified"))),
                ui_text('forms.candidate_summary_text.text_17').join(
                    ui_text('forms.candidate_summary_text.text_18').format(RESULT_LABELS[key], metric(metrics, key)) for key in headline
                ),
            )
        )
        for key in ('profit_factor', 'sharpe'):
            lines.append(ui_text('forms.candidate_summary_text.text_19').format(RESULT_LABELS[key], metric(metrics, key)))
            if key in metrics or key + '_reason' in metrics:
                lines.append(ui_text('forms.candidate_summary_text.text_20').format(RESULT_LABELS[key + '_reason'], reason(metrics, key)))
            if key == 'profit_factor' and key in metrics:
                lines.append(ui_text('forms.candidate_summary_text.text_21').format(_report_text(metrics.get('profit_factor_basis'))))
        if 'sharpe' in metrics:
            lines.append(
                ui_text('forms.candidate_summary_text.text_22').join(
                    ui_text('forms.candidate_summary_text.text_23').format(RESULT_LABELS[key], _report_number(metrics.get(key)))
                    for key in ('sharpe_observations', 'sharpe_sample_count')
                )
            )
            assumptions = metrics.get('annualization')
            if isinstance(assumptions, dict):
                lines.append(
                    ui_text('forms.candidate_summary_text.text_24').join(
                        ui_text('forms.candidate_summary_text.text_25').format(RESULT_LABELS[key], _report_number(assumptions.get(key), key))
                        for key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                    )
                )
                lines.append(
                    ui_text('forms.candidate_summary_text.text_26').join(
                        ui_text('forms.candidate_summary_text.text_27').format(RESULT_LABELS[key], _report_text(assumptions.get(key)))
                        for key in ('return_frequency', 'first_return', 'missing_dates', 'standard_deviation')
                    )
                )
            else:
                lines.append(ui_text('forms.candidate_summary_text.text_28'))
            lines.append(ui_text('forms.candidate_summary_text.text_29').format(_report_text(metrics.get('sharpe_note'))))
    lines.append(ui_text('forms.candidate_summary_text.text_30'))
    return '\n'.join(lines)


class CandidateSummaryCard(SummaryCard):
    """Only the generated-candidate pane; qualification stays host-owned."""

    def set_values(self, values):
        self.label.setText(candidate_summary_text(values))
