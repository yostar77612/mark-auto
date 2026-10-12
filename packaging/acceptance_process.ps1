# Windows-only lifecycle ownership and watchdog. No compiler runs during acceptance.
# Build this helper on CI with build_acceptance_helper.ps1 and verify the kit digest.

function Confirm-AcceptanceWorker([string]$JobName) {
  if (-not $JobName -or -not [MarkAutoAcceptanceJob]::Owns($JobName, [Diagnostics.Process]::GetCurrentProcess().Handle)) {
    throw 'Acceptance worker is not inside its creation-owned job'
  }
}
function Invoke-AcceptanceSupervisor([string]$ScriptPath, [System.Collections.IDictionary]$Parameters,
                                     [string]$ReportPath, [Diagnostics.Stopwatch]$Clock, [string]$FailureReportPath = '',
                                     [ValidateRange(10,1200)][int]$LimitSeconds = 1200) {
  $name = 'Local\MarkAutoAcceptance-' + [guid]::NewGuid().ToString('N')
  $command = "& '" + $ScriptPath.Replace("'", "''") + "' -AcceptanceJob '" + $name + "'"
  foreach ($key in $Parameters.Keys) {
    if ($key -eq 'AcceptanceJob') { continue }
    $value = $Parameters[$key]
    if ($value -is [System.Management.Automation.SwitchParameter]) {
      if ($value.IsPresent) { $command += ' -' + $key }
    } else { $command += " -" + $key + " '" + ([string]$value).Replace("'", "''") + "'" }
  }
  # EncodedCommand otherwise collapses a child script's exit 2 into exit 1.
  $command = '$ErrorActionPreference=''Stop''; $global:LASTEXITCODE=0; try { ' + $command + '; $ok=$?; $code=$global:LASTEXITCODE; if ($code -ne 0) { exit $code }; if (-not $ok) { exit 1 }; exit 0 } catch { [Console]::Error.WriteLine(''Acceptance worker failed; see saved evidence''); exit 1 }'
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  $engine = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
  $job = $null
  $status = 'failed'; $reason = 'cancelled_or_start_failed'; $code = 1
  $workerExited = $false; $workerExitCode = $null
  try {
    if ($Parameters['AcceptanceScope'] -eq 'PreparedHost' -and [MarkAutoAcceptanceJob]::FreeMemoryBytes() -lt 6GB) {
      $reason='host_free_memory_below_6GiB'; throw 'Host free memory is below the unchanged 6 GiB floor'
    }
    # Store the job before creating any process; Ctrl+C cannot discard an already-started job result.
    $job = New-Object MarkAutoAcceptanceJob($name)
    $job.Start($engine, "-NoProfile -NonInteractive -EncodedCommand $encoded")
    # Five seconds are reserved inside the cap for owned-job cancellation and reports.
    while ($Clock.Elapsed.TotalSeconds -lt ($LimitSeconds - 5)) {
      if ($Parameters['AcceptanceScope'] -eq 'PreparedHost' -and [MarkAutoAcceptanceJob]::FreeMemoryBytes() -lt 6GB) {
        $reason = 'host_free_memory_below_6GiB'; break
      }
      if (-not $workerExited -and $job.Wait(200)) { $workerExited=$true; $workerExitCode=$job.ExitCode; $code=$workerExitCode }
      if ($workerExited) {
        # Root exit alone does not finish an Inno process tree. Keep the job alive
        # until every owned descendant exits, or the unchanged deadline expires.
        if ($code -notin @(0,2)) { $status='completed'; $reason='worker_failed'; break }
        if ($job.ActiveProcesses -eq 0) { $status='completed'; $reason='worker_and_descendants_exit'; break }
        Start-Sleep -Milliseconds 100
      }
    }
    if ($status -ne 'completed') {
      if ($reason -ne 'host_free_memory_below_6GiB') {
        $reason = if ($workerExited) { 'owned_descendants_deadline' } else { 'whole_run_deadline' }
      }
      $code=1
      $job.Cancel(); [void]$job.Wait(1000)
    }
  } finally {
    $remainingOwned=$null
    try { if ($job) { $remainingOwned=$job.ActiveProcesses } }
    catch { $status='failed'; $reason='job_accounting_failed'; $code=1 }
    finally { if ($job) { $job.Dispose() } }
    $report = @{status=$status; reason=$reason; exit_code=$code; worker_exit_code=$workerExitCode;
      owned_processes_before_cleanup=$remainingOwned; limit_seconds=$LimitSeconds;
      elapsed_seconds=$Clock.Elapsed.TotalSeconds; cleanup='private creation-owned job closed';
      client_os_acceptance='BLOCKED'} | ConvertTo-Json
    [IO.File]::WriteAllText($ReportPath, $report)
    if ($FailureReportPath -and ($status -ne 'completed' -or $code -notin @(0,2))) {
      $failed = @{status='FAILED'; lifecycle='FAILED'; reason=$reason; full_functionality='BLOCKED';
        client_os_acceptance='BLOCKED'; live_trading='DISABLED'} | ConvertTo-Json
      [IO.File]::WriteAllText($FailureReportPath, $failed)
    }
  }
  return $code
}
function Start-OwnedAcceptanceProcess([string]$FilePath, [string[]]$ArgumentList = @(),
                                      [string]$ExpectedImage = $FilePath, [string]$WorkingDirectory = $env:TEMP) {
  Confirm-AcceptanceWorker $AcceptanceJob
  $before = [DateTime]::UtcNow.ToFileTimeUtc()
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $FilePath; $start.Arguments = $ArgumentList -join ' '
  $start.WorkingDirectory = $WorkingDirectory
  # Shell execution is required for the real .lnk acceptance case; executable launches never ask for elevation.
  $start.UseShellExecute = [IO.Path]::GetExtension($FilePath) -eq '.lnk'
  $process = [Diagnostics.Process]::Start($start)
  if (-not $process) { throw 'Launch returned no creation handle; no process will be adopted' }
  try {
    $handle = $process.Handle # Retain the creation-returned handle, never reopen by PID.
    $created = [MarkAutoAcceptanceJob]::Created($handle)
    if ($created -lt $before -or -not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob, $handle) -or
        [IO.Path]::GetFullPath([MarkAutoAcceptanceJob]::Image($handle)) -ne [IO.Path]::GetFullPath($ExpectedImage)) {
      throw 'Launch process identity or owned-job membership not proven'
    }
    $owned = @{Process=$process; Handle=$handle; Created=$created; Image=[IO.Path]::GetFullPath($ExpectedImage)}
    [void]$script:acceptanceProcesses.Add($owned)
    return $owned
  } catch { $process.Dispose(); throw }
}
function Assert-OwnedAcceptanceProcess($Owned) {
  if (-not $script:acceptanceProcesses.Contains($Owned) -or
      [MarkAutoAcceptanceJob]::Created($Owned.Handle) -ne $Owned.Created -or
      -not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob, $Owned.Handle)) { throw 'Process creation ownership changed' }
}
function Wait-OwnedAcceptanceProcess($Owned, [int]$Milliseconds, [string]$Failure, [switch]$DrainJob) {
  $phaseClock=[Diagnostics.Stopwatch]::StartNew()
  Assert-OwnedAcceptanceProcess $Owned
  if (-not $Owned.Process.WaitForExit($Milliseconds)) {
    [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob, $Owned.Handle)
    throw $Failure
  }
  if ($DrainJob) {
    Confirm-AcceptanceWorker $AcceptanceJob
    # Only use at phases with no intentionally live GUI. Count the private job;
    # never enumerate, adopt or signal descendant PIDs. One member is this worker.
    while ([MarkAutoAcceptanceJob]::OwnedActiveProcesses($AcceptanceJob) -ne 1) {
      if ($phaseClock.Elapsed.TotalMilliseconds -ge $Milliseconds) { throw $Failure }
      Start-Sleep -Milliseconds 50
    }
  }
}
function Close-AcceptanceProcesses {
  foreach ($owned in $script:acceptanceProcesses) {
    try { Assert-OwnedAcceptanceProcess $owned; [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob, $owned.Handle) }
    finally { $owned.Process.Dispose() }
  }
}
function Assert-AcceptancePath([string]$Path, [switch]$RequireAbsent) {
  $full = [IO.Path]::GetFullPath($Path)
  if ($full -notmatch '^[A-Za-z]:\\' -or $full.Substring(2).Contains(':')) { throw 'Only ordinary local acceptance paths are supported' }
  $inspect = $full
  while ($inspect) {
    if ('MarkAutoAcceptanceJob' -as [type]) {
      $attributes = [MarkAutoAcceptanceJob]::PathAttributes($inspect)
      $exists = $attributes -ne [uint32]::MaxValue
    } else {
      # Only used for read-only helper bootstrap before loading its verified DLL.
      # Every acceptance output/profile check below uses the native metadata handle.
      $item = $null
      try { $item = Get-Item -LiteralPath $inspect -Force -ErrorAction Stop }
      catch [System.Management.Automation.ItemNotFoundException] { }
      $exists = $null -ne $item
      $attributes = if ($exists) { [uint32]$item.Attributes } else { [uint32]::MaxValue }
    }
    if ($exists -and ($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse destination or ancestor refused; original state preserved' }
    if ($RequireAbsent -and $exists -and $inspect -eq $full) { throw 'Existing MarkAuto destination refused; original state preserved' }
    $parent = Split-Path $inspect -Parent
    if ($parent -eq $inspect) { break }
    $inspect = $parent
  }
}
function Assert-AbsentAcceptanceRegistration([string]$Registration) {
  foreach ($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryHive]::LocalMachine)) {
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
      $key = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
      try {
        $existing = $key.OpenSubKey($Registration, $false)
        if ($existing) { $existing.Dispose(); throw 'Existing MarkAuto registration refused; original state preserved' }
        "$hive/$view/$Registration"
      } finally { $key.Dispose() }
    }
  }
}
function Wait-OwnedAcceptanceWindow($Owned, [ValidateRange(1,30)][int]$Seconds = 30) {
  for ($i=0; $i -lt $Seconds; $i++) {
    Start-Sleep -Seconds 1
    Assert-OwnedAcceptanceProcess $Owned
    $Owned.Process.Refresh()
    if ($Owned.Process.HasExited) { throw 'Start menu process exited before showing a native window' }
    if ($Owned.Process.MainWindowHandle -ne 0) { return }
  }
  throw 'Start menu launch did not create a native window'
}

if (-not ('MarkAutoAcceptanceJob' -as [type])) {
  $assembly = Join-Path $PSScriptRoot 'acceptance_process.dll'
  if (-not (Test-Path -LiteralPath $assembly -PathType Leaf)) { throw 'Prebuilt acceptance helper is required; no host-side compilation is allowed' }
  Assert-AcceptancePath $assembly
  Add-Type -Path $assembly
}
