"""UI observation of pending manual intents, never a broker execution journal."""

from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.contracts import ManualPurpose
from quantlab.trading.domain.models import Environment


MANUAL_ACTIONS = frozenset(
    (UiAction.ENABLE_MANUAL_BOOK, UiAction.PREVIEW_MANUAL, UiAction.SUBMIT_MANUAL, UiAction.CANCEL_MANUAL, UiAction.AMEND_MANUAL, UiAction.TEST_SIM_ORDER)
)


def scope_matches(state, scope):
    return (
        scope is not None
        and state.environment is Environment.BROKER_SIMULATION
        and (
            state.context_id,
            state.context_epoch,
            state.environment,
            state.account_ref,
        )
        == (scope.context_id, scope.context_epoch, scope.environment, scope.account_ref)
    )


class ManualIntents:
    def __init__(self):
        self.pending = {}
        self.preview_id = ''
        self.preview_request = ''
        self.review_version = None

    def observe(self, state):
        result = state.manual.last_result
        if result is not None and result.outcome_known and self.pending.get(result.request_id) == result.scope:
            del self.pending[result.request_id]

    def unresolved(self, state):
        self.observe(state)
        # A new login generation does not prove the old broker request failed.
        same_book = lambda item: (item.context_id, item.account_ref, item.environment) == (state.context_id, state.account_ref, state.environment)
        local_unknown = any(same_book(item) for item in self.pending.values())
        return local_unknown or (state.manual.pending is not None and not state.manual.pending.outcome_known)

    def received(self, command, state, receipt):
        if command is None or receipt is None or command.action not in MANUAL_ACTIONS:
            return
        order = command.manual_order
        # A transport refusal can occur after admission. Only the matching
        # server projection can prove this particular financial outcome known.
        self.observe(state)
        if command.action is UiAction.PREVIEW_MANUAL or (command.action is UiAction.TEST_SIM_ORDER and order is None):
            preview = state.manual.preview
            matching = order is None or preview is not None and preview.request_id == order.request_id
            if receipt.accepted and preview is not None and matching and receipt.reference == preview.preview_id:
                if order is None and preview.purpose is not ManualPurpose.DIAGNOSTIC_TMF:
                    return
                self.preview_id, self.preview_request, self.review_version = preview.preview_id, preview.request_id, state.version
