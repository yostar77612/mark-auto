"""Opt-in connect-on-startup for the broker simulation session.

The runtime stays inert at startup. When the user has switched this on, the window sends the very command
the "save and connect" button sends (saved settings, current revision and generation) once it is idle, so
every existing guard still applies. The simulation target only: a saved production target is never connected
automatically, and a failed attempt is reported, not retried.
"""

from desktop_app.features.trading.sinopac_panel_text import reason_text
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment

MAX_ATTEMPTS = 3  # only a revision/generation race may repeat the command; a failure never does


class AutoConnect:
    def __init__(self, preferences):
        self.preferences = preferences
        self.active = preferences is not None and preferences.auto_connect()
        self.attempts = 0

    def attach(self, window):
        """Show the switch on the connection panel and persist changes to it."""
        panel = window.broker_panel
        panel.auto_connect.setVisible(self.preferences is not None)
        if self.preferences is None:
            return
        panel.auto_connect.setChecked(self.preferences.auto_connect())
        panel.auto_connect.toggled.connect(lambda value: self._save(window, value))

    def _save(self, window, value):
        self.active = False  # a change made mid-session only affects the next start
        try:
            self.preferences.set_auto_connect(value)
        except OSError:
            window.broker_panel.auto_connect.blockSignals(True)
            window.broker_panel.auto_connect.setChecked(not value)
            window.broker_panel.auto_connect.blockSignals(False)
            window._feedback(ui_text('autoconnect.save_failed'))

    def step(self, window) -> bool:
        """Called from the window's poll; True when it sent the connect command this tick."""
        if not self.active or window._operation is not None or window._priority_operation is not None or not window._engine_reachable:
            return False
        view = window.state.sinopac_connection
        if self.attempts and view.phase == 'DISCONNECTED' and view.error_code:
            # The engine keeps the attempted environment after a failure, so judge by phase and error.
            self.active = False
            window._feedback(ui_text('autoconnect.failed').format(reason_text(view.error_code)))
            return False
        if view.phase != 'DISCONNECTED' or view.environment is not None or view.error_code:
            self.active = False  # connecting or connected (by us or by the user), or an error left from before we tried
            return False
        if view.settings.environment is not Environment.BROKER_SIMULATION:
            self.active = False
            window._feedback(ui_text('autoconnect.skipped_live'))
            return False
        if window.broker_panel.dirty or self.attempts >= MAX_ATTEMPTS:
            self.active = False
            return False
        self.attempts += 1
        window.command(
            UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=view.settings, connection_revision=view.revision, connection_generation=view.generation
        )
        return True
