import json
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QPlainTextEdit, QCheckBox
from desktop_strings import ui_text
from quantlab.core import canonical_json, to_dict
from quantlab.reporting import load_result, demo_config
from quantlab.desktop_errors import error_message, exception_code
from desktop_forms import BacktestForm, BacktestSummaryCard, BacktestFillsTable
from .backtest_summary_card import ReportSummaryCard
from .host import PageHost
from .async_status import AsyncStatus
from .equity import EquityPlot
from .result_widgets import KpiCards, TaipeiFillsTable


class BacktestPage(QWidget):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = host.state
        layout = self.host.mount_page(self, ui_text('ui._backtest_page.text_1'))
        layout.addWidget(QLabel(ui_text('ui._backtest_page.text_2')))
        parameters = self.host.advanced(layout, ui_text('ui._backtest_page.text_3'))
        self.backtest_form = BacktestForm()
        parameters.addWidget(self.backtest_form)
        self.start_date = self.backtest_form.fields['start_date']
        self.end_date = self.backtest_form.fields['end_date']
        advanced = self.host.advanced(layout)
        self.config = self.host.text(advanced, ui_text('ui._backtest_page.text_4'), canonical_json(demo_config()), True)
        self.host.remember(self.config)
        self.batch = QCheckBox(ui_text('ui._backtest_page.text_5'))
        layout.addWidget(self.batch)
        self.run_button = self.host.button(layout, ui_text('ui._backtest_page.text_6'), 'run_backtest', self.run_backtest, role='primary')
        self.summary_card = ReportSummaryCard(self)
        layout.addWidget(self.summary_card)
        self.result_choice = QComboBox()
        self.result_choice.currentIndexChanged.connect(self.show_result)
        layout.addWidget(self.result_choice)
        self.plot = EquityPlot()
        layout.addWidget(self.plot)
        self.result_detail = QPlainTextEdit()
        self.result_detail.setReadOnly(True)
        self.result_empty = AsyncStatus()
        self.result_empty.setObjectName('result_empty_status')
        self.result_empty.set_state('empty', message=ui_text('ui.show_result.text_1'))
        advanced.addWidget(self.result_empty)
        advanced.addWidget(self.result_detail)
        self.result_card = BacktestSummaryCard()
        advanced.addWidget(self.result_card)
        self.result_card.hide()
        self.kpis = KpiCards(('net_pnl', 'profit_factor', 'sharpe', 'max_drawdown', 'closed_lots', 'open_position'))
        layout.addWidget(self.kpis)
        self.fills_table = TaipeiFillsTable()
        layout.addWidget(self.fills_table)
        for kind, caption in (('signal', ui_text('ui._backtest_page.text_7')), ('fill', ui_text('ui._backtest_page.text_8'))):
            toggle = QCheckBox(caption)
            toggle.setChecked(True)
            layout.addWidget(toggle)
            toggle.toggled.connect(lambda value, layer=kind: self.state.market.chart.set_layer_visible(layer, value))

    def run_backtest(self):
        self.summary_card.set_values({})
        typed = self.backtest_form.build_payload()
        config = self.host.payload(self.config, lambda: typed['config'])
        spec = self.state.strategy_form.build_payload() if self.state.active_candidate is None else None
        parameters = self.host.payload(self.state.parameters, lambda: spec['parameters']) if spec else json.loads(self.state.parameters.toPlainText())
        self.host.start_job(
            'ui_backtest',
            {
                'family': self.state.family.currentText(),
                'parameters': parameters,
                'config': config,
                'start_date': typed['start_date'],
                'end_date': typed['end_date'],
                'batch': self.batch.isChecked(),
                'candidate': self.state.active_candidate,
            },
        )

    def show_result(self, index=None):
        self.summary_card.set_values({})
        self.plot.set_values([])
        self.kpis.set_values({})
        self.fills_table.set_rows([])
        self.result_detail.clear()
        self.state.market.chart.set_reference_lines(())
        path = self.result_choice.currentData()
        self.state._selection_allowed = False
        if not path:
            self.plot.set_values([])
            self.kpis.set_values({})
            self.fills_table.set_rows([])
            self.result_empty.set_state('empty', message=ui_text('ui.show_result.text_1'))
            self.result_empty.setVisible(True)
            self.result_detail.clear()
            return
        try:
            result = load_result(path)
            self.result_empty.setVisible(False)
            self.plot.set_values(result.equity)
            self.result_card.set_values(dict(result.metrics))
            self.summary_card.set_values(dict(result.metrics), bar_count=len(result.equity))
            self.kpis.set_values(dict(result.metrics))
            self.fills_table.set_rows([to_dict(x) for x in result.fills])
            self.host.bind_result_layers(result)
            self.state._selection_allowed = True
            reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
            if reference:
                _, provenance = self.host.candidate_record(self.state.root, reference)
                self.state._selection_allowed = provenance['paper_qualified']
            self.state.select_button.setEnabled(self.state._selection_allowed and not self.state.jobs.active)
            self.result_detail.setPlainText(
                canonical_json(
                    {'metrics': result.metrics, 'warnings': result.warnings, 'manifest': result.manifest, 'fills': result.fills, 'rejects': result.rejects}
                )
            )
        except Exception as exc:
            self.summary_card.set_values({})
            self.plot.set_values([])
            self.kpis.set_values({})
            self.fills_table.set_rows([])
            self.result_detail.clear()
            self.result_empty.set_state('empty', message=ui_text('ui.show_result.text_1'))
            self.result_empty.setVisible(True)
            self.state._selection_allowed = False
            self.state.status.setText(error_message(exception_code(exc)))
