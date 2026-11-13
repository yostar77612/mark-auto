"""One reference-only Sinopac form; accepted facts remain backend-owned."""

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import SinopacConnectionSettings, SinopacConnectionView
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from desktop_app.features.trading import sinopac_panel_text as text
from desktop_app.features.trading.page_help import HelpText
from desktop_app.features.trading.readiness_guidance import ReadinessGuidance, account_guidance, readiness_steps
from desktop_app.features.trading.widgets import button


def _certificate_controls(panel, connected):
    live = panel.view.environment is Environment.LIVE or panel.view.settings.environment is Environment.LIVE
    enabled = connected and not live
    hint = text.reason_text('production_orders_disabled') if live else ui_text('m2.connection.ca_connect_first')
    for widget in (panel.choose_certificate, panel.certificate_secret_ref, panel.certificate_path):
        widget.setEnabled(enabled)
        widget.setToolTip(hint if not enabled else '')
    panel.activate_certificate.setEnabled(
        enabled and bool(panel.certificate_path.text()) and bool(panel.certificate_secret_ref.text()) and panel.view.certificate_status != 'ACTIVATING'
    )
    panel.activate_certificate.setToolTip(ui_text('m2.connection.ca_reference_needed') if enabled else hint)
    panel._paint(
        panel.certificate_status,
        text.reason_text('production_orders_disabled') if live else text.certificate_text(panel.view.certificate_status),
        'BLOCKED' if live else panel.view.certificate_status,
    )


