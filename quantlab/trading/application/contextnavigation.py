"""Explicit UI context changes without combining independent engine books."""

from dataclasses import replace
from threading import RLock

from .contracts import ContextPort, TradingFacade, UiAction, UiCommand, UiReceipt, UiState
from .errors import ERROR_TABLE
from quantlab.trading.domain.validation import DomainError, identity


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
        try:
            with self._lock:
                if self._switching or self._mutations:
                    raise DomainError('state_conflict', 'finish current operation before changing context')
                if command.context_epoch is not None and command.context_epoch != self._epoch:
                    raise DomainError('state_conflict', 'context selection changed before navigation')
                previous, epoch = self._current, self._epoch
                before = previous.snapshot()
                if before.version != command.expected_version:
                    raise DomainError('state_conflict', 'refresh before changing context')
                option = next((item for item in self.contexts.list_contexts() if item.context_id == command.context_id), None)
                if option is None or option.environment is not command.environment or command.account_ref not in option.account_refs:
                    raise DomainError('capability_missing', 'explicit configured context/account required')
                self._switching = True
            try:
                candidate = self.contexts.open_context(option.context_id, command.account_ref)
                self._verify(candidate.snapshot(), option.context_id, command.account_ref)
                with self._lock:
                    if self._epoch != epoch or self._current is not previous:
                        raise DomainError('state_conflict', 'current navigation changed while target opened')
                    self.contexts.persist_selection(option.context_id, command.account_ref)
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
