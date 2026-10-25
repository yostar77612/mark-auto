"""Immutable, validated execution and read-side boundary values."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from quantlab.trading.domain.models import AccountSnapshot, Environment, OrderPlan, OrderStatus, QuantityUnit, Side
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer

BROKER_SDK_VERSION = '1.7.9'


@dataclass(frozen=True)
class ConnectionState:
    environment: Environment
    connected: bool
    account_refs: tuple[str, ...]
    checked_at: datetime
    reason: str = ''

    def __post_init__(self) -> None:
        aware(self.checked_at)
        if not isinstance(self.environment, Environment) or type(self.connected) is not bool or type(self.account_refs) is not tuple:
            raise DomainError('validation_failed', 'connection types')
        for value in self.account_refs:
            identity(value)


@dataclass(frozen=True)
class SubmissionReceipt:
    local_order_id: str
    broker_order_ref: str | None
    status: OrderStatus
    accepted_at: datetime
    outcome_known: bool = True
    reason: str = ''

    def __post_init__(self) -> None:
        identity(self.local_order_id)
        aware(self.accepted_at)
        if self.broker_order_ref is not None:
            identity(self.broker_order_ref)
        if not isinstance(self.status, OrderStatus) or type(self.outcome_known) is not bool:
            raise DomainError('validation_failed', 'receipt type')
        if not self.outcome_known and self.status is not OrderStatus.UNKNOWN:
            raise DomainError('validation_failed', 'unknown outcome status')


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    accepted: bool
    status: OrderStatus
    query_ref: str
    occurred_at: datetime
    reason: str = ''

    def __post_init__(self) -> None:
        identity(self.command_id)
        identity(self.query_ref)
        aware(self.occurred_at)
        if type(self.accepted) is not bool or not isinstance(self.status, OrderStatus):
            raise DomainError('validation_failed', 'command receipt type')


@dataclass(frozen=True)
class BrokerOrder:
    local_order_id: str
    plan: OrderPlan
    cumulative_quantity: int
    average_price: Decimal
    status: OrderStatus
    broker_order_ref: str
    updated_at: datetime

    def __post_init__(self) -> None:
        identity(self.local_order_id)
        identity(self.broker_order_ref)
        integer(self.cumulative_quantity, 'cumulative_quantity')
        decimal_value(self.average_price, 'average_price', nonnegative=True)
        aware(self.updated_at)
        if not isinstance(self.plan, OrderPlan) or not isinstance(self.status, OrderStatus) or self.cumulative_quantity > self.plan.quantity:
            raise DomainError('validation_failed', 'broker order quantities')


@dataclass(frozen=True)
class OrderEvent:
    event_id: str
    local_order_id: str
    broker_order_ref: str
    status: OrderStatus
    cumulative_quantity: int
    last_fill_quantity: int
    last_fill_price: Decimal
    occurred_at: datetime
    sequence: int
    source: str

    def __post_init__(self) -> None:
        for value in (self.event_id, self.local_order_id, self.broker_order_ref, self.source):
            identity(value)
        integer(self.cumulative_quantity, 'cumulative_quantity')
        integer(self.last_fill_quantity, 'last_fill_quantity')
        integer(self.sequence, 'sequence', 1)
        decimal_value(self.last_fill_price, 'last_fill_price', nonnegative=True)
        aware(self.occurred_at)
        if not isinstance(self.status, OrderStatus) or self.last_fill_quantity > self.cumulative_quantity:
            raise DomainError('validation_failed', 'event quantity/status')


@dataclass(frozen=True)
class FillEvent:
    account_ref: str
    execution_ref: str
    instrument_id: str
    side: Side
    quantity: int
    unit: QuantityUnit
    price: Decimal
    fee: Decimal | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        for value in (self.account_ref, self.execution_ref, self.instrument_id):
            identity(value)
        integer(self.quantity, 'quantity', 1)
        decimal_value(self.price, 'price', positive=True)
        if self.fee is not None:
            decimal_value(self.fee, 'fee', nonnegative=True)
        aware(self.occurred_at)
        if not isinstance(self.side, Side) or not isinstance(self.unit, QuantityUnit):
            raise DomainError('validation_failed', 'fill units')


@dataclass(frozen=True)
class BrokerPosition:
    account_ref: str
    instrument_id: str
    quantity: int
    sellable_quantity: int
    unit: QuantityUnit
    average_cost: Decimal
    source: str = 'EXTERNAL'

    def __post_init__(self) -> None:
        for value in (self.account_ref, self.instrument_id, self.source):
            identity(value)
        if type(self.quantity) is not int:
            raise DomainError('validation_failed', 'signed position quantity')
        integer(self.sellable_quantity, 'sellable_quantity')
        decimal_value(self.average_cost, 'average_cost', nonnegative=True)
        if not isinstance(self.unit, QuantityUnit) or self.sellable_quantity > abs(self.quantity):
            raise DomainError('validation_failed', 'position quantity/unit')


@dataclass(frozen=True)
class RemoteSnapshot:
    account: AccountSnapshot
    orders: tuple[BrokerOrder, ...]
    positions: tuple[BrokerPosition, ...]
    sequence: int
    as_of: datetime

    def __post_init__(self) -> None:
        aware(self.as_of)
        integer(self.sequence, 'sequence')
        if not isinstance(self.account, AccountSnapshot) or type(self.orders) is not tuple or type(self.positions) is not tuple:
            raise DomainError('validation_failed', 'snapshot types')
        if any(not isinstance(order, BrokerOrder) or order.plan.account_ref != self.account.account_ref for order in self.orders):
            raise DomainError('validation_failed', 'snapshot order account')
        if any(not isinstance(position, BrokerPosition) or position.account_ref != self.account.account_ref for position in self.positions):
            raise DomainError('validation_failed', 'snapshot position account')


@dataclass(frozen=True)
class SettlementItem:
    account_ref: str
    settlement_date: date
    amount: Decimal
    source: str

    def __post_init__(self) -> None:
        identity(self.account_ref)
        identity(self.source)
        if type(self.settlement_date) is not date:
            raise DomainError('validation_failed', 'settlement date')
        decimal_value(self.amount, 'settlement amount')


@dataclass(frozen=True)
class HistoryBar:
    instrument_id: str
    start: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.source)
        aware(self.start)
        aware(self.available_at)
        integer(self.volume, 'volume')
        for name in ('open', 'high', 'low', 'close'):
            decimal_value(getattr(self, name), name, positive=True)
        if self.available_at <= self.start or self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.high < self.low:
            raise DomainError('validation_failed', 'bar shape/availability')


@dataclass(frozen=True)
class DataBatch:
    instrument_id: str
    bars: tuple[HistoryBar, ...]
    source: str
    complete: bool
    reason: str = ''

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.source)
        if (
            type(self.complete) is not bool
            or type(self.bars) is not tuple
            or any(not isinstance(bar, HistoryBar) or bar.instrument_id != self.instrument_id for bar in self.bars)
        ):
            raise DomainError('validation_failed', 'data batch types')


@dataclass(frozen=True)
class SubscriptionReceipt:
    subscription_id: str
    instrument_ids: tuple[str, ...]
    active: bool
    as_of: datetime
    reason: str = ''

    def __post_init__(self) -> None:
        identity(self.subscription_id)
        aware(self.as_of)
        if type(self.instrument_ids) is not tuple or type(self.active) is not bool:
            raise DomainError('validation_failed', 'subscription types')
        for value in self.instrument_ids:
            identity(value)
