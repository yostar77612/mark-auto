"""Serialize remote alert work off the GUI thread and publish immutable UI caches."""

from collections import deque
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from desktop_app.features.trading.alert_panel import AlertPanel
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.alert_contracts import AlertCommand, AlertProxy, AlertSnapshot
from quantlab.trading.domain.alerts import AlertEvent, AlertRule


class _QueuedActions:
    """The panel reads only the last GUI-published snapshot, never worker state."""

    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.rules: tuple[AlertRule, ...] = ()
        self.events: tuple[AlertEvent, ...] = ()
        self.warning = ''

    def add_rule(self, rule):
        self.enqueue(lambda proxy: proxy.add_rule(rule))

    def set_enabled(self, rule_id, enabled):
        self.enqueue(lambda proxy: proxy.set_enabled(rule_id, enabled))

    def delete_rule(self, rule_id):
        self.enqueue(lambda proxy: proxy.delete_rule(rule_id))

    def clear_events(self):
        self.enqueue(lambda proxy: proxy.clear_events())


class AlertPanelController(QObject):
    """One injected background operation owns the proxy at any instant.

    Construction is inert. ``submit`` must run its operation off the GUI thread
    and deliver ``completed(value, error)`` on the GUI thread, as the terminal's
    existing submit boundary does. Polls coalesce while mutations retain FIFO order.
    """

    def __init__(
        self,
        call: Callable[[AlertCommand], AlertSnapshot],
        submit,
        current_instrument,
        select_instrument,
        instrument_name,
        notify,
        rise_fall_colors,
        parent=None,
    ):
        super().__init__(parent)
        self._proxy, self._submit, self._notify = AlertProxy(call), submit, notify
        self._queue: deque[Callable[[AlertProxy], None]] = deque()
        self._busy = self._started = self._closed = self._initialized = self._poll_pending = False
        self.actions = _QueuedActions(self._enqueue)
        self.panel = AlertPanel(
            self.actions, current_instrument, select_instrument, instrument_name=instrument_name, notify=self._notification, rise_fall_colors=rise_fall_colors
        )
        self.panel.destroyed.connect(self.stop)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    def start(self):
        if self._started or self._closed:
            return
        self._started = True
        self.timer.start()
        self.refresh()

    def stop(self):
        self._closed = True
        self.timer.stop()
        self._queue.clear()
        self._poll_pending = False

    def refresh(self):
        if self._closed:
            return
        self._poll_pending = True
        self._advance()

    def _enqueue(self, operation):
        if self._closed:
            return
        self._queue.append(operation)
        self._advance()

    def _advance(self):
        if self._closed or not self._started or self._busy:
            return
        if self._queue:
            operation = self._queue.popleft()
        elif self._poll_pending:
            operation = lambda proxy: proxy.refresh()
            self._poll_pending = False
        else:
            return
        self._busy = True

        def run():
            operation(self._proxy)
            return self._proxy.rules, self._proxy.events, self._proxy.warning

        def completed(value, error):
            self._busy = False
            if self._closed:
                return
            if error is not None:
                self.panel.warning.setText(ui_text('alert.unavailable'))
                self.panel.warning.show()
            else:
                self.actions.rules, self.actions.events, self.actions.warning = value
                self.panel.warning.clear()
                self.panel.warning.setVisible(bool(self.actions.warning))
                # refresh emits latest_changed for restored status, but the first
                # successful snapshot must not replay desktop notifications.
                self.panel.refresh()
                self._initialized = True
            self._advance()

        self._submit(run, completed)

    def _notification(self, text):
        if self._initialized and self._notify is not None:
            self._notify(text)
