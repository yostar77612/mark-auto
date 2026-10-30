"""Download/import choices; economic validation remains in the existing worker."""

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QLineEdit, QWidget

from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError
from quantlab.desktop_errors import error_message


class DownloadImportControls(QWidget):
    def __init__(self, page, layout):
        super().__init__(page)
        self.page = page
        self.enabled = QCheckBox(ui_text('download_import.enabled'))
        self.enabled.setObjectName('download_auto_import')
        self.enabled.setChecked(True)
        layout.addWidget(self.enabled)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.contract = QLineEdit()
        self.contract.setObjectName('download_import_contract')
        self.contract.setAccessibleName(ui_text('download_import.contract'))
        self.contract.setPlaceholderText(ui_text('download_import.contract_example'))
        form.addRow(ui_text('download_import.contract'), self.contract)
        layout.addWidget(self)
        self.calendar = page._file_field(layout, ui_text('download_import.calendar'), ui_text('download_import.browse_calendar'), 'download_import_calendar')
        self.calendar.setObjectName('download_import_calendar_path')
        self.hint = QLabel(ui_text('download_import.hint'))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.status = QLabel()
        self.status.setObjectName('download_import_status')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.enabled.toggled.connect(self.update_choice)
        self.contract.textChanged.connect(self.invalidate)
        self.calendar.textChanged.connect(self.invalidate)

    def invalidate(self):
        self.page.network_data.setChecked(False)
        self.status.clear()

    def update_choice(self):
        enabled = self.enabled.isChecked()
        self.setEnabled(enabled)
        self.calendar.setEnabled(enabled)
        self.page.download_button.setText(ui_text('download_import.action') if enabled else ui_text('ui.data_page.download_recent'))
        self.page.network_data.setText(ui_text('download_import.consent') if enabled else ui_text('ui.data_page.download_consent'))
        self.invalidate()

    def request(self):
        self.status.clear()
        if not self.enabled.isChecked():
            return None
        calendar, contract = self.calendar.text().strip(), self.contract.text().strip()
        if not calendar or not contract.startswith('TAIFEX:TMF:'):
            self.status.setText(error_message('download_import_settings_required'))
            raise ValidationError('download_import_settings_required')
        return {'calendar': calendar, 'contract': contract, 'confirmed': True}

    def result(self, value):
        imported = value.get('auto_import')
        if imported and imported.get('status') == 'imported':
            self.status.setText(ui_text('download_import.completed').format(value['downloaded_archives'], imported['bars'], imported['contract']))
        elif 'downloaded_archives' in value:
            self.status.setText(ui_text('download_import.downloaded_only').format(value['downloaded_archives']))
