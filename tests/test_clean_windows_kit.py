"""Kit assembly integrity and fail-closed contracts; not client execution evidence."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clean_kit', ROOT / 'packaging/clean_windows_kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class CleanWindowsKitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = self.make_release('baseline', '0.1.1', 'a' * 40)
        self.new = self.make_release('candidate', '0.1.2', 'b' * 40)

    def make_release(self, name, version, commit):
        path = self.root / name
        path.mkdir()
        exe = path / f'MarkAuto-{version}-windows-x64-setup.exe'
        exe.write_bytes(('synthetic integrity fixture ' + version).encode())
        manifest = {'source_commit': commit, 'artifacts_sha256': {exe.name: kit.digest(exe)},
                    'inputs_sha256': {'quantlab\\' + n: 'c' * 64 for n in kit.ENGINE}}
        (path / 'build-manifest.json').write_text(json.dumps(manifest))
        return path

    def assemble(self):
        return kit.assemble(self.old, self.new, '0.1.1', '0.1.2', self.root / 'kit')

    def test_complete_standalone_layout_and_independent_manifests(self):
        result = self.assemble()
        dest = self.root / 'kit'
        self.assertEqual(result['full_acceptance'], 'EXTERNAL BLOCKED')
        self.assertNotEqual(result['baseline_commit'], result['candidate_commit'])
        self.assertEqual(len(result['files_sha256']), 7)
        for name, checksum in result['files_sha256'].items():
            self.assertEqual(kit.digest(dest / name), checksum)
        self.assertEqual((dest / 'packaging/test_installer.ps1').read_bytes(),
                         (ROOT / 'packaging/test_installer.ps1').read_bytes())
        self.assertFalse(list(dest.rglob('*.py')))
        self.assertFalse((dest / '.git').exists())
        with self.assertRaises(FileExistsError):
            self.assemble()

    def test_rejects_tampered_installer_before_creating_output(self):
        next(self.new.glob('*.exe')).write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse((self.root / 'kit').exists())

    def test_rejects_absent_source_or_bad_commit(self):
        path = self.new / 'build-manifest.json'
        original = json.loads(path.read_text())
        for key, value in [('source_commit', 'main'), ('inputs_sha256', {})]:
            modified = dict(original, **{key: value})
            path.write_text(json.dumps(modified))
            with self.assertRaises((ValueError, KeyError)):
                self.assemble()

    def test_accepts_posix_and_windows_manifest_keys(self):
        path = self.new / 'build-manifest.json'
        data = json.loads(path.read_text())
        data['inputs_sha256'] = {k.replace('\\', '/'): v for k, v in data['inputs_sha256'].items()}
        path.write_text(json.dumps(data))
        self.assemble()

    def test_rejects_same_commit_and_nonascending_versions(self):
        path = self.new / 'build-manifest.json'
        data = json.loads(path.read_text())
        data['source_commit'] = 'a' * 40
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.assemble()
        with self.assertRaises(ValueError):
            kit.assemble(self.old, self.old, '0.1.1', '0.1.1', self.root / 'kit')
        with self.assertRaises(ValueError):
            kit.release(self.old, '../../bad')

    def test_wrapper_preflight_precedes_any_app_execution(self):
        source = (ROOT / 'packaging/clean_windows_acceptance.ps1').read_text()
        run = source.index("& (Join-Path $PSScriptRoot 'test_installer.ps1')")
        for marker in ('ProductType -ne 1', 'Architecture -ne 9', '$build -ne 19045', '$build -lt 22000',
                       'Is64BitProcess', 'WindowsBuiltInRole]::Administrator', 'SessionId -eq 0',
                       'Existing MarkAuto', 'developer_tools.Count', 'Get-FileHash', 'LicenseAlreadyAccepted'):
            self.assertLess(source.index(marker), run)
        self.assertNotIn('Remove-Item', source)
        self.assertNotIn('Set-ExecutionPolicy', source)
        self.assertIn("$exitCode = 2", source)
        self.assertIn("full_functionality='BLOCKED'", source)
        self.assertIn("historical_data_migration='BLOCKED'", source)
        self.assertNotIn("$record.status = 'PASS", source)

    def test_harness_checks_each_releases_sources_and_app_version(self):
        source = (ROOT / 'packaging/test_installer.ps1').read_text()
        for marker in ('Install-Version $BaselineVersion $BaselineManifest',
                       'Install-Version $Version $CandidateManifest',
                       "Smoke 'installed' $BaselineAppVersion", "Smoke 'upgraded' $Version",
                       '$json.version -ne $expectedVersion', '$manifest.inputs_sha256', 'CreateShortcut($startLink).TargetPath', 'Join-Path $activeDirectory',
                       'historical schema migration requires separate evidence'):
            self.assertIn(marker, source)

    @unittest.skipUnless(shutil.which('pwsh'), 'Actual PowerShell parser runs in Windows CI; unavailable here')
    def test_actual_powershell_parser(self):
        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'packaging/validate_powershell.ps1')],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
