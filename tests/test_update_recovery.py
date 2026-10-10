"""Inventory behavior and installer contract; actual crash recovery runs on Windows."""
import importlib.util
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class UpdateRecoveryTests(unittest.TestCase):
    def inventory_module(self):
        spec = importlib.util.spec_from_file_location('payload_inventory', ROOT / 'packaging/payload_inventory.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_inventory_exact_files_and_hashes(self):
        module = self.inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, 'payload'); root.mkdir()
            (root / 'MarkAuto.exe').write_bytes(b'executable')
            (root / '_internal').mkdir()
            (root / '_internal/dependency.dll').write_bytes(b'new')
            inventory = module.inventory(root)
            self.assertEqual(len(inventory), 2)
            self.assertEqual(inventory[1][0], '_internal\\dependency.dll')
            self.assertEqual(len(inventory[0][1]), 64)
            (root / '_internal/obsolete.dll').write_bytes(b'old')
            self.assertEqual(len(module.inventory(root)), 3)

    def test_generated_inventory_digest_is_bound_into_compiler_include(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, 'payload'); root.mkdir()
            (root / 'MarkAuto.exe').write_bytes(b'executable')
            output = Path(temporary, 'payload-inventory.txt')
            include = Path(temporary, 'payload-inventory.iss')
            subprocess.run([sys.executable, str(ROOT / 'packaging/payload_inventory.py'),
                            str(root), str(output), str(include)], check=True)
            self.assertIn(hashlib.sha256(output.read_bytes()).hexdigest(), include.read_text())
            self.assertEqual(output.read_bytes(),
                (hashlib.sha256(b'executable').hexdigest() + '  MarkAuto.exe\r\n').encode('ascii'))

    def test_inventory_rejects_symlinks_and_unsafe_windows_names(self):
        module = self.inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, 'payload'); root.mkdir()
            (root / 'MarkAuto.exe').write_bytes(b'executable')
            bad = root / 'bad:name.dll'
            try:
                bad.write_bytes(b'bad')
            except OSError:
                pass  # Windows filesystem itself rejects this name.
            else:
                with self.assertRaises(ValueError): module.inventory(root)
                bad.unlink()
            try:
                (root / 'linked.dll').symlink_to(root / 'MarkAuto.exe')
            except OSError:
                return  # Creating symlinks can require privilege on Windows.
            with self.assertRaises(ValueError): module.inventory(root)

    def test_installer_never_overlays_previous_payload(self):
        script = (ROOT / 'packaging/markauto.iss').read_text()
        self.assertNotIn('DestDir: "{app}"', script)
        self.assertIn('GenerateUniqueName', script)
        self.assertIn('AfterInstall: VerifyPayload', script)
        self.assertIn('GetSHA256OfFile', script)
        self.assertIn('FILE_ATTRIBUTE_REPARSE_POINT', script)
        self.assertNotIn('[InstallDelete]', script)
        self.assertNotIn('DelTree(', script)

    def test_actual_settings_fixture_matches_existing_store_schema(self):
        from quantlab.desktop_runtime import SettingsStore
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        fixture = re.search(r"\$settingsFixture = '([^']+)'", script).group(1)
        preferences = {'max_calls': 3, 'max_tokens': 10000,
                       'persist_logs': False, 'local_notifications': False}
        self.assertEqual(json.loads(fixture), {'schema_version': 1, 'settings': preferences})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, 'settings.json')
            path.write_bytes(fixture.encode('utf-8'))
            original = path.read_bytes()
            self.assertEqual(SettingsStore(path).load(), preferences)
            self.assertEqual(path.read_bytes(), original)
        self.assertIn('[IO.FileMode]::CreateNew', script)
        self.assertIn('state-v1\\settings.json', script)
        self.assertIn('baseline-existing-settings-smoke', script)
        self.assertIn('Assert-ActualSettings', script)

    def test_real_windows_interruption_and_data_contract(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        for required in ('taskkill.exe', '/T', '/F', 'BaselineManifest', 'CandidateManifest',
                         'Assert-PriorPayload', 'Assert-Sentinels', 'obsolete-test.dll',
                         'payload-inventory.txt', 'interrupted-before-activation', 'CreateShortcut',
                         'reparse-refused.log', 'Assert-Artifact'):
            self.assertIn(required, script)
        self.assertNotIn('Stop-Process -Name', script)

if __name__ == '__main__':
    unittest.main()
