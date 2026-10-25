"""One side-effect-free risk authority. Preview never authorizes execution."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .arithmetic import decimal_operation
from .costs import ZERO, FeeSchedule
from .models import AccountSnapshot, CapabilitySnapshot, Environment, HoldingPolicy, InstrumentSpec, Market, OrderPlan, Quote, Reservation, RiskDecision, Side
from .policies import check_entry_eligibility
from .validation import DomainError, aware, decimal_value, identity, integer


@dataclass(frozen=True)
class RiskPolicy:
    total_budget: Decimal = Decimal('100000')
    trade_fraction: Decimal = Decimal('0.02')
    daily_fraction: Decimal = Decimal('0.10')
    group_fraction: Decimal = Decimal('0.04')
    max_quote_age_seconds: int = 30
    max_account_age_seconds: int = 60
    version: str = 'local-risk-v2'

    def __post_init__(self) -> None:
        decimal_value(self.total_budget, 'total_budget', positive=True)
        for name in ('trade_fraction', 'daily_fraction', 'group_fraction'):
            value = decimal_value(getattr(self, name), name, positive=True)
            if value > 1:
                raise DomainError('validation_failed', name)
        if self.trade_fraction not in (Decimal('0.02'), Decimal('0.03')) or self.daily_fraction > Decimal('0.10'):
            raise DomainError('validation_failed', 'risk bounds exceed the authorized policy')
        integer(self.max_quote_age_seconds, 'max_quote_age_seconds', 1)
        integer(self.max_account_age_seconds, 'max_account_age_seconds', 1)
        identity(self.version)


@dataclass(frozen=True)
class DailyRiskState:
    trade_date: str
    opening_equity: Decimal
    net_pnl: Decimal = ZERO
    locked: bool = False

    def __post_init__(self) -> None:
        try:
            valid_day = type(self.trade_date) is str and date.fromisoformat(self.trade_date).isoformat() == self.trade_date
        except ValueError:
            valid_day = False
        if not valid_day or type(self.locked) is not bool:
            raise DomainError('validation_failed', 'daily risk date/lock')
        decimal_value(self.opening_equity, 'opening equity', positive=True)
        decimal_value(self.net_pnl, 'net pnl')

    @decimal_operation
    def mark(self, net_pnl: Decimal, policy: RiskPolicy) -> 'DailyRiskState':
        decimal_value(net_pnl, 'net pnl')
        decimal_value(self.opening_equity, 'opening equity', positive=True)
        locked = self.locked or -net_pnl >= min(self.opening_equity, policy.total_budget) * policy.daily_fraction
        return DailyRiskState(self.trade_date, self.opening_equity, net_pnl, locked)


class RiskService:
    def __init__(self, policy: RiskPolicy, fees: FeeSchedule) -> None:
        if not isinstance(policy, RiskPolicy) or not isinstance(fees, FeeSchedule):
            raise DomainError('validation_failed', 'risk policy/cost schedule')
        self.policy = policy
        self.fees = fees

    def _check_context(
        self,
        plan: OrderPlan,
        spec: InstrumentSpec,
        quote: Quote,
        account: AccountSnapshot,
        capabilities: CapabilitySnapshot,
        now: datetime,
        policy: HoldingPolicy,
    ) -> None:
        aware(now)
        if (
            plan.account_ref != account.account_ref
            or account.account_ref != capabilities.account_ref
            or plan.environment is not account.environment
            or account.environment is not capabilities.environment
        ):
            raise DomainError('capability_missing', 'account/environment mismatch')
        if plan.instrument_id != spec.instrument_id or quote.instrument_id != spec.instrument_id:
            raise DomainError('instrument_unresolved', 'instrument identity mismatch')
        if plan.deadline <= now or plan.decision_at > now or plan.state_version != account.version:
            raise DomainError('state_conflict', 'stale plan')
        if not capabilities.checked_at <= now < capabilities.expires_at or not capabilities.can_trade or spec.market not in capabilities.markets:
            raise DomainError('eligibility_unknown', 'capability missing/expired')
        if plan.environment is Environment.LIVE and not capabilities.ca_ready:
            raise DomainError('capability_missing', 'CA unavailable')
        age = (now - quote.source_at).total_seconds()
        receive_age = (now - quote.received_at).total_seconds()
        account_age = (now - account.as_of).total_seconds()
        if not 0 <= age <= self.policy.max_quote_age_seconds or not 0 <= receive_age <= self.policy.max_quote_age_seconds or quote.quality != 'VERIFIED':
            raise DomainError('stale_quote')
        if not 0 <= account_age <= self.policy.max_account_age_seconds:
            raise DomainError('state_conflict', 'account valuation stale')
        if spec.effective_at > now or spec.expiry is not None and quote.trade_date > spec.expiry:
            raise DomainError('instrument_unresolved', 'specification not effective')
        spec.validate_quantity(plan.quantity, plan.unit, odd_lot=capabilities.odd_lot)
        spec.validate_price(plan.limit_price)
        if quote.session == 'NIGHT' and not policy.night_enabled:
            raise DomainError('session_closed', 'night execution disabled')
        if not plan.reduce_only:
            check_entry_eligibility(spec, policy, capabilities, plan.side, now)
            spec.validate_price(plan.stop_price)
            if plan.side is Side.BUY and plan.stop_price >= plan.limit_price or plan.side is Side.SELL and plan.stop_price <= plan.limit_price:
                raise DomainError('risk_rejected', 'stop must be on the loss side')
            if spec.market is not Market.STOCK and spec.margin is None:
                raise DomainError('risk_rejected', 'verified margin missing')

    @decimal_operation
    def preview(
        self,
        plan: OrderPlan,
        spec: InstrumentSpec,
        quote: Quote,
        account: AccountSnapshot,
        capabilities: CapabilitySnapshot,
        *,
        now: datetime,
        reservations: tuple[Reservation, ...] = (),
        daily_pnl: Decimal = ZERO,
        daily_locked: bool = False,
        allocations: tuple[AccountSnapshot, ...] = (),
        policy: HoldingPolicy | None = None,
        strategy_cash_limit: Decimal | None = None,
    ) -> RiskDecision:
        if not all(
            (
                isinstance(plan, OrderPlan),
                isinstance(spec, InstrumentSpec),
                isinstance(quote, Quote),
                isinstance(account, AccountSnapshot),
                isinstance(capabilities, CapabilitySnapshot),
            )
        ):
            raise DomainError('validation_failed', 'risk DTO types')
        decimal_value(daily_pnl, 'daily_pnl')
        if strategy_cash_limit is not None:
            decimal_value(strategy_cash_limit, 'strategy cash limit', nonnegative=True)
        if type(daily_locked) is not bool or type(reservations) is not tuple or any(not isinstance(r, Reservation) for r in reservations):
            raise DomainError('validation_failed', 'risk reservation context')
        daily_remaining = self.policy.total_budget * self.policy.daily_fraction - max(ZERO, -daily_pnl) - sum((r.risk for r in reservations), ZERO)
        try:
            self._check_context(plan, spec, quote, account, capabilities, now, policy or HoldingPolicy())
            self._check_allocations(allocations or (account,))
            if plan.reduce_only:
                return RiskDecision(True, 'risk_accepted', plan.quantity, ZERO, ZERO, ZERO, daily_remaining)
            if daily_locked or daily_remaining <= 0:
                raise DomainError('risk_rejected', 'daily stop is latched or exhausted')
            cash_limit, risk_limit = self._limits(account, spec, reservations, daily_remaining)
            if strategy_cash_limit is not None:
                cash_limit = min(cash_limit, strategy_cash_limit)
            lot_size = 1 if spec.market is Market.STOCK and capabilities.odd_lot else spec.lot_size
            quantity = self._size(plan, spec, lot_size, cash_limit, risk_limit)
            if not quantity:
                raise DomainError('insufficient_funds' if cash_limit <= 0 else 'risk_rejected', 'no legal quantity fits')
            cash = self.fees.entry_cash(spec, plan.limit_price, quantity, plan.side)
            risk = self.fees.loss_at_stop(spec, plan.limit_price, plan.stop_price, quantity, plan.side)
            code = 'risk_accepted' if quantity == plan.quantity else 'risk_resized'
            return RiskDecision(True, code, quantity, cash, risk, self.fees.unit_risk(spec, plan.limit_price, plan.stop_price, plan.side), daily_remaining)
        except DomainError as exc:
            return RiskDecision(False, exc.code, 0, ZERO, ZERO, ZERO, daily_remaining)

    def _check_allocations(self, allocations: tuple[AccountSnapshot, ...]) -> None:
        if type(allocations) is not tuple or any(not isinstance(a, AccountSnapshot) for a in allocations):
            raise DomainError('validation_failed', 'account allocations')
        identities = [(a.account_ref, a.environment) for a in allocations]
        if len(set(identities)) != len(identities) or sum((a.allocated_cash for a in allocations), ZERO) > self.policy.total_budget:
            raise DomainError('risk_rejected', 'shared allocations exceed the single platform budget')

    def _limits(
        self, account: AccountSnapshot, spec: InstrumentSpec, reservations: tuple[Reservation, ...], daily_remaining: Decimal
    ) -> tuple[Decimal, Decimal]:
        account_reserved = sum((r.cash for r in reservations if r.account_ref == account.account_ref), ZERO)
        pool_reserved = sum((r.cash for r in reservations), ZERO)
        group_reserved = sum((r.risk for r in reservations if r.group == spec.underlying), ZERO)
        cash = min(account.allocated_cash, account.settled_cash, account.broker_limit) - account.settlement_reserved - account.margin_used - account_reserved
        cash = min(cash, self.policy.total_budget - pool_reserved)
        risk = min(
            self.policy.total_budget * self.policy.trade_fraction, daily_remaining, self.policy.total_budget * self.policy.group_fraction - group_reserved
        )
        return max(ZERO, cash), max(ZERO, risk)

    def _size(self, plan: OrderPlan, spec: InstrumentSpec, lot_size: int, cash_limit: Decimal, risk_limit: Decimal) -> int:
        low, high = 0, plan.quantity // lot_size
        while low < high:
            middle = (low + high + 1) // 2
            quantity = middle * lot_size
            cash = self.fees.entry_cash(spec, plan.limit_price, quantity, plan.side)
            risk = self.fees.loss_at_stop(spec, plan.limit_price, plan.stop_price, quantity, plan.side)
            if cash <= cash_limit and risk <= risk_limit:
                low = middle
            else:
                high = middle - 1
        return low * lot_size
