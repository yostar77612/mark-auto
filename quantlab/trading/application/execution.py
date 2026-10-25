"""Single execution authority: revalidate, reserve, journal, submit, reconcile."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Callable
from uuid import uuid4

from .codec import dumps
from .state import ACTIVE, AppState, LocalOrder, replace_order
from quantlab.trading.domain.models import OrderPlan, OrderStatus, Reservation
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import OrderEvent
from quantlab.trading.ports.interfaces import ExecutionPort


class ExecutionService:
    """Callbacks are internal composition; the public boundary remains typed."""

    def __init__(
        self,
        broker: ExecutionPort,
        persist: Callable[[str, AppState], None],
        fence: Callable[[], None],
        clock: Callable[[], datetime],
        after_remote: Callable[[], None] = lambda: None,
    ):
        self.broker, self.persist, self.fence, self.clock = broker, persist, fence, clock
        self.after_remote = after_remote

    def commit(
        self, state: AppState, plan: OrderPlan, policy, reservation: Reservation, key: str, validate: Callable[[], None], *, request_hash: str | None = None
    ) -> str:
        request_hash = request_hash or sha256(dumps(plan).encode()).hexdigest()
        for prior in state.orders:
            if prior.key == key:
                if prior.request_hash != request_hash:
                    raise DomainError('state_conflict', 'idempotency key reused with changed command')
                return prior.order_id
        if plan.state_version != state.version or self.clock() >= plan.deadline:
            raise DomainError('state_conflict', 'expired or stale order plan')
        if not plan.reduce_only and (state.stopped or not state.reconciled or state.engine_closed or state.trading_day in state.daily_locks):
            raise DomainError('risk_rejected', 'new entries are stopped or not reconciled')
        validate()
        order_id = uuid4().hex
        order = LocalOrder(order_id, key, request_hash, plan, policy, replace(reservation, reservation_id=order_id), OrderStatus.SUBMITTING)
        proposed = replace(state, orders=(*state.orders, order))
        self.persist('order_submitting', proposed)
        # A durable intent and live ownership must exist before ANY adapter call.
        self.fence()
        try:
            receipt = self.broker.submit(plan, order_id)
        except Exception:
            try:
                self.after_remote()
            finally:
                unknown = replace_order(proposed, replace(order, status=OrderStatus.UNKNOWN))
                self.persist('order_unknown', replace(unknown, stopped=True, reconciled=False, issues=tuple(sorted(set((*unknown.issues, 'outcome_unknown'))))))
            raise DomainError('outcome_unknown', 'submission needs remote reconciliation') from None
        try:
            self.after_remote()
        except Exception:
            unknown = replace_order(proposed, replace(order, status=OrderStatus.UNKNOWN))
            self.persist(
                'remote_persistence_unknown', replace(unknown, stopped=True, reconciled=False, issues=tuple(sorted(set((*unknown.issues, 'outcome_unknown')))))
            )
            raise DomainError('outcome_unknown', 'remote persistence must be reconciled') from None
        status = receipt.status if receipt.outcome_known else OrderStatus.UNKNOWN
        updated = replace(order, status=status, broker_ref=receipt.broker_order_ref or '')
        if status is OrderStatus.REJECTED:
            updated = replace(updated, reservation=replace(updated.reservation, cash=Decimal('0'), risk=Decimal('0'), quantity=0, status=status))
        acknowledged = replace_order(proposed, updated)
        if status is OrderStatus.UNKNOWN:
            acknowledged = replace(acknowledged, stopped=True, reconciled=False, issues=tuple(sorted(set((*acknowledged.issues, 'outcome_unknown')))))
        self.persist('submission_receipt', acknowledged)
        return order_id

    def cancel(self, state: AppState, order_id: str) -> None:
        order = next((v for v in state.orders if v.order_id == order_id), None)
        if order is None or order.status not in ACTIVE:
            raise DomainError('state_conflict', 'order is not cancelable')
        if order.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING):
            raise DomainError('reconciliation_required', 'unknown order must be located before cancel')
        self.persist('cancel_pending', replace_order(state, replace(order, status=OrderStatus.CANCEL_PENDING)))
        self.fence()
        self.broker.cancel(order_id)


def check_event(state: AppState, event: OrderEvent) -> LocalOrder | None:
    order = next((v for v in state.orders if v.order_id == event.local_order_id), None)
    if order is None:
        raise DomainError('reconciliation_required', 'unowned broker event')
    event_key = f'{order.plan.account_ref}:{event.event_id}'
    if event_key in state.event_ids:
        if dict(state.event_hashes).get(event_key) != sha256(dumps(event).encode()).hexdigest():
            raise DomainError('reconciliation_required', 'event identity reused with changed payload')
        return None
    if order.broker_ref and order.broker_ref != event.broker_order_ref:
        raise DomainError('reconciliation_required', 'broker reference changed')
    if event.cumulative_quantity < order.filled or event.cumulative_quantity > order.plan.quantity:
        raise DomainError('reconciliation_required', 'nonmonotone fill cumulative quantity')
    if event.sequence <= order.event_sequence:
        raise DomainError('reconciliation_required', 'out of order event')
    if order.status in (OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.FILLED):
        late_cancel_fill = (
            order.status is OrderStatus.CANCELED
            and event.cumulative_quantity > order.filled
            and event.status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED)
        )
        if not late_cancel_fill and (event.status is not order.status or event.cumulative_quantity != order.filled):
            raise DomainError('reconciliation_required', 'terminal order cannot be revived')
    if event.cumulative_quantity == order.plan.quantity and event.status is not OrderStatus.FILLED:
        raise DomainError('reconciliation_required', 'full cumulative fill with inconsistent status')
    return order
