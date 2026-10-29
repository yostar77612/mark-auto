"""Small, data-only Traditional Chinese Qt forms for the existing worker API.

Forms never start work or connect to brokers. ``from_payload`` loads a detached
copy; ``build_payload`` validates without changing external state. Embed these
widgets in the desktop page's QScrollArea. Exact decimal strings avoid float or
QDoubleSpinBox rounding. Backend validation remains authoritative.
"""

from desktop_app.strings.catalog import ui_text
from quantlab.ui_preferences import family_parameters
import desktop_app.components.privacy as _privacy
from desktop_app.shell.theme import FINANCIAL_FIELDS, set_financial_item
from desktop_app.components.timeinput import DateInput, DATE_KEYS, TIME_KEYS, install_date_columns, open_date_editors
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
            ui_text('forms.labels.trend'),
            ui_text('forms.labels.mean_reversion'),
            ui_text('forms.labels.breakout'),
            ui_text('forms.labels.momentum'),
            ui_text('forms.labels.volatility'),
        ),
    )
)
PARAM_LABELS = {
    'fast': ui_text('forms.labels.fast_bars'),
    'slow': ui_text('forms.labels.slow_bars'),
    'lookback': ui_text('forms.labels.lookback_bars'),
    'entry_bps': ui_text('forms.labels.entry_bps'),
    'threshold_bps': ui_text('forms.labels.threshold_bps'),
    'max_holding_bars': ui_text('forms.labels.max_holding_bars'),
    'max_range_bps': ui_text('forms.labels.max_range_bps'),
    'quantity': ui_text('forms.labels.optional_quantity'),
    'stop_ticks': ui_text('forms.labels.optional_stop'),
    'target_ticks': ui_text('forms.labels.optional_target'),
}


def number(text, label, minimum=0, maximum='1e12', *, integer=False, optional=False):
    """Strict bounded decimal input; never silently clamp, round, or default."""
    text = str(text).strip()
    if not text and optional:
        return None
    if len(text) > 128 or not text:
        raise ValidationError(ui_text('forms.number.valid_number_required').format(label))
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
            ui_text('forms.number.range_prefix').format(label, minimum, maximum)
            + (ui_text('forms.number.integer') if integer else ui_text('forms.number.finite_number'))
        ) from None
    return int(value) if integer else format(value, 'f')


def required(text, label):
    text = text.strip()
    if not text or len(text) > 256:
        raise ValidationError(ui_text('forms.required.bounded_length_required').format(label))
    return text


def utc(text, label):
    from quantlab.paper import _time

    value = required(text, label)
    try:
        _time(value, label)
    except ValidationError:
        raise ValidationError(ui_text('forms.utc.utc_required').format(label)) from None
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
                    raise ValidationError(ui_text('forms.load.unsupported_option').format(field.accessibleName()))
                field.setCurrentIndex(index)
            else:
                field.setText('' if value is None else str(value))
        return self


class StrategyForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.family = self.field('family', ui_text('forms.init.strategy_family'), choices=[(FAMILY_LABELS[f], f) for f in FAMILIES])
        self.family.setToolTip(ui_text('tooltip.family'))
        self.parameter_form = QFormLayout()
        self.outer.addLayout(self.parameter_form)
        self._spec = None
        self._family_preferences = {}
        self.family.currentIndexChanged.connect(self._family_changed)
        self._family_changed()
        self.note(ui_text('forms.init.bounded_families_hint'))

    def _family_changed(self):
        self._remember_parameters()
        while self.parameter_form.rowCount():
            self.parameter_form.removeRow(0)
        self.fields = {'family': self.family}
        family = self.family.currentData()
        self._spec = {'strategy_id': f'{family}-v1', 'family': family, 'parameters': dict(DEFAULTS[family]), 'rules': {}, 'schema_version': 1}
        tooltips = {
            'fast': ui_text('tooltip.fast'),
            'slow': ui_text('tooltip.slow'),
            'lookback': ui_text('tooltip.lookback'),
            'entry_bps': ui_text('tooltip.entry_bps'),
            'threshold_bps': ui_text('tooltip.threshold_bps'),
            'max_holding_bars': ui_text('tooltip.max_holding_bars'),
            'max_range_bps': ui_text('tooltip.max_range_bps'),
            'quantity': ui_text('tooltip.quantity'),
            'stop_ticks': ui_text('tooltip.stop_ticks'),
            'target_ticks': ui_text('tooltip.target_ticks'),
        }
        for key, value in {**DEFAULTS[family], 'quantity': '', 'stop_ticks': '', 'target_ticks': ''}.items():
            widget = QLineEdit(str(value))
            widget.setObjectName(key)
            widget.setAccessibleName(PARAM_LABELS[key])
            widget.setToolTip(tooltips[key])
            label = QLabel(PARAM_LABELS[key])
            label.setBuddy(widget)
            self.parameter_form.addRow(label, widget)
            self.fields[key] = widget

        self._restore_parameters()

    def _remember_parameters(self):
        if self._spec is None:
            return
        family = self._spec['family']
        try:
            # Validate against the family owning the currently mounted fields.
            selected = self.family.currentData()
            self.family.blockSignals(True)
            self.family.setCurrentIndex(self.family.findData(family))
            payload = self.build_payload()
            self._family_preferences[family] = {key: payload['parameters'][key] for key in DEFAULTS[family]}
        except ValidationError:
            self._family_preferences.pop(family, None)
        finally:
            self.family.setCurrentIndex(self.family.findData(selected))
            self.family.blockSignals(False)

    def _restore_parameters(self):
        family = self.family.currentData()
        parameters = self._family_preferences.get(family)
        if parameters is None:
            return
        self.load(parameters)
        try:
            self.build_payload()
        except (ValidationError, TypeError, ValueError, OverflowError):
            self._family_preferences.pop(family, None)
            self.load(DEFAULTS[family])

    def preference_parameters(self):
        self._remember_parameters()
        return family_parameters(self._family_preferences, DEFAULTS)

    def restore_preference_parameters(self, value):
        self._family_preferences = {}
        for family, parameters in family_parameters(value, DEFAULTS).items():
            try:
                payload = self._validated_payload(family, parameters, f'{family}-v1', 1)
            except (ValidationError, TypeError, ValueError, OverflowError):
                continue
            self._family_preferences[family] = payload['parameters']
        self._restore_parameters()

    def from_payload(self, payload):
        spec = StrategySpec(**deepcopy(payload))
        validate_strategy(spec)
        if spec.rules:
            raise ValidationError(ui_text('forms.from_payload.readonly_dsl_required'))
        self.family.setCurrentIndex(self.family.findData(spec.family))
        self._family_changed()
        self._spec = to_dict(spec)
        self.load(spec.parameters)
        return self

    @staticmethod
    def _validated_payload(family, values, strategy_id, schema_version):
        p = {}
        for key, text in values.items():
            optional = key in ('quantity', 'stop_ticks', 'target_ticks')
            if optional and not str(text).strip():
                continue
            p[key] = number(text, PARAM_LABELS[key], integer=not key.endswith('_bps'))
        spec = StrategySpec(strategy_id, family, p, {}, schema_version)
        validate_strategy(spec)
        return to_dict(spec)

    def build_payload(self):
        return self._validated_payload(
            self.family.currentData(),
            {key: self.text(key) for key in self.fields if key != 'family'},
            self._spec['strategy_id'],
            self._spec['schema_version'],
        )


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
        from quantlab.__main__ import config_from_json

        config_from_json(config)
        start, end = self.text('start_date'), self.text('end_date')
        for value in (start, end):
            if value:
                validate_date(value, ui_text('forms.build_payload.trading_day'))
        if start and end and start > end:
            raise ValidationError(ui_text('forms.build_payload.reversed_dates'))
        return dict(config=config, start_date=start, end_date=end)


class CampaignForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self.note(ui_text('forms.init.split_hint'))
        for split, label in (
            ('train', ui_text('forms.init.training')),
            ('validation', ui_text('forms.init.validation')),
            ('oos', ui_text('forms.init.out_of_sample')),
            ('holdout', ui_text('forms.init.final_holdout')),
        ):
            self.field(split + '_start', ui_text('forms.init.range_start').format(label))
            self.field(split + '_end', ui_text('forms.init.range_end').format(label))
        for key, label, value in (
            ('max_trials', ui_text('forms.init.max_attempts'), 15),
            ('max_improvements', ui_text('forms.init.max_refinements'), 2),
            ('seed', ui_text('forms.init.research_seed'), 0),
            ('max_runtime_seconds', ui_text('forms.init.research_seconds'), 300),
            ('max_bars', ui_text('forms.init.max_bars'), 100000),
            ('purge_bars', ui_text('forms.init.purge_bars'), 0),
            ('minimum', ui_text('forms.init.minimum_pnl'), 0),
            ('min_trades', ui_text('forms.init.minimum_fills'), 0),
        ):
            self.field(key, label, value)
        self.families = {}
        for family in FAMILIES:
            box = QCheckBox(FAMILY_LABELS[family])
            box.setObjectName('campaign_' + family)
            box.setChecked(True)
            box.setAccessibleName(ui_text('forms.init.research_family').format(FAMILY_LABELS[family]))
            self.outer.addWidget(box)
            self.families[family] = box

    def from_payload(self, payload):
        families = payload.get('families')
        if not isinstance(families, list) or not families or len(set(families)) != len(families) or any(f not in FAMILIES for f in families):
            raise ValidationError(ui_text('forms.from_payload.invalid_research_families'))
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
            raise ValidationError(ui_text('forms.build_payload.data_cost_required'))
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
                raise ValidationError(ui_text('forms.build_payload.invalid_splits'))
            config['splits'][split] = [start, end]
            previous = end
        config['families'] = [f for f, b in self.families.items() if b.isChecked()]
        if not config['families']:
            raise ValidationError(ui_text('forms.build_payload.family_required'))
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
            ui_text('forms.init.pool_source'),
            choices=[(ui_text('forms.init.builtin_pool'), 'exact_builtin_pool'), (ui_text('forms.init.saved_pool'), 'saved_campaign_pool')],
        )
        self.field(
            'mode',
            ui_text('forms.init.training_window'),
            choices=[(ui_text('forms.init.rolling_window'), 'rolling'), (ui_text('forms.init.anchored_window'), 'expanding')],
        )
        self.field(
            'evidence_mode',
            ui_text('forms.init.evidence_mode'),
            choices=[(ui_text('forms.init.synthetic_evidence'), 'synthetic_validation'), (ui_text('forms.init.historical_replay'), 'historical_replay')],
        )
        for key, label, value in (
            ('start', ui_text('forms.init.first_start'), 0),
            ('train_bars', ui_text('forms.init.training_bars'), 240),
            ('validation_bars', ui_text('forms.init.validation_bars'), 120),
            ('oos_bars', ui_text('forms.init.forward_bars'), 120),
            ('fold_count', ui_text('forms.init.fold_count'), 3),
            ('step_bars', ui_text('forms.init.step_bars'), 120),
            ('gap_bars', ui_text('forms.init.gap_bars'), 0),
            ('final_holdout_start', ui_text('forms.init.holdout_start'), 720),
            ('final_holdout_end', ui_text('forms.init.holdout_end'), 960),
            ('max_evaluations', ui_text('forms.init.evaluation_budget'), 33),
            ('max_runtime_seconds', ui_text('forms.init.experiment_seconds'), 300),
            ('minimum', ui_text('forms.init.validation_pnl'), '0'),
            ('min_trades', ui_text('forms.init.validation_closed_lots'), 1),
            ('max_drawdown_percent', ui_text('forms.init.validation_drawdown'), '10.00'),
        ):
            self.field(key, label, value)
        self._plan = None
        self.fields['pool_origin'].currentIndexChanged.connect(self._pool_origin_changed)
        self._pool_origin_changed()
        self.note(ui_text('forms.init.pool_selection_hint'))
        self.note(ui_text('forms.init.shared_policy_hint'))

    def _pool_origin_changed(self):
        saved = self.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        cap = 620 if saved else 220
        label = ui_text('forms.pool_origin_changed.evaluation_budget_limit').format(cap)
        self.form.labelForField(self.fields['max_evaluations']).setText(label)
        self.fields['max_evaluations'].setAccessibleName(label)

    def defaults_for_bars(self, count):
        if type(count) is not int or count < 8:
            raise ValidationError(ui_text('forms.defaults_for_bars.minimum_bars'))
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
            raise ValidationError(ui_text('forms.from_payload.saved_pool_picker_required'))
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
            raise ValidationError(ui_text('forms.from_payload.fixed_step_only'))
        return self

    def build_payload(self, backtest_config=None):
        from quantlab.__main__ import config_from_json
        from quantlab.walk_forward import build_walk_forward_plan
        from decimal import localcontext

        stored = deepcopy(self._plan or {})
        config = backtest_config if backtest_config is not None else stored.get('backtest_config')
        if config is None:
            raise ValidationError(ui_text('forms.build_payload.shared_cost_required'))
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
        add = QPushButton(ui_text('forms.init.add_row'))
        add.setObjectName(name + '_add')
        add.clicked.connect(self.add_row)
        remove = QPushButton(ui_text('forms.init.remove_row'))
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
                ui_text('forms.remove_row.confirm_title'),
                ui_text('forms.remove_row.confirm_question'),
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


