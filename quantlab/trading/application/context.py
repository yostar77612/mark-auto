"""Injected account-scoped application dependencies."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .engine import TradingEngine
    from .state import StrategyRecord
    from .research import ResearchResult
    from .provenance import ProducerProfile
    from quantlab.trading.domain.calendar import TradingCalendar
    from quantlab.trading.domain.costs import FeeSchedule
    from quantlab.trading.domain.strategy import CompletedBar

from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, InstrumentSpec, Quote
from quantlab.trading.ports.contracts import OrderEvent, RemoteSnapshot
from quantlab.trading.ports.interfaces import ExecutionPort


class AccountGateway(ExecutionPort, Protocol):
    def snapshot(self, account_ref: str) -> AccountSnapshot: ...
    def inspect(self, account_ref: str) -> CapabilitySnapshot: ...
    def events(self, account_ref: str, after_sequence: int = 0) -> tuple[OrderEvent, ...]: ...
    def refresh(self, account_ref: str) -> RemoteSnapshot: ...


class ResearchRunner(Protocol):
    def run(
        self,
        strategy: 'StrategyRecord',
        spec: InstrumentSpec,
        calendar: 'TradingCalendar',
        bars: tuple['CompletedBar', ...],
        fees: 'FeeSchedule',
        *,
        deadline: datetime,
        source_profile: 'ProducerProfile | None' = None,
    ) -> 'ResearchResult': ...
    def close(self) -> None: ...


class LocalSimulationControl(Protocol):
    """Present only in local composition; never mapped onto a real broker."""

    def advance(self, day: date, now: datetime) -> None: ...
    def fill(self, account_ref: str, order_id: str, quantity: int, price: Decimal, fee: Decimal) -> None: ...
    def persist_remote(self) -> None: ...
    def apply_corporate_action(
        self, action_id: str, instrument_id: str, new_spec: InstrumentSpec, ratio: Decimal, receivable: Decimal, payday: date | None, *, account_ref: str
    ) -> None: ...
    def corporate_action_applied(self, action_id: str, account_ref: str) -> bool: ...
    def rebuild_history(self, engine: 'TradingEngine') -> None: ...


@dataclass(frozen=True)
class Catalog:
    instruments: tuple[InstrumentSpec, ...]

    def resolve(self, instrument_id: str) -> InstrumentSpec:
        from quantlab.trading.domain.validation import DomainError

        result = next((s for s in self.instruments if s.instrument_id == instrument_id), None)
        if result is None:
            raise DomainError('instrument_unresolved', 'explicit catalog identity required')
        return result


@dataclass(frozen=True)
class QuoteBatch:
    items: tuple[Quote, ...]

    def __post_init__(self) -> None:
        from quantlab.trading.domain.validation import DomainError

        if type(self.items) is not tuple or not 1 <= len(self.items) <= 1000 or any(not isinstance(item, Quote) for item in self.items):
            raise DomainError('validation_failed', 'bounded typed quote batch required')


@dataclass(frozen=True)
class ExecutionConfiguration:
    environment: Environment = Environment.LOCAL
    stock_account_ref: str = 'local-stock'
    futures_account_ref: str = 'local-futures'
    read_only: bool = False
    broker_simulation_enabled: bool = False
    live_execution_enabled: bool = False

    def __post_init__(self) -> None:
        from quantlab.trading.domain.validation import DomainError, identity

        if not isinstance(self.environment, Environment) or any(
            type(v) is not bool for v in (self.read_only, self.broker_simulation_enabled, self.live_execution_enabled)
        ):
            raise DomainError('validation_failed', 'execution configuration types')
        if self.stock_account_ref:
            identity(self.stock_account_ref)
        if self.futures_account_ref:
            identity(self.futures_account_ref)
        if not self.stock_account_ref and not self.futures_account_ref or self.stock_account_ref == self.futures_account_ref:
            raise DomainError('validation_failed', 'securities and futures accounts must remain explicit')
