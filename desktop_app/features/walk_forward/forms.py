"""desktop_app features walk_forward forms responsibilities."""

from desktop_app.strings.catalog import ui_text
from copy import deepcopy
from decimal import Decimal
from quantlab.core import ValidationError, to_dict
from desktop_app.components.forms import _Form


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
        from quantlab.configuration import config_from_json
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
