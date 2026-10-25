"""Holding windows, eligibility and one exit coordinator."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from .arithmetic import decimal_operation
from .calendar import TradingCalendar
from .models import CapabilitySnapshot, HoldingKind, HoldingPolicy, InstrumentSpec, Market, PositionLot, Side
from .validation import DomainError, aware, decimal_value, integer


@dataclass(frozen=True)
class HoldingWindow:
    entry_day: date
    earliest_normal_exit: date
    latest_exit: date
    calendar_version: str


def holding_window(policy: HoldingPolicy, entry_day: date, calendar: TradingCalendar) -> HoldingWindow:
    return HoldingWindow(entry_day, calendar.advance(entry_day, policy.min_days), calendar.advance(entry_day, policy.max_days), calendar.version)


def check_entry_eligibility(spec: InstrumentSpec, policy: HoldingPolicy, capability: CapabilitySnapshot, side: Side, now: datetime) -> None:
    aware(now)
    if not capability.checked_at <= now < capability.expires_at:
        raise DomainError('eligibility_unknown', 'capability expired/not yet effective')
    if spec.market not in capability.markets or not capability.can_trade:
        raise DomainError('capability_missing', 'market trading not enabled')
    if spec.market is Market.STOCK and policy.kind is HoldingKind.INTRADAY and not capability.day_trade:
        raise DomainError('capability_missing', 'stock intraday requires verified qualification')
    if side is Side.SELL and not capability.short_sell:
        raise DomainError('capability_missing', 'short entry not supported')
    if spec.expiry is not None and now.date() > spec.expiry:
        raise DomainError('instrument_unresolved', 'contract expired')


@dataclass(frozen=True)
class ExitDecision:
    quantity: int
    reason: str
    blocked: bool
    requires_attention: bool


class ExitCoordinator:
    def plan(
        self,
        lot: PositionLot,
        spec: InstrumentSpec,
        capabilities: CapabilitySnapshot,
        calendar: TradingCalendar,
        trade_date: date,
        *,
        now: datetime,
        pending_exit_quantity: int = 0,
        protective: bool = False,
        requested_quantity: int | None = None,
    ) -> ExitDecision:
        integer(pending_exit_quantity, 'pending exit quantity')
        if lot.origin != 'MANAGED':
            return ExitDecision(0, 'external_position_not_managed', True, True)
        if not capabilities.checked_at <= aware(now) < capabilities.expires_at or not capabilities.can_trade:
            return ExitDecision(0, 'eligibility_unknown', True, True)
        if lot.account_ref != capabilities.account_ref or lot.instrument_id != spec.instrument_id or spec.market not in capabilities.markets:
            return ExitDecision(0, 'capability_missing', True, True)
        age = calendar.age(lot.holding_origin, trade_date)
        if not protective and age < lot.policy.min_days:
            return ExitDecision(0, 'normal_holding_minimum', True, False)
        available = min(lot.quantity, lot.sellable_quantity)
        if spec.market is Market.STOCK and trade_date == lot.entry_trade_date and not capabilities.day_trade:
            available = 0
        quantity = max(0, available - pending_exit_quantity)
        if requested_quantity is not None:
            integer(requested_quantity, 'requested exit quantity', 1)
            quantity = min(quantity, requested_quantity)
        if not quantity:
            return ExitDecision(0, 'exit_unavailable' if available == 0 else 'exit_already_pending', True, available == 0)
        return ExitDecision(quantity, 'protective_exit' if protective else 'policy_exit', False, False)


@decimal_operation
def corporate_action(lot: PositionLot, old: InstrumentSpec, new: InstrumentSpec, ratio: Decimal) -> PositionLot:
    decimal_value(ratio, 'action ratio', positive=True)
    if old.instrument_id != lot.instrument_id or new.instrument_id != lot.instrument_id or new.corporate_action_version == old.corporate_action_version:
        raise DomainError('reconciliation_required', 'unresolved corporate action versions')
    if old.market is not new.market or old.underlying != new.underlying or new.effective_at <= old.effective_at:
        raise DomainError('reconciliation_required', 'corporate action identity/effective time')
    quantity = Decimal(lot.quantity) * ratio
    sellable = Decimal(lot.sellable_quantity) * ratio
    if quantity != quantity.to_integral_value() or sellable != sellable.to_integral_value():
        raise DomainError('reconciliation_required', 'fractional corporate action requires broker reconciliation')
    # Contract multiplier changes preserve the economic entry notional.
    price = lot.entry_price * old.multiplier / (ratio * new.multiplier)
    risk_price = (lot.risk_entry_price or lot.entry_price) * old.multiplier / (ratio * new.multiplier)
    return replace(lot, quantity=int(quantity), sellable_quantity=int(sellable), entry_price=price, risk_entry_price=risk_price)


def transfer_position(lot: PositionLot, strategy_id: str, version: int, policy: HoldingPolicy, *, reconciled: bool, pending_orders: int) -> PositionLot:
    integer(version, 'strategy version', 1)
    integer(pending_orders, 'pending orders')
    if not reconciled or pending_orders or lot.origin != 'MANAGED':
        raise DomainError('reconciliation_required', 'position transfer requires reconciled ownership and no pending orders')
    if lot.policy.kind is HoldingKind.INTRADAY and policy.kind is not HoldingKind.INTRADAY:
        raise DomainError('risk_rejected', 'intraday residual cannot be relabelled')
    return replace(lot, strategy_id=strategy_id, strategy_version=version, policy=policy)
