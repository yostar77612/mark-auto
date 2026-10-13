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
        self.assertIn('Confirm-PreparedStateInventory (Get-PreparedStateInventory $Destination -RequireUnaliased:$RequireUnaliased) $Expected', self.source)
        self.assertIn('Confirm-PreparedStateInventory (Get-PreparedStateInventory $Root -RequireUnaliased:$RequireUnaliased) $Expected', self.source)
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

    def test_session_hashes_are_module_independent_at_all_five_sites(self):
        self.assertNotIn('Get-FileHash', self.source)
        body = self.source.split('function Get-PreparedFileSha256', 1)[1].split('function Assert-PreparedReceiptKeys', 1)[0]
        for token in ('[IO.FileMode]::Open', '[IO.FileAccess]::Read', '[IO.FileShare]::Read',
                      '[Security.Cryptography.SHA256]::Create()', 'ComputeHash($stream)',
                      '$hash.Dispose()', '$stream.Dispose()', 'ToLowerInvariant()'):
            self.assertIn(token, body)
        self.assertEqual(self.source.count('(Get-PreparedFileSha256 '), 5)
        self.assertIn('Assert-AcceptancePath $path', self.source)
        self.assertIn("$entry.Value -cnotmatch '^[a-f0-9]{64}$'", self.source)
        self.assertIn('Kit entry escapes its root', self.source)
        self.assertIn('Kit file digest changed', self.source)
        for forbidden in ('PSModulePath', 'Import-Module', 'Set-ExecutionPolicy'):
            self.assertNotIn(forbidden, body)

    def test_native_hash_regression_executes_real_integrity_loop_without_install(self):
        fixture = (ROOT / 'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ('function Test-PreparedKitIntegrityGuard', 'Parser]::ParseFile',
                      "$node.Condition.Extent.Text -ceq '$kit.files_sha256.PSObject.Properties'",
                      '$code=[scriptblock]::Create($loops[0].Extent.Text)', '& $Code',
                      'Module-dependent hash command was invoked', 'Changed kit bytes were admitted',
                      'Malformed kit digest was admitted', 'Escaped kit path was admitted',
                      'Missing kit member did not fail with native error 2',
                      'Read-denied kit member did not fail with native error 32',
                      'function Reject-PreparedHashIO', 'GetBaseException()',
                      '$native -ne $ExpectedCode', '[IO.FileNotFoundException]', '[IO.IOException]',
                      'Reject-PreparedHashIO { Get-PreparedFileSha256 $File } 32',
                      "Get-PreparedFileSha256 (Join-Path $KitRoot 'missing.bin')",
                      'Hash factory seam not unique', '$body.Replace($factory,',
                      'Injected post-open hash failure', '$algorithm.DisposeCalls -eq 1',
                      '$algorithm.CapturedStream.get_CanRead()',
                      '[IO.FileShare]::None', '$exclusive.Dispose()', '$writer.Dispose()',
                      'real-production-loop-no-install'):
            self.assertIn(token, fixture)
        self.assertIn("Test-PreparedKitIntegrityGuard $dotHashRoot (Join-Path $PSScriptRoot 'prepared_host_session.ps1')", fixture)
        self.assertNotIn('Start-OwnedAcceptanceProcess $installer', fixture)

    def test_native_hash_fixture_matches_canonical_root_precondition_with_retained_dot_alias(self):
        fixture = (ROOT / 'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        guard = fixture.split('function Test-PreparedKitIntegrityGuard', 1)[1].split('function Get-PreparedNativeCode', 1)[0]
        self.assertLess(guard.index('$Root=[IO.Path]::GetFullPath($Root)'), guard.index("$file=Join-Path $Root"))
        self.assertIn(r"$dotHashRoot=$canonicalHashRoot.Substring(0,$hashSeparator+1)+'.\'+$canonicalHashRoot.Substring($hashSeparator+1)", fixture)
        self.assertIn('$dotHashRoot.Length -eq $canonicalHashRoot.Length+2', fixture)
        self.assertIn('[IO.Path]::GetFullPath($dotHashRoot) -ceq $canonicalHashRoot', fixture)
        self.assertIn('Kit root dot control was normalized before admission', fixture)
        self.assertIn('Escaped kit path was admitted', guard)
        self.assertIn('Reject-PreparedHashIO { & $Code } 2', guard)
        self.assertIn('Reject-PreparedHashIO { & $Code } 32', guard)
        self.assertIn('Algorithm disposal missing after hashing fault', guard)

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
        for token in ('using System.Windows.Controls;', 'VirtualizingPanel.SetIsVirtualizing(list,false)',
                      'form.ContentRendered+=delegate', 'ContainerFromIndex(i) as ListBoxItem',
                      'item==null || !item.IsVisible', 'ready-seven-rendered',
                      'File.Move(args[0]+".tmp",args[0])', '$renderClock.Elapsed.TotalSeconds -lt 25',
                      "'31bf3856ad364e35'", "'b77a5c561934e089'", '-ReferencedAssemblies $wpfReferences'):
            self.assertIn(token, fixture)
        self.assertNotIn('using System.Windows.Forms;', fixture)
        self.assertNotIn('RegisterClientSideProvider', fixture)
        self.assertLess(fixture.index("'Owned fixture render proof invalid'"), fixture.index('$result=Test-PreparedNavigation $owned'))
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
                      '[int]::TryParse', "'other-script'", 'native_code=$native',
                      'ui_navigation_found=$script:preparedUiFound', "'records_and_lease_closed'",
                      'worker_exit=$jobReport.worker_exit_code', 'cleanup_verified=$jobReport.cleanup_verified'):
            self.assertIn(token, fixture)
        sanitizer = fixture.split('function Get-PreparedFixtureFailure', 1)[1].split('function Write-PreparedFixtureReport', 1)[0]
        self.assertNotIn('[IO.Path]', sanitizer)
        self.assertNotIn('[int]$Matches', sanitizer)
        for token in ('$trace.Length,16384', '[0-9]{1,10}', 'catch { $frames.Clear() }',
                      '<No file>', '2147483648', "('9'*1000)", 'Native diagnostic leaked untrusted stack text'):
            self.assertIn(token, fixture)
        self.assertLess(fixture.index("Write-PreparedFixtureReport 'bootstrap.json'"),
                        fixture.index(". (Join-Path $PSScriptRoot 'prepared_host_session.ps1')"))
        self.assertLess(fixture.index("Write-PreparedFixtureReport 'bootstrap.json'"),
                        fixture.index('$safeDiagnostic=Get-PreparedFixtureFailure'))
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

