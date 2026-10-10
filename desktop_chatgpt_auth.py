"""Explicit, official ChatGPT public-client OAuth. No import/startup network work.

The host owns per-action consent and browser presentation. ``begin`` returns an
OpenAI authorization URL, never opens a browser or submits consent. Call ``poll``
from a UI worker until terminal, or ``cancel``. Never log the URL or callbacks.
Actual sign-in, Windows ACL/DPAPI and account admission require separate QA.

Protocol: https://developers.openai.com/siwc/token-sharing-open-source/sign-in
JWT verification: PyJWT[crypto] 2.15.1, fixed RS256 from production discovery.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import stat
import sys
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit
import uuid

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
REVOCATION = ISSUER + '/api/accounts/oauth/revoke'
DISCOVERY = ISSUER + '/.well-known/openid-configuration'
JWKS = ISSUER + '/.well-known/jwks.json'
RESOURCE = 'https://api.openai.com/v1'
DYNAMIC_CLIENT = 'dynamic_agent_client'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
PLAN_SCOPES = frozenset(('resource.invoke', 'chatgpt.tokens.use.direct'))
PINNED_DISCOVERY = dict(issuer=ISSUER, authorization_endpoint=AUTHORIZE,
                        token_endpoint=TOKEN, revocation_endpoint=REVOCATION, jwks_uri=JWKS)
MAX_RECORD = 65536
TERMINAL_REFRESH_ERRORS = frozenset(('invalid_grant','invalid_refresh_token','token_expired',
    'refresh_token_expired','refresh_token_invalidated','refresh_token_reused'))


class AuthError(ValueError):
    """Only fixed local error codes, never remote bodies or credential values."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthError('duplicate_json_key')
        result[key] = value
    return result


def _json(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_RECORD:
        raise AuthError('response_size')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(AuthError('invalid_json')))
        if not isinstance(value, dict):
            raise AuthError('invalid_json')
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise AuthError('invalid_json') from None


def _bytes(value):
    try:
        raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise AuthError('invalid_record') from None
    if len(raw) > MAX_RECORD:
        raise AuthError('record_size')
    return raw


def _text(value, maximum=16384):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(c) < 33 or ord(c) > 126 for c in value)


def _client(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,256}', value) and value != DYNAMIC_CLIENT


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 2**53


def pkce_challenge(verifier):
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
        raise AuthError('invalid_verifier')
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()


@dataclass(frozen=True, repr=False)
class HttpResponse:
    status: int
    body: bytes = field(repr=False)


