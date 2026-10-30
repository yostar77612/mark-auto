"""Own one existing research session inside the multi-market desktop.

Composition only: the original workers, credential references, recovery, journal
and budgets remain authoritative. No credential is copied into the v2 book.
"""

from types import SimpleNamespace

from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QShortcut

from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message


class ResearchUnavailable(Exception):
    pass


class EmbeddedSettings:
    """Reuse the original store without saving child-widget geometry as a window.

    All business preferences still use SettingsStore validation/atomic writes.
    Only the original standalone chrome is preserved, including its absence.
    """

    def __init__(self, store):
        self.store = store
        self.path = store.path

    def load(self):
        return self.store.load()

    def save(self, settings):
        current = self.store.load()
        value = dict(settings)
        if 'window' in current:
            value['window'] = current['window']
        else:
            value.pop('window', None)
        self.store.save(value)


class ResearchSession(QObject):
    released = Signal()

    def __init__(self, parent=None, *, bootstrap=None, restore_login=True):
        super().__init__(parent)
        self.bootstrap = bootstrap
        self.restore_login = restore_login
        self.state = None
        self.window = None
        self._released = False

    def open(self):
        if self.window is not None:
            return self.window
        self._released = False
        from desktop import prepare_workspace
        from desktop_app.shell.window import MainWindow
        from desktop_app.shell.main_window import create_window
        from quantlab.desktop_runtime import AppPaths, WorkspaceLocator

        owner = self

        class EmbeddedWindow(MainWindow):
            def closeEvent(self, event):
                try:
                    owner.quiesce_assistant()
                except Exception:
                    self.status.setText(ui_text('ui.close_event.stop_unconfirmed'))
                    event.ignore()
                    return
                super().closeEvent(event)
                if event.isAccepted():
                    owner.release()

        bootstrap = self.bootstrap if self.bootstrap is not None else AppPaths.discover().root
        bootstrap.mkdir(parents=True, exist_ok=True)
        locator = WorkspaceLocator(bootstrap)
        lock = QLockFile(str(locator.lock_path))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise ResearchUnavailable(error_message('startup_workspace_busy'))
        state = SimpleNamespace(
            args=SimpleNamespace(smoke_test=None),
            user_bootstrap=bootstrap,
            bootstrap=bootstrap,
            locator=locator,
            lock=lock,
            installation_guard=None,
            jobs=None,
            guard=None,
        )
        self.state = state
        try:
            if not prepare_workspace(state):
                raise ResearchUnavailable(error_message('startup_failed'))
            state.settings = EmbeddedSettings(state.settings)
            window = create_window(state.paths, state.jobs, state.settings, state.backups, state.guard, window_type=EmbeddedWindow)
            self.window = window
            window.setWindowFlags(Qt.WindowType.Widget)
            window.setMinimumSize(0, 0)
            window.navigation.hide()
            window.app_header.hide()
            window.app_header.explanation.hide()
            for shortcut in window.findChildren(QShortcut):
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            window.freeze_paper(
                'Previous session ended unexpectedly; reconcile paper account' if state.previous_unclean else 'Startup requires paper reconciliation'
            )
            self.clock_timer = QTimer(self)
            self.clock_timer.setInterval(1000)
            self.clock_timer.timeout.connect(self._clock_tick)
            self.clock_timer.start()
            self.power_events = _PowerEvents(self)
            from PySide6.QtWidgets import QApplication

            QApplication.instance().installNativeEventFilter(self.power_events)
            if self.restore_login:
                window.auto_restore_chatgpt()
            return window
        except BaseException:
            self.release()
            self.window = None
            self.state = None
            raise

    def _clock_tick(self):
        if self.state.guard.check_clock():
            self.window._safe(lambda: self.window.freeze_paper('Sleep or clock change detected; reconcile paper account before resuming'))

    def request_close(self):
        if self.window is None or self._released:
            return True
        # Original closeEvent can refuse or asynchronously reconcile an unknown
        # result. The outer desktop must remain alive until it actually accepts.
        return self.window.close()

    def quiesce_assistant(self):
        if self.window is not None:
            self.window.settings_page.assistant_panel.cancel()

    def release(self):
        if self._released:
            return
        state = self.state
        if state is None:
            return
        self.quiesce_assistant()
        if state.jobs is not None:
            state.jobs.close()
        if self.window is not None:
            # The embedded presenter may outlive its accepted close while the
            # outer engine operation finishes. No backup/poll callback may run
            # after this session gives up its writer lock.
            for timer in self.window.findChildren(QTimer):
                timer.stop()
        if hasattr(self, 'clock_timer'):
            self.clock_timer.stop()
        if hasattr(self, 'power_events'):
            from PySide6.QtWidgets import QApplication

            QApplication.instance().removeNativeEventFilter(self.power_events)
        if state.installation_guard is not None:
            state.installation_guard.close()
        state.lock.unlock()
        self._released = True
        self.released.emit()


