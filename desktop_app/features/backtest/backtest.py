from decimal import DecimalException
from pathlib import Path
from quantlab import strict_json
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QPlainTextEdit, QCheckBox, QFormLayout, QSizePolicy, QToolButton
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError, canonical_json, to_dict
from quantlab.reporting import load_result, demo_config
from quantlab.desktop_errors import error_message, exception_code
from desktop_app.features.backtest.forms import BacktestForm
from desktop_app.features.backtest.summary import BacktestSummaryCard, BacktestFillsTable
from desktop_app.features.backtest.backtest_summary_card import ReportSummaryCard
from desktop_app.shell.host import PageHost
from desktop_app.components.async_status import AsyncStatus
from desktop_app.components.equity import EquityPlot
from desktop_app.components.result_widgets import KpiCards, TaipeiFillsTable
from desktop_app.components.design import card, section
from desktop_app.shell.palette_commands import page_index


class BacktestPage(QWidget):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = host.state
        layout = self.host.mount_page(self, ui_text('ui.backtest_page.title'))
        setup = card(layout, 'redesign.backtest.conditions')
        self._setup_panel = layout.itemAt(layout.count() - 1).widget()
        self.setup_toggle = QToolButton()
        self.setup_toggle.setObjectName('backtest_setup_toggle')
        self.setup_toggle.setText(ui_text('redesign.backtest.setup_again'))
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setProperty('designDisclosure', True)
        self.setup_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setup_toggle.toggled.connect(self._setup_panel.setVisible)
        self.setup_toggle.toggled.connect(lambda checked: self.setup_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        layout.insertWidget(layout.indexOf(self._setup_panel), self.setup_toggle)
        self.run_summary = QLabel()
        self.run_summary.setWordWrap(True)
        self.run_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.run_summary.setAccessibleName(ui_text('redesign.backtest.conditions'))
        setup.addWidget(self.run_summary)
        self.host.button(setup, ui_text('redesign.backtest.change_strategy'), 'backtest_to_strategy', lambda: self.navigate('strategy'))
        self.backtest_form = BacktestForm()
        self.start_date = self.backtest_form.fields['start_date']
        self.end_date = self.backtest_form.fields['end_date']
        common = section(setup, 'redesign.backtest.common', key='redesign_backtest_common', state=self.state)
        common_form = QFormLayout()
        common_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        common.addLayout(common_form)
        for key in ('start_date', 'end_date', 'initial_cash', 'commission_per_side', 'tax_rate', 'slippage_ticks'):
            row = self.backtest_form.form.takeRow(self.backtest_form.fields[key])
            common_form.addRow(row.labelItem.widget(), row.fieldItem.widget())
        advanced = section(setup, 'redesign.backtest.advanced', key='redesign_backtest_advanced', state=self.state)
        advanced.addWidget(self.backtest_form)
        self.config = self.host.text(advanced, ui_text('ui.backtest_page.cost_json'), canonical_json(demo_config()), True)
        self.host.remember(self.config)
        self.batch = QCheckBox(ui_text('ui.backtest_page.batch_defaults'))
        advanced.addWidget(self.batch)
        self.run_button = self.host.button(setup, ui_text('ui.backtest_page.run'), 'run_backtest', self.run_backtest, role='primary')
        self.summary_card = ReportSummaryCard(self)
        self.summary_card.hint.setWordWrap(True)
        layout.addWidget(self.summary_card)
        self.result_choice = QComboBox()
        self.result_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.result_choice.setMinimumContentsLength(12)
        self.result_choice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.result_choice.setAccessibleName(ui_text('redesign.backtest.results'))
        self.result_label = QLabel(ui_text('redesign.backtest.results'))
        layout.addWidget(self.result_label)
        self.result_choice.currentIndexChanged.connect(self.show_result)
        layout.addWidget(self.result_choice)
        self.plot = EquityPlot()
        self.plot.setMinimumHeight(250)
        layout.addWidget(self.plot)
        self.result_detail = QPlainTextEdit()
        self.result_detail.setReadOnly(True)
        self.result_empty = AsyncStatus()
        self.result_empty.setObjectName('result_empty_status')
        self.result_empty.set_state('empty', message=ui_text('ui.show_result.no_result'))
        layout.addWidget(self.result_empty)
        self._report_layout = section(layout, 'redesign.backtest.details', key='redesign_backtest_report', state=self.state)
        report_section = layout.itemAt(layout.count() - 1).widget()
        self._report_layout.addWidget(self.result_detail)
        self.result_card = BacktestSummaryCard()
        self._report_layout.addWidget(self.result_card)
        self.result_card.hide()
        self.kpis = KpiCards(('net_pnl', 'profit_factor', 'sharpe', 'max_drawdown', 'closed_lots', 'open_position'))
        self._report_layout.addWidget(self.kpis)
        self.fills_table = TaipeiFillsTable()
        fills = section(layout, 'redesign.backtest.fills', key='redesign_backtest_fills', state=self.state)
        fills_section = layout.itemAt(layout.count() - 1).widget()
        fills.addWidget(self.fills_table)
        self.fills_table.setMaximumHeight(280)
        compare_button = self.host.button(layout, ui_text('redesign.backtest.compare'), 'backtest_to_compare', self.compare_result)
        report_button = self.host.button(layout, ui_text('redesign.backtest.open_report'), 'backtest_open_report', self.open_report)
        report_button.setToolTip(ui_text('privacy.exports_raw'))
        notice = QLabel(ui_text('redesign.backtest.research_notice'))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        paper_button = self.host.button(layout, ui_text('redesign.backtest.eligibility'), 'backtest_to_paper', lambda: self.navigate('paper'))
        layers = section(layout, 'redesign.backtest.layers', key='redesign_backtest_layers', state=self.state)
        self._result_widgets = (
            self.result_label,
            self.result_choice,
            self.plot,
            report_section,
            fills_section,
            compare_button,
            report_button,
            notice,
            paper_button,
            layout.itemAt(layout.count() - 1).widget(),
        )
        for kind, caption in (('signal', ui_text('ui.backtest_page.show_signals')), ('fill', ui_text('ui.backtest_page.show_fills'))):
            toggle = QCheckBox(caption)
            toggle.setChecked(True)
            layers.addWidget(toggle)
            toggle.toggled.connect(lambda value, layer=kind: self.state.market.chart.set_layer_visible(layer, value))
        for field in self.backtest_form.fields.values():
            if hasattr(field, 'textChanged'):
                field.textChanged.connect(self.refresh_run_summary)
        self.config.textChanged.connect(self.refresh_run_summary)
        self.refresh_run_summary()
        self._set_result_visibility(False)

    def _set_result_visibility(self, ready):
        self.setup_toggle.setVisible(ready)
        self.setup_toggle.setChecked(not ready)
        self._setup_panel.setVisible(not ready)
        for widget in self._result_widgets:
            widget.setVisible(ready)

    def showEvent(self, event):
        self.refresh_run_summary()
        super().showEvent(event)

    def navigate(self, identity):
        index = page_index(self.state, identity)
        if index >= 0:
            self.state.navigation.setCurrentRow(index)

    def compare_result(self):
        path = self.result_choice.currentData()
        if path:
            for row in range(self.state.comparison_list.count()):
                item = self.state.comparison_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == path:
                    item.setSelected(True)
                    break
        self.navigate('compare')

    def open_report(self):
        path = self.result_choice.currentData()
        if not path:
            raise ValidationError(ui_text('ui.select_strategy.result_required'))
        selected = Path(path).resolve(strict=True)
        reports = (self.state.root / 'reports').resolve(strict=True)
        if selected.name != 'result.json' or not selected.is_relative_to(reports):
            raise ValidationError(ui_text('ui.execute_ui_operation.incomplete_report'))
        load_result(selected)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(selected.parent))):
            raise ValidationError(error_message('operation_failed'))

    def refresh_run_summary(self, *args):
        overview = getattr(self.state, 'data_card', None)
        source = (
            overview.text().splitlines()[0] if overview is not None and getattr(self.state, '_dataset_ready', True) else ui_text('redesign.backtest.no_data')
        )
        candidate = getattr(self.state, 'active_candidate', None)
        family = getattr(self.state, 'family', None)
        strategy = (
            ui_text('redesign.backtest.candidate').format(str(candidate.get('strategy_hash', ''))[:12])
            if candidate
            else family.currentText()
            if family is not None
            else ui_text('ui.backtest_page.strategy_hint')
        )
        try:
            typed = self.backtest_form.build_payload()
            config = self.host.payload(self.config, lambda: typed['config']) if hasattr(self.host, 'payload') else typed['config']
            # Use the worker's existing configuration validator for JSON overrides.
            from quantlab.__main__ import config_from_json

            costs = config_from_json(config).costs
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError, DecimalException):
            self.run_summary.setText(ui_text('redesign.backtest.error_summary'))
            return
        self.run_summary.setText(
            ui_text('redesign.backtest.summary').format(
                source,
                strategy,
                typed['start_date'] or ui_text('redesign.backtest.full_range'),
                typed['end_date'] or ui_text('redesign.backtest.full_end'),
                costs.commission_per_side,
                format((costs.tax_rate * 100).normalize(), 'f') + '%',
                costs.slippage_ticks,
            )
        )

    def run_backtest(self):
        self.summary_card.set_values({})
        self.refresh_run_summary()
        typed = self.backtest_form.build_payload()
        config = self.host.payload(self.config, lambda: typed['config'])
        spec = self.state.strategy_form.build_payload() if self.state.active_candidate is None else None
        parameters = self.host.payload(self.state.parameters, lambda: spec['parameters']) if spec else strict_json.loads(self.state.parameters.toPlainText())
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
        if getattr(self, 'synthetic_notice', None) is not None:
            self.synthetic_notice.hide()
        self.summary_card.set_values({})
        self.plot.set_values([])
        self.kpis.set_values({})
        self.fills_table.set_rows([])
        self.result_detail.clear()
        self.state.market.chart.set_reference_lines(())
        path = self.result_choice.currentData()
        self.state._selection_allowed = False
        self.state.select_button.setEnabled(False)
        self._set_result_visibility(False)
        if not path:
            self.plot.set_values([])
            self.kpis.set_values({})
            self.fills_table.set_rows([])
            self.result_empty.set_state('empty', message=ui_text('ui.show_result.no_result'))
            self.result_empty.setVisible(not hasattr(self.state, 'onboarding'))
            self.result_detail.clear()
            return
        try:
            result = load_result(path)
            if result.manifest.get('dataset_manifest', {}).get('source_type') == 'synthetic':
                if getattr(self, 'synthetic_notice', None) is None:
                    self.synthetic_notice = QLabel(ui_text('quick_start.disclaimer'), self)
                    self.synthetic_notice.setWordWrap(True)
                    self.synthetic_notice.setAccessibleName(ui_text('quick_start.disclaimer'))
                    self.layout().insertWidget(1, self.synthetic_notice)
                self.synthetic_notice.show()
            self.result_empty.setVisible(False)
            self._set_result_visibility(True)
            self.plot.set_values(result.equity)
            self.result_card.set_values(dict(result.metrics))
            self.summary_card.set_values(dict(result.metrics), bar_count=len(result.equity), ledger=getattr(result, 'ledger', None))
            if hasattr(self.summary_card, 'structure'):
                self._report_layout.addWidget(self.summary_card.structure)
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
            return True
        except Exception as exc:
            self._set_result_visibility(False)
            self.summary_card.set_values({})
            self.plot.set_values([])
            self.kpis.set_values({})
            self.fills_table.set_rows([])
            self.result_detail.clear()
            self.result_empty.set_state('empty', message=ui_text('ui.show_result.no_result'))
            self.result_empty.setVisible(True)
            self.state._selection_allowed = False
            self.state.status.setText(error_message(exception_code(exc)))
            return False
