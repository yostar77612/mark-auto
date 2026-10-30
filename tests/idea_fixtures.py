"""Offline fixtures for idea research: a local fake HTTPS site and scripted SSE responses.

No external network and no real account: hostnames resolve to a documentation-only
public address in the injected resolver, and the injected opener connects to the
local fixture. Certificates come from an ephemeral CA in a temporary directory.
"""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time

from quantlab.web_fetch import Fetcher

PUBLIC_IP = '93.184.216.34'
HOSTS = ('alpha.example.org', 'beta.example.org', 'gamma.example.org', 'delta.example.org', 'big.example.org', 'yuanta.com.tw')


def certificates(directory, hosts):
    # Load optional certificate and desktop dependencies only when a fixture needs them.
    from cryptography import x509

    # Load optional certificate and desktop dependencies only when a fixture needs them.
    from cryptography.hazmat.primitives import hashes, serialization

    # Load optional certificate and desktop dependencies only when a fixture needs them.
    from cryptography.hazmat.primitives.asymmetric import ec

    # Load optional certificate and desktop dependencies only when a fixture needs them.
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Idea fixture CA')])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert, private = Path(directory) / 'leaf.pem', Path(directory) / 'leaf-key.pem'
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca.public_bytes(serialization.Encoding.PEM).decode('ascii'), cert, private


class FakeSite:
    """routes[(host, path)] = (status, headers, body_bytes, delay_seconds)."""

    def __init__(self, hosts=HOSTS):
        self.hosts = hosts
        self.routes = {}
        self.requests = []
        self.lock = threading.Lock()

    def page(self, host, path, body, *, status=200, headers=None, delay=0):
        raw = body.encode('utf-8') if type(body) is str else body
        self.routes[(host, path)] = (status, {'Content-Type': 'text/html; charset=utf-8', **(headers or {})}, raw, delay)

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='idea-site-')
        self.ca, cert, key = certificates(self.directory.name, self.hosts)
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_GET(self):
                host = (self.headers.get('Host') or '').split(':')[0]
                with site.lock:
                    site.requests.append((host, self.path, dict(self.headers)))
                status, headers, body, delay = site.routes.get((host, self.path), (404, {'Content-Type': 'text/html'}, b'<p>missing</p>', 0))
                if delay:
                    time.sleep(delay)
                try:
                    self.send_response(status)
                    for name, value in headers.items():
                        self.send_header(name, value)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def client_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=self.ca)
        return context

    def fetcher(self, *, peer=PUBLIC_IP, proxies=None, opened=None):
        """Every fixture host resolves to PUBLIC_IP; the opener reaches only this local site."""
        opened = opened if opened is not None else []

        def resolver(host):
            if host in self.hosts:
                return [PUBLIC_IP]
            raise socket.gaierror('fixture: unknown host')

        def opener(address, timeout):
            opened.append(address)
            return socket.create_connection(('127.0.0.1', self.port), timeout=timeout), peer

        fetcher = Fetcher(resolver=resolver, opener=opener, tls_context=self.client_context(), proxies=proxies or (lambda: {}))
        fetcher.opened = opened
        return fetcher

    def hits(self, host=None):
        with self.lock:
            return [r for r in self.requests if host is None or r[0] == host]


def sse(*events):
    return b''.join(b'data: ' + json.dumps(e, ensure_ascii=False).encode('utf-8') + b'\n\n' for e in events)


def search_call(item_id, query, urls):
    added = {'type': 'response.output_item.added', 'item': {'type': 'web_search_call', 'id': item_id, 'status': 'in_progress'}}
    done = {
        'type': 'response.output_item.done',
        'item': {
            'type': 'web_search_call',
            'id': item_id,
            'status': 'completed',
            'action': {'type': 'search', 'query': query, 'sources': [{'type': 'url', 'url': u} for u in urls]},
        },
    }
    return [added, done]


def message(text, citations=()):
    annotations = [{'type': 'url_citation', 'url': u, 'title': 'cited', 'start_index': 0, 'end_index': 1} for u in citations]
    item = {'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': text, 'annotations': annotations}]}
    return [{'type': 'response.output_item.done', 'item': item}, {'type': 'response.completed', 'response': {'status': 'completed', 'output': [item]}}]


def search_response(searches, urls, *, citations=(), extra=()):
    """searches: [(query, [urls])]; urls: the model's final URL list."""
    events = []
    for index, (query, found) in enumerate(searches, start=1):
        events += search_call('ws_%d' % index, query, found)
    events += list(extra)
    events += message(json.dumps({'urls': [{'url': u, 'reason': 'rules'} for u in urls]}), citations)
    return sse(*events)


def extraction_response(candidates):
    return sse(*message(json.dumps({'candidates': candidates}, ensure_ascii=False)))


def candidate(source_id, quote, *, family='channel_breakout', parameters=None, data=('ohlcv',), fits=True, **extra):
    value = {
        'name': '通道突破',
        'idea': '收盤突破前 20 日高點做多',
        'family': family,
        'parameters': parameters if parameters is not None else {'lookback': 20},
        'fits_builtin_family': fits,
        'rules_zh': '收盤價高於前 20 日最高價做多，低於前 20 日最低價做空',
        'explicit_rules': ['buy when price closes above the 20-day high'],
        'assumptions': [],
        'data_required': list(data),
        'evidence': [{'source_id': source_id, 'quote': quote}],
        'source_claims': ['年化 18%'],
        'limitations': ['僅日線'],
    }
    value.update(extra)
    return value


class FakeTransport:
    """PlanHTTPTransport stand-in: one scripted response (bytes or exception) per call."""

    def __init__(self, *responses, chunk=512, on_chunk=None):
        self.responses = list(responses)
        self.requests = []
        self.limits = []
        self.closed = 0
        self.chunk = chunk
        self.on_chunk = on_chunk
        self.consumed = []

    def stream(self, reference, request, limits, cancelled=None):
        self.requests.append(json.loads(json.dumps(request)))
        self.limits.append(limits)
        if not self.responses:
            raise AssertionError('Unexpected extra model call')
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        sent = 0
        try:
            for start in range(0, len(response), self.chunk):
                if cancelled is not None and cancelled():
                    # Load optional certificate and desktop dependencies only when a fixture needs them.
                    from quantlab.assistant.domain.plan_protocol import PlanError

                    raise PlanError('cancelled')
                piece = response[start : start + self.chunk]
                sent += len(piece)
                if self.on_chunk is not None:
                    self.on_chunk(len(self.requests), sent)
                yield piece
        finally:
            self.closed += 1
            self.consumed.append(sent)


def caller(transport):
    # Load optional certificate and desktop dependencies only when a fixture needs them.
    import desktop_app.shell.main_window

    return desktop_app.shell.main_window._idea_event_caller(object(), transport)


def page(rule):
    return '<html><head><title>Strategy notes</title></head><body><nav>menu</nav><article><h1>Rules</h1><p>%s</p></article></body></html>' % rule
