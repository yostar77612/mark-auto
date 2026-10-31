from quantlab.assistant.application.connection_contracts import (
    ConnectionEvent,
    ConnectionRequest,
    LOCAL_ACTIONS,
    RECONCILIATION_ACTIONS,
    RECOVERABLE_PAUSES,
    ReconciliationEvent,
    STARTUP_ACTIONS,
    _ref,
    official_authorization_url,
)

AUTH_CODES = frozenset(
    {'refresh_required', 'reauthorization_required', 'restore_refresh_failed', 'credential_diagnosis', 'invalid_credential', 'registration_retry_required'}
)

QUOTA_CODES = frozenset({'quota_paused', 'models_http_rate_limited'})

SUCCESS_CODES = frozenset({'completed', 'success', 'plan_ready'})


def outcome_state(code):
    if type(code) is not str:
        return 'generic_failure'
    if code in AUTH_CODES:
        return 'auth_expired'
    if code in QUOTA_CODES:
        return 'quota_exhausted'
    if code in SUCCESS_CODES:
        return 'success'
    return 'generic_failure'


class ConnectionStateMachine:
    """Host must wire requests to bounded jobs and acknowledge ACTUAL joins.

    quiesce_requested(request): stop/join every auth/inference worker first.
    request_ready(request): now safe to submit the allowlisted job.
    cancel_requested(id): stop/join that job, then call worker_joined(id).
    browser_requested(url): host opens only this transient, validated URL, never logs it.
    apply_event accepts typed worker messages only; late/stale IDs cannot change state.
    """

    def __init__(self, *, emit=None, present=None):
        if emit is None:
            return
        self._emit = emit
        self._present = present
        self.host_available = False
        self.background_busy = False
        self.reconciliation_inspection = None
        self.reconciliation_outcome = None
        self.busy = False
        self.stopping = False
        self.outcome = None
        self.state = 'unknown'
        self._present('init_1')
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
        self._present('init_2')

    def set_host_available(self, available):
        if type(available) is not bool:
            raise ValueError('host availability must be explicit')
        self.host_available = available
        self._emit('changed')

    def set_background_busy(self, active):
        if type(active) is not bool:
            raise ValueError('background status must be explicit')
        if self.background_busy != active:
            self.background_busy = active
            self._emit('changed')

    def request(self, action, registration=None, *, confirmed=False, model=None, acknowledgement_version=None, expected=(None, None, None)):
        if not self.host_available or self.busy:
            raise ValueError(self._present('request_3'))
        if action in RECONCILIATION_ACTIONS and (
            self.background_busy
            or registration != self.active_registration
            or (not self.account_status_known)
            or (not self.account_pending)
            or (self.account_state != 'reserved_unknown')
            or (dict(self.registrations).get(registration) == 'registration_retry_required')
        ):
            raise ValueError('active_or_unknown_request')
        if action == 'test' and (
            registration != self.active_registration
            or self.state != 'plan_ready'
            or model not in self.models
            or (not self.account_status_known)
            or self.account_paused
            or self.account_pending
            or self.unknown_count
        ):
            raise ValueError('account_paused')
        if action == 'models' and (
            registration != self.active_registration
            or self.state != 'plan_ready'
            or (not self.account_status_known)
            or self.account_paused
            or self.account_pending
        ):
            raise ValueError(self._present('request_4'))
        if action == 'clear_pause' and (
            registration != self.active_registration
            or not self.account_status_known
            or self.account_pending
            or self.unknown_count
            or (self.account_state not in RECOVERABLE_PAUSES)
        ):
            raise ValueError(self._present('request_5'))
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
            acknowledgement_version,
            *expected,
        )
        if action in ('test', 'select', 'sign_out'):
            self._present('request_6')
            if action == 'test':
                self._present('request_7')
        self.reconciliation_inspection = None
        self.reconciliation_outcome = None
        self.busy = True
        self.outcome = None
        self.stopping = False
        self._request = request
        self._authorization_url = None
        self._terminal_received = False
        self._terminal_ok = False
        self._awaiting_join = action not in LOCAL_ACTIONS | STARTUP_ACTIONS
        self._present('request_8', action=action)
        if action in RECONCILIATION_ACTIONS:
            self._present('request_9', action=action)
        self._emit('changed')
        self._emit('quiesce_requested' if self._awaiting_join else 'request_ready', request)
        return request

    def acknowledge_quiescence(self, request_id, *, joined):
        if not self._request or request_id != self._request.request_id or (not self._awaiting_join):
            return False
        if joined is not True:
            self._present('acknowledge_quiescence_10')
            self._emit('changed')
            return False
        if self.stopping:
            return False
        self._awaiting_join = False
        self._present('acknowledge_quiescence_11')
        self._emit('changed')
        self._emit('request_ready', self._request)
        return True

    def apply_event(self, event):
        if not isinstance(event, ConnectionEvent):
            raise ValueError('typed sanitized event required')
        if not self._request or event.request_id != self._request.request_id or self._awaiting_join or self.stopping:
            return False
        if self._request.action in RECONCILIATION_ACTIONS:
            return self._apply_reconciliation_event(event)
        if isinstance(event, ReconciliationEvent):
            raise ValueError('unexpected reconciliation event')
        if event.kind == 'authorization':
            self._authorization_url = event.authorization_url
            self.state = 'authorizing'
            self._present('apply_event_12')
        elif event.kind == 'progress':
            self.state = event.state
            self._present('apply_event_13', event=event)
        else:
            action = self._request.action
            if action == 'test':
                self._terminal_received = True
                self._terminal_ok = event.kind == 'result'
                self.stopping = True
                self._present('apply_event_14', event=event)
                usage = getattr(event, 'test_usage', None)
                self._present('apply_event_15', usage=usage)
                self._present('apply_event_16')
                self._emit('changed')
                return True
            self.state = event.state
            self._terminal_received = True
            self._terminal_ok = event.kind == 'result'
            self._authorization_url = None
            if event.kind == 'error':
                self.outcome = outcome_state(event.error_code)
                self._present('apply_event_17', event=event)
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
                self._present('apply_event_18', event=event)
                if action == 'sign_out':
                    self._present('apply_event_19', event=event)
            self.stopping = True
            self._present('apply_event_20')
        self._emit('changed')
        return True

    def _apply_reconciliation_event(self, event):
        if (
            not isinstance(event, ReconciliationEvent)
            or event.reconciliation_action != self._request.action
            or event.reconciliation_registration != self._request.registration
            or (self.active_registration != self._request.registration)
        ):
            raise ValueError('reconciliation account/request mismatch')
        self._terminal_received = True
        self._terminal_ok = event.kind == 'result'
        self.stopping = True
        self.reconciliation_inspection = event.inspection
        self.reconciliation_outcome = event.inspection_outcome
        if event.kind == 'error':
            self._present('apply_reconciliation_event_21', event=event)
        elif event.inspection is not None:
            kind, sequence, calls, old_enough = event.inspection
            self._present('apply_reconciliation_event_22', calls=calls, event=event, old_enough=old_enough, sequence=sequence)
            self._present('apply_reconciliation_event_23', kind=kind)
        else:
            if event.account_status is None:
                self.account_status_known = False
                self._present('apply_reconciliation_event_24')
            else:
                state, pending = event.account_status
                self.set_account_status(self._request.registration, {'state': state, 'pending': pending})
                self._present('apply_reconciliation_event_25', pending=pending, state=state)
            self.invalidate_campaign_usage()
        self._present('apply_reconciliation_event_26')
        self._emit('changed')
        return True

    def show_outcome(self, code):
        self.outcome = outcome_state(code)
        self._present('show_outcome_27', code=code)
        self._emit('changed')

    def open_authorization(self):
        if not self.busy or self.stopping or (not self._authorization_url):
            raise ValueError(self._present('open_authorization_28'))
        value = official_authorization_url(self._authorization_url)
        self._authorization_url = None
        self._emit('changed')
        self._emit('browser_requested', value)

    def cancel(self):
        if not self.busy:
            return
        self.stopping = True
        self._authorization_url = None
        self._terminal_received = False
        self._terminal_ok = False
        self._present('cancel_29', RECONCILIATION_ACTIONS=RECONCILIATION_ACTIONS)
        self._emit('changed')
        self._emit('cancel_requested', self._request.request_id)

    def worker_joined(self, request_id, *, joined, terminal_received=True):
        if not self._request or request_id != self._request.request_id or joined is not True:
            return False
        finished = self._request
        succeeded = terminal_received is True and self._terminal_received and self._terminal_ok
        if terminal_received is not True or not self._terminal_received:
            if finished.action not in RECONCILIATION_ACTIONS:
                self.state = 'unknown'
            self.reconciliation_inspection = None
            self.reconciliation_outcome = None
            self._present('worker_joined_30', RECONCILIATION_ACTIONS=RECONCILIATION_ACTIONS, finished=finished)
            self.usage_known = False
            self.unknown_count = None
            self.account_status_known = False
        self._present('worker_joined_31')
        self.busy = False
        self.stopping = False
        self._awaiting_join = False
        self._authorization_url = None
        self._request = None
        self._emit('changed')
        self._emit('request_finished', finished, succeeded)
        return True

    def set_account_status(self, registration, status):
        """Verified local account barrier only; never invents campaign call counts."""
        _ref(registration)
        if registration != self.active_registration:
            raise ValueError('account status/account mismatch')
        allowed = RECOVERABLE_PAUSES | {'ready', 'reserved_unknown', 'blocked'}
        if not isinstance(status, dict) or set(status) != {'state', 'pending'} or status['state'] not in allowed or (type(status['pending']) is not bool):
            raise ValueError('verified account status required')
        self.account_paused = status['state'] != 'ready'
        self.account_pending = status['pending']
        self.account_state = status['state']
        self.account_status_known = True
        self._emit('changed')

    def invalidate_campaign_usage(self):
        self.usage_known = False
        self.reserved_count = None
        self.unknown_count = None
        self._emit('changed')

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
            'user_confirmed_consumed',
            'blocked',
        }
        if (
            not isinstance(account_status, dict)
            or set(account_status) != {'state', 'pending'}
            or account_status['state'] not in allowed
            or (type(account_status['pending']) is not bool)
        ):
            raise ValueError('verified account status required')
        if not isinstance(receipts, (list, tuple)) or len(receipts) > 10000:
            raise ValueError('bounded verified receipts required')
        sequences = []
        unknown = 0
        for row in receipts:
            if not isinstance(row, dict) or type(row.get('sequence')) is not int or row['sequence'] < 1 or (not isinstance(row.get('status'), str)):
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
        self._emit('changed')