from desktop_app.components.formatting import display_value, display_number, STATUS_LABELS


RESULT_LABELS = {
    'net_pnl': ui_text('forms.labels.net_pnl'),
    'gross_pnl': ui_text('forms.labels.gross_pnl'),
    'trade_count': ui_text('forms.labels.trade_count'),
    'closed_trades': ui_text('forms.labels.closed_trades'),
    'fill_count': ui_text('forms.labels.fill_count'),
    'max_drawdown': ui_text('forms.labels.max_drawdown'),
    'max_drawdown_pct': ui_text('forms.labels.max_drawdown_percent'),
    'win_rate': ui_text('forms.labels.win_rate'),
    'profit_factor': ui_text('forms.labels.profit_factor'),
    'source_type': ui_text('forms.labels.data_source'),
    'strategy_hash': ui_text('forms.labels.strategy_hash'),
    'result_hash': ui_text('forms.labels.result_hash'),
    'warnings': ui_text('forms.labels.warnings'),
    'equity_samples': ui_text('forms.labels.equity_points'),
    'status': ui_text('forms.labels.status'),
    'family': ui_text('forms.labels.strategy_family'),
    'sequence': ui_text('forms.labels.candidate_version'),
    'strategy_id': ui_text('forms.labels.strategy_id'),
    'account_id': ui_text('forms.labels.account'),
    'cash': ui_text('forms.labels.cash'),
    'reconciliation_required': ui_text('forms.labels.reconciliation_required'),
    'kill_switch': ui_text('forms.labels.stopped'),
    'initial_cash': ui_text('forms.labels.initial_cash'),
    'final_equity': ui_text('forms.labels.ending_equity'),
    'realized_gross_pnl': ui_text('forms.labels.realized_gross_pnl'),
    'unrealized_pnl': ui_text('forms.labels.unrealized_pnl'),
    'total_costs': ui_text('forms.labels.total_cost'),
    'slippage_cost': ui_text('forms.labels.slippage_cost'),
    'return': ui_text('forms.labels.return_percent'),
    'closed_lots': ui_text('forms.labels.closed_lots'),
    'open_position': ui_text('forms.labels.open_quantity'),
    'sharpe': ui_text('forms.labels.sharpe'),
    'sharpe_reason': ui_text('forms.labels.sharpe_reason'),
    'win_rate_reason': ui_text('forms.labels.win_rate_basis'),
    'annualization': ui_text('forms.labels.annualization'),
    'profit_factor_reason': ui_text('forms.labels.profit_factor_reason'),
    'profit_factor_basis': ui_text('forms.labels.profit_factor_basis'),
    'sharpe_observations': ui_text('forms.labels.sharpe_observations'),
    'sharpe_note': ui_text('forms.labels.sharpe_limitations'),
    'sharpe_sample_count': ui_text('forms.labels.valid_return_periods'),
    'periods_per_year': ui_text('forms.labels.annual_periods'),
    'annual_risk_free_rate': ui_text('forms.labels.risk_free_rate'),
    'return_frequency': ui_text('forms.labels.return_frequency'),
    'first_return': ui_text('forms.labels.first_return'),
    'missing_dates': ui_text('forms.labels.missing_dates'),
    'standard_deviation': ui_text('forms.labels.standard_deviation'),
    'minimum_observations': ui_text('forms.labels.minimum_observations'),
    'created_at': ui_text('forms.labels.created_at'),
    'side': ui_text('forms.labels.side'),
    'quantity': ui_text('forms.labels.quantity'),
    'price': ui_text('forms.labels.price'),
    'order_type': ui_text('forms.labels.kind'),
    'filled_quantity': ui_text('forms.labels.filled_quantity'),
    'commission': ui_text('forms.labels.commission'),
    'tax': ui_text('forms.labels.tax'),
}


