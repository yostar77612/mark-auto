"""M3 owner commands projected through the engine's existing single writer.

The lifecycle service never receives the engine's raw journal. Every M3 event is
stored as an AppState envelope so old and new journals have one replay format.
No function here submits, cancels, amends, or otherwise calls a broker gateway.
"""

from dataclasses import replace
from typing import TYPE_CHECKING

from .auto_strategy_views import AutoStrategyView, PromotionProgressView
from .codec import loads
from .contracts import AutoBuildRequest, AutoStrategyCommand, UiAction, UiCommand
from .promotion_service import AutoStrategyEvent, PromotionService
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.promotion import PauseReason, RunState, Stage, TransitionContext, Trigger, evaluate_drift, next_stage, thresholds_for
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import StoredEvent

if TYPE_CHECKING:
    from .engine import TradingEngine
    from .state import AppState


AUTO_STRATEGY_ACTIONS = frozenset(
    (
        UiAction.BUILD_AUTO_STRATEGY,
        UiAction.PAUSE_AUTO_STRATEGY,
        UiAction.RESUME_AUTO_STRATEGY,
        UiAction.RETIRE_AUTO_STRATEGY,
        UiAction.APPROVE_LIVE_INTENT,
    )
)


class _EngineProjectionJournal:
    def __init__(self, engine: 'TradingEngine') -> None:
        self.engine = engine

    def append(self, kind, payload, now, *, expected_sequence):
        engine = self.engine
        if expected_sequence != engine.state.version:
            raise DomainError('state_conflict', 'refresh auto strategy projection')
        event = loads(payload)
        if not isinstance(event, AutoStrategyEvent):
            raise DomainError('validation_failed', 'auto event projection required')
        row = event.record
        key = row.auto.strategy_id, row.auto.version
        existing = engine.state.auto_strategies
        records = tuple(row if (old.auto.strategy_id, old.auto.version) == key else old for old in existing)
        if not any((old.auto.strategy_id, old.auto.version) == key for old in existing):
            records = (*records, row)
        evaluations = engine.state.auto_promotion_evaluations
        if event.evaluation is not None:
            item = event.evaluation
            evaluations = (*evaluations, item)
        engine.fence()
        engine._persist(kind, replace(engine.state, auto_strategies=records, auto_promotion_evaluations=evaluations))
        # A sequence receipt for the lifecycle service, not a second durable event.
        return StoredEvent(engine.state.version, kind, payload, '', '')


def promotion_service(engine: 'TradingEngine') -> PromotionService:
    return PromotionService.from_projection(
        _EngineProjectionJournal(engine),
        engine.configuration.environment,
        engine.state.auto_strategies,
        engine.state.auto_promotion_evaluations,
        sequence=engine.state.version,
    )


def restarted_auto_records(records, environment):
    return tuple(
        replace(row, eligible=False, state=next_stage(row.state, Trigger.AUTO_PAUSE, TransitionContext(environment, pause_reason=PauseReason.RESTART)))
        if row.state.stage is not Stage.BACKTEST and row.state.run_state is RunState.RUNNING
        else row
        for row in records
    )


