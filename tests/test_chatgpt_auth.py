"""Frozen A1–A6 contract. Offline fixture keys, fake transport/vault/listener only."""

import quantlab.assistant.adapters.chatgpt.identity as _auth_identity
import quantlab.assistant.adapters.chatgpt.loopback as _auth_loopback
import quantlab.assistant.adapters.chatgpt.vault as _auth_vault
import quantlab.assistant.domain.auth_protocol as _auth_auth_protocol
import base64
import copy
import json
import importlib.util
import tempfile
from pathlib import Path
import pickle
import threading
import time
import unittest
from contextlib import contextmanager
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

OPTIONAL_AUTH_DEPS = all(importlib.util.find_spec(name) is not None for name in ('jwt', 'cryptography'))
if OPTIONAL_AUTH_DEPS:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
import quantlab.assistant.adapters.chatgpt.auth as a


class FakeVault:
    """TEST ONLY: in-memory vault, never a production plaintext fallback."""

    def __init__(self):
        self.record = None
        self.mutex = threading.RLock()
        self.writes = 0
        self.fail_at = None

    @contextmanager
    def lock(self):
        with self.mutex:
            yield

    def load(self):
        return copy.deepcopy(self.record)

    def save(self, record):
        self.writes += 1
        if self.writes == self.fail_at:
            raise OSError('fixture persistence failure')
        self.record = copy.deepcopy(record)


class FakeListener:
    def __init__(self, callback):
        self.callback = callback
        self.port = 1455
        self.closed = False

    def close(self):
        self.closed = True

    def poll(self, timeout=0):
        pass


class FakeTransport:
    def __init__(self, owner):
        self.owner = owner
        self.calls = []
        self.refresh_error = None
        self.revocation_status = 200
        self.jwks_calls = 0

    def request(self, method, url, *, form=None):
        self.calls.append((method, url, copy.deepcopy(form)))
        if url == _auth_auth_protocol.DISCOVERY:
            value = dict(_auth_auth_protocol.PINNED_DISCOVERY, id_token_signing_alg_values_supported=['RS256'])
        elif url == _auth_auth_protocol.JWKS:
            self.jwks_calls += 1
            value = {'keys': [self.owner.jwk]}
        elif url == _auth_auth_protocol.REVOCATION:
            return _auth_auth_protocol.HttpResponse(self.revocation_status, b'')
        elif url == _auth_auth_protocol.TOKEN:
            if form['grant_type'] == 'refresh_token' and self.refresh_error:
                if isinstance(self.refresh_error, Exception):
                    raise self.refresh_error
                return _auth_auth_protocol.HttpResponse(*self.refresh_error)
            self.owner.rotation += form['grant_type'] == 'refresh_token'
            value = self.owner.tokens(form['client_id'])
        else:
            raise AssertionError('Unexpected endpoint')
        return _auth_auth_protocol.HttpResponse(200, json.dumps(value).encode())


