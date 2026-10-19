"""Offline selection tests; fake DER entries do not claim real-chain validation."""

import ast
from pathlib import Path
import ssl
import subprocess
import unittest
from unittest.mock import Mock, patch

from quantlab import downloads, market_providers, tls_trust


ROOT = Path(__file__).resolve().parents[1]


class TrustContextTests(unittest.TestCase):
    def assert_verified(self, context):
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_only_server_auth_root_store_entries_are_loaded(self):
        # Model the problematic cross-signed chain without a crypto dependency.
        root = (b'self-signed-root', 'x509_asn', True)
        valid_root = (b'valid-server-auth-root', 'x509_asn', {'1.3.6.1.5.5.7.3.1'})
        expired_intermediate = (b'expired-cross-signed-intermediate', 'x509_asn', True)
        valid_intermediate = (b'valid-intermediate', 'x509_asn', True)
        stores = {
            'ROOT': [root, valid_root, (b'client-only', 'x509_asn', {'1.3.6.1.5.5.7.3.2'}), (b'pkcs7', 'pkcs_7_asn', True)],
            'CA': [expired_intermediate, valid_intermediate],
        }
        loader = Mock(side_effect=stores.__getitem__)
        with patch.object(ssl.SSLContext, 'load_verify_locations') as load, patch.object(ssl, 'create_default_context') as fallback:
            context = tls_trust.build_trust_context(store_loader=loader)
        self.assert_verified(context)
        loader.assert_called_once_with('ROOT')
        self.assertEqual([call.kwargs['cadata'] for call in load.call_args_list], [ssl.DER_cert_to_PEM_cert(entry[0]) for entry in (root, valid_root)])
        fallback.assert_not_called()

    def test_bad_der_is_skipped_and_valid_root_kept(self):
        loader = Mock(return_value=[(b'bad', 'x509_asn', True), (b'good', 'x509_asn', True)])
        with patch.object(ssl.SSLContext, 'load_verify_locations', side_effect=[ssl.SSLError('bad DER'), None]) as load:
            context = tls_trust.build_trust_context(store_loader=loader)
        self.assert_verified(context)
        self.assertEqual(load.call_count, 2)

    def test_empty_untrusted_bad_and_unavailable_stores_use_verified_default(self):
        default = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        for loader, failure in (
            (Mock(return_value=[]), None),
            (Mock(return_value=[(b'no-trust', 'x509_asn', set())]), None),
            (Mock(return_value=[(b'bad', 'x509_asn', True)]), ssl.SSLError('bad DER')),
            (Mock(side_effect=OSError('store unavailable')), None),
        ):
            with self.subTest(loader=loader), patch.object(ssl, 'create_default_context', return_value=default) as fallback:
                with patch.object(ssl.SSLContext, 'load_verify_locations', side_effect=failure):
                    context = tls_trust.build_trust_context(store_loader=loader)
                self.assertIs(context, default)
                fallback.assert_called_once_with()
                self.assert_verified(context)

    def test_missing_platform_loader_uses_verified_default(self):
        default = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.object(ssl, 'enum_certificates', None, create=True), patch.object(ssl, 'create_default_context', return_value=default) as fallback:
            self.assertIs(tls_trust.build_trust_context(), default)
        fallback.assert_called_once_with()
        self.assert_verified(default)

    def test_store_iteration_failure_discards_partial_context(self):
        def loader(store):
            yield b'root', 'x509_asn', True
            raise OSError('late store error')

        default = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.object(ssl.SSLContext, 'load_verify_locations'), patch.object(ssl, 'create_default_context', return_value=default):
            self.assertIs(tls_trust.build_trust_context(store_loader=loader), default)

    def test_transports_use_shared_builder_without_network(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertIs(downloads.build_trust_context, tls_trust.build_trust_context)
        self.assertIs(market_providers.build_trust_context, tls_trust.build_trust_context)
        with patch.object(downloads, 'build_trust_context', return_value=context) as builder, patch.object(downloads, 'build_opener') as opener:
            downloads.https_transport('https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData', 1)
            builder.assert_called_once_with()
            handler = opener.call_args.args[1]
            self.assertIs(handler._context, context)
        with patch.object(market_providers, 'build_trust_context', return_value=context) as builder:
            handler = market_providers._DeadlineHTTPSHandler(1)
            self.assertIs(handler._context, context)
            builder.assert_called_once_with()

    def test_non_test_code_never_disables_tls_verification(self):
        names = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.py'], cwd=ROOT).decode().split('\0')
        paths = {ROOT / name for name in names if name and not name.startswith('tests/')}
        paths.update((ROOT / 'quantlab').glob('*.py'))
        violations = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ''
                if name in {'CERT_NONE', '_create_unverified_context'}:
                    violations.append((path.name, node.lineno))
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant) and node.value.value is False:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(isinstance(target, ast.Attribute) and target.attr == 'check_hostname' for target in targets):
                        violations.append((path.name, node.lineno))
                if isinstance(node, ast.keyword) and node.arg == 'check_hostname' and isinstance(node.value, ast.Constant) and node.value.value is False:
                    violations.append((path.name, node.value.lineno))
        self.assertEqual(violations, [])
