"""Keep the pre-open checklist filled in by itself, without recording anything.

The 交易 page's checklist used to read 'not checked, press the button' until the owner clicked. Recording a check is
not harmless: a failing record latches the trading day as blocked and a later pass can never undo it, and the
daily admission only records its own proof when the day has no row yet. So the window never records on its own.
It asks for the read-only PREVIEW_PREFLIGHT instead (the same facts, nothing written, no new version) and shows
the answer in the checklist, marked as a preview. The owner's click still makes the official record.
"""

from time import monotonic

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from quantlab.trading.application.contracts import UiAction

REFRESH_SECONDS = 30  # facts change as the connection comes up and the session opens; a refused preview just waits for the next turn


class AutoPreflight:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.key = None
        self.next_at = 0.0

    def step(self, window) -> bool:
        """Called from the window's poll; True when it sent the preview this tick."""
        state = window.state
        if not state.account_ref or window._operation is not None or window._priority_operation is not None or not window._engine_reachable:
            return False
        # A recorded checklist for this day is the truth and is never replaced by a preview.
        if any(item.account_ref == state.account_ref and item.trade_date.isoformat() == state.trading_day for item in state.preflight):
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QComboBox)) and window.isAncestorOf(focus):
            return False  # a command in flight disables the page: wait until the user is not typing in a field
        key = (state.context_id, state.context_epoch, state.environment, state.account_ref, state.trading_day, state.sinopac_connection.phase)
        now = self.clock()
        if key == self.key and now < self.next_at:
            return False
        self.key, self.next_at = key, now + REFRESH_SECONDS
        window._quiet_next = True
        window.command(UiAction.PREVIEW_PREFLIGHT, account_ref=state.account_ref)
        window._quiet_next = False  # the command consumes it; never let it leak onto a later user command
        return True
