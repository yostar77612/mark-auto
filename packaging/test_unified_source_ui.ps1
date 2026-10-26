# Early native Qt integration gate. Never install/uninstall or use host profiles.
param([Parameter(Mandatory=$true)][string]$PythonPath,
      [Parameter(DontShow=$true)][string]$FixtureRoot='',
      [Parameter(DontShow=$true)][string]$AcceptanceJob='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$acceptanceClock=[Diagnostics.Stopwatch]::StartNew()
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
  throw 'Source UI fixture requires ephemeral hosted CI; no personal-host UI automation'
}
$root=Split-Path $PSScriptRoot -Parent
$expectedPython=Join-Path $root 'build\unified-source-python\python.exe'
if ([IO.Path]::GetFullPath($PythonPath) -ine [IO.Path]::GetFullPath($expectedPython)) { throw 'Unexpected private source runtime' }
. (Join-Path $PSScriptRoot 'acceptance_process.ps1')
. (Join-Path $PSScriptRoot 'unified_acceptance_ui.ps1')
$results=Join-Path $root 'dist\validation\unified-source-ui'
$dependencies=Join-Path $root 'audit-runtime'
foreach ($path in @($PythonPath,$dependencies)) { Assert-AcceptancePath $path }
if (-not $AcceptanceJob) {
  Assert-AcceptancePath $results -RequireAbsent
  New-Item -ItemType Directory -Path $results | Out-Null
  $FixtureRoot=Join-Path $env:RUNNER_TEMP ('MarkAutoUnifiedSource-'+[guid]::NewGuid().ToString('N'))
  Assert-AcceptancePath $FixtureRoot -RequireAbsent
  New-Item -ItemType Directory -Path $FixtureRoot | Out-Null
  $parameters=@{PythonPath=$PythonPath;FixtureRoot=$FixtureRoot}
  $code=Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath -Parameters $parameters -Clock $acceptanceClock -ReportPath (Join-Path $results 'supervisor.json') -FailureReportPath (Join-Path $results 'result.json') -LimitSeconds 120
  if ($code -ne 0) { throw 'Source Qt close integration failed; see bounded fixture evidence' }
  return
}
Confirm-AcceptanceWorker $AcceptanceJob
Assert-AcceptancePath $FixtureRoot
$fixtureParent=[IO.Path]::GetFullPath((Split-Path $FixtureRoot -Parent)).TrimEnd('\')
if ($fixtureParent -ine [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') -or
    (Split-Path $FixtureRoot -Leaf) -notmatch '^MarkAutoUnifiedSource-[a-f0-9]{32}$') { throw 'Private source fixture root changed' }
$script:acceptanceProcesses=New-Object System.Collections.ArrayList
$gui=$null
$closeClock=$null
try {
  foreach ($entry in @(@('LOCALAPPDATA','local'),@('APPDATA','roaming'),@('USERPROFILE','home'))) {
    $privatePath=Join-Path $FixtureRoot $entry[1]
    Assert-AcceptancePath $privatePath -RequireAbsent
    New-Item -ItemType Directory -Path $privatePath | Out-Null
    [Environment]::SetEnvironmentVariable($entry[0],$privatePath,'Process')
  }
  $env:PYTHONPATH=$dependencies
  $env:PYTHONNOUSERSITE='1'
  $env:QT_QPA_PLATFORM='windows'
  $env:PATH=(Split-Path $PythonPath -Parent)+';'+$env:SYSTEMROOT+'\System32;'+$env:SYSTEMROOT
  $launcher=Join-Path $FixtureRoot 'source_launcher.py'
  Assert-AcceptancePath $launcher -RequireAbsent
  @'
from pathlib import Path
import sys
if __name__ == '__main__':
    sys.path.insert(0, sys.argv[1])
    from trading_runtime import run_window
    raise SystemExit(run_window(root=Path(sys.argv[2]), research_bootstrap=Path(sys.argv[3])))
'@ | Set-Content -LiteralPath $launcher -Encoding UTF8
  $book=Join-Path $FixtureRoot 'trading'
  $research=Join-Path $FixtureRoot 'research'
  $arguments=@(('"'+$launcher+'"'),('"'+$root+'"'),('"'+$book+'"'),('"'+$research+'"'))
  $gui=Start-OwnedAcceptanceProcess $PythonPath -ArgumentList $arguments -WorkingDirectory $root -ExpectedImage $PythonPath
  Wait-OwnedAcceptanceWindow $gui
  Start-Sleep -Seconds 2
  $global:acceptanceDiagnosticPhase='native_navigation'
  $closeClock=[Diagnostics.Stopwatch]::StartNew()
  $proof=Close-OwnedUnifiedAcceptanceWindow $gui $closeClock
  $remaining=15000-$closeClock.ElapsedMilliseconds
  if ($remaining -le 0) { throw 'Window did not close cleanly' }
  Wait-OwnedAcceptanceProcess $gui ([int]$remaining) 'Window did not close cleanly' -DrainJob
  if ($gui.Process.get_ExitCode() -ne 0) { throw 'Source Qt window did not close cleanly' }
  $proof.status='passed'
  $proof.elapsed_milliseconds=$closeClock.ElapsedMilliseconds
  $proof.source_commit=$env:GITHUB_SHA
  $proof.private_source_ui=$true
  $proof.installer_acceptance=$false
  $proof | ConvertTo-Json | Set-Content (Join-Path $results 'result.json')
} catch {
  $primaryFailure=$_
  try { Write-AcceptanceWorkerFailure -Failure $primaryFailure -Path (Join-Path $results 'worker-failure.json') -Source encoded_wrapper -Phase $global:acceptanceDiagnosticPhase }
  catch { [Console]::Error.WriteLine('Source UI primary diagnostic unavailable') }
  $uiExited=$null; $uiExitCode=$null
  try {
    if ($gui) {
      $gui.Process.Refresh(); $uiExited=$gui.Process.get_HasExited()
      if ($uiExited) { $uiExitCode=$gui.Process.get_ExitCode() }
    }
    @{status='failed';private_source_ui=$true;installer_acceptance=$false;
      ui_exit_observed=$uiExited;ui_exit_code=$uiExitCode;
      close_elapsed_milliseconds=$(if ($closeClock) {$closeClock.ElapsedMilliseconds} else {$null})} |
      ConvertTo-Json | Set-Content (Join-Path $results 'application-exit-observation.json')
  } catch { [Console]::Error.WriteLine('Source UI exit observation unavailable; primary failure preserved') }
  throw
} finally { Close-AcceptanceProcesses }
