"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from dataclasses import field
import hashlib
import json
import math
import re
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


PINNED_DISCOVERY = dict(issuer=ISSUER, authorization_endpoint=AUTHORIZE, token_endpoint=TOKEN, revocation_endpoint=REVOCATION, jwks_uri=JWKS)


MAX_RECORD = 65536


TERMINAL_REFRESH_ERRORS = frozenset(
    ('invalid_grant', 'invalid_refresh_token', 'token_expired', 'refresh_token_expired', 'refresh_token_invalidated', 'refresh_token_reused')
)


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
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(AuthError('invalid_json')))
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


def _validate_record(record):
    base = {'schema', 'host_id', 'active', 'registrations'}
    if not isinstance(record, dict) or type(record.get('schema')) is not int:
        raise AuthError('invalid_record')
    if record['schema'] == 1 and set(record) == base:
        # Read-only normalization; the next explicit write persists schema 2.
        record = {**record, 'schema': 2, 'registration_retries': {}}
    elif record['schema'] != 2 or set(record) != base | {'registration_retries'}:
        raise AuthError('invalid_record')
    try:
        host = uuid.UUID(record['host_id'][9:])
        if record['host_id'] != 'urn:uuid:' + str(host) or host.version != 4:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AuthError('invalid_host') from None
    registrations = record['registrations']
    if not isinstance(registrations, dict) or len(registrations) > 32 or record['active'] is not None and record['active'] not in registrations:
        raise AuthError('invalid_record')
    for ref, item in registrations.items():
        if not isinstance(ref, str) or not re.fullmatch('[a-f0-9]{32}', ref) or not isinstance(item, dict):
            raise AuthError('invalid_registration')
        if (
            set(item) != {'identity', 'tokens', 'generation', 'operation'}
            or item['operation'] not in (None, 'refresh', 'sign_out')
            or type(item['generation']) is not int
            or item['generation'] < 1
        ):
            raise AuthError('invalid_registration')
        identity = item['identity']
        if (
            not isinstance(identity, dict)
            or set(identity) != {'issuer', 'client_id', 'subject'}
            or identity['issuer'] != ISSUER
            or not _client(identity['client_id'])
            or not _text(identity['subject'], 1024)
        ):
            raise AuthError('invalid_registration')
        tokens = item['tokens']
        if tokens is not None:
            if not isinstance(tokens, dict) or set(tokens) != {'access_token', 'refresh_token', 'id_token', 'scopes', 'expires_at', 'earliest_refresh_at'}:
                raise AuthError('invalid_tokens')
            if (
                any(not _text(tokens.get(k)) for k in ('access_token', 'id_token'))
                or tokens['refresh_token'] is not None
                and not _text(tokens['refresh_token'])
            ):
                raise AuthError('invalid_tokens')
            if (
                not isinstance(tokens['scopes'], list)
                or any(s not in SCOPES.split() for s in tokens['scopes'])
                or len(set(tokens['scopes'])) != len(tokens['scopes'])
                or any(not _number(tokens[k]) for k in ('expires_at', 'earliest_refresh_at'))
            ):
                raise AuthError('invalid_tokens')
    retries = record['registration_retries']
    if not isinstance(retries, dict) or len(retries) > 32:
        raise AuthError('invalid_registration_retry')
    clients = {row['identity']['client_id'] for row in registrations.values()}
    for ref, retry in retries.items():
        if (
            not isinstance(ref, str)
            or not re.fullmatch('[a-f0-9]{32}', ref)
            or ref in registrations
            or not isinstance(retry, dict)
            or set(retry) != {'client_id'}
            or not _client(retry['client_id'])
            or retry['client_id'] in clients
        ):
            raise AuthError('invalid_registration_retry')
        clients.add(retry['client_id'])
    _bytes(record)
    return record
