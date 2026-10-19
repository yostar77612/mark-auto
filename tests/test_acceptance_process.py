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
        for token in ('0x2000D', '0x00080004', '0x2000', 'false,0x00080004', 'IsProcessInJob(handle,owned', 'TerminateProcess(handle,1)', 'CloseHandle(job)'):
            self.assertIn(token, self.native)
        self.assertLess(self.native.index('UpdateProcThreadAttribute(attributes'), self.native.index('Check(CreateProcess('))
        self.assertLess(self.helper.index('$job = New-Object'), self.helper.index('$job.Start('))
        for source in (self.native, self.helper, self.lifecycle):
            self.assertNotIn('taskkill', source.lower())
            self.assertNotIn('Stop-Process', source)
        for source in (self.helper, self.lifecycle):
            self.assertNotIn('GetProcessById', source)
        self.assertEqual(self.native.count('GetProcessById('), 1)
        self.assertIn('GetProcessById(unchecked((int)pi.id))', self.native)

    def test_creation_bound_binding_is_verified_before_resume(self):
        launch = self.native.split('> StartOwned(', 1)[1].split('    public bool Wait(', 1)[0]
        for token in (
            'Owns(name,GetCurrentProcess())',
            'false,4,IntPtr.Zero,directory',
            'SafeProcessHandle(pi.process,true)',
            'GetProcessId(bound)!=pi.id',
            'Created(bound)!=created',
            '!Owns(name,bound)',
            'Image(bound)',
            'TerminateProcess(pi.process,1)',
            'acceptance_cleanup_failed',
            'Check(childCreated)',
            'previousSuspendCount!=1',
        ):
            self.assertIn(token, launch)
        resume = launch.index('uint previousSuspendCount=ResumeThread(pi.thread)')
        for token in (
            'SafeProcessHandle(pi.process,true)',
            'Image(pi.process)',
            'GetProcessById(unchecked((int)pi.id))',
            'GetProcessId(bound)',
            'Image(bound)',
        ):
            self.assertLess(launch.index(token), resume)
        self.assertIn('NativeHandle=$launch.Item2', self.helper)
        self.assertIn('$owned.NativeHandle.Dispose()', self.helper)
        self.assertIn('if ($firstCleanupError) { throw $firstCleanupError }', self.helper)
        self.assertIn("if ([IO.Path]::GetExtension($FilePath) -ne '.lnk')", self.helper)

    def test_fixture_continues_only_after_verified_isolation(self):
        fixture = (ROOT / 'packaging/test_acceptance_process.ps1').read_text()
        for token in (
            'post-exit-diagnostic',
            'wrong-image-proof.json',
            'rejected-image-executed.txt',
            'native_handle_closed',
            'managed_handle_closed',
            'acceptance_phase',
            'cleanup-error-closes-all',
            'all_four_handles_closed',
            'Unverified launch cleanup',
            'Native ownership cases failed',
        ):
            self.assertIn(token, fixture)
        append = fixture.index('[void]$caseResults.Add($caseResult)')
        for token in ('$caseReport.cleanup_verified -eq $true', 'Unrelated creation identity changed'):
            self.assertLess(fixture.index(token), append)
        self.assertIn('$failedCases.Count -eq 0', fixture)
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        self.assertIn('  build:\n    needs: quality\n', workflow)

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
        for case in (
            'install',
            'bundled-runtime-launch',
            'start-menu-shortcut',
            'desktop-shortcut',
            'version-upgrade',
            'reject-active-upgrade',
            'reject-active-uninstall',
            'native-window-close',
            'uninstall',
            'preserve-user-data',
        ):
            self.assertIn("'" + case + "'", self.lifecycle)
        for assertion in (
            "$json.steps.Count -ne 7",
            "$json.version -ne $expectedVersion",
            "$json.native_window_visible -ne $true",
            "$json.worker_completed -ne $true",
            "$json.real_model_status -ne 'not_verified'",
            "$refused.get_ExitCode() -eq 0",
            "$window.get_HasExited()",
            'Assert-Sentinel',
            'Get-FileHash $shipped',
            "Smoke 'installed' $BaselineAppVersion",
            "Smoke 'upgraded' $Version",
        ):
            self.assertIn(assertion, self.lifecycle)

    def test_install_uninstall_wait_owned_descendants_before_accepting(self):
        self.assertIn("Wait-OwnedAcceptanceProcess $owned 180000 'Installer timed out' -DrainJob", self.lifecycle)
        self.assertIn("Wait-OwnedAcceptanceProcess $owned 180000 'Uninstall timed out' -DrainJob", self.lifecycle)
        self.assertIn('OwnedActiveProcesses($AcceptanceJob) -ne 1', self.helper)
        self.assertIn('$job.get_ActiveProcesses() -eq 0', self.helper)
        self.assertIn('owned_descendants_deadline', self.helper)
        self.assertIn('QueryInformationJobObject(handle,1', self.native)
        self.assertIn('if(handle==IntPtr.Zero || handle==new IntPtr(-1))', self.native)
        for name in ('unins000.exe', 'unins000.dat'):
            marker = 'Assert-AcceptancePath "$appDir\\' + name + '" -RequireAbsent'
            self.assertIn(marker, self.lifecycle)
            self.assertLess(self.lifecycle.index(marker), self.lifecycle.index("@{status=$(if"))

    def test_preflight_preserves_unknown_state_and_all_evidence(self):
        for assertion in ('Registry32', 'Registry64', 'CurrentUser', 'LocalMachine', 'ReparsePoint', '-ErrorAction Stop', 'ItemNotFoundException'):
            self.assertIn(assertion, self.helper)
        self.assertNotIn('SilentlyContinue', self.helper)
        self.assertIn('[MarkAutoAcceptanceJob]::PathAttributes($inspect)', self.helper)
        self.assertIn('CreateFile(path,0x80,7,IntPtr.Zero,3,0x02200000', self.native)
        self.assertIn('if(error==2 || error==3) return 0xffffffff', self.native)
        self.assertIn('throw new Win32Exception(error)', self.native)

        for name in (
            'os-evidence.json',
            'smoke-installed.json',
            'smoke-upgraded.json',
            'performance-observation.json',
            'refused-upgrade.log',
            'refused-uninstall.log',
            'uninstall.log',
        ):
            self.assertIn(name, self.lifecycle.split('try {\n$os =', 1)[0])
        self.assertIn('[IO.FileMode]::CreateNew', self.lifecycle)
        self.assertLess(self.lifecycle.index('Assert-AbsentAcceptanceRegistration $registration'), self.lifecycle.index('New-Item $dataDir'))

    def test_native_getter_failures_cannot_be_suppressed_as_null(self):
        for source in (self.helper, self.lifecycle, self.wrapper):
            for prop in ('ActiveProcesses', 'ExitCode', 'HasExited', 'MainWindowHandle', 'SessionId', 'Attributes'):
                self.assertNotRegex(source, r'\.' + prop + r'\b')
        for call in ('$job.get_ActiveProcesses()', '$job.get_ExitCode()', '$Owned.Process.get_HasExited()', '$Owned.Process.get_MainWindowHandle()'):
            self.assertIn(call, self.helper)
        fixture = (ROOT / 'packaging/test_acceptance_process.ps1').read_text()
        for evidence in (
            'Valid empty job accounting',
            'disposed-job-accounting',
            'native_guard_refused',
            'Owned job handle is unavailable',
            'Unavailable disposed-worker exit code',
            'window-exited-getter-failure',
            'window-handle-getter-failure',
            'native_membership_retained',
        ):
            self.assertIn(evidence, fixture)

    def test_native_failures_are_exercised_in_existing_ci(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        fixture = (ROOT / 'packaging/test_acceptance_process.ps1').read_text()
        self.assertIn('build_acceptance_helper.ps1', workflow)
        self.assertIn('test_acceptance_process.ps1', workflow)
        for case in (
            'install-hang',
            'uninstall-hang',
            'missing-window',
            'wrong-image',
            'unrelated',
            'whole-run-hang',
            'fast-nonzero',
            'exit-two',
            'descendant-completes',
            'descendant-hang',
            'worker-exits-completes',
            'worker-exits-hang',
            'owned_descendant_timeout',
            'Access-denied inventory',
            'Reparse ancestor',
            'Existing job name',
        ):
            self.assertIn(case, fixture)
        self.assertIn('Owned child survived abrupt supervisor cancellation', fixture)


if __name__ == '__main__':
    unittest.main()
