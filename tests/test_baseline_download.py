"""Pinned baseline bytes are required before executing historical installers."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'packaging/fetch_baseline.py'
spec = importlib.util.spec_from_file_location('baseline', MODULE)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class BaselineDownloadTests(unittest.TestCase):
    def test_existing_unexpected_bytes_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / next(iter(baseline.ASSETS))
            path.write_bytes(b'user-owned-unexpected-file')
            with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
                baseline.fetch(folder)
            self.assertEqual(path.read_bytes(), b'user-owned-unexpected-file')

    def test_changed_or_oversized_download_never_promotes_partial(self):
        class Response(io.BytesIO):
            url = 'https://example.test/verified-pinned-source'
        for content in (b'bad', b'too-many-bytes'):
            with tempfile.TemporaryDirectory() as folder:
                with patch.dict(baseline.ASSETS, {'one': (hashlib.sha256(b'abc').hexdigest(), 3)}, clear=True):
                    with patch.object(baseline.urllib.request, 'urlopen', return_value=Response(content)):
                        with self.assertRaises(ValueError):
                            baseline.fetch(folder)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_pins_match_actual_delivered_baseline(self):
        self.assertEqual(baseline.SOURCE, '28c9f9020e5f44a7a986380e3a6d16bdb7235b2d')
        self.assertEqual(baseline.ASSETS['MarkAuto-0.1.2-windows-x64-setup.exe'][1], 36695486)
        self.assertTrue(baseline.BASE.startswith('https://github.com/yostar77612/mark-auto/releases/download/'))
