"""desktop_app features research forms responsibilities."""

from desktop_app.strings.catalog import ui_text
from copy import deepcopy
from PySide6.QtWidgets import QCheckBox
from quantlab.core import ValidationError
from quantlab.strategies import FAMILIES
from desktop_app.components.forms import _Form
from desktop_app.features.strategy.forms import FAMILY_LABELS


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
        from quantlab.configuration import config_from_json

        config_from_json(config['backtest_config'])
        return config
