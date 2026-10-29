"""Report projections shared by the walk-forward wizard and saved results."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFormLayout, QLineEdit, QPushButton
from quantlab.capital_scenario import validate_inputs
from desktop_app.strings.catalog import ui_text
from desktop_app.features.walk_forward.presenter import status_label
from desktop_app.components.result_widgets import KpiCards, ResultTable


class WalkForwardResults(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('wf_result_panel')
        layout = QVBoxLayout(self)
        self.kpis = KpiCards(('folds', 'evaluated_oos_folds', 'evaluations_reserved', 'evaluation_limit'))
        layout.addWidget(self.kpis)
        self.table = ResultTable()
        layout.addWidget(self.table)
        self.set_result({})

    def set_result(self, result):
        self.scenario_reference = result.get('reference')
        evaluated = result.get('summary', {}).get('evaluated_oos_folds', 0)
        if evaluated and self.scenario_reference and not hasattr(self, '_scenario'):
            self._build_scenario()
        if hasattr(self, '_scenario'):
            self._scenario.setVisible(bool(evaluated and self.scenario_reference))
            self._scenario_output.clear()
        text = result.get('oos_statistics_text', '')
        if text and not hasattr(self, '_oos_statistics'):
            self._oos_statistics = QLabel(self)
            self._oos_statistics.setWordWrap(True)
            self._oos_statistics.setAccessibleName(ui_text('walk_forward.statistics.title'))
            self.layout().addWidget(self._oos_statistics)
        if hasattr(self, '_oos_statistics'):
            self._oos_statistics.setText(text)
            self._oos_statistics.setVisible(bool(text))
        summary = result.get('summary', {})
        values = dict(summary.get('metrics', {}))
        values.update({key: summary[key] for key in ('evaluated_oos_folds', 'evaluations_reserved', 'evaluation_limit') if key in summary})
        if 'folds' in result:
            values['folds'] = len(result['folds'])
        self.kpis.set_values(values)
        rows = []
        for fold in result.get('folds', []):
            oos = fold.get('oos') or {}
            metrics = oos.get('metrics') or {}
            row = {ui_text('wf.fold'): fold['index'] + 1, 'status': status_label(fold.get('status'))}
            row.update(
                {
                    key: metrics[key]
                    for key in ('net_pnl', 'return', 'profit_factor', 'sharpe', 'max_drawdown_pct', 'trade_count', 'open_position')
                    if key in metrics
                }
            )
            rows.append(row)
        self.table.set_rows(
            rows, (ui_text('wf.fold'), 'status', 'net_pnl', 'return', 'profit_factor', 'sharpe', 'max_drawdown_pct', 'trade_count', 'open_position')
        )

    def _build_scenario(self):
        self._scenario = QWidget(self)
        layout = QVBoxLayout(self._scenario)
        title = QLabel(ui_text('capital.title'), self._scenario)
        layout.addWidget(title)
        form = QFormLayout()
        self._scenario_fields = {}
        fields = (
            ('start_equity', '1000000', ui_text('capital.start')),
            ('threshold', '900000', ui_text('capital.threshold')),
            ('horizon_days', '60', ui_text('capital.days')),
            ('paths', '1000', ui_text('capital.paths')),
        )
        for key, default, label in fields:
            widget = QLineEdit(default, self._scenario)
            widget.setObjectName('capital_' + key)
            widget.setAccessibleName(label)
            widget.setToolTip(label)
            form.addRow(label, widget)
            self._scenario_fields[key] = widget
        layout.addLayout(form)
        self._scenario_run = QPushButton(ui_text('capital.run'), self._scenario)
        self._scenario_run.setObjectName('capital_run')
        self._scenario_run.setAccessibleName(ui_text('capital.run'))
        self._scenario_run.setToolTip(ui_text('capital.run_tip'))
        self._scenario_run.setProperty('role', 'secondary')
        self._scenario_run.clicked.connect(self._run_scenario)
        layout.addWidget(self._scenario_run)
        disclaimer = QLabel(ui_text('capital.disclaimer'), self._scenario)
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)
        self._scenario_output = QLabel(self._scenario)
        self._scenario_output.setWordWrap(True)
        layout.addWidget(self._scenario_output)
        self.layout().addWidget(self._scenario)
        self.set_scenario_busy(bool(getattr(getattr(getattr(self, 'scenario_state', None), 'jobs', None), 'active', False)))

    def set_scenario_busy(self, active):
        if hasattr(self, '_scenario_run'):
            self._scenario_run.setEnabled(not active)

    def _run_scenario(self):
        state = getattr(self, 'scenario_state', None)
        if getattr(getattr(state, 'jobs', None), 'active', False):
            return
        parameters = {key: widget.text() for key, widget in self._scenario_fields.items()}
        try:
            parameters['horizon_days'] = int(parameters['horizon_days'])
            parameters['paths'] = int(parameters['paths'])
            parameters['seed'] = 1729
            if validate_inputs(**parameters):
                raise ValueError
        except (ValueError, TypeError):
            self._scenario_output.setText(ui_text('capital.invalid'))
            return
        host = getattr(self, 'scenario_host', None)
        if host is None or not self.scenario_reference:
            self._scenario_output.setText(ui_text('capital.invalid'))
            return
        self._scenario_output.clear()
        self._scenario_run.setEnabled(False)
        host.start_job('ui_capital_scenario', {'reference': self.scenario_reference, **parameters})

    def set_scenario(self, result):
        if not hasattr(self, '_scenario_output'):
            return
        status = result.get('status')
        text = {
            'completed': ui_text('capital.completed'),
            'cancelled': ui_text('capital.cancelled'),
            'timed_out': ui_text('capital.timed_out'),
        }.get(status, ui_text('capital.rejected'))
        if status == 'completed':
            text += '\n' + ui_text('capital.result').format(result.get('breach_fraction'), result.get('actual_paths'))
            for key, value in (result.get('percentiles') or {}).items():
                text += '\n' + ui_text('capital.percentile').format(key, value)
        self._scenario_output.setText(text)