@unittest.skipUnless(OPTIONAL_AUTH_DEPS, 'optional desktop auth dependencies: PyJWT[crypto] required')
class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key())), kid='fixture', alg='RS256', use='sig')

    def setUp(self):
        self.vault = FakeVault()
        self.transport = FakeTransport(self)
        self.rotation = 0
        self.claim_changes = {}
        self.scope = _auth_auth_protocol.SCOPES
        self.session = self.new_session()

    def new_session(self):
        return a.AuthSession(self.vault, self.transport, listener_factory=FakeListener)

    def tokens(self, client):
        claims = dict(
            iss=_auth_auth_protocol.ISSUER,
            sub='fixture-user',
            aud=client,
            exp=int(time.time()) + 3600,
            iat=int(time.time()),
            nonce=self.query['nonce'][0],
            email='same@example.invalid',
        )
        claims.update(self.claim_changes)
        return dict(
            access_token='fixture-access-' + str(self.rotation),
            refresh_token='fixture-refresh-' + str(self.rotation),
            id_token=jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'fixture'}),
            token_type='Bearer',
            expires_in=3600,
            scope=self.scope,
            earliest_refresh_at=0,
        )

    def begin(self, registration=None):
        self.session.initialize_host()
        url = self.session.begin(registration)
        self.query = parse_qs(urlsplit(url).query)
        return url

    def callback(self, **changes):
        query = dict(state=self.query['state'][0], code='fixture-code', client_id='fixture-client')
        query.update(changes)
        query = {k: v for k, v in query.items() if v is not None}
        return self.session.accept_callback('GET', '/auth/callback?' + urlencode(query), '127.0.0.1:1455', '127.0.0.1')

    def connect(self):
        self.begin()
        self.callback()
        return self.session.active_registration

    def test_a1_pkce_vector_and_inert_constructor(self):
        self.assertEqual(_auth_auth_protocol.pkce_challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.vault.record)
        self.begin()
        old = self.query
        self.session.cancel()
        self.begin()
        for key in ('state', 'nonce', 'code_challenge'):
            self.assertNotEqual(old[key], self.query[key])

    def test_a2_reject_wrong_state_without_exchange(self):
        self.begin()
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback(state='wrong')
        self.assertEqual(self.transport.calls, [])
        self.callback()
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback()

    def test_a2_callback_adversarial_matrix(self):
        for method, path, host, peer in [
            ('POST', '/auth/callback?state=x', '127.0.0.1:1455', '127.0.0.1'),
            ('GET', '/wrong?state=x', '127.0.0.1:1455', '127.0.0.1'),
            ('GET', '/auth/callback?state=x', 'localhost:1455', '127.0.0.1'),
            ('GET', '/auth/callback?state=x', '127.0.0.1:1455', '10.0.0.1'),
            ('GET', '/auth/callback?state=%GG', '127.0.0.1:1455', '127.0.0.1'),
            ('GET', '/auth/callback?state=x&state=y', '127.0.0.1:1455', '127.0.0.1'),
        ]:
            with self.subTest(path=path, method=method, host=host, peer=peer):
                self.session.cancel()
                self.begin()
                with self.assertRaises(_auth_auth_protocol.AuthError):
                    self.session.accept_callback(method, path, host, peer)
        self.assertEqual(self.transport.calls, [])

    def test_a2_cancel_expiry_denial_double_click_bind_failure(self):
        self.begin()
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.begin()
        self.session.cancel()
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback()
        self.begin()
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback(error='access_denied', code=None)
        self.assertEqual(self.session.state, 'cancelled')
        self.begin()
        self.session._pending.deadline = 0
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback()
        self.assertEqual(self.session.state, 'timeout')
        self.assertEqual(self.transport.calls, [])
        with patch.object(self.session, '_listener_factory', side_effect=OSError('bind')):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                self.session.begin()
        self.assertIsNone(self.session._pending)

    def test_a3_initial_and_returning_registration(self):
        self.begin()
        for client in (None, _auth_auth_protocol.DYNAMIC_CLIENT, 'bad client'):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                self.callback(client_id=client)
        self.callback()
        registration = self.session.active_registration
        self.begin(registration)
        self.assertNotIn('agent_name_hint', self.query)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback(client_id='other')
        self.callback(client_id=None)
        self.assertEqual(registration, self.session.active_registration)

    def make_registration_retry(self, client='retry-client'):
        self.begin()
        original = self.transport.request

        def fail_exchange(method, url, **kwargs):
            if url == _auth_auth_protocol.TOKEN:
                return _auth_auth_protocol.HttpResponse(400, b'{"error":"invalid_grant"}')
            return original(method, url, **kwargs)

        with patch.object(self.transport, 'request', side_effect=fail_exchange):
            with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'registration_retry_required'):
                self.callback(client_id=client)
        return next(ref for ref, row in self.vault.record['registration_retries'].items() if row['client_id'] == client)

    def test_schema1_migration_retains_verified_rows_and_is_read_only_until_write(self):
        ref = self.connect()
        old = copy.deepcopy(self.vault.record)
        old['schema'] = 1
        old.pop('registration_retries')
        self.vault.record = copy.deepcopy(old)
        migrated = _auth_auth_protocol._validate_record(old)
        self.assertEqual(migrated['schema'], 2)
        self.assertEqual(migrated['registration_retries'], {})
        self.assertEqual(migrated['registrations'], old['registrations'])
        self.assertEqual(old['schema'], 1)
        self.assertNotIn('registration_retries', old)
        writes = self.vault.writes
        self.new_session().status_summary()
        self.assertEqual(self.vault.writes, writes)
        self.assertEqual(self.vault.record, old)
        self.new_session().select(ref)
        self.assertEqual(self.vault.record, migrated)

    def test_invalid_grant_retains_only_unverified_routing_id_and_explicit_retry_reuses_it(self):
        ref = self.make_registration_retry()
        record = copy.deepcopy(self.vault.record)
        self.assertEqual(record['registrations'], {})
        self.assertIsNone(record['active'])
        self.assertEqual(record['registration_retries'][ref], {'client_id': 'retry-client'})
        self.session = self.new_session()
        summary = self.session.status_summary()
        self.assertEqual(summary['registrations'], [{'registration': ref, 'state': 'registration_retry_required'}])
        self.assertNotIn('retry-client', json.dumps(summary))
        for action in (self.session.select, self.session.access_token, self.session.refresh, self.session.sign_out):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                action(ref)
        self.assertEqual(self.vault.record, record)
        before = len(self.transport.calls)
        self.begin(ref)
        self.assertEqual(len(self.transport.calls), before)
        self.assertEqual(self.query['client_id'], ['retry-client'])
        self.assertNotIn('agent_name_hint', self.query)
        self.assertNotIn('prompt', self.query)
        self.callback(client_id=None)
        self.assertEqual(self.session.active_registration, ref)
        self.assertEqual(self.vault.record['registration_retries'], {})
        self.assertEqual(self.vault.record['registrations'][ref]['identity']['client_id'], 'retry-client')
        self.assertEqual(self.session.access_token(ref), 'fixture-access-0')

    def test_retry_never_replaces_existing_identity_or_promotes_invalid_token(self):
        active = self.connect()
        original = copy.deepcopy(self.vault.record['registrations'][active])
        retry = self.make_registration_retry()
        self.assertEqual(self.vault.record['active'], active)
        self.assertEqual(self.vault.record['registrations'][active], original)
        self.session = self.new_session()
        self.begin(retry)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback(client_id='changed-client')
        self.assertEqual(self.session.state, 'authorizing')
        self.claim_changes = {'aud': 'wrong-audience'}
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback(client_id=None)
        self.assertIn(retry, self.vault.record['registration_retries'])
        self.assertNotIn(retry, self.vault.record['registrations'])
        self.assertEqual(self.vault.record['active'], active)
        self.assertEqual(self.vault.record['registrations'][active], original)

    def test_retry_record_rejects_identity_tokens_active_alias_and_duplicate_clients(self):
        ref = self.make_registration_retry()
        base = copy.deepcopy(self.vault.record)
        for extra in ({'tokens': {}}, {'identity': {}}, {'scopes': ['chatgpt.tokens.use.direct']}):
            bad = copy.deepcopy(base)
            bad['registration_retries'][ref].update(extra)
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_auth_protocol._validate_record(bad)
        bad = copy.deepcopy(base)
        bad['active'] = ref
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_auth_protocol._validate_record(bad)
        bad = copy.deepcopy(base)
        bad['registration_retries']['f' * 32] = {'client_id': 'retry-client'}
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_auth_protocol._validate_record(bad)
        bad = copy.deepcopy(base)
        bad['registration_retries'][ref] = {'client_id': _auth_auth_protocol.DYNAMIC_CLIENT}
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_auth_protocol._validate_record(bad)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.begin(ref, enable_plan=True)

    def test_cancelled_or_failed_retry_persistence_does_not_create_identity(self):
        self.begin()
        original = self.transport.request

        def cancelled_exchange(method, url, **kwargs):
            if url == _auth_auth_protocol.TOKEN:
                self.session._cancel.set()
                return _auth_auth_protocol.HttpResponse(400, b'{"error":"invalid_grant"}')
            return original(method, url, **kwargs)

        with patch.object(self.transport, 'request', side_effect=cancelled_exchange):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                self.callback(client_id='retry-client')
        self.assertEqual(self.vault.record['registration_retries'], {})
        self.assertEqual(self.vault.record['registrations'], {})
        self.session = self.new_session()
        self.begin()
        self.vault.fail_at = self.vault.writes + 1
        with patch.object(self.transport, 'request', return_value=_auth_auth_protocol.HttpResponse(400, b'{"error":"invalid_grant"}')):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                self.callback(client_id='retry-client')
        self.assertEqual(self.vault.record['registration_retries'], {})
        self.assertEqual(self.vault.record['registrations'], {})

    def test_first_use_initializer_requires_guard_and_never_recreates_existing_host(self):
        with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'first_use_check_unavailable'):
            self.session.initialize_host(first_use_only=True)
        self.assertIsNone(self.vault.record)
        self.vault.assert_first_use = lambda: None
        host = self.session.initialize_host(first_use_only=True)
        saved = copy.deepcopy(self.vault.record)
        with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'explicit_host_recovery_required'):
            self.session.initialize_host(first_use_only=True)
        self.assertEqual(self.vault.record, saved)
        self.assertEqual(self.vault.record['host_id'], host)
        self.assertEqual(self.transport.calls, [])

    def test_first_use_guard_rejects_prior_host_control_and_partial_vault_evidence(self):
        for evidence in (
            'chatgpt-oauth-host-v1.marker',
            'chatgpt-plan-controls-v1.marker',
            'control-v1/chatgpt-plan-account-controls.sqlite',
            'control-v1/chatgpt-plan-old.sqlite3',
            'credentials/chatgpt-oauth-v1/accounts.dpapi.bak',
        ):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as tmp:
                vault = _auth_vault.DPAPIVault(str(Path(tmp)))
                vault.directory.mkdir(parents=True)
                (vault.directory / 'vault.lock').write_bytes(b'0')
                vault.assert_first_use()
                target = Path(tmp) / evidence
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'fixture')
                with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'explicit_host_recovery_required'):
                    vault.assert_first_use()
        with tempfile.TemporaryDirectory() as tmp:
            vault = _auth_vault.DPAPIVault(str(Path(tmp)))
            vault.host_marker.symlink_to(Path(tmp) / 'missing')
            with self.assertRaises(_auth_auth_protocol.AuthError):
                vault.assert_first_use()

    def test_first_use_guard_rejects_surviving_analysis_ledger_without_other_host_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = _auth_vault.DPAPIVault(str(root))
            controls = root / 'control-v1'
            controls.mkdir()
            unrelated = controls / 'other-feature.sqlite3'
            unrelated.write_bytes(b'fixture')
            vault.assert_first_use()
            ledger = controls / ('chatgpt-analysis-' + 'a' * 64 + '.sqlite3')
            ledger.write_bytes(b'prior-analysis-fixture')
            before = {path.name: path.read_bytes() for path in controls.iterdir()}
            with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'explicit_host_recovery_required'):
                vault.assert_first_use()
            self.assertFalse(vault.path.exists())
            self.assertFalse(vault.host_marker.exists())
            self.assertFalse((root / 'chatgpt-plan-controls-v1.marker').exists())
            self.assertEqual({path.name: path.read_bytes() for path in controls.iterdir()}, before)

    def test_dpapi_save_retains_nonsecret_host_history_if_credential_file_is_lost(self):
        self.session.initialize_host()
        record = copy.deepcopy(self.vault.record)
        with tempfile.TemporaryDirectory() as tmp:
            vault = _auth_vault.DPAPIVault(str(Path(tmp)))
            vault.directory.mkdir(parents=True)
            with patch.object(vault, '_windows'), patch('quantlab.desktop_runtime.CredentialVault._crypt', return_value=b'fixture-encrypted'):
                vault.save(record)
            self.assertEqual(vault.host_marker.read_bytes(), b'markauto-chatgpt-host-v1\n')
            vault.path.unlink()
            with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'explicit_host_recovery_required'):
                vault.assert_first_use()
            self.assertNotIn(record['host_id'].encode(), vault.host_marker.read_bytes())

    def test_explicit_plan_reconsent_is_never_part_of_ordinary_login(self):
        self.begin()
        self.assertNotIn('prompt', self.query)
        self.callback()
        registration = self.session.active_registration
        self.begin(registration)
        self.assertNotIn('prompt', self.query)
        self.session.cancel()
        url = self.session.begin(registration, enable_plan=True)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['prompt'], ['consent'])
        self.assertEqual(query['client_id'], ['fixture-client'])
        self.assertNotIn('agent_name_hint', query)
        self.assertNotIn('force_reconsent', query)
        self.session.cancel()
        for registration, value in ((None, True), (registration, 'yes')):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                self.session.begin(registration, enable_plan=value)

    def test_a4_invalid_signed_claim_matrix_preserves_account(self):
        registration = self.connect()
        for changes in [
            dict(iss='https://evil.invalid'),
            dict(aud='wrong'),
            dict(nonce='wrong'),
            dict(sub=''),
            dict(exp=0),
            dict(iat=int(time.time()) + 30),
            dict(nbf=int(time.time()) + 30),
            dict(exp=True),
            dict(aud=['fixture-client', 'other']),
            dict(aud=['fixture-client', 'other'], azp='other'),
        ]:
            with self.subTest(changes=changes):
                self.claim_changes = changes
                self.begin(registration)
                with self.assertRaises(_auth_auth_protocol.AuthError):
                    self.callback()
                self.assertEqual(self.session.active_registration, registration)

    def test_a4_multiple_aud_and_unknown_kid_bounded(self):
        self.claim_changes = dict(aud=['fixture-client', 'other'], azp='fixture-client')
        self.connect()
        validator = _auth_identity.IdentityValidator(self.transport)
        self.begin()
        token = jwt.encode(
            dict(iss=_auth_auth_protocol.ISSUER, sub='s', aud='fixture-client', exp=int(time.time()) + 60, iat=int(time.time()), nonce='n'),
            self.key,
            algorithm='RS256',
            headers={'kid': 'unknown'},
        )
        before = self.transport.jwks_calls
        with self.assertRaises(_auth_auth_protocol.AuthError):
            validator.verify(token, 'fixture-client', 'n')
        self.assertLessEqual(self.transport.jwks_calls - before, 2)

    def test_a4_duplicate_claims_none_hs_bad_signature(self):
        validator = _auth_identity.IdentityValidator(self.transport)
        self.begin()
        claims = dict(iss=_auth_auth_protocol.ISSUER, sub='s', aud='fixture-client', exp=int(time.time()) + 60, iat=int(time.time()), nonce='n')
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        bad = [
            jwt.encode(claims, other, algorithm='RS256', headers={'kid': 'fixture'}),
            jwt.encode(claims, 'fixture-secret' * 4, algorithm='HS256', headers={'kid': 'fixture'}),
            jwt.encode(claims, None, algorithm='none'),
        ]
        raw = json.dumps(claims)[:-1] + ',"sub":"duplicate"}'
        bad.append(jwt.api_jws.encode(raw.encode(), self.key, algorithm='RS256', headers={'kid': 'fixture'}))
        for token in bad:
            with self.assertRaises(_auth_auth_protocol.AuthError):
                validator.verify(token, 'fixture-client', 'n')

    def test_a5_identity_only_and_host_retained(self):
        self.scope = 'openid profile email'
        registration = self.connect()
        host = self.vault.record['host_id']
        self.assertEqual(self.session.state, 'identity_only')
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.access_token(registration)
        self.session.sign_out(registration)
        self.assertEqual(self.vault.record['host_id'], host)
        self.session = self.new_session()
        self.begin(registration)
        self.assertEqual(self.query['ext_agent_host_id'], [host])
        self.assertFalse(any('api.openai.com' in c[1] for c in self.transport.calls))

    def test_a6_refresh_rotation_atomic_and_serialized(self):
        registration = self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at'] = 0
        sessions = [self.new_session(), self.new_session()]
        failures = []

        def run(s):
            try:
                s.refresh(registration)
            except Exception as e:
                failures.append(e)

        threads = [threading.Thread(target=run, args=(s,)) for s in sessions]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failures, [])
        self.assertEqual(self.rotation, 1)
        stored = self.vault.record['registrations'][registration]
        self.assertEqual(stored['tokens']['refresh_token'], 'fixture-refresh-1')
        self.assertEqual(stored['generation'], 2)

    def test_a6_persistence_failure_blocks_replay(self):
        registration = self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at'] = 0
        self.vault.fail_at = self.vault.writes + 2
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.refresh(registration)
        self.vault.fail_at = None
        before = len(self.transport.calls)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.new_session().refresh(registration)
        self.assertEqual(len(self.transport.calls), before)

    def test_a6_transient_terminal_revocation(self):
        registration = self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at'] = 0
        self.transport.refresh_error = (503, b'{}')
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.refresh(registration)
        self.assertIsNotNone(self.vault.record['registrations'][registration]['tokens'])
        self.transport.refresh_error = (400, b'{"error":"invalid_grant"}')
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.refresh(registration)
        self.assertIsNone(self.vault.record['registrations'][registration]['tokens'])
        self.transport.refresh_error = None
        self.begin(registration)
        self.callback()
        self.transport.revocation_status = 503
        result = self.session.sign_out(registration)
        self.assertFalse(result)
        self.assertIsNone(self.vault.record['registrations'][registration]['tokens'])

    def test_a6_no_secret_pickle_or_repr_and_nonwindows_fails(self):
        self.connect()
        with self.assertRaises(TypeError):
            pickle.dumps(self.session)
        self.assertNotIn('fixture-access', repr(self.session))
        with patch.object(_auth_vault.sys, 'platform', 'linux'):
            vault = _auth_vault.DPAPIVault(str(Path(tempfile.gettempdir()) / 'fixture-bootstrap'))
            with self.assertRaises(_auth_auth_protocol.AuthError):
                vault.load()

    def test_a1_host_loss_requires_explicit_recovery(self):
        with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'host_initialization_required'):
            self.session.begin()
        self.assertIsNone(self.vault.record)
        self.assertEqual(self.transport.calls, [])

    def test_a2_missing_duplicate_ambiguous_oversize_callbacks(self):
        self.begin()
        state = self.query['state'][0]
        for query in (
            'code=x&client_id=fixture-client',
            'state=' + state + '&code=x&code=y&client_id=fixture-client',
            'state=' + state + '&code=x&error=access_denied&client_id=fixture-client',
            'state=' + state + '&code=x&client_id=x&client_id=y',
            'state=' + state + '&code=%FF&client_id=fixture-client',
            'state=' + state + '&code=' + ('x' * 8200),
        ):
            with self.subTest(query=query[:35]):
                with self.assertRaises(_auth_auth_protocol.AuthError):
                    self.session.accept_callback('GET', '/auth/callback?' + query, '127.0.0.1:1455', '127.0.0.1')
        self.assertEqual(self.transport.calls, [])

    def test_a2_cancel_during_exchange_never_commits(self):
        self.begin()
        entered = threading.Event()
        resume = threading.Event()
        original = self.transport.request

        def delayed(*args, **kwargs):
            if args[1] == _auth_auth_protocol.TOKEN:
                entered.set()
                resume.wait(3)
            return original(*args, **kwargs)

        self.transport.request = delayed
        failures = []

        def callback():
            try:
                self.callback()
            except _auth_auth_protocol.AuthError:
                failures.append(True)

        thread = threading.Thread(target=callback)
        thread.start()
        self.assertTrue(entered.wait(2))
        cancel = threading.Thread(target=self.session.cancel)
        cancel.start()
        self.assertTrue(self.session._cancel.wait(2))
        resume.set()
        thread.join(3)
        cancel.join(3)
        self.assertEqual(failures, [True])
        self.assertEqual(self.vault.record['registrations'], {})

    def test_a4_discovery_and_jwks_changes_fail_closed(self):
        self.begin()
        original = self.transport.request
        for changed in [
            dict(issuer='https://evil.invalid'),
            dict(jwks_uri='https://evil.invalid/key'),
            dict(token_endpoint=_auth_auth_protocol.TOKEN + '?evil'),
            dict(id_token_signing_alg_values_supported=['HS256']),
        ]:

            def request(method, url, **kwargs):
                if url == _auth_auth_protocol.DISCOVERY:
                    return _auth_auth_protocol.HttpResponse(
                        200, json.dumps(dict(_auth_auth_protocol.PINNED_DISCOVERY, id_token_signing_alg_values_supported=['RS256'], **{}) | changed).encode()
                    )
                return original(method, url, **kwargs)

            self.transport.request = request
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_identity.IdentityValidator(self.transport).discovery()
        self.transport.request = original
        duplicate = dict(self.jwk)

        def request(method, url, **kwargs):
            if url == _auth_auth_protocol.JWKS:
                return _auth_auth_protocol.HttpResponse(200, json.dumps({'keys': [duplicate, duplicate]}).encode())
            return original(method, url, **kwargs)

        self.transport.request = request
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_identity.IdentityValidator(self.transport).verify(self.tokens('fixture-client')['id_token'], 'fixture-client', self.query['nonce'][0])

    def test_a4_header_key_urls_and_duplicate_header_rejected(self):
        self.begin()
        validator = _auth_identity.IdentityValidator(self.transport)
        claims = dict(iss=_auth_auth_protocol.ISSUER, sub='s', aud='fixture-client', exp=int(time.time()) + 60, iat=int(time.time()), nonce='n')
        for field in ('jku', 'x5u', 'jwk', 'crit'):
            token = jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'fixture', field: 'https://evil.invalid'})
            with self.assertRaises(_auth_auth_protocol.AuthError):
                validator.verify(token, 'fixture-client', 'n')
        for header in (b'{"alg":"RS256","kid":"fixture","kid":"fixture"}', b'{"alg":"RS256","kid":"fixture","b64":true}'):
            altered = base64.urlsafe_b64encode(header).rstrip(b'=').decode() + '.' + token.split('.', 1)[1]
            with self.assertRaises(_auth_auth_protocol.AuthError):
                validator.verify(altered, 'fixture-client', 'n')
        self.assertEqual(self.transport.calls, [])

    def test_a5_same_email_keeps_distinct_registration(self):
        first = self.connect()
        self.begin()
        self.callback(client_id='second-client')
        second = self.session.active_registration
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.vault.record['registrations']), 2)
        self.assertEqual(self.session.select(first), 'plan_ready')
        self.assertEqual(self.session.active_registration, first)

    def test_a5_validated_subject_mismatch_never_replaces(self):
        first = self.connect()
        prior = copy.deepcopy(self.vault.record)
        self.claim_changes = {'sub': 'other-user'}
        self.begin(first)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.callback()
        self.assertEqual(self.vault.record, prior)

    def test_a6_response_scope_and_token_boundaries(self):
        self.begin()
        data = self.tokens('fixture-client')
        for changes in [
            dict(token_type='MAC'),
            dict(access_token=''),
            dict(refresh_token=None),
            dict(scope='openid openid'),
            dict(scope='openid rogue.scope'),
            dict(expires_in=True),
            dict(expires_in=0),
            dict(earliest_refresh_at=float('nan')),
            dict(access_token='x' * 16385),
        ]:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(_auth_auth_protocol.AuthError):
                    self.session._tokens(data | changes)

    def test_a6_refresh_network_ambiguity_persisted_across_restart(self):
        ref = self.connect()
        self.vault.record['registrations'][ref]['tokens']['expires_at'] = 0
        self.transport.refresh_error = OSError('fixture timeout')
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.session.refresh(ref)
        self.assertEqual(self.vault.record['registrations'][ref]['operation'], 'refresh')
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.new_session().access_token(ref)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.new_session().refresh(ref)
        self.assertEqual(self.rotation, 0)

    def test_a6_crash_barrier_prevents_transmission_and_expired_status(self):
        ref = self.connect()
        self.vault.record['registrations'][ref]['tokens']['expires_at'] = 0
        self.assertEqual(self.session.select(ref), 'refresh_required')
        before = len(self.transport.calls)
        self.vault.fail_at = self.vault.writes + 1
        with self.assertRaises(OSError):
            self.session.refresh(ref)
        self.assertEqual(len(self.transport.calls), before)
        self.vault.fail_at = None
        self.session.refresh(ref)
        self.assertEqual(self.rotation, 1)

    def test_a6_reference_contains_no_secrets_and_record_limit(self):
        ref = self.connect()
        reference = a.OAuthCredentialReference(str(Path(tempfile.gettempdir()) / 'fixture'), ref)
        raw = pickle.dumps(reference)
        for secret in (b'fixture-access', b'fixture-refresh', b'fixture-user'):
            self.assertNotIn(secret, raw)
        oversized = copy.deepcopy(self.vault.record)
        oversized['padding'] = 'x' * 65536
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_auth_protocol._validate_record(oversized)
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'x' * 65537):
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_auth_protocol._json(raw)

    def test_transport_pins_origins_methods_and_does_not_follow_redirects(self):
        transport = _auth_identity.OfficialTransport()
        with patch.object(_auth_identity.http.client, 'HTTPSConnection') as constructor:
            for url in ('https://evil.invalid/token', _auth_auth_protocol.TOKEN + '?x=1', 'http://auth.openai.com/api/accounts/oauth/token'):
                with self.assertRaises(_auth_auth_protocol.AuthError):
                    transport.request('POST', url, form={})
            with self.assertRaises(_auth_auth_protocol.AuthError):
                transport.request('GET', _auth_auth_protocol.TOKEN)
            constructor.assert_not_called()
            connection = constructor.return_value
            response = connection.getresponse.return_value
            response.status = 302
            response.getheader.return_value = 'identity'
            response.read1.return_value = b''
            result = transport.request('POST', _auth_auth_protocol.TOKEN, form={'grant_type': 'fixture'})
            self.assertEqual(result.status, 302)
            self.assertEqual(connection.request.call_count, 1)
            self.assertEqual(connection.request.call_args.args[:2], ('POST', '/api/accounts/oauth/token'))
            headers = connection.request.call_args.kwargs['headers']
            self.assertNotIn('Cookie', headers)
            self.assertNotIn('Authorization', headers)
            connection.close.assert_called_once()

    def test_transport_size_and_compression_are_bounded(self):
        with patch.object(_auth_identity.http.client, 'HTTPSConnection') as constructor:
            response = constructor.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'gzip'
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_identity.OfficialTransport().request('GET', _auth_auth_protocol.JWKS)
            response.getheader.return_value = 'identity'
            response.read1.return_value = b'x' * 65537
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_identity.OfficialTransport().request('GET', _auth_auth_protocol.JWKS)

    def test_listener_parser_with_fake_sockets_no_bind_or_network(self):
        from unittest.mock import MagicMock

        for request, expected in [
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: 127.0.0.1:1455\r\n\r\n', True),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n', False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n', False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\n\r\n', False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\n\r\nxx', False),
        ]:
            with self.subTest(expected=expected):
                listener = _auth_loopback.LoopbackListener.__new__(_auth_loopback.LoopbackListener)
                listener.socket = MagicMock()
                listener.callback = MagicMock()
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.recv.return_value = request
                listener.socket.accept.return_value = (connection, ('127.0.0.1', 12345))
                listener.poll()
                self.assertEqual(listener.callback.called, expected)
                sent = connection.sendall.call_args.args[0]
                for forbidden in (b'state=x', b'Location:', b'Set-Cookie:', b'Access-Control-Allow-Origin:'):
                    self.assertNotIn(forbidden, sent)

    def test_a5_backup_excludes_host_and_oauth_vault(self):
        import tempfile
        import zipfile
        from pathlib import Path
        from quantlab.desktop_runtime import AppPaths
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary) / 'bootstrap').ensure()
            vault = _auth_vault.DPAPIVault(str(paths.root))
            vault.directory.mkdir(parents=True)
            vault.path.write_bytes(b'fixture-encrypted-host-and-account')
            (paths.state / 'fixture.json').write_text('{}')
            archive = Path(temporary) / 'backup.zip'
            BackupManager(paths).create(archive)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {'manifest.json', 'state/fixture.json'})

    def test_a2_cancel_while_waiting_for_commit_lock(self):
        self.begin()
        waiting = threading.Event()
        release = threading.Event()
        original = self.vault.lock

        @contextmanager
        def blocked_lock():
            waiting.set()
            release.wait(3)
            with original():
                yield

        self.vault.lock = blocked_lock
        failures = []

        def callback():
            try:
                self.callback()
            except _auth_auth_protocol.AuthError:
                failures.append(True)

        thread = threading.Thread(target=callback)
        thread.start()
        self.assertTrue(waiting.wait(2))
        cancel = threading.Thread(target=self.session.cancel)
        cancel.start()
        self.assertTrue(self.session._cancel.wait(2))
        release.set()
        thread.join(3)
        cancel.join(3)
        self.assertEqual(failures, [True])
        self.assertEqual(self.vault.record['registrations'], {})

    def test_dpapi_rejects_dangling_links_and_junction_lstat_attributes(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as temporary:
            dangling = Path(temporary) / 'dangling'
            dangling.symlink_to(Path(temporary) / 'missing', target_is_directory=True)
            with self.assertRaises(_auth_auth_protocol.AuthError):
                _auth_vault.DPAPIVault._check_path(dangling)
        junction = MagicMock()
        junction.lstat.return_value = SimpleNamespace(st_mode=0o40700, st_file_attributes=0x400)
        with self.assertRaises(_auth_auth_protocol.AuthError):
            _auth_vault.DPAPIVault._check_path(junction)
        junction.stat.assert_not_called()

    def test_absolute_deadline_watchdog_interrupts_header_read(self):
        from unittest.mock import MagicMock

        watchdog = []

        def timer(interval, callback):
            self.assertEqual(interval, 20)
            watchdog.append(callback)
            return MagicMock()

        with patch.object(a.threading, 'Timer', side_effect=timer), patch.object(_auth_identity.http.client, 'HTTPSConnection') as constructor:
            connection = constructor.return_value
            response = MagicMock()
            response.status = 200
            response.getheader.return_value = 'identity'
            response.read1.return_value = b''

            def drip_headers():
                if watchdog:
                    watchdog[0]()
                    raise TimeoutError('fixture socket interrupted')
                return response

            connection.getresponse.side_effect = drip_headers
            with self.assertRaisesRegex(_auth_auth_protocol.AuthError, 'transport_timeout'):
                _auth_identity.OfficialTransport().request('GET', _auth_auth_protocol.JWKS)
            connection.sock.shutdown.assert_called_with(_auth_identity.socket.SHUT_RDWR)

    def test_cancel_after_commit_boundary_reports_connected_state(self):
        self.begin()
        entered = threading.Event()
        release = threading.Event()
        original = self.vault.save

        def blocked_save(record):
            entered.set()
            release.wait(3)
            original(record)

        self.vault.save = blocked_save
        result = []
        callback = threading.Thread(target=self.callback)
        callback.start()
        self.assertTrue(entered.wait(2))
        cancel = threading.Thread(target=lambda: result.append(self.session.cancel()))
        cancel.start()
        release.set()
        callback.join(3)
        cancel.join(3)
        self.assertEqual(result, ['plan_ready'])
        self.assertEqual(self.session.state, 'plan_ready')
        self.assertIsNotNone(self.session.active_registration)

    def test_signout_after_uncertain_rotation_cannot_confirm_remote_revocation(self):
        ref = self.connect()
        self.vault.record['registrations'][ref]['operation'] = 'refresh'
        self.assertFalse(self.session.sign_out(ref))
        self.assertIsNone(self.vault.record['registrations'][ref]['tokens'])

    def test_status_summary_reconstructs_active_from_one_local_read(self):
        ref = self.connect()
        restarted = self.new_session()
        before = len(self.transport.calls)
        with patch.object(self.vault, 'load', wraps=self.vault.load) as load:
            summary = restarted.status_summary()
            load.assert_called_once_with()
        self.assertRegex(summary['registrations'][0]['account_label'], r'^已驗證帳戶 ••••[a-f0-9]{8}（電子郵件未提供）$')
        self.assertNotIn('fixture-user', json.dumps(summary))
        self.assertNotIn('same@example.invalid', json.dumps(summary))
        self.assertEqual(
            summary,
            {
                'registrations': [{'registration': ref, 'state': 'plan_ready', 'account_label': summary['registrations'][0]['account_label']}],
                'active_registration': ref,
                'state': 'plan_ready',
            },
        )
        self.assertEqual(len(self.transport.calls), before)
        self.assertNotIn('fixture-access', json.dumps(summary))
        self.assertNotIn('fixture-user', json.dumps(summary))
        self.assertNotIn('fixture-client', json.dumps(summary))
        self.assertEqual(restarted.state, 'disconnected')

    def test_status_summary_missing_empty_expired_and_invalid_vault(self):
        self.assertEqual(self.session.status_summary(), {'registrations': [], 'active_registration': None, 'state': 'host_initialization_required'})
        self.assertIsNone(self.vault.record)
        self.session.initialize_host()
        self.assertEqual(self.session.status_summary()['state'], 'disconnected')
        ref = self.connect()
        self.vault.record['registrations'][ref]['tokens']['expires_at'] = 0
        self.assertEqual(self.new_session().status_summary()['state'], 'refresh_required')
        self.vault.record['registrations'][ref]['operation'] = 'refresh'
        self.assertEqual(self.new_session().status_summary()['state'], 'reauthorization_required')
        self.vault.record['active'] = None
        summary = self.new_session().status_summary()
        self.assertEqual(summary['state'], 'disconnected')
        self.assertIsNone(summary['active_registration'])
        self.vault.record['active'] = 'unknown-ref'
        with self.assertRaises(_auth_auth_protocol.AuthError):
            self.new_session().status_summary()
