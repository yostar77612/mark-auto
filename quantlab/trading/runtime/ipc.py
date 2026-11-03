"""Authenticated local IPC; bytes only, no pickle, no network listener."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from multiprocessing.connection import Client
from pathlib import Path
import os
from uuid import uuid4

from quantlab.trading.application.codec import MAX_BYTES, dumps, loads
from quantlab.trading.application.contracts import MarketSeriesPage, MarketSeriesQuery, UiCommand, UiReceipt, UiState
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from .control_secret import unprotect
from .protocol import Operation, Request, Response
from quantlab.trading.application.alert_contracts import AlertCommand, AlertSnapshot
from .unix_socket import validate_unix_address


@dataclass(frozen=True)
class Session:
    address: str
    family: str
    key: bytes
    process_id: int


def read_session(root: Path) -> Session:
    path = root / 'engine-session-v2.json'
    if path.is_symlink() or path.stat().st_size > 8192:
        raise DomainError('validation_failed', 'local session metadata')
    body = json.loads(path.read_text(encoding='utf-8'))
    if set(body) != {'schema_version', 'address', 'family', 'protected_key', 'process_id'} or body['schema_version'] != 2:
        raise DomainError('validation_failed', 'session schema')
    expected_family = 'AF_PIPE' if os.name == 'nt' else 'AF_UNIX'
    if body['family'] != expected_family or type(body['address']) is not str or type(body['process_id']) is not int:
        raise DomainError('validation_failed', 'local session fields')
    if os.name == 'nt' and not body['address'].startswith('\\\\.\\pipe\\markauto-v2-'):
        raise DomainError('validation_failed', 'not a local named pipe')
    if os.name != 'nt':
        validate_unix_address(root, body['address'])
    key = unprotect(bytes.fromhex(body['protected_key']))
    if len(key) != 32:
        raise DomainError('validation_failed', 'invalid control key')
    return Session(body['address'], body['family'], key, body['process_id'])


class IpcFacade:
    def __init__(self, root: Path, *, environment: Environment = Environment.LOCAL, account_ref: str = 'local-stock'):
        initialize()
        from quantlab.trading.domain.validation import identity

        if not isinstance(environment, Environment):
            raise DomainError('validation_failed', 'explicit environment required')
        identity(account_ref)
        self.root = root
        self.environment, self.account_ref = environment, account_ref
        self.closed_state: UiState | None = None

    def request(
        self, operation: Operation, *, command: UiCommand | None = None, quotes=None, series: MarketSeriesQuery | None = None, alert: AlertCommand | None = None
    ) -> Response:
        session = read_session(self.root)
        envelope = Request(
            uuid4().hex,
            self.environment,
            self.account_ref,
            datetime.now(timezone.utc) + timedelta(seconds=10),
            operation,
            command,
            quotes,
            series=series,
            alert=alert,
        )
        with Client(session.address, family=session.family, authkey=session.key) as connection:
            connection.send_bytes(dumps(envelope).encode('utf-8'))
            if not connection.poll(10):
                raise DomainError('outcome_unknown', 'local response timed out; refresh before retry')
            response = loads(connection.recv_bytes(MAX_BYTES).decode('utf-8'))
        if not isinstance(response, Response) or response.request_id != envelope.request_id:
            raise DomainError('validation_failed', 'response identity mismatch')
        if response.code:
            raise DomainError(response.code, 'engine rejected request')
        return response

    def candidates(self):
        return self.request(Operation.LIST_CANDIDATES).candidates

    def market_series(self, query: MarketSeriesQuery) -> MarketSeriesPage:
        response = self.request(Operation.MARKET_SERIES, series=query)
        if not isinstance(response.series, MarketSeriesPage):
            raise DomainError('validation_failed', 'missing market series page')
        return response.series

    def symbol_directory(self):
        return self.request(Operation.SYMBOL_DIRECTORY).instruments

    def select_market_instrument(self, instrument_id: str, period: str = '1m') -> bool:
        response = self.request(Operation.MARKET_SELECT, series=MarketSeriesQuery(instrument_id, period))
        if not isinstance(response.receipt, UiReceipt) or response.receipt.reference not in ('LIVE', 'HISTORY'):
            raise DomainError('validation_failed', 'missing market selection receipt')
        return response.receipt.reference == 'LIVE'

    def market_status(self):
        return self.request(Operation.MARKET_STATUS).market_status

    def market_preferences(self) -> str:
        return self.request(Operation.MARKET_PREFERENCES).market_selected

    def alerts(self, command: AlertCommand) -> AlertSnapshot:
        response = self.request(Operation.ALERTS, alert=command)
        if not isinstance(response.alerts, AlertSnapshot):
            raise DomainError('validation_failed', 'missing alert snapshot')
        return response.alerts

    def snapshot(self) -> UiState:
        if self.closed_state is not None:
            return self.closed_state
        response = self.request(Operation.SNAPSHOT)
        if not isinstance(response.state, UiState):
            raise DomainError('validation_failed', 'missing read model')
        self.environment, self.account_ref = response.state.environment, response.state.account_ref
        return response.state

    def execute(self, command: UiCommand) -> UiReceipt:
        from quantlab.trading.application.auto_strategy_service import AUTO_STRATEGY_ACTIONS
        from quantlab.trading.application.contracts import UiAction

        operation = (
            Operation.BUILD_AUTO_STRATEGY
            if command.action is UiAction.BUILD_AUTO_STRATEGY
            else Operation.AUTO_STRATEGY_COMMAND
            if command.action in AUTO_STRATEGY_ACTIONS
            else Operation.COMMAND
        )
        response = self.request(operation, command=command)
        if not isinstance(response.receipt, UiReceipt):
            raise DomainError('validation_failed', 'missing command receipt')
        if response.state is not None and response.state.engine_state == 'CLOSED':
            self.closed_state = response.state
        return response.receipt
