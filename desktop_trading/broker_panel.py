"""Reference-only configuration; UI never opens a certificate or credential store."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from desktop_strings import ui_text
from quantlab.trading.application.contracts import BrokerReadiness, BrokerSettings
from quantlab.trading.domain.models import Environment

from .widgets import button, label, rows, table


FIELDS = (
    ('profile_alias', 'v2.broker_profile'),
    ('stock_account_ref', 'v2.broker_stock_alias'),
    ('futures_account_ref', 'v2.broker_futures_alias'),
    ('broker_secret_ref', 'v2.broker_secret_reference'),
    ('account_mapping_ref', 'v2.broker_account_mapping'),
    ('certificate_ref', 'v2.broker_certificate_reference'),
    ('certificate_secret_ref', 'v2.broker_certificate_secret'),
    ('instrument_spec_ref', 'v2.broker_instrument_reference'),
    ('calendar_ref', 'v2.broker_calendar_reference'),
    ('fee_schedule_ref', 'v2.broker_fee_reference'),
    ('capability_proof_ref', 'v2.broker_capability_reference'),
    ('sdk_version', 'v2.broker_sdk_version'),
)
CHECK_KEYS = {
    'sdk_version': 'v2.broker_sdk_version',
    'account_selection': 'v2.broker_account_selection',
    'broker_secret_ref': 'v2.broker_secret_reference',
    'account_mapping_ref': 'v2.broker_account_mapping',
    'instrument_spec_ref': 'v2.broker_instrument_reference',
    'calendar_ref': 'v2.broker_calendar_reference',
    'fee_schedule_ref': 'v2.broker_fee_reference',
    'capability_proof_ref': 'v2.broker_capability_reference',
    'certificate_ref': 'v2.broker_certificate_reference',
    'certificate_secret_ref': 'v2.broker_certificate_secret',
    'execution_default_disabled': 'v2.broker_execution_disabled',
    'external_account_verified': 'v2.broker_external_account',
    'external_capability_verified': 'v2.broker_external_capability',
    'external_broker_simulation_verified': 'v2.broker_external_simulation',
    'external_ca_verified': 'v2.broker_external_ca',
}


class BrokerPanel(QWidget):
    save_requested = Signal(object)
    check_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('broker_readiness_panel')
        self.dirty = False
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('v2.broker_title'))
        self.status = QLabel(ui_text('v2.broker_not_checked'))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setObjectName('broker_readiness_status')
        layout.addWidget(self.status)
        layout.addWidget(label('v2.broker_reference_hint'))
        self.group = QGroupBox(ui_text('v2.broker_configuration'))
        self.group.setCheckable(True)
        self.group.setChecked(False)
        group_layout = QVBoxLayout(self.group)
        self.content = QWidget()
        form = QFormLayout(self.content)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.environment = QComboBox()
        self.environment.setObjectName('broker_environment')
        self.environment.setAccessibleName(ui_text('v2.broker_environment'))
        self.environment.addItem(ui_text('v2.broker_sim'), Environment.BROKER_SIMULATION)
        self.environment.addItem(ui_text('v2.live'), Environment.LIVE)
        self.environment.currentIndexChanged.connect(self._edited)
        form.addRow(ui_text('v2.broker_environment'), self.environment)
        self.fields: dict[str, QLineEdit] = {}
        for name, key in FIELDS:
            field = QLineEdit()
            field.setObjectName('broker_' + name)
            field.setAccessibleName(ui_text(key))
            field.setMaxLength(1000)
            field.textEdited.connect(self._edited)
            if name == 'sdk_version':
                field.setReadOnly(True)
            self.fields[name] = field
            form.addRow(ui_text(key), field)
        form.addRow(label('v2.broker_local_only'))
        save = button('v2.broker_save', 'broker_save_button')
        save.clicked.connect(self._save)
        form.addRow(save)
        group_layout.addWidget(self.content)
        self.content.setVisible(False)
        self.group.toggled.connect(self.content.setVisible)
        layout.addWidget(self.group)
        check = button('v2.broker_check', 'broker_check_button')
        check.clicked.connect(self._check)
        layout.addWidget(check)
        self.checks = table(('v2.broker_check_item', 'v2.state', 'v2.broker_next_step'), 'broker_readiness_checks')
        layout.addWidget(self.checks)

    def _edited(self) -> None:
        if not self._loading:
            self.dirty = True

    def settings(self) -> BrokerSettings:
        value = lambda name: self.fields[name].text().strip()
        return BrokerSettings(
            profile_alias=value('profile_alias'),
            environment=Environment(self.environment.currentData()),
            stock_account_ref=value('stock_account_ref'),
            futures_account_ref=value('futures_account_ref'),
            account_mapping_ref=value('account_mapping_ref'),
            broker_secret_ref=value('broker_secret_ref'),
            certificate_ref=value('certificate_ref'),
            certificate_secret_ref=value('certificate_secret_ref'),
            instrument_spec_ref=value('instrument_spec_ref'),
            calendar_ref=value('calendar_ref'),
            fee_schedule_ref=value('fee_schedule_ref'),
            capability_proof_ref=value('capability_proof_ref'),
            sdk_version=value('sdk_version'),
            read_only=True,
            execution_enabled=False,
        )

    def _save(self) -> None:
        try:
            settings = self.settings()
        except ValueError:
            self.status.setText(ui_text('v2.broker_form_invalid'))
            return
        self.save_requested.emit(settings)

    def _check(self) -> None:
        if self.dirty:
            self.status.setText(ui_text('v2.broker_save_first'))
            return
        self.check_requested.emit()

    def apply(self, settings: BrokerSettings, readiness: BrokerReadiness | None) -> None:
        if not self.dirty:
            self._loading = True
            self.environment.setCurrentIndex(self.environment.findData(settings.environment))
            for name, _ in FIELDS:
                self.fields[name].setText(getattr(settings, name))
            self._loading = False
        if readiness is None:
            self.status.setText(ui_text('v2.broker_not_checked'))
            rows(self.checks, ())
            return
        self.status.setText(ui_text('v2.broker_local_complete' if readiness.local_ready else 'v2.broker_local_incomplete'))
        rows(
            self.checks,
            tuple(
                (
                    check.code,
                    (
                        ui_text(CHECK_KEYS.get(check.code, 'v2.broker_check_item')),
                        ui_text(
                            'v2.broker_external_pending'
                            if check.external_required
                            else 'v2.broker_metadata_passed'
                            if check.passed
                            else 'v2.broker_metadata_missing'
                        ),
                        ui_text(
                            'v2.broker_external_next' if check.external_required else 'v2.broker_metadata_next' if not check.passed else 'v2.broker_no_action'
                        ),
                    ),
                )
                for check in readiness.checks
            ),
        )
