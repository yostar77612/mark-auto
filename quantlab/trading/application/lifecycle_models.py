"""Durable lifecycle jobs; intent, external application and confirmation differ."""

from dataclasses import dataclass
from decimal import Decimal

from quantlab.trading.domain.lifecycle import CorporateAction
from quantlab.trading.domain.models import InstrumentSpec, OrderPlan, PositionLot


@dataclass(frozen=True)
class CorporateActionJob:
    job_id: str
    account_ref: str
    instrument_id: str
    old_spec: InstrumentSpec
    new_spec: InstrumentSpec
    action: CorporateAction
    before_lots: tuple[PositionLot, ...]
    after_lots: tuple[PositionLot, ...]
    receivable: Decimal
    status: str = 'PREPARED'
    error: str = ''


@dataclass(frozen=True)
class RollJob:
    job_id: str
    lot_id: str
    old_instrument_id: str
    new_instrument_id: str
    quantity: int
    source_lot: PositionLot
    destination_strategy_ref: str = ''
    status: str = 'CLOSE_PREPARED'
    close_order_id: str = ''
    open_order_id: str = ''
    close_plan: OrderPlan | None = None
    open_plan: OrderPlan | None = None
    error: str = ''
