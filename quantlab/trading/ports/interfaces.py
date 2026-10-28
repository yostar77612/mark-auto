"""Narrow typed protocols; implementations may combine ports through composition."""

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, InstrumentSpec, OrderPlan, Quote
from quantlab.trading.domain.ticks import Tick
from .contracts import (
    BrokerPosition,
    CommandReceipt,
    ConnectionState,
    DataBatch,
    OrderEvent,
    RemoteSnapshot,
    SettlementItem,
    SubmissionReceipt,
    SubscriptionReceipt,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class ConnectionPort(Protocol):
    def connect(self, secret_ref: str, environment: Environment) -> ConnectionState: ...
    def disconnect(self) -> None: ...


class CapabilityPort(Protocol):
    def inspect(self, account_ref: str) -> CapabilitySnapshot: ...


class InstrumentPort(Protocol):
    def resolve(self, instrument_id: str) -> InstrumentSpec: ...


class MarketDataPort(Protocol):
    def history(self, instrument_id: str, start: datetime, end: datetime) -> DataBatch: ...
    def subscribe(self, instrument_ids: tuple[str, ...]) -> SubscriptionReceipt: ...
    def unsubscribe(self, subscription_id: str) -> None: ...
    def latest(self, instrument_id: str) -> Quote | None: ...
    def drain_ticks(self, max_items: int) -> tuple[Tick, ...]:
        """Consume at most max_items ticks in delivery order, once; zero drains none."""
        ...


class SessionResolver(Protocol):
    def session_at(self, instrument_id: str, timestamp: datetime) -> tuple[date, str]: ...


class AccountPort(Protocol):
    def snapshot(self, account_ref: str) -> AccountSnapshot: ...
    def settlements(self, account_ref: str) -> tuple[SettlementItem, ...]: ...


class PositionPort(Protocol):
    def list(self, account_ref: str) -> tuple[BrokerPosition, ...]: ...


class ExecutionPort(Protocol):
    def submit(self, plan: OrderPlan, local_order_id: str) -> SubmissionReceipt: ...
    def cancel(self, local_order_id: str) -> CommandReceipt: ...
    def amend(self, local_order_id: str, price: Decimal, quantity: int | None = None) -> CommandReceipt: ...
    def refresh(self, account_ref: str) -> RemoteSnapshot: ...


class OrderEventPort(Protocol):
    def events(self, account_ref: str, after_sequence: int = 0) -> tuple[OrderEvent, ...]: ...
