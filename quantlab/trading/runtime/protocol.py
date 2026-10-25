"""Bounded command envelopes shared by the engine and its UI client."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from quantlab.trading.application.codec import register
from quantlab.trading.application.contracts import UiCommand, UiReceipt, UiState
from quantlab.trading.application.context import QuoteBatch
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware, identity


class Operation(str, Enum):
    SNAPSHOT = 'SNAPSHOT'
    COMMAND = 'COMMAND'
    QUOTES = 'QUOTES'
    METRICS = 'METRICS'


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


register(Operation, Request, Response, Metrics, QuoteBatch)
