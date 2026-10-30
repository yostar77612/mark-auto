from dataclasses import dataclass, field, asdict
import re
from urllib.parse import urlsplit, parse_qsl

RECONCILIATION_ACKNOWLEDGEMENT_VERSION = 1

FINISHED_RECONCILIATION_ACKNOWLEDGEMENT_VERSION = 1

RECONCILIATION_ACTIONS = frozenset(('inspect_unknown', 'resolve_unknown', 'resolve_finished_unknown'))

FINISHED_OUTCOMES = frozenset(
    (
        'ambiguous_candidate',
        'ambiguous_event_type',
        'ambiguous_terminal',
        'cancelled',
        'candidate_byte_limit',
        'candidate_family_mismatch',
        'compressed_response',
        'deadline_exceeded',
        'done_without_completion',
        'duplicate_event_type',
        'duplicate_json_key',
        'eof_without_completion',
        'event_byte_limit',
        'event_count',
        'failed_or_interrupted',
        'http_transport_failed',
        'incomplete_message',
        'invalid_content_type',
        'invalid_credential',
        'invalid_event',
        'invalid_json',
        'invalid_output',
        'invalid_response_id',
        'invalid_stream_chunk',
        'invalid_terminal_status',
        'invalid_utf8',
        'json_depth',
        'json_object_required',
        'missing_output',
        'nonfinite_json',
        'redirect_rejected',
        'refusal_or_tool_event',
        'refusal_or_unknown_content',
        'remote_error',
        'request_byte_limit',
        'response_id_mismatch',
        'response_incomplete',
        'stream_byte_limit',
        'tools_or_unknown_output',
        'truncated_event',
    )
)

ACTIONS = frozenset(
    (
        'initialize',
        'begin',
        'first_sign_in',
        'enable_plan',
        'list',
        'restore',
        'select',
        'sign_out',
        'refresh',
        'models',
        'clear_pause',
        'test',
        'inspect_unknown',
        'resolve_unknown',
        'resolve_finished_unknown',
    )
)

LOCAL_ACTIONS = frozenset(('list',)) | RECONCILIATION_ACTIONS

STARTUP_ACTIONS = frozenset(('restore',))

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

RECOVERABLE_PAUSES = frozenset(
    (
        'eligibility_blocked',
        'quota_paused',
        'transient_blocked',
        'invalid_request',
        'configuration_blocked',
        'credential_diagnosis',
        'grant_blocked',
        'user_confirmed_consumed',
    )
)

REF = '[a-f0-9]{32}'

MODEL = '[A-Za-z0-9._:-]{1,128}'


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
    if url.scheme != 'https' or url.netloc != 'auth.openai.com' or url.path != '/api/accounts/authorize' or url.fragment or any((c.isspace() for c in value)):
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
        or (not port)
        or callback.username
        or callback.password
        or (callback.path != '/auth/callback')
        or callback.query
        or callback.fragment
    ):
        raise ValueError('invalid callback')
    if params['response_type'] != 'code' or params['resource'] != 'https://api.openai.com/v1' or params['code_challenge_method'] != 'S256':
        raise ValueError('invalid authorization flow')
    if not re.fullmatch('[A-Za-z0-9._:-]{1,256}', params['client_id']) or not re.fullmatch('urn:uuid:[a-fA-F0-9-]{36}', params['ext_agent_host_id']):
        raise ValueError('invalid public client binding')
    for key in ('state', 'nonce', 'code_challenge'):
        if not re.fullmatch('[A-Za-z0-9_-]{32,128}', params[key]):
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
    acknowledgement_version: int | None = None
    expected_sequence: int | None = None
    expected_calls: int | None = None
    expected_outcome: str | None = None

    def __post_init__(self):
        if type(self.request_id) is not int or self.request_id < 1 or self.action not in ACTIONS:
            raise ValueError('invalid connection request')
        _ref(self.registration, optional=True)
        if self.action == 'first_sign_in' and self.registration is not None:
            raise ValueError('first sign-in cannot select an existing account')
        if (
            self.action in ('enable_plan', 'select', 'sign_out', 'refresh', 'models', 'clear_pause', 'test') or self.action in RECONCILIATION_ACTIONS
        ) and self.registration is None:
            raise ValueError('registration required')
        expected = (self.expected_sequence, self.expected_calls, self.expected_outcome)
        if self.action == 'resolve_finished_unknown':
            if (
                any((type(value) is not int or not 1 <= value <= 100 for value in expected[:2]))
                or type(self.expected_outcome) is not str
                or self.expected_outcome not in FINISHED_OUTCOMES
            ):
                raise ValueError('resolution_confirmation_required')
        elif expected != (None, None, None):
            raise ValueError('expected receipt only for finished resolution')
        if self.action == 'test':
            if type(self.model) is not str or not re.fullmatch(MODEL, self.model):
                raise ValueError('discovered model required')
        elif self.model is not None:
            raise ValueError('model only for connection test')
        versions = {'resolve_unknown': RECONCILIATION_ACKNOWLEDGEMENT_VERSION, 'resolve_finished_unknown': FINISHED_RECONCILIATION_ACKNOWLEDGEMENT_VERSION}
        if self.action in versions:
            if self.user_confirmed is not True or type(self.acknowledgement_version) is not int or self.acknowledgement_version != versions[self.action]:
                raise ValueError('resolution_confirmation_required')
        elif self.acknowledgement_version is not None:
            raise ValueError('acknowledgement only for resolution')
        if type(self.max_runtime_seconds) is not int or not 1 <= self.max_runtime_seconds <= 600:
            raise ValueError('bounded runtime required')
        if type(self.user_confirmed) is not bool or (self.action not in LOCAL_ACTIONS | STARTUP_ACTIONS and (not self.user_confirmed)):
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
        if self.active_registration is not None and self.kind == 'result' and (self.active_registration not in seen):
            raise ValueError('active registration missing from verified summary')
        if (
            self.kind == 'result'
            and self.state in ('plan_ready', 'identity_only', 'refresh_required', 'reauthorization_required')
            and (self.active_registration is None)
        ):
            raise ValueError('connected status requires an active verified registration')
        if self.authorization_url is not None:
            if self.kind != 'authorization':
                raise ValueError('authorization URL only in transient event')
            official_authorization_url(self.authorization_url)
        if not isinstance(self.error_code, str) or not re.fullmatch('[a-z_]{0,80}', self.error_code):
            raise ValueError('invalid sanitized error code')
        if self.revocation_confirmed is not None and type(self.revocation_confirmed) is not bool:
            raise ValueError('invalid revocation status')
        if not isinstance(self.models, tuple) or len(self.models) > 1024 or any((not isinstance(x, str) or not re.fullmatch(MODEL, x) for x in self.models)):
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
                or (not isinstance(row[1], str))
                or (not 1 <= len(row[1]) <= 256)
                or any((ord(c) < 32 for c in row[1]))
            ):
                raise ValueError('invalid model labels')
        if self.model_labels and tuple((row[0] for row in self.model_labels)) != self.models:
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
                or (row[0] in label_refs)
                or (states[row[0]] == 'registration_retry_required')
                or (not isinstance(row[1], str))
                or (not re.fullmatch('已驗證帳戶 ••••[a-f0-9]{8}（電子郵件未提供）', row[1]))
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
            or any((type(v) is not int or not 0 <= v <= 2**53 for v in self.test_usage))
            or (self.test_usage[0] + self.test_usage[1] != self.test_usage[2])
        ):
            raise ValueError('invalid bounded token usage')


