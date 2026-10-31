"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""
from __future__ import annotations

from quantlab.assistant.adapters.chatgpt.account_summary import status_summary

from quantlab.assistant.domain.auth_protocol import AUTHORIZE
from quantlab.assistant.domain.auth_protocol import AuthError
from quantlab.assistant.ports.auth import AuthTransportPort
from quantlab.assistant.ports.auth import AuthVaultPort
from quantlab.assistant.adapters.chatgpt.vault import DPAPIVault
from quantlab.assistant.domain.auth_protocol import DYNAMIC_CLIENT
from quantlab.assistant.adapters.chatgpt.identity import IdentityValidator
from quantlab.assistant.adapters.chatgpt.loopback import LoopbackListener
from quantlab.assistant.adapters.chatgpt.identity import OfficialTransport
from quantlab.assistant.domain.auth_protocol import PLAN_SCOPES
from pathlib import Path
from quantlab.assistant.domain.auth_protocol import RESOURCE
from quantlab.assistant.domain.auth_protocol import SCOPES
from quantlab.assistant.domain.auth_protocol import TERMINAL_REFRESH_ERRORS
from quantlab.assistant.domain.auth_protocol import TOKEN
from quantlab.assistant.adapters.chatgpt.loopback import _Pending
from quantlab.assistant.domain.auth_protocol import _client
from quantlab.assistant.domain.auth_protocol import _json
from quantlab.assistant.domain.auth_tokens import _parsed_tokens
from quantlab.assistant.domain.auth_protocol import _text
from quantlab.assistant.domain.auth_protocol import _unique
from quantlab.assistant.domain.auth_protocol import _validate_record
from dataclasses import dataclass
from urllib.parse import parse_qsl
from quantlab.assistant.domain.auth_protocol import pkce_challenge
import re
import secrets
import threading
import time
from urllib.parse import urlencode
from urllib.parse import urlsplit
import uuid


