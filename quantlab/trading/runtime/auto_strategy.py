"""Trusted M3 composition. The default E1 source is intentionally unavailable.

No evidence producer is inferred from display results or test fixtures. Training
input preparation is an explicit host dependency, not a UI/IPC payload.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from quantlab.trading.application.auto_strategy_views import CandidateSummaryView
from quantlab.trading.application.candidate_intake import AutoBuildRequest, build_auto_strategy
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.signal_executor import SignalExecutor
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.minute_research import MinuteResearchSettings
from quantlab.trading.domain.models import InstrumentSpec
from quantlab.trading.domain.signal_strategy import SignalBar
from quantlab.trading.domain.validation import DomainError
from .candidate_catalog import ResearchWorkspaceCandidateCatalog
from .v1_signal_source import V1SignalSource


@dataclass(frozen=True)
class AutoBuildInputs:
    spec: InstrumentSpec
    calendar: TradingCalendar
    bars: tuple[SignalBar, ...]
    fees: FeeSchedule
    allocated_amount: Decimal
    source_profile: ProducerProfile
    settings: MinuteResearchSettings


class AutoStrategyRuntime:
    def __init__(self, engine, catalog, *, source=None, prepare: Callable[[AutoBuildRequest], AutoBuildInputs] | None = None):
        self.engine = engine
        self.catalog = catalog
        self.source = source if source is not None else V1SignalSource()
        self.prepare = prepare

    def candidates(self) -> tuple[CandidateSummaryView, ...]:
        return tuple(CandidateSummaryView.from_summary(row) for row in self.catalog.passed())

    def executor(self, contract_ref: str) -> SignalExecutor:
        return SignalExecutor(self.source, contract_ref)

    def build(self, request, service):
        # Resolve authoritative E1 before touching any training input. The
        # production default has no authoritative producer and refuses here.
        self.catalog.resolve(request.candidate_ref)
        if self.prepare is None:
            raise DomainError('auto_execution_data_insufficient')
        inputs = self.prepare(request)
        return build_auto_strategy(
            request,
            catalog=self.catalog,
            source=self.source,
            spec=inputs.spec,
            calendar=inputs.calendar,
            bars=inputs.bars,
            fees=inputs.fees,
            allocated_amount=inputs.allocated_amount,
            now=self.engine.clock.now(),
            source_profile=inputs.source_profile,
            service=service,
            settings=inputs.settings,
        )

    def resume_checks(self, record):
        # No runtime execution/admission adapter is composed yet. Do not turn
        # a UI click, a fixture, or stale E2 into permission to resume trading.
        return False, False


def attach_auto_runtime(bundle):
    engine = bundle.engine
    if engine is not None and engine.auto_runtime is None:
        engine.auto_runtime = AutoStrategyRuntime(engine, ResearchWorkspaceCandidateCatalog(bundle.launch.root))