class OfficialTransport:
    """No redirects, proxies, cookies or retries. Bounded HTTPS, fixed origins."""
    def request(self, method, url, *, form=None):
        if url not in (DISCOVERY, JWKS, TOKEN, REVOCATION):
            raise AuthError('untrusted_endpoint')
        if (method, url) not in (('GET', DISCOVERY), ('GET', JWKS), ('POST', TOKEN), ('POST', REVOCATION)):
            raise AuthError('invalid_http_method')
        body = None if form is None else urlencode(form).encode('ascii')
        if body is not None and len(body) > MAX_RECORD:
            raise AuthError('request_size')
        connection = http.client.HTTPSConnection('auth.openai.com', timeout=15, context=ssl.create_default_context())
        deadline = time.monotonic() + 20
        expired = threading.Event()
        live_socket = []

        def interrupt():
            expired.set()
            # shutdown interrupts makefile/header reads too; close alone can
            # leave a socket alive while HTTPResponse owns a file reference.
            sock = live_socket[0] if live_socket else connection.sock
            if sock is not None:
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            connection.close()

        watchdog = threading.Timer(20, interrupt)
        watchdog.daemon = True
        watchdog.start()
        try:
            connection.connect()
            if connection.sock is not None:
                live_socket.append(connection.sock)
            if expired.is_set() or time.monotonic() >= deadline:
                raise AuthError('transport_timeout')
            headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
            if body is not None:
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
            connection.request(method, urlsplit(url).path, body=body, headers=headers)
            response = connection.getresponse()
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise AuthError('unsupported_encoding')
            chunks = []; size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AuthError('transport_timeout')
                if connection.sock:
                    connection.sock.settimeout(min(remaining, 15))
                chunk = response.read1(min(8192, MAX_RECORD + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RECORD:
                    raise AuthError('response_size')
                chunks.append(chunk)
            if expired.is_set() or time.monotonic() >= deadline:
                raise AuthError('transport_timeout')
            return HttpResponse(response.status, b''.join(chunks))
        except (OSError, http.client.HTTPException):
            raise AuthError('transport_timeout' if expired.is_set() else 'transport_failure') from None
        finally:
            watchdog.cancel()
            connection.close()


class IdentityValidator:
    def __init__(self, transport):
        self.transport = transport
        self._keys = None
        self._keys_at = 0
        self._discovery = None
        self._last_unknown_refresh = 0

    def discovery(self):
        if self._discovery is None:
            response = self.transport.request('GET', DISCOVERY)
            if response.status != 200:
                raise AuthError('discovery_unavailable')
            doc = _json(response.body)
            if any(doc.get(k) != v for k, v in PINNED_DISCOVERY.items()):
                raise AuthError('discovery_changed')
            if doc.get('id_token_signing_alg_values_supported') != ['RS256']:
                raise AuthError('discovery_algorithm_changed')
            self._discovery = doc
        return self._discovery

    def _fetch_keys(self):
        self.discovery()
        response = self.transport.request('GET', JWKS)
        if response.status != 200:
            raise AuthError('jwks_unavailable')
        keys = _json(response.body).get('keys')
        if not isinstance(keys, list) or not 1 <= len(keys) <= 32 or any(not isinstance(k, dict) for k in keys):
            raise AuthError('invalid_jwks')
        ids = [k.get('kid') for k in keys]
        if any(not _text(k,256) for k in ids) or len(set(ids)) != len(ids):
            raise AuthError('ambiguous_jwks')
        self._keys = keys
        self._keys_at = time.monotonic()

    def verify(self, token, client_id, nonce=None):
        # Strict JSON preflight rejects duplicate claims; all cryptography is PyJWT.
        if not _text(token) or not _client(client_id):
            raise AuthError('invalid_identity')
        try:
            import jwt
            if tuple(int(n) for n in jwt.__version__.split('.')[:3]) < (2,15,1):
                raise AuthError('jwt_dependency_too_old')
            parts = token.split('.')
            if len(parts) != 3 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', p) for p in parts):
                raise AuthError('invalid_identity')
            header, claims = [_json(base64.urlsafe_b64decode(p + '=' * (-len(p)%4))) for p in parts[:2]]
            if header.get('alg') != 'RS256' or not _text(header.get('kid'),256) or any(k in header for k in ('jku','x5u','jwk','crit','b64')):
                raise AuthError('invalid_identity')
            if self._keys is None or time.monotonic()-self._keys_at >= 300:
                self._fetch_keys()
            matches = [k for k in self._keys if k['kid'] == header['kid']]
            if not matches and time.monotonic()-self._last_unknown_refresh >= 30:
                self._last_unknown_refresh = time.monotonic()
                self._fetch_keys()
                matches = [k for k in self._keys if k['kid'] == header['kid']]
            if len(matches) != 1:
                raise AuthError('unknown_signing_key')
            key = matches[0]
            if key.get('kty') != 'RSA' or key.get('alg','RS256') != 'RS256' or key.get('use','sig') != 'sig' or ('key_ops' in key and key['key_ops'] != ['verify']):
                raise AuthError('invalid_signing_key')
            if any(not _number(claims.get(k)) for k in ('exp','iat')) or ('nbf' in claims and not _number(claims['nbf'])):
                raise AuthError('invalid_identity_dates')
            if not _text(claims.get('sub'),1024) or claims['iat'] >= claims['exp']:
                raise AuthError('invalid_identity')
            public_key = jwt.PyJWK.from_dict(key, algorithm='RS256')
            claims = jwt.decode(token, public_key, algorithms=['RS256'], issuer=ISSUER,
                                audience=client_id, leeway=5,
                                options={'require':['iss','sub','aud','exp','iat'], 'enforce_minimum_key_length':True})
            if nonce is not None and (not isinstance(claims.get('nonce'), str) or not secrets.compare_digest(claims['nonce'],nonce)):
                raise AuthError('invalid_nonce')
            audience = claims['aud']
            if isinstance(audience, list) and (len(set(audience)) != len(audience) or len(audience)>1 and claims.get('azp') != client_id):
                raise AuthError('invalid_authorized_party')
            if 'azp' in claims and claims['azp'] != client_id:
                raise AuthError('invalid_authorized_party')
            return dict(issuer=ISSUER, client_id=client_id, subject=claims['sub'])
        except AuthError:
            raise
        except Exception:
            raise AuthError('invalid_identity') from None


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != {'schema','host_id','active','registrations'} or type(record['schema']) is not int or record['schema'] != 1:
        raise AuthError('invalid_record')
    try:
        host = uuid.UUID(record['host_id'][9:])
        if record['host_id'] != 'urn:uuid:'+str(host) or host.version != 4:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AuthError('invalid_host') from None
    registrations = record['registrations']
    if not isinstance(registrations,dict) or len(registrations)>32 or record['active'] is not None and record['active'] not in registrations:
        raise AuthError('invalid_record')
    for ref, item in registrations.items():
        if not isinstance(ref,str) or not re.fullmatch('[a-f0-9]{32}',ref) or not isinstance(item,dict):
            raise AuthError('invalid_registration')
        if set(item) != {'identity','tokens','generation','operation'} or item['operation'] not in (None,'refresh','sign_out') or type(item['generation']) is not int or item['generation']<1:
            raise AuthError('invalid_registration')
        identity=item['identity']
        if not isinstance(identity,dict) or set(identity) != {'issuer','client_id','subject'} or identity['issuer'] != ISSUER or not _client(identity['client_id']) or not _text(identity['subject'],1024):
            raise AuthError('invalid_registration')
        tokens=item['tokens']
        if tokens is not None:
            if not isinstance(tokens,dict) or set(tokens) != {'access_token','refresh_token','id_token','scopes','expires_at','earliest_refresh_at'}:
                raise AuthError('invalid_tokens')
            if any(not _text(tokens.get(k)) for k in ('access_token','id_token')) or tokens['refresh_token'] is not None and not _text(tokens['refresh_token']):
                raise AuthError('invalid_tokens')
            if not isinstance(tokens['scopes'],list) or any(s not in SCOPES.split() for s in tokens['scopes']) or len(set(tokens['scopes'])) != len(tokens['scopes']) or any(not _number(tokens[k]) for k in ('expires_at','earliest_refresh_at')):
                raise AuthError('invalid_tokens')
    _bytes(record)
    return record


class DPAPIVault:
    """Windows-only installation-local vault, outside restorable workspace state.

    Bootstrap must be the original installation app-data root, never a selected
    workspace. A missing record is never recreated except through explicit
    ``initialize_host``. ACL hardening and DPAPI require Windows validation.
    """
    def __init__(self, bootstrap):
        root=Path(bootstrap)
        if not root.is_absolute():
            raise AuthError('absolute_bootstrap_required')
        if '..' in root.parts:
            raise AuthError('invalid_bootstrap')
        self.directory=root/'credentials'/'chatgpt-oauth-v1'
        self.path=self.directory/'accounts.dpapi'
        self._thread_lock=threading.RLock()

    def _windows(self):
        if sys.platform != 'win32':
            raise AuthError('windows_dpapi_required')

    @staticmethod
    def _check_path(path):
        try:
            info=path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise AuthError('vault_reparse_point')

    def _prepare(self):
        self._windows()
        for ancestor in (self.directory, *self.directory.parents):
            self._check_path(ancestor)
        # Restrict DACL to current user using their actual process-token SID.
        import ctypes
        from ctypes import wintypes
        adv=ctypes.WinDLL('advapi32',use_last_error=True)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        handle=wintypes.HANDLE(); size=wintypes.DWORD()
        adv.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        adv.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
        adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
        adv.SetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p]
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        sid=wintypes.LPWSTR(); descriptor=ctypes.c_void_p()
        try:
            if not adv.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(handle)):
                raise AuthError('vault_acl_failed')
            adv.GetTokenInformation(handle,1,None,0,ctypes.byref(size))
            data=ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(handle,1,data,size,ctypes.byref(size)):
                raise AuthError('vault_acl_failed')
            sid_pointer=ctypes.cast(data,ctypes.POINTER(ctypes.c_void_p))[0]
            if not adv.ConvertSidToStringSidW(sid_pointer,ctypes.byref(sid)):
                raise AuthError('vault_acl_failed')
            if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;OICI;FA;;;'+sid.value+')',1,ctypes.byref(descriptor),None):
                raise AuthError('vault_acl_failed')
            self.directory.mkdir(parents=True,exist_ok=True)
            for p in (self.directory, self.path, self.directory/'vault.lock'):
                self._check_path(p)
                if p.exists():
                    if not adv.SetFileSecurityW(str(p),0x80000004,descriptor):
                        raise AuthError('vault_acl_failed')
        finally:
            if descriptor:kernel.LocalFree(descriptor)
            if sid:kernel.LocalFree(sid)
            if handle:kernel.CloseHandle(handle)

    @contextmanager
    def lock(self):
        self._prepare()
        import msvcrt
        with self._thread_lock:
            with (self.directory/'vault.lock').open('a+b') as stream:
                stream.seek(0,2)
                if stream.tell()==0:stream.write(b'0');stream.flush()
                stream.seek(0)
                deadline=time.monotonic()+30
                while True:
                    try:
                        msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                        break
                    except OSError:
                        if time.monotonic()>=deadline:raise AuthError('vault_busy') from None
                        time.sleep(.05)
                try:yield
                finally:
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

    def load(self):
        self._windows()
        self._check_path(self.path)
        if not self.path.exists():return None
        if self.path.is_symlink() or self.path.stat().st_size>MAX_RECORD:
            raise AuthError('invalid_vault')
        from quantlab.desktop_runtime import CredentialVault
        try:
            raw=CredentialVault._crypt(self.path.read_bytes(),decrypt=True)
            return _validate_record(_json(raw))
        except Exception:
            raise AuthError('vault_read_failed') from None

    def save(self,record):
        self._windows()
        raw=_bytes(_validate_record(record))
        from quantlab.desktop_runtime import CredentialVault, atomic_write
        try:
            encrypted=CredentialVault._crypt(raw)
            if len(encrypted)>MAX_RECORD:raise AuthError('record_size')
            atomic_write(self.path,encrypted)
        except Exception:
            raise AuthError('vault_write_failed') from None


