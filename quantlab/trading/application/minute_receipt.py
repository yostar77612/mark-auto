"""Self-contained training receipt; no broker accounts, credentials or activation."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from .codec import dumps, register
from .minute_research import MinuteResearchResult
from .provenance import ProducerProfile
from .research import research_fingerprint
from .state import StrategyRecord
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.minute_research import complete_minutes
from quantlab.trading.domain.models import InstrumentSpec
from quantlab.trading.domain.validation import DomainError, aware


@dataclass(frozen=True)
class MinuteResearchReceipt:
    result: MinuteResearchResult
    strategy: StrategyRecord
    spec: InstrumentSpec
    calendar: TradingCalendar
    fees: FeeSchedule
    source_profile: ProducerProfile
    raw_bars: tuple[LiveBar, ...]
    completed_at: datetime
    source: str = 'M1_SQLITE_BARS_1M'
    schema_version: int = 1

    def __post_init__(self):
        aware(self.completed_at)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.source != 'M1_SQLITE_BARS_1M'
            or not isinstance(self.strategy, StrategyRecord)
            or not isinstance(self.spec, InstrumentSpec)
            or not isinstance(self.calendar, TradingCalendar)
            or not isinstance(self.fees, FeeSchedule)
            or not isinstance(self.result, MinuteResearchResult)
            or not isinstance(self.source_profile, ProducerProfile)
            or self.result.partition != 'TRAINING'
        ):
            raise DomainError('source_invalid_evidence', 'minute receipt schema or training scope')
        settings = self.result.minute_settings
        if settings is None or sha256(dumps(self.raw_bars).encode()).hexdigest() != settings.raw_data_digest:
            raise DomainError('source_invalid_evidence', 'minute receipt raw snapshot mismatch')
        bars = complete_minutes(self.raw_bars, self.spec.instrument_id, self.calendar, settings, self.completed_at)
        dataset = sha256(dumps((bars, settings)).encode()).hexdigest()
        base = research_fingerprint(self.strategy, self.spec, self.calendar, self.fees, dataset, self.source_profile)
        if (
            dataset != self.result.dataset_id
            or (self.result.strategy_id, self.result.version) != (self.strategy.strategy_id, self.strategy.version)
            or self.result.observations != len(bars)
            or self.result.producer != 'markauto-minute-training-1'
            or self.result.producer_profile != self.source_profile.profile_id
            or sha256(('minute-research-v1:' + base).encode()).hexdigest() != self.result.fingerprint
            or self.result.source_digest != self.source_profile.source_digest
            or self.result.cost_version != self.fees.version
            or self.result.calendar_version != self.calendar.version
            or self.result.price_basis != 'RAW_CONTRACT'
        ):
            raise DomainError('source_invalid_evidence', 'minute receipt parameters mismatch')


register(MinuteResearchReceipt)
