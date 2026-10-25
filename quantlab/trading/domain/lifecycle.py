"""Explicit corporate actions and expiry/roll plans without fabricated fills."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from .arithmetic import decimal_operation
from .calendar import TradingCalendar
from .costs import FeeSchedule
from .models import InstrumentSpec, Market, PositionLot, Side
from .policies import corporate_action
from .validation import DomainError, aware, decimal_value, identity, integer, trading_date


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    old_spec_version: str
    new_spec_version: str
    effective_at: datetime
    quantity_ratio: Decimal
    cash_per_old_unit: Decimal
    cash_payable_date: date | None
    source: str

    def __post_init__(self) -> None:
        for name in ('action_id', 'old_spec_version', 'new_spec_version', 'source'):
            identity(getattr(self, name))
        aware(self.effective_at)
        decimal_value(self.quantity_ratio, 'quantity ratio', positive=True)
        decimal_value(self.cash_per_old_unit, 'corporate cash', nonnegative=True)
        if self.cash_payable_date is not None:
            trading_date(self.cash_payable_date)
        if self.cash_per_old_unit and self.cash_payable_date is None:
            raise DomainError('reconciliation_required', 'corporate cash payment date missing')


@dataclass(frozen=True)
class CorporateActionResult:
    action_id: str
    lot: PositionLot
    receivable: Decimal
    payable_date: date | None


@decimal_operation
def apply_corporate_action(lot: PositionLot, old: InstrumentSpec, new: InstrumentSpec, action: CorporateAction, *, now: datetime) -> CorporateActionResult:
    if (
        old.version != action.old_spec_version
        or new.version != action.new_spec_version
        or new.effective_at != action.effective_at
        or aware(now) < action.effective_at
    ):
        raise DomainError('reconciliation_required', 'corporate action version/effective time mismatch')
    if action.cash_per_old_unit and old.market is not Market.STOCK:
        raise DomainError('reconciliation_required', 'futures cash adjustment needs an explicit settlement event')
    adjusted = corporate_action(lot, old, new, action.quantity_ratio)
    adjusted = replace(adjusted, risk_entry_price=(adjusted.risk_entry_price or adjusted.entry_price) - action.cash_per_old_unit / action.quantity_ratio)
    sign = Decimal('1') if lot.direction is Side.BUY else Decimal('-1')
    return CorporateActionResult(action.action_id, adjusted, action.cash_per_old_unit * lot.quantity * sign, action.cash_payable_date)


@dataclass(frozen=True)
class ExpiryPlan:
    action: str
    close_instrument_id: str
    open_instrument_id: str | None
    close_side: Side
    open_side: Side | None
    quantity: int
    deadline: date
    estimated_cost: Decimal
    required_fills: int


@decimal_operation
def plan_expiry(
    lot: PositionLot,
    current: InstrumentSpec,
    next_contract: InstrumentSpec | None,
    calendar: TradingCalendar,
    *,
    now: datetime,
    close_price: Decimal,
    open_price: Decimal | None,
    fees: FeeSchedule,
    roll_before_days: int = 1,
) -> ExpiryPlan | None:
    aware(now)
    integer(roll_before_days, 'roll before trading days')
    if current.market is Market.STOCK or current.expiry is None or current.instrument_id != lot.instrument_id:
        raise DomainError('instrument_unresolved', 'real futures position required')
    session = calendar.session_at(now, allow_night=lot.policy.night_enabled)
    expiry_index = calendar.index(current.expiry)
    trigger_index = expiry_index - roll_before_days
    if trigger_index < 0:
        raise DomainError('calendar_missing', 'expiry cutoff not covered')
    if calendar.index(session.trade_date) < trigger_index:
        return None
    if session.trade_date > current.expiry:
        raise DomainError('reconciliation_required', 'position crossed expiry without verified settlement')
    close_side = Side.SELL if lot.direction is Side.BUY else Side.BUY
    costs = fees.transaction(current, close_side, close_price, lot.quantity) + fees.slippage(current, lot.quantity, legs=1, prices=(close_price,))
    if lot.policy.expiry_action == 'EXIT':
        return ExpiryPlan('EXIT', current.instrument_id, None, close_side, None, lot.quantity, current.expiry, costs, 1)
    if next_contract is None or open_price is None or next_contract.expiry is None:
        raise DomainError('instrument_unresolved', 'roll requires an explicit priced next contract')
    if (
        next_contract.market is not current.market
        or next_contract.underlying != current.underlying
        or next_contract.expiry <= current.expiry
        or next_contract.instrument_id == current.instrument_id
    ):
        raise DomainError('instrument_unresolved', 'invalid roll contract')
    if next_contract.effective_at > now:
        raise DomainError('instrument_unresolved', 'next contract specification not effective')
    next_contract.validate_quantity(lot.quantity, next_contract.unit)
    next_contract.validate_price(open_price)
    costs += fees.transaction(next_contract, lot.direction, open_price, lot.quantity) + fees.slippage(next_contract, lot.quantity, legs=1, prices=(open_price,))
    return ExpiryPlan('ROLL', current.instrument_id, next_contract.instrument_id, close_side, lot.direction, lot.quantity, current.expiry, costs, 2)


@decimal_operation
def net_liquidation_pnl(lot: PositionLot, spec: InstrumentSpec, price: Decimal, fees: FeeSchedule) -> Decimal:
    """Conservative mark including both entry and estimated exit fees and slippage."""
    decimal_value(price, 'mark price', positive=True)
    if lot.instrument_id != spec.instrument_id:
        raise DomainError('instrument_unresolved', 'valuation instrument mismatch')
    sign = Decimal('1') if lot.direction is Side.BUY else Decimal('-1')
    gross = (price - lot.entry_price) * spec.multiplier * lot.quantity * sign
    costs = fees.round_trip(spec, lot.entry_price, price, lot.quantity, lot.direction) + fees.slippage(spec, lot.quantity, prices=(lot.entry_price, price))
    return lot.realized_pnl + gross - costs
