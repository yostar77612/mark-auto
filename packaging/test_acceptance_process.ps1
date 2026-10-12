# Native regression tests run in Windows PowerShell 5.1 on an ephemeral CI runner.
# All files/registry values/processes below are exclusively created by this test.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Native regression fixtures require a GitHub-hosted ephemeral runner' }
. (Join-Path $PSScriptRoot 'acceptance_process.ps1')
function Check([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$fixture = Join-Path $env:TEMP ("markauto ownership's-" + [guid]::NewGuid().ToString('N'))
New-Item $fixture -ItemType Directory | Out-Null
$outsider = $null
$registration = 'Software\MarkAuto-TestLab\' + [guid]::NewGuid().ToString('N')
try {
  $name='Local\MarkAutoAcceptance-Test-' + [guid]::NewGuid().ToString('N')
  $first=New-Object MarkAutoAcceptanceJob($name)
  try {
    $refused=$false
    try { $duplicate=New-Object MarkAutoAcceptanceJob($name); $duplicate.Dispose() } catch { $refused=$true }
    Check $refused 'Existing job name was accepted'
    $refused=$false
    try { $first.Start((Join-Path $fixture 'missing.exe'), '') } catch { $refused=$true }
    Check $refused 'Missing native executable was accepted'
  } finally { $first.Dispose() }
  $exe = Join-Path $fixture 'MarkAuto.exe'
  Add-Type -TypeDefinition 'public static class MarkAutoFixture { public static void Main() { System.Threading.Thread.Sleep(60000); } }' -OutputAssembly $exe -OutputType ConsoleApplication
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName=$exe; $info.UseShellExecute=$false
  $outsider = [Diagnostics.Process]::Start($info)
  $outsiderHandle = $outsider.Handle
  $outsiderCreated = [MarkAutoAcceptanceJob]::Created($outsiderHandle)
  $sentinel = Join-Path $fixture 'original-sentinel.txt'
  [IO.File]::WriteAllText($sentinel, 'original bytes')
  $refused = $false
  try { Assert-AcceptancePath $sentinel -RequireAbsent } catch { $refused = $true }
  Check $refused 'Preexisting file was not refused'
  Check ([IO.File]::ReadAllText($sentinel) -eq 'original bytes') 'Preexisting sentinel changed'
  $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($registration)
  try { $key.SetValue('original', 'preserve') } finally { $key.Dispose() }
  $refused = $false
  try { [void](Assert-AbsentAcceptanceRegistration $registration) } catch { $refused = $true }
  Check $refused 'Preexisting registration was not refused'
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registration)
  try { Check ($key.GetValue('original') -eq 'preserve') 'Preexisting registration changed' } finally { $key.Dispose() }
  $junction=Join-Path $fixture 'reparse'
  New-Item -ItemType Junction -Path $junction -Target $fixture | Out-Null
  try {
    $refused=$false
    try { Assert-AcceptancePath (Join-Path $junction 'not-created') } catch { $refused=$true }
    Check $refused 'Reparse ancestor was accepted'
  } finally { [IO.Directory]::Delete($junction) }
  $denied=Join-Path $fixture 'denied'
  New-Item $denied -ItemType Directory | Out-Null
  [IO.File]::WriteAllText((Join-Path $denied 'existing.txt'), 'unchanged')
  $originalAcl=Get-Acl -LiteralPath $denied
  try {
    $acl=Get-Acl -LiteralPath $denied
    $user=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($user, 'ReadData,ReadAttributes', 'ContainerInherit,ObjectInherit', 'None', 'Deny')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $denied -AclObject $acl
    $refused=$false
    try { Assert-AcceptancePath (Join-Path $denied 'existing.txt') } catch { $refused=$true }
    Check $refused 'Access-denied inventory was accepted as absence'
  } finally { Set-Acl -LiteralPath $denied -AclObject $originalAcl }
  $worker = Join-Path $fixture 'worker.ps1'
  @'
param([string]$AcceptanceJob, [string]$Helper, [string]$Fixture, [string]$Case)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. $Helper
Confirm-AcceptanceWorker $AcceptanceJob
$script:acceptanceProcesses=New-Object System.Collections.ArrayList
try {
  if ($Case -eq 'exit-two') { exit 2 }
  if ($Case -eq 'fast-nonzero') {
    $owned=Start-OwnedAcceptanceProcess $env:ComSpec -ArgumentList @('/c','exit','7')
    Wait-OwnedAcceptanceProcess $owned 1000 'Fast exit timed out'
    if ($owned.Process.ExitCode -ne 7) { throw 'Nonzero native exit code lost' }
    exit 0
  }
  $owned=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe')
  if ($Case -eq 'missing-window') { Wait-OwnedAcceptanceWindow $owned -Seconds 1 }
  elseif ($Case -eq 'install-hang' -or $Case -eq 'uninstall-hang') { Wait-OwnedAcceptanceProcess $owned 500 'Injected installer/uninstaller wait timed out' }
  elseif ($Case -eq 'wrong-image') { [void](Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe') -ExpectedImage $env:ComSpec) }
  elseif ($Case -eq 'unrelated') {
    $outside=[Diagnostics.Process]::GetProcessById([int](Get-Content (Join-Path $Fixture 'outsider-pid.txt')))
    try {
      if ([MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$outside.Handle)) { throw 'Unrelated process adopted by job' }
      $refused=$false
      try { [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob,$outside.Handle) } catch { $refused=$true }
      if (-not $refused -or $outside.HasExited) { throw 'Unrelated same-name process was stopped' }
    } finally { $outside.Dispose() }
  } else {
    @{id=$owned.Process.Id; created=$owned.Created} | ConvertTo-Json | Set-Content (Join-Path $Fixture 'owned-process.json')
    Start-Sleep -Seconds 60
  }
} finally { Close-AcceptanceProcesses }
'@ | Set-Content $worker
  Set-Content (Join-Path $fixture 'outsider-pid.txt') $outsider.Id
  foreach ($case in @('install-hang','uninstall-hang','missing-window','wrong-image','unrelated','whole-run-hang','fast-nonzero','exit-two')) {
    $parameters = @{Helper=(Join-Path $PSScriptRoot 'acceptance_process.ps1'); Fixture=$fixture; Case=$case}
    $report = Join-Path $fixture ($case + '.json')
    $failure = Join-Path $fixture ($case + '-failure.json')
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $exitCode = Invoke-AcceptanceSupervisor $worker $parameters $report $clock -LimitSeconds 10 -FailureReportPath $failure
    $expected = if ($case -eq 'unrelated' -or $case -eq 'fast-nonzero') { 0 } elseif ($case -eq 'exit-two') { 2 } else { 1 }
    Check ($exitCode -eq $expected) ('Unexpected exit: ' + $case)
    Check ($clock.Elapsed.TotalSeconds -lt 10) ('Unbounded wait: ' + $case)
    Check (Test-Path $report) ('Missing supervisor report: ' + $case)
    if ($expected -eq 1) { Check (Test-Path $failure) ('Missing failure report: ' + $case) }
    if ($case -eq 'whole-run-hang') {
      Check ((Get-Content $report -Raw | ConvertFrom-Json).reason -eq 'whole_run_deadline') 'Whole deadline not enforced'
    }
    $outsider.Refresh()
    Check (-not $outsider.HasExited) ('Unrelated same-name process exited: ' + $case)
    Check ([MarkAutoAcceptanceJob]::Created($outsiderHandle) -eq $outsiderCreated) 'Unrelated creation identity changed'
  }
  # Forced supervisor termination must also close the private job without a finally block.
  $supervisor = Join-Path $fixture 'supervisor.ps1'
  @'
param([string]$Helper,[string]$Worker,[string]$Fixture)
$ErrorActionPreference='Stop'
. $Helper
$p=@{Helper=$Helper;Fixture=$Fixture;Case='cancel'}
[void](Invoke-AcceptanceSupervisor $Worker $p (Join-Path $Fixture 'cancel-report.json') ([Diagnostics.Stopwatch]::StartNew()) -LimitSeconds 30)
'@ | Set-Content $supervisor
  [IO.File]::Delete((Join-Path $fixture 'owned-process.json'))
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
  $start.UseShellExecute=$false
  $start.Arguments='-NoProfile -File "' + $supervisor + '" -Helper "' + (Join-Path $PSScriptRoot 'acceptance_process.ps1') + '" -Worker "' + $worker + '" -Fixture "' + $fixture + '"'
  $outer = [Diagnostics.Process]::Start($start)
  [void]$outer.Handle
  $observed = $null
  try {
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path (Join-Path $fixture 'owned-process.json')) -and $clock.Elapsed.TotalSeconds -lt 15) { Start-Sleep -Milliseconds 100 }
    $identity=Get-Content (Join-Path $fixture 'owned-process.json') -Raw | ConvertFrom-Json
    # PID is used only to observe an identified fixture, never for termination.
    $observed=[Diagnostics.Process]::GetProcessById($identity.id)
    Check ([MarkAutoAcceptanceJob]::Created($observed.Handle) -eq $identity.created) 'Fixture identity mismatch'
    $outer.Kill() # Exact creation-returned supervisor handle retained above.
    Check ($outer.WaitForExit(2000)) 'Supervisor did not exit'
    Check ($observed.WaitForExit(2000)) 'Owned child survived abrupt supervisor cancellation'
    $outsider.Refresh()
    Check (-not $outsider.HasExited) 'Cancellation stopped unrelated same-name process'
  } finally {
    if (-not $outer.HasExited) { $outer.Kill(); [void]$outer.WaitForExit(2000) }
    $outer.Dispose()
    if ($observed) { $observed.Dispose() }
  }
  Write-Host 'Native acceptance ownership regressions passed; this is not client lifecycle acceptance'
} finally {
  if ($outsider) {
    if (-not $outsider.HasExited) { $outsider.Kill(); [void]$outsider.WaitForExit(2000) }
    $outsider.Dispose()
  }
  [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($registration, $false)
  Remove-Item -LiteralPath $fixture -Recurse -Force
}
