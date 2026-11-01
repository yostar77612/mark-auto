"""Broker observations without inventing account funds or previous-close PnL."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity
from .contracts import BrokerOrder, BrokerPosition, OrderEvent


@dataclass(frozen=True)
class ManualPriceLimit:
    instrument_id: str
    lower: Decimal
    upper: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.source)
        aware(self.observed_at)
        decimal_value(self.lower, 'verified lower limit', positive=True)
        decimal_value(self.upper, 'verified upper limit', positive=True)
        if self.upper < self.lower:
            raise DomainError('instrument_unresolved', 'inverted daily limits')


@dataclass(frozen=True)
class ManualAccountObservation:
    account_ref: str
    environment: Environment
    orders: tuple[BrokerOrder, ...]
    positions: tuple[BrokerPosition, ...]
    events: tuple[OrderEvent, ...]
    as_of: datetime
    source: str = 'SHIOAJI_SCOPED_REFRESH_HEALTHY'
    amended_prices: tuple[tuple[str, Decimal], ...] = ()

    def __post_init__(self) -> None:
        identity(self.account_ref)
        identity(self.source)
        aware(self.as_of)
        if not isinstance(self.environment, Environment) or any(type(rows) is not tuple for rows in (self.orders, self.positions, self.events)):
            raise DomainError('validation_failed', 'typed manual account observation required')
        if any(not isinstance(row, BrokerOrder) or row.plan.account_ref != self.account_ref for row in self.orders):
            raise DomainError('reconciliation_required', 'observation order scope')
        if any(not isinstance(row, BrokerPosition) or row.account_ref != self.account_ref for row in self.positions):
            raise DomainError('reconciliation_required', 'observation position scope')
        if any(not isinstance(row, OrderEvent) for row in self.events):
            raise DomainError('validation_failed', 'typed order events required')
        if type(self.amended_prices) is not tuple:
            raise DomainError('validation_failed', 'typed amended prices required')
        for order_id, price in self.amended_prices:
            identity(order_id)
            decimal_value(price, 'observed amended price', positive=True)