class BrokerPanel(QWidget):
    save_connect_requested = Signal(object, int, str)
    accounts_requested = Signal(object, int, str)
    certificate_requested = Signal(object, int, str)
    disconnect_requested = Signal(int, str)

    def __init__(self, parent=None, *, confirm):
        super().__init__(parent)
        self.setObjectName('sinopac_connection_panel')
        self.setAccessibleName(ui_text('m2.connection.title'))
        self.confirm, self.view = confirm, SinopacConnectionView()
        self._loading, self._initialized, self._busy = False, False, False
        self._connection_dirty, self._certificate_dirty, self._failure = False, False, ''
        self._available = True
        self.account_boxes = {}
        self.account_guidance = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._label(ui_text('m2.connection.title')))
        self.help = HelpText(ui_text('m2.connection.help_short'), ui_text('m2.connection.help_full'), 'sinopac_connection')
        self._layout.addWidget(self.help)
        self._connection_fields()
        self._account_fields()
        self._certificate_fields()
        self._fee_fields()
        ready = QGroupBox(ui_text('m2.connection.readiness'), self)
        form = QVBoxLayout(ready)
        self.readiness_labels = {}
        self.readiness_guidance = {}
        for code in ('market', 'accounts', 'simulation_orders', 'production_orders'):
            guidance = ReadinessGuidance('', readiness_steps(code), 'sinopac_readiness_' + code, ready)
            guidance.summary.setObjectName('sinopac_readiness_' + code)
            self.readiness_labels[code] = guidance.summary
            self.readiness_guidance[code] = guidance
            form.addWidget(guidance)
        self.maintenance_checklist = self._label('')
        self.maintenance_checklist.setObjectName('sinopac_pre_open_checklist')
        form.addWidget(self.maintenance_checklist)
        self._layout.addWidget(ready)
        self.apply(self.view)

    @staticmethod
    def _label(value):
        widget = QLabel(value)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setWordWrap(True)
        return widget

    def _connection_fields(self):
        group = QGroupBox(ui_text('m2.connection.key_step'), self)
        form = QFormLayout(group)
        self.environment = QComboBox(group)
        self.environment.setObjectName('sinopac_environment')
        self.environment.setAccessibleName(ui_text('m2.connection.target'))
        self.environment.addItem(ui_text('v2.broker_sim'), Environment.BROKER_SIMULATION)
        self.environment.addItem(ui_text('v2.live'), Environment.LIVE)
        self.environment.currentIndexChanged.connect(self._changed)
        form.addRow(ui_text('m2.connection.target'), self.environment)
        self.key_ref = QLineEdit(group)
        self.key_ref.setObjectName('sinopac_key_ref')
        self.key_ref.setAccessibleName(ui_text('m2.connection.key'))
        self.key_ref.setMaxLength(120)
        self.key_ref.textEdited.connect(self._changed)
        form.addRow(ui_text('m2.connection.key'), self.key_ref)
        self.key_expiry = QLineEdit(group)
        self.key_expiry.setObjectName('sinopac_key_expiry')
        self.key_expiry.setMaxLength(10)
        self.key_expiry.setPlaceholderText(ui_text('m2.maintenance.expiry_hint'))
        self.key_expiry.setAccessibleName(ui_text('m2.maintenance.expiry'))
        self.key_expiry.textEdited.connect(self._changed)
        form.addRow(ui_text('m2.maintenance.expiry'), self.key_expiry)
        self.key_expiry_status = self._label('')
        form.addRow(self.key_expiry_status)
        self.auto_connect = QCheckBox(ui_text('autoconnect.label'), group)
        self.auto_connect.setObjectName('sinopac_auto_connect')
        self.auto_connect.setAccessibleName(ui_text('autoconnect.label'))
        self.auto_connect.setToolTip(ui_text('autoconnect.hint'))
        form.addRow(self.auto_connect)
        controls = QHBoxLayout()
        self.save_connect = button('m2.connection.save', 'sinopac_save_connect', role='primary')
        self.save_connect.clicked.connect(self._save)
        self.disconnect_button = button('m2.connection.disconnect', 'sinopac_disconnect', role='danger')
        self.disconnect_button.clicked.connect(self._disconnect)
        controls.addWidget(self.save_connect)
        controls.addWidget(self.disconnect_button)
        form.addRow(controls)
        self.status = self._label('')
        self.status.setObjectName('sinopac_connection_status')
        form.addRow(self.status)
        self.draft_notice = self._label(ui_text('m2.connection.draft_notice'))
        form.addRow(self.draft_notice)
        self._layout.addWidget(group)

    def _account_fields(self):
        group = QGroupBox(ui_text('m2.connection.accounts'), self)
        form = QVBoxLayout(group)
        self.account_container = QWidget(group)
        self._accounts_layout = QVBoxLayout(self.account_container)
        self._accounts_layout.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self.account_container)
        self.account_empty = self._label(ui_text('m2.connection.account_empty'))
        form.addWidget(self.account_empty)
        self.account_next = button('m2.connection.back_to_connect', 'sinopac_account_next')
        self.account_next.clicked.connect(lambda: self.key_ref.setFocus())
        form.addWidget(self.account_next)
        self._layout.addWidget(group)

    def _certificate_fields(self):
        self.certificate_group = QGroupBox(ui_text('m2.connection.certificate'), self)
        self.certificate_group.setCheckable(True)
        self.certificate_group.setChecked(False)
        layout = QVBoxLayout(self.certificate_group)
        self.certificate_guidance = ReadinessGuidance('', ui_text('u1.readiness.ca_steps'), 'sinopac_ca', self)
        self.certificate_status = self.certificate_guidance.summary
        self._layout.addWidget(self.certificate_guidance)
        self._certificate_container = QWidget(self.certificate_group)
        form = QFormLayout(self._certificate_container)
        self.certificate_path = QLineEdit(self._certificate_container)
        self.certificate_path.setReadOnly(True)
        self.certificate_path.setAccessibleName(ui_text('m2.connection.ca_file'))
        self.certificate_path.setObjectName('sinopac_certificate_path')
        self.choose_certificate = button('m2.connection.choose_ca', 'sinopac_choose_certificate')
        self.choose_certificate.clicked.connect(self._choose_certificate)
        form.addRow(self.certificate_path, self.choose_certificate)
        self.certificate_secret_ref = QLineEdit(self._certificate_container)
        self.certificate_secret_ref.setObjectName('sinopac_certificate_secret_ref')
        self.certificate_secret_ref.setAccessibleName(ui_text('m2.connection.ca_ref'))
        self.certificate_secret_ref.setMaxLength(120)
        self.certificate_secret_ref.textEdited.connect(self._certificate_changed)
        form.addRow(ui_text('m2.connection.ca_ref'), self.certificate_secret_ref)
        self.activate_certificate = button('m2.connection.activate_ca', 'sinopac_activate_certificate')
        self.activate_certificate.clicked.connect(self._activate_certificate)
        form.addRow(self.activate_certificate)
        layout.addWidget(self._certificate_container)
        self._certificate_container.hide()
        self.certificate_group.toggled.connect(self._certificate_container.setVisible)
        self._layout.addWidget(self.certificate_group)

    def _fee_fields(self):
        self.fee_group = QGroupBox(ui_text('v2.advanced') + ' · ' + ui_text('m2.connection.fee'), self)
        self.fee_group.setCheckable(True)
        self.fee_group.setChecked(False)
        layout = QVBoxLayout(self.fee_group)
        self.fee_discount = QLineEdit(self.fee_group)
        self.fee_discount.setObjectName('sinopac_fee_discount')
        self.fee_discount.setAccessibleName(ui_text('m2.connection.fee'))
        self.fee_discount.setToolTip(ui_text('m2.connection.fee_help'))
        self.fee_discount.textEdited.connect(self._changed)
        layout.addWidget(self.fee_discount)
        self.fee_discount.hide()
        self.fee_group.toggled.connect(self.fee_discount.setVisible)
        self.minimum_fee = QLineEdit(self.fee_group)
        self.minimum_fee.setAccessibleName(ui_text('m2.maintenance.minimum_fee'))
        self.minimum_fee.setToolTip(ui_text('m2.maintenance.minimum_fee'))
        self.tmf_fee = QLineEdit(self.fee_group)
        self.tmf_fee.setAccessibleName(ui_text('m2.maintenance.tmf_fee'))
        self.tmf_fee.setToolTip(ui_text('m2.maintenance.tmf_fee'))
        for widget in (self.minimum_fee, self.tmf_fee):
            widget.setMaxLength(30)
            widget.textEdited.connect(self._changed)
            label = self._label(widget.accessibleName())
            layout.addWidget(label)
            label.hide()
            self.fee_group.toggled.connect(label.setVisible)
            layout.addWidget(widget)
            widget.hide()
            self.fee_group.toggled.connect(widget.setVisible)
        self._layout.addWidget(self.fee_group)

    @property
    def dirty(self):
        return self._connection_dirty or self._certificate_dirty

    def settings(self):
        text = self.key_expiry.text().strip()
        expires_on = date.fromisoformat(text) if text else None
        if expires_on is not None and expires_on.isoformat() != text:
            raise ValueError('ISO expiry date required')
        return SinopacConnectionSettings(
            Environment(self.environment.currentData()),
            self.key_ref.text().strip(),
            self.certificate_path.text().strip(),
            self.certificate_secret_ref.text().strip(),
            Decimal(self.fee_discount.text().strip()),
            expires_on,
            Decimal(self.minimum_fee.text().strip()),
            Decimal(self.tmf_fee.text().strip()),
        )

    def _changed(self):
        if not self._loading:
            self._connection_dirty, self._failure = True, ''
            self.key_expiry_status.setText(ui_text('m2.maintenance.expiry_unknown'))
            self.maintenance_checklist.setText(text.maintenance_text(self.view, reachable=False))
            self._enabled()

    def _certificate_changed(self):
        if not self._loading:
            self._certificate_dirty, self._failure = True, ''
            self._enabled()

    def _save(self):
        try:
            settings = self.settings()
        except (DomainError, InvalidOperation, ValueError):
            self._failure = ui_text('m2.connection.invalid')
            self._enabled()
            return
        self.save_connect_requested.emit(settings, self.view.revision, self.view.generation)

    def _choose_certificate(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('m2.connection.choose_ca'), '', ui_text('m2.connection.ca_filter'))
        if path:
            self.certificate_path.setText(path)
            self._certificate_changed()

    def _activate_certificate(self):
        try:
            settings = self.settings()
        except (DomainError, InvalidOperation, ValueError):
            self._failure = ui_text('m2.connection.invalid')
            self._enabled()
            return
        self.certificate_requested.emit(settings, self.view.revision, self.view.generation)

    def _select_accounts(self):
        selected = tuple(alias for alias, widget in self.account_boxes.items() if widget.isChecked())
        self._update_accounts()
        self.accounts_requested.emit(selected, self.view.revision, self.view.generation)

    def _disconnect(self):
        scope = self.view.revision, self.view.generation
        if self.confirm(ui_text('m2.connection.disconnect_confirm')):
            if scope == (self.view.revision, self.view.generation):
                self.disconnect_requested.emit(*scope)
            else:
                self._failure = ui_text('m2.connection.state_conflict')
                self._enabled()

    def set_busy(self, value):
        self._busy = value
        if value:
            self._failure = ''
        self._enabled()

    def apply(self, view):
        if view.revision < self.view.revision:
            return
        if self._initialized and view == self.view and self._available:
            self._enabled()
            return
        self.view, self._failure, self._loading = view, '', True
        self._available = True
        if not self._connection_dirty:
            self.environment.setCurrentIndex(self.environment.findData(view.settings.environment))
            self.key_ref.setText(view.settings.key_ref)
            self.key_expiry.setText(view.settings.api_key_expires_on.isoformat() if view.settings.api_key_expires_on else '')
            self.fee_discount.setText(str(view.settings.fee_discount))
            self.minimum_fee.setText(str(view.settings.minimum_fee))
            self.tmf_fee.setText(str(view.settings.tmf_fee_per_contract))
        if not self._certificate_dirty:
            self.certificate_path.setText(view.settings.certificate_path)
            self.certificate_secret_ref.setText(view.settings.certificate_secret_ref)
        self.key_expiry_status.setText(ui_text('m2.maintenance.expiry_unknown') if self._connection_dirty else text.expiry_text(view))
        self.maintenance_checklist.setText(text.maintenance_text(view, reachable=not self._connection_dirty))
        self._loading, self._initialized = False, True
        self._update_accounts()
        for item in view.readiness:
            self._paint(self.readiness_labels[item.code], text.readiness_text(item), 'BLOCKED' if item.code == 'production_orders' else item.state)
        self._enabled()

    def unavailable(self):
        self._available = False
        self._failure = ui_text('m2.connection.outcome_unknown')
        for item in self.view.readiness:
            self._paint(
                self.readiness_labels[item.code], text.readiness_text(item, reachable=False), 'BLOCKED' if item.code == 'production_orders' else 'UNKNOWN'
            )
        self.key_expiry_status.setText(ui_text('m2.maintenance.expiry_unknown'))
        self.maintenance_checklist.setText(text.maintenance_text(self.view, reachable=False))
        self._paint(self.certificate_status, ui_text('m2.connection.unknown'), 'UNKNOWN')
        self._enabled()

    def _update_accounts(self):
        aliases = {item.alias for item in self.view.accounts}
        for alias in self.account_boxes.keys() - aliases:
            self.account_boxes.pop(alias).deleteLater()
            self.account_guidance.pop(alias).deleteLater()
        for item in self.view.accounts:
            widget = self.account_boxes.get(item.alias)
            if widget is None:
                widget = QCheckBox(self.account_container)
                widget.setObjectName('sinopac_account_' + item.alias)
                widget.toggled.connect(self._select_accounts)
                self.account_boxes[item.alias] = widget
                self.account_guidance[item.alias] = ReadinessGuidance('', '', 'sinopac_account_' + item.alias, self.account_container)
            with QSignalBlocker(widget):
                widget.setChecked(item.selected)
            widget.setText(text.account_text(item))
            widget.setAccessibleName(widget.text())
            widget.setToolTip(text.reason_text(item.reason))
            self._accounts_layout.removeWidget(widget)
            self._accounts_layout.addWidget(widget)
            guidance = self.account_guidance[item.alias]
            guidance.set_content(*account_guidance(item.signed))
            self._accounts_layout.removeWidget(guidance)
            self._accounts_layout.addWidget(guidance)
        self.account_empty.setVisible(not self.view.accounts)
        self.account_next.setVisible(not self.view.accounts)

    def complete(self, command, receipt):
        if receipt.accepted:
            if command.sinopac_settings is not None:
                try:
                    if self.settings() == command.sinopac_settings == self.view.settings:
                        self._connection_dirty = self._certificate_dirty = False
                except (DomainError, InvalidOperation, ValueError):
                    pass  # A newer invalid user draft must survive the old receipt.
        else:
            self._failure = text.reason_text(receipt.code)
        self._update_accounts()
        self._enabled()

    @staticmethod
    def _paint(widget, value, status):
        widget.setText(value)
        widget.setAccessibleName(value)
        widget.setProperty('sinopacStatus', status)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _enabled(self):
        busy = self._busy or self.view.phase in ('CONNECTING', 'DISCONNECTING')
        connected = self._available and self.view.phase == 'CONNECTED' and not self._connection_dirty and not busy
        for widget in (self.environment, self.key_ref, self.key_expiry, self.fee_discount, self.minimum_fee, self.tmf_fee, self.save_connect):
            widget.setEnabled(not busy)
        self.disconnect_button.setEnabled(not self._busy and self.view.phase in ('CONNECTED', 'CONNECTING'))
        _certificate_controls(self, connected)
        self.save_connect.setToolTip(ui_text('m2.connection.busy') if busy else ui_text('m2.connection.help_short'))
        for item in self.view.accounts:
            widget = self.account_boxes[item.alias]
            widget.setEnabled(connected and item.selectable)
            hint = (
                ui_text('m2.connection.busy')
                if busy
                else ui_text('m2.connection.draft_notice')
                if self._connection_dirty
                else ui_text('m2.connection.connect_first')
            )
            widget.setToolTip(text.reason_text(item.reason) or (hint if not widget.isEnabled() else ''))
        self.draft_notice.setVisible(self.dirty)
        message = ui_text('m2.connection.busy') if self._busy else self._failure or text.phase_text(self.view)
        self._paint(self.status, message, 'CONNECTING' if self._busy else 'FAILED' if self._failure or self.view.error_code else self.view.phase)
