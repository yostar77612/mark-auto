"""Durable disconnected broker settings, with explicitly unknown financial facts.

This session is not a trading engine and cannot accept execution commands. It
keeps configuration usable before a calendar, account or connector is available.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from .broker_settings import BrokerReadiness, BrokerSettings, ReferenceInspector, check_readiness
from .codec import dumps, loads, register
from .concurrency import WriterLock
from .contracts import AccountView, SettingsForm, UiAction, UiCommand, UiReceipt, UiState
from .errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError, decimal_value, identity, integer
from quantlab.trading.ports.storage import Journal
from quantlab.trading.ports.interfaces import Clock


@dataclass(frozen=True)
class ReadinessState:
    version: int
    environment: Environment
    account_refs: tuple[str, ...]
    selected_account_ref: str
    settings: BrokerSettings
    readiness: BrokerReadiness | None = None
    engine_closed: bool = False
    stopped: bool = True
    connection_status: str = 'DISCONNECTED'
    connection_code: str = ''
    connection_attempt: str = ''

    def __post_init__(self) -> None:
        integer(self.version, 'metadata version')
        if (
            self.environment not in (Environment.BROKER_SIMULATION, Environment.LIVE)
            or type(self.account_refs) is not tuple
            or not self.account_refs
            or self.selected_account_ref not in self.account_refs
            or len(set(self.account_refs)) != len(self.account_refs)
        ):
            raise DomainError('validation_failed', 'metadata context identity')
        for account in self.account_refs:
            identity(account)
        if (
            not isinstance(self.settings, BrokerSettings)
            or self.settings.environment is not self.environment
            or not self.settings.read_only
            or self.settings.execution_enabled
            or self.readiness is not None
            and not isinstance(self.readiness, BrokerReadiness)
            or type(self.engine_closed) is not bool
            or type(self.stopped) is not bool
            or not self.stopped
        ):
            raise DomainError('validation_failed', 'metadata session types and disabled execution')
        if self.connection_status not in ('DISCONNECTED', 'CONNECTING', 'CONNECTED') or self.connection_code not in (
            '',
            'capability_missing',
            'outcome_unknown',
            'state_conflict',
            'journal_failed',
        ):
            raise DomainError('validation_failed', 'connection metadata status')
        if self.connection_attempt:
            identity(self.connection_attempt)


register(ReadinessState)


class ReadinessSession:
    def __init__(
        self,
        journal: Journal,
        environment: Environment,
        account_refs: tuple[str, ...],
        selected_account_ref: str,
        clock: Clock,
        inspector: ReferenceInspector,
        *,
        settings: BrokerSettings | None = None,
        stock_allocation: Decimal = Decimal('0'),
        futures_allocation: Decimal = Decimal('0'),
    ) -> None:
        from .registry import initialize

        # A fresh no-profile process has not loaded a resource bundle. Register
        # the trusted nested settings/domain DTOs before its first journal write.
        initialize()
        if (
            environment not in (Environment.BROKER_SIMULATION, Environment.LIVE)
            or type(account_refs) is not tuple
            or not account_refs
            or len(set(account_refs)) != len(account_refs)
            or selected_account_ref not in account_refs
        ):
            raise DomainError('capability_missing', 'explicit disconnected account context required')
        for account in account_refs:
            identity(account)
        for value in (stock_allocation, futures_allocation):
            decimal_value(value, 'configured allocation', nonnegative=True)
        if stock_allocation + futures_allocation > Decimal('100000'):
            raise DomainError('risk_rejected', 'single shared configured budget')
        self.journal, self.clock, self.inspector = journal, clock, inspector
        self.lock, self.storage_failed = WriterLock(), False
        self.stock_allocation, self.futures_allocation = stock_allocation, futures_allocation
        self.state = ReadinessState(0, environment, account_refs, selected_account_ref, settings or BrokerSettings(environment=environment))
        for event in journal.replay():
            value = loads(event.payload)
            if (
                not isinstance(value, ReadinessState)
                or value.version != event.sequence
                or value.environment is not environment
                or value.account_refs != account_refs
            ):
                raise DomainError('startup_workspace_incompatible', 'disconnected runtime journal context changed')
            self.state = replace(value, selected_account_ref=selected_account_ref)
        unresolved = self.state.connection_status in ('CONNECTING', 'CONNECTED')
        self._commit(
            replace(
                self.state,
                engine_closed=False,
                connection_status='DISCONNECTED',
                connection_code='outcome_unknown' if unresolved else self.state.connection_code,
            ),
            'disconnected_session_opened',
        )

    def _commit(self, proposed: ReadinessState, kind: str) -> None:
        value = replace(proposed, version=self.state.version + 1)
        try:
            event = self.journal.append(kind, dumps(value), self.clock.now(), expected_sequence=self.state.version)
            if event.sequence != value.version:
                raise DomainError('journal_failed', 'disconnected journal sequence mismatch')
        except Exception as exc:
            self.storage_failed = True
            raise DomainError('journal_failed', 'disconnected metadata append failed') from exc
        self.state = value

    def snapshot(self) -> UiState:
        with self.lock:
            state = self.state
            return UiState(
                environment=state.environment,
                account_ref=state.selected_account_ref,
                engine_state='CLOSED' if state.engine_closed else state.connection_status,
                policy_label='',
                allocated_cash=self.stock_allocation + self.futures_allocation,
                daily_pnl=None,
                remaining_risk=None,
                quote_status='NO_DATA',
                version=state.version,
                trading_day='',
                synthetic_data=False,
                issues=(ERROR_TABLE['journal_failed' if self.storage_failed else state.connection_code or 'capability_missing'].explanation,),
                settings=SettingsForm(self.stock_allocation, self.futures_allocation, Decimal('0.02')),
                cost_version='UNVERIFIED',
                broker_settings=state.settings,
                broker_readiness=state.readiness,
                financial_facts_verified=False,
                accounts=tuple(
                    AccountView(ref, state.environment, market, allocation, 'EXTERNAL_REQUIRED')
                    for ref, market, allocation in (
                        (state.settings.stock_account_ref, Market.STOCK, self.stock_allocation),
                        (state.settings.futures_account_ref, Market.INDEX_FUTURE, self.futures_allocation),
                    )
                    if ref
                ),
            )

    def execute(self, command: UiCommand) -> UiReceipt:
        with self.lock:
            try:
                if not isinstance(command, UiCommand) or not isinstance(command.action, UiAction) or type(command.expected_version) is not int:
                    raise DomainError('validation_failed', 'typed metadata command required')
                if command.expected_version != self.state.version or self.state.engine_closed:
                    raise DomainError('state_conflict', 'refresh disconnected session before command')
                if self.storage_failed:
                    raise DomainError('journal_failed')
                if command.action is UiAction.SAVE_BROKER_SETTINGS:
                    settings = command.broker_settings
                    if (
                        not isinstance(settings, BrokerSettings)
                        or settings.environment is not self.state.environment
                        or not settings.read_only
                        or settings.execution_enabled
                    ):
                        raise DomainError('capability_missing', 'readonly matching broker configuration required')
                    self._commit(replace(self.state, settings=settings, readiness=None), 'broker_reference_settings_saved')
                elif command.action is UiAction.CHECK_READINESS:
                    readiness = check_readiness(self.state.settings, self.inspector, self.clock.now())
                    self._commit(replace(self.state, readiness=readiness), 'broker_metadata_readiness_checked')
                elif command.action is UiAction.STOP_NEW:
                    self._commit(
                        replace(
                            self.state,
                            stopped=True,
                            connection_status='DISCONNECTED',
                            connection_code='outcome_unknown' if self.state.connection_status == 'CONNECTING' else self.state.connection_code,
                        ),
                        'disconnected_new_entries_stopped',
                    )
                elif command.action is UiAction.SHUTDOWN_ENGINE:
                    self._commit(
                        replace(
                            self.state,
                            engine_closed=True,
                            connection_status='DISCONNECTED',
                            connection_code='outcome_unknown' if self.state.connection_status == 'CONNECTING' else self.state.connection_code,
                        ),
                        'disconnected_session_shutdown',
                    )
                else:
                    raise DomainError('capability_missing', 'disconnected session accepts metadata only')
                return UiReceipt(True, 'completed', '')
            except DomainError as exc:
                entry = ERROR_TABLE.get(exc.code, ERROR_TABLE['operation_failed'])
                return UiReceipt(False, exc.code, entry.explanation + ' ' + entry.action)

    def begin_connection(self, attempt_id: str) -> None:
        with self.lock:
            if self.storage_failed or self.state.engine_closed:
                raise DomainError('journal_failed' if self.storage_failed else 'state_conflict')
            identity(attempt_id)
            self._commit(
                replace(self.state, connection_status='CONNECTING', connection_code='', connection_attempt=attempt_id), 'readonly_connection_requested'
            )

    def finish_connection(self, attempt_id: str, code: str = '') -> None:
        with self.lock:
            if self.state.engine_closed or self.state.connection_attempt != attempt_id:
                return
            sanitized = code if code in ('', 'capability_missing', 'outcome_unknown', 'state_conflict', 'journal_failed') else 'capability_missing'
            self._commit(
                replace(self.state, connection_status='CONNECTED' if not sanitized else 'DISCONNECTED', connection_code=sanitized),
                'readonly_connection_completed' if not sanitized else 'readonly_connection_unconfirmed',
            )
