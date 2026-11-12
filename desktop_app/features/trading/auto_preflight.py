"""Run the pre-open check by itself, so the checklist is never left waiting for a click.

The check only records a readiness snapshot from what the engine and the connection already know (no order, no
login), so it is safe to send unattended. It runs once when the window first has an account, and once more when
the connection becomes ready, because the first answer was recorded before there was a connection to judge. The
result is shown in the checklist itself; the window's message line is left alone.
"""

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

MAX_TRIES = 3  # a check the engine did not record (a version race) may repeat a few times; a refusal never loops


class AutoPreflight:
    def __init__(self):
        self.key = None
        self.tries = 0

    def step(self, window) -> bool:
        """Called from the window's poll; True when it sent the check this tick."""
        state = window.state
        if not state.account_ref or window._operation is not None or window._priority_operation is not None or not window._engine_reachable:
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QComboBox)) and window.isAncestorOf(focus):
            return False  # the result re-renders the page: wait until the user is not typing in a field
        key = (state.context_id, state.context_epoch, state.environment, state.account_ref, state.trading_day, state.sinopac_connection.phase == 'CONNECTED')
        if key != self.key:
            self.key, self.tries = key, 0
        recorded = any(item.account_ref == state.account_ref and item.trade_date.isoformat() == state.trading_day for item in state.preflight)
        if self.tries and (recorded or self.tries >= MAX_TRIES):
            return False
        self.tries += 1
        window._quiet_next = True
        window.automatic_controls.check()
        window._quiet_next = False  # the command consumes it; never let it leak onto a later user command
        return True
