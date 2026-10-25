"""Durable reservation floors revalued with current specifications and costs."""

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from .state import ACTIVE
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import Reservation

if TYPE_CHECKING:
    from .engine import TradingEngine


@decimal_operation
def current_reservations(engine: 'TradingEngine') -> tuple[Reservation, ...]:
    result = []
    stops = dict(engine.state.protection_stops)
    for order in engine.state.orders:
        if order.plan.reduce_only:
            continue
        spec = engine.catalog.resolve(order.plan.instrument_id)
        owned = tuple(p for p in engine.state.positions if p.lot_id == order.order_id and p.quantity)
        pending = max(0, order.plan.quantity - order.filled) if order.status in ACTIVE else 0
        risk = sum(
            (
                engine.fees.loss_at_stop(
                    spec, lot.risk_entry_price or lot.entry_price, stops.get(lot.lot_id, order.plan.stop_price), lot.quantity, lot.direction
                )
                for lot in owned
            ),
            Decimal('0'),
        )
        if pending:
            risk += engine.fees.loss_at_stop(spec, order.plan.limit_price, order.plan.stop_price, pending, order.plan.side)
        cash = engine.fees.entry_cash(spec, order.plan.limit_price, pending, order.plan.side) if pending else Decimal('0')
        quantity = sum(lot.quantity for lot in owned) + pending
        if quantity:
            result.append(replace(order.reservation, quantity=quantity, risk=max(order.reservation.risk, risk), cash=max(order.reservation.cash, cash)))
    return tuple(result)
