"""Journal-first M3 lifecycle, with no broker, scheduler or owner-approval entry.

This isolated application service uses the existing Journal/codec contracts. M3-4
will compose it with the engine's single writer; it must not run as a second writer.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from .codec import dumps, loads, register
from .research import ResearchTrade
from .signal_research import ExecutionEvidence
from quantlab.trading.domain.models import Environment, HoldingKind, Side
from quantlab.trading.domain.promotion import (
    Check,
    DriftVerdict,
    ExecutionExpectation,
    INITIAL_STATE,
    PauseReason,
    PromotionVerdict,
    RunState,
    SimObservation,
    Stage,
    StageState,
    TransitionContext,
    Trigger,
    evaluate_drift,
    evaluate_promotion,
    next_stage,
    thresholds_for,
)
from quantlab.trading.domain.signal_strategy import AutoStrategy, CandidateEvidence, DirectionPolicy, SizingKind, SizingRule, WindowMode
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, trading_date
from quantlab.trading.ports.storage import Journal


@dataclass(frozen=True)
class AutoStrategyRecord:
    auto: AutoStrategy
    account_ref: str
    execution_instrument_id: str
    candidate: CandidateEvidence
    evidence: ExecutionEvidence
    start_in_sim: bool = False
    state: StageState = INITIAL_STATE
    observation_started_on: date | None = None
    eligible: bool = False
    live_approved_on: date | None = None
    observation_started_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.observation_started_at is not None:
            aware(self.observation_started_at, 'observation epoch')
        if self.live_approved_on is not None:
            trading_date(self.live_approved_on)
        decimal_value(self.allocated_amount, 'allocated amount', positive=True)
        e = self.evidence
        if (e.strategy_id, e.version, e.frozen_hash) != (self.auto.strategy_id, self.auto.version, self.auto.frozen_hash) or e.partition != 'TRAINING':
            raise DomainError('auto_evidence_changed', 'execution evidence identity mismatch')
        for name in ('account_ref', 'execution_instrument_id', 'behavior_hash', 'source_digest', 'dataset_id', 'result_hash'):
            identity(getattr(self, name), name)

    @property
    def allocated_amount(self) -> Decimal:
        return self.evidence.allocated_amount

    @property
    def expectation(self) -> ExecutionExpectation:
        return self.evidence.expectation

    @property
    def behavior_hash(self) -> str:
        return self.evidence.behavior_hash

    @property
    def source_digest(self) -> str:
        return self.evidence.source_digest

    @property
    def dataset_id(self) -> str:
        return self.evidence.dataset_id

    @property
    def result_hash(self) -> str:
        return self.evidence.result_hash

    @property
    def permits_new_entries(self) -> bool:
        return self.state.stage is Stage.BROKER_SIM and self.state.run_state is RunState.RUNNING

    @property
    def protective_exits_required(self) -> bool:
        """Pausing/retiring never suppresses M2's independently owned protective exits."""
        return self.state.stage is not Stage.BACKTEST


@dataclass(frozen=True)
class PromotionEvaluation:
    strategy_id: str
    version: int
    trade_date: date
    observation_started_on: date
    observation: SimObservation
    verdict: PromotionVerdict
    observation_started_at: datetime | None = None


@dataclass(frozen=True)
class AutoStrategyEvent:
    record: AutoStrategyRecord
    evaluation: PromotionEvaluation | None = None


_EVENT_KINDS = frozenset(
    (
        'auto_strategy_built',
        'auto_stage_changed',
        'auto_promotion_evaluated',
        'auto_paused',
        'auto_resumed',
        'auto_retired',
        'auto_evidence_refreshed',
        'auto_live_intent_approved',
    )
)
# Explicit module-local registration follows automatic_state.py. Central engine
# registry/composition remains M3-4 work; decoding never imports incoming names.
register(
    AutoStrategy,
    CandidateEvidence,
    DirectionPolicy,
    SizingKind,
    SizingRule,
    WindowMode,
    HoldingKind,
    Stage,
    RunState,
    PauseReason,
    StageState,
    ExecutionExpectation,
    Check,
    PromotionVerdict,
    SimObservation,
    AutoStrategyRecord,
    PromotionEvaluation,
    AutoStrategyEvent,
    ExecutionEvidence,
    ResearchTrade,
    Side,
)