def execute_auto_strategy(engine: 'TradingEngine', command: UiCommand) -> str:
    if command.environment is not engine.configuration.environment or command.account_ref not in engine.gateways:
        raise DomainError('state_conflict', 'explicit auto strategy account/environment required')
    service = promotion_service(engine)
    if command.action is UiAction.BUILD_AUTO_STRATEGY:
        request = command.auto_build
        if not isinstance(request, AutoBuildRequest):
            raise DomainError('validation_failed', 'auto build request required')
        if engine.configuration.environment is Environment.LIVE:
            raise DomainError('production_orders_disabled')
        if request.account_ref not in engine.gateways or command.account_ref not in ('', request.account_ref):
            raise DomainError('state_conflict', 'auto build account mismatch')
        if engine.auto_runtime is None:
            raise DomainError('candidate_unavailable')
        engine.auto_runtime.build(request, service)
        return request.strategy_id
    intent = command.auto_strategy
    if not isinstance(intent, AutoStrategyCommand) or command.target_id not in ('', intent.strategy_id):
        raise DomainError('validation_failed', 'version-bound auto strategy intent required')
    row = service.record(intent.strategy_id, intent.version)
    if intent.frozen_hash != row.auto.frozen_hash or command.account_ref not in ('', row.account_ref):
        raise DomainError('state_conflict', 'auto strategy identity changed')
    now = engine.clock.now()
    if command.action is UiAction.PAUSE_AUTO_STRATEGY:
        service.pause(intent.strategy_id, intent.version, now=now)
    elif command.action is UiAction.RESUME_AUTO_STRATEGY:
        # The UI cannot assert reconciliation or evidence freshness. The trusted
        # runtime must reproduce those checks for this exact immutable version.
        if engine.auto_runtime is None:
            raise DomainError('capability_missing', 'auto strategy execution runtime unavailable')
        reconciled, cause_cleared = engine.auto_runtime.resume_checks(row)
        service.resume(intent.strategy_id, intent.version, trade_date=engine.state.trading_day, reconciled=reconciled, cause_cleared=cause_cleared, now=now)
    elif command.action is UiAction.RETIRE_AUTO_STRATEGY:
        if not intent.confirmed:
            raise DomainError('auto_confirmation_required')
        # Closing positions belongs to the existing execution coordinator. Until
        # it owns signal-strategy exits, never claim retirement flattened a lot.
        if any((lot.strategy_id, lot.strategy_version) == (intent.strategy_id, intent.version) and lot.quantity for lot in engine.state.positions):
            raise DomainError('auto_exit_required')
        if any(
            (order.plan.strategy_id, order.plan.strategy_version) == (intent.strategy_id, intent.version)
            and order.status.value in ('SUBMITTING', 'ACCEPTED', 'PARTIALLY_FILLED', 'CANCEL_PENDING', 'UNKNOWN')
            for order in engine.state.orders
        ):
            raise DomainError('auto_exit_required')
        service.retire(intent.strategy_id, intent.version, now=now)
    elif command.action is UiAction.APPROVE_LIVE_INTENT:
        if not intent.confirmed:
            raise DomainError('auto_confirmation_required')
        if engine.configuration.environment is not Environment.BROKER_SIMULATION or not row.eligible:
            raise DomainError('auto_not_eligible')
        state = next_stage(row.state, Trigger.OWNER_APPROVE_LIVE, TransitionContext(service.environment, eligible=row.eligible))
        service._write('auto_live_intent_approved', replace(row, state=state, eligible=False, live_approved_on=engine.state.trading_day), now)
    else:
        raise DomainError('validation_failed', 'unknown auto strategy command')
    return intent.strategy_id


def auto_strategy_views(state: 'AppState') -> tuple[AutoStrategyView, ...]:
    views = []
    for row in state.auto_strategies:
        evaluation = next(
            (
                item
                for item in reversed(state.auto_promotion_evaluations)
                if (item.strategy_id, item.version, item.observation_started_on, item.observation_started_at)
                == (row.auto.strategy_id, row.auto.version, row.observation_started_on, row.observation_started_at)
            ),
            None,
        )
        observation = evaluation.observation if evaluation else None
        observed = observation.max_drawdown_pct if observation is not None else None
        drift = evaluate_drift(row.expectation.max_drawdown_pct, observed, thresholds_for(row.auto.thresholds_version)) if observed is not None else None
        progress = PromotionProgressView(
            evaluation.verdict.checks if evaluation else (),
            row.eligible,
            observation.history_complete if observation else False,
            row.observation_started_on,
            drift.drift_line_pct if drift else None,
            observed,
        )
        views.append(
            AutoStrategyView(
                row.auto.strategy_id,
                row.auto.version,
                row.auto.holding_kind,
                row.auto.instrument_rule,
                row.state.stage,
                row.state.run_state,
                row.state.pause_reason,
                row.auto.frozen_hash,
                progress,
                account_ref=row.account_ref,
            )
        )
    return tuple(views)
