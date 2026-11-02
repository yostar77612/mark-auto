"""Durable automatic execution claims. Caller journals each returned state first."""

from dataclasses import dataclass, replace
from datetime import datetime

from quantlab.trading.domain.auto_cycle import EvaluationCursor, ForceExitWindow, force_exit_due, should_evaluate
from quantlab.trading.application.codec import register
from quantlab.trading.domain.models import OrderStatus
from .daily_state import DailyIntent, DailyState
from . import daily_state as daily_claims


@dataclass(frozen=True)
class EvaluationStatus:
    cursor: EvaluationCursor
    evaluated_at: datetime
    next_evaluation_at: datetime | None = None
    phase: str = 'CLAIMED'
    order_result: OrderStatus | None = None
    order_id: str = ''
    code: str = ''


@dataclass(frozen=True)
class ForcedAttempt:
    lot_id: str
    attempt: int
    attempted_at: datetime
    status: OrderStatus = OrderStatus.SUBMITTING
    order_id: str = ''

    @property
    def key(self) -> str:
        return f'forced-exit:{self.lot_id}:{self.attempt}'


@dataclass(frozen=True)
class AutomaticState:
    auto_paused: bool = True
    reasons: tuple[str, ...] = ('program_restarted',)
    resumed_at: datetime | None = None
    evaluations: tuple[EvaluationStatus, ...] = ()
    forced_attempts: tuple[ForcedAttempt, ...] = ()
    daily: DailyState = DailyState()

    @property
    def cursors(self) -> tuple[EvaluationCursor, ...]:
        return tuple(row.cursor for row in self.evaluations)


def pause(state: AutomaticState, reason: str) -> AutomaticState:
    return replace(state, auto_paused=True, reasons=tuple(sorted(set((*state.reasons, reason)))), daily=daily_claims.revoke(state.daily))


def restart(state: AutomaticState) -> AutomaticState:
    """Retain claims so a crash cannot replay evaluation or ambiguous submission."""
    evaluations = tuple(replace(row, phase='INTERRUPTED') if row.phase == 'CLAIMED' else row for row in state.evaluations)
    attempts = tuple(
        replace(row, status=OrderStatus.UNKNOWN) if row.status in (OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING) else row for row in state.forced_attempts
    )
    return pause(replace(state, evaluations=evaluations, forced_attempts=attempts, daily=daily_claims.restart(state.daily)), 'program_restarted')


def resume(state: AutomaticState, now: datetime, *, user_confirmed: bool, reconciled: bool, preflight_passed: bool) -> AutomaticState | None:
    """Automatic-only action, after current server-side proofs; manual resume never calls it."""
    if not user_confirmed or not reconciled or not preflight_passed:
        return None
    if any(row.phase in ('CLAIMED', 'INTERRUPTED') or row.order_result is OrderStatus.UNKNOWN for row in state.evaluations):
        return None
    if any(row.status in (OrderStatus.SUBMITTING, OrderStatus.UNKNOWN, OrderStatus.CANCEL_PENDING) for row in state.forced_attempts):
        return None
    return replace(state, auto_paused=False, reasons=(), resumed_at=now)


def _identity(cursor: EvaluationCursor) -> tuple[str, int, str, str]:
    return cursor.strategy_id, cursor.version, cursor.instrument_id, cursor.interval


def claim_cursor(state: AutomaticState, cursor: EvaluationCursor, evaluated_at: datetime, next_evaluation_at: datetime | None = None) -> AutomaticState | None:
    if state.auto_paused or state.resumed_at is None:
        return None
    if not state.resumed_at < cursor.bar_end <= evaluated_at:
        return None
    previous = next((row for row in state.evaluations if _identity(row.cursor) == _identity(cursor)), None)
    if previous is not None and previous.phase != 'COMPLETED':
        return None
    if not should_evaluate(previous.cursor if previous else None, *_identity(cursor), cursor.bar_end):
        return None
    row = EvaluationStatus(cursor, evaluated_at, next_evaluation_at)
    retained = tuple(old for old in state.evaluations if _identity(old.cursor) != _identity(cursor))
    return replace(state, evaluations=(*retained, row))


def complete_evaluation(
    state: AutomaticState, cursor: EvaluationCursor, result: OrderStatus | None = None, *, order_id: str = '', code: str = '', observed: bool = False
) -> AutomaticState | None:
    previous = next((row for row in state.evaluations if row.cursor == cursor), None)
    if previous is None:
        return None
    if previous.order_id and previous.order_id != order_id:
        return None
    if previous.phase != 'CLAIMED' and not observed:
        return None
    if observed and result is OrderStatus.UNKNOWN:
        return None
    if previous.order_result is OrderStatus.UNKNOWN and result is None:
        return None
    row = replace(previous, phase='COMPLETED', order_result=result, order_id=order_id, code=code)
    updated = replace(state, evaluations=tuple(row if old.cursor == cursor else old for old in state.evaluations))
    return pause(updated, 'order_result_unknown') if result is OrderStatus.UNKNOWN else updated


def claim_force_attempt(state: AutomaticState, lot_id: str, window: ForceExitWindow, now: datetime) -> AutomaticState | None:
    """Protective exits remain available while paused; retry only a proven terminal miss."""
    previous = next((row for row in state.forced_attempts if row.lot_id == lot_id), None)
    if previous is not None and previous.status not in (OrderStatus.CANCELED, OrderStatus.REJECTED):
        return None
    if not force_exit_due(window, now, previous.attempted_at if previous else None):
        return None
    row = ForcedAttempt(lot_id, previous.attempt + 1 if previous else 1, now)
    return replace(state, forced_attempts=(*tuple(old for old in state.forced_attempts if old.lot_id != lot_id), row))


def transition_force_attempt(
    state: AutomaticState, lot_id: str, attempt: int, status: OrderStatus, *, order_id: str = '', observed: bool = False
) -> AutomaticState | None:
    previous = next((row for row in state.forced_attempts if row.lot_id == lot_id and row.attempt == attempt), None)
    if previous is None:
        return None
    if previous.order_id and previous.order_id != order_id:
        return None
    if status is OrderStatus.CANCELED and not observed:
        return None
    allowed = {
        OrderStatus.SUBMITTING: (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.UNKNOWN),
        OrderStatus.ACCEPTED: (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCEL_PENDING, OrderStatus.UNKNOWN),
        OrderStatus.PARTIALLY_FILLED: (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCEL_PENDING, OrderStatus.UNKNOWN),
        OrderStatus.CANCEL_PENDING: (OrderStatus.CANCELED, OrderStatus.FILLED, OrderStatus.UNKNOWN),
    }
    permitted = status in allowed.get(previous.status, ())
    if observed and previous.status is OrderStatus.UNKNOWN:
        permitted = status in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)
    if observed and status is OrderStatus.CANCELED and previous.status in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
        permitted = True
    if not permitted:
        return None
    row = replace(previous, status=status, order_id=order_id)
    updated = replace(state, forced_attempts=tuple(row if old.lot_id == lot_id else old for old in state.forced_attempts))
    return pause(updated, 'order_result_unknown') if status is OrderStatus.UNKNOWN else updated


register(OrderStatus, EvaluationCursor, DailyIntent, DailyState, EvaluationStatus, ForcedAttempt, AutomaticState)
