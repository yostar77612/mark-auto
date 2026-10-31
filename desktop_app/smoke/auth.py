"""Offline smoke auth; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations

from pathlib import Path
import quantlab.assistant.adapters.chatgpt.identity as _auth_identity
import quantlab.assistant.domain.auth_protocol as _auth_auth_protocol


def _auth_smoke_dependencies():
    """Offline synthetic packaging proof; no host registration, vault or model calls."""
    import json
    import socket
    import time
    import jwt
    import cffi
    import pycparser
    import cryptography
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends.openssl.backend import backend
    from quantlab.assistant.adapters.chatgpt.provenance import implementation_provenance

    def deny_network(*args, **kwargs):
        raise RuntimeError('Network forbidden in synthetic auth packaging smoke')

    versions = {'PyJWT': jwt.__version__, 'cryptography': cryptography.__version__, 'cffi': cffi.__version__, 'pycparser': pycparser.__version__}
    expected = {'PyJWT': '2.15.1', 'cryptography': '50.0.2', 'cffi': '2.1.1', 'pycparser': '3.11'}
    if versions != expected or 'OpenSSL 4.0.3' not in backend.openssl_version_text():
        raise ValueError('Auth packaging dependency mismatch')
    before = set(Path.cwd().iterdir())
    network_functions = {name: getattr(socket, name) for name in ('socket', 'create_connection', 'getaddrinfo')}
    try:
        for name in network_functions:
            setattr(socket, name, deny_network)
        provenance = implementation_provenance()
        parsed = pycparser.CParser().parse('typedef unsigned long size_t; struct sample { int value; };')
        ffi = cffi.FFI()
        ffi.cdef('struct sample { int value; };')
        if len(parsed.ext) != 2 or ffi.new('struct sample *', {'value': 17}).value != 17:
            raise ValueError('Parser or native CFFI packaging failed')
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), kid='packaging-fixture', alg='RS256', use='sig')
        claims = dict(
            iss=_auth_auth_protocol.ISSUER,
            sub='packaging-fixture',
            aud='fixture-client',
            nonce='fixture-nonce',
            iat=int(time.time()),
            exp=int(time.time()) + 60,
        )
        token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'packaging-fixture'})

        class FixtureTransport:
            def request(self, method, url, *, form=None):
                if method != 'GET' or form is not None:
                    raise ValueError('Unexpected synthetic auth operation')
                if url == _auth_auth_protocol.DISCOVERY:
                    value = dict(_auth_auth_protocol.PINNED_DISCOVERY, id_token_signing_alg_values_supported=['RS256'])
                elif url == _auth_auth_protocol.JWKS:
                    value = {'keys': [jwk]}
                else:
                    raise ValueError('Unexpected synthetic auth endpoint')
                return _auth_auth_protocol.HttpResponse(200, json.dumps(value).encode('utf-8'))

        validator = _auth_identity.IdentityValidator(FixtureTransport())
        identity = validator.verify(token, 'fixture-client', 'fixture-nonce')
        if identity.get('subject') != 'packaging-fixture':
            raise ValueError('Synthetic identity validation failed')
        for client, nonce in [('different-client', 'fixture-nonce'), ('fixture-client', 'wrong-nonce')]:
            try:
                validator.verify(token, client, nonce)
            except _auth_auth_protocol.AuthError:
                pass
            else:
                raise ValueError('Identity binding failure accepted')
        try:
            jwt.decode(token, jwt.PyJWK.from_dict(jwk), algorithms=['HS256'], issuer=_auth_auth_protocol.ISSUER, audience='fixture-client')
        except jwt.InvalidAlgorithmError:
            pass
        else:
            raise ValueError('JWT algorithm confusion accepted')
    finally:
        for name, function in network_functions.items():
            setattr(socket, name, function)
    if set(Path.cwd().iterdir()) != before:
        raise ValueError('Auth packaging parser wrote into working directory')
    return {
        'status': 'passed',
        'source_type': 'synthetic',
        'network_used': False,
        'versions': versions,
        'native_openssl': backend.openssl_version_text(),
        'parser_and_cffi': True,
        'rs256_identity_binding': True,
        'implementation_provenance': provenance,
        'real_oauth_status': 'not_verified',
        'real_model_status': 'not_verified',
        'scope': 'offline packaging only; not an account grant or actual model verification',
    }
