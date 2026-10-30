from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QPlainTextEdit, QCheckBox, QSpinBox, QTabWidget, QVBoxLayout, QFormLayout, QLineEdit, QHBoxLayout
from desktop_app.strings.catalog import ui_text
from desktop_app.components.formatting import display_status
from quantlab.core import ValidationError
from quantlab.data_gap_report import GapReport
from desktop_app.features.market.history_dialog import MarketHistoryDialog
from desktop_app.shell.host import PageHost
from desktop_app.features.data.data_gaps import GapPanel
from desktop_app.components.design import card, section
from desktop_app.shell.palette_commands import page_index
from desktop_app.components.result_widgets import taipei_time


class DataPage(QWidget):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = host.state
        self.overview = QLabel()
        self.data_card = QLabel()
        self.data_card.setWordWrap(True)
        self.data_card.setTextFormat(Qt.TextFormat.PlainText)
        self.data_card.setAccessibleName(ui_text('redesign.data.loaded'))
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout = self.host.mount_page(self, ui_text('ui.data_page.title'))
        self._gap_layout = layout
        self.gap_panel = None
        self.overview.setWordWrap(True)
        layout.addWidget(QLabel(ui_text('redesign.data.flow')))
        current = card(layout, 'redesign.data.loaded')
        self.current_panel = layout.itemAt(layout.count() - 1).widget()
        current.setContentsMargins(16, 10, 16, 10)
        current.setSpacing(6)
        current.itemAt(0).widget().hide()
        current_row = QHBoxLayout()
        current.addLayout(current_row)
        current_row.addWidget(self.data_card, 1)
        self.overview.hide()
        self.next_button = self.host.button(current_row, ui_text('redesign.data.strategy'), 'data_to_strategy', lambda: self.navigate('strategy'))
        self.next_button.setEnabled(False)
        self.empty_note = QLabel(ui_text('redesign.data.empty'))
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)
        self.sources = QTabWidget()
        self.sources.setObjectName('data_sources')
        self.sources.setAccessibleName(ui_text('redesign.data.flow'))
        layout.addWidget(self.sources)
        local = self._source(ui_text('redesign.data.local'))
        official = self._source(ui_text('redesign.data.official'))
        download = self._source(ui_text('redesign.data.download'))
        download.setContentsMargins(12, 12, 12, 12)
        download.setSpacing(6)
        synthetic = self._source(ui_text('redesign.data.synthetic'))
        self.market_provider = QComboBox()
        self.market_provider.addItem(ui_text('ui.data_page.twse_json'), ('twse', 'json'))
        self.market_provider.addItem(ui_text('ui.data_page.taifex_json'), ('taifex', 'json'))
        self.market_provider.addItem(ui_text('ui.data_page.taifex_csv'), ('taifex', 'csv'))
        self._note(official, ui_text('redesign.data.official_hint'))
        official.addWidget(QLabel(ui_text('redesign.data.provider')))
        official.addWidget(self.market_provider)
        self.host.button(official, ui_text('ui.data_page.import_market'), 'import_market_file', self.import_market_file, role='primary')
        self.host.button(official, ui_text('ui.data_page.import_tick_history'), 'import_market_history', self.import_market_history)
        self.import_kind = QComboBox()
        self.import_kind.setAccessibleName(ui_text('redesign.data.kind'))
        for kind, label in (
            ('validated_dataset', ui_text('import.kind.validated_dataset')),
            ('ticks', ui_text('import.kind.ticks')),
            ('ticks_rpt', ui_text('import.kind.ticks_rpt')),
            ('daily_json', ui_text('import.kind.daily_json')),
            ('synthetic_daily_json', ui_text('import.kind.synthetic_daily_json')),
            ('synthetic_bars', ui_text('import.kind.synthetic_bars')),
            ('synthetic_ticks', ui_text('import.kind.synthetic_ticks')),
            ('proxy_bars', ui_text('import.kind.proxy_bars')),
            ('proxy_ticks', ui_text('import.kind.proxy_ticks')),
        ):
            self.import_kind.addItem(label, kind)
            self.import_kind.setItemData(self.import_kind.count() - 1, kind, Qt.ItemDataRole.ToolTipRole)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(ui_text('redesign.data.kind'), self.import_kind)
        local.addLayout(form)
        self.import_path = self._file_field(local, ui_text('ui.data_page.local_file_path'), ui_text('ui.data_page.browse_file'), 'browse_data')
        self.calendar_path = self._file_field(local, ui_text('ui.data_page.calendar_path'), ui_text('ui.data_page.browse_calendar'), 'browse_calendar')
        self._note(local, ui_text('redesign.data.calendar_hint'))
        self.contract_box = QWidget()
        contract_layout = QFormLayout(self.contract_box)
        contract_layout.setContentsMargins(0, 0, 0, 0)
        self.contract = QLineEdit('TAIFEX:TMF:202601')
        self.contract.setObjectName('data_contract')
        self.contract.setAccessibleName(ui_text('ui.data_page.optional_contract'))
        contract_layout.addRow(ui_text('ui.data_page.optional_contract'), self.contract)
        self.contract_filter = QCheckBox(ui_text('redesign.data.contract_filter'))
        self.contract_filter.setObjectName('data_contract_filter')
        self.contract_filter.setAccessibleName(ui_text('redesign.data.contract_filter'))
        self.contract_filter.setToolTip(ui_text('redesign.data.contract_filter_hint'))
        self.contract_filter.toggled.connect(self._kind_changed)
        local.addWidget(self.contract_filter)
        local.addWidget(self.contract_box)
        self.kind_notice = self._note(local, '')
        self.host.button(local, ui_text('ui.data_page.import_validate'), 'import_data', self.import_data, role='primary')
        self.bars = QSpinBox()
        self.bars.setRange(120, 10000)
        self.bars.setValue(960)
        self._note(synthetic, ui_text('redesign.data.synthetic_hint'))
        self.bars.setAccessibleName(ui_text('redesign.data.bars'))
        synthetic.addWidget(QLabel(ui_text('redesign.data.bars')))
        synthetic.addWidget(self.bars)
        self.host.button(
            synthetic,
            ui_text('ui.data_page.create_synthetic'),
            'create_demo',
            lambda: self.host.start_job('ui_demo', {'bars': self.bars.value()}),
            role='primary',
        )
        self.network_data = QCheckBox(ui_text('ui.data_page.download_consent'))
        download.addWidget(self.network_data)
        self.days = QSpinBox()
        self.days.setRange(1, 30)
        self.days.setAccessibleName(ui_text('redesign.data.days'))
        download.addWidget(QLabel(ui_text('redesign.data.days')))
        download.addWidget(self.days)
        # Construct operation-specific controls only while mounting the data page.
        from desktop_app.features.data.download_import import DownloadImportControls

        self.download_import = DownloadImportControls(self, download)
        self.download_button = self.host.button(download, ui_text('download_import.action'), 'refresh_data', self.download_data, role='primary')
        self.download_import.update_choice()
        details = section(layout, 'redesign.data.details', key='redesign_data_details', state=self.state)
        self.data_detail = QPlainTextEdit()
        self.data_detail.setReadOnly(True)
        details.addWidget(self.data_detail)
        details.addWidget(self.summary)
        self.data_detail.setMaximumHeight(200)
        self.summary.setMaximumHeight(180)
        self.import_kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()
        self.set_dataset_summary(None)

    def _source(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.sources.addTab(page, title)
        return layout

    def _file_field(self, layout, title, button_title, name):
        label = QLabel(title)
        layout.addWidget(label)
        field = QLineEdit()
        field.setAccessibleName(title)
        label.setBuddy(field)
        row = QHBoxLayout()
        layout.addLayout(row)
        row.addWidget(field, 1)
        self.host.button(row, button_title, name, lambda: self.host.browse(field))
        return field

    def _note(self, layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def _kind_changed(self):
        kind = self.import_kind.currentData()
        needs_contract = kind in ('ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json')
        self.contract.setToolTip(ui_text('redesign.data.contract_hint' if needs_contract else 'redesign.data.contract_filter_hint'))
        self.contract_filter.setVisible(not needs_contract and kind != 'validated_dataset')
        self.contract_box.setVisible(needs_contract or (kind != 'validated_dataset' and self.contract_filter.isChecked()))
        text = ui_text('redesign.data.contract_hint') if needs_contract else ''
        if kind.startswith(('synthetic_', 'proxy_')):
            text = ui_text('redesign.data.classification')
        self.kind_notice.setText(text)
        self.kind_notice.setVisible(bool(text))

    def navigate(self, identity):
        index = page_index(self.state, identity)
        if index >= 0:
            self.state.navigation.setCurrentRow(index)

    def set_dataset_summary(self, data):
        self.next_button.setEnabled(data is not None and not self.state.jobs.active)
        self.current_panel.setVisible(data is not None)
        self.next_button.setVisible(data is not None)
        self.empty_note.setVisible(data is None)
        if data is None:
            self.data_card.setText(ui_text('redesign.data.empty'))
            detail = self.overview.text()
            self.empty_note.setText(detail if detail and detail != ui_text('ui.refresh_views.no_data') else ui_text('redesign.data.empty'))
            self.data_detail.clear()
            return
        manifest = data.manifest
        coverage = manifest.get('coverage', {})
        period = manifest.get('timeframe_minutes')
        if not period and data.bars:
            period = (data.bars[0].end - data.bars[0].timestamp).total_seconds() / 60
            period = int(period) if period.is_integer() else period
        period = ui_text('redesign.data.minutes').format(period) if period else ui_text('redesign.data.period_unknown')
        valid = data.quality.get('valid') is True and not data.quality.get('errors')
        product = manifest.get('product') or ' / '.join(sorted({bar.contract_id for bar in data.bars})[:3]) or '—'
        self.data_card.setText(
            ui_text('redesign.data.summary').format(
                product,
                period,
                len(data.bars),
                taipei_time(coverage.get('start') or (data.bars[0].timestamp if data.bars else None)),
                taipei_time(coverage.get('end') or (data.bars[-1].end if data.bars else None)),
                display_status(manifest.get('source_type', 'unknown')),
                (ui_text('redesign.data.validation') if valid else ui_text('redesign.data.validation_failed'))
                + ' · '
                + ui_text('redesign.data.warnings').format(len(data.quality.get('warnings', ()))),
            )
        )

    def import_market_file(self):
        name, _ = self.host.open_file(ui_text('ui.import_market_file.file_dialog_title'), '', 'JSON / CSV (*.json *.csv)')
        if name:
            provider, format_name = self.market_provider.currentData()
            self.host.start_job('ui_market_refresh', {'provider': provider, 'format': format_name, 'local_path': name})

    def import_market_history(self):
        if self.state.jobs.active:
            raise ValidationError(ui_text('ui.import_market_history.job_busy'))
        if getattr(self.state, '_closing', False):
            raise ValidationError(ui_text('ui.import_market_history.closing_blocked'))
        existing = getattr(self.state, '_history_dialog', None)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        dialog = self.host.market_history_dialog()
        self.state._history_dialog = dialog

        def accepted():
            if not getattr(self.state, '_closing', False):
                self.host.safe(lambda: self.host.start_job('ui_market_refresh', dialog.payload()))

        def finished(_):
            if self.state._history_dialog is dialog:
                self.state._history_dialog = None
            dialog.deleteLater()

        dialog.accepted.connect(accepted)
        dialog.finished.connect(finished)
        dialog.open()

    def import_data(self):
        self.reset_gap_report()
        if not self.import_path.text().strip() or not self.calendar_path.text().strip():
            raise ValidationError(ui_text('ui.import_data.file_calendar_required'))
        self.host.start_job(
            'ui_import',
            {
                'path': self.import_path.text(),
                'calendar': self.calendar_path.text(),
                'kind': self.import_kind.currentData(),
                'contract': ''
                if self.import_kind.currentData().startswith(('synthetic_', 'proxy_'))
                and not self.contract_filter.isChecked()
                and self.import_kind.currentData() != 'synthetic_daily_json'
                else self.contract.text(),
            },
        )

    def download_data(self):
        if not self.network_data.isChecked():
            raise ValidationError(ui_text('ui.download_data.consent_required'))
        payload = {'days': self.days.value(), 'network_opt_in': True}
        settings = self.download_import.request()
        if settings is not None:
            payload['auto_import'] = settings
        self.host.start_job('ui_refresh', payload)
        self.network_data.setChecked(False)

    def show_gap_report(self, report):
        if not report.gaps:
            self.reset_gap_report()
            return
        if self.gap_panel is None:
            self.gap_panel = GapPanel(self)
            self._gap_layout.insertWidget(1, self.gap_panel)
        self.gap_panel.set_report(report)

    def reset_gap_report(self):
        if self.gap_panel is not None:
            self.gap_panel.set_report(GapReport())
