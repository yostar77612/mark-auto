"""Source/kit contracts only. Native behavior runs separately in Windows CI."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AcceptanceProcessContracts(unittest.TestCase):
    def setUp(self):
        self.helper = (ROOT / 'packaging/acceptance_process.ps1').read_text()
        self.native = (ROOT / 'packaging/acceptance_process.cs').read_text()
        self.lifecycle = (ROOT / 'packaging/test_installer.ps1').read_text()
        self.wrapper = (ROOT / 'packaging/clean_windows_acceptance.ps1').read_text()

    def test_native_membership_is_atomic_and_handle_owned(self):
        for token in ('0x2000D', '0x00080004', '0x2000', 'false,0x00080004',
                      'IsProcessInJob(handle,owned', 'TerminateProcess(handle,1)', 'CloseHandle(job)'):
            self.assertIn(token, self.native)
        self.assertLess(self.native.index('UpdateProcThreadAttribute(attributes'), self.native.index('Check(CreateProcess('))
        self.assertLess(self.helper.index('$job = New-Object'), self.helper.index('$job.Start('))
        for source in (self.native, self.helper, self.lifecycle):
            self.assertNotIn('taskkill', source.lower())
            self.assertNotIn('Stop-Process', source)
            self.assertNotIn('GetProcessById', source)

    def test_no_host_compiler_or_unbounded_process_wait(self):
        self.assertNotIn('Add-Type -TypeDefinition', self.helper)
        self.assertIn('Add-Type -Path $assembly', self.helper)
        self.assertNotIn('Start-Process', self.lifecycle)
        self.assertNotIn('.Kill()', self.lifecycle)
        self.assertIn('[ValidateRange(10,1200)]', self.helper)
        self.assertIn('$LimitSeconds - 5', self.helper)
        self.assertIn('-lt 6GB', self.helper)
        self.assertIn('Invoke-AcceptanceSupervisor', self.wrapper)
        self.assertIn('$global:LASTEXITCODE=0', self.helper)
        self.assertIn('if ($code -ne 0) { exit $code }', self.helper)
        self.assertIn('catch { [Console]::Error.WriteLine', self.helper)

    def test_host_mode_is_partial_and_never_shell_launches(self):
        host = self.lifecycle.split("if ($AcceptanceScope -eq 'PreparedHost') {\n  # ShellExecute", 1)[1].split('} else {', 1)[0]
        self.assertIn('Start-OwnedAcceptanceProcess $shortcut.TargetPath', host)
        self.assertNotIn('Start-OwnedAcceptanceProcess $startMenu', host)
        self.assertIn('Start-OwnedAcceptanceProcess $startMenu', self.lifecycle)
        self.assertIn("NOT RUN: verified shortcut resolution", self.lifecycle)
        self.assertIn("if ($AcceptanceScope -eq 'PreparedHost') { exit 2 }", self.lifecycle)

    def test_preserves_original_acceptance_cases(self):
        for case in ('install', 'bundled-runtime-launch', 'start-menu-shortcut', 'desktop-shortcut',
                     'version-upgrade', 'reject-active-upgrade', 'reject-active-uninstall',
                     'native-window-close', 'uninstall', 'preserve-user-data'):
            self.assertIn("'" + case + "'", self.lifecycle)
        for assertion in ("$json.steps.Count -ne 7", "$json.version -ne $expectedVersion", "$json.native_window_visible -ne $true",
                          "$json.worker_completed -ne $true", "$json.real_model_status -ne 'not_verified'",
                          "$refused.ExitCode -eq 0", "$window.HasExited", 'Assert-Sentinel',
                          'Get-FileHash $shipped', "Smoke 'installed' $BaselineAppVersion", "Smoke 'upgraded' $Version"):
            self.assertIn(assertion, self.lifecycle)

    def test_preflight_preserves_unknown_state_and_all_evidence(self):
        for assertion in ('Registry32', 'Registry64', 'CurrentUser', 'LocalMachine', 'ReparsePoint',
                          '-ErrorAction Stop', 'ItemNotFoundException'):
            self.assertIn(assertion, self.helper)
        self.assertNotIn('SilentlyContinue', self.helper)
        for name in ('os-evidence.json', 'smoke-installed.json', 'smoke-upgraded.json', 'performance-observation.json',
                     'refused-upgrade.log', 'refused-uninstall.log', 'uninstall.log'):
            self.assertIn(name, self.lifecycle.split('try {\n$os =', 1)[0])
        self.assertIn('[IO.FileMode]::CreateNew', self.lifecycle)
        self.assertLess(self.lifecycle.index('Assert-AbsentAcceptanceRegistration $registration'), self.lifecycle.index('New-Item $dataDir'))

    def test_native_failures_are_exercised_in_existing_ci(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        fixture = (ROOT / 'packaging/test_acceptance_process.ps1').read_text()
        self.assertIn('build_acceptance_helper.ps1', workflow)
        self.assertIn('test_acceptance_process.ps1', workflow)
        for case in ('install-hang', 'uninstall-hang', 'missing-window', 'wrong-image', 'unrelated', 'whole-run-hang',
                     'fast-nonzero', 'exit-two', 'Access-denied inventory', 'Reparse ancestor', 'Existing job name'):
            self.assertIn(case, fixture)
        self.assertIn('Owned child survived abrupt supervisor cancellation', fixture)

if __name__ == '__main__':
    unittest.main()
