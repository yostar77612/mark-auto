"""Monotone broker event reduction and explicit reconciliation of unknown work."""

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING
from hashlib import sha256

from .codec import dumps

from .execution import check_event
from .state import ACTIVE, EventCursor, replace_order
from .reconciliation_views import differences
from .reconciliation_state import confirmed_availability
from quantlab.trading.domain.models import Market, PositionLot, Side
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import OrderEvent

if TYPE_CHECKING:
    from .engine import TradingEngine

ZERO = Decimal('0')


def cursor(engine: 'TradingEngine', account: str) -> int:
    return next((c.sequence for c in engine.state.cursors if c.account_ref == account), 0)


def with_cursor(state, account: str, sequence: int):
    cursors = tuple(c for c in state.cursors if c.account_ref != account) + (EventCursor(account, sequence),)
    return replace(state, cursors=cursors)


@decimal_operation
def apply_event(engine: 'TradingEngine', event: OrderEvent, *, reconciled: bool = False) -> None:
    order = check_event(engine.state, event)
    if order is None:
        return
    account = order.plan.account_ref
    previous = cursor(engine, account)
    if not reconciled and event.sequence != previous + 1:
        raise DomainError('reconciliation_required', 'broker sequence gap')
    delta = event.cumulative_quantity - order.filled
    if delta and (event.last_fill_quantity != delta or event.last_fill_price <= 0):
        raise DomainError('reconciliation_required', 'fill economics incomplete')
    state = engine.state
    positions = list(state.positions)
    spec = engine.catalog.resolve(order.plan.instrument_id)
    cumulative_average = (order.average_price * order.filled + event.last_fill_price * delta) / event.cumulative_quantity if event.cumulative_quantity else ZERO
    fee = engine.fees.incremental_transaction(spec, order.plan.side, cumulative_average, event.cumulative_quantity, order.costs) if delta else ZERO
    realized = ZERO
    if delta:
        if order.plan.reduce_only:
            index = next((i for i, p in enumerate(positions) if p.lot_id == order.plan.exit_lot_id), None)
            if index is None or delta > positions[index].quantity:
                raise DomainError('reconciliation_required', 'exit fill exceeds owned lot')
            lot = positions[index]
            realized = (event.last_fill_price - lot.entry_price) * delta * spec.multiplier * (1 if lot.direction is Side.BUY else -1)
            positions[index] = replace(
                lot, quantity=lot.quantity - delta, sellable_quantity=max(0, lot.sellable_quantity - delta), realized_pnl=lot.realized_pnl + realized - fee
            )
            entry = next(o for o in state.orders if o.order_id == lot.lot_id)
            remaining = max(0, entry.reservation.quantity - delta)
            stop = dict(state.protection_stops).get(lot.lot_id, entry.plan.stop_price)
            risk = engine.fees.loss_at_stop(spec, lot.entry_price, stop, remaining, lot.direction) if remaining else ZERO
            entry = replace(entry, released_quantity=entry.released_quantity + delta, reservation=replace(entry.reservation, quantity=remaining, risk=risk))
            state = replace_order(state, entry)
        else:
            index = next((i for i, p in enumerate(positions) if p.lot_id == order.order_id), None)
            capability = engine.gateways[account].inspect(account)
            sellable = delta if spec.market is not Market.STOCK or capability.day_trade else 0
            if index is None:
                positions.append(
                    PositionLot(
                        order.order_id,
                        account,
                        spec.instrument_id,
                        order.plan.strategy_id,
                        order.plan.strategy_version,
                        order.policy,
                        delta,
                        event.last_fill_price,
                        state.trading_day,
                        sellable,
                        direction=order.plan.side,
                    )
                )
            else:
                lot = positions[index]
                average = (lot.entry_price * lot.quantity + event.last_fill_price * delta) / (lot.quantity + delta)
                positions[index] = replace(lot, quantity=lot.quantity + delta, entry_price=average, sellable_quantity=lot.sellable_quantity + sellable)
    average = (order.average_price * order.filled + event.last_fill_price * delta) / event.cumulative_quantity if event.cumulative_quantity else ZERO
    reservation = order.reservation
    # Broker cash/margin already accounts for filled quantity. Pending cash and
    # owned risk have different lifetimes; do not double reserve filled cash.
    terminal_ack = delta == 0 and event.status is order.status and order.status.value in ('FILLED', 'CANCELED', 'REJECTED')
    if not order.plan.reduce_only and not terminal_ack:
        pending = order.plan.quantity - event.cumulative_quantity if event.status in ACTIVE else 0
        total_open = event.cumulative_quantity + pending
        closed = order.released_quantity
        total_open = max(0, total_open - closed)
        required_risk = engine.fees.loss_at_stop(spec, order.plan.limit_price, order.plan.stop_price, total_open) if total_open else ZERO
        pending_cash = engine.fees.entry_cash(spec, order.plan.limit_price, pending, order.plan.side) if pending else ZERO
        reservation = replace(reservation, quantity=total_open, cash=pending_cash, risk=required_risk, status=event.status)
    order = replace(
        order,
        status=event.status,
        filled=event.cumulative_quantity,
        average_price=average,
        broker_ref=event.broker_order_ref,
        event_sequence=event.sequence,
        reservation=reservation,
        costs=order.costs + fee,
    )
    state = replace_order(state, order)
    event_key = f'{account}:{event.event_id}'
    state = replace(
        state,
        positions=tuple(positions),
        costs=state.costs + fee,
        realized_pnl=state.realized_pnl + realized - fee,
        event_ids=(*state.event_ids, event_key),
        event_hashes=(*state.event_hashes, (event_key, sha256(dumps(event).encode()).hexdigest())),
    )
    state = with_cursor(state, account, max(previous, event.sequence))
    engine._persist('broker_event_' + event.status.value.lower(), state)


