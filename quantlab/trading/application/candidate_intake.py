"""Candidate reference -> frozen strategy, with no journal write until E1/E2 pass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import TYPE_CHECKING

from .provenance import ProducerProfile
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.minute_contract import is_tmf_contract
from quantlab.trading.domain.minute_research import MinuteResearchSettings
from quantlab.trading.domain.models import HoldingKind, InstrumentSpec
from quantlab.trading.domain.promotion import DEFAULT_THRESHOLDS, RunState
from quantlab.trading.domain.signal_strategy import AutoStrategy, CandidateEvidence, DirectionPolicy, SignalBar, SizingKind, SizingRule, WindowMode
from quantlab.trading.domain.validation import DomainError, identity
from quantlab.trading.ports.candidates import CandidateCatalog
from quantlab.trading.ports.signals import SignalSource


if TYPE_CHECKING:
    from .promotion_service import AutoStrategyRecord, PromotionService
    from .signal_research import ExecutionEvidence


@dataclass(frozen=True)
class AutoBuildRequest:
    candidate_ref: str
    strategy_id: str
    account_ref: str
    holding_kind: HoldingKind
    instrument_rule: str
    bar_interval: str
    sizing: SizingRule
    protective_stop_pct: Decimal = Decimal('0.01')
    start_in_sim: bool = False
    risk_ref: str = 'risk-v1'

    def __post_init__(self):
        for value in (self.candidate_ref, self.strategy_id, self.account_ref, self.instrument_rule, self.risk_ref):
            identity(value)
        if type(self.start_in_sim) is not bool:  # guard:build_consent_type
            raise DomainError('validation_failed', 'simulation consent must be boolean')


@dataclass(frozen=True)
class AutoBuildResult:
    record: AutoStrategyRecord
    evidence: ExecutionEvidence


def _qualify(candidate: CandidateEvidence, request: AutoBuildRequest) -> None:
    if candidate.candidate_ref != request.candidate_ref:  # guard:candidate_reference
        raise DomainError('candidate_unavailable')
    if candidate.verdict != DEFAULT_THRESHOLDS.BUILD_REQUIRED_VERDICT:  # guard:candidate_verdict
        raise DomainError('candidate_not_passed')
    if not candidate.oos_consumed:  # guard:candidate_consumed
        raise DomainError('candidate_not_passed')
    if candidate.sample_count == 0:  # guard:candidate_samples
        raise DomainError('candidate_not_passed')
    if candidate.dataset_family != 'TMF' or candidate.dataset_interval != '1d':  # guard:candidate_dataset
        raise DomainError('candidate_data_mismatch')
    try:
        body = json.loads(candidate.signal_spec_json)
    except ValueError:
        raise DomainError('candidate_spec_unsupported') from None
    if not isinstance(body, dict) or not isinstance(body.get('parameters'), dict):  # guard:candidate_shape
        raise DomainError('candidate_spec_unsupported')
    parameters = body['parameters']
    if 'stop_ticks' in parameters:  # guard:candidate_stop
        raise DomainError('candidate_spec_unsupported')
    if 'target_ticks' in parameters:  # guard:candidate_target
        raise DomainError('candidate_spec_unsupported')
    if type(parameters.get('quantity', 1)) is not int or parameters.get('quantity', 1) != 1:  # guard:candidate_quantity
        raise DomainError('candidate_spec_unsupported')
    # This is a rejection filter, not an AST parser. SignalSource remains the
    # sole semantic validator, and CandidateCatalog owns fingerprint matching.


def _configuration(request: AutoBuildRequest, spec: InstrumentSpec, service: PromotionService) -> None:
    if request.holding_kind is not HoldingKind.INTRADAY:  # guard:build_kind
        raise DomainError('auto_instrument_not_allowed')
    if not is_tmf_contract(spec):  # guard:build_contract
        raise DomainError('auto_instrument_not_allowed')
    allowed = ('TMF_NEAR', spec.instrument_id, f'TAIFEX:TMF:{spec.delivery_month}', f'TMF:{spec.delivery_month}')
    if request.instrument_rule not in allowed:  # guard:build_instrument
        raise DomainError('auto_instrument_not_allowed')
    if request.bar_interval not in ('1m', '5m'):  # guard:build_interval
        raise DomainError('candidate_data_mismatch')
    if request.sizing.kind is not SizingKind.FIXED_CONTRACTS:  # guard:build_sizing
        raise DomainError('auto_instrument_not_allowed')
    if any(
        r.account_ref == request.account_ref and r.execution_instrument_id == f'TAIFEX:TMF:{spec.delivery_month}' and r.state.run_state is RunState.RUNNING
        for r in service.records
    ):  # guard:build_busy
        raise DomainError('auto_instrument_busy')


def research_auto_strategy(*args, **kwargs):
    """Keep the existing injectable research seam without a DTO import cycle."""
    from .signal_research import research_auto_strategy as research

    return research(*args, **kwargs)


def build_auto_strategy(
    request: AutoBuildRequest,
    *,
    catalog: CandidateCatalog,
    source: SignalSource,
    spec: InstrumentSpec,
    calendar: TradingCalendar,
    bars: tuple[SignalBar, ...],
    fees: FeeSchedule,
    allocated_amount: Decimal,
    now: datetime,
    source_profile: ProducerProfile,
    service: PromotionService,
    settings: MinuteResearchSettings,
) -> AutoBuildResult:
    from .promotion_service import AutoStrategyRecord

    candidate = catalog.resolve(request.candidate_ref)
    _qualify(candidate, request)
    _configuration(request, spec, service)
    counts: dict[object, int] = {}
    for bar in bars:
        counts[bar.trade_date] = counts.get(bar.trade_date, 0) + 1
    if not bars or max(counts.values()) > DEFAULT_THRESHOLDS.EXECUTOR_MAX_BARS:  # guard:build_window
        raise DomainError('auto_execution_data_insufficient')
    auto = AutoStrategy(
        request.strategy_id,
        1,
        candidate.signal_spec_json,
        candidate.candidate_fingerprint,
        request.holding_kind,
        request.instrument_rule,
        request.bar_interval,
        WindowMode.PER_SESSION,
        None,
        DirectionPolicy.BOTH,
        request.sizing,
        request.protective_stop_pct,
        0,
        fees.version,
        request.risk_ref,
        DEFAULT_THRESHOLDS.version,
    )
    evidence = research_auto_strategy(
        auto, spec, calendar, bars, fees, source, allocated_amount=allocated_amount, now=now, source_profile=source_profile, settings=settings
    )
    if evidence.completed_trades < DEFAULT_THRESHOLDS.BUILD_MIN_RESEARCH_TRADES:  # guard:build_trades
        raise DomainError('auto_execution_data_insufficient')
    record = AutoStrategyRecord(
        auto=auto,
        account_ref=request.account_ref,
        execution_instrument_id=f'TAIFEX:TMF:{spec.delivery_month}',
        candidate=candidate,
        evidence=evidence,
        start_in_sim=request.start_in_sim,
    )
    service.record_built(record, now=now)
    return AutoBuildResult(record, evidence)