@dataclass(repr=False)
class _Pending:
    state: str
    nonce: str
    verifier: str
    redirect: str
    deadline: float
    registration: str | None
    identity: dict | None
    listener: object


class LoopbackListener:
    """A tiny bounded HTTP/1.x callback listener; no access logs or browser assets."""
    def __init__(self, callback):
        self.callback=callback
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            self.socket.bind(('127.0.0.1',0));self.socket.listen(4)
            self.port=self.socket.getsockname()[1]
        except Exception:
            self.socket.close();raise
    def close(self):
        self.socket.close()
    def poll(self,timeout=.1):
        self.socket.settimeout(min(max(timeout,0),.2))
        try:connection,peer=self.socket.accept()
        except (TimeoutError,BlockingIOError):return
        with connection:
            connection.settimeout(1)
            raw=b'';deadline=time.monotonic()+2
            accepted=False
            try:
                while b'\r\n\r\n' not in raw:
                    if len(raw)>=8192 or time.monotonic()>deadline:raise AuthError('callback_size')
                    part=connection.recv(min(1024,8192-len(raw)))
                    if not part:raise AuthError('invalid_callback')
                    raw+=part
                head,body=raw.split(b'\r\n\r\n',1)
                lines=head.decode('ascii').split('\r\n')
                method,target,version=lines[0].split(' ')
                if version not in ('HTTP/1.0','HTTP/1.1') or body:raise AuthError('invalid_callback')
                headers={}
                for line in lines[1:]:
                    key,sep,value=line.partition(':');key=key.lower()
                    if not sep or key in headers or line[:1].isspace():raise AuthError('invalid_callback')
                    headers[key]=value.strip()
                if 'transfer-encoding' in headers or headers.get('content-length','0')!='0':raise AuthError('invalid_callback')
                self.callback(method,target,headers.get('host',''),peer[0]);accepted=True
            except Exception:
                pass
            message=b'You may close this window.' if accepted else b'Authorization callback rejected.'
            response=(b'HTTP/1.1 '+(b'200 OK' if accepted else b'400 Bad Request')+b'\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src \'none\'\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\nContent-Length: '+str(len(message)).encode()+b'\r\n\r\n'+message)
            try:connection.sendall(response)
            except OSError:pass


