from PySide6.QtCore import QObject, Signal
from desktop_app.strings.catalog import ui_text
from desktop_app.features.assistant.states import outcome_message
from quantlab.desktop_errors import error_message
from quantlab.assistant.application.connection_controller import ConnectionStateMachine

STATE_LABELS = {
    'host_initialization_required': ui_text('chatgpt_ui.labels.identity_uninitialized'),
    'disconnected': ui_text('chatgpt_ui.labels.disconnected'),
    'initialized': ui_text('chatgpt_ui.labels.unauthorized'),
    'authorizing': ui_text('chatgpt_ui.labels.awaiting_authorization'),
    'validating': ui_text('chatgpt_ui.labels.verifying_response'),
    'plan_ready': ui_text('chatgpt_ui.labels.subscription_entitled'),
    'identity_only': ui_text('chatgpt_ui.labels.identity_only'),
    'refresh_required': ui_text('chatgpt_ui.labels.refresh_required'),
    'reauthorization_required': ui_text('chatgpt_ui.labels.reauthorize_required'),
    'registration_retry_required': ui_text('chatgpt_ui.labels.registration_unverified'),
    'authorization_failed': ui_text('chatgpt_ui.labels.authorization_incomplete'),
    'timeout': ui_text('chatgpt_ui.labels.authorization_timeout'),
    'cancelled': ui_text('chatgpt_ui.labels.authorization_cancelled'),
    'transient_blocked': ui_text('chatgpt_ui.labels.unavailable'),
    'client_configuration_required': ui_text('chatgpt_ui.labels.client_settings_required'),
    'unknown': ui_text('chatgpt_ui.labels.unknown_state'),
}


def render_init_1(self):
    self.message = ui_text('chatgpt_ui.init.unchecked_connection')


def render_init_2(self):
    self.test_message = ui_text('connection_test.untested')


def render_request_3(self):
    return ui_text('chatgpt_ui.request.host_busy')


def render_request_4(self):
    return ui_text('chatgpt_ui.request.reconciliation_required')


def render_request_5(self):
    return ui_text('chatgpt_ui.request.unknown_requests_block_resume')


def render_request_6(self):
    self.test_message = ui_text('connection_test.untested')


def render_request_7(self):
    self.test_message += '\n' + ui_text('connection_test.usage_unknown')


def render_request_8(self, action):
    self.message = (
        ui_text('chatgpt_ui.request.stop_required')
        if self._awaiting_join
        else ui_text('chatgpt_ui.request.restoring_login')
        if action == 'restore'
        else ui_text('chatgpt_ui.request.reading_local_state')
    )


def render_request_9(self, action):
    self.message = ui_text('chatgpt_reconciliation.inspecting') if action == 'inspect_unknown' else ui_text('chatgpt_reconciliation.resolving')


def render_acknowledge_quiescence_10(self):
    self.message = ui_text('chatgpt_ui.acknowledge_quiescence.stop_unconfirmed')


def render_acknowledge_quiescence_11(self):
    self.message = ui_text('chatgpt_ui.acknowledge_quiescence.running_authorization')


def render_apply_event_12(self):
    self.message = ui_text('chatgpt_ui.apply_event.official_destination')


def render_apply_event_13(self, event):
    self.message = STATE_LABELS[event.state]


def render_apply_event_14(self, event):
    self.test_message = ui_text('connection_test.responded') if self._terminal_ok else error_message(event.error_code)


def render_apply_event_15(self, usage):
    self.test_message += '\n' + (ui_text('connection_test.usage').format(*usage) if usage is not None else ui_text('connection_test.usage_unknown'))


def render_apply_event_16(self):
    self.message = self.test_message


def render_apply_event_17(self, event):
    self.message = outcome_message(event.error_code)


def render_apply_event_18(self, event):
    self.message = outcome_message(event.state) if self.outcome else STATE_LABELS[event.state]


def render_apply_event_19(self, event):
    self.message = (
        ui_text('chatgpt_ui.apply_event.revocation_confirmed')
        if event.revocation_confirmed is True
        else ui_text('chatgpt_ui.apply_event.revocation_unconfirmed')
    )


def render_apply_event_20(self):
    self.message += ui_text('chatgpt_ui.apply_event.wait_for_host')


def render_apply_reconciliation_event_21(self, event):
    self.message = error_message(event.error_code)