def poll_events(engine: 'TradingEngine') -> None:
    try:
        for account, gateway in engine.gateways.items():
            for event in gateway.events(account, cursor(engine, account)):
                apply_event(engine, event)
    except DomainError as exc:
        engine._persist('event_quarantine', replace(engine.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*engine.state.issues, exc.code))))))
        raise


@decimal_operation
def reconcile(engine: 'TradingEngine') -> None:
    """Query-only reconciliation. Missing/ambiguous/external work stays visible."""
    from .sessions import synchronize_session, BASELINE_ISSUE

    synchronize_session(engine)
    engine._persist('reconciliation_started', replace(engine.state, stopped=True, reconciled=False))
    from .lifecycle import recover_corporate_actions

    recover_corporate_actions(engine)
    unresolved: list[str] = []
    for account, gateway in engine.gateways.items():
        try:
            remote = gateway.refresh(account)
        except Exception:
            engine._persist(
                'reconciliation_query_failed',
                replace(engine.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*engine.state.issues, 'reconciliation_required'))))),
            )
            raise DomainError('reconciliation_required', 'account query did not complete') from None
        local_orders = tuple(o for o in engine.state.orders if o.plan.account_ref == account)
        local_ids = {o.order_id for o in local_orders}
        if any(r.local_order_id not in local_ids and r.status in ACTIVE for r in remote.orders):
            unresolved.append('external_order_difference')
        for order in local_orders:
            match = next((r for r in remote.orders if r.local_order_id == order.order_id and r.plan == order.plan), None)
            if match is None:
                if order.status in ACTIVE:
                    unresolved.append('outcome_unknown')
                continue
            if match.cumulative_quantity < order.filled:
                unresolved.append('reconciliation_required')
                continue
            if match.cumulative_quantity != order.filled or match.status is not order.status:
                delta = match.cumulative_quantity - order.filled
                price = (match.average_price * match.cumulative_quantity - order.average_price * order.filled) / delta if delta else ZERO
                sequence = max(remote.sequence, order.event_sequence + 1)
                event = OrderEvent(
                    f'query:{account}:{order.order_id}:{sequence}:{match.cumulative_quantity}:{match.status.value}',
                    order.order_id,
                    match.broker_order_ref,
                    match.status,
                    match.cumulative_quantity,
                    delta,
                    price,
                    remote.as_of,
                    sequence,
                    'RECONCILED_QUERY',
                )
                apply_event(engine, event, reconciled=True)
        expected: dict[str, int] = {}
        for lot in engine.state.positions:
            if lot.account_ref == account and lot.origin == 'MANAGED':
                expected[lot.instrument_id] = expected.get(lot.instrument_id, 0) + lot.quantity * (1 if lot.direction is Side.BUY else -1)
        actual = {p.instrument_id: p.quantity for p in remote.positions if p.quantity}
        if {k: v for k, v in expected.items() if v} != actual:
            unresolved.append('external_position_difference')
        positions = confirmed_availability(engine.state, remote)
        retained = tuple(row for row in engine.state.reconciliation if row.account_ref != account)
        rows = differences(engine.state, remote)
        if rows:
            unresolved.extend('external_position_difference' if row.kind == 'POSITION' else 'external_order_difference' for row in rows)
        engine._persist(
            'account_reconciled', with_cursor(replace(engine.state, positions=tuple(positions), reconciliation=(*retained, *rows)), account, remote.sequence)
        )
    if any(job.status != 'APPLIED' for job in engine.state.corporate_actions):
        unresolved.append('reconciliation_required')
    issues = (*unresolved, BASELINE_ISSUE) if engine.state.daily_baseline_required else tuple(unresolved)
    state = replace(engine.state, reconciled=not unresolved, stopped=True, issues=tuple(sorted(set(issues))))
    engine._persist('reconciliation_complete' if not unresolved else 'reconciliation_unresolved', state)
    if unresolved:
        raise DomainError('reconciliation_required', 'unresolved account differences')
