"""Native-loader fixtures plus real, bounded loopback TLS; no external services."""

import ast
import copy
import ctypes
import hashlib
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import desktop_tls_smoke as tls

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ROOT / 'packaging' / 'qt_notices' / 'manifest.json'


def report():
    pins = tls.read_pins(NOTICE)
    return {
        'status': 'passed',
        'scope': tls.SCOPE,
        'runtime': {
            'frozen': True,
            'platform': 'win32',
            'openssl_version': 'OpenSSL 3.5.9 INERT TEST FIXTURE',
            'openssl_version_info': [3, 5, 0, 9, 0],
            'notice_sha256': tls.NOTICE_SHA256,
            'loaded_from': 'exact_frozen_bundle',
            'modules': [{'filename': name, 'relative_path': name, 'sha256': pin['sha256'], 'bytes': pin['bytes']} for name, pin in pins.items()],
        },
        'https': {
            'status': 'passed',
            'transport': 'loopback_fixture',
            'requests': 1,
            'certificate_verified': True,
            'hostname_verified': True,
            'trust_scope': 'ephemeral_fixture_ca',
            'protocol': 'TLSv1.3',
            'cipher': 'TLS_AES_256_GCM_SHA384',
            'status_code': 200,
            'response_sha256': tls.BODY_SHA256,
            'cleanup_verified': True,
            'external_network_used': False,
            'seconds': 0.1,
            'cap_seconds': 10,
        },
    }


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pins = {}
        for name in tls.DLL_NAMES:
            raw = ('INERT ' + name).encode()
            (self.root / name).write_bytes(raw)
            self.pins[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'version': [3, 5, 9, 0]}

    def runtime(self, loaded=None, version=(3, 5, 0, 9, 0)):
        with (
            patch.object(sys, 'platform', 'win32'),
            patch.object(sys, 'frozen', True, create=True),
            patch.object(sys, '_MEIPASS', str(self.root), create=True),
            patch.object(ssl, 'OPENSSL_VERSION_INFO', version),
            patch.object(ssl, 'OPENSSL_VERSION', 'OpenSSL 3.5.9 INERT TEST FIXTURE'),
            patch.object(tls, 'read_pins', return_value=self.pins),
            patch.object(tls, 'loaded_module', side_effect=loaded or (lambda name: self.root / name)),
        ):
            return tls.runtime_evidence()

    def test_loaded_private_runtime_records_actual_hashes_and_relative_paths(self):
        value = self.runtime()
        self.assertEqual(value['openssl_version_info'], [3, 5, 0, 9, 0])
        self.assertEqual(value['modules'], report_modules(self.pins))
        self.assertNotIn(str(self.root), json.dumps(value))

    def test_only_exact_cpython_openssl_tuple_is_accepted(self):
        # v3.13.16 Modules/_ssl.c decodes 0x30500090 into these five fields.
        number = 0x30500090
        decoded = ((number >> 28) & 0xFF, (number >> 20) & 0xFF, (number >> 12) & 0xFF, (number >> 4) & 0xFF, number & 0xF)
        self.assertEqual(decoded, (3, 5, 0, 9, 0))
        self.assertEqual(self.runtime(version=decoded)['openssl_version_info'], list(decoded))
        for wrong in (
            (3, 5, 0, 8, 0),
            (3, 5, 0, 10, 0),
            (3, 5, 0, 9, 15),
            (3, 5, 9, 0, 15),
            (3, 5, 1, 9, 0),
            (3, 5, 9),
            (3, 5, 0, 9, 0, 0),
            (3, 5, False, 9, 0),
            (3, 5, 0, 9.0, 0),
            [3, 5, 0, 9, 0],
            None,
        ):
            with self.subTest(version=wrong), self.assertRaises(ValueError):
                self.runtime(version=wrong)

    def test_wrong_hash_size_or_outside_location_refuses(self):
        name = tls.DLL_NAMES[0]
        path = self.root / name
        original = path.read_bytes()
        for raw in (b'x', b'X' * len(original)):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.runtime()
        path.write_bytes(original)
        outside = self.root / 'elsewhere'
        outside.mkdir()
        for dll in tls.DLL_NAMES:
            (outside / dll).write_bytes((self.root / dll).read_bytes())
        with self.assertRaises(ValueError):
            self.runtime(lambda name: outside / name)

    def test_unfrozen_or_unexpected_version_fails_before_tls_fixture(self):
        with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', False, create=True), patch.object(tls, 'https_fixture') as fixture:
            self.assertEqual(tls.run(self.root), {'status': 'failed', 'scope': tls.SCOPE, 'error_category': 'validation'})
        fixture.assert_not_called()
        with (
            patch.object(sys, 'platform', 'win32'),
            patch.object(sys, 'frozen', True, create=True),
            patch.object(sys, '_MEIPASS', str(self.root), create=True),
            patch.object(tls, 'read_pins', return_value=self.pins),
            patch.object(ssl, 'OPENSSL_VERSION_INFO', (3, 5, 5, 0, 15)),
            patch.object(tls, 'loaded_module') as loaded,
        ):
            with self.assertRaises(ValueError):
                tls.runtime_evidence()
        loaded.assert_not_called()

    def test_native_module_inspection_never_loads_openssl_and_keeps_handle_width(self):
        handle = (1 << 40) + 7 if ctypes.sizeof(ctypes.c_void_p) == 8 else 123
        kernel = Mock()
        kernel.GetModuleHandleW.return_value = handle

        def filename(found, buffer, size):
            self.assertEqual(found, handle)
            buffer.value = str(self.root / 'libssl-3.dll')
            return len(buffer.value)

        kernel.GetModuleFileNameW.side_effect = filename
        with patch.object(sys, 'platform', 'win32'), patch.object(ctypes, 'WinDLL', return_value=kernel, create=True) as library:
            self.assertEqual(tls.loaded_module('libssl-3.dll'), self.root / 'libssl-3.dll')
        library.assert_called_once_with('kernel32', use_last_error=True)
        kernel.GetModuleHandleW.assert_called_once_with('libssl-3.dll')
        self.assertIs(kernel.GetModuleHandleW.restype, ctypes.c_void_p)
        self.assertIs(kernel.GetModuleFileNameW.argtypes[0], ctypes.c_void_p)
        kernel.LoadLibraryW.assert_not_called()
        kernel.LoadLibraryExW.assert_not_called()

    def test_missing_or_truncated_loaded_module_refuses(self):
        for handle, length in ((None, 0), (123, 0), (123, 32768)):
            kernel = Mock()
            kernel.GetModuleHandleW.return_value = handle
            kernel.GetModuleFileNameW.return_value = length
            with (
                self.subTest(handle=handle, length=length),
                patch.object(sys, 'platform', 'win32'),
                patch.object(ctypes, 'WinDLL', return_value=kernel, create=True),
            ):
                with self.assertRaises(ValueError):
                    tls.loaded_module('libssl-3.dll')
        with patch.object(ctypes, 'WinDLL', create=True) as library:
            with self.assertRaises(ValueError):
                tls.loaded_module('libssl-3-x64.dll')
        library.assert_not_called()

    def test_notice_manifest_is_exact_hash_pinned(self):
        self.assertEqual(set(tls.read_pins(NOTICE)), set(tls.DLL_NAMES))
        target = self.root / 'manifest.json'
        target.write_bytes(NOTICE.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            tls.read_pins(target)


def report_modules(pins):
    return [{'filename': name, 'relative_path': name, 'sha256': pin['sha256'], 'bytes': pin['bytes']} for name, pin in pins.items()]


class LocalHTTPSFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.before_default = ssl._create_default_https_context

    def assert_clean(self):
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertFalse(any(t.name == 'markauto-owned-tls-fixture' and t.is_alive() for t in threading.enumerate()))
        self.assertIs(ssl._create_default_https_context, self.before_default)

    def test_real_https_uses_only_loopback_one_request_and_scoped_ca(self):
        original = socket.socket.connect
        destinations = []

        def connect(sock, address):
            self.assertEqual(address[0], '127.0.0.1')
            destinations.append(address)
            return original(sock, address)

        with (
            patch.object(socket.socket, 'connect', new=connect),
            patch.object(ssl, 'create_default_context', side_effect=AssertionError('No system trust context')),
        ):
            value = tls.https_fixture(self.root)
        self.assertEqual(len(destinations), 1)
        self.assertEqual(value['requests'], 1)
        self.assertTrue(value['hostname_verified'])
        self.assertTrue(value['certificate_verified'])
        self.assertTrue(value['cleanup_verified'])
        self.assertFalse(value['external_network_used'])
        self.assertEqual(value['trust_scope'], 'ephemeral_fixture_ca')
        self.assertEqual(value['response_sha256'], tls.BODY_SHA256)
        self.assertLessEqual(value['seconds'], 10)
        self.assertIn(value['protocol'], ('TLSv1.2', 'TLSv1.3'))
        self.assert_clean()

    def test_genuine_hostname_mismatch_fails_and_owned_server_stops(self):
        original = tls.fixture_certificates
        with patch.object(tls, 'fixture_certificates', side_effect=lambda directory: original(directory, '127.0.0.2')):
            with self.assertRaises(ssl.SSLCertVerificationError):
                tls.https_fixture(self.root)
        self.assert_clean()

    def test_genuine_wrong_ca_fails_without_global_trust_changes(self):
        original = tls.fixture_certificates

        def wrong_ca(directory):
            ca, cert, key = original(directory)
            other = Path(directory) / 'other'
            other.mkdir()
            unrelated, _, _ = original(other)
            return unrelated, cert, key

        with patch.object(tls, 'fixture_certificates', side_effect=wrong_ca):
            with self.assertRaises(ssl.SSLCertVerificationError):
                tls.https_fixture(self.root)
        self.assert_clean()

    def test_corrupt_https_body_is_not_accepted(self):
        original = ssl.SSLSocket.sendall

        def send(sock, data, *args, **kwargs):
            if data.startswith(b'HTTP/1.1 200 OK'):
                data = data[:-1] + b'X'
            return original(sock, data, *args, **kwargs)

        with patch.object(ssl.SSLSocket, 'sendall', new=send):
            with self.assertRaises(ValueError):
                tls.https_fixture(self.root)
        self.assert_clean()

    def test_server_handshake_timeout_does_not_leave_an_owned_thread(self):
        original = ssl.SSLSocket.do_handshake

        def handshake(sock, *args, **kwargs):
            if sock.server_side:
                raise TimeoutError('INERT SERVER TIMEOUT')
            return original(sock, *args, **kwargs)

        start = time.monotonic()
        with patch.object(ssl.SSLSocket, 'do_handshake', new=handshake):
            with self.assertRaises(OSError):
                tls.https_fixture(self.root)
        self.assertLess(time.monotonic() - start, 10)
        self.assert_clean()

    def test_expired_deadline_opens_no_socket_and_leaves_no_key_files(self):
        original = tls.fixture_certificates

        def expire(directory):
            result = original(directory)
            time.sleep(0.02)
            return result

        with (
            patch.object(tls, 'FIXTURE_SECONDS', 0.001),
            patch.object(tls, 'fixture_certificates', side_effect=expire),
            patch.object(socket, 'socket') as opened,
        ):
            with self.assertRaises(TimeoutError):
                tls.https_fixture(self.root)
        opened.assert_not_called()
        self.assert_clean()

    def test_tls_failure_preserves_runtime_evidence_without_raw_error_text(self):
        runtime = report()['runtime']
        with (
            patch.object(tls, 'runtime_evidence', return_value=runtime),
            patch.object(tls, 'https_fixture', side_effect=ssl.SSLCertVerificationError('SECRET_EXCEPTION')),
        ):
            result = tls.run(self.root)
        self.assertEqual(result, {'status': 'failed', 'scope': tls.SCOPE, 'runtime': runtime, 'error_category': 'certificate_verification'})
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('https', result)

    def test_completed_real_fixture_rechecks_loaded_runtime(self):
        runtime = report()['runtime']
        with patch.object(tls, 'runtime_evidence', return_value=runtime) as inspect:
            result = tls.run(self.root)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(result['https']['requests'], 1)
        self.assert_clean()

    def test_runtime_change_after_tls_cannot_pass(self):
        before = report()['runtime']
        after = copy.deepcopy(before)
        after['modules'][0]['sha256'] = '0' * 64
        with patch.object(tls, 'runtime_evidence', side_effect=[before, after]), patch.object(tls, 'https_fixture', return_value=report()['https']):
            result = tls.run(self.root)
        self.assertEqual(result['status'], 'failed')
        with self.assertRaises(ValueError):
            tls.validate_report(result, NOTICE)


class EvidenceGateTests(unittest.TestCase):
    def test_valid_finite_evidence_passes_without_network(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('Evidence validation is offline')):
            tls.validate_report(report(), NOTICE)

    def test_missing_tampered_unbounded_or_unverified_proof_fails_closed(self):
        cases = [None, {}, dict(report(), status='failed')]
        for section, key, wrong in (
            ('runtime', 'frozen', False),
            ('runtime', 'platform', 'linux'),
            ('runtime', 'openssl_version_info', [3, 5, 5]),
            ('runtime', 'openssl_version_info', [3, 5, 9]),
            ('runtime', 'openssl_version_info', [3, 5, 0, 8, 0]),
            ('runtime', 'openssl_version_info', [3, 5, 0, 9, 15]),
            ('runtime', 'openssl_version_info', [3, 5, False, 9, 0]),
            ('runtime', 'openssl_version_info', [3, 5, 0, 9.0, 0]),
            ('runtime', 'openssl_version_info', [3, 5, 0, 9, 0, 0]),
            ('runtime', 'openssl_version', 'OpenSSL 3.5.5 wrong'),
            ('runtime', 'notice_sha256', '0' * 64),
            ('runtime', 'loaded_from', 'system'),
            ('runtime', 'modules', []),
            ('https', 'requests', True),
            ('https', 'requests', 0),
            ('https', 'requests', 2),
            ('https', 'hostname_verified', False),
            ('https', 'certificate_verified', False),
            ('https', 'trust_scope', 'system'),
            ('https', 'status_code', 500),
            ('https', 'response_sha256', '0' * 64),
            ('https', 'cleanup_verified', False),
            ('https', 'external_network_used', True),
            ('https', 'protocol', 'TLSv1.1'),
            ('https', 'cipher', ''),
            ('https', 'cap_seconds', 11),
            ('https', 'seconds', 10.001),
            ('https', 'seconds', float('nan')),
            ('https', 'seconds', True),
        ):
            value = report()
            value[section][key] = wrong
            cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tls.validate_report(value, NOTICE)

    def test_standalone_tls_hook_has_no_model_runtime_dependency(self):
        source = (ROOT / 'desktop.py').read_text(encoding='utf-8')
        self.assertIn("parser.add_argument('--tls-smoke'", source)
        self.assertIn('return write_report(args.tls_smoke)', source)
        self.assertNotIn('--local-ai-smoke', source)
        source = (ROOT / 'desktop_tls_smoke.py').read_text(encoding='utf-8')
        self.assertNotIn('quantlab.local_ai', source)
        self.assertIn('public trust-store, Qt Schannel, account and model acceptance not tested', tls.SCOPE)


if __name__ == '__main__':
    unittest.main()
