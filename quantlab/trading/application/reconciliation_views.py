"""Explicit observed/local quantities, without adopting external assets."""

from datetime import timezone

from .contracts import ReconciliationView
from .state import ACTIVE, AppState
from quantlab.trading.domain.models import Side
from quantlab.trading.ports.contracts import RemoteSnapshot


def differences(state: AppState, remote: RemoteSnapshot) -> tuple[ReconciliationView, ...]:
    account = remote.account.account_ref
    stamp = remote.as_of.astimezone(timezone.utc).isoformat()
    expected: dict[str, int] = {}
    units = {}
    for lot in state.positions:
        if lot.account_ref == account and lot.origin == 'MANAGED':
            expected[lot.instrument_id] = expected.get(lot.instrument_id, 0) + lot.quantity * (1 if lot.direction is Side.BUY else -1)
    actual = {p.instrument_id: p for p in remote.positions if p.quantity}
    for order in state.orders:
        units[order.plan.instrument_id] = order.plan.unit
    result = []
    for instrument in sorted(set(expected) | set(actual)):
        observed = actual.get(instrument)
        local, broker = expected.get(instrument, 0), observed.quantity if observed else 0
        if local != broker:
            result.append(
                ReconciliationView(
                    account,
                    instrument,
                    local,
                    broker,
                    observed.sellable_quantity if observed else 0,
                    observed.unit if observed else units[instrument],
                    as_of=stamp,
                )
            )
    local_orders = {o.order_id: o for o in state.orders if o.plan.account_ref == account}
    for order in remote.orders:
        local = local_orders.get(order.local_order_id)
        if order.status in ACTIVE and (local is None or local.plan != order.plan):
            sign = 1 if order.plan.side is Side.BUY else -1
            quantity = (order.plan.quantity - order.cumulative_quantity) * sign
            local_quantity = (local.plan.quantity - local.filled) * (1 if local.plan.side is Side.BUY else -1) if local else 0
            result.append(
                ReconciliationView(
                    account,
                    order.plan.instrument_id,
                    local_quantity,
                    quantity,
                    None,
                    order.plan.unit,
                    'ORDER',
                    order.broker_order_ref,
                    order.status.value,
                    stamp,
                )
            )
    remote_ids = {o.local_order_id for o in remote.orders}
    for order in local_orders.values():
        if order.status in ACTIVE and order.order_id not in remote_ids:
            quantity = (order.plan.quantity - order.filled) * (1 if order.plan.side is Side.BUY else -1)
            result.append(
                ReconciliationView(account, order.plan.instrument_id, quantity, None, None, order.plan.unit, 'ORDER', order.broker_ref, 'UNKNOWN', stamp)
            )
    return tuple(result)
