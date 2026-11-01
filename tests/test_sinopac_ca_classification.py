"""No credential store writes, network or certificate activation in these tests."""

from datetime import datetime, timezone
from io import BytesIO, StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.sinopac_classification import load_classification
from tools import store_sinopac_ca


class ReferenceAndClassificationTests(unittest.TestCase):
    def test_password_only_new_schema_and_original_certificate_triple_remain_distinct(self):
        backend = SimpleNamespace(read=lambda target: b'{"ca_password":"FAKE_PASSWORD"}')
        resolver = WindowsSecretResolver(backend)
        self.assertEqual(resolver.certificate_password(store_sinopac_ca.TARGET), 'FAKE_PASSWORD')
        with self.assertRaises(DomainError):
            resolver.certificate_credentials(store_sinopac_ca.TARGET)
        backend.read = lambda target: b'{"ca_path":"C:/fake.pfx","ca_password":"FAKE_PASSWORD","person_id":"FAKE_PERSON"}'
        self.assertEqual(resolver.certificate_credentials(store_sinopac_ca.TARGET).person_id, 'FAKE_PERSON')

    def test_tool_writes_only_password_reference_and_never_echoes_it(self):
        output = StringIO()
        with (
            patch.object(store_sinopac_ca, 'getpass', return_value='FAKE_PASSWORD'),
            patch('tools.store_sinopac_key._write') as writer,
            patch('sys.stdout', output),
        ):
            self.assertEqual(store_sinopac_ca.main(), 0)
        self.assertEqual(writer.call_args.args, (store_sinopac_ca.TARGET, b'{"ca_password": "FAKE_PASSWORD"}'))
        self.assertNotIn('FAKE_PASSWORD', output.getvalue())

    def test_public_classification_uses_published_date_not_industry_or_symbol_guess(self):
        document = b'Date Stock Updated:2026/10/30<table><tr><td>2330 TSMC</td><td>TW0002330008</td><td>ESVUFR</td></tr></table>'
        evidence = load_classification('2330', 'TSE', datetime(2026, 11, 1, tzinfo=timezone.utc), opener=lambda *args, **kw: BytesIO(document))
        self.assertEqual(evidence.product_class, 'COMMON_STOCK')
        self.assertEqual(evidence.source_version, '2026-10-30')
        self.assertEqual(evidence.isin, 'TW0002330008')
        missing = document.replace(b'ESVUFR', b'UNKNOWN')
        with self.assertRaises(DomainError):
            load_classification('2330', 'TSE', datetime(2026, 11, 1, tzinfo=timezone.utc), opener=lambda *args, **kw: BytesIO(missing))


if __name__ == '__main__':
    unittest.main()
