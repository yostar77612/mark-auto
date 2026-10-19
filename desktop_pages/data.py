from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QPlainTextEdit, QCheckBox, QSpinBox, QFileDialog
from desktop_strings import ui_text
from quantlab.core import ValidationError
from desktop_market import MarketHistoryDialog
from .host import PageHost


class DataPage(QWidget):
    def __init__(self, host: PageHost):
        super().__init__()
        self.host = host
        self.state = host.state
        self.overview = QLabel()
        self.data_card = QLabel()
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout = self.host.mount_page(self, ui_text('ui._data_page.text_1'))
        layout.addWidget(self.overview)
        self.market_provider = QComboBox()
        self.market_provider.addItem(ui_text('ui._data_page.text_2'), ('twse', 'json'))
        self.market_provider.addItem(ui_text('ui._data_page.text_3'), ('taifex', 'json'))
        self.market_provider.addItem(ui_text('ui._data_page.text_4'), ('taifex', 'csv'))
        layout.addWidget(self.market_provider)
        self.host.button(layout, ui_text('ui._data_page.text_5'), 'import_market_file', self.import_market_file)
        self.host.button(layout, ui_text('ui._data_page.text_6'), 'import_market_history', self.import_market_history)
        self.import_path = self.host.text(layout, ui_text('ui._data_page.text_7'))
        self.host.button(layout, ui_text('ui._data_page.text_8'), 'browse_data', lambda: self.host.browse(self.import_path))
        self.calendar_path = self.host.text(layout, ui_text('ui._data_page.text_9'))
        self.host.button(layout, ui_text('ui._data_page.text_10'), 'browse_calendar', lambda: self.host.browse(self.calendar_path))
        self.import_kind = QComboBox()
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
        layout.addWidget(self.import_kind)
        self.host.button(layout, ui_text('ui._data_page.text_12'), 'import_data', self.import_data, role='primary')
        self.bars = QSpinBox()
        self.bars.setRange(120, 10000)
        self.bars.setValue(960)
        layout.addWidget(self.bars)
        self.host.button(layout, ui_text('ui._data_page.text_13'), 'create_demo', lambda: self.host.start_job('ui_demo', {'bars': self.bars.value()}))
        self.network_data = QCheckBox(ui_text('ui._data_page.text_14'))
        layout.addWidget(self.network_data)
        self.days = QSpinBox()
        self.days.setRange(1, 30)
        layout.addWidget(self.days)
        self.host.button(layout, ui_text('ui._data_page.text_15'), 'refresh_data', self.download_data)
        details = self.host.advanced(layout)
        self.contract = self.host.text(details, ui_text('ui._data_page.text_11'), 'TAIFEX:TMF:202601')
        self.data_detail = QPlainTextEdit()
        self.data_detail.setReadOnly(True)
        details.addWidget(self.data_detail)
        details.addWidget(self.summary)

    def import_market_file(self):
        name, _ = self.host.open_file(ui_text('ui.import_market_file.text_1'), '', 'JSON / CSV (*.json *.csv)')
        if name:
            provider, format_name = self.market_provider.currentData()
            self.host.start_job('ui_market_refresh', {'provider': provider, 'format': format_name, 'local_path': name})

    def import_market_history(self):
        if self.state.jobs.active:
            raise ValidationError(ui_text('ui.import_market_history.text_1'))
        if getattr(self.state, '_closing', False):
            raise ValidationError(ui_text('ui.import_market_history.text_2'))
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
        if not self.import_path.text().strip() or not self.calendar_path.text().strip():
            raise ValidationError(ui_text('ui.import_data.text_1'))
        self.host.start_job(
            'ui_import',
            {'path': self.import_path.text(), 'calendar': self.calendar_path.text(), 'kind': self.import_kind.currentData(), 'contract': self.contract.text()},
        )

    def download_data(self):
        if not self.network_data.isChecked():
            raise ValidationError(ui_text('ui.download_data.text_1'))
        self.host.start_job('ui_refresh', {'days': self.days.value(), 'network_opt_in': True})
        self.network_data.setChecked(False)