class AuthSession:
    def status_summary(self):
        return status_summary(self)

    def __init__(self,vault: AuthVaultPort,transport: AuthTransportPort | None=None,*,listener_factory=LoopbackListener):
        self.vault=vault
        self.transport=transport if transport is not None else OfficialTransport()
        self.validator=IdentityValidator(self.transport)
        self._listener_factory=listener_factory
        self._pending=None
        self._mutex=threading.RLock()
        self._commit_mutex=threading.Lock()
        self.state='disconnected'
        self.active_registration=None
        self.authorization_error_code=None
        self._cancel=threading.Event()

    def __reduce_ex__(self,protocol):
        raise TypeError('AuthSession cannot cross process boundaries')

    def initialize_host(self,*,first_use_only=False):
        """Explicit first-install/recovery action; never silently regenerate at startup."""
        if type(first_use_only) is not bool:raise AuthError('invalid_first_use_confirmation')
        with self.vault.lock():
            record=self.vault.load()
            if first_use_only:
                if record is not None:raise AuthError('explicit_host_recovery_required')
                checker=getattr(self.vault,'assert_first_use',None)
                if checker is None:raise AuthError('first_use_check_unavailable')
                checker()
            if record is None:
                record=dict(schema=2,host_id='urn:uuid:'+str(uuid.uuid4()),active=None,registrations={},registration_retries={})
                self.vault.save(record)
            return _validate_record(record)['host_id']

    def _load(self):
        record=self.vault.load()
        if record is None:raise AuthError('host_initialization_required')
        return _validate_record(record)

    def begin(self,registration=None,*,enable_plan=False):
        if type(enable_plan) is not bool or enable_plan and registration is None:
            raise AuthError('explicit_registered_plan_consent_required')
        with self._mutex:
            if self._pending is not None:raise AuthError('authorization_busy')
            # Host setup/recovery is a separate explicit operation. Never infer
            # that a missing record means a new installation.
            with self.vault.lock():
                record=self.vault.load()
                if record is None:
                    raise AuthError('host_initialization_required')
                record=_validate_record(record)
                selected=record['registrations'].get(registration) if registration else None
                retry=record['registration_retries'].get(registration) if registration else None
                if registration and selected is None and retry is None:raise AuthError('unknown_registration')
                if enable_plan and selected is None:raise AuthError('explicit_registered_plan_consent_required')
                client=selected['identity']['client_id'] if selected is not None else (retry['client_id'] if retry is not None else DYNAMIC_CLIENT)
                self.active_registration=record['active']
            try:listener=self._listener_factory(self.accept_callback)
            except Exception:raise AuthError('callback_bind_failed') from None
            self._cancel.clear()
            pending=_Pending(secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(64),
                'http://127.0.0.1:'+str(listener.port)+'/auth/callback',time.monotonic()+600,registration,
                None if selected is None else selected['identity'].copy(),listener,
                None if client==DYNAMIC_CLIENT else client)
            self._pending=pending;self.state='authorizing';self.authorization_error_code=None
            params=dict(client_id=client,
                ext_agent_host_id=record['host_id'],response_type='code',redirect_uri=pending.redirect,scope=SCOPES,
                resource=RESOURCE,state=pending.state,nonce=pending.nonce,code_challenge_method='S256',
                code_challenge=pkce_challenge(pending.verifier))
            if client==DYNAMIC_CLIENT:params['agent_name_hint']='MarkAuto QuantLab'
            if enable_plan:params['prompt']='consent'
            # Retained ID-token hints deliberately omitted: URL contains no tokens.
            return AUTHORIZE+'?'+urlencode(params)

    def cancel(self):
        # Linearization boundary: cancellation wins before commit starts. If
        # an atomic save has already started, wait for it and report the actual
        # connected state; callers can explicitly sign out the new session.
        with self._commit_mutex:
            self._cancel.set()
        with self._mutex:
            if self._pending is None and self.state in ('plan_ready','identity_only'):
                return self.state
            if self._pending:
                self._pending.listener.close();self._pending=None
            self.state='cancelled'

    def poll(self,timeout=.1):
        with self._mutex:
            pending=self._pending
            if pending and time.monotonic()>=pending.deadline:
                pending.listener.close();self._pending=None;self.state='timeout'
                raise AuthError('authorization_timeout')
        if pending:pending.listener.poll(timeout)
        return self.state

    def accept_callback(self,method,target,host,peer):
        with self._mutex:
            pending=self._pending
            if pending is None or self._cancel.is_set():raise AuthError('no_pending_authorization')
            if time.monotonic()>=pending.deadline:
                pending.listener.close();self._pending=None;self.state='timeout'
                raise AuthError('authorization_timeout')
            if method!='GET' or peer!='127.0.0.1' or host!=urlsplit(pending.redirect).netloc or not isinstance(target,str) or len(target)>8192:
                raise AuthError('invalid_callback')
            if not target.startswith('/auth/callback?') or '#' in target or any(ord(c)<33 or ord(c)>126 for c in target) or re.search(r'%(?![A-Fa-f0-9]{2})',target):
                raise AuthError('invalid_callback')
            try:pairs=parse_qsl(target.split('?',1)[1],keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=16)
            except ValueError:raise AuthError('invalid_callback') from None
            query=_unique(pairs)
            if not _text(query.get('state'),256) or not secrets.compare_digest(query['state'],pending.state):
                raise AuthError('invalid_state')
            if 'code' in query and 'error' in query:raise AuthError('ambiguous_callback')
            if 'error' in query:
                pending.listener.close();self._pending=None;self.state='cancelled'
                raise AuthError('authorization_denied')
            client=query.get('client_id',pending.client_id)
            if not _client(client) or pending.client_id is not None and client!=pending.client_id:
                raise AuthError('invalid_client_id')
            if not _text(query.get('code'),4096):raise AuthError('invalid_code')
            # Consume before any exchange, including failures. No replay of a code.
            pending.listener.close();self._pending=None;self.state='validating'
            failure_code='authorization_exchange_failed'
            try:
                response=self.transport.request('POST',TOKEN,form=dict(grant_type='authorization_code',client_id=client,
                    code=query['code'],code_verifier=pending.verifier,redirect_uri=pending.redirect,resource=RESOURCE))
                if response.status!=200:
                    error=_json(response.body).get('error')
                    if isinstance(error,dict):error=error.get('code')
                    if error=='invalid_grant' and pending.identity is None:
                        failure_code='authorization_storage_failed'
                        self._retain_registration_retry(pending,client)
                        self.state='registration_retry_required'
                        raise AuthError(self.state)
                    raise AuthError('code_exchange_failed')
                data=_json(response.body)
                failure_code='authorization_identity_failed'
                identity=self.validator.verify(data.get('id_token'),client,pending.nonce)
                if pending.identity is not None and identity!=pending.identity:raise AuthError('account_mismatch')
                failure_code='authorization_tokens_failed'
                tokens=self._tokens(data)
                if self._cancel.is_set() or time.monotonic()>=pending.deadline:raise AuthError('authorization_cancelled')
                failure_code='authorization_storage_failed'
                with self.vault.lock():
                    if self._cancel.is_set() or time.monotonic()>=pending.deadline:
                        raise AuthError('authorization_cancelled')
                    record=self._load()
                    ref=pending.registration or uuid.uuid4().hex
                    old=record['registrations'].get(ref)
                    if pending.identity is not None and (old is None or old['identity']!=identity):raise AuthError('registration_changed')
                    if pending.registration and pending.identity is None:
                        if record['registration_retries'].get(ref)!={'client_id':client}:raise AuthError('registration_changed')
                    # A new attempt must not alias an already saved registration.
                    if pending.identity is None and any(r['identity']==identity for r in record['registrations'].values()):raise AuthError('registration_already_saved')
                    record['registrations'][ref]=dict(identity=identity,tokens=tokens,generation=1 if old is None else old['generation']+1,operation=None)
                    record['registration_retries'].pop(ref,None)
                    record['active']=ref
                    with self._commit_mutex:
                        if self._cancel.is_set() or time.monotonic()>=pending.deadline:
                            raise AuthError('authorization_cancelled')
                        self.vault.save(_validate_record(record))
                        self.active_registration=ref;self.state=self._state(tokens)
                return ref
            except Exception:
                self.state='cancelled' if self._cancel.is_set() else ('registration_retry_required' if self.state=='registration_retry_required' else 'authorization_failed')
                self.authorization_error_code=failure_code if self.state=='authorization_failed' else None
                raise AuthError(self.state) from None

    def _retain_registration_retry(self,pending,client):
        # This unverified ID is only an OAuth routing hint. It can never supply
        # an active identity, credential, model catalog, or inference grant.
        with self.vault.lock():
            record=self._load()
            ref=pending.registration or uuid.uuid4().hex
            if ref in record['registrations']:raise AuthError('registration_changed')
            old=record['registration_retries'].get(ref)
            if old is not None and old!={'client_id':client}:raise AuthError('registration_changed')
            record['registration_retries'][ref]={'client_id':client}
            with self._commit_mutex:
                if self._cancel.is_set() or time.monotonic()>=pending.deadline:
                    raise AuthError('authorization_cancelled')
                self.vault.save(_validate_record(record))

    def _tokens(self, data, previous=None):
        fields = _parsed_tokens(data, previous)
        return dict(access_token=fields['access_token'], refresh_token=fields['refresh_token'],
                    id_token=fields['id_token'], scopes=fields['scopes'],
                    expires_at=time.time()+fields['expires_in'], earliest_refresh_at=fields['earliest_refresh_at'])

    @staticmethod
    def _state(tokens):
        if time.time() >= tokens['expires_at']-5:
            return 'refresh_required'
        return 'plan_ready' if PLAN_SCOPES<=set(tokens['scopes']) else 'identity_only'


    def registrations(self):
        """Local opaque references/status only. Never exposes ID claims or tokens."""
        with self.vault.lock():
            record=self._load()
            return ([{'registration':ref,'state':'reauthorization_required' if row['operation'] or row['tokens'] is None else self._state(row['tokens'])}
                    for ref,row in record['registrations'].items()]
                    +[{'registration':ref,'state':'registration_retry_required'} for ref in record['registration_retries']])

    def select(self,registration):
        with self.vault.lock():
            record=self._load();row=record['registrations'].get(registration)
            if row is None:raise AuthError('unknown_registration')
            record['active']=registration;self.vault.save(record)
            self.active_registration=registration
            self.state='reauthorization_required' if row['tokens'] is None or row['operation'] else self._state(row['tokens'])
        return self.state

    def access_token(self,registration):
        """Worker-local secret resolution. Never refreshes implicitly or permits identity-only."""
        with self.vault.lock():
            record=self._load();row=record['registrations'].get(registration)
            if row is None or row['operation'] or row['tokens'] is None:raise AuthError('reauthorization_required')
            tokens=row['tokens']
            if not PLAN_SCOPES<=set(tokens['scopes']):raise AuthError('plan_scope_missing')
            if time.time()>=tokens['expires_at']-5:raise AuthError('refresh_required')
            return tokens['access_token']

    def refresh(self,registration):
        with self.vault.lock():
            record=self._load();row=record['registrations'].get(registration)
            if row is None or row['operation'] or row['tokens'] is None:raise AuthError('reauthorization_required')
            previous=row['tokens']
            if time.time()<previous['expires_at']-60:return self._state(previous)
            if not previous['refresh_token']:raise AuthError('reauthorization_required')
            if time.time()<previous['earliest_refresh_at']:raise AuthError('refresh_too_early')
            row['operation']='refresh'
            self.vault.save(record)  # durable barrier BEFORE transmission
            try:
                response=self.transport.request('POST',TOKEN,form=dict(grant_type='refresh_token',client_id=row['identity']['client_id'],refresh_token=previous['refresh_token'],resource=RESOURCE))
                if response.status!=200:
                    error=_json(response.body).get('error')
                    if isinstance(error,dict):error=error.get('code')
                    if error in TERMINAL_REFRESH_ERRORS:
                        row['tokens']=None;row['operation']=None;self.vault.save(record)
                        self.state='reauthorization_required'
                    elif response.status>=500:
                        row['operation']=None;self.vault.save(record);self.state='transient_blocked'
                    else:
                        self.state='client_configuration_required' if error=='invalid_client' else 'reauthorization_required'
                    raise AuthError(self.state)
                data=_json(response.body)
                if 'id_token' in data and self.validator.verify(data['id_token'],row['identity']['client_id'])!=row['identity']:
                    raise AuthError('account_mismatch')
                tokens=self._tokens(data,previous)
                if not tokens['refresh_token'] or tokens['refresh_token']==previous['refresh_token']:raise AuthError('refresh_not_rotated')
                row.update(tokens=tokens,generation=row['generation']+1,operation=None)
                self.vault.save(record)
                self.state=self._state(tokens)
                return self.state
            except Exception:
                # If response/persistence is ambiguous the durable barrier remains.
                # Neither restart nor another worker can replay the old refresh token.
                if self.state not in ('transient_blocked','client_configuration_required'):
                    self.state='reauthorization_required'
                raise AuthError(self.state) from None

    def sign_out(self,registration):
        self.cancel()
        confirmed=False
        with self.vault.lock():
            record=self._load();row=record['registrations'].get(registration)
            if row is None:raise AuthError('unknown_registration')
            tokens=row['tokens'];uncertain_rotation=row['operation']=='refresh'
            row['operation']='sign_out'
            self.vault.save(record)
            try:
                if tokens and tokens['refresh_token']:
                    endpoint=self.validator.discovery()['revocation_endpoint']
                    response=self.transport.request('POST',endpoint,form=dict(token=tokens['refresh_token'],token_type_hint='refresh_token',client_id=row['identity']['client_id']))
                    confirmed=response.status==200 and not uncertain_rotation
            except Exception:
                confirmed=False
            finally:
                row['tokens']=None;row['operation']=None
                if record['active']==registration:record['active']=None
                try:self.vault.save(record)
                except Exception:raise AuthError('local_signout_persistence_failed') from None
            self.active_registration=record['active'];self.state='disconnected'
        return confirmed


@dataclass(frozen=True)
class OAuthCredentialReference:
    """Only bootstrap path and opaque reference may be serialized to a worker."""
    bootstrap: str
    registration: str
    def __post_init__(self):
        if not Path(self.bootstrap).is_absolute() or not re.fullmatch('[a-f0-9]{32}',self.registration):
            raise AuthError('invalid_credential_reference')
    def __call__(self):
        return AuthSession(DPAPIVault(self.bootstrap)).access_token(self.registration)
