"""Display-only plain-language summary of a reported backtest."""

from PySide6.QtWidgets import QLabel

from desktop_forms import SummaryCard, RESULT_LABELS
from desktop_strings import ui_text
import desktop_privacy as _privacy
from quantlab.backtest_summary import warning_keys
from .result_widgets import shown, MISSING


class ReportSummaryCard(SummaryCard):
    """Three reported metrics, hidden until a result exists."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('backtest_summary')
        self.setAccessibleName(ui_text('backtest.summary.title'))
        self.label.setAccessibleName(ui_text('backtest.summary.metrics'))
        self.hint = QLabel(ui_text('backtest.summary.hint'), self)
        self.hint.setObjectName('backtest_summary_hint')
        self.hint.setAccessibleName(ui_text('backtest.summary.hint'))
        self.layout().addWidget(self.hint)
        self.warning = QLabel(self)
        self.warning.setObjectName('backtest_summary_warnings')
        self.warning.setAccessibleName(ui_text('backtest.summary.warnings'))
        self.warning.setWordWrap(True)
        self.layout().addWidget(self.warning)
        self.set_values({})

    def set_values(self, values, *, bar_count=0):
        self.setVisible(bool(values))
        metrics = {key: values[key] for key in ('net_pnl', 'max_drawdown', 'closed_lots') if key in values}
        keys = warning_keys(bar_count, values.get('trade_count', values.get('closed_lots', 0)), values.get('closed_lots', 0)) if values else ()
        captions = {
            'backtest.summary.sample_short': ui_text('backtest.summary.sample_short'),
            'backtest.summary.no_closed_trades': ui_text('backtest.summary.no_closed_trades'),
        }
        self.warning.setText('\n'.join(captions[key] for key in keys))
        self.warning.setVisible(bool(keys))
        _privacy.bind_text(
            self.label,
            lambda: self.label.setText(
                '\n'.join(
                    ui_text('forms.set_values.text_1').format(RESULT_LABELS[key], _privacy.display(self.label, shown(metrics.get(key, MISSING), key), key))
                    for key in ('net_pnl', 'max_drawdown', 'closed_lots')
                )
                if metrics
                else ui_text('backtest.summary.empty')
            ),
        )
