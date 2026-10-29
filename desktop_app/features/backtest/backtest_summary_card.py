"""Display-only plain-language summary of a reported backtest."""

from PySide6.QtWidgets import QLabel

from desktop_app.components.forms import SummaryCard, RESULT_LABELS
from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
from quantlab.backtest_summary import warning_keys
from quantlab.trade_statistics import describe, breakeven, red_flags
from desktop_app.components.result_widgets import shown, MISSING


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

    def set_values(self, values, *, bar_count=0, ledger=None):
        self.setVisible(bool(values))
        self._set_structure(values, ledger)
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
                    ui_text('forms.set_values.named_value').format(RESULT_LABELS[key], _privacy.display(self.label, shown(metrics.get(key, MISSING), key), key))
                    for key in ('net_pnl', 'max_drawdown', 'closed_lots')
                )
                if metrics
                else ui_text('backtest.summary.empty')
            ),
        )

    def _set_structure(self, values, ledger):
        if ledger is None or not values:
            if hasattr(self, 'structure'):
                _privacy.bind_text(self.structure, self.structure.clear)
                self.structure.hide()
            return
        if not hasattr(self, 'structure'):
            self.structure = QLabel(self)
            self.structure.setObjectName('backtest_trade_structure')
            self.structure.setAccessibleName(ui_text('trade_structure.title'))
            self.structure.setWordWrap(True)
            self.layout().addWidget(self.structure)
        stats = describe(ledger)
        stats.update(breakeven(stats))
        captions = {
            'n': ui_text('trade_structure.n'),
            'wins': ui_text('trade_structure.wins'),
            'losses': ui_text('trade_structure.losses'),
            'ties': ui_text('trade_structure.ties'),
            'expectancy': ui_text('trade_structure.expectancy'),
            'avg_win': ui_text('trade_structure.avg_win'),
            'avg_loss': ui_text('trade_structure.avg_loss'),
            'payoff_ratio': ui_text('trade_structure.payoff_ratio'),
            'win_rate': ui_text('trade_structure.win_rate'),
            'max_losing_streak': ui_text('trade_structure.max_losing_streak'),
            'largest_win': ui_text('trade_structure.largest_win'),
            'largest_win_share': ui_text('trade_structure.largest_win_share'),
            'breakeven_payoff_ratio': ui_text('trade_structure.breakeven_payoff_ratio'),
            'breakeven_win_rate': ui_text('trade_structure.breakeven_win_rate'),
        }
        reasons = {
            'trade_structure.reason.no_closed_lots': ui_text('trade_structure.reason.no_closed_lots'),
            'trade_structure.reason.no_wins': ui_text('trade_structure.reason.no_wins'),
            'trade_structure.reason.no_losses': ui_text('trade_structure.reason.no_losses'),
            'trade_structure.reason.tie_lots': ui_text('trade_structure.reason.tie_lots'),
        }
        flags = {
            'negative_expectancy': ui_text('trade_structure.flag.negative_expectancy'),
            'single_trade_dominance': ui_text('trade_structure.flag.single_trade_dominance'),
            'small_wins_big_losses': ui_text('trade_structure.flag.small_wins_big_losses'),
            'thin_edge_margin': ui_text('trade_structure.flag.thin_edge_margin'),
            'severe_drawdown': ui_text('trade_structure.flag.severe_drawdown'),
            'long_losing_streak': ui_text('trade_structure.flag.long_losing_streak'),
            'marginal_profit_factor': ui_text('trade_structure.flag.marginal_profit_factor'),
        }
        alerts = red_flags(stats, values.get('max_drawdown_pct'))
        severities = {'high': ui_text('trade_structure.severity.high'), 'medium': ui_text('trade_structure.severity.medium')}
        self.structure.show()

        def render():
            lines = [ui_text('trade_structure.title')]
            for key, caption in captions.items():
                value = stats[key]
                text = reasons[stats[key + '_reason']] if value is None else str(value)
                if value is not None and key in ('expectancy', 'avg_win', 'avg_loss', 'largest_win'):
                    text = _privacy.display(self.structure, text, 'net_pnl')
                lines.append(ui_text('forms.set_values.named_value').format(caption, text))
            lines.extend(ui_text('trade_structure.flag_line').format(severities[flag['severity']], flags[flag['code']]) for flag in alerts)
            self.structure.setText('\n'.join(lines))

        _privacy.bind_text(self.structure, render)
