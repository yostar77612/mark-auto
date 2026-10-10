"""Inventory behavior and installer contract; actual crash recovery runs on Windows."""
import importlib.util
import hashlib
import json
import os
import shutil
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

    def test_recovery_supports_explicit_legacy_and_versioned_baselines(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        self.assertIn("[string]$BaselineVersion = '0.1.1'", script)
        from quantlab import __version__
        self.assertIn(f"[string]$Version = '{__version__}'", script)
        self.assertIn("if ($expectedVersion -eq '0.1.1')", script)
        self.assertIn("$full -ne (Join-Path $trustedRoot 'MarkAuto.exe')", script)
        self.assertIn('Join-Path $trustedRoot "payloads\\$expectedVersion"', script)
        self.assertIn('(Split-Path $directory -Parent) -ne $versionRoot', script)
        self.assertIn("if ($BaselineVersion -ne '0.1.1') { Assert-Inventory $oldDir }", script)
        self.assertEqual(script.count('Smoke $oldExe $BaselineVersion'), 3)
        self.assertNotIn("Smoke $oldExe '0.1.1'", script)

    def test_windows_canonical_aliases_keep_explicit_traversal_rejection(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        guard = script.split('function Assert-PayloadTarget', 1)[1].split('function Assert-Inventory', 1)[0]
        self.assertNotIn('$full -ne $exe', guard)
        self.assertIn('$trustedRoot = [IO.Path]::GetFullPath($appDir)', guard)
        self.assertIn("$exe -notmatch '^[A-Za-z]:\\\\'", guard)
        self.assertIn("$exe.Substring(2).Contains(':')", guard)
        self.assertIn("$exe -match '(^|[\\\\/])\\.\\.?([\\\\/]|$)'", guard)
        self.assertIn('Assert-NoReparsePath $full', guard)

    def test_recovery_preserves_all_prior_payloads_and_unknown_files(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        capture = script.split('$prior = @{}', 1)[1].split('$sentinels = @{}', 1)[0]
        self.assertIn('Get-SafePayloadFiles $appDir', capture)
        self.assertIn("'^unins\\d+\\.(exe|dat|msg)$'", capture)
        self.assertNotIn('payloads', capture)
        self.assertEqual(capture.count('continue'), 1)
        self.assertIn("$obsolete = Join-Path $oldDir '_internal\\obsolete-test.dll'", script)
        self.assertIn('Assert-NoReparsePath $full', script)
        self.assertIn('Assert-NoReparsePath $link', script)
        traversal = script.split('function Get-SafePayloadFiles', 1)[1].split('function Assert-PayloadTarget', 1)[0]
        self.assertLess(traversal.index('[IO.FileAttributes]::ReparsePoint'), traversal.index('if ($entry.PSIsContainer)'))
        self.assertNotIn('-Recurse', traversal)

    def test_recovery_artifact_provenance_is_required_before_setup(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        self.assertIn('MarkAuto-$BaselineVersion-windows-x64-setup.exe', script)
        self.assertIn("$manifest.source_commit -notmatch '^[0-9a-fA-F]{40}$'", script)
        self.assertIn('artifacts_sha256.PSObject.Properties[(Split-Path $file -Leaf)]', script)
        self.assertIn('Get-FileHash -LiteralPath $file -Algorithm SHA256', script)
        self.assertLess(script.index('$baselineEvidence = Assert-Artifact'), script.index("Run-Setup $BaselineInstaller 'baseline-install'"))
        self.assertIn('baseline_source_commit=$baselineEvidence.source_commit', script)
        self.assertIn('candidate_source_commit=$candidateEvidence.source_commit', script)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell path contract execution required')
    def test_windows_payload_target_contract_legacy_versioned_and_escape(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        helpers = '\n'.join(re.search(r'(?ms)^function ' + name + r'\(.*?(?=^function |\Z)', script).group(0)
                            for name in ('Assert-NoReparsePath', 'Assert-PayloadTarget'))
        with tempfile.TemporaryDirectory() as temporary:
            check = Path(temporary, 'check.ps1')
            check.write_text("param([string]$Root)\n$ErrorActionPreference = 'Stop'\n" + helpers + r"""
$appDir = Join-Path $Root 'MarkAuto'
$versioned = Join-Path $appDir 'payloads\0.1.2\is-owned'
New-Item -ItemType Directory -Path $versioned -Force | Out-Null
$legacyExe = Join-Path $appDir 'MarkAuto.exe'
$versionedExe = Join-Path $versioned 'MarkAuto.exe'
[IO.File]::WriteAllText($legacyExe, 'fixture')
[IO.File]::WriteAllText($versionedExe, 'fixture')
Assert-PayloadTarget $legacyExe '0.1.1'
Assert-PayloadTarget $versionedExe '0.1.2'
# Exercise the exact 8.3 spelling that GetFullPath may expand on Windows CI.
$fso = New-Object -ComObject Scripting.FileSystemObject
$shortLegacy = $fso.GetFile($legacyExe).ShortPath
$shortVersioned = $fso.GetFile($versionedExe).ShortPath
Assert-PayloadTarget $shortLegacy '0.1.1'
Assert-PayloadTarget $shortVersioned '0.1.2'
Write-Output ('short_alias_expansion=' + ($shortLegacy -ne [IO.Path]::GetFullPath($shortLegacy)))
foreach ($case in @(@($legacyExe, '0.1.2'), @($versionedExe, '0.1.1'), @($versionedExe, '0.2.0'), @((Join-Path $Root 'MarkAuto.exe'), '0.1.2'),
    @('MarkAuto.exe', '0.1.1'), @('C:MarkAuto.exe', '0.1.1'),
    @((Join-Path $appDir 'payloads\..\MarkAuto.exe'), '0.1.1'),
    @((Join-Path $appDir '.\MarkAuto.exe'), '0.1.1'), @(($legacyExe + ':stream'), '0.1.1'))) {
  $rejected = $false
  try { Assert-PayloadTarget -exe ($case[0]) -expectedVersion ($case[1]) } catch { $rejected = $true }
  if (-not $rejected) { throw 'Unsafe layout accepted' }
}
""", encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(check), '-Root', temporary],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lifecycle_handoff_is_opt_in_absence_owned_and_hash_bound(self):
        lifecycle = (ROOT / 'packaging/test_installer.ps1').read_text()
        recovery = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        self.assertIn('[switch]$CreateRecoveryHandoff', lifecycle)
        self.assertLess(lifecycle.index('Recovery handoff requires absent initial settings'),
                        lifecycle.index('Install-Version $BaselineVersion'))
        self.assertIn('[IO.FileMode]::CreateNew', lifecycle)
        self.assertIn("initial_settings_absent=$true", lifecycle)
        self.assertIn('settings_sha256=$digest', lifecycle)
        guard = recovery.split('function Preserve-OwnedLifecycleSettings', 1)[1].split('function Get-SafePayloadFiles', 1)[0]
        for condition in ('if (-not $LifecycleHandoff) { return }', 'Assert-NoReparsePath $LifecycleHandoff',
                          'Assert-NoReparsePath $settingsPath', '$receipt.candidate_version -ne $Version',
                          '$receipt.candidate_sha256 -ne $candidateHash', '$receipt.app_data_path',
                          '$receipt.initial_settings_absent -ne $true', '$receipt.settings_sha256',
                          'workspace-location.json', '[IO.File]::Move($settingsPath, $archive)'):
            self.assertIn(condition, guard)
        self.assertNotIn('Remove-Item', guard)
        self.assertNotIn('WriteAllBytes', guard)
        self.assertIn(".lifecycle-' + [guid]::NewGuid()", guard)
        self.assertIn('Unknown settings/workspace state: refusing', recovery)
        self.assertIn('Preserved lifecycle preferences changed or disappeared', recovery)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell handoff execution required')
    def test_windows_handoff_preserves_owned_bytes_and_rejects_changed_state(self):
        script = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        helpers = '\n'.join(re.search(r'(?ms)^function ' + name + r'\b.*?(?=^function |\Z)', script).group(0)
                            for name in ('Assert-NoReparsePath', 'Get-OptionalStateItem', 'Preserve-OwnedLifecycleSettings'))
        with tempfile.TemporaryDirectory() as temporary:
            check = Path(temporary, 'handoff.ps1')
            check.write_text("param([string]$Root)\n$ErrorActionPreference = 'Stop'\n" + helpers + r"""
$root = [IO.Path]::GetFullPath($Root)
$results = Join-Path $root 'dist\validation\update-recovery'
$dataDir = Join-Path $root 'owned-test-data'
$settingsPath = Join-Path $dataDir 'state-v1\settings.json'
$Version = '0.2.0'
$candidate = Join-Path $root 'candidate.exe'
$LifecycleHandoff = Join-Path $root 'dist\validation\lifecycle-state-handoff.json'
New-Item -ItemType Directory -Path $results -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $settingsPath -Parent) -Force | Out-Null
[IO.File]::WriteAllText($candidate, 'fixture candidate, not a real installer')
[IO.File]::WriteAllText($settingsPath, 'unique test-owned preference bytes')
$originalHash = (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash.ToLowerInvariant()
$receipt = @{schema_version=1; owner='installer-lifecycle-test'; initial_settings_absent=$true;
  initial_workspace_pointer_absent=$true; lifecycle_passed=$true; candidate_version=$Version;
  candidate_sha256=(Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant();
  app_data_path=$dataDir; settings_relative_path='state-v1/settings.json'; settings_created=$true;
  settings_sha256=('0' * 64)}
$receipt | ConvertTo-Json | Set-Content -LiteralPath $LifecycleHandoff
$rejected = $false
try { Preserve-OwnedLifecycleSettings } catch { $rejected = $true }
if (-not $rejected -or (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $originalHash) { throw 'Changed-state refusal lost original preferences' }
$receipt.settings_sha256 = $originalHash
$receipt.app_data_path = Join-Path $root 'unowned-data'
$receipt | ConvertTo-Json | Set-Content -LiteralPath $LifecycleHandoff
$rejected = $false
try { Preserve-OwnedLifecycleSettings } catch { $rejected = $true }
if (-not $rejected -or -not (Test-Path -LiteralPath $settingsPath)) { throw 'Unowned path accepted' }
$receipt.app_data_path = $dataDir
$receipt | ConvertTo-Json | Set-Content -LiteralPath $LifecycleHandoff
Preserve-OwnedLifecycleSettings
if ((Test-Path -LiteralPath $settingsPath) -or -not (Test-Path -LiteralPath $lifecycleArchive)) { throw 'Owned state not archived' }
if ((Get-FileHash -LiteralPath $lifecycleArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $originalHash) { throw 'Archived bytes differ' }
$rejected = $false
try { Preserve-OwnedLifecycleSettings } catch { $rejected = $true }
if (-not $rejected) { throw 'Consumed handoff replay was accepted' }
""", encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(check), '-Root', temporary],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failure_evidence_upload_does_not_weaken_release_gate(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        self.assertIn('-CreateRecoveryHandoff', workflow)
        self.assertIn('-LifecycleHandoff dist/validation/lifecycle-state-handoff.json', workflow)
        upload = workflow.split('- name: Preserve exact build evidence and candidate installer', 1)[1].split('  release:', 1)[0]
        self.assertIn('if: always()', upload)
        self.assertIn('needs: [build, quality]', workflow.split('  release:', 1)[1])
        self.assertIn('packaging/wait_for_gates.py', workflow)

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
