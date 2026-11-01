"""Preserve confirmed request identity when a boundary refuses its admission."""

from dataclasses import replace

from .contracts import UiAction, UiCommand, UiReceipt
from .errors import ERROR_TABLE
from .manual_contracts import ManualMutationForm, ManualOrderForm
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


def refusal_command(command: UiCommand) -> UiCommand | None:
    """A deny-only copy confers no execution permission and never changes scope."""
    if command.environment is not Environment.BROKER_SIMULATION or command.manual_book is not None:
        return None
    if command.action in (UiAction.SUBMIT_MANUAL, UiAction.TEST_SIM_ORDER):
        form = command.manual_order
        if not isinstance(form, ManualOrderForm) or command.manual_mutation is not None:
            return None
    elif command.action in (UiAction.CANCEL_MANUAL, UiAction.AMEND_MANUAL):
        form = command.manual_mutation
        if not isinstance(form, ManualMutationForm) or command.manual_order is not None:
            return None
    else:
        return None
    if not form.confirmed or (
        form.scope.context_id,
        form.scope.context_epoch,
        form.scope.environment,
        form.scope.account_ref,
        form.scope.connection_generation,
        form.scope.connection_revision,
    ) != (command.context_id, command.context_epoch, command.environment, command.account_ref, command.connection_generation, command.connection_revision):
        return None
    return replace(command, manual_no_admission=True)


def _refused(code):
    error = ERROR_TABLE.get(code, ERROR_TABLE['operation_failed'])
    return UiReceipt(False, code, error.explanation + ' ' + error.action)


def forward_refusal(command, facade, connection):
    """Use an already-held same-owner port; never open or switch a book/host."""
    if command.environment is Environment.LIVE:
        return _refused('production_orders_disabled')
    denied = refusal_command(command)
    if denied is None:
        return _refused('state_conflict')
    try:
        state = facade.snapshot()
        scope = state.manual.scope
        current = scope is not None and (state.environment, state.account_ref, scope.context_id, scope.connection_generation, scope.connection_revision) == (
            command.environment,
            command.account_ref,
            command.context_id,
            command.connection_generation,
            command.connection_revision,
        )
        if not current:
            if connection is None:
                return _refused('state_conflict')
            native = connection.snapshot().sinopac_connection
            if (native.environment, native.generation, native.revision) != (command.environment, command.connection_generation, command.connection_revision):
                return _refused('state_conflict')
            facade = connection
        return facade.execute(denied)
    except (OSError, EOFError):
        return _refused('operation_failed')
    except DomainError as error:
        return _refused(error.code)
