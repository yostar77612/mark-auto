"""Fixture-only validator tests, not actual remote-source evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('market_download_validation', Path(__file__).resolve().parents[1] / 'tools/validate_market_download.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class MarketDownloadValidationTests(unittest.TestCase):
    def test_unavailable_is_blocked_never_a_mock_pass(self):
        def fail(*args, **kwargs): raise OSError('fixture unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            result = module.validate(Path(tmp) / 'result.json', loader=fail)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(len(result['providers']), 2)
            self.assertFalse(any('source_hashes' in row for row in result['providers']))

    def test_missing_symbol_or_stale_cannot_pass(self):
        def fixture(provider, *args, **kwargs):
            provenance=SimpleNamespace(sha256='a'*64,source_url='https://example.test/fixture',as_of='2026-10-08',mode='eod')
            return SimpleNamespace(stale=True,series=(SimpleNamespace(instrument=SimpleNamespace(symbol='TAIEX'),bars=(1,),provenance=provenance),))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            self.assertEqual(module.validate(path,loader=fixture)['status'],'BLOCKED')
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):module.validate(path,loader=fixture)
            self.assertEqual(path.read_bytes(),before)
