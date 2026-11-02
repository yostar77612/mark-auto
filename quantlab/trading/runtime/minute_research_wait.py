"""One non-renewable deadline covers refill, calculation and receipt admission."""

from datetime import datetime, timedelta, timezone
from threading import Event
from time import monotonic

from quantlab.trading.domain.validation import DomainError, aware


class MinuteResearchBudget:
    def __init__(self, deadline: datetime, cancel: Event | None = None):
        self.deadline = min(aware(deadline), datetime.now(timezone.utc) + timedelta(seconds=900))
        self.cancel = cancel if cancel is not None else Event()
        self.until = monotonic() + min(900, (self.deadline - datetime.now(timezone.utc)).total_seconds())
        self.check()

    def remaining(self):
        return max(0, min(self.until - monotonic(), (self.deadline - datetime.now(timezone.utc)).total_seconds()))

    def check(self):
        if self.cancel.is_set():
            raise DomainError('research_worker_failed', 'minute research canceled')
        if monotonic() >= self.until or datetime.now(timezone.utc) >= self.deadline:
            raise DomainError('research_timeout', 'minute research deadline expired')

    def wait_for_history(self, history, instrument_id):
        while True:
            self.check()
            progress = history.progress(instrument_id)
            if progress is not None:
                pending, state = progress
                if state.paused:
                    raise DomainError('capability_missing', 'minute history refill paused')
                if not pending:
                    if instrument_id in dict(state.history_error):
                        raise DomainError('capability_missing', 'minute history refill failed')
                    return
            self.cancel.wait(min(0.025, self.remaining()))
