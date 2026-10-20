"""Official subscription connection UI, wired into the desktop host.

The host owns an allowlisted bounded PROCESS, cancellation/join, the fixed
bootstrap/control paths and browser presentation. No token, vault, HTTP, browser
or process work occurs at import/construction. AuthSession must be created inside
one worker and remain there through begin/poll. All test transports are fixtures.
"""

from desktop_strings import ui_text
from desktop_chatgpt_states import outcome_state, outcome_message
from dataclasses import dataclass, field, asdict
import re
import sqlite3
import time
from urllib.parse import urlsplit, parse_qsl

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QMessageBox

USAGE_SETTINGS_URL = 'https://chatgpt.com/settings/usage'

ACTIONS = frozenset(
    ('initialize', 'begin', 'first_sign_in', 'enable_plan', 'list', 'restore', 'select', 'sign_out', 'refresh', 'models', 'clear_pause', 'test')
)
# Local-only reads that never need the host to stop background work first.
LOCAL_ACTIONS = frozenset(('list',))
# Startup-only restore may refresh over the network; host scheduling ensures idle workers.
STARTUP_ACTIONS = frozenset(('restore',))
# A saved, unexpired login: the sign-in button is hidden in these states.
CONNECTED_STATES = frozenset(('plan_ready', 'identity_only'))
STATES = frozenset(
    (
        'host_initialization_required',
        'disconnected',
        'initialized',
        'authorizing',
        'validating',
        'plan_ready',
        'identity_only',
        'refresh_required',
        'registration_retry_required',
        'reauthorization_required',
        'authorization_failed',
        'timeout',
        'cancelled',
        'transient_blocked',
        'client_configuration_required',
        'unknown',
    )
)
STATE_LABELS = {
    'host_initialization_required': ui_text('chatgpt_ui.labels.text_1'),
    'disconnected': ui_text('chatgpt_ui.labels.text_2'),
    'initialized': ui_text('chatgpt_ui.labels.text_3'),
    'authorizing': ui_text('chatgpt_ui.labels.text_4'),
    'validating': ui_text('chatgpt_ui.labels.text_5'),
    'plan_ready': ui_text('chatgpt_ui.labels.text_6'),
    'identity_only': ui_text('chatgpt_ui.labels.text_7'),
    'refresh_required': ui_text('chatgpt_ui.labels.text_8'),
    'reauthorization_required': ui_text('chatgpt_ui.labels.text_9'),
    'registration_retry_required': ui_text('chatgpt_ui.labels.text_10'),
    'authorization_failed': ui_text('chatgpt_ui.labels.text_11'),
    'timeout': ui_text('chatgpt_ui.labels.text_12'),
    'cancelled': ui_text('chatgpt_ui.labels.text_13'),
    'transient_blocked': ui_text('chatgpt_ui.labels.text_14'),
    'client_configuration_required': ui_text('chatgpt_ui.labels.text_15'),
    'unknown': ui_text('chatgpt_ui.labels.text_16'),
}
from quantlab.desktop_errors import ERROR_LABELS, exception_code

RECOVERABLE_PAUSES = frozenset(
    ('eligibility_blocked', 'quota_paused', 'transient_blocked', 'invalid_request', 'configuration_blocked', 'credential_diagnosis', 'grant_blocked')
)
REF = r'[a-f0-9]{32}'
MODEL = r'[A-Za-z0-9._:-]{1,128}'