def render_apply_reconciliation_event_22(self, calls, event, old_enough, sequence):
    self._messages = {
        'k1_resolvable': ui_text('chatgpt_reconciliation.summary').format(sequence, calls) if old_enough else ui_text('chatgpt_reconciliation.too_recent'),
        'k1_other_registration': ui_text('chatgpt_reconciliation.other_registration'),
        'k2_resolvable': ui_text('chatgpt_reconciliation_k2.summary').format(sequence, calls, event.inspection_outcome)
        if old_enough
        else ui_text('chatgpt_reconciliation_k2.too_recent'),
        'k2_other_registration': ui_text('chatgpt_reconciliation_k2.other_registration'),
        'k2_unresolvable': ui_text('chatgpt_reconciliation_k2.unmappable'),
        'none': ui_text('chatgpt_reconciliation.none'),
    }


def render_apply_reconciliation_event_23(self, kind):
    self.message = self._messages[kind]


def render_apply_reconciliation_event_24(self):
    self.message = ui_text('chatgpt_reconciliation.resolved_unverified')


def render_apply_reconciliation_event_25(self, pending, state):
    self.message = (
        ui_text('chatgpt_reconciliation.pending')
        if pending
        else ui_text('chatgpt_reconciliation.resolved_ready')
        if state == 'ready'
        else ui_text('chatgpt_reconciliation.resolved')
    )


def render_apply_reconciliation_event_26(self):
    self.message += ui_text('chatgpt_ui.apply_event.wait_for_host')


def render_show_outcome_27(self, code):
    self.message = outcome_message(code)


def render_open_authorization_28(self):
    return ui_text('chatgpt_ui.open_authorization.authorization_unavailable')


def render_cancel_29(self, RECONCILIATION_ACTIONS):
    self.message = (
        ui_text('chatgpt_reconciliation.changed') if self._request.action in RECONCILIATION_ACTIONS else ui_text('chatgpt_ui.cancel.stopping_remote_unknown')
    )


def render_worker_joined_30(self, RECONCILIATION_ACTIONS, finished):
    self.message = (
        ui_text('chatgpt_reconciliation.changed') if finished.action in RECONCILIATION_ACTIONS else ui_text('chatgpt_ui.worker_joined.remote_outcome_unknown')
    )


def render_worker_joined_31(self):
    self.message = self.message.removesuffix(ui_text('chatgpt_ui.worker_joined.wait_for_host'))


RENDERERS = {
    'init_1': render_init_1,
    'init_2': render_init_2,
    'request_3': render_request_3,
    'request_4': render_request_4,
    'request_5': render_request_5,
    'request_6': render_request_6,
    'request_7': render_request_7,
    'request_8': render_request_8,
    'request_9': render_request_9,
    'acknowledge_quiescence_10': render_acknowledge_quiescence_10,
    'acknowledge_quiescence_11': render_acknowledge_quiescence_11,
    'apply_event_12': render_apply_event_12,
    'apply_event_13': render_apply_event_13,
    'apply_event_14': render_apply_event_14,
    'apply_event_15': render_apply_event_15,
    'apply_event_16': render_apply_event_16,
    'apply_event_17': render_apply_event_17,
    'apply_event_18': render_apply_event_18,
    'apply_event_19': render_apply_event_19,
    'apply_event_20': render_apply_event_20,
    'apply_reconciliation_event_21': render_apply_reconciliation_event_21,
    'apply_reconciliation_event_22': render_apply_reconciliation_event_22,
    'apply_reconciliation_event_23': render_apply_reconciliation_event_23,
    'apply_reconciliation_event_24': render_apply_reconciliation_event_24,
    'apply_reconciliation_event_25': render_apply_reconciliation_event_25,
    'apply_reconciliation_event_26': render_apply_reconciliation_event_26,
    'show_outcome_27': render_show_outcome_27,
    'open_authorization_28': render_open_authorization_28,
    'cancel_29': render_cancel_29,
    'worker_joined_30': render_worker_joined_30,
    'worker_joined_31': render_worker_joined_31,
}


class ConnectionController(QObject, ConnectionStateMachine):
    """Qt effects and localized messages around the application state machine."""

    quiesce_requested = Signal(object)
    request_ready = Signal(object)
    cancel_requested = Signal(int)
    browser_requested = Signal(str)
    changed = Signal()
    request_finished = Signal(object, bool)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        ConnectionStateMachine.__init__(self, emit=self._dispatch, present=self._render)

    def _dispatch(self, name, *args):
        getattr(self, name).emit(*args)

    def _render(self, name, **values):
        return RENDERERS[name](self, **values)
