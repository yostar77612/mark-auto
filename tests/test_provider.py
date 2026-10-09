"""Inert loopback HTTP fixtures only. Never contacts an external model service."""
import json
import os
import threading
import time
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from quantlab.core import ValidationError, to_dict
from quantlab.provider import HTTPTransport
from quantlab.research import CompatibleProvider, validate_dsl
from quantlab.strategies import builtin_strategies


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    seen = []
    def log_message(self, *args): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        type(self).seen.append((self.path, self.headers.get('Authorization'), body))
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location', '/good'); self.send_header('Content-Length', '0'); self.end_headers(); return
        if self.path == '/slow': time.sleep(2)
        if self.path == '/big':
            output = b'x' * 3000
        else:
            output = json.dumps({'choices': [{'message': {'content': json.dumps(to_dict(builtin_strategies()[0]))}}],
                                 'usage': {'total_tokens': 12}, 'id': 'inert-local-fixture'}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(output))); self.end_headers()
        try: self.wfile.write(output)
        except (BrokenPipeError, ConnectionResetError): pass


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = 'http://127.0.0.1:' + str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)

    def test_default_off_and_endpoint_restrictions(self):
        before = len(Handler.seen)
        with self.assertRaises(ValidationError): HTTPTransport()(self.endpoint + '/good', {}, 1)
        transport = HTTPTransport(allow_network=True)
        for url in ['http://example.invalid/v1', 'https://user:password@example.invalid/v1', self.endpoint + '/good?key=x']:
            with self.subTest(url=url), self.assertRaises(ValidationError): transport(url, {}, 1)
        self.assertEqual(len(Handler.seen), before)

    def test_real_transport_compatible_schema_loopback_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CompatibleProvider(model='inert-local-fixture', endpoint=self.endpoint + '/good',
                transport=HTTPTransport(allow_network=True), budget_path=Path(tmp) / 'budget.db',
                network_opt_in=True, max_calls=1, max_tokens=10000)
            self.assertEqual(validate_dsl(provider.generate({})).family, 'trend')
            self.assertEqual(provider.real_model_status, 'not_verified')
            self.assertEqual(len(provider.receipts), 1)

    def test_spawn_campaign_uses_http_transport_without_external_model(self):
        from tests.test_research import inputs
        from quantlab.research import run_campaign
        data, config = inputs(); config['max_trials'] = 1; config['max_improvements'] = 0
        config['families'] = ['trend']; config['process_start_method'] = 'spawn'
        with tempfile.TemporaryDirectory() as tmp:
            provider = CompatibleProvider(model='inert-local-fixture', endpoint=self.endpoint + '/good',
                transport=HTTPTransport(allow_network=True), budget_path=Path(tmp) / 'budget.db',
                network_opt_in=True, max_calls=1, max_tokens=10000)
            state = run_campaign(data, config=config, generator=provider, output_dir=Path(tmp) / 'campaign')
        self.assertEqual(state['attempts'][0]['status'], 'evaluated', state['attempts'])
        self.assertEqual(state['real_model_status'], 'not_verified')
        self.assertEqual(len(state['provider_receipts']), 1)

    def test_redirect_not_followed(self):
        before = len(Handler.seen)
        with self.assertRaises(ValidationError): HTTPTransport(allow_network=True)(self.endpoint + '/redirect', {}, 1)
        self.assertEqual(len(Handler.seen), before + 1)

    def test_timeout_and_response_limit(self):
        transport = HTTPTransport(allow_network=True, max_response_bytes=1024)
        with self.assertRaises(ValidationError): transport(self.endpoint + '/big', {}, 1)
        started = time.monotonic()
        with self.assertRaises(ValidationError): transport(self.endpoint + '/slow', {}, 1)
        self.assertLess(time.monotonic() - started, 1.8)

    def test_runtime_env_credential_and_sanitized_failure(self):
        transport = HTTPTransport(allow_network=True, api_key_env='QUANTLAB_TEST_INERT_KEY')
        with patch.dict(os.environ, {'QUANTLAB_TEST_INERT_KEY': 'fake-local-fixture-only'}):
            transport(self.endpoint + '/good', {}, 1)
            self.assertEqual(Handler.seen[-1][1], 'Bearer fake-local-fixture-only')
            with self.assertRaises(ValidationError) as caught:
                transport(self.endpoint + '/redirect', {}, 1)
            self.assertNotIn('fake-local-fixture-only', str(caught.exception))
        self.assertNotIn('fake-local-fixture-only', repr(transport))


if __name__ == '__main__': unittest.main()