def readable(value, key=""):
    if value is None:
        return ui_text('forms.readable.not_provided')
    if isinstance(value, bool):
        return ui_text('forms.readable.yes') if value else ui_text('forms.readable.no')
    if isinstance(value, dict):
        return ui_text('forms.readable.item_separator').join(
            ui_text('forms.readable.named_value').format(RESULT_LABELS.get(k, k), readable(v, k)) for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return ui_text('forms.readable.item_separator').join(readable(v) for v in value) or ui_text('forms.readable.none')
    return display_value(value, key)


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('result_table')
        self.setAccessibleName(ui_text('forms.init.results_accessible_name'))
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
                if key in FINANCIAL_FIELDS:
                    set_financial_item(self, item, row.get(key))
                _privacy.item_display(self, item, key)
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
        _privacy.bind_text(
            self.label,
            lambda: self.label.setText(
                '\n'.join(
                    ui_text('forms.set_values.named_value').format(
                        RESULT_LABELS.get(k, k),
                        (
                            _privacy.mask_money(v)
                            if _privacy.enabled(self.label) and isinstance(v, (dict, list, tuple))
                            else _privacy.display(self.label, readable(v, k), k)
                        ),
                    )
                    for k, v in values.items()
                )
            ),
        )


# These adapters only present verified report fields. Raw records remain in the
# host's existing advanced result_detail; no metric or report identity is changed.
_REPORT_TEXT = {
    'no closed lots': ui_text('forms.labels.no_closed_lots'),
    'no losing closed lots': ui_text('forms.labels.zero_loss_denominator'),
    'closed FIFO lot net PnL after allocated entry/exit costs; open lots excluded': ui_text('forms.labels.fifo_net_basis'),
    'missing or nonpositive daily equity; no observations discarded': ui_text('forms.labels.invalid_daily_equity'),
    'at least 2 daily returns required for sample standard deviation': ui_text('forms.labels.insufficient_returns'),
    'zero daily-return sample variance': ui_text('forms.labels.zero_return_variance'),
    'between last supplied equity per exchange trading date; gaps may span multiple days': ui_text('forms.labels.daily_equity_frequency'),
    'initial cash to first supplied trading-date equity': ui_text('forms.labels.initial_cash_basis'),
    'supplied trading dates only; no imputation': ui_text('forms.labels.provided_dates_only'),
    'sample (ddof=1)': ui_text('forms.labels.sample_standard_deviation'),
    'Descriptive only. Two returns is a mathematical minimum, not evidence of reliability; short samples do not establish strategy quality. The 252-period convention is assumed, not a validated annual trading calendar; gaps may span multiple days.': ui_text(
        'forms.labels.descriptive_sharpe_warning'
    ),
}


def _report_text(value):
    if value is None:
        return ui_text('forms.report_text.not_provided')
    return (
        _REPORT_TEXT.get(value, ui_text('forms.report_text.unknown_explanation'))
        if isinstance(value, str)
        else ui_text('forms.report_text.unknown_explanation')
    )


def _report_number(value, key=""):
    if value is None:
        return ui_text('forms.report_number.not_provided')
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return ui_text('forms.report_number.diagnostics_required')
    if len(str(value)) > 128:
        return ui_text('forms.report_number.diagnostics_required')
    try:
        if not Decimal(str(value)).is_finite():
            return ui_text('forms.report_number.diagnostics_required')
    except (InvalidOperation, ValueError):
        return ui_text('forms.report_number.diagnostics_required')
    return display_number(value, key)


def backtest_summary_text(values, *, private=False):
    """Bounded Traditional Chinese presentation, preserving exact scalar values."""

    def metric(key):
        if private and key in _privacy.MONEY_FIELDS:
            return _privacy.mask_money(None)
        value = values.get(key)
        if value is None:
            return (
                ui_text('forms.metric.undefined') if key in values and key in ('profit_factor', 'sharpe', 'win_rate') else ui_text('forms.metric.not_provided')
            )
        return _report_number(value, key)

    def fields(*keys):
        return ui_text('forms.fields.field_separator').join(ui_text('forms.fields.named_value').format(RESULT_LABELS[key], metric(key)) for key in keys)

    def reason(key, metric_key):
        value = values.get(key)
        metric_value = values.get(metric_key)
        if metric_value is not None and _report_number(metric_value) == ui_text('forms.reason.diagnostics_required'):
            text = ui_text('forms.reason.unknown_metric')
        else:
            text = ui_text('forms.reason.not_applicable') if value is None and metric_value is not None else _report_text(value)
        return ui_text('forms.reason.named_value').format(RESULT_LABELS[key], text)

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
        ui_text('forms.backtest_summary_text.profit_factor_basis').format(_report_text(values.get('profit_factor_basis'))),
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
                ui_text('forms.backtest_summary_text.field_separator').join(
                    ui_text('forms.backtest_summary_text.named_value').format(
                        RESULT_LABELS[key],
                        _report_number(assumptions.get(key), key)
                        if key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                        else _report_text(assumptions.get(key)),
                    )
                    for key in keys
                )
            )
    else:
        lines.append(ui_text('forms.backtest_summary_text.annualization_missing'))
    lines.extend(
        (
            ui_text('forms.backtest_summary_text.sharpe_limitations').format(_report_text(values.get('sharpe_note'))),
            ui_text('forms.backtest_summary_text.advanced_hint'),
        )
    )
    return '\n'.join(lines)


