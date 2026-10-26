"""Explicit UI context changes without combining independent engine books."""

from dataclasses import replace
from threading import RLock

from .contracts import ContextNavigationRequest, ContextPort, TradingFacade, UiAction, UiCommand, UiReceipt, UiState
from .errors import ERROR_TABLE
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

    def _verify(self, state: UiState, context_id: str, account_ref: str = '') -> None:
        option = next((item for item in self.contexts.list_contexts() if item.context_id == context_id), None)
        if option is None or state.environment is not option.environment or state.account_ref not in option.account_refs:
            raise DomainError('capability_missing', 'runtime context does not match selected configuration')
        if account_ref and state.account_ref != account_ref:
            raise DomainError('state_conflict', 'target runtime did not select the explicit account')

    def snapshot(self) -> UiState:
        with self._lock:
            facade, context_id, epoch = self._current, self._context_id, self._epoch
        state = facade.snapshot()
        self._verify(state, context_id)
        with self._lock:
            if (facade, context_id, epoch) != (self._current, self._context_id, self._epoch):
                raise DomainError('state_conflict', 'context changed during read')
            return replace(state, context_id=context_id, context_epoch=epoch, contexts=self.contexts.list_contexts())

    def execute(self, command: UiCommand) -> UiReceipt:
        if not isinstance(command, UiCommand):
            return _failure('validation_failed')
        if command.action is UiAction.SWITCH_CONTEXT:
            return self._switch(command)
        try:
            with self._lock:
                if command.context_id and command.context_id != self._context_id:
                    raise DomainError('state_conflict', 'command belongs to a different context')
                if command.context_epoch is not None and command.context_epoch != self._epoch:
                    raise DomainError('state_conflict', 'command belongs to an old context selection')
                if self._switching and command.action is not UiAction.STOP_NEW:
                    raise DomainError('state_conflict', 'context switch in progress')
                if self._switching and command.action is UiAction.STOP_NEW:
                    # An explicit stop cancels the in-flight navigation intent;
                    # observation-only book updates do not change this epoch.
                    self._epoch += 1
                facade = self._current
                self._mutations += 1
            try:
                if command.action is UiAction.ADD_CONTEXT:
                    if facade.snapshot().version != command.expected_version or command.environment is None:
                        raise DomainError('state_conflict', 'refresh before registering a profile')
                    added = self.contexts.register_profile(command.profile_ref, command.environment)
                    return UiReceipt(True, 'completed', '', added.context_id)
                return facade.execute(command)
            finally:
                with self._lock:
                    self._mutations -= 1
        except (OSError, EOFError):
            return _failure('operation_failed')
        except DomainError as exc:
            return _failure(exc.code)

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
