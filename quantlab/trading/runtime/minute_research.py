"""Cache-first minute research; M1 refill is asynchronous and never fakes data."""

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256

from quantlab.trading.application.codec import dumps
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.minute_research import validate_minute_request
from quantlab.trading.domain.minute_research import MinuteResearchSettings, complete_minutes
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.history import KlineStorePort
from .research_worker import SpawnResearchRunner
from .minute_research_wait import MinuteResearchBudget


class MinuteHistoryPending(DomainError):
    def __init__(self):
        super().__init__('validation_failed', 'minute history refill requested; retry after completion')


@dataclass(frozen=True)
class MinuteHistoryTarget:
    instrument_id: str


class MinuteResearchService:
    """Retry after HistorySync completes; incomplete data never reaches a worker.

    The owner supplies a resolved TMF history session and immutable TRAINING
    inputs. This service neither reads OOS partitions nor publishes deployment
    state. A worker returns a self-contained research-only receipt.
    """

    def __init__(self, store: KlineStorePort, history: HistorySync, runner: SpawnResearchRunner):
        if history.store is not store:
            raise DomainError('validation_failed', 'minute history must populate the selected cache')
        self.store, self.history, self.runner = store, history, runner

    def run(
        self,
        strategy,
        spec,
        calendar,
        fees,
        settings: MinuteResearchSettings,
        *,
        now: datetime,
        deadline: datetime,
        source_profile=None,
        refill=True,
        cancel_event=None,
    ):
        aware(now)
        sessions = validate_minute_request(strategy, spec, calendar, settings)
        if sessions[-1].closes_at > now:
            raise DomainError('validation_failed', 'minute training requires closed sessions')
        start, end = sessions[0].opens_at, sessions[-1].closes_at
        revision = self.store.revision
        rows = tuple(bar for bar in self.store.read(spec.instrument_id, start, end) if bar.session == 'DAY')
        try:
            bars = complete_minutes(rows, spec.instrument_id, calendar, settings, now)
        except DomainError:
            if not refill:
                raise DomainError('validation_failed', 'minute history incomplete after refill') from None
            self.history.request(MinuteHistoryTarget(spec.instrument_id), start, end, priority=0, force=True)
            raise MinuteHistoryPending() from None
        settings = replace(settings, raw_data_digest=sha256(dumps(rows).encode()).hexdigest())
        options = {'cancel_event': cancel_event} if cancel_event is not None else {}
        result = self.runner.run(strategy, spec, calendar, bars, fees, deadline=deadline, source_profile=source_profile, minute_settings=settings, **options)
        if self.store.revision != revision:
            current = tuple(bar for bar in self.store.read(spec.instrument_id, start, end) if bar.session == 'DAY')
            if sha256(dumps(current).encode()).hexdigest() != settings.raw_data_digest:
                raise DomainError('source_invalid_evidence', 'minute cache changed during research; retry')
        return result

    def run_waiting(self, strategy, spec, calendar, fees, settings, *, now, deadline, source_profile=None, cancel_event=None, budget=None):
        budget = budget or MinuteResearchBudget(deadline, cancel_event)
        options = dict(now=now, deadline=budget.deadline, source_profile=source_profile, cancel_event=budget.cancel)
        try:
            budget.check()
            try:
                result = self.run(strategy, spec, calendar, fees, settings, **options)
            except MinuteHistoryPending:
                budget.wait_for_history(self.history, spec.instrument_id)
                result = self.run(strategy, spec, calendar, fees, settings, refill=False, **options)
            budget.check()
            return result
        except BaseException:
            self.history.watch_removed(spec.instrument_id, timeout=min(0.05, budget.remaining()))
            raise
