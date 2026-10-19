"""Report projections shared by the walk-forward wizard and saved results."""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from desktop_strings import ui_text
from desktop_walk_forward import status_label
from .result_widgets import KpiCards, ResultTable


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
