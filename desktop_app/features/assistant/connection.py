from quantlab.desktop_errors import exception_code
from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QMessageBox
from desktop_app.features.assistant.connection_presenter import ConnectionController, STATE_LABELS
from quantlab.assistant.application.connection_contracts import CONNECTED_STATES, RECOVERABLE_PAUSES, SubscriptionOptions

USAGE_SETTINGS_URL = 'https://chatgpt.com/settings/usage'


class ChatGPTConnectionPanel(QWidget):
    """Traditional Chinese standalone settings panel; no credentials in widgets."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller or ConnectionController(self)
        self._rendered_active = None
        self._included_usage_registration = None
        self._primary_flow = None
        self._restore_flow = None
        self.setObjectName('chatgpt_subscription_panel')
        layout = QVBoxLayout(self)
        title = QLabel(ui_text('chatgpt_ui.init.title'))
        layout.addWidget(title)
        self.disclosure = QLabel(ui_text('chatgpt_ui.init.included_usage_hint'))
        self.disclosure.setWordWrap(True)
        self.disclosure.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.disclosure)
        self.consent = QCheckBox(ui_text('chatgpt_ui.init.connection_consent'))
        layout.addWidget(self.consent)
        self.included_usage_only = QCheckBox(ui_text('chatgpt_ui.init.included_usage_consent'))
        self.included_usage_only.setObjectName('chatgpt_included_usage_only')
        layout.addWidget(self.included_usage_only)
        self.included_usage_only.toggled.connect(self._confirm_included_usage)
        self.manage_usage = QPushButton(ui_text('chatgpt_ui.init.usage_settings'))
        layout.addWidget(self.manage_usage)
        self.manage_usage.clicked.connect(self._open_usage_settings)
        self.active_account = QLabel(ui_text('chatgpt_ui.init.signed_out'))
        self.active_account.setTextFormat(Qt.TextFormat.PlainText)
        self.active_account.setWordWrap(True)
        layout.addWidget(self.active_account)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.primary_sign_in = QPushButton(ui_text('chatgpt_ui.init.primary_sign_in'))
        self.primary_sign_in.setObjectName('chatgpt_primary_sign_in')
        layout.addWidget(self.primary_sign_in)
        self.primary_sign_in.clicked.connect(lambda: self._safe(self._start_primary_sign_in))
        self.account = QComboBox()
        self.account.setAccessibleName(ui_text('chatgpt_ui.init.saved_connections'))
        layout.addWidget(self.account)
        self.advanced_toggle = QPushButton(ui_text('chatgpt_ui.init.advanced_management'))
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.advanced_toggle.toggled.connect(self._render)
        self.buttons = {}
        for action, label in [
            ('list', ui_text('chatgpt_ui.init.read_local')),
            ('initialize', ui_text('chatgpt_ui.init.initialize_identity')),
            ('begin', ui_text('chatgpt_ui.init.add_connection')),
            ('reauthorize', ui_text('chatgpt_ui.init.reauthorize')),
            ('enable_plan', ui_text('chatgpt_ui.init.enable_usage')),
            ('select', ui_text('chatgpt_ui.init.switch_connection')),
            ('refresh', ui_text('chatgpt_ui.init.refresh_connection')),
            ('models', ui_text('chatgpt_ui.init.fetch_models')),
            ('sign_out', ui_text('chatgpt_ui.init.logout')),
            ('clear_pause', ui_text('chatgpt_ui.init.resume_known_pause')),
            ('inspect_unknown', ui_text('chatgpt_reconciliation.inspect')),
        ]:
            button = QPushButton(label)
            button.setObjectName('chatgpt_' + action)
            (layout if action in ('select', 'models', 'sign_out', 'enable_plan', 'inspect_unknown') else advanced_layout).addWidget(button)
            self.buttons[action] = button
            button.clicked.connect(lambda checked=False, a=action: self._act(a))
        self.open_button = QPushButton(ui_text('chatgpt_ui.init.continue_authorization'))
        self.open_button.setObjectName('chatgpt_open_official')
        advanced_layout.addWidget(self.open_button)
        self.open_button.clicked.connect(lambda: self._safe(self.controller.open_authorization))
        self.cancel_button = QPushButton(ui_text('chatgpt_ui.init.cancel_wait'))
        layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self._cancel_primary)
        form = QFormLayout()
        self.model_form = form
        layout.addLayout(form)
        self.model = QComboBox()
        form.addRow(ui_text('chatgpt_ui.init.available_models'), self.model)
        self.max_calls = QSpinBox()
        self.max_calls.setRange(0, 100)
        form.addRow(ui_text('chatgpt_ui.init.request_limit'), self.max_calls)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 120)
        self.timeout.setValue(30)
        form.addRow(ui_text('chatgpt_ui.init.timeout_seconds'), self.timeout)
        self.usage = QLabel()
        self.usage.setWordWrap(True)
        layout.addWidget(self.usage)
        self.controller.changed.connect(self._render)
        self.controller.request_finished.connect(self._primary_finished)
        self.account.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self.controller.invalidate_campaign_usage)
        self.max_calls.valueChanged.connect(self._reset_included_usage)
        self.max_calls.valueChanged.connect(self.controller.invalidate_campaign_usage)
        self.timeout.valueChanged.connect(self._reset_included_usage)
        self.timeout.valueChanged.connect(self.controller.invalidate_campaign_usage)
        for index, widget in enumerate((self.primary_sign_in, self.active_account, self.status, self.account), 1):
            layout.removeWidget(widget)
            layout.insertWidget(index, widget)
        layout.addStretch(1)
        self._render()
        from desktop_app.features.assistant.connection_test import ConnectionTest

        self.connection_test = ConnectionTest(self)
        from desktop_app.features.assistant.chatgpt_reconciliation import ReconciliationFlow

        self.reconciliation = ReconciliationFlow(self)

    def _start_primary_sign_in(self):
        c = self.controller
        if not c.host_available or c.busy:
            raise ValueError('connection is busy')
        self._reset_included_usage()
        self._primary_flow = {
            'phase': 'list',
            'request_id': c._counter + 1,
            'selected': self.account.currentData(),
            'browser_queued': False,
            'reauthorize': c.outcome == 'auth_expired',
        }
        try:
            c.request('list')
        except Exception:
            self._primary_flow = None
            raise

    def start_auto_restore(self):
        """Startup: reload the saved login and refresh it once if expired.

        Runs one startup 'restore' job that may use the network; the worker refreshes only the active
        registration, only when it is refresh_required. Failures leave the
        verified vault state, which shows the sign-in button again.
        """
        c = self.controller
        if not c.host_available or c.busy or self._primary_flow is not None:
            return None
        request = c.request('restore')
        self._restore_flow = request.request_id
        return request

    def _primary_finished(self, request, succeeded):
        if self._restore_flow is not None and request.request_id == self._restore_flow:
            self._restore_flow = None
            return
        flow = self._primary_flow
        if flow is None or request.request_id != flow['request_id']:
            return
        if not succeeded or flow['phase'] != 'list':
            self._primary_flow = None
            return
        QTimer.singleShot(0, lambda: self._safe(lambda: self._continue_primary(request.request_id)))

    def _continue_primary(self, request_id):
        c = self.controller
        flow = self._primary_flow
        if flow is None or flow['request_id'] != request_id or c.busy or (flow['phase'] != 'list'):
            return
        action = 'begin'
        registration = flow['selected']
        if c.state == 'host_initialization_required':
            answer = QMessageBox.question(
                self,
                ui_text('chatgpt_ui.continue_primary.first_sign_in_title'),
                ui_text('chatgpt_ui.continue_primary.initialize_or_recover_question'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if self._primary_flow is not flow:
                return
            if answer != QMessageBox.StandardButton.Yes:
                self._primary_flow = None
                return
            action = 'first_sign_in'
            registration = None
        else:
            refs = {ref for ref, _ in c.registrations}
            if registration not in refs:
                registration = c.active_registration
            if registration is None and len(refs) == 1:
                registration = next(iter(refs))
            if registration is None and len(refs) > 1:
                self._primary_flow = None
                self.status.setText(ui_text('chatgpt_ui.continue_primary.connection_required'))
                return
            if registration == c.active_registration and c.state in CONNECTED_STATES and (not flow.get('reauthorize')):
                self._primary_flow = None
                return
            if registration == c.active_registration and c.state == 'refresh_required' and (not flow.get('reauthorize')):
                self._primary_flow = None
                c.request('refresh', registration, confirmed=True)
                return
        flow.update(phase='authorization', request_id=c._counter + 1, browser_queued=False)
        try:
            c.request(action, registration, confirmed=True)
        except Exception:
            self._primary_flow = None
            raise

    def _open_primary_authorization(self, request_id):
        c = self.controller
        flow = self._primary_flow
        if (
            flow is None
            or flow['request_id'] != request_id
            or (not c.busy)
            or c.stopping
            or (c._request is None)
            or (c._request.request_id != request_id)
            or (c._authorization_url is None)
        ):
            return
        self._safe(c.open_authorization)

    @property
    def primary_sign_in_pending(self):
        """Host schedulers must include the post-join queued authorization gap."""
        return self._primary_flow is not None

    def abandon_primary_sign_in(self):
        self._primary_flow = None
        self._restore_flow = None
        reconciliation = getattr(self, 'reconciliation', None)
        if reconciliation is not None:
            reconciliation.abandon()

    def _cancel_primary(self):
        self.abandon_primary_sign_in()
        self.controller.cancel()

    def hideEvent(self, event):
        self.abandon_primary_sign_in()
        super().hideEvent(event)

    def _reset_included_usage(self, *_):
        self._included_usage_registration = None
        self.included_usage_only.setChecked(False)

    def _confirm_included_usage(self, checked):
        c = self.controller
        if checked and c.state == 'plan_ready' and c.active_registration and (not c.busy) and (self.account.currentData() == c.active_registration):
            self._included_usage_registration = c.active_registration
        else:
            self._reset_included_usage()

    def _open_usage_settings(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl(USAGE_SETTINGS_URL)):
            self.status.setText(ui_text('chatgpt_ui.open_usage_settings.browser_failed'))

    def _safe(self, call):
        try:
            return call()
        except Exception as exc:
            self.controller.show_outcome(exception_code(exc))

    def _act(self, action):
        self.abandon_primary_sign_in()
        if action == 'inspect_unknown':
            return self._safe(self.reconciliation.start)

        def run():
            if action != 'list' and (not self.consent.isChecked()):
                raise ValueError('consent required')
            registration = (
                self.account.currentData() if action in ('reauthorize', 'enable_plan', 'select', 'sign_out', 'refresh', 'models', 'clear_pause') else None
            )
            if action == 'models' and registration != self.controller.active_registration:
                raise ValueError('select account first')
            if action == 'clear_pause' and (not self.controller.account_status_known or self.controller.unknown_count or self.controller.account_pending):
                raise ValueError('unknown reservations cannot clear')
            result = self.controller.request('begin' if action == 'reauthorize' else action, registration, confirmed=self.consent.isChecked())
            self.consent.setChecked(False)
            return result

        return self._safe(run)

    def _render(self):
        c = self.controller
        self.status.setText(c.message)
        if c.busy or c.state != 'plan_ready' or self._rendered_active != c.active_registration:
            self._reset_included_usage()
        selected = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        labels = dict(c.account_labels)
        for reference, state in c.registrations:
            label = labels.get(
                reference,
                ui_text('chatgpt_ui.render.unverified_registration')
                if state == 'registration_retry_required'
                else ui_text('chatgpt_ui.render.saved_connection'),
            )
            self.account.addItem(ui_text('chatgpt_ui.render.masked_connection').format(label, reference[-8:], STATE_LABELS[state]), reference)
        self.active_account.setText(
            ui_text('chatgpt_ui.render.signed_in').format(labels.get(c.active_registration, ui_text('chatgpt_ui.render.saved_account')))
            if c.active_registration is not None
            else ui_text('chatgpt_ui.render.signed_out')
        )
        selection = c.active_registration if c.active_registration != self._rendered_active else selected or c.active_registration
        self._rendered_active = c.active_registration
        index = self.account.findData(selection)
        if index >= 0:
            self.account.setCurrentIndex(index)
        self.account.blockSignals(False)
        chosen = self.model.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        labels = dict(c.model_labels)
        for slug in c.models:
            self.model.addItem(labels.get(slug, slug), slug)
        if chosen in c.models:
            self.model.setCurrentIndex(self.model.findData(chosen))
        self.model.blockSignals(False)
        ready = c.host_available and (not c.busy)
        self.primary_sign_in.setEnabled(ready)
        signed_in = c.active_registration is not None and c.state in CONNECTED_STATES
        self.primary_sign_in.setVisible(not signed_in or c.outcome == 'auth_expired')
        self.primary_sign_in.setText(ui_text('outcome.auth_expired.action') if c.outcome == 'auth_expired' else ui_text('chatgpt_ui.init.primary_sign_in'))
        self.buttons['enable_plan'].setVisible(c.state == 'identity_only')
        self.buttons['select'].setVisible(len(c.registrations) > 1)
        self.buttons['models'].setVisible(c.state == 'plan_ready')
        self.buttons['sign_out'].setVisible(c.active_registration is not None)
        self.cancel_button.setVisible(c.busy)
        self.consent.setVisible(c.active_registration is not None or self.advanced_toggle.isChecked())
        self.included_usage_only.setVisible(c.state == 'plan_ready')
        for row in range(3):
            self.model_form.setRowVisible(row, c.state == 'plan_ready')
        flow = self._primary_flow
        if (
            flow is not None
            and flow['phase'] == 'authorization'
            and (not flow['browser_queued'])
            and (c._request is not None)
            and (c._request.request_id == flow['request_id'])
            and (c._authorization_url is not None)
            and c.busy
            and (not c.stopping)
        ):
            flow['browser_queued'] = True
            QTimer.singleShot(0, lambda rid=flow['request_id']: self._open_primary_authorization(rid))
        for action, button in self.buttons.items():
            button.setEnabled(ready and (action in ('list', 'initialize', 'begin') or self.account.count() > 0))
        self.buttons['enable_plan'].setEnabled(ready and c.state == 'identity_only' and (c.active_registration is not None))
        self.included_usage_only.setEnabled(ready and c.state == 'plan_ready' and (c.active_registration is not None))
        self.buttons['models'].setEnabled(ready and c.state == 'plan_ready' and c.account_status_known and (not c.account_paused) and (not c.account_pending))
        inspection_visible = c.account_status_known and c.account_state == 'reserved_unknown' and c.account_pending
        self.buttons['inspect_unknown'].setVisible(inspection_visible)
        self.buttons['inspect_unknown'].setEnabled(
            ready and (not c.background_busy) and inspection_visible and (self.account.currentData() == c.active_registration)
        )
        self.buttons['inspect_unknown'].setToolTip(ui_text('chatgpt_reconciliation.disabled'))
        self.buttons['clear_pause'].setEnabled(
            ready
            and self.account.count() > 0
            and (c.account_state in RECOVERABLE_PAUSES)
            and c.account_status_known
            and (not c.unknown_count)
            and (not c.account_pending)
        )
        self.open_button.setEnabled(c.busy and (not c.stopping) and (c._authorization_url is not None))
        self.cancel_button.setEnabled(c.busy and (not c.stopping))
        self.account.setEnabled(ready)
        self.model.setEnabled(ready)
        self.usage.setText(
            ui_text('chatgpt_ui.render.request_record_unknown')
            if not c.usage_known
            else ui_text('chatgpt_ui.render.reserved_requests').format(c.reserved_count, c.unknown_count)
        )
        if c.account_status_known:
            barrier = (
                ui_text('chatgpt_ui.render.unresolved_requests')
                if c.account_pending
                else ui_text('chatgpt_ui.render.account_paused')
                if c.account_paused
                else ui_text('chatgpt_ui.render.local_not_paused_disclaimer')
            )
            self.usage.setText(self.usage.text() + '\n' + barrier)

    def build_plan_options(self):
        c = self.controller
        if (
            c.busy
            or c.state != 'plan_ready'
            or (not c.active_registration)
            or (not c.account_status_known)
            or c.account_paused
            or c.account_pending
            or (not c.usage_known)
            or c.unknown_count
        ):
            raise ValueError('subscription is not ready')
        if not self.consent.isChecked() or self.model.currentData() not in c.models:
            raise ValueError('explicit consent and discovered model required')
        if (
            not self.included_usage_only.isChecked()
            or self._included_usage_registration != c.active_registration
            or self.account.currentData() != c.active_registration
        ):
            raise ValueError('included usage only confirmation required for this account')
        result = SubscriptionOptions(
            c.active_registration,
            self.model.currentData(),
            self.max_calls.value(),
            self.timeout.value(),
            network_opt_in=True,
            included_usage_policy_confirmed=True,
        )
        self.consent.setChecked(False)
        self._reset_included_usage()
        return result

    def preferences(self):
        return {'version': 1, 'max_calls': self.max_calls.value(), 'timeout_seconds': self.timeout.value()}

    def restore_preferences(self, value):
        if not isinstance(value, dict) or set(value) != {'version', 'max_calls', 'timeout_seconds'} or value['version'] != 1:
            raise ValueError('invalid connection preferences')
        for key, minimum, maximum in [('max_calls', 0, 100), ('timeout_seconds', 1, 120)]:
            if type(value[key]) is not int or not minimum <= value[key] <= maximum:
                raise ValueError('invalid bounded preference')
        self.max_calls.setValue(value['max_calls'])
        self.timeout.setValue(value['timeout_seconds'])
        self.consent.setChecked(False)
        self._reset_included_usage()

    def closeEvent(self, event):
        self.abandon_primary_sign_in()
        if self.controller.busy:
            self.controller.cancel()
            event.ignore()
        else:
            event.accept()