class CurrentBaselineSourceContracts(unittest.TestCase):
    def test_distinct_unknown_continuity_and_exact_maps(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("ValidateSet('LifecycleHandoff','CurrentBaseline')", "schema_version -ne 2",
                      "original_lifecycle_continuity -cne 'UNPROVEN'", "Current baseline receipt schema refused",
                      "Current baseline freshness refused", "Current baseline unknown file refused",
                      "Current baseline unknown directory refused", "entrypoint_sha256", "lifecycle_invocation_sha256"):
            self.assertIn(token,source)
        self.assertNotIn("no_intervening_app_use=$true",source)
        self.assertIn("$receipt.no_intervening_app_use -ne $true",source)
        self.assertIn("-OwnedPointerDigest $ownedPointerDigest",source)
        self.assertNotIn("Remove-Item",source)

    def test_both_powershell_sources_have_bom_and_seven_navigation_labels(self):
        labels=('市場總覽','資料匯入與更新','AI 策略中心','回測與結果',
                '比較與策略選擇','紙上交易與復原','設定與備份')
        for name in ('prepared_host_session.ps1','test_prepared_host_session.ps1'):
            raw=(ROOT/'packaging'/name).read_bytes()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'),name)
            text=raw.decode('utf-8-sig')
            for label in labels:
                self.assertIn(label,text,name)

    def test_acl_controls_verify_native_denial_and_restore_exact_bytes(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("Confirm-PreparedSelfOnlyListDeny", "'ListDirectory','None','None','Deny'",
                      "$nativeRootCode -eq 5", "$predicateCode -eq 5",
                      "$scaffoldNativeCode -eq 5", "$scaffoldPredicateCode -eq 5",
                      "ACL probe changed fixture bytes", "ACL restored file metadata control failed"):
            self.assertIn(token,fixture)
        self.assertNotIn("$deniedRejected=$true",fixture)
        self.assertNotIn("$scaffoldDenied=$true",fixture)
        self.assertLess(fixture.index("Set-Acl -LiteralPath $aclParent -AclObject $originalParentAcl"),
                        fixture.index("Set-Acl -LiteralPath $aclRoot -AclObject $originalRootAcl"))

    def test_every_backup_inventory_pass_is_strict_and_between_pass_is_exercised(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        backup=source.split('function Backup-PreparedState',1)[1].split('function Assert-',1)[0]
        import re
        passes=re.findall(r'Get-PreparedStateInventory \$(?:Root|Destination)[^\r\n)]*',backup)
        self.assertEqual(len(passes),4)
        for call in passes:
            self.assertIn('-RequireUnaliased:$RequireUnaliased',call)
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("$script:productionInventory", "$script:inventoryPasses -eq 2",
                      "$script:secondInventoryStrict", "-not $script:secondInventoryReturned",
                      "Unknown-file content access trap was not verified",
                      "Second inventory bypassed strict admission before content access",
                      "Between-pass refusal copied content before admission"):
            self.assertIn(token,fixture)

    def test_directory_streams_and_prior_root_gate_are_fail_closed(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        native=(ROOT/'packaging/acceptance_process.cs').read_text(encoding='utf-8')
        for token in ("Assert-PreparedDirectoryStreams $Root", "Assert-PreparedDirectoryStreams $path",
                      "Assert-PreparedDirectoryStreams $directory", "RequireNoDirectoryDataStreams"):
            self.assertIn(token,source)
        method=native.split('public static void RequireNoDirectoryDataStreams',1)[1].split('struct Accounting',1)[0]
        self.assertIn("if(error!=38) throw new Win32Exception(error)",method)
        self.assertIn("Directory data stream refused",method)
        self.assertIn("finally { FindClose(search); }",method)
        entry=source.split("if ($MyInvocation.InvocationName -eq '.') { return }",1)[1]
        self.assertLess(entry.index('$bootstrapPriorContext=Read-PreparedPriorContext'),
                        entry.index('[IO.Directory]::CreateDirectory($SessionRoot)'))
        gate=source.split('function Read-PreparedPriorContext',1)[1].split('function Assert-PreparedDirectoryStreams',1)[0]
        self.assertIn('Assert-PreparedSeparateRoots $priorRoot $sessionPath',gate)
        self.assertIn('Assert-PreparedSeparateRoots $kitPath $sessionPath',gate)

    def test_native_directory_ads_and_prior_kit_controls_are_verified(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ('MarkAutoPreparedStreamFixture','CreateFileW','DeleteFileW','FindFirstStreamW',
                      'Regular ADS setup was not verified','Regular ADS cleanup was not verified',
                      'Backup ADS setup was not verified','Directory ADS setup was not independently verified',
                      'Backup directory ADS setup was not verified','Scaffold directory ADS setup was not verified',
                      'Session inside prior kit admitted','Prior kit reused as session admitted',
                      'Session ancestor of prior kit admitted','Unpinned same-kit identity admitted'):
            self.assertIn(token,fixture)
        self.assertNotIn("[IO.File]::WriteAllText(($currentSentinel+':",fixture)
        self.assertNotIn("[IO.File]::Delete(($currentSentinel+':",fixture)
        self.assertNotIn("[IO.File]::WriteAllText(($backupSentinel+':",fixture)
        self.assertNotIn("[IO.File]::Delete(($backupSentinel+':",fixture)

    def test_scaffold_uses_one_canonical_root_and_native_alias_controls(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        scaffold=source.split('function Assert-PreparedInstallScaffolding',1)[1].split('function Read-PreparedPriorContext',1)[0]
        self.assertIn("$rootPath=[IO.Path]::GetFullPath($Root).TrimEnd",scaffold)
        self.assertIn("$pending.Enqueue($rootPath)",scaffold)
        self.assertIn("$directory -ceq $rootPath",scaffold)
        self.assertIn("$directory.Substring($rootPrefix.Length)",scaffold)
        self.assertNotIn("$Root.TrimEnd",scaffold)
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("GetShortPathNameW","GetLongPathNameW","Native scaffold alias control unavailable",
                      "Native short alias accepted unknown scaffold child","root_length_changed"):
            self.assertIn(token,fixture)

    def test_deterministic_dot_component_control_exercises_production_guard(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        control=fixture.split("$controllerStage='scaffold_dot_component_controls'",1)[1].split("$controllerStage='scaffold_alias_controls'",1)[0]
        for token in ("$dotCanonical -ceq $canonicalScaffold",
                      "$dotScaffold.Length -ne $dotCanonical.Length",
                      "$dotScaffold.Length -eq ($dotCanonical.Length+2)",
                      "Dot-component root accepted unknown scaffold child",
                      "prefix_length_delta=2", "unknown_child_refused=$true"):
            self.assertIn(token,control)
        self.assertEqual(control.count('Assert-PreparedInstallScaffolding $dotScaffold $reviewed $priorKitContext $invocationContext'),3)
        self.assertIn("'Unknown installer scaffolding directory'",control)
        self.assertIn("Native scaffold alias control unavailable",fixture)

    def test_declared_receipts_are_canonical_and_operational_aliases_stay_separate(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$priorRoot -cne $Receipt.prior_kit_root",source)
        self.assertIn("$labRoot=[IO.Path]::GetFullPath($LabPath)",source)
        self.assertIn("$lab=[IO.Path]::GetFullPath((Join-Path",source)
        for token in ("kit_root=$canonicalSource", "app_data_path=$canonicalCurrent",
                      "install_path=$canonicalScaffold", "prior_kit_root=$canonicalSource",
                      "Noncanonical prior receipt admitted", "Exact lab root adopted as prior kit",
                      "Outside lab prior kit admitted", "Noncanonical declared receipt identity admitted",
                      "Operational alias changed canonical receipt identity or output",
                      "Operational alias bypassed same-kit digest pin",
                      "$sourceOperationalAlias $currentOperationalAlias $scaffoldOperationalAlias"):
            self.assertIn(token,fixture)
        bootstrap=fixture.split('# Bootstrap separation runs before any session directory creation.',1)[1].split("[Console]::Out.WriteLine",1)[0]
        self.assertNotIn("$source (Join-Path $fixture",bootstrap)
        self.assertIn("$rootReceipt.prior_kit_root=$priorRoot",bootstrap)
        self.assertIn("$sameReceipt.prior_kit_root=$bootstrapSource",bootstrap)
        self.assertIn("$disjoint.root -ceq $priorRoot",bootstrap)
        self.assertIn("Assert-PreparedInstallScaffolding $dotScaffold",fixture)
        self.assertIn("Assert-PreparedInstallScaffolding $aliasRoot",fixture)

    def test_v7_prior_receipt_trims_before_strict_identity(self):
        self.source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        gate=self.source.split('function Read-PreparedPriorContext',1)[1].split('function Assert-PreparedDirectoryStreams',1)[0]
        self.assertIn("$priorRoot=[IO.Path]::GetFullPath($Receipt.prior_kit_root).TrimEnd('\\')",gate)
        self.assertLess(gate.index('$priorRoot=[IO.Path]'),gate.index('$priorRoot -cne $Receipt.prior_kit_root'))
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("@(($priorRoot+'\\'),($bootstrapLab+'\\'))",fixture)
        self.assertIn("'Trailing-separator prior receipt admitted' 'Current baseline prior kit path refused'",fixture)

    def test_v7_all_entry_inputs_use_canonical_containment_without_identity_rewrite(self):
        self.source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        gate=self.source.split('function Assert-PreparedLabContainment',1)[1].split('function Assert-PreparedShortcutContainment',1)[0]
        self.assertIn("$full=[IO.Path]::GetFullPath($Path).TrimEnd('\\')",gate)
        self.assertIn("$labRoot=[IO.Path]::GetFullPath($LabPath).TrimEnd('\\')",gate)
        self.assertIn("$full.StartsWith(($labRoot+'\\'),[StringComparison]::OrdinalIgnoreCase)",gate)
        entry=self.source.split("if ($MyInvocation.InvocationName -eq '.') { return }",1)[1]
        self.assertIn("foreach ($path in @($KitRoot,$SessionRoot,$StateReceipt,$PSCommandPath)) {\n  Assert-PreparedLabContainment $path $lab 'Kit, script, receipt and session evidence must stay in MarkAuto-TestLab'",entry)
        self.assertNotIn('$PSCommandPath=',entry)
        self.assertIn('foreach ($path in @($KitRoot,$StateReceipt,$PSCommandPath)) { Assert-PreparedBootstrapPath $path }',entry)
        self.assertIn('Assert-PreparedBootstrapPath $path -AllowAbsent; Assert-AcceptancePath $path',entry)
        self.assertIn('Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath',entry)
        self.assertIn('Get-PreparedFileSha256 $PSCommandPath',entry)

    def test_v7_invocation_and_shortcut_use_production_boundary_guards(self):
        self.source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$invocationPath=[IO.Path]::GetFullPath($receipt.lifecycle_invocation_path).TrimEnd('\\')",self.source)
        self.assertIn("Assert-PreparedLabContainment $invocationPath $lab 'Current baseline invocation path refused'",self.source)
        self.assertLess(self.source.index('Assert-PreparedLabContainment $invocationPath'),self.source.index('$invocation=Read-PreparedJson $invocationPath'))
        shortcut=self.source.split('function Assert-PreparedShortcutContainment',1)[1].split('function Assert-PreparedBootstrapPath',1)[0]
        self.assertIn("$appRoot=[IO.Path]::GetFullPath($AppPath).TrimEnd('\\')",shortcut)
        self.assertIn("[IO.Path]::GetFullPath($Target).StartsWith(($appRoot+'\\')",shortcut)
        self.assertIn("(Split-Path $Target -Leaf) -cne 'MarkAuto.exe'",shortcut)
        self.assertIn('Assert-PreparedShortcutContainment $exe $app',self.source)
        self.assertIn('$resolved.TargetPath -ine $exe -or $resolved.Arguments',self.source)
        self.assertIn('Start-OwnedAcceptanceProcess $exe',self.source)

    def test_v7_native_boundary_controls_assert_exact_refusals_and_positives(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        control=fixture.split("$controllerStage='canonical_boundary_controls'",1)[1].split("[Console]::Out.WriteLine",1)[0]
        for token in ('Assert-PreparedLabContainment $boundaryChild $boundaryLab $failure',
                      'Assert-PreparedLabContainment $boundaryChildAlias $boundaryAlias $failure',
                      'Assert-PreparedLabContainment $boundaryScriptAlias $boundaryAlias',
                      "($boundaryLab+'\\')", "($boundaryLab+'-sibling\\file.json')",
                      "'Lab containment accepted a non-descendant' $failure",
                      'Assert-PreparedShortcutContainment $boundaryExe $boundaryAppAlias',
                      "(Join-Path $boundaryApp 'Other.exe')", "(Join-Path $boundaryApp 'markauto.exe')",
                      "'Shortcut containment accepted an escaped or non-exact executable' 'Installed shortcut escaped the exact app tree'"):
            self.assertIn(token,control)
        reject=fixture.split('function Reject(',1)[1].split('function Get-PreparedNativeCode',1)[0]
        self.assertIn('$_.Exception.Message -cne $ExpectedFailure',reject)

    def test_original_run_context_is_not_relabelled_as_current_build(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("$Invocation.ExecutionSha -cne $Receipt.prior_candidate_commit",
                      "$prior=Join-Path $priorKitRoot", "$Receipt.prior_kit_sha256",
                      "Assert-PreparedInstallScaffolding $app $receipt $priorKit"):
            self.assertIn(token,source)
        self.assertIn("$candidate.source_commit -cne $kit.candidate_commit",source)
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("ExecutionSha=('7'*40)",fixture)
        self.assertIn("candidate_commit=('a'*40)",fixture)

    def test_alias_metadata_is_native_and_bound_to_the_open_stream(self):
        source=(ROOT/'packaging/prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        native=(ROOT/'packaging/acceptance_process.cs').read_text(encoding='utf-8')
        for token in ("RequireSingleLinkDefaultStream", "get_SafeFileHandle().DangerousGetHandle()", "Assert-PreparedBootstrapPath $path -AllowAbsent"):
            self.assertIn(token,source)
        for token in ("before.links!=1", "after.links!=1", "before.indexHigh", "FindFirstStreamW",
                      "FindNextStreamW", "ERROR_HANDLE_EOF", '"::$DATA"', "finally { FindClose(search); }"):
            self.assertIn(token,native)

    def test_v2_native_follow_on_cases_use_runtime_gates(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("Version-one current receipt admitted", "Wrong original invocation candidate admitted",
                      "Timed-out original invocation admitted", "Hard-linked backup admitted",
                      "Alternate backup stream admitted", "Hard-linked owned pointer admitted",
                      "Scaffold metadata access denial admitted",
                      "Reviewed empty scaffolding changed after rejection controls"):
            self.assertIn(token,fixture)
        self.assertIn("$wrongInvocation=$invocationContext.Clone()",fixture)
        self.assertIn("Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased",fixture)

    def test_native_negative_cases_are_part_of_existing_ci_fixture(self):
        fixture=(ROOT/'packaging/test_prepared_host_session.ps1').read_text(encoding='utf-8-sig')
        for token in ("Historical continuity was manufactured", "Stale current baseline accepted",
                      "Future current baseline accepted", "Unsafe current receipt map accepted",
                      "Wrong prior invocation context accepted", "Current unknown file read",
                      "Current unknown directory admitted", "Current credential presence admitted",
                      "Current changed content accepted", "Hard-linked current file admitted",
                      "Alternate current stream admitted", "Current redirect followed",
                      "Current metadata access denial admitted", "Non-empty installer tree admitted",
                      "Unknown installer directory admitted", "Current backup mismatch accepted",
                      "Existing workspace pointer admitted", "Current admission deleted installer scaffolding",
                      "Tampered current receipt accepted", "Installer scaffold redirect admitted",
                      "Wrong scaffold provenance accepted", "Changed owned workspace pointer admitted"):
            self.assertIn(token,fixture)

if __name__ == '__main__':
    unittest.main()
