"""Explicit UI context changes without combining independent engine books."""

from dataclasses import replace
from threading import RLock

from .contracts import ContextNavigationRequest, ContextPort, TradingFacade, UiAction, UiCommand, UiReceipt, UiState
from .errors import ERROR_TABLE
from .manual_contracts import ManualBookForm, ManualOrderForm, ManualMutationForm
from .manual_routing import forward_refusal
from quantlab.trading.domain.validation import DomainError, identity
from quantlab.trading.domain.models import Environment


def _failure(code: str) -> UiReceipt:
    error = ERROR_TABLE.get(code, ERROR_TABLE['operation_failed'])
    return UiReceipt(False, code, error.explanation + ' ' + error.action)


class CompositeFacade:
    """The selected facade changes only after a verified target is ready.

    No SDK, files, database, money calculations or implicit connection live in
    this use case. ContextPort owns runtime composition and durable selection.
    """

    def __init__(self, contexts: ContextPort, context_id: str, current: TradingFacade):
        identity(context_id)
        self.contexts, self._context_id, self._current = contexts, context_id, current
        self._epoch, self._mutations, self._switching = 0, 0, False
        self._lock = RLock()
        self._verify(current.snapshot(), context_id)
        restore = getattr(contexts, 'current_sinopac', None)
        self._connection = restore() if callable(restore) else None
        self._connection_offset, self._connection_high = 0, -1

    def _verify(self, state: UiState, context_id: str, account_ref: str = '') -> None:
        option = next((item for item in self.contexts.list_contexts() if item.context_id == context_id), None)
        if option is None or state.environment is not option.environment or state.account_ref not in option.account_refs:
            raise DomainError('capability_missing', 'runtime context does not match selected configuration')
        if account_ref and state.account_ref != account_ref:
            raise DomainError('state_conflict', 'target runtime did not select the explicit account')

    def snapshot(self) -> UiState:
        with self._lock:
            facade, context_id, epoch = self._current, self._context_id, self._epoch
            connection, offset = self._connection, self._connection_offset
        state = facade.snapshot()
        self._verify(state, context_id)
        with self._lock:
            if (facade, context_id, epoch) != (self._current, self._context_id, self._epoch):
                raise DomainError('state_conflict', 'context changed during read')
        if connection is not None:
            connected = connection.snapshot()
            view = connected.sinopac_connection
            native_scope = state.manual.scope
            if native_scope is not None and (state.environment, state.account_ref, native_scope.connection_generation, native_scope.connection_revision) == (
                view.environment,
                native_scope.account_ref,
                view.generation,
                view.revision,
            ):
                # The control host's pending-account view cannot borrow another
                # book's diagnostic readiness. Preserve this selected book only.
                view = replace(view, readiness=state.sinopac_connection.readiness)
            projected = view.revision + offset
            with self._lock:
                if connection is not self._connection or offset != self._connection_offset or projected < self._connection_high:
                    raise DomainError('state_conflict', 'connection changed during read')
                self._connection_high = projected
            state = replace(
                state,
                sinopac_connection=replace(view, revision=projected),
                market_watch=connected.market_watch,
                market_health=connected.market_health,
                market_revision=connected.market_revision,
                market_connection=connected.market_connection,
                market_data_settings=connected.market_data_settings,
                market_data_error=connected.market_data_error,
                watchlist=connected.watchlist,
            )
        manual = state.manual
        if manual.scope is not None:
            # Owner CAS is native to the broker host. Presentation connection
            # offsets must never rebase an admitted preview or pending result.
            manual = replace(manual, scope=replace(manual.scope, context_id=context_id, context_epoch=epoch))
        return replace(state, manual=manual, context_id=context_id, context_epoch=epoch, contexts=self.contexts.list_contexts())

    def market_series(self, query):
        with self._lock:
            facade, epoch = self._connection or self._current, self._epoch
        page = facade.market_series(query)
        with self._lock:
            if facade is not (self._connection or self._current) or epoch != self._epoch:
                raise DomainError('state_conflict', 'context changed during series read')
        return page

    def candidates(self):
        # Candidate references belong to the selected engine context, never to
        # the market-only connection host.
        with self._lock:
            facade, context_id, epoch = self._current, self._context_id, self._epoch
        catalogue = facade.candidates()
        with self._lock:
            if (facade, context_id, epoch) != (self._current, self._context_id, self._epoch):
                raise DomainError('state_conflict', 'context changed during candidate read')
        return catalogue

    def symbol_directory(self):
        with self._lock:
            return (self._connection or self._current).symbol_directory()

    def select_market_instrument(self, instrument_id: str, period: str = '1m') -> bool:
        with self._lock:
            return (self._connection or self._current).select_market_instrument(instrument_id, period)

    def market_status(self):
        with self._lock:
            return (self._connection or self._current).market_status()

    def market_preferences(self) -> str:
        with self._lock:
            return (self._connection or self._current).market_preferences()

    def alerts(self, command):
        with self._lock:
            return (self._connection or self._current).alerts(command)

    def execute(self, command: UiCommand) -> UiReceipt:
        if not isinstance(command, UiCommand):
            return _failure('validation_failed')
        if type(command.manual_no_admission) is not bool:
            return _failure('validation_failed')
        if command.manual_no_admission:
            with self._lock:
                facade = self._current
            return self._manual_refusal(command, facade)
        if command.action is UiAction.SWITCH_CONTEXT:
            return self._switch(command)
        try:
            with self._lock:
                facade = self._current
                refused = (
                    (command.context_id and command.context_id != self._context_id)
                    or (command.context_epoch is not None and command.context_epoch != self._epoch)
                    or (self._switching and command.action is not UiAction.STOP_NEW)
                )
                if not refused and self._switching and command.action is UiAction.STOP_NEW:
                    # An explicit stop cancels the in-flight navigation intent;
                    # observation-only book updates do not change this epoch.
                    self._epoch += 1
                if not refused:
                    self._mutations += 1
            if refused:
                return self._manual_refusal(command, facade)
            try:
                if command.action in (
                    UiAction.SAVE_AND_CONNECT_SINOPAC,
                    UiAction.SELECT_SINOPAC_ACCOUNTS,
                    UiAction.ACTIVATE_SINOPAC_CA,
                    UiAction.DISCONNECT_SINOPAC,
                ):
                    return self._sinopac(command, facade)
                if self._connection is not None and command.action is UiAction.SAVE_SETTINGS and command.watchlist is not None and command.settings is None:
                    if facade.snapshot().version != command.expected_version:
                        raise DomainError('state_conflict', 'refresh before changing market watchlist')
                    return self._connection.execute(replace(command, expected_version=self._connection.snapshot().version))
                if command.action is UiAction.ADD_CONTEXT:
                    if facade.snapshot().version != command.expected_version or command.environment is None:
                        raise DomainError('state_conflict', 'refresh before registering a profile')
                    added = self.contexts.register_profile(command.profile_ref, command.environment)
                    return UiReceipt(True, 'completed', '', added.context_id)
                if command.action in (
                    UiAction.ENABLE_MANUAL_BOOK,
                    UiAction.PREVIEW_MANUAL,
                    UiAction.SUBMIT_MANUAL,
                    UiAction.TEST_SIM_ORDER,
                    UiAction.CANCEL_MANUAL,
                    UiAction.AMEND_MANUAL,
                    UiAction.ADOPT_MANUAL_ORDER,
                    UiAction.DECLARE_MANUAL_NOT_SENT,
                ) or (command.action in (UiAction.RESUME, UiAction.FLATTEN) and facade.snapshot().manual.scope is not None):
                    accepted = self.snapshot().manual.scope
                    form = command.manual_book or command.manual_order or command.manual_mutation
                    if form is not None and not isinstance(form, (ManualBookForm, ManualOrderForm, ManualMutationForm)):
                        raise DomainError('validation_failed', 'typed manual intent required')
                    if (
                        accepted is None
                        or (
                            command.context_id,
                            command.context_epoch,
                            command.environment,
                            command.account_ref,
                            command.connection_generation,
                            command.connection_revision,
                        )
                        != (
                            accepted.context_id,
                            accepted.context_epoch,
                            accepted.environment,
                            accepted.account_ref,
                            accepted.connection_generation,
                            accepted.connection_revision,
                        )
                        or form is not None
                        and form.scope != accepted
                    ):
                        return self._manual_refusal(command, facade)
                return facade.execute(command)
            finally:
                with self._lock:
                    self._mutations -= 1
        except (OSError, EOFError):
            return _failure('operation_failed')
        except DomainError as exc:
            return _failure(exc.code)

    def _manual_refusal(self, command, facade):
        with self._lock:
            connection = self._connection
        return forward_refusal(command, facade, connection)

    def _sinopac(self, command, book):
        if book.snapshot().version != command.expected_version:
            raise DomainError('state_conflict', 'refresh before connection command')
        connection = self._connection
        current = self.snapshot().sinopac_connection
        if command.connection_revision != current.revision or command.connection_generation != current.generation:
            raise DomainError('state_conflict', 'connection changed before intent')
        expected_revision = current.revision - self._connection_offset
        expected_generation = current.generation
        if command.action is UiAction.SAVE_AND_CONNECT_SINOPAC:
            if command.sinopac_settings is None:
                raise DomainError('validation_failed', 'connection settings required')
            target = command.sinopac_settings.environment
            if connection is None:
                previous_book = book.snapshot()
                if (
                    previous_book.market_data_error == 'logout_unconfirmed'
                    or previous_book.market_connection in ('CONNECTED', 'CONNECTING')
                    and (previous_book.market_data_settings.enabled or previous_book.environment is not Environment.LOCAL)
                ):
                    receipt = book.execute(UiCommand(UiAction.DISCONNECT_SINOPAC, previous_book.version))
                    if not receipt.accepted:
                        raise DomainError('outcome_unknown', 'legacy session logout unconfirmed')
            if connection is not None and connection.snapshot().environment is not target:
                previous = connection.snapshot()
                receipt = connection.execute(
                    UiCommand(UiAction.DISCONNECT_SINOPAC, previous.version, connection_revision=expected_revision, connection_generation=expected_generation)
                )
                after = connection.snapshot().sinopac_connection
                if not receipt.accepted or after.phase != 'DISCONNECTED' or after.error_code:
                    raise DomainError('outcome_unknown', 'previous session logout unconfirmed')
            if connection is None or connection.snapshot().environment is not target:
                opener = getattr(self.contexts, 'open_sinopac', None)
                if not callable(opener):
                    raise DomainError('capability_missing', 'unified connection host unavailable')
                connection = opener(target)
                native = connection.snapshot().sinopac_connection
                expected_revision, expected_generation = native.revision, native.generation
                with self._lock:
                    self._connection = connection
                    self._connection_offset = max(0, self._connection_high + 1 - native.revision)
        if connection is None:
            raise DomainError('capability_missing', 'connection owner unavailable')
        state = connection.snapshot()
        return connection.execute(
            replace(command, expected_version=state.version, connection_revision=expected_revision, connection_generation=expected_generation)
        )

    def _switch(self, command: UiCommand) -> UiReceipt:
        # Preserve the historical version-bound command contract verbatim.
        return self._select_context(command.context_id, command.environment, command.account_ref, command.context_epoch, command.expected_version)

    def navigate_context(self, request: ContextNavigationRequest) -> UiReceipt:
        # View selection never changes a book. Its authority is the selected
        # context generation, not a continuously changing engine journal version.
        if not isinstance(request, ContextNavigationRequest) or type(request.expected_epoch) is not int or request.expected_epoch < 0:
            return _failure('validation_failed')
        try:
            for value in (request.expected_context_id, request.context_id, request.account_ref):
                identity(value)
            if not isinstance(request.environment, Environment):
                raise DomainError('validation_failed', 'explicit navigation environment required')
        except DomainError as exc:
            return _failure(exc.code)
        return self._select_context(
            request.context_id, request.environment, request.account_ref, request.expected_epoch, None, request.expected_context_id, read_only=True
        )

    def _select_context(self, context_id, environment, account_ref, expected_epoch, expected_version, expected_context_id='', *, read_only=False) -> UiReceipt:
        try:
            with self._lock:
                if self._switching or self._mutations:
                    raise DomainError('state_conflict', 'finish current operation before changing context')
                if expected_epoch is not None and expected_epoch != self._epoch:
                    raise DomainError('state_conflict', 'context selection changed before navigation')
                if expected_context_id and expected_context_id != self._context_id:
                    raise DomainError('state_conflict', 'navigation belongs to another source context')
                previous, epoch = self._current, self._epoch
                if not read_only and previous.snapshot().version != expected_version:
                    raise DomainError('state_conflict', 'refresh before changing context')
                option = next((item for item in self.contexts.list_contexts() if item.context_id == context_id), None)
                if option is None or option.environment is not environment or account_ref not in option.account_refs:
                    raise DomainError('capability_missing', 'explicit configured context/account required')
                self._switching = True
            try:
                candidate = self.contexts.open_context(option.context_id, account_ref)
                self._verify(candidate.snapshot(), option.context_id, account_ref)
                with self._lock:
                    if self._epoch != epoch or self._current is not previous:
                        raise DomainError('state_conflict', 'current navigation changed while target opened')
                    self.contexts.persist_selection(option.context_id, account_ref)
                    self._current, self._context_id = candidate, option.context_id
                    self._epoch += 1
                return UiReceipt(True, 'completed', '', option.context_id)
            finally:
                with self._lock:
                    self._switching = False
        except (OSError, EOFError):
            return _failure('operation_failed')
        except DomainError as exc:
            return _failure(exc.code)