class PromotionService:
    def __init__(self, journal: Journal, environment: Environment, *, now: datetime) -> None:
        aware(now, 'now')
        self.journal = journal
        self.environment = environment
        self._records: dict[tuple[str, int], AutoStrategyRecord] = {}
        self._evaluations: dict[tuple[str, int, date], PromotionVerdict] = {}
        events = journal.replay()
        self._sequence = events[-1].sequence if events else 0
        for event in events:
            if event.kind in _EVENT_KINDS:
                payload = loads(event.payload)
                if not isinstance(payload, AutoStrategyEvent):
                    raise DomainError('validation_failed', 'auto event schema')
                self._restore(event.kind, payload)
        for record in tuple(self._records.values()):
            if record.state.stage is not Stage.BACKTEST and record.state.run_state is RunState.RUNNING:
                self.pause(record.auto.strategy_id, record.auto.version, PauseReason.RESTART, now=now)

    @classmethod
    def from_projection(
        cls,
        journal: Journal,
        environment: Environment,
        records: tuple[AutoStrategyRecord, ...],
        evaluations: tuple[PromotionEvaluation, ...],
        *,
        sequence: int,
    ) -> 'PromotionService':
        """Use the engine's already-decoded state without replaying or restarting it.

        The caller holds the engine writer lock; journal is its projection adapter,
        never the engine's underlying journal. Obtain a fresh service per operation.
        """
        service = cls.__new__(cls)
        service.journal, service.environment, service._sequence = journal, environment, sequence
        service._records = {(row.auto.strategy_id, row.auto.version): row for row in records}
        service._evaluations = {(item.strategy_id, item.version, item.trade_date): item.verdict for item in evaluations}
        return service

    def _restore(self, kind: str, event: AutoStrategyEvent) -> None:
        row = event.record
        if not isinstance(row, AutoStrategyRecord):
            raise DomainError('validation_failed', 'auto event record schema')
        previous = self._records.get((row.auto.strategy_id, row.auto.version))
        if previous is not None and (
            row.account_ref != previous.account_ref
            or row.execution_instrument_id != previous.execution_instrument_id
            or row.candidate != previous.candidate
            or replace(row.evidence, source_digest=previous.source_digest, result_hash=previous.result_hash) != previous.evidence
        ):
            raise DomainError('auto_frozen', 'replay changed a frozen version')
        item = event.evaluation
        if (kind == 'auto_promotion_evaluated') != (item is not None):
            raise DomainError('validation_failed', 'auto evaluation event shape')
        if item is not None and (
            not isinstance(item, PromotionEvaluation)
            or (item.strategy_id, item.version) != (row.auto.strategy_id, row.auto.version)
            or item.observation_started_on != row.observation_started_on
            or item.observation_started_at != row.observation_started_at
        ):
            raise DomainError('validation_failed', 'auto evaluation identity')
        self._apply(event)

    @property
    def records(self) -> tuple[AutoStrategyRecord, ...]:
        return tuple(self._records.values())

    def record(self, strategy_id: str, version: int) -> AutoStrategyRecord:
        try:
            return self._records[strategy_id, version]
        except KeyError:
            raise DomainError('validation_failed', 'unknown auto strategy version') from None

    def _apply(self, event: AutoStrategyEvent) -> None:
        row = event.record
        self._records[row.auto.strategy_id, row.auto.version] = row
        if event.evaluation is not None:
            item = event.evaluation
            self._evaluations[item.strategy_id, item.version, item.trade_date] = item.verdict

    def _write(self, kind: str, row: AutoStrategyRecord, now: datetime, evaluation: PromotionEvaluation | None = None) -> AutoStrategyRecord:
        event = AutoStrategyEvent(row, evaluation)
        stored = self.journal.append(kind, dumps(event), now, expected_sequence=self._sequence)
        self._sequence = stored.sequence
        self._apply(event)
        return row

    def record_built(self, record: AutoStrategyRecord, *, now: datetime) -> AutoStrategyRecord:
        key = record.auto.strategy_id, record.auto.version
        if key in self._records:
            raise DomainError('auto_frozen', 'strategy version already exists')
        if record.state != INITIAL_STATE or record.eligible or record.observation_started_on is not None or record.observation_started_at is not None:
            raise DomainError('stage_transition_denied', 'build must begin at BACKTEST')
        state = next_stage(None, Trigger.OWNER_BUILD, TransitionContext(self.environment))
        return self._write('auto_strategy_built', replace(record, state=state), now)

    def _require_sim(self) -> None:
        if self.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('stage_transition_denied', 'broker simulation required')

    def _require_unique(self, row: AutoStrategyRecord) -> None:
        for other in self.records:
            if (
                (other.auto.strategy_id, other.auto.version) != (row.auto.strategy_id, row.auto.version)
                and other.account_ref == row.account_ref
                and other.execution_instrument_id == row.execution_instrument_id
                and other.permits_new_entries
            ):
                raise DomainError('auto_instrument_busy', 'running auto strategy on instrument')

    def start_sim(
        self, strategy_id: str, version: int, *, trade_date: date, reproduced_behavior_hash: str, preopen_checks_passed: bool, now: datetime
    ) -> AutoStrategyRecord:
        row = self.record(strategy_id, version)
        self._require_unique(row)
        state = next_stage(
            row.state,
            Trigger.AUTO_START_SIM,
            TransitionContext(
                self.environment,
                start_in_sim=row.start_in_sim,
                reproduced=reproduced_behavior_hash == row.behavior_hash,
                preopen_checks_passed=preopen_checks_passed,
            ),
        )
        return self._write('auto_stage_changed', replace(row, state=state, observation_started_on=trade_date, observation_started_at=now), now)

    def evaluate_after_close(
        self, strategy_id: str, version: int, trade_date: date, observation: SimObservation, *, observation_started_on: date, now: datetime
    ) -> PromotionVerdict:
        self._require_sim()
        key = strategy_id, version, trade_date
        if key in self._evaluations:
            return self._evaluations[key]
        row = self.record(strategy_id, version)
        if not row.permits_new_entries:
            raise DomainError('stage_transition_denied', 'evaluation requires running simulation')
        if observation_started_on != row.observation_started_on or trade_date < observation_started_on:
            raise DomainError('validation_failed', 'observation epoch mismatch')
        trading_date(trade_date)
        verdict = evaluate_promotion(row.auto.holding_kind, row.expectation, observation, thresholds_for(row.auto.thresholds_version))
        item = PromotionEvaluation(strategy_id, version, trade_date, observation_started_on, observation, verdict, row.observation_started_at)
        self._write('auto_promotion_evaluated', replace(row, eligible=verdict.eligible), now, item)
        return verdict

    def check_drift(self, strategy_id: str, version: int, observed_drawdown_pct: Decimal, *, now: datetime) -> DriftVerdict:
        self._require_sim()
        row = self.record(strategy_id, version)
        result = evaluate_drift(row.expectation.max_drawdown_pct, observed_drawdown_pct, thresholds_for(row.auto.thresholds_version))
        if result.paused and row.state.stage is not Stage.BACKTEST and row.state.run_state is RunState.RUNNING:
            self.pause(strategy_id, version, PauseReason.DRIFT, now=now)
        return result

    def pause(self, strategy_id: str, version: int, reason: PauseReason = PauseReason.MANUAL, *, now: datetime) -> AutoStrategyRecord:
        row = self.record(strategy_id, version)
        trigger = Trigger.OWNER_PAUSE if reason is PauseReason.MANUAL else Trigger.AUTO_PAUSE
        state = next_stage(row.state, trigger, TransitionContext(self.environment, pause_reason=reason))
        return self._write('auto_paused', replace(row, state=state, eligible=False), now)

    def resume(self, strategy_id: str, version: int, *, trade_date: date, reconciled: bool, cause_cleared: bool, now: datetime) -> AutoStrategyRecord:
        row = self.record(strategy_id, version)
        self._require_unique(row)
        state = next_stage(row.state, Trigger.OWNER_RESUME, TransitionContext(self.environment, reconciled=reconciled, cause_cleared=cause_cleared))
        return self._write('auto_resumed', replace(row, state=state, eligible=False, observation_started_on=trade_date, observation_started_at=now), now)

    def retire(self, strategy_id: str, version: int, *, now: datetime) -> AutoStrategyRecord:
        row = self.record(strategy_id, version)
        state = next_stage(row.state, Trigger.OWNER_RETIRE, TransitionContext(self.environment))
        return self._write('auto_retired', replace(row, state=state, eligible=False), now)

    def refresh_evidence(self, strategy_id: str, version: int, evidence: ExecutionEvidence, *, now: datetime) -> AutoStrategyRecord:
        row = self.record(strategy_id, version)
        if (evidence.strategy_id, evidence.version, evidence.frozen_hash) != (strategy_id, version, row.auto.frozen_hash):
            raise DomainError('auto_evidence_changed', 'execution evidence version mismatch')
        if evidence.behavior_hash != row.behavior_hash:
            if row.state.stage is not Stage.BACKTEST and row.state.run_state is RunState.RUNNING:
                return self.pause(strategy_id, version, PauseReason.EVIDENCE_CHANGED, now=now)
            raise DomainError('auto_evidence_changed', 'execution behavior changed')
        elif replace(evidence, source_digest=row.source_digest, result_hash=row.result_hash) != row.evidence:
            raise DomainError('auto_evidence_changed', 'same behavior hash with different execution evidence')
        updated = replace(row, evidence=evidence)
        if evidence == row.evidence:
            return row
        return self._write('auto_evidence_refreshed', updated, now)
