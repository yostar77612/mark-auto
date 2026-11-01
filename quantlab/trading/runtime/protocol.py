"""Bounded command envelopes shared by the engine and its UI client."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from quantlab.trading.application.codec import register
from quantlab.trading.application.contracts import MarketSeriesPage, MarketSeriesQuery, UiCommand, UiReceipt, UiState
from quantlab.trading.application.context import QuoteBatch
from quantlab.trading.application.market_terminal_service import MarketTerminalStatus
from quantlab.trading.application.history_sync import HistorySyncState
from quantlab.trading.application.alert_contracts import AlertCommand, AlertSnapshot
from quantlab.trading.ports.history import HistoryUsage
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware, identity


class Operation(str, Enum):
    SNAPSHOT = 'SNAPSHOT'
    COMMAND = 'COMMAND'
    QUOTES = 'QUOTES'
    METRICS = 'METRICS'
    MARKET_SERIES = 'MARKET_SERIES'
    SYMBOL_DIRECTORY = 'SYMBOL_DIRECTORY'
    MARKET_SELECT = 'MARKET_SELECT'
    MARKET_STATUS = 'MARKET_STATUS'
    MARKET_PREFERENCES = 'MARKET_PREFERENCES'
    ALERTS = 'ALERTS'


@dataclass(frozen=True)
class Request:
    request_id: str
    environment: Environment
    account_ref: str
    deadline: datetime
    operation: Operation
    command: UiCommand | None = None
    quotes: QuoteBatch | None = None
    schema_version: int = 2
    series: MarketSeriesQuery | None = None
    alert: AlertCommand | None = None

    def __post_init__(self) -> None:
        identity(self.request_id)
        identity(self.account_ref)
        aware(self.deadline)
        if self.schema_version != 2 or not isinstance(self.environment, Environment) or not isinstance(self.operation, Operation):
            raise DomainError('validation_failed', 'protocol version/types')
        if self.operation is Operation.COMMAND and not isinstance(self.command, UiCommand):
            raise DomainError('validation_failed', 'missing command')
        if self.operation is Operation.QUOTES and not isinstance(self.quotes, QuoteBatch):
            raise DomainError('validation_failed', 'missing quote batch')
        if self.operation in (Operation.MARKET_SERIES, Operation.MARKET_SELECT) and not isinstance(self.series, MarketSeriesQuery):
            raise DomainError('validation_failed', 'missing series query')
        if self.operation is Operation.ALERTS and not isinstance(self.alert, AlertCommand):
            raise DomainError('validation_failed', 'missing alert command')


@dataclass(frozen=True)
class Metrics:
    quote_count: int
    quote_keys: int
    recent_latency_count: int
    process_id: int
    subscription_count: int = 0
    active_strategy_count: int = 0
    candidate_count: int = 0


@dataclass(frozen=True)
class Response:
    request_id: str
    state: UiState | None = None
    receipt: UiReceipt | None = None
    metrics: Metrics | None = None
    code: str = ''
    series: MarketSeriesPage | None = None
    instruments: tuple[WatchInstrument, ...] = ()
    market_status: MarketTerminalStatus | None = None
    market_selected: str = ''
    alerts: AlertSnapshot | None = None


register(Operation, Request, Response, Metrics, QuoteBatch)
register(WatchInstrument, WatchKind, HistoryUsage, HistorySyncState, MarketTerminalStatus)
