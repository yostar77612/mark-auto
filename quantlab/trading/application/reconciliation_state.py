"""One allocation of observed sellable quantity to managed, matching lots."""

from dataclasses import replace

from .state import AppState
from quantlab.trading.domain.models import PositionLot, Side
from quantlab.trading.ports.contracts import RemoteSnapshot


def confirmed_availability(state: AppState, remote: RemoteSnapshot) -> tuple[PositionLot, ...]:
    observed = {p.instrument_id: p for p in remote.positions}
    available = {p.instrument_id: p.sellable_quantity for p in remote.positions}
    positions = []
    for lot in state.positions:
        if lot.account_ref != remote.account.account_ref:
            positions.append(lot)
            continue
        position = observed.get(lot.instrument_id)
        same_direction = position is not None and position.quantity * (1 if lot.direction is Side.BUY else -1) > 0
        sellable = min(lot.quantity, available.get(lot.instrument_id, 0)) if same_direction else 0
        available[lot.instrument_id] = max(0, available.get(lot.instrument_id, 0) - sellable)
        positions.append(replace(lot, sellable_quantity=sellable))
    return tuple(positions)