class BacktestSummaryCard(SummaryCard):
    """A report-only view; other summary cards retain their original contract."""

    def set_values(self, values):
        _privacy.bind_text(self.label, lambda: self.label.setText(backtest_summary_text(values, private=_privacy.enabled(self.label))))


_FILL_REASONS = {
    'target_open': ui_text('forms.labels.target_entry'),
    'target_close': ui_text('forms.labels.target_exit'),
    'gap_stop': ui_text('forms.labels.gap_stop'),
    'gap_target': ui_text('forms.labels.gap_target'),
    'stop': ui_text('forms.labels.stop_hit'),
    'target': ui_text('forms.labels.target_hit'),
    'maintenance_liquidation': ui_text('forms.labels.maintenance_liquidation'),
    'roll_close': ui_text('forms.labels.roll_close'),
    'roll_open': ui_text('forms.labels.roll_open'),
    'final_settlement': ui_text('forms.labels.expiry_settlement'),
}


class BacktestFillsTable(ResultTable):
    """Readable fills first; exact IDs remain in cell tooltips and diagnostics."""

    _columns = ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax', 'reason')
    _labels = (
        ui_text('forms.labels.fill_time'),
        ui_text('forms.labels.contract'),
        ui_text('forms.labels.side'),
        ui_text('forms.labels.quantity'),
        ui_text('forms.labels.price'),
        ui_text('forms.labels.commission'),
        ui_text('forms.labels.tax'),
        ui_text('forms.labels.fill_reason'),
    )

    def set_rows(self, rows, columns=None):
        from datetime import datetime, timezone

        display = []
        for row in rows:
            shown = {key: row.get(key) for key in self._columns}
            side, reason = row.get('side'), row.get('reason')
            shown['side'] = display_value(side, 'side') if side in ('buy', 'sell') else ui_text('forms.set_rows.unknown_value')
            shown['reason'] = (
                _FILL_REASONS.get(reason, ui_text('forms.set_rows.other_value'))
                if isinstance(reason, str) and reason
                else ui_text('forms.set_rows.not_provided')
                if reason is None or reason == ''
                else ui_text('forms.set_rows.other_value')
            )
            timestamp = row.get('timestamp')
            try:
                parsed = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError('timezone required')
                shown['timestamp'] = parsed.astimezone(timezone.utc).isoformat(sep=' ', timespec='seconds').removesuffix('+00:00')
            except (ValueError, TypeError, AttributeError):
                shown['timestamp'] = ui_text('forms.set_rows.time_missing')
            display.append(shown)
        super().set_rows(display, self._columns)
        self.setHorizontalHeaderLabels(self._labels)
        for index, row in enumerate(rows):
            detail = ui_text('forms.set_rows.fill_order_ids').format(
                str(row.get('fill_id', ui_text('forms.set_rows.not_provided'))), str(row.get('order_id', ui_text('forms.set_rows.not_provided')))
            )
            for column in range(self.columnCount()):
                item = self.item(index, column)
                _privacy.item_tooltip(self, item, str(row.get(self._columns[column], ui_text('forms.set_rows.not_provided'))) + '\n' + detail)
        self.resizeColumnsToContents()
        for column in range(self.columnCount()):
            self.setColumnWidth(column, min(self.columnWidth(column), 340))


