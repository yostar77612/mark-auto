"""Workspace settings, local backups and the ChatGPT connection panel."""

from desktop_app.strings.catalog import ui_text
from pathlib import Path
from quantlab.core import ValidationError
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QApplication
from desktop_app.shell.bindings import PageContext
from desktop_app.features.settings.preferences import disclosure_value, load_store, save_preferences, restore_preferences


class SettingsPage(PageContext, QWidget):
    def __init__(self, host):
        super().__init__()
        self.setup_context(host)
        layout = self.host.mount_page(self, ui_text('ui.settings_page.title'))
        from desktop_app.features.settings.settings_layout import build_settings

        build_settings(self, layout)
        self.chatgpt_controller.set_host_available(True)
        self.chatgpt_controller.quiesce_requested.connect(self._chatgpt_quiesce)
        self.chatgpt_controller.request_ready.connect(self._chatgpt_dispatch)
        self.chatgpt_controller.cancel_requested.connect(self._chatgpt_cancel)
        self.chatgpt_controller.browser_requested.connect(self._chatgpt_open_browser)

    def auto_restore_chatgpt(self):
        """Startup only: reload the saved ChatGPT login once background work is idle."""
        self._pending_chatgpt_restore = True

    def show_chatgpt_sign_in(self):
        """One research entry to the existing official connection panel."""
        self.connection_toggle.setChecked(True)
        self.provider_mode.setCurrentIndex(self.provider_mode.findData('chatgpt_plan'))
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if page.isAncestorOf(self.chatgpt_panel):
                self.navigation.setCurrentRow(index)
                self.chatgpt_panel.primary_sign_in.setFocus()
                # The panel is taller than one viewport: show its title and
                # consent disclosure, rather than centering a clipped widget.
                page.verticalScrollBar().setValue(self.chatgpt_panel.mapTo(page.widget(), self.chatgpt_panel.rect().topLeft()).y())
                page.horizontalScrollBar().setValue(0)
                self.status.setText(ui_text('ui.show_chatgpt_sign_in.checking_connection'))
                self.chatgpt_panel.primary_sign_in.click()
                return
        raise ValidationError(ui_text('ui.show_chatgpt_sign_in.connection_panel_missing'))

    def _chatgpt_quiesce(self, request):
        try:
            self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # The original analysis tree is joined, but its local evidence
                # reconciliation owns the slot. This auth request was never
                # dispatched: fail it explicitly rather than strand or queue it.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self.status.setText(ui_text('ui.chatgpt_quiesce.stop_record_checking'))
                return
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=not self.jobs.active)
        except Exception:
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=False)

    def _chatgpt_dispatch(self, request):
        if request.action in ('inspect_unknown', 'resolve_unknown', 'resolve_finished_unknown') and (self.jobs.active or getattr(self, '_closing', False)):
            # A local manual action must never cancel an unrelated job to obtain the slot.
            self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
            self.status.setText(ui_text('chatgpt_reconciliation.disabled'))
            return
        try:
            if self.jobs.active:
                self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # Primary sign-in starts with local list (no quiesce signal).
                # It must not remain busy after reconciliation takes the slot.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request = None
                self._chatgpt_job_id = None
                self.status.setText(ui_text('ui.chatgpt_dispatch.stop_record_checking'))
                return
            self._chatgpt_job_request = request
            self._chatgpt_job_id = self.start_job('ui_chatgpt_auth', {'request': request.payload()})
        except Exception:
            self.chatgpt_controller.worker_joined(request.request_id, joined=not self.jobs.active, terminal_received=False)
            self._chatgpt_job_request = None
            self.status.setText(ui_text('ui.chatgpt_dispatch.connection_start_failed'))

    def _chatgpt_cancel(self, request_id):
        self.chatgpt_panel.abandon_primary_sign_in()
        self._pending_usage_refresh = False
        if self.jobs.active:
            self.jobs.cancel()
        if self.jobs.active:
            return
        # Drain old packets before another operation may own the single manager.
        self.poll_jobs()
        self.chatgpt_controller.worker_joined(request_id, joined=True, terminal_received=False)
        self._chatgpt_job_request = None
        self._chatgpt_job_id = None
        self.chatgpt_panel.consent.setChecked(False)

    def _chatgpt_open_browser(self, url):
        if getattr(self, '_closing', False) or not self.chatgpt_controller.host_available:
            return
        from desktop_app.features.assistant.connection import official_authorization_url
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl(official_authorization_url(url))):
            self.status.setText(ui_text('ui.chatgpt_open_browser.authorization_page_failed'))

    def _plan_usage_request(self):
        c = self.chatgpt_controller
        panel = self.chatgpt_panel
        if c.state != 'plan_ready' or not c.active_registration or panel.model.currentData() not in c.models:
            raise ValidationError(ui_text('ui.plan_usage_request.connection_models_required'))
        options = {
            'mode': 'chatgpt_plan',
            'registration': c.active_registration,
            'model': panel.model.currentData(),
            'max_calls': panel.max_calls.value(),
            'timeout_seconds': panel.timeout.value(),
            'network_opt_in': False,
            'included_usage_policy_confirmed': False,
            'paid_api_fallback': False,
        }
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        return {'registration': c.active_registration, 'provider': options, 'config': config}

    def _current_plan_binding(self):
        from quantlab.__main__ import config_from_json

        payload = self._plan_usage_request()
        config = dict(payload['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        return self.host.callbacks['plan_provider'](self.paths, self.host.callbacks['_dataset'](self.root, {}), config, payload['provider'], for_usage=True)[1]

    def inspect_plan_usage(self):
        self._invalidate_analysis_preview()
        if self.chatgpt_controller.busy:
            raise ValidationError(ui_text('ui.inspect_plan_usage.connection_job_busy'))
        payload = self._plan_usage_request()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        self.start_job('ui_chatgpt_usage', payload)

    def _record_connection_error(self, code):
        from quantlab.desktop_errors import ERROR_TABLE
        from quantlab.desktop_runtime import RedactedEventLog

        fixed = code if code in ERROR_TABLE else 'operation_failed'
        RedactedEventLog(self.paths.logs / 'desktop-events.jsonl').append('ui_chatgpt_auth', 'error', error_code=fixed)

    def _chatgpt_event(self, event):
        operation = self.last_operation
        if operation not in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
            return False
        kind = event.get('type')
        if operation == 'ui_chatgpt_reconcile':
            if kind in ('result', 'completed', 'success', 'error', 'failed', 'cancelled', 'canceled'):
                self.chatgpt_controller.account_status_known = False
                self.chatgpt_controller.invalidate_campaign_usage()
                self._pending_usage_refresh = True
                self.status.setText(ui_text('ui.chatgpt_event.recovery_checked') if kind == 'result' else ui_text('ui.chatgpt_event.recovery_failed'))
            return True
        if operation == 'ui_chatgpt_auth':
            request = self._chatgpt_job_request
            if request is None:
                return True
            if self._chatgpt_job_id is not None and event.get('job_id') not in (None, self._chatgpt_job_id):
                return True
            if kind == 'auth_progress':
                connection = self.host.callbacks['connection_event_from_payload'](event['auth_event'])
                if connection.kind == 'error':
                    self._record_connection_error(connection.error_code)
                self.chatgpt_controller.apply_event(connection)
            elif kind in ('result', 'completed', 'success', 'error', 'failed', 'cancelled', 'canceled'):
                received = False
                if kind in ('result', 'completed', 'success'):
                    connection = self.host.callbacks['connection_event_from_payload'](event['result']['auth_event'])
                    if connection.kind == 'error':
                        self._record_connection_error(connection.error_code)
                    received = self.chatgpt_controller.apply_event(connection)
                joined = not self.jobs.active
                self.chatgpt_controller.worker_joined(request.request_id, joined=joined, terminal_received=received)
                if joined:
                    self._chatgpt_job_request = None
                    self._chatgpt_job_id = None
                    self._pending_usage_refresh = bool(
                        received
                        and self.chatgpt_controller.active_registration
                        and request.action not in ('inspect_unknown', 'resolve_unknown', 'resolve_finished_unknown')
                    )
            return True
        if kind in ('result', 'completed', 'success'):
            result = event['result']
            c = self.chatgpt_controller
            if result.get('registration') != c.active_registration:
                return True
            c.set_account_status(result['registration'], result['account_status'])
            if 'receipts' in result:
                if result.get('binding') != self._current_plan_binding():
                    c.invalidate_campaign_usage()
                    self._plan_usage_binding = None
                    self.status.setText(ui_text('ui.chatgpt_event.settings_changed'))
                else:
                    c.set_usage(result['registration'], result['receipts'], account_status=result['account_status'])
                    self._plan_usage_binding = result['binding']
                    self.status.setText(ui_text('ui.chatgpt_event.request_record_checked'))
        elif kind in ('error', 'failed', 'cancelled', 'canceled'):
            self.chatgpt_controller.account_status_known = False
            self.chatgpt_controller.invalidate_campaign_usage()
            self.status.setText(ui_text('ui.chatgpt_event.request_record_unknown'))
        return True

    def save_settings(self):
        if self.settings is None:
            raise ValidationError(ui_text('ui.save_settings.service_unavailable'))
        value = load_store(self.settings)
        # Preserve legacy provider settings as inert historical data. They are
        # never read into executable provider options or overwritten on save.
        value.update({'persist_logs': self.persist_logs.isChecked(), 'local_notifications': self.local_notifications.isChecked()})
        value['market'] = self.market.preferences()
        position = self.host.window_position()
        value['window'] = {'x': position.x(), 'y': position.y(), 'width': self.host.window_geometry().width(), 'height': self.host.window_geometry().height()}
        save_preferences(self, value)
        self.settings.save(value)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.chatgpt_panel.consent.setChecked(False)
        self.status.setText(ui_text('ui.save_settings.preferences_saved'))

    def load_settings(self):
        if self.settings is None:
            return
        value = load_store(self.settings)
        finder = getattr(self.host, 'find_child', None)
        privacy_toggle = finder(type(self.persist_logs), 'privacy_toggle') if finder is not None else None
        if privacy_toggle is not None:
            privacy_toggle.setChecked(value.get('privacy_mode') is True)
        self._restoring_sections = True
        for key, toggle in self._section_toggles.items():
            toggle.blockSignals(True)
            toggle.setChecked(disclosure_value(key, toggle, value.get('advanced_sections')))
            toggle.blockSignals(False)
            # Visibility must follow restored state even while signals are blocked.
            toggle.toggled.emit(toggle.isChecked())
        self._restoring_sections = False
        self.persist_logs.setChecked(value.get('persist_logs', True) is True)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.local_notifications.setChecked(value.get('local_notifications', True) is True)
        try:
            if 'market' in value:
                self.market.restore_preferences(value['market'])
            size = value.get('window', {})
            position = self.host.window_position()
            x, y = int(size.get('x', position.x())), int(size.get('y', position.y()))
            available = [screen.availableGeometry() for screen in QApplication.screens()]
            screen = next((rect for rect in available if rect.contains(x, y)), self.host.window_screen().availableGeometry())
            minimum_width, minimum_height = self.host.window_minimum_size()
            width = max(minimum_width, min(int(size.get('width', self.host.window_geometry().width())), screen.width()))
            height = max(minimum_height, min(int(size.get('height', self.host.window_geometry().height())), screen.height()))
            self.host.resize_window(width, height)
            self.host.move_window(
                max(screen.left(), min(x, screen.right() - self.host.window_geometry().width() + 1)),
                max(screen.top(), min(y, screen.bottom() - self.host.window_geometry().height() + 1)),
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            self.status.setText(ui_text('ui.load_settings.invalid_market_preferences'))
        restore_preferences(self, value)
        self.read_logs()

    def configure_workspace(self):
        self.chatgpt_panel.abandon_primary_sign_in()
        from quantlab.desktop_runtime import WorkspaceLocator

        if self.jobs.active:
            raise ValidationError(ui_text('ui.configure_workspace.job_busy'))
        self.chatgpt_panel.consent.setChecked(False)
        self._invalidate_analysis_preview()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        root = WorkspaceLocator(getattr(self.paths, 'bootstrap', None) or self.paths.root).configure(Path(self.workspace_path.text().strip()))
        self.status.setText(ui_text('ui.configure_workspace.next_workspace').format(str(root)))

    def open_releases(self):
        if self.property('offlinePreview') is True:
            self.status.setText(ui_text('redesign.preview.network_disabled'))
            return
        # Verified repository Releases destination; never invent latest version or assets.
        if not QDesktopServices.openUrl(QUrl('https://github.com/yostar77612/mark-auto/releases')):
            raise ValidationError(ui_text('ui.open_releases.browser_failed'))
        self.status.setText(ui_text('ui.open_releases.browser_requested'))

    def record_event(self, operation, kind):
        # Runtime owns persistence. Re-read its redacted API, never event payloads.
        self.read_logs()

    def read_logs(self):
        from quantlab.desktop_runtime import RedactedEventLog

        self.log_view.load(RedactedEventLog(self.paths.logs / 'desktop-events.jsonl').tail())

    def backup(self, restore):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.backups is None:
            raise ValidationError(ui_text('ui.backup.service_unavailable'))
        if not self.backup_path.text().strip():
            raise ValidationError(ui_text('ui.backup.path_required'))
        if restore and not self.restore_confirm.isChecked():
            raise ValidationError(ui_text('ui.backup.restore_consent_required'))
        panel = getattr(self, 'backup_inspection_panel', None)
        if self.jobs.active:
            raise ValidationError(ui_text('ui.backup.job_busy'))
        self.start_job('ui_backup_restore' if restore else 'ui_backup_create', {'path': self.backup_path.text()})
        self.restore_confirm.setChecked(False)
        if panel is not None:
            panel.invalidate()
