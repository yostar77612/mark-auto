"""Local strategy lifecycle, scheduling, valuation and distinct engine controls."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from .codec import dumps
from .events import poll_events, reconcile
from .execution import ExecutionService
from .research import research
from .state import ACTIVE
from .performance import advance_tracks, unrealized_liquidation
from quantlab.trading.domain.models import Environment, HoldingKind
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.policies import transfer_position
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine
    from .state import AppState
    from quantlab.trading.domain.strategy import CompletedBar

ZERO = Decimal('0')


def run_research(engine: 'TradingEngine', reference: str, bars: tuple['CompletedBar', ...]) -> None:
    record = engine.strategy(reference)
    if record.state not in ('RULE_VALID', 'RESEARCHED'):
        raise DomainError('risk_rejected', 'validate rules before research')
    spec = engine.catalog.resolve(record.form.instrument_id)
    training = tuple(bar for bar in bars if spec.effective_at <= bar.opened_at and bar.available_at < engine.clock.now())
    if engine.profile is None:
        raise DomainError('source_invalid_evidence', 'v2 producer profile required')
    calendar, fees, profile = engine.calendar, engine.fees, engine.profile
    with engine.lock.suspended():
        if engine.research_runner is None:
            result = research(record, spec, calendar, training, fees, source_profile=profile)
        else:
            result = engine.research_runner.run(
                record, spec, calendar, training, fees, deadline=engine.ownership_clock() + timedelta(minutes=15), source_profile=profile
            )
    current = engine.strategy(reference)
    if (
        current.form != record.form
        or current.definition != record.definition
        or current.state != record.state
        or current.evidence_hash != record.evidence_hash
        or engine.calendar != calendar
        or engine.fees != fees
        or engine.catalog.resolve(spec.instrument_id) != spec
        or engine.profile != profile
        or engine.state.engine_closed
        or engine.storage_failed
    ):
        raise DomainError('state_conflict', 'research inputs or lifecycle changed while computing')
    engine.update_strategy(
        replace(record, state='RESEARCHED', evidence='LOCAL_SYNTHETIC_TRAINING', evidence_hash=result.fingerprint, research_blob=dumps(result)),
        'training_research_completed',
    )


def cancel_entries(engine: 'TradingEngine') -> None:
    engine.assert_execution_allowed()
    failures = []
    for order in tuple(engine.state.orders):
        if order.status in ACTIVE and not order.plan.reduce_only:
            service = ExecutionService(engine.gateways[order.plan.account_ref], engine._persist, engine.fence, engine.clock.now)
            try:
                service.cancel(engine.state, order.order_id)
            except DomainError as exc:
                failures.append(exc.code)
    if engine.simulation:
        engine.simulation.persist_remote()
    poll_events(engine)
    if failures:
        engine._persist(
            'entry_cancel_requires_attention',
            replace(engine.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*engine.state.issues, *failures))))),
        )


def resume(engine: 'TradingEngine') -> None:
    if not engine.state.reconciled or engine.state.issues or engine.storage_failed or engine.state.engine_closed:
        raise DomainError('reconciliation_required', 'engine requires reconciled healthy state')
    if engine.state.trading_day in engine.state.daily_locks:
        raise DomainError('risk_rejected', 'daily loss stop cannot be cleared today')
    if any(job.status != 'APPLIED' for job in engine.state.corporate_actions) or any(job.status == 'FROZEN' for job in engine.state.rolls):
        raise DomainError('reconciliation_required', 'durable lifecycle work remains unresolved')
    engine.fence()
    engine._persist('entries_resumed_explicitly', replace(engine.state, stopped=False))


def transfer(engine: 'TradingEngine', lot_id: str, destination: str) -> None:
    lot = next((p for p in engine.state.positions if p.lot_id == lot_id and p.quantity), None)
    strategy = engine.strategy(destination)
    if strategy.state not in ('ACTIVE', 'RESEARCHED') or not strategy.evidence_hash:
        raise DomainError('risk_rejected', 'validated destination version required')
    if lot is None or strategy.form.account_ref != lot.account_ref or strategy.form.instrument_id != lot.instrument_id:
        raise DomainError('state_conflict', 'transfer scope mismatch')
    pending = sum(o.status in ACTIVE and o.plan.instrument_id == lot.instrument_id for o in engine.state.orders)
    moved = transfer_position(lot, strategy.strategy_id, strategy.version, strategy.policy, reconciled=engine.state.reconciled, pending_orders=pending)
    proposed = replace(engine.state, positions=tuple(moved if p.lot_id == lot_id else p for p in engine.state.positions))
    tracks = advance_tracks(engine, proposed_state=proposed)
    engine._persist('position_transferred_explicitly', replace(proposed, performance_tracks=tracks))


@decimal_operation
def total_mark(engine: 'TradingEngine') -> Decimal:
    result = engine.state.realized_pnl
    for lot in engine.state.positions:
        if not lot.quantity:
            continue
        result += unrealized_liquidation(engine, lot)
    return result


@decimal_operation
def _risk_mark(engine: 'TradingEngine') -> 'tuple[AppState, bool] | None':
    if engine.configuration.environment is not Environment.LOCAL and engine.state.daily_baseline_required:
        return None  # No invented new-day zero/baseline; protection remains independent.
    pnl = total_mark(engine) - engine.state.daily_baseline_pnl
    settings = engine.state.settings
    hit = -pnl >= Decimal('100000') * settings.daily_loss_fraction
    locks = engine.state.daily_locks
    if hit and engine.state.trading_day not in locks:
        locks = (*locks, engine.state.trading_day)
    tracks = advance_tracks(engine)
    proposed = replace(engine.state, daily_pnl=pnl, daily_locks=locks, stopped=engine.state.stopped or hit, performance_tracks=tracks)
    return proposed, hit


def observe_risk(engine: 'TradingEngine') -> None:
    """Record the same valuation/stop without issuing any execution command."""
    prepared = _risk_mark(engine)
    if prepared is not None:
        proposed, _hit = prepared
        if proposed != engine.state:
            engine._persist('portfolio_observed_read_only', proposed)


@decimal_operation
def mark_risk(engine: 'TradingEngine') -> None:
    prepared = _risk_mark(engine)
    if prepared is None:
        return
    proposed, hit = prepared
    engine._persist('portfolio_marked', proposed)
    if hit:
        try:
            cancel_entries(engine)
        except DomainError:
            # A bad unrelated report cannot suppress a legal known-lot exit.
            # Storage/ownership failures remain authoritative in submit/fence.
            pass
        # Protective exits are attempted independently; illegal stock exits stay
        # visible rather than inventing an intraday qualification or fill.
        for lot in tuple(engine.state.positions):
            if lot.quantity:
                try:
                    engine.exit_lot(lot.lot_id, protective=True)
                except DomainError as exc:
                    if engine.storage_failed:
                        raise
                    engine._persist(
                        'protective_exit_requires_attention', replace(engine.state, stopped=True, issues=tuple(sorted(set((*engine.state.issues, exc.code)))))
                    )


@decimal_operation
def fill_local_pending(engine: 'TradingEngine') -> None:
    if engine.simulation is None or engine.state.environment is not Environment.LOCAL:
        raise DomainError('capability_missing', 'local-only simulation control')
    for order in tuple(engine.state.orders):
        if order.status.value not in ('ACCEPTED', 'PARTIALLY_FILLED'):
            continue
        remaining = order.plan.quantity - order.filled
        if not remaining:
            continue
        spec = engine.catalog.resolve(order.plan.instrument_id)
        # All current plans are limit orders. Spread/slippage is represented in
        # the decision quote and cost reserve, never a fill beyond its limit.
        price = order.plan.limit_price
        average = (order.average_price * order.filled + price * remaining) / order.plan.quantity
        fee = engine.fees.incremental_transaction(spec, order.plan.side, average, order.plan.quantity, order.costs)
        engine.fence()
        engine.simulation.fill(order.plan.account_ref, order.order_id, remaining, price, fee)
        engine.simulation.persist_remote()
    poll_events(engine)


def step(engine: 'TradingEngine', history: dict[str, tuple['CompletedBar', ...]]) -> None:
    if engine.state.environment is not Environment.LOCAL or engine.simulation is None or engine.state.engine_closed:
        raise DomainError('capability_missing', 'only running local simulation can advance')
    next_day = engine.calendar.advance(engine.state.trading_day, 1)
    baseline = total_mark(engine)
    tracks = tuple(replace(track, daily_baseline=track.equity, trade_date=next_day) for track in advance_tracks(engine))
    now = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=5)
    engine.simulation.advance(next_day, now)
    engine._persist('trading_day_advanced', replace(engine.state, trading_day=next_day, daily_baseline_pnl=baseline, daily_pnl=ZERO, performance_tracks=tracks))
    # Simulation composition updates quote state through the regular quote port.
    for instrument, bars in history.items():
        current = next((b for b in bars if b.opened_at.date() == next_day), None)
        if current:
            spec = engine.catalog.resolve(instrument)
            from quantlab.trading.domain.models import Quote

            engine.quote(Quote(instrument, current.open, spec.shift_ticks(current.open, 1), current.open, now, now, next_day, sequence=engine.quote_count + 1))
    reconcile(engine)
    # Reconciliation keeps new risk stopped until explicitly resumed. A normal
    # local day step retains an already-authorized RUNNING decision across days.
    # The caller remembers that intent, while restart always remains stopped.


def execute_day(engine: 'TradingEngine', history: dict[str, tuple['CompletedBar', ...]], *, allow_entries: bool) -> None:
    from .coordinator import run_cycle
    from .lifecycle import run_lifecycle

    if engine.state.environment is not Environment.LOCAL or engine.simulation is None:
        raise DomainError('capability_missing', 'explicit day-end composition is local-only')
    run_lifecycle(engine)
    fill_local_pending(engine)
    run_lifecycle(engine)
    fill_local_pending(engine)
    run_lifecycle(engine)
    run_cycle(engine, history, allow_entries=allow_entries)
    fill_local_pending(engine)
    # This action represents a complete simulated day, unlike a broker tick.
    # It explicitly reaches the local intraday end boundary without changing
    # the injected clock or pretending broker orders filled synchronously.
    for lot in tuple(engine.state.positions):
        if lot.quantity and lot.policy.kind is HoldingKind.INTRADAY:
            engine.exit_lot(lot.lot_id, protective=True)
    fill_local_pending(engine)
    mark_risk(engine)
