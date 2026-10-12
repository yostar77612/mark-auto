# Windows-only lifecycle ownership and watchdog. No compiler runs during acceptance.
# Build this helper on CI with build_acceptance_helper.ps1 and verify the kit digest.
# Invoke safety-critical CLR getters explicitly: PowerShell property access suppresses
# getter exceptions to null, which can otherwise look like success or a live process.

function Confirm-AcceptanceWorker([string]$JobName) {
  if (-not $JobName -or -not [MarkAutoAcceptanceJob]::Owns($JobName, [Diagnostics.Process]::GetCurrentProcess().get_Handle())) {
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
  $engine = [Diagnostics.Process]::GetCurrentProcess().get_MainModule().get_FileName()
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
      if (-not $workerExited -and $job.Wait(200)) { $workerExited=$true; $workerExitCode=$job.get_ExitCode(); $code=$workerExitCode }
      if ($workerExited) {
        # Root exit alone does not finish an Inno process tree. Keep the job alive
        # until every owned descendant exits, or the unchanged deadline expires.
        if ($code -notin @(0,2)) { $status='completed'; $reason='worker_failed'; break }
        if ($job.get_ActiveProcesses() -eq 0) { $status='completed'; $reason='worker_and_descendants_exit'; break }
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
    $remainingOwned=$null; $cleanupVerified=$false
    try {
      if ($job) {
        $remainingOwned=$job.get_ActiveProcesses()
        if ($remainingOwned -gt 0) {
          $job.Cancel()
          # Use only the existing cleanup reserve; retain one second for disposal/reports.
          $cleanupDeadline=[Math]::Min($LimitSeconds-1,$Clock.Elapsed.TotalSeconds+4)
          while ($job.get_ActiveProcesses() -gt 0 -and $Clock.Elapsed.TotalSeconds -lt $cleanupDeadline) { Start-Sleep -Milliseconds 50 }
        }
        $cleanupVerified=($job.get_ActiveProcesses() -eq 0)
        if (-not $cleanupVerified) { $status='failed'; $reason='job_cleanup_unverified'; $code=1 }
      }
    } catch { $status='failed'; $reason='job_accounting_failed'; $code=1 }
    finally { if ($job) { $job.Dispose() } }
    $report = @{status=$status; reason=$reason; exit_code=$code; worker_exit_code=$workerExitCode;
      owned_processes_before_cleanup=$remainingOwned; cleanup_verified=$cleanupVerified; limit_seconds=$LimitSeconds;
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
  $script:acceptancePhase='direct_launch'
  if ([IO.Path]::GetExtension($FilePath) -ne '.lnk') {
    $launch=[MarkAutoAcceptanceJob]::StartOwned($AcceptanceJob,$FilePath,($ArgumentList -join ' '),$WorkingDirectory,$ExpectedImage)
    try {
      # The original native creation handle remains authoritative for this record.
      $owned=@{Process=$launch.Item1; NativeHandle=$launch.Item2; Handle=$launch.Item2.DangerousGetHandle(); Created=$launch.Item3; Image=$launch.Item4}
      [void]$script:acceptanceProcesses.Add($owned)
      return $owned
    } catch {
      try { [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob,$launch.Item2.DangerousGetHandle()) }
      finally { try { $launch.Item1.Dispose() } finally { $launch.Item2.Dispose() } }
      throw
    }
  }
  # Disposable-only actual shortcut case retains ShellExecute semantics; host scope
  # uses its already-validated direct target instead. No unrelated shell process is adopted.
  $before = [DateTime]::UtcNow.ToFileTimeUtc()
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $FilePath; $start.Arguments = $ArgumentList -join ' '
  $start.WorkingDirectory = $WorkingDirectory; $start.UseShellExecute = $true
  $script:acceptancePhase='shell_launch'
  $process = [Diagnostics.Process]::Start($start)
  if (-not $process) { throw 'Launch returned no creation handle; no process will be adopted' }
  try {
    $script:acceptancePhase='shell_creation_handle'
    $handle = $process.get_Handle()
    $script:acceptancePhase='shell_creation_identity'
    $created = [MarkAutoAcceptanceJob]::Created($handle)
    if ($created -lt $before) { throw 'Launch process creation identity not proven' }
    $script:acceptancePhase='shell_private_job'
    if (-not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$handle)) { throw 'Launch owned-job membership not proven' }
    $script:acceptancePhase='shell_image_identity'
    if ([IO.Path]::GetFullPath([MarkAutoAcceptanceJob]::Image($handle)) -ne [IO.Path]::GetFullPath($ExpectedImage)) { throw 'Launch process image not proven' }
    $owned = @{Process=$process; NativeHandle=$null; Handle=$handle; Created=$created; Image=[IO.Path]::GetFullPath($ExpectedImage)}
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
  $firstCleanupError=$null
  foreach ($owned in $script:acceptanceProcesses) {
    try { Assert-OwnedAcceptanceProcess $owned; [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob, $owned.Handle) }
    catch { if (-not $firstCleanupError) { $firstCleanupError=$_ } }
    finally {
      try { $owned.Process.Dispose() }
      catch { if (-not $firstCleanupError) { $firstCleanupError=$_ } }
      finally {
        try { if ($owned.NativeHandle) { $owned.NativeHandle.Dispose() } }
        catch { if (-not $firstCleanupError) { $firstCleanupError=$_ } }
      }
    }
  }
  if ($firstCleanupError) { throw $firstCleanupError }
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
      $attributes = if ($exists) { [uint32]$item.get_Attributes() } else { [uint32]::MaxValue }
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
    if ($Owned.Process.get_HasExited()) { throw 'Start menu process exited before showing a native window' }
    if ($Owned.Process.get_MainWindowHandle() -ne 0) { return }
  }
  throw 'Start menu launch did not create a native window'
}

if (-not ('MarkAutoAcceptanceJob' -as [type])) {
  $assembly = Join-Path $PSScriptRoot 'acceptance_process.dll'
  if (-not (Test-Path -LiteralPath $assembly -PathType Leaf)) { throw 'Prebuilt acceptance helper is required; no host-side compilation is allowed' }
  Assert-AcceptancePath $assembly
  Add-Type -Path $assembly
}