class AuthSession:
    def __init__(self,vault,transport=None,*,listener_factory=LoopbackListener):
        self.vault=vault
        self.transport=transport if transport is not None else OfficialTransport()
        self.validator=IdentityValidator(self.transport)
        self._listener_factory=listener_factory
        self._pending=None
        self._mutex=threading.RLock()
        self._commit_mutex=threading.Lock()
        self.state='disconnected'
        self.active_registration=None
        self._cancel=threading.Event()

    def __reduce_ex__(self,protocol):
        raise TypeError('AuthSession cannot cross process boundaries')

    def initialize_host(self):
        """Explicit first-install/recovery action; never silently regenerate at startup."""
        with self.vault.lock():
            record=self.vault.load()
            if record is None:
                record=dict(schema=1,host_id='urn:uuid:'+str(uuid.uuid4()),active=None,registrations={})
                self.vault.save(record)
            return _validate_record(record)['host_id']

    def _load(self):
        record=self.vault.load()
        if record is None:raise AuthError('host_initialization_required')
        return _validate_record(record)

    def begin(self,registration=None):
        with self._mutex:
            if self._pending is not None:raise AuthError('authorization_busy')
            # Host setup/recovery is a separate explicit operation. Never infer
            # that a missing record means a new installation.
            with self.vault.lock():
                record=self.vault.load()
                if record is None:
                    raise AuthError('host_initialization_required')
                _validate_record(record)
                selected=record['registrations'].get(registration) if registration else None
                if registration and selected is None:raise AuthError('unknown_registration')
                self.active_registration=record['active']
            try:listener=self._listener_factory(self.accept_callback)
            except Exception:raise AuthError('callback_bind_failed') from None
            self._cancel.clear()
            pending=_Pending(secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(64),
                'http://127.0.0.1:'+str(listener.port)+'/auth/callback',time.monotonic()+600,registration,
                None if selected is None else selected['identity'].copy(),listener)
            self._pending=pending;self.state='authorizing'
            params=dict(client_id=DYNAMIC_CLIENT if selected is None else selected['identity']['client_id'],
                ext_agent_host_id=record['host_id'],response_type='code',redirect_uri=pending.redirect,scope=SCOPES,
                resource=RESOURCE,state=pending.state,nonce=pending.nonce,code_challenge_method='S256',
                code_challenge=pkce_challenge(pending.verifier))
            if selected is None:params['agent_name_hint']='MarkAuto QuantLab'
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
            client=query.get('client_id',None if pending.identity is None else pending.identity['client_id'])
            if not _client(client) or pending.identity and client!=pending.identity['client_id']:
                raise AuthError('invalid_client_id')
            if not _text(query.get('code'),4096):raise AuthError('invalid_code')
            # Consume before any exchange, including failures. No replay of a code.
            pending.listener.close();self._pending=None;self.state='validating'
            try:
                response=self.transport.request('POST',TOKEN,form=dict(grant_type='authorization_code',client_id=client,
                    code=query['code'],code_verifier=pending.verifier,redirect_uri=pending.redirect,resource=RESOURCE))
                if response.status!=200:raise AuthError('code_exchange_failed')
                data=_json(response.body)
                identity=self.validator.verify(data.get('id_token'),client,pending.nonce)
                if pending.identity is not None and identity!=pending.identity:raise AuthError('account_mismatch')
                tokens=self._tokens(data)
                if self._cancel.is_set() or time.monotonic()>=pending.deadline:raise AuthError('authorization_cancelled')
                with self.vault.lock():
                    if self._cancel.is_set() or time.monotonic()>=pending.deadline:
                        raise AuthError('authorization_cancelled')
                    record=self._load()
                    ref=pending.registration or uuid.uuid4().hex
                    old=record['registrations'].get(ref)
                    if pending.registration and (old is None or old['identity']!=identity):raise AuthError('registration_changed')
                    # A new attempt must not alias an already saved registration.
                    if not pending.registration and any(r['identity']==identity for r in record['registrations'].values()):raise AuthError('registration_already_saved')
                    record['registrations'][ref]=dict(identity=identity,tokens=tokens,generation=1 if old is None else old['generation']+1,operation=None)
                    record['active']=ref
                    with self._commit_mutex:
                        if self._cancel.is_set() or time.monotonic()>=pending.deadline:
                            raise AuthError('authorization_cancelled')
                        self.vault.save(_validate_record(record))
                        self.active_registration=ref;self.state=self._state(tokens)
                return ref
            except Exception:
                self.state='cancelled' if self._cancel.is_set() else 'authorization_failed'
                raise AuthError(self.state) from None

    def _tokens(self,data,previous=None):
        if data.get('token_type')!='Bearer' or not _text(data.get('access_token')):
            raise AuthError('invalid_token_response')
        scope=data.get('scope')
        if not isinstance(scope,str) or len(scope)>1024:
            raise AuthError('invalid_scopes')
        scopes=scope.split(' ')
        if not scopes or any(s not in SCOPES.split() for s in scopes) or len(set(scopes))!=len(scopes) or 'openid' not in scopes:
            raise AuthError('invalid_scopes')
        expires=data.get('expires_in');earliest=data.get('earliest_refresh_at',0)
        if not _number(expires) or not 0<expires<=86400 or not _number(earliest):raise AuthError('invalid_expiry')
        refresh=data.get('refresh_token')
        if 'offline_access' in scopes and not _text(refresh):raise AuthError('missing_refresh_token')
        if refresh is not None and not _text(refresh):raise AuthError('invalid_refresh_token')
        id_token=data.get('id_token',None if previous is None else previous['id_token'])
        if not _text(id_token):raise AuthError('missing_id_token')
        return dict(access_token=data['access_token'],refresh_token=refresh,id_token=id_token,scopes=scopes,
                    expires_at=time.time()+expires,earliest_refresh_at=earliest)

    @staticmethod
    def _state(tokens):
        if time.time() >= tokens['expires_at']-5:
            return 'refresh_required'
        return 'plan_ready' if PLAN_SCOPES<=set(tokens['scopes']) else 'identity_only'

    def status_summary(self):
        """One local, locked snapshot for account UI after restart.

        Returns only opaque references and derived status. No implicit host
        initialization, refresh, token resolution or network requests. Invalid
        vaults fail closed rather than appearing to be a new installation.
        This does not change the in-memory authorization-attempt state.
        """
        with self.vault.lock():
            record=self.vault.load()
            if record is None:
                return {'registrations': [], 'active_registration': None,
                        'state': 'host_initialization_required'}
            record=_validate_record(record)
            summaries=[]
            active_state='disconnected'
            for ref,row in record['registrations'].items():
                state=('reauthorization_required' if row['operation'] or row['tokens'] is None
                       else self._state(row['tokens']))
                summaries.append({'registration': ref, 'state': state})
                if ref==record['active']:
                    active_state=state
            return {'registrations': summaries, 'active_registration': record['active'],
                    'state': active_state}

    def registrations(self):
        """Local opaque references/status only. Never exposes ID claims or tokens."""
        with self.vault.lock():
            record=self._load()
            return [{'registration':ref,'state':'reauthorization_required' if row['operation'] or row['tokens'] is None else self._state(row['tokens'])}
                    for ref,row in record['registrations'].items()]

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
