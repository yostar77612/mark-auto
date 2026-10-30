"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

from quantlab.assistant.domain.auth_protocol import AuthError
from quantlab.assistant.domain.auth_protocol import DISCOVERY
from quantlab.assistant.domain.auth_protocol import HttpResponse
from quantlab.assistant.domain.auth_protocol import ISSUER
from quantlab.assistant.domain.auth_protocol import JWKS
from quantlab.assistant.domain.auth_protocol import MAX_RECORD
from quantlab.assistant.domain.auth_protocol import PINNED_DISCOVERY
from quantlab.assistant.domain.auth_protocol import REVOCATION
from quantlab.assistant.domain.auth_protocol import TOKEN
from quantlab.assistant.domain.auth_protocol import _client
from quantlab.assistant.domain.auth_protocol import _json
from quantlab.assistant.domain.auth_protocol import _number
from quantlab.assistant.domain.auth_protocol import _text
import base64
import http.client
import re
import secrets
import socket
import ssl
import threading
import time
from urllib.parse import urlencode
from urllib.parse import urlsplit


def official_tls_context():
    """Verified TLS context anchored only on trusted Windows ROOT certificates.

    ssl.create_default_context() also loads the Windows intermediate (CA) store
    as anchors; a stale expired cross-signed intermediate there (e.g. ISRG Root
    X2) makes OpenSSL reject a chain the server sends correctly. Verification,
    hostname checking and TLS 1.2+ stay mandatory; only the anchor set shrinks.
    """
    enum = getattr(ssl, 'enum_certificates', None)
    if enum is None:
        return ssl.create_default_context()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    loaded = 0
    try:
        for der, encoding, trust in enum('ROOT'):
            if encoding != 'x509_asn' or not (trust is True or '1.3.6.1.5.5.7.3.1' in trust):
                continue
            try:
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
                loaded += 1
            except ssl.SSLError:
                continue
    except OSError:
        loaded = 0
    return context if loaded else ssl.create_default_context()


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
        connection = http.client.HTTPSConnection('auth.openai.com', timeout=15, context=official_tls_context())
        deadline = time.monotonic() + 20
        expired = threading.Event()
        live_socket = []

        def interrupt():
            expired.set()
            # shutdown interrupts makefile/header reads too; close alone can
            # leave a socket alive while HTTPResponse owns a file reference.
            sock = live_socket[0] if live_socket else connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
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
            chunks = []
            size = 0
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
        if any(not _text(k, 256) for k in ids) or len(set(ids)) != len(ids):
            raise AuthError('ambiguous_jwks')
        self._keys = keys
        self._keys_at = time.monotonic()

    def verify(self, token, client_id, nonce=None):
        # Strict JSON preflight rejects duplicate claims; all cryptography is PyJWT.
        if not _text(token) or not _client(client_id):
            raise AuthError('invalid_identity')
        try:
            import jwt

            if tuple(int(n) for n in jwt.__version__.split('.')[:3]) < (2, 15, 1):
                raise AuthError('jwt_dependency_too_old')
            parts = token.split('.')
            if len(parts) != 3 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', p) for p in parts):
                raise AuthError('invalid_identity')
            header, claims = [_json(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))) for p in parts[:2]]
            if header.get('alg') != 'RS256' or not _text(header.get('kid'), 256) or any(k in header for k in ('jku', 'x5u', 'jwk', 'crit', 'b64')):
                raise AuthError('invalid_identity')
            if self._keys is None or time.monotonic() - self._keys_at >= 300:
                self._fetch_keys()
            matches = [k for k in self._keys if k['kid'] == header['kid']]
            if not matches and time.monotonic() - self._last_unknown_refresh >= 30:
                self._last_unknown_refresh = time.monotonic()
                self._fetch_keys()
                matches = [k for k in self._keys if k['kid'] == header['kid']]
            if len(matches) != 1:
                raise AuthError('unknown_signing_key')
            key = matches[0]
            if (
                key.get('kty') != 'RSA'
                or key.get('alg', 'RS256') != 'RS256'
                or key.get('use', 'sig') != 'sig'
                or ('key_ops' in key and key['key_ops'] != ['verify'])
            ):
                raise AuthError('invalid_signing_key')
            if any(not _number(claims.get(k)) for k in ('exp', 'iat')) or ('nbf' in claims and not _number(claims['nbf'])):
                raise AuthError('invalid_identity_dates')
            if not _text(claims.get('sub'), 1024) or claims['iat'] >= claims['exp']:
                raise AuthError('invalid_identity')
            public_key = jwt.PyJWK.from_dict(key, algorithm='RS256')
            claims = jwt.decode(
                token,
                public_key,
                algorithms=['RS256'],
                issuer=ISSUER,
                audience=client_id,
                leeway=5,
                options={'require': ['iss', 'sub', 'aud', 'exp', 'iat'], 'enforce_minimum_key_length': True},
            )
            if nonce is not None and (not isinstance(claims.get('nonce'), str) or not secrets.compare_digest(claims['nonce'], nonce)):
                raise AuthError('invalid_nonce')
            audience = claims['aud']
            if isinstance(audience, list) and (len(set(audience)) != len(audience) or len(audience) > 1 and claims.get('azp') != client_id):
                raise AuthError('invalid_authorized_party')
            if 'azp' in claims and claims['azp'] != client_id:
                raise AuthError('invalid_authorized_party')
            return dict(issuer=ISSUER, client_id=client_id, subject=claims['sub'])
        except AuthError:
            raise
        except Exception:
            raise AuthError('invalid_identity') from None