@dataclass(frozen=True)
class ReconciliationEvent(ConnectionEvent):
    """Fixed local-control evidence, without loading or projecting the auth vault."""

    reconciliation_action: str = ''
    reconciliation_registration: str | None = None
    inspection: tuple | None = None
    account_status: tuple | None = None
    inspection_outcome: str | None = None

    def __post_init__(self):
        super().__post_init__()
        _ref(self.reconciliation_registration)
        if self.inspection_outcome is not None and (
            self.inspection is None or self.inspection[0] != 'k2_resolvable' or self.inspection_outcome not in FINISHED_OUTCOMES
        ):
            raise ValueError('invalid inspection outcome')
        if (
            self.reconciliation_action not in RECONCILIATION_ACTIONS
            or self.kind not in ('result', 'error')
            or self.state != 'unknown'
            or self.registrations
            or (self.active_registration is not None)
            or (self.authorization_url is not None)
            or self.models
            or self.model_labels
            or self.account_labels
            or (self.revocation_confirmed is not None)
        ):
            raise ValueError('invalid local reconciliation event')
        if self.kind == 'error':
            if self.inspection is not None or self.account_status is not None or (not self.error_code):
                raise ValueError('invalid reconciliation error')
            return
        if self.error_code:
            raise ValueError('invalid reconciliation result')
        if self.reconciliation_action == 'inspect_unknown':
            if type(self.inspection) is not tuple or len(self.inspection) != 4 or self.account_status is not None:
                raise ValueError('invalid bounded inspection')
            kind, sequence, calls, old_enough = self.inspection
            if (
                kind not in ('k1_resolvable', 'k1_other_registration', 'k2_resolvable', 'k2_other_registration', 'k2_unresolvable', 'none')
                or type(old_enough) is not bool
            ):
                raise ValueError('invalid inspection kind')
            if (kind == 'k2_resolvable') != (self.inspection_outcome is not None):
                raise ValueError('invalid inspection outcome')
            if kind in ('k1_resolvable', 'k2_resolvable'):
                if any((type(value) is not int or not 1 <= value <= 100 for value in (sequence, calls))) or sequence != calls:
                    raise ValueError('invalid inspection counts')
            elif sequence is not None or calls is not None or old_enough:
                raise ValueError('unexpected inspection details')
        elif self.inspection is not None or (
            self.account_status is not None
            and (
                type(self.account_status) is not tuple
                or len(self.account_status) != 2
                or self.account_status[0] not in RECOVERABLE_PAUSES | {'ready', 'reserved_unknown', 'blocked'}
                or (type(self.account_status[1]) is not bool)
            )
        ):
            raise ValueError('invalid resolved account status')


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
            or (self.included_usage_policy_confirmed is not True)
        ):
            raise ValueError('no paid fallback or implicit consent')
