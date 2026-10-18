"""Offline native dependency packaging proof, never actual account acceptance."""
import importlib.util
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

HAS_DEPS = all(importlib.util.find_spec(name) is not None for name in ('jwt', 'cryptography', 'cffi', 'pycparser'))

@unittest.skipUnless(HAS_DEPS, 'Pinned optional desktop auth dependencies required')
class AuthPackagingSmokeTests(unittest.TestCase):
    def test_actual_native_parser_and_identity_smoke_never_grants_account(self):
        from desktop import _auth_smoke_dependencies
        original = (socket.socket, socket.create_connection, socket.getaddrinfo)
        with tempfile.TemporaryDirectory() as directory, patch('desktop.Path.cwd', return_value=Path(directory)):
            result = _auth_smoke_dependencies()
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['source_type'], 'synthetic')
        self.assertFalse(result['network_used'])
        self.assertEqual(result['real_oauth_status'], 'not_verified')
        self.assertEqual(result['real_model_status'], 'not_verified')
        self.assertTrue(result['rs256_identity_binding'])
        self.assertTrue(result['parser_and_cffi'])
        self.assertEqual(set(result['implementation_provenance']['source_sha256']), {'desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'})
        self.assertEqual(original, (socket.socket, socket.create_connection, socket.getaddrinfo))

    def test_native_failure_is_not_swallowed_and_network_functions_restored(self):
        from desktop import _auth_smoke_dependencies
        import pycparser
        original = (socket.socket, socket.create_connection, socket.getaddrinfo)
        with patch.object(pycparser, 'CParser', side_effect=RuntimeError('synthetic parser fault')):
            with self.assertRaises(RuntimeError):
                _auth_smoke_dependencies()
        self.assertEqual(original, (socket.socket, socket.create_connection, socket.getaddrinfo))

    def test_wrong_version_fails_closed(self):
        from desktop import _auth_smoke_dependencies
        import jwt
        with patch.object(jwt, '__version__', '0.0.0'):
            with self.assertRaises(ValueError):
                _auth_smoke_dependencies()

if __name__ == '__main__':
    unittest.main()