def _ref(value, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(REF, value):
        raise ValueError('invalid opaque registration')


def official_authorization_url(value):
    """Validate only an auth worker URL; never accepts tokens, hints or arbitrary URLs."""
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('invalid authorization destination')
    url = urlsplit(value)
    if url.scheme != 'https' or url.netloc != 'auth.openai.com' or url.path != '/api/accounts/authorize' or url.fragment or any(c.isspace() for c in value):
        raise ValueError('invalid authorization destination')
    pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
    params = dict(pairs)
    required = {
        'client_id',
        'ext_agent_host_id',
        'response_type',
        'redirect_uri',
        'scope',
        'resource',
        'state',
        'nonce',
        'code_challenge_method',
        'code_challenge',
    }
    if len(params) != len(pairs) or not required <= params.keys() or set(params) - required - {'agent_name_hint', 'prompt'}:
        raise ValueError('invalid authorization parameters')
    callback = urlsplit(params['redirect_uri'])
    try:
        port = callback.port
    except ValueError:
        raise ValueError('invalid callback') from None
    if (
        callback.scheme != 'http'
        or callback.hostname != '127.0.0.1'
        or not port
        or callback.username
        or callback.password
        or callback.path != '/auth/callback'
        or callback.query
        or callback.fragment
    ):
        raise ValueError('invalid callback')
    if params['response_type'] != 'code' or params['resource'] != 'https://api.openai.com/v1' or params['code_challenge_method'] != 'S256':
        raise ValueError('invalid authorization flow')
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,256}', params['client_id']) or not re.fullmatch(r'urn:uuid:[a-fA-F0-9-]{36}', params['ext_agent_host_id']):
        raise ValueError('invalid public client binding')
    for key in ('state', 'nonce', 'code_challenge'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', params[key]):
            raise ValueError('invalid authorization binding')
    if set(params['scope'].split()) != {'openid', 'profile', 'email', 'offline_access', 'resource.invoke', 'chatgpt.tokens.use.direct'}:
        raise ValueError('invalid authorization scope')
    if 'prompt' in params and (params['prompt'] != 'consent' or params['client_id'] == 'dynamic_agent_client'):
        raise ValueError('explicit plan consent requires an existing registration')
    return value


@dataclass(frozen=True)
class ConnectionRequest:
    request_id: int
    action: str
    registration: str | None = None
    max_runtime_seconds: int = 120
    user_confirmed: bool = False
    model: str | None = None

    def __post_init__(self):
        if type(self.request_id) is not int or self.request_id < 1 or self.action not in ACTIONS:
            raise ValueError('invalid connection request')
        _ref(self.registration, optional=True)
        if self.action == 'first_sign_in' and self.registration is not None:
            raise ValueError('first sign-in cannot select an existing account')
        if self.action in ('enable_plan', 'select', 'sign_out', 'refresh', 'models', 'clear_pause', 'test') and self.registration is None:
            raise ValueError('registration required')
        if self.action == 'test':
            if type(self.model) is not str or not re.fullmatch(MODEL, self.model):
                raise ValueError('discovered model required')
        elif self.model is not None:
            raise ValueError('model only for connection test')
        if type(self.max_runtime_seconds) is not int or not 1 <= self.max_runtime_seconds <= 600:
            raise ValueError('bounded runtime required')
        if type(self.user_confirmed) is not bool or (self.action not in LOCAL_ACTIONS | STARTUP_ACTIONS and not self.user_confirmed):
            raise ValueError('explicit user action required')

    def payload(self):
        return asdict(self)


@dataclass(frozen=True)
class ConnectionEvent:
    request_id: int
    kind: str
    state: str = 'unknown'
    registrations: tuple = ()
    active_registration: str | None = None
    authorization_url: str | None = field(default=None, repr=False)
    error_code: str = ''
    revocation_confirmed: bool | None = None
    models: tuple = ()
    model_labels: tuple = ()
    account_labels: tuple = ()

    def __post_init__(self):
        if type(self.request_id) is not int or self.request_id < 1 or self.kind not in ('progress', 'authorization', 'result', 'error'):
            raise ValueError('invalid connection event')
        if self.state not in STATES:
            raise ValueError('invalid connection state')
        _ref(self.active_registration, optional=True)
        if not isinstance(self.registrations, tuple) or len(self.registrations) > 64:
            raise ValueError('invalid registrations')
        seen = set()
        for row in self.registrations:
            if not isinstance(row, tuple) or len(row) != 2:
                raise ValueError('invalid registration summary')
            _ref(row[0])
            if row[0] in seen or row[1] not in STATES:
                raise ValueError('invalid registration summary')
            seen.add(row[0])
        if self.active_registration is not None and self.kind == 'result' and self.active_registration not in seen:
            raise ValueError('active registration missing from verified summary')
        if (
            self.kind == 'result'
            and self.state in ('plan_ready', 'identity_only', 'refresh_required', 'reauthorization_required')
            and self.active_registration is None
        ):
            raise ValueError('connected status requires an active verified registration')
        if self.authorization_url is not None:
            if self.kind != 'authorization':
                raise ValueError('authorization URL only in transient event')
            official_authorization_url(self.authorization_url)
        if not isinstance(self.error_code, str) or not re.fullmatch(r'[a-z_]{0,80}', self.error_code):
            raise ValueError('invalid sanitized error code')
        if self.revocation_confirmed is not None and type(self.revocation_confirmed) is not bool:
            raise ValueError('invalid revocation status')
        if not isinstance(self.models, tuple) or len(self.models) > 1024 or any(not isinstance(x, str) or not re.fullmatch(MODEL, x) for x in self.models):
            raise ValueError('invalid model summary')
        if len(set(self.models)) != len(self.models):
            raise ValueError('duplicate model summary')
        if not isinstance(self.model_labels, tuple) or len(self.model_labels) > 1024:
            raise ValueError('invalid model labels')
        for row in self.model_labels:
            if (
                not isinstance(row, tuple)
                or len(row) != 2
                or row[0] not in self.models
                or not isinstance(row[1], str)
                or not 1 <= len(row[1]) <= 256
                or any(ord(c) < 32 for c in row[1])
            ):
                raise ValueError('invalid model labels')
        if self.model_labels and tuple(row[0] for row in self.model_labels) != self.models:
            raise ValueError('model label/account mismatch')
        if not isinstance(self.account_labels, tuple) or len(self.account_labels) > 64:
            raise ValueError('invalid account labels')
        states = dict(self.registrations)
        label_refs = set()
        for row in self.account_labels:
            if (
                not isinstance(row, tuple)
                or len(row) != 2
                or row[0] not in states
                or row[0] in label_refs
                or states[row[0]] == 'registration_retry_required'
                or not isinstance(row[1], str)
                or not re.fullmatch(ui_text('chatgpt_ui.__post_init__.text_1'), row[1])
            ):
                raise ValueError('invalid verified account label')
            label_refs.add(row[0])


@dataclass(frozen=True)
class TestConnectionEvent(ConnectionEvent):
    test_usage: tuple | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.test_usage is not None and (
            type(self.test_usage) is not tuple
            or len(self.test_usage) != 3
            or any(type(v) is not int or not 0 <= v <= 2**53 for v in self.test_usage)
            or self.test_usage[0] + self.test_usage[1] != self.test_usage[2]
        ):
            raise ValueError('invalid bounded token usage')


@dataclass(frozen=True)
class SubscriptionOptions:
    registration: str
    model: str
    max_calls: int
    timeout_seconds: int
    network_opt_in: bool = False
    included_usage_policy_confirmed: bool = False
    mode: str = 'chatgpt_plan'
    paid_api_fallback: bool = False

    def __post_init__(self):
        _ref(self.registration)
        if not isinstance(self.model, str) or not re.fullmatch(MODEL, self.model):
            raise ValueError('invalid model')
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 100:
            raise ValueError('explicit call budget required')
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise ValueError('invalid runtime')
        if (
            self.mode != 'chatgpt_plan'
            or self.paid_api_fallback is not False
            or self.network_opt_in is not True
            or self.included_usage_policy_confirmed is not True
        ):
            raise ValueError('no paid fallback or implicit consent')


class ConnectionController(QObject):
    """Host must wire requests to bounded jobs and acknowledge ACTUAL joins.

    quiesce_requested(request): stop/join every auth/inference worker first.
    request_ready(request): now safe to submit the allowlisted job.
    cancel_requested(id): stop/join that job, then call worker_joined(id).
    browser_requested(url): host opens only this transient, validated URL, never logs it.
    apply_event accepts typed worker messages only; late/stale IDs cannot change state.
    """

    quiesce_requested = Signal(object)
    request_ready = Signal(object)
    cancel_requested = Signal(int)
    browser_requested = Signal(str)
    changed = Signal()
    request_finished = Signal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host_available = False
        self.busy = False
        self.stopping = False
        self.outcome = None
        self.state = 'unknown'
        self.message = ui_text('chatgpt_ui.__init__.text_1')
        self.registrations = ()
        self.account_labels = ()
        self.active_registration = None
        self.models = ()
        self.model_labels = ()
        self._counter = 0
        self._request = None
        self._awaiting_join = False
        self._authorization_url = None
        self._terminal_received = False
        self._terminal_ok = False
        self.usage_known = False
        self.reserved_count = None
        self.unknown_count = None
        self.account_paused = False
        self.account_pending = False
        self.account_state = 'blocked'
        self.account_status_known = False
        self.test_message = ui_text('connection_test.untested')

    def set_host_available(self, available):
        if type(available) is not bool:
            raise ValueError('host availability must be explicit')
        self.host_available = available
        self.changed.emit()

    def request(self, action, registration=None, *, confirmed=False, model=None):
        if not self.host_available or self.busy:
            raise ValueError(ui_text('chatgpt_ui.request.text_1'))
        if action == 'test' and (
            registration != self.active_registration
            or self.state != 'plan_ready'
            or model not in self.models
            or not self.account_status_known
            or self.account_paused
            or self.account_pending
            or self.unknown_count
        ):
            raise ValueError('account_paused')
        if action == 'models' and (
            registration != self.active_registration
            or self.state != 'plan_ready'
            or not self.account_status_known
            or self.account_paused
            or self.account_pending
        ):
            raise ValueError(ui_text('chatgpt_ui.request.text_2'))
        if action == 'clear_pause' and (
            registration != self.active_registration
            or not self.account_status_known
            or self.account_pending
            or self.unknown_count
            or self.account_state not in RECOVERABLE_PAUSES
        ):
            raise ValueError(ui_text('chatgpt_ui.request.text_3'))
        if (
            action in ('select', 'sign_out', 'refresh', 'models', 'clear_pause', 'enable_plan')
            and dict(self.registrations).get(registration) == 'registration_retry_required'
        ):
            raise ValueError('unverified registration permits reauthorization only')
        if action == 'enable_plan' and (registration != self.active_registration or self.state != 'identity_only'):
            raise ValueError('select an identity-only account before enabling plan use')
        self._counter += 1
        request = ConnectionRequest(
            self._counter,
            action,
            registration,
            600 if action in ('begin', 'first_sign_in', 'enable_plan') else 30 if action == 'test' else 120,
            confirmed,
            model,
        )
        if action in ('test', 'select', 'sign_out'):
            self.test_message = ui_text('connection_test.untested')
            if action == 'test':
                self.test_message += '\n' + ui_text('connection_test.usage_unknown')
        self.busy = True
        self.outcome = None
        self.stopping = False
        self._request = request
        self._authorization_url = None
        self._terminal_received = False
        self._terminal_ok = False
        self._awaiting_join = action not in LOCAL_ACTIONS | STARTUP_ACTIONS
        self.message = (
            ui_text('chatgpt_ui.request.text_4')
            if self._awaiting_join
            else (ui_text('chatgpt_ui.request.text_5') if action == 'restore' else ui_text('chatgpt_ui.request.text_6'))
        )
        self.changed.emit()
        (self.quiesce_requested if self._awaiting_join else self.request_ready).emit(request)
        return request

    def acknowledge_quiescence(self, request_id, *, joined):
        if not self._request or request_id != self._request.request_id or not self._awaiting_join:
            return False
        if joined is not True:
            self.message = ui_text('chatgpt_ui.acknowledge_quiescence.text_1')
            self.changed.emit()
            return False
        if self.stopping:
            return False
        self._awaiting_join = False
        self.message = ui_text('chatgpt_ui.acknowledge_quiescence.text_2')
        self.changed.emit()
        self.request_ready.emit(self._request)
        return True

    def apply_event(self, event):
        if not isinstance(event, ConnectionEvent):
            raise ValueError('typed sanitized event required')
        if not self._request or event.request_id != self._request.request_id or self._awaiting_join or self.stopping:
            return False
        if event.kind == 'authorization':
            self._authorization_url = event.authorization_url
            self.state = 'authorizing'
            self.message = ui_text('chatgpt_ui.apply_event.text_1')
        elif event.kind == 'progress':
            self.state = event.state
            self.message = STATE_LABELS[event.state]
        else:
            action = self._request.action
            if action == 'test':
                # Use the shared B1 projection without changing legacy connection wording.
                from quantlab.desktop_errors import error_message

                self._terminal_received = True
                self._terminal_ok = event.kind == 'result'
                self.stopping = True
                self.test_message = ui_text('connection_test.responded') if self._terminal_ok else error_message(event.error_code)
                usage = getattr(event, 'test_usage', None)
                self.test_message += '\n' + (ui_text('connection_test.usage').format(*usage) if usage is not None else ui_text('connection_test.usage_unknown'))
                self.message = self.test_message
                self.changed.emit()
                return True
            self.state = event.state
            self._terminal_received = True
            self._terminal_ok = event.kind == 'result'
            self._authorization_url = None
            if event.kind == 'error':
                self.outcome = outcome_state(event.error_code)
                self.message = outcome_message(event.error_code)
            else:
                if action == 'models' and event.active_registration != self._request.registration:
                    raise ValueError('model/account mismatch')
                if self.active_registration != event.active_registration:
                    self.usage_known = False
                    self.account_status_known = False
                self.registrations = event.registrations
                self.account_labels = event.account_labels
                self.active_registration = event.active_registration
                if action in ('begin', 'first_sign_in', 'enable_plan', 'select', 'sign_out', 'refresh', 'restore'):
                    self.models = ()
                    self.model_labels = ()
                if action == 'models':
                    self.models = event.models
                    self.model_labels = event.model_labels
                    self.usage_known = False
                    self.reserved_count = None
                    self.unknown_count = None
                self.outcome = outcome_state(event.state) if action in ('refresh', 'restore') else None
                self.message = outcome_message(event.state) if self.outcome else STATE_LABELS[event.state]
                if action == 'sign_out':
                    self.message = ui_text('chatgpt_ui.apply_event.text_2') if event.revocation_confirmed is True else ui_text('chatgpt_ui.apply_event.text_3')
            # Terminal message is not process-exit evidence. Keep controls locked until joined.
            self.stopping = True
            self.message += ui_text('chatgpt_ui.apply_event.text_4')
        self.changed.emit()
        return True

    def show_outcome(self, code):
        self.outcome = outcome_state(code)
        self.message = outcome_message(code)
        self.changed.emit()

    def open_authorization(self):
        if not self.busy or self.stopping or not self._authorization_url:
            raise ValueError(ui_text('chatgpt_ui.open_authorization.text_1'))
        value = official_authorization_url(self._authorization_url)
        self._authorization_url = None
        self.changed.emit()
        self.browser_requested.emit(value)

    def cancel(self):
        if not self.busy:
            return
        self.stopping = True
        self._authorization_url = None
        self._terminal_received = False
        self._terminal_ok = False
        self.message = ui_text('chatgpt_ui.cancel.text_1')
        self.changed.emit()
        self.cancel_requested.emit(self._request.request_id)

    def worker_joined(self, request_id, *, joined, terminal_received=True):
        if not self._request or request_id != self._request.request_id or joined is not True:
            return False
        finished = self._request
        succeeded = terminal_received is True and self._terminal_received and self._terminal_ok
        if terminal_received is not True or not self._terminal_received:
            self.state = 'unknown'
            self.message = ui_text('chatgpt_ui.worker_joined.text_1')
            self.usage_known = False
            self.unknown_count = None
            self.account_status_known = False
        self.message = self.message.removesuffix(ui_text('chatgpt_ui.worker_joined.text_2'))
        self.busy = False
        self.stopping = False
        self._awaiting_join = False
        self._authorization_url = None
        self._request = None
        self.changed.emit()
        self.request_finished.emit(finished, succeeded)
        return True

    def set_account_status(self, registration, status):
        """Verified local account barrier only; never invents campaign call counts."""
        _ref(registration)
        if registration != self.active_registration:
            raise ValueError('account status/account mismatch')
        allowed = RECOVERABLE_PAUSES | {'ready', 'reserved_unknown', 'blocked'}
        if not isinstance(status, dict) or set(status) != {'state', 'pending'} or status['state'] not in allowed or type(status['pending']) is not bool:
            raise ValueError('verified account status required')
        self.account_paused = status['state'] != 'ready'
        self.account_pending = status['pending']
        self.account_state = status['state']
        self.account_status_known = True
        self.changed.emit()

    def invalidate_campaign_usage(self):
        self.usage_known = False
        self.reserved_count = None
        self.unknown_count = None
        self.changed.emit()

    def set_usage(self, registration, receipts, *, account_status):
        _ref(registration)
        if registration != self.active_registration:
            raise ValueError('receipt/account mismatch')
        allowed = {
            'ready',
            'reserved_unknown',
            'eligibility_blocked',
            'quota_paused',
            'transient_blocked',
            'invalid_request',
            'configuration_blocked',
            'credential_diagnosis',
            'grant_blocked',
            'blocked',
        }
        if (
            not isinstance(account_status, dict)
            or set(account_status) != {'state', 'pending'}
            or account_status['state'] not in allowed
            or type(account_status['pending']) is not bool
        ):
            raise ValueError('verified account status required')
        if not isinstance(receipts, (list, tuple)) or len(receipts) > 10000:
            raise ValueError('bounded verified receipts required')
        sequences = []
        unknown = 0
        for row in receipts:
            if not isinstance(row, dict) or type(row.get('sequence')) is not int or row['sequence'] < 1 or not isinstance(row.get('status'), str):
                raise ValueError('invalid receipt summary')
            sequences.append(row['sequence'])
            unknown += row['status'] not in RECOVERABLE_PAUSES | {'completed'}
        if len(set(sequences)) != len(sequences):
            raise ValueError('duplicate receipts')
        self.usage_known = True
        self.reserved_count = len(sequences)
        self.unknown_count = unknown
        self.account_paused = account_status['state'] != 'ready'
        self.account_pending = account_status['pending']
        self.account_state = account_status['state']
        self.account_status_known = True
        self.changed.emit()


class ChatGPTConnectionPanel(QWidget):
    """Traditional Chinese standalone settings panel; no credentials in widgets."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller or ConnectionController(self)
        self._rendered_active = None
        self._included_usage_registration = None
        self._primary_flow = None
        self._restore_flow = None
        self.setObjectName('chatgpt_subscription_panel')
        layout = QVBoxLayout(self)
        title = QLabel(ui_text('chatgpt_ui.__init__.text_2'))
        layout.addWidget(title)
        self.disclosure = QLabel(ui_text('chatgpt_ui.__init__.text_3'))
        self.disclosure.setWordWrap(True)
        self.disclosure.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.disclosure)
        self.consent = QCheckBox(ui_text('chatgpt_ui.__init__.text_4'))
        layout.addWidget(self.consent)
        self.included_usage_only = QCheckBox(ui_text('chatgpt_ui.__init__.text_5'))
        self.included_usage_only.setObjectName('chatgpt_included_usage_only')
        layout.addWidget(self.included_usage_only)
        self.included_usage_only.toggled.connect(self._confirm_included_usage)
        self.manage_usage = QPushButton(ui_text('chatgpt_ui.__init__.text_6'))
        layout.addWidget(self.manage_usage)
        self.manage_usage.clicked.connect(self._open_usage_settings)
        self.active_account = QLabel(ui_text('chatgpt_ui.__init__.text_7'))
        self.active_account.setTextFormat(Qt.TextFormat.PlainText)
        self.active_account.setWordWrap(True)
        layout.addWidget(self.active_account)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.primary_sign_in = QPushButton(ui_text('chatgpt_ui.__init__.text_8'))
        self.primary_sign_in.setObjectName('chatgpt_primary_sign_in')
        layout.addWidget(self.primary_sign_in)
        self.primary_sign_in.clicked.connect(lambda: self._safe(self._start_primary_sign_in))
        self.account = QComboBox()
        self.account.setAccessibleName(ui_text('chatgpt_ui.__init__.text_9'))
        layout.addWidget(self.account)
        self.advanced_toggle = QPushButton(ui_text('chatgpt_ui.__init__.text_10'))
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.advanced_toggle.toggled.connect(self._render)
        self.buttons = {}
        for action, label in [
            ('list', ui_text('chatgpt_ui.__init__.text_11')),
            ('initialize', ui_text('chatgpt_ui.__init__.text_12')),
            ('begin', ui_text('chatgpt_ui.__init__.text_13')),
            ('reauthorize', ui_text('chatgpt_ui.__init__.text_14')),
            ('enable_plan', ui_text('chatgpt_ui.__init__.text_15')),
            ('select', ui_text('chatgpt_ui.__init__.text_16')),
            ('refresh', ui_text('chatgpt_ui.__init__.text_17')),
            ('models', ui_text('chatgpt_ui.__init__.text_18')),
            ('sign_out', ui_text('chatgpt_ui.__init__.text_19')),
            ('clear_pause', ui_text('chatgpt_ui.__init__.text_20')),
        ]:
            button = QPushButton(label)
            button.setObjectName('chatgpt_' + action)
            (layout if action in ('select', 'models', 'sign_out', 'enable_plan') else advanced_layout).addWidget(button)
            self.buttons[action] = button
            button.clicked.connect(lambda checked=False, a=action: self._act(a))
        self.open_button = QPushButton(ui_text('chatgpt_ui.__init__.text_21'))
        self.open_button.setObjectName('chatgpt_open_official')
        advanced_layout.addWidget(self.open_button)
        self.open_button.clicked.connect(lambda: self._safe(self.controller.open_authorization))
        self.cancel_button = QPushButton(ui_text('chatgpt_ui.__init__.text_22'))
        layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self._cancel_primary)
        form = QFormLayout()
        self.model_form = form
        layout.addLayout(form)
        self.model = QComboBox()
        form.addRow(ui_text('chatgpt_ui.__init__.text_23'), self.model)
        self.max_calls = QSpinBox()
        self.max_calls.setRange(0, 100)
        form.addRow(ui_text('chatgpt_ui.__init__.text_24'), self.max_calls)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 120)
        self.timeout.setValue(30)
        form.addRow(ui_text('chatgpt_ui.__init__.text_25'), self.timeout)
        self.usage = QLabel()
        self.usage.setWordWrap(True)
        layout.addWidget(self.usage)
        self.controller.changed.connect(self._render)
        self.controller.request_finished.connect(self._primary_finished)
        self.account.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self.controller.invalidate_campaign_usage)
        self.max_calls.valueChanged.connect(self._reset_included_usage)
        self.max_calls.valueChanged.connect(self.controller.invalidate_campaign_usage)
        self.timeout.valueChanged.connect(self._reset_included_usage)
        self.timeout.valueChanged.connect(self.controller.invalidate_campaign_usage)
        for index, widget in enumerate((self.primary_sign_in, self.active_account, self.status, self.account), 1):
            layout.removeWidget(widget)
            layout.insertWidget(index, widget)
        layout.addStretch(1)
        self._render()
        # Extend only the optional connection area without a startup import cycle.
        from desktop_pages.connection_test import ConnectionTest

        self.connection_test = ConnectionTest(self)

    def _start_primary_sign_in(self):
        c = self.controller
        if not c.host_available or c.busy:
            raise ValueError('connection is busy')
        # This click authorizes the local read and opening the official page,
        # never granting scopes or starting model requests for the user.
        self._reset_included_usage()
        self._primary_flow = {
            'phase': 'list',
            'request_id': c._counter + 1,
            'selected': self.account.currentData(),
            'browser_queued': False,
            'reauthorize': c.outcome == 'auth_expired',
        }
        try:
            c.request('list')
        except Exception:
            self._primary_flow = None
            raise

    def start_auto_restore(self):
        """Startup: reload the saved login and refresh it once if expired.

        Runs one startup 'restore' job that may use the network; the worker refreshes only the active
        registration, only when it is refresh_required. Failures leave the
        verified vault state, which shows the sign-in button again.
        """
        c = self.controller
        if not c.host_available or c.busy or self._primary_flow is not None:
            return None
        request = c.request('restore')
        self._restore_flow = request.request_id
        return request

    def _primary_finished(self, request, succeeded):
        if self._restore_flow is not None and request.request_id == self._restore_flow:
            self._restore_flow = None
            return
        flow = self._primary_flow
        if flow is None or request.request_id != flow['request_id']:
            return
        if not succeeded or flow['phase'] != 'list':
            self._primary_flow = None
            return
        QTimer.singleShot(0, lambda: self._safe(lambda: self._continue_primary(request.request_id)))

    def _continue_primary(self, request_id):
        c = self.controller
        flow = self._primary_flow
        if flow is None or flow['request_id'] != request_id or c.busy or flow['phase'] != 'list':
            return
        action = 'begin'
        registration = flow['selected']
        if c.state == 'host_initialization_required':
            answer = QMessageBox.question(
                self,
                ui_text('chatgpt_ui._continue_primary.text_1'),
                ui_text('chatgpt_ui._continue_primary.text_2'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if self._primary_flow is not flow:
                return
            if answer != QMessageBox.StandardButton.Yes:
                self._primary_flow = None
                return
            action = 'first_sign_in'
            registration = None
        else:
            refs = {ref for ref, _ in c.registrations}
            if registration not in refs:
                registration = c.active_registration
            if registration is None and len(refs) == 1:
                registration = next(iter(refs))
            if registration is None and len(refs) > 1:
                self._primary_flow = None
                self.status.setText(ui_text('chatgpt_ui._continue_primary.text_3'))
                return
            if registration == c.active_registration and c.state in CONNECTED_STATES and not flow.get('reauthorize'):
                # Already signed in with the saved login: no new authorization.
                self._primary_flow = None
                return
            if registration == c.active_registration and c.state == 'refresh_required' and not flow.get('reauthorize'):
                # Saved refresh token first; a failed refresh shows sign-in again.
                self._primary_flow = None
                c.request('refresh', registration, confirmed=True)
                return
        flow.update(phase='authorization', request_id=c._counter + 1, browser_queued=False)
        try:
            c.request(action, registration, confirmed=True)
        except Exception:
            self._primary_flow = None
            raise

    def _open_primary_authorization(self, request_id):
        c = self.controller
        flow = self._primary_flow
        if (
            flow is None
            or flow['request_id'] != request_id
            or not c.busy
            or c.stopping
            or c._request is None
            or c._request.request_id != request_id
            or c._authorization_url is None
        ):
            return
        self._safe(c.open_authorization)

    @property
    def primary_sign_in_pending(self):
        """Host schedulers must include the post-join queued authorization gap."""
        return self._primary_flow is not None

    def abandon_primary_sign_in(self):
        # The desktop host calls this before shutdown, cancel, or freeze so a
        # queued post-join step cannot start another authentication worker.
        self._primary_flow = None
        self._restore_flow = None

    def _cancel_primary(self):
        self.abandon_primary_sign_in()
        self.controller.cancel()

    def hideEvent(self, event):
        self.abandon_primary_sign_in()
        super().hideEvent(event)

    def _reset_included_usage(self, *_):
        self._included_usage_registration = None
        self.included_usage_only.setChecked(False)

    def _confirm_included_usage(self, checked):
        c = self.controller
        if checked and c.state == 'plan_ready' and c.active_registration and not c.busy and self.account.currentData() == c.active_registration:
            self._included_usage_registration = c.active_registration
        else:
            self._reset_included_usage()

    def _open_usage_settings(self):
        # Only this fixed official destination opens, and only on a user click.
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl(USAGE_SETTINGS_URL)):
            self.status.setText(ui_text('chatgpt_ui._open_usage_settings.text_1'))

    def _safe(self, call):
        try:
            return call()
        except Exception as exc:
            self.controller.show_outcome(exception_code(exc))

    def _act(self, action):
        self._primary_flow = None

        def run():
            if action != 'list' and not self.consent.isChecked():
                raise ValueError('consent required')
            registration = (
                self.account.currentData() if action in ('reauthorize', 'enable_plan', 'select', 'sign_out', 'refresh', 'models', 'clear_pause') else None
            )
            if action == 'models' and registration != self.controller.active_registration:
                raise ValueError('select account first')
            if action == 'clear_pause' and (not self.controller.account_status_known or self.controller.unknown_count or self.controller.account_pending):
                raise ValueError('unknown reservations cannot clear')
            result = self.controller.request('begin' if action == 'reauthorize' else action, registration, confirmed=self.consent.isChecked())
            self.consent.setChecked(False)
            return result

        return self._safe(run)

    def _render(self):
        c = self.controller
        self.status.setText(c.message)
        if c.busy or c.state != 'plan_ready' or self._rendered_active != c.active_registration:
            self._reset_included_usage()
        selected = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        labels = dict(c.account_labels)
        for reference, state in c.registrations:
            label = labels.get(
                reference, ui_text('chatgpt_ui._render.text_1') if state == 'registration_retry_required' else ui_text('chatgpt_ui._render.text_2')
            )
            self.account.addItem(ui_text('chatgpt_ui._render.text_3').format(label, reference[-8:], STATE_LABELS[state]), reference)
        self.active_account.setText(
            (ui_text('chatgpt_ui._render.text_5').format(labels.get(c.active_registration, ui_text('chatgpt_ui._render.text_4'))))
            if c.active_registration is not None
            else ui_text('chatgpt_ui._render.text_6')
        )
        selection = c.active_registration if c.active_registration != self._rendered_active else selected or c.active_registration
        self._rendered_active = c.active_registration
        index = self.account.findData(selection)
        if index >= 0:
            self.account.setCurrentIndex(index)
        self.account.blockSignals(False)
        chosen = self.model.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        labels = dict(c.model_labels)
        for slug in c.models:
            self.model.addItem(labels.get(slug, slug), slug)
        if chosen in c.models:
            self.model.setCurrentIndex(self.model.findData(chosen))
        self.model.blockSignals(False)
        ready = c.host_available and not c.busy
        self.primary_sign_in.setEnabled(ready)
        signed_in = c.active_registration is not None and c.state in CONNECTED_STATES
        self.primary_sign_in.setVisible(not signed_in or c.outcome == 'auth_expired')
        self.primary_sign_in.setText(ui_text('outcome.auth_expired.action') if c.outcome == 'auth_expired' else ui_text('chatgpt_ui.__init__.text_8'))
        self.buttons['enable_plan'].setVisible(c.state == 'identity_only')
        self.buttons['select'].setVisible(len(c.registrations) > 1)
        self.buttons['models'].setVisible(c.state == 'plan_ready')
        self.buttons['sign_out'].setVisible(c.active_registration is not None)
        self.cancel_button.setVisible(c.busy)
        self.consent.setVisible(c.active_registration is not None or self.advanced_toggle.isChecked())
        self.included_usage_only.setVisible(c.state == 'plan_ready')
        for row in range(3):
            self.model_form.setRowVisible(row, c.state == 'plan_ready')
        flow = self._primary_flow
        if (
            flow is not None
            and flow['phase'] == 'authorization'
            and not flow['browser_queued']
            and c._request is not None
            and c._request.request_id == flow['request_id']
            and c._authorization_url is not None
            and c.busy
            and not c.stopping
        ):
            flow['browser_queued'] = True
            QTimer.singleShot(0, lambda rid=flow['request_id']: self._open_primary_authorization(rid))
        for action, button in self.buttons.items():
            button.setEnabled(ready and (action in ('list', 'initialize', 'begin') or self.account.count() > 0))
        self.buttons['enable_plan'].setEnabled(ready and c.state == 'identity_only' and c.active_registration is not None)
        self.included_usage_only.setEnabled(ready and c.state == 'plan_ready' and c.active_registration is not None)
        self.buttons['models'].setEnabled(ready and c.state == 'plan_ready' and c.account_status_known and not c.account_paused and not c.account_pending)
        self.buttons['clear_pause'].setEnabled(
            ready
            and self.account.count() > 0
            and c.account_state in RECOVERABLE_PAUSES
            and c.account_status_known
            and not c.unknown_count
            and not c.account_pending
        )
        self.open_button.setEnabled(c.busy and not c.stopping and c._authorization_url is not None)
        self.cancel_button.setEnabled(c.busy and not c.stopping)
        self.account.setEnabled(ready)
        self.model.setEnabled(ready)
        self.usage.setText(
            ui_text('chatgpt_ui._render.text_7') if not c.usage_known else ui_text('chatgpt_ui._render.text_8').format(c.reserved_count, c.unknown_count)
        )
        if c.account_status_known:
            barrier = (
                ui_text('chatgpt_ui._render.text_9')
                if c.account_pending
                else (ui_text('chatgpt_ui._render.text_10') if c.account_paused else ui_text('chatgpt_ui._render.text_11'))
            )
            self.usage.setText(self.usage.text() + '\n' + barrier)

    def build_plan_options(self):
        c = self.controller
        if (
            c.busy
            or c.state != 'plan_ready'
            or not c.active_registration
            or not c.account_status_known
            or c.account_paused
            or c.account_pending
            or not c.usage_known
            or c.unknown_count
        ):
            raise ValueError('subscription is not ready')
        if not self.consent.isChecked() or self.model.currentData() not in c.models:
            raise ValueError('explicit consent and discovered model required')
        if (
            not self.included_usage_only.isChecked()
            or self._included_usage_registration != c.active_registration
            or self.account.currentData() != c.active_registration
        ):
            raise ValueError('included usage only confirmation required for this account')
        result = SubscriptionOptions(
            c.active_registration,
            self.model.currentData(),
            self.max_calls.value(),
            self.timeout.value(),
            network_opt_in=True,
            included_usage_policy_confirmed=True,
        )
        self.consent.setChecked(False)
        self._reset_included_usage()
        return result

    def preferences(self):
        return {'version': 1, 'max_calls': self.max_calls.value(), 'timeout_seconds': self.timeout.value()}

    def restore_preferences(self, value):
        if not isinstance(value, dict) or set(value) != {'version', 'max_calls', 'timeout_seconds'} or value['version'] != 1:
            raise ValueError('invalid connection preferences')
        for key, minimum, maximum in [('max_calls', 0, 100), ('timeout_seconds', 1, 120)]:
            if type(value[key]) is not int or not minimum <= value[key] <= maximum:
                raise ValueError('invalid bounded preference')
        self.max_calls.setValue(value['max_calls'])
        self.timeout.setValue(value['timeout_seconds'])
        self.consent.setChecked(False)
        self._reset_included_usage()

    def closeEvent(self, event):
        self.abandon_primary_sign_in()
        if self.controller.busy:
            self.controller.cancel()
            event.ignore()
        else:
            event.accept()


def _safe_error_code(exc):
    """Map an exception to a fixed allowlisted code; never expose its text."""
    code = exception_code(exc)
    if code not in ('operation_failed', 'validation_failed', 'operation_failed_local'):
        return code
    names = tuple(c.__name__ for c in type(exc).__mro__)
    if 'PlanError' in names:
        local = getattr(exc, 'code', None)
        if local == 'remote_error':
            status = getattr(exc, 'http_status', None)
            if status == 400:
                return 'models_http_bad_request'
            if status == 404:
                return 'models_http_not_found'
            if status == 429:
                return 'models_http_rate_limited'
            if type(status) is int and 500 <= status <= 599:
                return 'models_http_server_error'
            return 'models_http_other'
        return local if local in ERROR_LABELS else 'operation_failed_plan'
    if 'AuthError' in names:
        return 'operation_failed_auth'
    if isinstance(exc, (OSError, sqlite3.Error)):
        return 'operation_failed_local'
    return 'operation_failed'


def run_connection_request(request, *, bootstrap, emit, cancelled, session_factory=None, clock=time.monotonic):
    """Worker-only adapter. Parent MUST enforce process deadline/terminate/join.

    No unbounded work on the GUI thread. The parent fixes bootstrap, never accepts
    it from user/model JSON, and forwards only ConnectionEvent through private IPC.
    The official URL is transient IPC, never a log/result/history field.
    """
    if not isinstance(request, ConnectionRequest):
        raise ValueError('typed connection request required')
    if request.action == 'test':
        # Load the probe only inside the allowlisted bounded job.
        from desktop_pages.connection_test import run_probe

        return run_probe(request, bootstrap, cancelled, clock=clock)
    session = None
    deadline = clock() + request.max_runtime_seconds

    def snapshot(state=None, kind='result', **extra):
        summary = session.status_summary()
        rows = tuple((row['registration'], row['state']) for row in summary['registrations'])
        return ConnectionEvent(
            request.request_id,
            kind,
            state or summary['state'],
            rows,
            summary['active_registration'],
            account_labels=tuple((row['registration'], row['account_label']) for row in summary['registrations'] if 'account_label' in row),
            **extra,
        )

    try:
        if session_factory is None:
            from desktop_chatgpt_auth import AuthSession, DPAPIVault

            session_factory = lambda: AuthSession(DPAPIVault(str(bootstrap)))
        session = session_factory()
        if cancelled():
            session.cancel()
            return ConnectionEvent(request.request_id, 'result', 'cancelled')
        if request.action == 'initialize':
            session.initialize_host()
            return snapshot()
        if request.action == 'list':
            return snapshot()
        if request.action == 'restore':
            summary = session.status_summary()
            if summary['active_registration'] is not None and summary['state'] == 'refresh_required':
                # Preserve AuthSession failure barriers and report a fixed refresh stage.
                try:
                    session.refresh(summary['active_registration'])
                except Exception:
                    return snapshot(state='reauthorization_required', kind='error', error_code='restore_refresh_failed')
            return snapshot()
        if request.action in ('begin', 'first_sign_in', 'enable_plan'):
            if request.action == 'first_sign_in':
                session.initialize_host(first_use_only=True)
            url = session.begin(request.registration, enable_plan=True) if request.action == 'enable_plan' else session.begin(request.registration)
            emit(ConnectionEvent(request.request_id, 'authorization', 'authorizing', authorization_url=url))
            while session.state in ('authorizing', 'validating'):
                if cancelled():
                    session.cancel()
                    return snapshot(state=session.state)
                if clock() >= deadline:
                    session.cancel()
                    return ConnectionEvent(request.request_id, 'error', 'timeout', error_code='authorization_timeout')
                session.poll(timeout=0.1)
            if session.state == 'authorization_failed':
                code = getattr(session, 'authorization_error_code', None)
                if code not in (
                    'authorization_exchange_failed',
                    'authorization_identity_failed',
                    'authorization_tokens_failed',
                    'authorization_storage_failed',
                ):
                    code = 'authorization_failed'
                return snapshot(state='authorization_failed', kind='error', error_code=code)
            return snapshot(state=session.state)
        if request.action == 'select':
            session.select(request.registration)
            return snapshot()
        if request.action == 'refresh':
            session.refresh(request.registration)
            return snapshot()
        if request.action == 'sign_out':
            return snapshot(revocation_confirmed=session.sign_out(request.registration))
        if request.action in ('models', 'clear_pause'):
            from desktop_chatgpt_auth import OAuthCredentialReference
            from desktop_chatgpt_provider import discover_models, clear_account_pause, read_account_status
            from pathlib import Path

            reference = OAuthCredentialReference(str(bootstrap), request.registration)
            if request.action == 'models':
                status = read_account_status(reference, Path(bootstrap) / 'control-v1')
                if status != {'state': 'ready', 'pending': False}:
                    raise ValueError('account_paused')
                models = discover_models(
                    reference, network_opt_in=request.user_confirmed, timeout_seconds=min(request.max_runtime_seconds, 120), cancelled=cancelled
                )
                return snapshot(models=tuple(row['slug'] for row in models), model_labels=tuple((row['slug'], row['display_name']) for row in models))
            clear_account_pause(reference, Path(bootstrap) / 'control-v1', user_confirmed=request.user_confirmed)
            return snapshot()
    except Exception as exc:
        # Only known safe constants cross IPC; never exception repr, responses or tokens.
        code = _safe_error_code(exc)
        return ConnectionEvent(request.request_id, 'error', 'unknown', error_code=code)
    finally:
        if request.action in ('begin', 'first_sign_in', 'enable_plan') and session is not None and session.state in ('authorizing', 'validating'):
            try:
                session.cancel()
            except Exception:
                emit(ConnectionEvent(request.request_id, 'error', 'unknown', error_code='authorization_cleanup_failed'))
