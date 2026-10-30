"""desktop_app components result_tables responsibilities."""

from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
from desktop_app.shell.theme import FINANCIAL_FIELDS, set_financial_item
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView
from desktop_app.components.formatting import display_value


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
