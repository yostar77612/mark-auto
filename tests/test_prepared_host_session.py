"""Follow-on source contracts. Real Windows behavior is a distinct mandatory gate."""
from pathlib import Path
import hashlib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class PreparedHostSessionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')

    def test_existing_lifecycle_is_unchanged(self):
        expected = '5a75b4b9c58534267e61643f25b841f1cb228837fe76310e04d7eb675d5861fb'
        # Git's Windows checkout converts this text file to CRLF; compare the
        # original source bytes with that checkout-only transformation reversed.
        actual = (ROOT / 'packaging/test_installer.ps1').read_bytes()
        canonical = actual.replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected)
        windows_checkout = canonical.replace(b'\n', b'\r\n')
        self.assertEqual(windows_checkout.replace(b'\r\n', b'\n'), canonical)
        self.assertEqual(hashlib.sha256(windows_checkout.replace(b'\r\n', b'\n')).hexdigest(), expected)
        assertion = b'$json.steps.Count -ne 7'
        self.assertIn(assertion, canonical)
        weakened = canonical.replace(assertion, b'$json.steps.Count -ne 6')
        for changed in (weakened, weakened.replace(b'\n', b'\r\n')):
            self.assertNotEqual(hashlib.sha256(changed.replace(b'\r\n', b'\n')).hexdigest(), expected)

    def test_supervisor_and_exact_external_provenance(self):
        for token in ('Invoke-AcceptanceSupervisor', "$parameters.AcceptanceScope='PreparedHost'",
                      'Confirm-AcceptanceWorker $AcceptanceJob', '$KitSha256', '$StateReceiptSha256',
                      "'candidate-manifest.json'", '$candidate.source_commit -cne $kit.candidate_commit',
                      'no_intervening_app_use', 'prior_reports_sha256', '$supervisor.cleanup_verified -ne $true',
                      '$supervisor.exit_code -ne 2', "$scope.scope -cne 'PreparedHost'"):
            self.assertIn(token, self.source)
        self.assertIn('Assert-PreparedSeparateRoots $KitRoot $SessionRoot', self.source)
        self.assertNotIn('LimitSeconds', self.source)
        self.assertNotIn('Add-Type -TypeDefinition', self.source)
        entry = self.source.split("if ($MyInvocation.InvocationName -eq '.') { return }", 1)[1]
        self.assertLess(entry.index('Assert-PreparedInteractiveUser'), entry.index('[IO.Directory]::CreateDirectory($SessionRoot)'))
        self.assertIn('preloaded ownership types cannot prove this kit', entry)

    def test_bootstrap_refuses_redirects_and_bounds_inputs_before_import(self):
        bootstrap = self.source.split('function Assert-PreparedBootstrapPath', 1)[1].split('function Get-PreparedStateInventory', 1)[0]
        self.assertIn('System.Collections.Generic.Stack[string]', bootstrap)
        self.assertIn('get_Attributes()', bootstrap)
        self.assertIn('Bootstrap redirect refused before content reads', bootstrap)
        self.assertLess(bootstrap.index('Assert-PreparedBootstrapPath $Path'), bootstrap.index('[IO.File]::Open'))
        self.assertIn('$stream.get_Length() -gt $MaxBytes', bootstrap)
        self.assertIn("$KitSha256 64KB -Text", self.source)
        self.assertIn('$digest 1MB -Hold', self.source)
        self.assertIn('foreach ($locked in $helperStreams) { $locked.Dispose() }', self.source)
        self.assertIn('Read-PreparedBootstrap $Path $Digest 1MB -Text', self.source)
        self.assertIn('$acceptanceClock.Elapsed.TotalSeconds -ge 30', self.source)

    def test_backup_precedes_profile_and_install(self):
        backup = self.source.index('  Backup-PreparedState $data $backup $receipt')
        pointer = self.source.index('$stream=[IO.File]::Open($pointer')
        launch = self.source.index('  $owned=Start-OwnedAcceptanceProcess $installer')
        preflight = self.source.index('$preflightStream.Flush($true)')
        self.assertLess(self.source.index('$installerLease=Read-PreparedBootstrap'), backup)
        self.assertIn('if ($installerLease) { $installerLease.Dispose() }', self.source)
        self.assertLess(backup, preflight)
        self.assertLess(preflight, pointer)
        self.assertLess(pointer, launch)
        self.assertIn('Confirm-PreparedStateInventory (Get-PreparedStateInventory $Destination) $Expected', self.source)
        self.assertIn('Confirm-PreparedStateInventory (Get-PreparedStateInventory $Root) $Expected', self.source)
        self.assertIn('[IO.FileMode]::CreateNew', self.source)
        self.assertIn('Original sentinel and absent workspace pointer are required', self.source)

    def test_inventory_uses_real_tree_and_refuses_credentials_before_content(self):
        inventory = self.source.split('function Get-PreparedStateInventory', 1)[1].split('function Confirm-', 1)[0]
        self.assertLess(inventory.index('Credential-bearing state'), inventory.index('[IO.File]::Open'))
        self.assertIn('Assert-AcceptancePath $path', inventory)
        self.assertIn('[MarkAutoAcceptanceJob]::PathAttributes($path)', inventory)
        self.assertIn('[IO.FileShare]::Read', inventory)
        self.assertIn('EnumerateFileSystemEntries($directory).GetEnumerator()', inventory)
        self.assertIn('$entries.MoveNext()', inventory)
        self.assertNotIn('GetFileSystemEntries(', inventory)
        self.assertIn('$entries -isnot [Collections.IEnumerator]', inventory)
        backup = self.source.split('function Backup-PreparedState', 1)[1].split('function Assert-', 1)[0]
        self.assertIn('foreach ($relative in $actual.files_sha256.Keys)', backup)
        self.assertNotIn('foreach ($relative in $Expected', backup)
        self.assertNotIn('Remove-Item', self.source)
        self.assertNotIn('Copy-Item', self.source)

    def test_ui_is_owned_application_only_and_partial(self):
        for token in ('[Windows.Automation.AutomationElement]::FromHandle($hwnd)',
                      '$element.GetCurrentPropertyValue($pidProperty) -ne $ownedPid',
                      '[Windows.Automation.TreeScope]::Children', '[Windows.Automation.SelectionItemPattern]::Pattern',
                      "screenshots='NOT CAPTURED'", "visual_layout='NOT VERIFIED'", "full_functionality='BLOCKED'", "exit 2"):
            self.assertIn(token, self.source)
        for forbidden in ('RootElement', 'FromPoint', 'SendKeys', 'CopyFromScreen', 'PrintWindow',
                          'taskkill', 'Stop-Process', 'GetProcessById', '.Kill()', '.lnk -'):
            self.assertNotIn(forbidden, self.source)
        for prop in ('HasExited', 'MainWindowHandle', 'ExitCode', 'SessionId'):
            self.assertNotRegex(self.source, r'\.' + prop + r'\b')

    def test_original_smoke_assertions_remain_explicit(self):
        for token in ('$proof.steps.Count -ne 7', '$proof.native_window_visible -ne $true',
                      '$proof.worker_completed -ne $true', "'backtest_completed','campaign_completed','paper_completed'",
                      "$proof.generator -cne 'fixture'", "$proof.real_model_status -cne 'not_verified'",
                      "$proof.live_status -cne 'disabled'", "Wait-OwnedAcceptanceProcess $smoke 180000", '-DrainJob'):
            self.assertIn(token, self.source)

    def test_native_fixture_is_mandatory_and_isolated(self):
        fixture = (ROOT / 'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$env:RUNNER_ENVIRONMENT -ne 'github-hosted'", fixture)
        for token in ('Existing backup overwritten', 'Changed sentinel was accepted', 'Unexplained file was accepted',
                      'Unexplained empty directory accepted', 'Credential-bearing directory', 'Receipt paths escaped'):
            self.assertIn(token, fixture)
        self.assertIn('Start-OwnedAcceptanceProcess $UiFixture', fixture)
        self.assertIn('PowerShell eagerly unrolled the inventory iterator', fixture)
        self.assertIn('$index -lt 4097', fixture)
        self.assertIn('Inventory entry cap was bypassed', fixture)
        for token in ('owned-seven-selections-observed', 'foreign-root-refused-before-metadata',
                      "$script:preparedUiPhase -ceq 'root_ownership'", 'Foreign fixture navigation was touched',
                      '$jobReport.cleanup_verified -eq $true'):
            self.assertIn(token, fixture)
        self.assertNotIn('Start-OwnedAcceptanceProcess $installer', fixture)
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text(encoding='utf-8')
        self.assertIn('run: ./packaging/test_prepared_host_session.ps1', workflow)
        self.assertIn('  build:\n    needs: quality\n', workflow)

    def test_fixture_contracts_do_not_depend_on_windows_ansi_default(self):
        original = Path.read_text
        def ansi_default(path, *args, **kwargs):
            if not args:
                kwargs.setdefault('encoding', 'cp1252')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', ansi_default):
            self.test_native_fixture_is_mandatory_and_isolated()

    def test_native_failure_evidence_survives_scratch_cleanup(self):
        fixture = (ROOT / 'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ('Get-PreparedFixtureFailure', 'Select-Object -First 8', '$i -lt 4',
                      '[IO.Path]::GetFileName($Matches[2])', "'other-script'", 'native_code=$native',
                      'ui_navigation_found=$script:preparedUiFound', "'records_and_lease_closed'",
                      'worker_exit=$jobReport.worker_exit_code', 'cleanup_verified=$jobReport.cleanup_verified'):
            self.assertIn(token, fixture)
        self.assertLess(fixture.index("Write-PreparedFixtureReport ($UiCase+'-primary.json') $primary"),
                        fixture.index('try { Close-AcceptanceProcesses } catch'))
        self.assertIn("$report=Join-Path $nativeEvidence ($case+'-supervisor.json')", fixture)
        self.assertIn('Remove-Item -LiteralPath $fixture -Recurse -Force', fixture)
        self.assertNotIn('Remove-Item -LiteralPath $nativeEvidence', fixture)
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text(encoding='utf-8')
        upload = workflow.split('name: Preserve native prepared-host diagnostics even on failure', 1)[1].split('      - uses: actions/setup-python', 1)[0]
        for token in ('if: always()', 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',
                      'path: dist/validation/prepared-host-native/', 'if-no-files-found: error'):
            self.assertIn(token, upload)

if __name__ == '__main__':
    unittest.main()
