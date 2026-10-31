"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

from quantlab.assistant.domain.auth_protocol import AuthError
from quantlab.assistant.domain.auth_protocol import SCOPES
from quantlab.assistant.domain.auth_protocol import _number
from quantlab.assistant.domain.auth_protocol import _text
from datetime import datetime
import re
from datetime import timezone


def _parsed_tokens(data, previous=None):
    token_type = data.get('token_type')
    if not isinstance(token_type, str) or token_type.lower() != 'bearer' or (not _text(data.get('access_token'))):
        raise AuthError('invalid_token_response')
    scope = data.get('scope')
    if not isinstance(scope, str) or len(scope) > 1024:
        raise AuthError('invalid_scopes')
    scopes = scope.split(' ')
    if not scopes or any((s not in SCOPES.split() for s in scopes)) or len(set(scopes)) != len(scopes) or ('openid' not in scopes):
        raise AuthError('invalid_scopes')
    expires = data.get('expires_in')
    earliest = data.get('earliest_refresh_at', 0)
    if isinstance(earliest, str):
        if not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,9})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', earliest):
            raise AuthError('invalid_expiry')
        try:
            stamp = datetime.fromisoformat(earliest.replace('Z', '+00:00'))
            delta = stamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
            earliest = delta.days * 86400 + delta.seconds + delta.microseconds // 1000 / 1000
        except (ValueError, OverflowError):
            raise AuthError('invalid_expiry') from None
    if not _number(expires) or not 0 < expires <= 86400 or (not _number(earliest)):
        raise AuthError('invalid_expiry')
    refresh = data.get('refresh_token')
    if 'offline_access' in scopes and (not _text(refresh)):
        raise AuthError('missing_refresh_token')
    if refresh is not None and (not _text(refresh)):
        raise AuthError('invalid_refresh_token')
    id_token = data.get('id_token', None if previous is None else previous['id_token'])
    if not _text(id_token):
        raise AuthError('missing_id_token')
    return dict(access_token=data['access_token'], refresh_token=refresh, id_token=id_token, scopes=scopes, expires_in=expires, earliest_refresh_at=earliest)
