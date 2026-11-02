"""Durable automatic execution claims. Caller journals each returned state first."""

from dataclasses import dataclass, replace
from datetime import datetime

from quantlab.trading.domain.auto_cycle import EvaluationCursor, ForceExitWindow, force_exit_due, should_evaluate
from quantlab.trading.application.codec import register
from quantlab.trading.domain.models import OrderStatus


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

    @property
    def cursors(self) -> tuple[EvaluationCursor, ...]:
        return tuple(row.cursor for row in self.evaluations)


register(OrderStatus, EvaluationCursor, EvaluationStatus, ForcedAttempt, AutomaticState)
