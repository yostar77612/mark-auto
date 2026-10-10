"""Frozen A1–A6 contract. Offline fixture keys, fake transport/vault/listener only."""
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

OPTIONAL_AUTH_DEPS = all(importlib.util.find_spec(name) is not None
                         for name in ('jwt', 'cryptography'))
if OPTIONAL_AUTH_DEPS:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
import desktop_chatgpt_auth as a


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
        if url == a.DISCOVERY:
            value = dict(a.PINNED_DISCOVERY, id_token_signing_alg_values_supported=['RS256'])
        elif url == a.JWKS:
            self.jwks_calls += 1
            value = {'keys': [self.owner.jwk]}
        elif url == a.REVOCATION:
            return a.HttpResponse(self.revocation_status, b'')
        elif url == a.TOKEN:
            if form['grant_type'] == 'refresh_token' and self.refresh_error:
                if isinstance(self.refresh_error, Exception):
                    raise self.refresh_error
                return a.HttpResponse(*self.refresh_error)
            self.owner.rotation += form['grant_type'] == 'refresh_token'
            value = self.owner.tokens(form['client_id'])
        else:
            raise AssertionError('Unexpected endpoint')
        return a.HttpResponse(200, json.dumps(value).encode())


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
        self.scope = a.SCOPES
        self.session = self.new_session()
    def new_session(self):
        return a.AuthSession(self.vault, self.transport, listener_factory=FakeListener)
    def tokens(self, client):
        claims = dict(iss=a.ISSUER, sub='fixture-user', aud=client, exp=int(time.time())+3600,
                      iat=int(time.time()), nonce=self.query['nonce'][0], email='same@example.invalid')
        claims.update(self.claim_changes)
        return dict(access_token='fixture-access-'+str(self.rotation), refresh_token='fixture-refresh-'+str(self.rotation),
                    id_token=jwt.encode(claims, self.key, algorithm='RS256', headers={'kid':'fixture'}),
                    token_type='Bearer', expires_in=3600, scope=self.scope, earliest_refresh_at=0)
    def begin(self, registration=None):
        self.session.initialize_host()
        url = self.session.begin(registration)
        self.query = parse_qs(urlsplit(url).query)
        return url
    def callback(self, **changes):
        query = dict(state=self.query['state'][0], code='fixture-code', client_id='fixture-client')
        query.update(changes)
        query = {k:v for k,v in query.items() if v is not None}
        return self.session.accept_callback('GET', '/auth/callback?'+urlencode(query), '127.0.0.1:1455', '127.0.0.1')
    def connect(self):
        self.begin()
        self.callback()
        return self.session.active_registration
    def test_a1_pkce_vector_and_inert_constructor(self):
        self.assertEqual(a.pkce_challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.vault.record)
        self.begin(); old = self.query
        self.session.cancel(); self.begin()
        for key in ('state','nonce','code_challenge'):
            self.assertNotEqual(old[key], self.query[key])
    def test_a2_reject_wrong_state_without_exchange(self):
        self.begin()
        with self.assertRaises(a.AuthError): self.callback(state='wrong')
        self.assertEqual(self.transport.calls, [])
        self.callback()
        with self.assertRaises(a.AuthError): self.callback()
    def test_a2_callback_adversarial_matrix(self):
        for method, path, host, peer in [
            ('POST','/auth/callback?state=x','127.0.0.1:1455','127.0.0.1'),
            ('GET','/wrong?state=x','127.0.0.1:1455','127.0.0.1'),
            ('GET','/auth/callback?state=x','localhost:1455','127.0.0.1'),
            ('GET','/auth/callback?state=x','127.0.0.1:1455','10.0.0.1'),
            ('GET','/auth/callback?state=%GG','127.0.0.1:1455','127.0.0.1'),
            ('GET','/auth/callback?state=x&state=y','127.0.0.1:1455','127.0.0.1')]:
            with self.subTest(path=path, method=method, host=host, peer=peer):
                self.session.cancel(); self.begin()
                with self.assertRaises(a.AuthError): self.session.accept_callback(method,path,host,peer)
        self.assertEqual(self.transport.calls, [])
    def test_a2_cancel_expiry_denial_double_click_bind_failure(self):
        self.begin()
        with self.assertRaises(a.AuthError): self.session.begin()
        self.session.cancel()
        with self.assertRaises(a.AuthError): self.callback()
        self.begin()
        with self.assertRaises(a.AuthError): self.callback(error='access_denied', code=None)
        self.assertEqual(self.session.state, 'cancelled')
        self.begin()
        self.session._pending.deadline = 0
        with self.assertRaises(a.AuthError): self.callback()
        self.assertEqual(self.session.state, 'timeout')
        self.assertEqual(self.transport.calls, [])
        with patch.object(self.session, '_listener_factory', side_effect=OSError('bind')):
            with self.assertRaises(a.AuthError): self.session.begin()
        self.assertIsNone(self.session._pending)
    def test_a3_initial_and_returning_registration(self):
        self.begin()
        for client in (None, a.DYNAMIC_CLIENT, 'bad client'):
            with self.assertRaises(a.AuthError): self.callback(client_id=client)
        self.callback(); registration = self.session.active_registration
        self.begin(registration)
        self.assertNotIn('agent_name_hint', self.query)
        with self.assertRaises(a.AuthError): self.callback(client_id='other')
        self.callback(client_id=None)
        self.assertEqual(registration, self.session.active_registration)
    def test_a4_invalid_signed_claim_matrix_preserves_account(self):
        registration = self.connect()
        for changes in [dict(iss='https://evil.invalid'), dict(aud='wrong'),dict(nonce='wrong'),dict(sub=''),
                        dict(exp=0),dict(iat=int(time.time())+30),dict(nbf=int(time.time())+30),dict(exp=True),
                        dict(aud=['fixture-client','other']),dict(aud=['fixture-client','other'],azp='other')]:
            with self.subTest(changes=changes):
                self.claim_changes = changes; self.begin(registration)
                with self.assertRaises(a.AuthError): self.callback()
                self.assertEqual(self.session.active_registration, registration)
    def test_a4_multiple_aud_and_unknown_kid_bounded(self):
        self.claim_changes = dict(aud=['fixture-client','other'],azp='fixture-client')
        self.connect()
        validator = a.IdentityValidator(self.transport)
        self.begin()
        token = jwt.encode(dict(iss=a.ISSUER,sub='s',aud='fixture-client',exp=int(time.time())+60,iat=int(time.time()),nonce='n'),self.key,algorithm='RS256',headers={'kid':'unknown'})
        before=self.transport.jwks_calls
        with self.assertRaises(a.AuthError): validator.verify(token,'fixture-client','n')
        self.assertLessEqual(self.transport.jwks_calls-before,2)
    def test_a4_duplicate_claims_none_hs_bad_signature(self):
        validator=a.IdentityValidator(self.transport)
        self.begin()
        claims=dict(iss=a.ISSUER,sub='s',aud='fixture-client',exp=int(time.time())+60,iat=int(time.time()),nonce='n')
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        bad=[jwt.encode(claims,other,algorithm='RS256',headers={'kid':'fixture'}),
             jwt.encode(claims,'fixture-secret'*4,algorithm='HS256',headers={'kid':'fixture'}),
             jwt.encode(claims,None,algorithm='none')]
        raw=json.dumps(claims)[:-1]+',"sub":"duplicate"}'
        bad.append(jwt.api_jws.encode(raw.encode(),self.key,algorithm='RS256',headers={'kid':'fixture'}))
        for token in bad:
            with self.assertRaises(a.AuthError): validator.verify(token,'fixture-client','n')
    def test_a5_identity_only_and_host_retained(self):
        self.scope='openid profile email'
        registration=self.connect(); host=self.vault.record['host_id']
        self.assertEqual(self.session.state,'identity_only')
        with self.assertRaises(a.AuthError): self.session.access_token(registration)
        self.session.sign_out(registration)
        self.assertEqual(self.vault.record['host_id'],host)
        self.session=self.new_session(); self.begin(registration)
        self.assertEqual(self.query['ext_agent_host_id'],[host])
        self.assertFalse(any('api.openai.com' in c[1] for c in self.transport.calls))
    def test_a6_refresh_rotation_atomic_and_serialized(self):
        registration=self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at']=0
        sessions=[self.new_session(),self.new_session()]
        failures=[]
        def run(s):
            try: s.refresh(registration)
            except Exception as e: failures.append(e)
        threads=[threading.Thread(target=run,args=(s,)) for s in sessions]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(failures,[])
        self.assertEqual(self.rotation,1)
        stored=self.vault.record['registrations'][registration]
        self.assertEqual(stored['tokens']['refresh_token'],'fixture-refresh-1')
        self.assertEqual(stored['generation'],2)
    def test_a6_persistence_failure_blocks_replay(self):
        registration=self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at']=0
        self.vault.fail_at=self.vault.writes+2
        with self.assertRaises(a.AuthError):self.session.refresh(registration)
        self.vault.fail_at=None
        before=len(self.transport.calls)
        with self.assertRaises(a.AuthError):self.new_session().refresh(registration)
        self.assertEqual(len(self.transport.calls),before)
    def test_a6_transient_terminal_revocation(self):
        registration=self.connect()
        self.vault.record['registrations'][registration]['tokens']['expires_at']=0
        self.transport.refresh_error=(503,b'{}')
        with self.assertRaises(a.AuthError):self.session.refresh(registration)
        self.assertIsNotNone(self.vault.record['registrations'][registration]['tokens'])
        self.transport.refresh_error=(400,b'{"error":"invalid_grant"}')
        with self.assertRaises(a.AuthError):self.session.refresh(registration)
        self.assertIsNone(self.vault.record['registrations'][registration]['tokens'])
        self.transport.refresh_error=None;self.begin(registration);self.callback()
        self.transport.revocation_status=503
        result=self.session.sign_out(registration)
        self.assertFalse(result)
        self.assertIsNone(self.vault.record['registrations'][registration]['tokens'])
    def test_a6_no_secret_pickle_or_repr_and_nonwindows_fails(self):
        self.connect()
        with self.assertRaises(TypeError):pickle.dumps(self.session)
        self.assertNotIn('fixture-access',repr(self.session))
        with patch.object(a.sys,'platform','linux'):
            vault=a.DPAPIVault(str(Path(tempfile.gettempdir())/'fixture-bootstrap'))
            with self.assertRaises(a.AuthError):vault.load()

    def test_a1_host_loss_requires_explicit_recovery(self):
        with self.assertRaisesRegex(a.AuthError,'host_initialization_required'):
            self.session.begin()
        self.assertIsNone(self.vault.record)
        self.assertEqual(self.transport.calls,[])

    def test_a2_missing_duplicate_ambiguous_oversize_callbacks(self):
        self.begin();state=self.query['state'][0]
        for query in ('code=x&client_id=fixture-client',
                      'state='+state+'&code=x&code=y&client_id=fixture-client',
                      'state='+state+'&code=x&error=access_denied&client_id=fixture-client',
                      'state='+state+'&code=x&client_id=x&client_id=y',
                      'state='+state+'&code=%FF&client_id=fixture-client',
                      'state='+state+'&code='+('x'*8200)):
            with self.subTest(query=query[:35]):
                with self.assertRaises(a.AuthError):
                    self.session.accept_callback('GET','/auth/callback?'+query,'127.0.0.1:1455','127.0.0.1')
        self.assertEqual(self.transport.calls,[])

    def test_a2_cancel_during_exchange_never_commits(self):
        self.begin(); entered=threading.Event(); resume=threading.Event()
        original=self.transport.request
        def delayed(*args,**kwargs):
            if args[1]==a.TOKEN:entered.set();resume.wait(3)
            return original(*args,**kwargs)
        self.transport.request=delayed
        failures=[]
        def callback():
            try:self.callback()
            except a.AuthError:failures.append(True)
        thread=threading.Thread(target=callback);thread.start();self.assertTrue(entered.wait(2))
        cancel=threading.Thread(target=self.session.cancel);cancel.start()
        self.assertTrue(self.session._cancel.wait(2));resume.set()
        thread.join(3);cancel.join(3)
        self.assertEqual(failures,[True]);self.assertEqual(self.vault.record['registrations'],{})

    def test_a4_discovery_and_jwks_changes_fail_closed(self):
        self.begin()
        original=self.transport.request
        for changed in [dict(issuer='https://evil.invalid'),dict(jwks_uri='https://evil.invalid/key'),
                        dict(token_endpoint=a.TOKEN+'?evil'),dict(id_token_signing_alg_values_supported=['HS256'])]:
            def request(method,url,**kwargs):
                if url==a.DISCOVERY:
                    return a.HttpResponse(200,json.dumps(dict(a.PINNED_DISCOVERY,id_token_signing_alg_values_supported=['RS256'],**{} )|changed).encode())
                return original(method,url,**kwargs)
            self.transport.request=request
            with self.assertRaises(a.AuthError):a.IdentityValidator(self.transport).discovery()
        self.transport.request=original
        duplicate=dict(self.jwk)
        def request(method,url,**kwargs):
            if url==a.JWKS:return a.HttpResponse(200,json.dumps({'keys':[duplicate,duplicate]}).encode())
            return original(method,url,**kwargs)
        self.transport.request=request
        with self.assertRaises(a.AuthError):a.IdentityValidator(self.transport).verify(self.tokens('fixture-client')['id_token'],'fixture-client',self.query['nonce'][0])

    def test_a4_header_key_urls_and_duplicate_header_rejected(self):
        self.begin();validator=a.IdentityValidator(self.transport)
        claims=dict(iss=a.ISSUER,sub='s',aud='fixture-client',exp=int(time.time())+60,iat=int(time.time()),nonce='n')
        for field in ('jku','x5u','jwk','crit'):
            token=jwt.encode(claims,self.key,algorithm='RS256',headers={'kid':'fixture',field:'https://evil.invalid'})
            with self.assertRaises(a.AuthError):validator.verify(token,'fixture-client','n')
        for header in (b'{"alg":"RS256","kid":"fixture","kid":"fixture"}', b'{"alg":"RS256","kid":"fixture","b64":true}'):
            altered=base64.urlsafe_b64encode(header).rstrip(b'=').decode()+'.'+token.split('.',1)[1]
            with self.assertRaises(a.AuthError):validator.verify(altered,'fixture-client','n')
        self.assertEqual(self.transport.calls,[])

    def test_a5_same_email_keeps_distinct_registration(self):
        first=self.connect();self.begin();self.callback(client_id='second-client')
        second=self.session.active_registration
        self.assertNotEqual(first,second)
        self.assertEqual(len(self.vault.record['registrations']),2)
        self.assertEqual(self.session.select(first),'plan_ready')
        self.assertEqual(self.session.active_registration,first)

    def test_a5_validated_subject_mismatch_never_replaces(self):
        first=self.connect();prior=copy.deepcopy(self.vault.record)
        self.claim_changes={'sub':'other-user'};self.begin(first)
        with self.assertRaises(a.AuthError):self.callback()
        self.assertEqual(self.vault.record,prior)

    def test_a6_response_scope_and_token_boundaries(self):
        self.begin();data=self.tokens('fixture-client')
        for changes in [dict(token_type='MAC'),dict(access_token=''),dict(refresh_token=None),
                        dict(scope='openid openid'),dict(scope='openid rogue.scope'),
                        dict(expires_in=True),dict(expires_in=0),dict(earliest_refresh_at=float('nan')),
                        dict(access_token='x'*16385)]:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(a.AuthError):self.session._tokens(data|changes)

    def test_a6_refresh_network_ambiguity_persisted_across_restart(self):
        ref=self.connect();self.vault.record['registrations'][ref]['tokens']['expires_at']=0
        self.transport.refresh_error=OSError('fixture timeout')
        with self.assertRaises(a.AuthError):self.session.refresh(ref)
        self.assertEqual(self.vault.record['registrations'][ref]['operation'],'refresh')
        with self.assertRaises(a.AuthError):self.new_session().access_token(ref)
        with self.assertRaises(a.AuthError):self.new_session().refresh(ref)
        self.assertEqual(self.rotation,0)

    def test_a6_crash_barrier_prevents_transmission_and_expired_status(self):
        ref=self.connect();self.vault.record['registrations'][ref]['tokens']['expires_at']=0
        self.assertEqual(self.session.select(ref),'refresh_required')
        before=len(self.transport.calls);self.vault.fail_at=self.vault.writes+1
        with self.assertRaises(OSError):self.session.refresh(ref)
        self.assertEqual(len(self.transport.calls),before)
        self.vault.fail_at=None
        self.session.refresh(ref)
        self.assertEqual(self.rotation,1)

    def test_a6_reference_contains_no_secrets_and_record_limit(self):
        ref=self.connect()
        reference=a.OAuthCredentialReference(str(Path(tempfile.gettempdir())/'fixture'),ref)
        raw=pickle.dumps(reference)
        for secret in (b'fixture-access',b'fixture-refresh',b'fixture-user'):
            self.assertNotIn(secret,raw)
        oversized=copy.deepcopy(self.vault.record)
        oversized['padding']='x'*65536
        with self.assertRaises(a.AuthError):a._validate_record(oversized)
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}',b'[]',b'x'*65537):
            with self.assertRaises(a.AuthError):a._json(raw)

    def test_transport_pins_origins_methods_and_does_not_follow_redirects(self):
        transport=a.OfficialTransport()
        with patch.object(a.http.client,'HTTPSConnection') as constructor:
            for url in ('https://evil.invalid/token',a.TOKEN+'?x=1','http://auth.openai.com/api/accounts/oauth/token'):
                with self.assertRaises(a.AuthError):transport.request('POST',url,form={})
            with self.assertRaises(a.AuthError):transport.request('GET',a.TOKEN)
            constructor.assert_not_called()
            connection=constructor.return_value
            response=connection.getresponse.return_value
            response.status=302;response.getheader.return_value='identity';response.read1.return_value=b''
            result=transport.request('POST',a.TOKEN,form={'grant_type':'fixture'})
            self.assertEqual(result.status,302)
            self.assertEqual(connection.request.call_count,1)
            self.assertEqual(connection.request.call_args.args[:2],('POST','/api/accounts/oauth/token'))
            headers=connection.request.call_args.kwargs['headers']
            self.assertNotIn('Cookie',headers);self.assertNotIn('Authorization',headers)
            connection.close.assert_called_once()

    def test_transport_size_and_compression_are_bounded(self):
        with patch.object(a.http.client,'HTTPSConnection') as constructor:
            response=constructor.return_value.getresponse.return_value
            response.status=200;response.getheader.return_value='gzip'
            with self.assertRaises(a.AuthError):a.OfficialTransport().request('GET',a.JWKS)
            response.getheader.return_value='identity';response.read1.return_value=b'x'*65537
            with self.assertRaises(a.AuthError):a.OfficialTransport().request('GET',a.JWKS)

    def test_listener_parser_with_fake_sockets_no_bind_or_network(self):
        from unittest.mock import MagicMock
        for request,expected in [
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: 127.0.0.1:1455\r\n\r\n',True),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n',False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n',False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\n\r\n',False),
            (b'GET /auth/callback?state=x HTTP/1.1\r\nHost: a\r\n\r\nxx',False)]:
            with self.subTest(expected=expected):
                listener=a.LoopbackListener.__new__(a.LoopbackListener)
                listener.socket=MagicMock();listener.callback=MagicMock()
                connection=MagicMock();connection.__enter__.return_value=connection
                connection.recv.return_value=request
                listener.socket.accept.return_value=(connection,('127.0.0.1',12345))
                listener.poll()
                self.assertEqual(listener.callback.called,expected)
                sent=connection.sendall.call_args.args[0]
                for forbidden in (b'state=x',b'Location:',b'Set-Cookie:',b'Access-Control-Allow-Origin:'):
                    self.assertNotIn(forbidden,sent)

    def test_a5_backup_excludes_host_and_oauth_vault(self):
        import tempfile
        import zipfile
        from pathlib import Path
        from quantlab.desktop_runtime import AppPaths,BackupManager
        with tempfile.TemporaryDirectory() as temporary:
            paths=AppPaths(Path(temporary)/'bootstrap').ensure()
            vault=a.DPAPIVault(str(paths.root))
            vault.directory.mkdir(parents=True)
            vault.path.write_bytes(b'fixture-encrypted-host-and-account')
            (paths.state/'fixture.json').write_text('{}')
            archive=Path(temporary)/'backup.zip'
            BackupManager(paths).create(archive)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()),{'manifest.json','state/fixture.json'})

    def test_a2_cancel_while_waiting_for_commit_lock(self):
        self.begin(); waiting=threading.Event();release=threading.Event()
        original=self.vault.lock
        @contextmanager
        def blocked_lock():
            waiting.set();release.wait(3)
            with original():yield
        self.vault.lock=blocked_lock
        failures=[]
        def callback():
            try:self.callback()
            except a.AuthError:failures.append(True)
        thread=threading.Thread(target=callback);thread.start();self.assertTrue(waiting.wait(2))
        cancel=threading.Thread(target=self.session.cancel);cancel.start()
        self.assertTrue(self.session._cancel.wait(2));release.set()
        thread.join(3);cancel.join(3)
        self.assertEqual(failures,[True]);self.assertEqual(self.vault.record['registrations'],{})

    def test_dpapi_rejects_dangling_links_and_junction_lstat_attributes(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as temporary:
            dangling=Path(temporary)/'dangling'
            dangling.symlink_to(Path(temporary)/'missing',target_is_directory=True)
            with self.assertRaises(a.AuthError):a.DPAPIVault._check_path(dangling)
        junction=MagicMock()
        junction.lstat.return_value=SimpleNamespace(st_mode=0o40700,st_file_attributes=0x400)
        with self.assertRaises(a.AuthError):a.DPAPIVault._check_path(junction)
        junction.stat.assert_not_called()

    def test_absolute_deadline_watchdog_interrupts_header_read(self):
        from unittest.mock import MagicMock
        watchdog=[]
        def timer(interval, callback):
            self.assertEqual(interval,20)
            watchdog.append(callback)
            return MagicMock()
        with patch.object(a.threading,'Timer',side_effect=timer),patch.object(a.http.client,'HTTPSConnection') as constructor:
            connection=constructor.return_value
            response=MagicMock();response.status=200;response.getheader.return_value='identity';response.read1.return_value=b''
            def drip_headers():
                if watchdog:
                    watchdog[0]()
                    raise TimeoutError('fixture socket interrupted')
                return response
            connection.getresponse.side_effect=drip_headers
            with self.assertRaisesRegex(a.AuthError,'transport_timeout'):
                a.OfficialTransport().request('GET',a.JWKS)
            connection.sock.shutdown.assert_called_with(a.socket.SHUT_RDWR)

    def test_cancel_after_commit_boundary_reports_connected_state(self):
        self.begin();entered=threading.Event();release=threading.Event()
        original=self.vault.save
        def blocked_save(record):
            entered.set();release.wait(3);original(record)
        self.vault.save=blocked_save
        result=[]
        callback=threading.Thread(target=self.callback);callback.start()
        self.assertTrue(entered.wait(2))
        cancel=threading.Thread(target=lambda:result.append(self.session.cancel()));cancel.start()
        release.set();callback.join(3);cancel.join(3)
        self.assertEqual(result,['plan_ready'])
        self.assertEqual(self.session.state,'plan_ready')
        self.assertIsNotNone(self.session.active_registration)

    def test_signout_after_uncertain_rotation_cannot_confirm_remote_revocation(self):
        ref=self.connect()
        self.vault.record['registrations'][ref]['operation']='refresh'
        self.assertFalse(self.session.sign_out(ref))
        self.assertIsNone(self.vault.record['registrations'][ref]['tokens'])

    def test_status_summary_reconstructs_active_from_one_local_read(self):
        ref=self.connect();restarted=self.new_session();before=len(self.transport.calls)
        with patch.object(self.vault,'load',wraps=self.vault.load) as load:
            summary=restarted.status_summary()
            load.assert_called_once_with()
        self.assertEqual(summary,{'registrations':[{'registration':ref,'state':'plan_ready'}],
                                  'active_registration':ref,'state':'plan_ready'})
        self.assertEqual(len(self.transport.calls),before)
        self.assertNotIn('fixture-access',json.dumps(summary))
        self.assertNotIn('fixture-user',json.dumps(summary))
        self.assertNotIn('fixture-client',json.dumps(summary))
        self.assertEqual(restarted.state,'disconnected')

    def test_status_summary_missing_empty_expired_and_invalid_vault(self):
        self.assertEqual(self.session.status_summary(),{'registrations':[],
                          'active_registration':None,'state':'host_initialization_required'})
        self.assertIsNone(self.vault.record)
        self.session.initialize_host()
        self.assertEqual(self.session.status_summary()['state'],'disconnected')
        ref=self.connect()
        self.vault.record['registrations'][ref]['tokens']['expires_at']=0
        self.assertEqual(self.new_session().status_summary()['state'],'refresh_required')
        self.vault.record['registrations'][ref]['operation']='refresh'
        self.assertEqual(self.new_session().status_summary()['state'],'reauthorization_required')
        self.vault.record['active']=None
        summary=self.new_session().status_summary()
        self.assertEqual(summary['state'],'disconnected')
        self.assertIsNone(summary['active_registration'])
        self.vault.record['active']='unknown-ref'
        with self.assertRaises(a.AuthError):self.new_session().status_summary()
