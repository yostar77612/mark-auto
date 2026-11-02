"""Allowlisted, immutable presentation values; never an AI context or command."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from quantlab.trading.domain.models import HoldingKind
from quantlab.trading.domain.promotion import Check, PauseReason, RunState, Stage
from quantlab.trading.domain.signal_strategy import CandidateSummary


@dataclass(frozen=True)
class CandidateSummaryView:
    candidate_ref: str
    verdict: str
    completed_at: datetime
    dataset_interval: str

    @classmethod
    def from_summary(cls, summary: CandidateSummary) -> 'CandidateSummaryView':
        return cls(summary.candidate_ref, summary.verdict, summary.completed_at, summary.dataset_interval)


@dataclass(frozen=True)
class PromotionProgressView:
    checks: tuple[Check, ...] = ()
    eligible: bool = False
    history_complete: bool = False
    observation_started_on: date | None = None
    drift_line_pct: Decimal | None = None
    observed_drawdown_pct: Decimal | None = None


@dataclass(frozen=True)
class AutoStrategyView:
    strategy_id: str
    version: int
    holding_kind: HoldingKind
    instrument_rule: str
    stage: Stage
    run_state: RunState
    pause_reason: PauseReason | None
    frozen_hash: str
    progress: PromotionProgressView = PromotionProgressView()
    live_available: bool = field(default=False, init=False)


@dataclass(frozen=True)
class BuildDialogOptions:
    holding_kinds: tuple[HoldingKind, ...] = (HoldingKind.INTRADAY,)
    bar_intervals: tuple[str, ...] = ('1m', '5m')
    instrument_rules: tuple[str, ...] = ('TMF_NEAR',)
    min_contracts: int = 1
    max_contracts: int = 5
    default_stop_pct: Decimal = Decimal('0.01')
    stock_research_available: bool = False
    live_available: bool = field(default=False, init=False)
