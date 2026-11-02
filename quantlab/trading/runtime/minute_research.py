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

    def run(self, strategy, spec, calendar, fees, settings: MinuteResearchSettings, *, now: datetime, deadline: datetime, source_profile=None):
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
            self.history.request(MinuteHistoryTarget(spec.instrument_id), start, end, priority=0, force=True)
            raise DomainError('validation_failed', 'minute history refill requested; retry after completion') from None
        settings = replace(settings, raw_data_digest=sha256(dumps(rows).encode()).hexdigest())
        result = self.runner.run(strategy, spec, calendar, bars, fees, deadline=deadline, source_profile=source_profile, minute_settings=settings)
        if self.store.revision != revision:
            current = tuple(bar for bar in self.store.read(spec.instrument_id, start, end) if bar.session == 'DAY')
            if sha256(dumps(current).encode()).hexdigest() != settings.raw_data_digest:
                raise DomainError('source_invalid_evidence', 'minute cache changed during research; retry')
        return result