class _PowerEvents(QAbstractNativeEventFilter):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def nativeEventFilter(self, event_type, message):
        import sys

        if sys.platform == 'win32':
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0218 and msg.wParam in (4, 6, 7, 18):
                self.session.state.guard.reconciliation_required = True
                self.session.window._safe(lambda: self.session.window.freeze_paper('Windows power event; reconcile paper account before resuming'))
        return False, 0


class UnifiedResearch(QObject):
    """Connect the same research presenter to all six desktop workspaces."""

    def __init__(self, trading, *, session=None):
        super().__init__(trading)
        from desktop_app.features.trading.research_panel import ResearchPanel

        self.trading = trading
        self.session = session or ResearchSession(self)
        self.panel = ResearchPanel(trading)
        trading.pages.addWidget(self.panel)
        trading.legacy_requested.connect(self.show)
        trading.chatgpt_button.clicked.connect(lambda: self.show('connection'))
        trading.cancel_research_button.clicked.connect(self.cancel_research)
        self.panel.page_requested.connect(self.show)
        self.panel.back_requested.connect(self.back)
        trading.research_close_guard = self.request_close
        self._host = None
        self._routing = False
        self._pending_close = False
        self._closing = False
        self._appearance = None
        self.session.released.connect(self._released)
        trading.pages.currentChanged.connect(self._visibility)
        # Restore the saved login through the existing controller, not a second
        # credential implementation. A busy original desktop stays untouched.
        QTimer.singleShot(0, self.ensure_open)

    def ensure_open(self):
        if self.session._released:
            self.panel.set_error(ui_text('unified.research_unavailable'))
            return False
        if self._host is not None:
            return True
        try:
            host = self.session.open()
        except Exception:
            self.panel.set_error(ui_text('unified.research_unavailable'))
            self.trading.chatgpt_button.setText(ui_text('unified.connection_unavailable'))
            self.trading.chatgpt_button.setAccessibleName(self.trading.chatgpt_button.text())
            return False
        self._host = host
        self.panel.mount(host)
        # Only the embedded presenter needs a host different from window().
        # Standalone v1 keeps its historical hint and popup semantics.
        assistant = host.settings_page.assistant_panel
        self._assistant_hint = None
        self._assistant_prerequisite = ''
        for hint in host._disabled_hints:
            hint.host = host
            hint.update()
            if hint.button is assistant.send:
                self._assistant_hint = hint
                self._assistant_prerequisite = hint.prerequisite
        host.navigation.currentRowChanged.connect(self._research_navigated)
        host.chatgpt_controller.changed.connect(self.refresh_connection)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self.refresh_connection)
        self.status_timer.start()
        self.refresh_connection()
        return True

    def refresh_connection(self):
        host = self._host
        if host is None:
            return
        connected = host.chatgpt_controller.state == 'plan_ready'
        host.app_header.refresh()
        if self._assistant_hint is not None:
            self._assistant_hint.prerequisite = (
                ui_text('ui.plan_usage_request.connection_models_required')
                if host.settings_page.assistant_panel.model.count() == 0
                else self._assistant_prerequisite
            )
            self._assistant_hint.update()
        # A consumed connection-result event leaves the legacy generic running
        # caption behind. Clear only that caption after confirmed idle/done;
        # keep all failures, unknown outcomes and pending reconciliation text.
        if (
            not host.jobs.active
            and not host.job_progress.running
            and not host.chatgpt_controller.busy
            and not host.settings_page.assistant_panel.worker.active
            and not any(getattr(host, flag, False) for flag in ('_pending_analysis_reconcile', '_pending_plan_reconcile', '_wf_pending_reconcile'))
            and host.app_header.job.text() in (ui_text('header.idle'), ui_text('header.done'))
            and host.status.text() in (ui_text('ui.start_job.running'), ui_text('ui.poll_jobs.running'))
        ):
            host.status.setText(ui_text('ui.init.ready'))
        from desktop_app.shell.theme import appearance, apply_theme

        current_appearance = appearance(host)
        if current_appearance != self._appearance:
            self.trading.setProperty('appearanceTheme', current_appearance[0])
            self.trading.setProperty('appearanceConvention', current_appearance[1])
            apply_theme(self.trading)
            self._appearance = current_appearance
        connection_text = ui_text('redesign.header.connected') if connected else ui_text('redesign.header.connection')
        self.trading.chatgpt_button.setText(connection_text)
        self.trading.chatgpt_button.setAccessibleName(self.trading.chatgpt_button.text())
        # Only the existing fixed-status presentation crosses this boundary.
        self.panel.job_status.setText(host.app_header.job.text())
        self.trading.research_job.setText(ui_text('unified.research_job').format(host.app_header.job.text()))
        self.trading.cancel_research_button.setEnabled(
            host.settings_page.assistant_panel.worker.active or host.job_progress.running and not host.job_progress.cancel_pending
        )

    def cancel_research(self):
        if self._host is not None:
            try:
                assistant = self._host.settings_page.assistant_panel
                if assistant.worker.active:
                    assistant.cancel()
                self._host.job_progress.request_cancel(self._host.cancel_job)
            except Exception:
                self.trading._feedback(ui_text('ui.close_event.stop_unconfirmed'))
            self.refresh_connection()

    def show(self, page):
        if page not in self.panel.ROUTES:
            return
        target, research_page = self.panel.ROUTES[page]
        self._routing = True
        try:
            self.trading.navigation.setCurrentRow(target)
            self.trading.pages.setCurrentWidget(self.panel)
            self.panel.set_page(page)
            if not self.ensure_open():
                return
            from desktop_app.shell.palette_commands import page_index

            self._host.navigation.setCurrentRow(page_index(self._host, research_page))
            if page == 'connection':
                self._host.settings_page.connection_toggle.setChecked(True)
                self._host.settings_page.connection_status.setFocus()
            elif page == 'assistant':
                self._host.settings_page.maintenance_toggle.setChecked(True)
                QTimer.singleShot(0, self._focus_assistant)
        finally:
            self._routing = False

    def _research_navigated(self, index):
        if self._routing or self._host is None:
            return
        from desktop_app.shell.palette_commands import page_index

        for page, (_workspace, original) in self.panel.ROUTES.items():
            if page not in ('connection', 'assistant') and page_index(self._host, original) == index:
                self.show(page)
                return

    def back(self):
        self.trading.pages.setCurrentIndex(self.trading.navigation.currentRow())

    def _focus_assistant(self):
        if self.panel.choice.currentData() != 'assistant' or self.trading.pages.currentWidget() is not self.panel:
            return
        assistant = self._host.settings_page.assistant_panel
        self._host.stack.currentWidget().ensureWidgetVisible(assistant.send, 0, 24)
        assistant.input.setFocus()

    def _visibility(self, index):
        visible = self.trading.pages.widget(index) is self.panel
        from PySide6.QtGui import QShortcut

        for shortcut in self.trading.findChildren(QShortcut, options=Qt.FindChildOption.FindDirectChildrenOnly):
            shortcut.setEnabled(not visible)

    def _released(self):
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()
        # Original workspace restore/restart may close its presenter directly.
        # Never leave an unlocked, usable research widget in the outer shell.
        if self._host is not None:
            self._host.setEnabled(False)
        if self._pending_close or self._host is not None and not self._closing:
            self._pending_close = False
            QTimer.singleShot(0, self.trading.close)

    def request_close(self):
        self._closing = True
        try:
            accepted = self.session.request_close()
        finally:
            self._closing = False
        # Asynchronous original reconciliation can finish after this close
        # request. Only then may the outer window close, never before joining.
        self._pending_close = not accepted and bool(getattr(self._host, '_close_after_reconcile', False))
        return accepted
