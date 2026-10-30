"""desktop_app features strategy forms responsibilities."""

from desktop_app.strings.catalog import ui_text
from quantlab.ui_preferences import family_parameters
from copy import deepcopy
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit
from quantlab.core import ValidationError, StrategySpec, to_dict
from quantlab.strategies import DEFAULTS, FAMILIES, validate_strategy
from desktop_app.components.form_values import number
from desktop_app.components.forms import _Form


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
