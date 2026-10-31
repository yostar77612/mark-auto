"""Offline checks of the official TLS trust context; no network."""

import quantlab.assistant.adapters.chatgpt.identity as _auth_identity
import ssl
import unittest
from unittest.mock import patch


class OfficialTlsContextTests(unittest.TestCase):
    def test_verification_stays_mandatory(self):
        context = _auth_identity.official_tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_intermediate_store_is_not_an_anchor(self):
        stores = []

        def fake_enum(name):
            stores.append(name)
            return []

        with patch.object(ssl, 'enum_certificates', fake_enum, create=True), patch.object(ssl, 'create_default_context'):
            _auth_identity.official_tls_context()
        self.assertEqual(stores, ['ROOT'])

    def test_falls_back_to_default_context_without_roots(self):
        sentinel = object()
        with patch.object(ssl, 'enum_certificates', lambda name: [], create=True), patch.object(ssl, 'create_default_context', return_value=sentinel):
            self.assertIs(_auth_identity.official_tls_context(), sentinel)


if __name__ == '__main__':
    unittest.main()
