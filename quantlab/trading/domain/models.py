"""Immutable public DTOs. Quantities are shares/contracts, money is Decimal."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum

from .validation import DomainError, aware, decimal_value, identity, integer, trading_date
from .arithmetic import decimal_operation


class Market(str, Enum):
    STOCK = 'STOCK'
    INDEX_FUTURE = 'INDEX_FUTURE'
    STOCK_FUTURE = 'STOCK_FUTURE'


class Environment(str, Enum):
    LOCAL = 'LOCAL'
    BROKER_SIMULATION = 'BROKER_SIMULATION'
    LIVE = 'LIVE'


class Side(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class QuantityUnit(str, Enum):
    SHARE = 'SHARE'
    CONTRACT = 'CONTRACT'


class HoldingKind(str, Enum):
    INTRADAY = 'INTRADAY'
    SWING = 'SWING'
    POSITION = 'POSITION'
    CUSTOM = 'CUSTOM'


class OrderStatus(str, Enum):
    CREATED = 'CREATED'
    VALIDATED = 'VALIDATED'
    RESERVED = 'RESERVED'
    SUBMITTING = 'SUBMITTING'
    ACCEPTED = 'ACCEPTED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCEL_PENDING = 'CANCEL_PENDING'
    CANCELED = 'CANCELED'
    REJECTED = 'REJECTED'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class PriceBand:
    """Half-open Decimal price interval with a zero-origin legal price grid."""

    lower: Decimal
    upper: Decimal | None
    tick: Decimal

    @decimal_operation
    def __post_init__(self) -> None:
        decimal_value(self.lower, 'band lower', nonnegative=True)
        decimal_value(self.tick, 'band tick', positive=True)
        if self.upper is not None:
            decimal_value(self.upper, 'band upper', positive=True)
            if self.upper <= self.lower or self.upper % self.tick:
                raise DomainError('validation_failed', 'band upper/grid')
        if self.lower % self.tick:
            raise DomainError('validation_failed', 'band lower/grid')


def validate_price_bands(bands: tuple[PriceBand, ...], *, base_tick: Decimal | None = None) -> None:
    """One complete-table validator shared with the SDK normalizer."""
    if base_tick is not None:
        decimal_value(base_tick, 'base tick', positive=True)
    if type(bands) is not tuple or len(bands) > 64 or any(not isinstance(band, PriceBand) for band in bands):
        raise DomainError('validation_failed', 'typed bounded price bands')
    if bands:
        if bands[0].lower != 0 or bands[-1].upper is not None or base_tick is not None and base_tick != bands[0].tick:
            raise DomainError('validation_failed', 'complete price bands/base tick required')
        for previous, current in zip(bands, bands[1:]):
            if previous.upper is None or previous.upper != current.lower:
                raise DomainError('validation_failed', 'price bands must be ordered without gaps or overlap')


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    market: Market
    currency: str
    unit: QuantityUnit
    lot_size: int
    multiplier: Decimal
    tick_size: Decimal
    underlying: str
    version: str
    source: str
    effective_at: datetime
    expiry: date | None = None
    margin: Decimal | None = None
    exchange: str = 'TWSE'
    delivery_month: str | None = None
    tick_rule_id: str = 'fixed-demo-v1'
    calendar_id: str = 'explicit-demo-v1'
    settlement_rule_id: str = 'cash-funded-v1'
    corporate_action_version: str = 'none-v1'
    schema_version: int = 2
    price_bands: tuple[PriceBand, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            'instrument_id',
            'underlying',
            'version',
            'source',
            'exchange',
            'tick_rule_id',
            'calendar_id',
            'settlement_rule_id',
            'corporate_action_version',
        ):
            identity(getattr(self, name), name)
        if not isinstance(self.market, Market) or not isinstance(self.unit, QuantityUnit) or self.schema_version != 2 or self.currency != 'TWD':
            raise DomainError('validation_failed', 'instrument type/schema/currency')
        integer(self.lot_size, 'lot_size', 1)
        decimal_value(self.multiplier, 'multiplier', positive=True)
        decimal_value(self.tick_size, 'tick_size', positive=True)
        validate_price_bands(self.price_bands, base_tick=self.tick_size)
        aware(self.effective_at)
        expected = QuantityUnit.SHARE if self.market is Market.STOCK else QuantityUnit.CONTRACT
        if self.unit is not expected or self.market is Market.STOCK and self.multiplier != 1:
            raise DomainError('validation_failed', 'quantity unit/multiplier')
        if self.margin is not None:
            decimal_value(self.margin, 'margin', positive=True)
        if self.expiry is not None:
            trading_date(self.expiry)
        if self.market is not Market.STOCK:
            if self.expiry is None or self.delivery_month is None or len(self.delivery_month) != 6 or not self.delivery_month.isdigit():
                raise DomainError('instrument_unresolved', 'actual delivery month and expiry required')
            if (
                not 1 <= int(self.delivery_month[4:]) <= 12
                or int(self.delivery_month[:4]) != self.expiry.year
                or int(self.delivery_month[4:]) != self.expiry.month
            ):
                raise DomainError('instrument_unresolved', 'delivery month disagrees with expiry')

    def validate_quantity(self, quantity: int, unit: QuantityUnit, *, odd_lot: bool = False) -> None:
        integer(quantity, 'quantity', 1)
        if unit is not self.unit or quantity % self.lot_size and not (self.market is Market.STOCK and odd_lot):
            raise DomainError('validation_failed', 'quantity unit or trading lot')

    def tick_for(self, price: Decimal) -> Decimal:
        decimal_value(price, 'price', positive=True)
        for band in self.price_bands:
            if band.lower <= price and (band.upper is None or price < band.upper):
                return band.tick
        return self.tick_size

    @decimal_operation
    def validate_price(self, price: Decimal) -> None:
        decimal_value(price, 'price', positive=True)
        if price % self.tick_for(price):
            raise DomainError('validation_failed', 'price tick')

    @decimal_operation
    def round_price(self, price: Decimal, *, up: bool = False) -> Decimal:
        decimal_value(price, 'price', positive=True)
        if type(up) is not bool:
            raise DomainError('validation_failed', 'price rounding direction')
        tick = self.tick_for(price)
        rounded = (price / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick
        self.validate_price(rounded)
        return rounded

    @decimal_operation
    def shift_ticks(self, price: Decimal, signed_ticks: int) -> Decimal:
        """Move along the executable grid, using the preceding band on a down-step.

        Every boundary belongs to the upper band for validation, but the next
        lower legal price uses the lower band's tick. Jump by whole intervals
        rather than looping per tick; runtime is bounded by the band count.
        """
        self.validate_price(price)
        integer(abs(signed_ticks) if type(signed_ticks) is int else signed_ticks, 'signed tick movement')
        if not self.price_bands:
            result = price + self.tick_size * signed_ticks
            self.validate_price(result)
            return result
        remaining = abs(signed_ticks)
        current = price
        upwards = signed_ticks >= 0
        while remaining:
            index = next(i for i, band in enumerate(self.price_bands) if band.lower <= current and (band.upper is None or current < band.upper))
            if not upwards and index and current == self.price_bands[index].lower:
                index -= 1
            band = self.price_bands[index]
            boundary = band.upper if upwards else band.lower
            available = remaining if boundary is None else int(abs(boundary - current) / band.tick)
            steps = min(remaining, available)
            if not steps:
                raise DomainError('validation_failed', 'tick movement crosses zero')
            current += band.tick * steps * (1 if upwards else -1)
            remaining -= steps
            if current <= 0:
                raise DomainError('validation_failed', 'tick movement crosses zero')
        self.validate_price(current)
        return current

    @decimal_operation
    def slippage_distance(self, price: Decimal, ticks: int) -> Decimal:
        """Worst adverse distance in either direction, including band crossings."""
        decimal_value(price, 'slippage reference', positive=True)
        integer(ticks, 'slippage ticks')
        if not self.price_bands or not ticks:
            return self.tick_size * ticks
        # A cumulative fill/VWAP is a valid valuation basis even when it lies
        # between grid points. Round outwards, never reject that known basis.
        up = self.shift_ticks(self.round_price(price, up=True), ticks) - price
        try:
            down = price - self.shift_ticks(self.round_price(price), -ticks)
        except DomainError:
            # A nonpositive quote cannot execute; a complete loss to zero is
            # still a conservative bound for every positive down-grid price.
            down = price
        return max(up, down)


@dataclass(frozen=True)
class HoldingPolicy:
    kind: HoldingKind = HoldingKind.SWING
    min_days: int = 3
    max_days: int = 5
    night_enabled: bool = False
    expiry_action: str = 'EXIT'

    def __post_init__(self) -> None:
        integer(self.min_days, 'min_days')
        integer(self.max_days, 'max_days')
        if not isinstance(self.kind, HoldingKind) or self.max_days < self.min_days or self.max_days > 10000 or type(self.night_enabled) is not bool:
            raise DomainError('validation_failed', 'holding policy')
        if self.kind is HoldingKind.INTRADAY and (self.min_days or self.max_days):
            raise DomainError('validation_failed', 'intraday must use day zero')
        if self.expiry_action not in ('EXIT', 'ROLL'):
            raise DomainError('validation_failed', 'expiry_action')


@dataclass(frozen=True)
class AccountSnapshot:
    account_ref: str
    environment: Environment
    equity: Decimal
    allocated_cash: Decimal
    settled_cash: Decimal
    broker_limit: Decimal
    settlement_reserved: Decimal
    margin_used: Decimal
    as_of: datetime
    version: int
    unsettled_receivables: Decimal = Decimal('0')

    def __post_init__(self) -> None:
        identity(self.account_ref)
        if not isinstance(self.environment, Environment):
            raise DomainError('validation_failed', 'environment')
        for name in ('equity', 'allocated_cash', 'settled_cash', 'broker_limit', 'settlement_reserved', 'margin_used', 'unsettled_receivables'):
            decimal_value(getattr(self, name), name, nonnegative=True)
        aware(self.as_of)
        integer(self.version, 'version')


@dataclass(frozen=True)
class CapabilitySnapshot:
    account_ref: str
    environment: Environment
    markets: frozenset[Market]
    day_trade: bool
    short_sell: bool
    odd_lot: bool
    can_query: bool
    can_trade: bool
    source: str
    checked_at: datetime
    expires_at: datetime
    version: str
    ca_ready: bool = False

    def __post_init__(self) -> None:
        identity(self.account_ref)
        identity(self.source)
        identity(self.version)
        if not isinstance(self.environment, Environment) or type(self.markets) is not frozenset or any(not isinstance(m, Market) for m in self.markets):
            raise DomainError('validation_failed', 'capability types')
        if any(type(getattr(self, field)) is not bool for field in ('day_trade', 'short_sell', 'odd_lot', 'can_query', 'can_trade', 'ca_ready')):
            raise DomainError('validation_failed', 'capability flags')
        aware(self.checked_at)
        aware(self.expires_at)
        if self.expires_at <= self.checked_at:
            raise DomainError('validation_failed', 'capability expiry')


@dataclass(frozen=True)
class Quote:
    instrument_id: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    source_at: datetime
    received_at: datetime
    trade_date: date
    session: str = 'DAY'
    sequence: int | None = None
    source: str = 'LOCAL_SIMULATED'
    quality: str = 'VERIFIED'

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        for name in ('bid', 'ask', 'last'):
            decimal_value(getattr(self, name), name, positive=True)
        aware(self.source_at)
        aware(self.received_at)
        trading_date(self.trade_date)
        if self.received_at < self.source_at or self.bid > self.ask or self.session not in ('DAY', 'NIGHT'):
            raise DomainError('validation_failed', 'quote ordering/session')
        if self.sequence is not None:
            integer(self.sequence, 'sequence')
        identity(self.source)


@dataclass(frozen=True)
class OrderPlan:
    plan_id: str
    account_ref: str
    environment: Environment
    instrument_id: str
    strategy_id: str
    strategy_version: int
    side: Side
    quantity: int
    unit: QuantityUnit
    limit_price: Decimal
    stop_price: Decimal
    reduce_only: bool
    decision_at: datetime
    deadline: datetime
    state_version: int
    exit_lot_id: str | None = None

    def __post_init__(self) -> None:
        for name in ('plan_id', 'account_ref', 'instrument_id', 'strategy_id'):
            identity(getattr(self, name), name)
        integer(self.strategy_version, 'strategy_version', 1)
        integer(self.quantity, 'quantity', 1)
        integer(self.state_version, 'state_version')
        if (
            not isinstance(self.environment, Environment)
            or not isinstance(self.side, Side)
            or not isinstance(self.unit, QuantityUnit)
            or type(self.reduce_only) is not bool
        ):
            raise DomainError('validation_failed', 'order enum/bool types')
        decimal_value(self.limit_price, 'limit_price', positive=True)
        decimal_value(self.stop_price, 'stop_price', positive=True)
        aware(self.decision_at)
        aware(self.deadline)
        if self.deadline <= self.decision_at:
            raise DomainError('validation_failed', 'order deadline')
        if self.exit_lot_id is not None:
            identity(self.exit_lot_id)


@dataclass(frozen=True)
class PositionLot:
    lot_id: str
    account_ref: str
    instrument_id: str
    strategy_id: str
    strategy_version: int
    policy: HoldingPolicy
    quantity: int
    entry_price: Decimal
    entry_trade_date: date
    sellable_quantity: int
    origin: str = 'MANAGED'
    realized_pnl: Decimal = Decimal('0')
    direction: Side = Side.BUY
    risk_entry_price: Decimal | None = None
    holding_origin_trade_date: date | None = None

    def __post_init__(self) -> None:
        for name in ('lot_id', 'account_ref', 'instrument_id', 'strategy_id'):
            identity(getattr(self, name))
        integer(self.strategy_version, 'strategy_version', 1)
        integer(self.quantity, 'quantity')
        integer(self.sellable_quantity, 'sellable_quantity')
        decimal_value(self.entry_price, 'entry_price', positive=True)
        decimal_value(self.realized_pnl, 'realized_pnl')
        if self.risk_entry_price is not None:
            decimal_value(self.risk_entry_price, 'risk entry basis', positive=True)
        trading_date(self.entry_trade_date)
        if self.holding_origin_trade_date is not None:
            trading_date(self.holding_origin_trade_date)
            if self.holding_origin_trade_date > self.entry_trade_date:
                raise DomainError('validation_failed', 'holding origin cannot follow actual entry')
        if (
            not isinstance(self.direction, Side)
            or not isinstance(self.policy, HoldingPolicy)
            or self.sellable_quantity > self.quantity
            or self.origin not in ('MANAGED', 'EXTERNAL')
        ):
            raise DomainError('validation_failed', 'position policy/quantity/origin')

    @property
    def holding_origin(self) -> date:
        return self.holding_origin_trade_date or self.entry_trade_date


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    account_ref: str
    instrument_id: str
    group: str
    cash: Decimal
    risk: Decimal
    quantity: int
    status: OrderStatus

    def __post_init__(self) -> None:
        for name in ('reservation_id', 'account_ref', 'instrument_id', 'group'):
            identity(getattr(self, name))
        decimal_value(self.cash, 'cash', nonnegative=True)
        decimal_value(self.risk, 'risk', nonnegative=True)
        integer(self.quantity, 'quantity')
        if not isinstance(self.status, OrderStatus):
            raise DomainError('validation_failed', 'reservation status')


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    code: str
    quantity: int
    cash_required: Decimal
    risk_required: Decimal
    unit_risk: Decimal
    remaining_daily_risk: Decimal

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise DomainError('validation_failed', 'risk allowed')
        identity(self.code)
        integer(self.quantity, 'quantity')
        for name in ('cash_required', 'risk_required', 'unit_risk'):
            decimal_value(getattr(self, name), name, nonnegative=True)
        decimal_value(self.remaining_daily_risk, 'remaining_daily_risk')