_CANDIDATE_EVALUATION_LABELS = STATUS_LABELS


def candidate_summary_text(values, *, private=False):
    """Bounded view of saved split records; never recalculate qualification."""

    def eligibility(value):
        return (
            ui_text('forms.eligibility.passed')
            if value is True
            else ui_text('forms.eligibility.failed')
            if value is False
            else ui_text('forms.eligibility.not_provided')
        )

    def metric(metrics, key):
        if private and key in _privacy.MONEY_FIELDS:
            return _privacy.mask_money(None)
        value = metrics.get(key)
        if value is None:
            return ui_text('forms.metric.undefined') if key in metrics and key in ('profit_factor', 'sharpe') else ui_text('forms.metric.not_provided')
        return _report_number(value, key)

    def reason(metrics, key):
        value, explanation = metrics.get(key), metrics.get(key + '_reason')
        if value is not None and _report_number(value) == ui_text('forms.reason.diagnostics_required'):
            return ui_text('forms.reason.unknown_metric')
        return ui_text('forms.reason.not_applicable') if explanation is None and value is not None else _report_text(explanation)

    name = values.get(ui_text('forms.candidate_summary_text.strategy'))
    if not isinstance(name, str):
        name = ui_text('forms.candidate_summary_text.not_provided')
    elif re.fullmatch('[0-9a-fA-F]{64}', name):
        name = ui_text('forms.candidate_summary_text.abbreviated_id').format(name[:12])
    else:
        name = ' '.join(name.split())[:80] + (ui_text('forms.candidate_summary_text.truncated_name') if len(name) > 80 else '')
    lines = [
        ui_text('forms.candidate_summary_text.candidate_strategy').format(name),
        ui_text('forms.candidate_summary_text.saved_paper_gate').format(eligibility(values.get(ui_text('forms.candidate_summary_text.paper_eligibility')))),
        ui_text('forms.candidate_summary_text.eligibility_disclaimer'),
    ]
    evaluations = values.get(ui_text('forms.candidate_summary_text.oos_holdout'))
    evaluations = evaluations if isinstance(evaluations, dict) else {}
    for split, title in (('oos', ui_text('forms.candidate_summary_text.out_of_sample')), ('holdout', ui_text('forms.candidate_summary_text.final_holdout'))):
        saved = evaluations.get(split)
        saved = saved if isinstance(saved, dict) else {}
        row = saved.get('evaluation')
        row = row if isinstance(row, dict) else {}
        state = row.get('status')
        status = (
            ui_text('forms.candidate_summary_text.no_saved_evaluation')
            if not row
            else ui_text('forms.candidate_summary_text.not_provided')
            if state is None
            else _CANDIDATE_EVALUATION_LABELS.get(state, ui_text('forms.candidate_summary_text.unknown_status'))
            if isinstance(state, str)
            else ui_text('forms.candidate_summary_text.unknown_status')
        )
        metrics = row.get('metrics')
        metrics = metrics if isinstance(metrics, dict) else {}
        headline = ['net_pnl'] + (['max_drawdown'] if 'max_drawdown' in metrics else []) + ['max_drawdown_pct']
        headline.append('closed_trades' if 'trade_count' not in metrics and 'closed_trades' in metrics else 'trade_count')
        lines.extend(
            (
                '',
                ui_text('forms.candidate_summary_text.segment_status').format(title, status, eligibility(saved.get("qualified"))),
                ui_text('forms.candidate_summary_text.field_separator').join(
                    ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], metric(metrics, key)) for key in headline
                ),
            )
        )
        for key in ('profit_factor', 'sharpe'):
            lines.append(ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], metric(metrics, key)))
            if key in metrics or key + '_reason' in metrics:
                lines.append(ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key + '_reason'], reason(metrics, key)))
            if key == 'profit_factor' and key in metrics:
                lines.append(ui_text('forms.candidate_summary_text.profit_factor_basis').format(_report_text(metrics.get('profit_factor_basis'))))
        if 'sharpe' in metrics:
            lines.append(
                ui_text('forms.candidate_summary_text.field_separator').join(
                    ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_number(metrics.get(key)))
                    for key in ('sharpe_observations', 'sharpe_sample_count')
                )
            )
            assumptions = metrics.get('annualization')
            if isinstance(assumptions, dict):
                lines.append(
                    ui_text('forms.candidate_summary_text.field_separator').join(
                        ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_number(assumptions.get(key), key))
                        for key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                    )
                )
                lines.append(
                    ui_text('forms.candidate_summary_text.item_separator').join(
                        ui_text('forms.candidate_summary_text.named_value').format(RESULT_LABELS[key], _report_text(assumptions.get(key)))
                        for key in ('return_frequency', 'first_return', 'missing_dates', 'standard_deviation')
                    )
                )
            else:
                lines.append(ui_text('forms.candidate_summary_text.annualization_missing'))
            lines.append(ui_text('forms.candidate_summary_text.sharpe_limitations').format(_report_text(metrics.get('sharpe_note'))))
    lines.append(ui_text('forms.candidate_summary_text.advanced_hint'))
    return '\n'.join(lines)


class CandidateSummaryCard(SummaryCard):
    """Only the generated-candidate pane; qualification stays host-owned."""

    def set_values(self, values):
        _privacy.bind_text(self.label, lambda: self.label.setText(candidate_summary_text(values, private=_privacy.enabled(self.label))))
