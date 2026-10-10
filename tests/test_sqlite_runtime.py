"""Supply-chain checks stay offline; native provisioning is exercised by CI setup."""
import hashlib
from contextlib import closing
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from quantlab import sqlite_runtime
from tools import install_sqlite_runtime as installer


class SQLiteRuntimeSupplyTests(unittest.TestCase):
    def test_manifest_pins_official_source_and_distinct_hashes(self):
        pin = json.loads(installer.MANIFEST.read_text())
        self.assertEqual(pin['version'], '3.54.0')
        for name in ('windows_x64', 'amalgamation'):
            self.assertTrue(pin[name]['url'].startswith('https://www.sqlite.org/2026/'))
            for digest in ('sha256', 'sha3_256'):
                self.assertEqual(len(bytes.fromhex(pin[name][digest])), 32)
        self.assertEqual(len(bytes.fromhex(pin['amalgamation']['source_sha3_256'])), 32)

    def test_destination_rejects_existing_and_overlap(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root) / 'base'
            base.mkdir()
            for dest in (base, base / 'child', Path(root)):
                with self.assertRaises(RuntimeError):
                    installer.validate_destination(base, dest)
            installer.validate_destination(base, Path(root) / 'private')

    def test_destination_rejects_symlink(self):
        if not hasattr(Path, 'symlink_to'):
            return
        with tempfile.TemporaryDirectory() as root:
            base, link = Path(root) / 'base', Path(root) / 'link'
            base.mkdir()
            try:
                link.symlink_to(base, target_is_directory=True)
            except OSError:
                # Windows CI may disallow unprivileged symlinks. Reparse rejection
                # is still covered through mocked file attributes below.
                return
            with self.assertRaises(RuntimeError):
                installer.validate_destination(base, link / 'private')

    def test_reparse_destination_rejected(self):
        fake = type('Info', (), {'st_mode': 0, 'st_file_attributes': 0x400})()
        with patch.object(Path, 'lstat', return_value=fake):
            with self.assertRaises(RuntimeError):
                installer.reject_links(Path('private'))

    def test_archive_exact_member_no_path_extraction(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('../unsafe', b'ignored')
            archive.writestr('sqlite3.dll', b'correct')
        self.assertEqual(installer.member(output.getvalue(), 'sqlite3.dll'), b'correct')
        with self.assertRaises(RuntimeError):
            installer.member(output.getvalue(), 'missing')
        with self.assertRaises(RuntimeError):
            installer.member(output.getvalue(), 'sqlite3.dll', maximum=2)

    def test_download_checks_both_hashes_and_origin(self):
        class Response(io.BytesIO):
            url = 'https://www.sqlite.org/2026/test.zip'
        data = b'archive'
        pin = {'url': Response.url, 'sha256': hashlib.sha256(data).hexdigest(),
               'sha3_256': hashlib.sha3_256(data).hexdigest()}
        with patch.object(installer.urllib.request, 'urlopen', return_value=Response(data)):
            self.assertEqual(installer.download(pin), data)
        for algorithm in ('sha256', 'sha3_256'):
            with patch.object(installer.urllib.request, 'urlopen', return_value=Response(data)):
                with self.assertRaises(RuntimeError):
                    installer.download({**pin, algorithm: '0' * 64})
        response = Response(data)
        response.url = 'https://unexpected.example/test.zip'
        with patch.object(installer.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(RuntimeError):
                installer.download(pin)

    def test_verifier_checks_sql_version_source_path_and_hash(self):
        import sqlite3
        with closing(sqlite3.connect(':memory:')) as db:
            version, source_id = db.execute('SELECT sqlite_version(), sqlite_source_id()').fetchone()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            dll = root / 'sqlite3.dll'
            dll.write_bytes(b'fixture')
            digest = hashlib.sha256(b'fixture').hexdigest()
            pin = {'version': version, 'source_id': source_id, 'windows_x64': {'dll_sha256': digest}}
            manifest = root / 'pin.json'
            manifest.write_text(json.dumps(pin))
            with patch.object(sqlite_runtime, 'loaded_library', return_value=dll.resolve()):
                self.assertEqual(sqlite_runtime.verify(manifest, root)['library_sha256'], digest)
                with self.assertRaises(RuntimeError):
                    sqlite_runtime.verify(manifest, root, '0' * 64)
                with self.assertRaises(RuntimeError):
                    sqlite_runtime.verify(manifest, root / 'other')
                for key in ('version', 'source_id'):
                    manifest.write_text(json.dumps({**pin, key: 'wrong'}))
                    with self.assertRaises(RuntimeError):
                        sqlite_runtime.verify(manifest, root)

    def test_freezer_rejects_missing_duplicate_or_unpinned_dll(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            dll = root / 'sqlite3.dll'
            dll.write_bytes(b'fixture')
            manifest = root / 'pin.json'
            manifest.write_text(json.dumps({'windows_x64': {'dll_sha256': hashlib.sha256(b'fixture').hexdigest()}}))
            entry = ('sqlite3.dll', str(dll), 'BINARY')
            sqlite_runtime.verify_binaries([entry], manifest)
            for entries in ([], [entry, entry]):
                with self.assertRaises(RuntimeError):
                    sqlite_runtime.verify_binaries(entries, manifest)
            dll.write_bytes(b'tampered')
            with self.assertRaises(RuntimeError):
                sqlite_runtime.verify_binaries([entry], manifest)

    def test_frozen_build_and_child_startup_have_native_checks(self):
        spec = (installer.ROOT / 'packaging/markauto.spec').read_text()
        hook = (installer.ROOT / 'packaging/sqlite_runtime_hook.py').read_text()
        self.assertIn('runtime_hooks=', spec)
        self.assertIn('verify_binaries(analysis.binaries', spec)
        self.assertIn('sys._MEIPASS', hook)
        self.assertIn('verify(', hook)


if __name__ == '__main__':
    unittest.main()
