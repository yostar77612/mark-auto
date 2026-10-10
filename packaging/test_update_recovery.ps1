param([ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.2.2',
      [ValidatePattern('^\d+\.\d+\.\d+$')][string]$BaselineVersion = '0.1.1',
      [Parameter(Mandatory=$true)][string]$BaselineInstaller,
      [Parameter(Mandatory=$true)][string]$BaselineManifest,
      [Parameter(Mandatory=$true)][string]$CandidateManifest,
      [string]$LifecycleHandoff = '')
# DESTRUCTIVE PROCESS INTERRUPTION TEST: only run in a disposable Windows test profile.
# Only the installer process tree started here is terminated. User data is never deleted.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path $PSScriptRoot -Parent
$results = Join-Path $root 'dist\validation\update-recovery'
New-Item $results -ItemType Directory -Force | Out-Null
$appDir = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\MarkAuto'))
$dataDir = Join-Path $env:LOCALAPPDATA 'MarkAuto'
$settingsPath = Join-Path $dataDir 'state-v1\settings.json'
$settingsDigest = $null
$lifecycleArchive = $lifecycleArchiveDigest = $null
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'
$candidate = Join-Path $root "dist\installers\MarkAuto-$Version-windows-x64-setup.exe"
$shell = New-Object -ComObject WScript.Shell
if (Test-Path "$appDir\unins000.exe") { throw 'Recovery test requires no installed app; run lifecycle uninstall first in a disposable profile' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Existing app shortcut: refusing to replace an unknown installation' }
function Assert-Artifact([string]$file, [string]$manifestPath) {
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  if ($manifest.source_commit -notmatch '^[0-9a-fA-F]{40}$') { throw 'Release manifest must identify its exact source commit' }
  $property = $manifest.artifacts_sha256.PSObject.Properties[(Split-Path $file -Leaf)]
  if (-not $property -or $property.Value -notmatch '^[0-9a-fA-F]{64}$' -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw 'Installer digest does not match supplied release manifest' }
  return $manifest
}
if ((Split-Path $BaselineInstaller -Leaf) -ne "MarkAuto-$BaselineVersion-windows-x64-setup.exe") { throw 'Recovery baseline filename must match the explicitly requested released version' }
$baselineEvidence = Assert-Artifact $BaselineInstaller $BaselineManifest
$candidateEvidence = Assert-Artifact $candidate $CandidateManifest
function Run-Setup([string]$installer, [string]$stage) {
  $p = Start-Process $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\$stage.log`"") -PassThru -Wait
  if ($p.ExitCode -ne 0) { throw "$stage failed: $($p.ExitCode)" }
}
function Assert-NoReparsePath([string]$path) {
  $current = [IO.Path]::GetFullPath($path)
  while ($current) {
    $item = Get-Item -LiteralPath $current -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse path refused in recovery evidence or shortcut' }
    $parent = Split-Path $current -Parent
    if ($parent -eq $current) { break }
    $current = $parent
  }
}
function Get-OptionalStateItem([string]$path) {
  try { return Get-Item -LiteralPath $path -Force -ErrorAction Stop }
  catch [System.Management.Automation.ItemNotFoundException] { return $null }
}
function Preserve-OwnedLifecycleSettings {
  if (-not $LifecycleHandoff) { return }
  $expectedReceipt = [IO.Path]::GetFullPath((Join-Path $root 'dist\validation\lifecycle-state-handoff.json'))
  if ([IO.Path]::GetFullPath($LifecycleHandoff) -ne $expectedReceipt) { throw 'Unexpected lifecycle ownership receipt path' }
  Assert-NoReparsePath $LifecycleHandoff
  $receipt = Get-Content -LiteralPath $LifecycleHandoff -Raw | ConvertFrom-Json
  $candidateHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($receipt.schema_version -ne 1 -or $receipt.owner -ne 'installer-lifecycle-test' -or
      $receipt.initial_settings_absent -ne $true -or $receipt.initial_workspace_pointer_absent -ne $true -or
      $receipt.lifecycle_passed -ne $true -or $receipt.candidate_version -ne $Version -or
      $receipt.candidate_sha256 -ne $candidateHash -or $receipt.settings_relative_path -ne 'state-v1/settings.json' -or
      [IO.Path]::GetFullPath($receipt.app_data_path) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Lifecycle state ownership not proven' }
  if (Get-OptionalStateItem (Join-Path $dataDir 'workspace-location.json')) { throw 'Unknown workspace pointer cannot be handed off' }
  if ($receipt.settings_created -eq $false) {
    if (Get-OptionalStateItem $settingsPath) { throw 'Settings appeared after ownership receipt' }
    return
  }
  if ($receipt.settings_created -ne $true -or $receipt.settings_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid lifecycle settings evidence' }
  Assert-NoReparsePath $settingsPath
  if ((Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $receipt.settings_sha256) { throw 'Lifecycle settings changed after ownership receipt; original preserved' }
  # Preserve exact bytes at an exclusive sibling path. Never reset/delete state.
  $archive = $settingsPath + '.lifecycle-' + [guid]::NewGuid().ToString('N') + '.preserved'
  [IO.File]::Move($settingsPath, $archive)
  if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $receipt.settings_sha256) { throw 'Archived lifecycle settings hash mismatch' }
  $script:lifecycleArchive = $archive
  $script:lifecycleArchiveDigest = $receipt.settings_sha256
  @{status='preserved'; owner='installer-lifecycle-test'; archive_path=$archive;
    sha256=$receipt.settings_sha256; candidate_sha256=$candidateHash;
    scope='Only settings proven absent before lifecycle and unchanged since its receipt were relocated; no deletion'} |
    ConvertTo-Json | Set-Content (Join-Path $results 'lifecycle-state-preservation.json')
}
function Get-SafePayloadFiles([string]$directory) {
  Assert-NoReparsePath $directory
  foreach ($entry in Get-ChildItem -LiteralPath $directory -Force) {
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse entry refused before payload traversal' }
    if ($entry.PSIsContainer) { Get-SafePayloadFiles $entry.FullName } else { $entry }
  }
}
function Assert-PayloadTarget([string]$exe, [string]$expectedVersion) {
  # GetFullPath expands existing 8.3 names (for example RUNNER~1 in TEMP).
  # Compare canonical trusted paths, not raw spelling; reject traversal explicitly.
  if ($exe -notmatch '^[A-Za-z]:\\' -or $exe.Substring(2).Contains(':') -or $exe -match '(^|[\\/])\.\.?([\\/]|$)') { throw 'Executable path must be absolute local and contain no traversal or alternate stream' }
  $full = [IO.Path]::GetFullPath($exe)
  $trustedRoot = [IO.Path]::GetFullPath($appDir)
  if ((Split-Path $full -Leaf) -ne 'MarkAuto.exe') { throw 'Unexpected executable filename' }
  $directory = Split-Path $full -Parent
  if ($expectedVersion -eq '0.1.1') {
    if ($full -ne (Join-Path $trustedRoot 'MarkAuto.exe')) { throw 'Legacy baseline must use its exact root executable' }
  } else {
    $versionRoot = Join-Path $trustedRoot "payloads\$expectedVersion"
    if ((Split-Path $directory -Parent) -ne $versionRoot) { throw 'Executable must be inside one owned versioned payload directory' }
  }
  if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw 'Payload executable missing' }
  Assert-NoReparsePath $full
}
function Assert-Inventory([string]$directory) {
  $inventoryPath = Join-Path $directory 'payload-inventory.txt'
  Assert-NoReparsePath $inventoryPath
  $inventory = @(Get-Content -LiteralPath $inventoryPath)
  $seen = @{}
  foreach ($row in $inventory) {
    if ($row -notmatch '^([0-9a-f]{64})  (.+)$') { throw 'Malformed active inventory' }
    $digest = $Matches[1]; $relative = $Matches[2]
    if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or $relative -match '(^|[\\/])\.\.?([\\/]|$)' -or $seen.ContainsKey($relative)) { throw 'Unsafe or duplicate inventory path' }
    $seen[$relative] = $true
    $file = Join-Path $directory $relative
    Assert-NoReparsePath $file
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'Active payload hash mismatch' }
  }
  if (-not $seen.ContainsKey('MarkAuto.exe') -or @(Get-SafePayloadFiles $directory).Count -ne $inventory.Count + 1) { throw 'Incomplete or unexpected active payload file' }
}
function Target([string]$link) {
  if (-not (Test-Path -LiteralPath $link)) { throw "Missing shortcut: $link" }
  Assert-NoReparsePath $link
  $target = $shell.CreateShortcut($link).TargetPath
  Assert-NoReparsePath $target
  return $target
}
function Assert-ActualSettings {
  if ($lifecycleArchive) {
    Assert-NoReparsePath $lifecycleArchive
    if ((Get-FileHash -LiteralPath $lifecycleArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lifecycleArchiveDigest) { throw 'Preserved lifecycle preferences changed or disappeared' }
  }
  if ($settingsDigest -and (-not (Test-Path -LiteralPath $settingsPath) -or (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash -ne $settingsDigest)) {
    throw 'Actual app settings changed or disappeared'
  }
}
function Smoke([string]$exe, [string]$versionExpected, [string]$stage) {
  Assert-ActualSettings
  Assert-PayloadTarget $exe $versionExpected
  $report = Join-Path $results "$stage.json"
  $p = Start-Process $exe -ArgumentList @('--smoke-test',"`"$report`"") -WorkingDirectory $env:TEMP -PassThru
  if (-not $p.WaitForExit(180000)) { $p.Kill(); throw 'Recovery smoke timed out' }
  if ($p.ExitCode -ne 0) { throw 'Recovery smoke failed' }
  $evidence = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
  if ($evidence.status -ne 'passed' -or $evidence.version -ne $versionExpected -or $evidence.live_status -ne 'disabled' -or [IO.Path]::GetFullPath($evidence.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Recovery smoke evidence invalid or settings workspace not used' }
  Assert-ActualSettings
}
function Assert-ReleasedWorkspaceGuard([string]$exe) {
  # Reuse the already verified/installed release, never fetch another installer.
  # Exact 0.2.1 desktop.py checks WorkspaceLocator before MainWindow or SQLite;
  # --smoke-test catches that RuntimeSafetyError and exits without a GUI dialog.
  if ($BaselineVersion -ne '0.2.1') {
    return @{status='not_run'; reason='Native guard proof is scoped to the exact published 0.2.1 baseline'}
  }
  if ($baselineEvidence.source_commit -ne '2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8') {
    throw 'Required 0.2.1 native guard proof has an unexpected baseline source commit'
  }
  Assert-PayloadTarget $exe $BaselineVersion
  Assert-ActualSettings
  $pointer = Join-Path $dataDir 'workspace-location.json'
  if (Get-OptionalStateItem $pointer) { throw 'Guard proof requires absent workspace pointer; existing preferences preserved' }
  $fixture = Join-Path $results ('guarded-workspace-' + [guid]::NewGuid().ToString('N'))
  New-Item (Join-Path $fixture 'state-v1\replays') -ItemType Directory | Out-Null
  $marker = '{"kind":"markauto_workspace","schema_version":1,"sqlite_replay":{"profile":"wal_full","minimum_runtime":"3.51.3"}}'
  [IO.File]::WriteAllBytes((Join-Path $fixture 'workspace-format.json'), [Text.Encoding]::UTF8.GetBytes($marker))
  # Deliberately not a database: the proof must refuse before attempting SQLite.
  foreach ($name in @('proof.sqlite3', 'proof.sqlite3-wal', 'proof.sqlite3-shm')) {
    [IO.File]::WriteAllBytes((Join-Path $fixture "state-v1\replays\$name"), [Text.Encoding]::UTF8.GetBytes('must remain unopened: ' + $name))
  }
  $before = @{}
  foreach ($file in Get-SafePayloadFiles $fixture) {
    $before[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
  }
  $pointerBytes = [Text.Encoding]::UTF8.GetBytes((@{schema_version=1; root=$fixture} | ConvertTo-Json -Compress))
  $pointerCreated = $false
  $pointerDigest = $null
  $report = Join-Path $results 'released-wal-workspace-refusal.json'
  if (Get-OptionalStateItem $report) { throw 'Guard refusal report already exists; refusing stale proof' }
  try {
    $stream = [IO.File]::Open($pointer, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $pointerCreated = $true
    try { $stream.Write($pointerBytes, 0, $pointerBytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    $pointerDigest = (Get-FileHash -LiteralPath $pointer -Algorithm SHA256).Hash
    $p = Start-Process $exe -ArgumentList @('--smoke-test',"`"$report`"") -WorkingDirectory $env:TEMP -PassThru
    if (-not $p.WaitForExit(30000)) {
      & taskkill.exe /PID $p.Id /T /F | Out-Null
      if (-not $p.WaitForExit(15000)) { throw 'Owned old-runtime guard process did not exit after timeout' }
      throw 'Old-runtime workspace refusal timed out; no pass claimed'
    }
    if ($p.ExitCode -ne 1) { throw 'Old runtime did not return the expected startup refusal exit code' }
    if (-not (Test-Path -LiteralPath $report -PathType Leaf)) { throw 'Old-runtime guard refusal report missing' }
    $evidence = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($evidence.status -ne 'failed' -or $evidence.version -ne '0.2.1' -or
        $evidence.market_smoke.error_type -ne 'RuntimeSafetyError' -or @($evidence.steps).Count -ne 0 -or
        $evidence.live_status -ne 'disabled') { throw 'Old-runtime refusal was not the expected pre-worker safety failure' }
    $after = @(Get-SafePayloadFiles $fixture)
    if ($after.Count -ne $before.Count) { throw 'Old runtime added or removed guarded workspace files' }
    foreach ($file in $after) {
      if (-not $before.ContainsKey($file.FullName) -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne $before[$file.FullName]) {
        throw 'Old runtime changed guarded workspace bytes'
      }
    }
    Assert-ActualSettings
    return @{status='passed'; baseline_version=$BaselineVersion; baseline_source_commit=$baselineEvidence.source_commit;
      executable=$exe; report=$report; fixture=$fixture; exit_code=$p.ExitCode; unchanged_files=$before.Count;
      scope='Actual released EXE refuses guarded workspace before worker/SQLite startup; sentinel files are not databases';
      archive_refusal='Exact released-source test only; no old-EXE backup-restore command-line entrypoint'}
  } finally {
    if ($pointerCreated) {
      Assert-NoReparsePath $pointer
      if (-not $pointerDigest -or (Get-FileHash -LiteralPath $pointer -Algorithm SHA256).Hash -ne $pointerDigest) {
        throw 'Owned guard pointer changed; preserve it for diagnosis instead of deleting unknown state'
      }
      # Only the exact test-created, unchanged pointer is removed. Fixture stays.
      [IO.File]::Delete($pointer)
    }
  }
}
Preserve-OwnedLifecycleSettings
if ((Get-OptionalStateItem $settingsPath) -or (Get-OptionalStateItem (Join-Path $dataDir 'workspace-location.json'))) {
  throw 'Unknown settings/workspace state: refusing to overwrite or relocate existing user preferences'
}
# Refuse a redirected existing install root before even the legacy installer runs.
Assert-NoReparsePath $env:LOCALAPPDATA
$programsDir = Split-Path $appDir -Parent
if (Get-Item -LiteralPath $programsDir -Force -ErrorAction SilentlyContinue) { Assert-NoReparsePath $programsDir }
if (Get-Item -LiteralPath $appDir -Force -ErrorAction SilentlyContinue) { [void]@(Get-SafePayloadFiles $appDir) }
Run-Setup $BaselineInstaller 'baseline-install'
$oldExe = Target $startMenu
Assert-PayloadTarget $oldExe $BaselineVersion
$oldDir = Split-Path $oldExe -Parent
if ((Target $desktop) -ne $oldExe) { throw 'Released baseline shortcuts disagree' }
if ($BaselineVersion -ne '0.1.1') { Assert-Inventory $oldDir }
Smoke $oldExe $BaselineVersion 'baseline-smoke'
# Released 5943b6e SettingsStore uses this exact schema at state-v1/settings.json.
# Both released and candidate desktop startup load it; no schema migration claim.
foreach ($directory in @($dataDir, (Split-Path $settingsPath -Parent))) {
  if (((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing settings fixture through a reparse directory' }
}
$settingsFixture = '{"schema_version":1,"settings":{"max_calls":3,"max_tokens":10000,"persist_logs":false,"local_notifications":false}}'
$settingsBytes = [Text.Encoding]::UTF8.GetBytes($settingsFixture)
$stream = [IO.File]::Open($settingsPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try { $stream.Write($settingsBytes, 0, $settingsBytes.Length) } finally { $stream.Dispose() }
$settingsDigest = (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash
Smoke $oldExe $BaselineVersion 'baseline-existing-settings-smoke'
$workspaceGuardEvidence = Assert-ReleasedWorkspaceGuard $oldExe
# Freeze old-payload and unknown-file expectations before invoking the candidate.
$obsolete = Join-Path $oldDir '_internal\obsolete-test.dll'
Assert-NoReparsePath (Split-Path $obsolete -Parent)
if (Test-Path $obsolete) { throw 'Unexpected preexisting test marker' }
[IO.File]::WriteAllBytes($obsolete, [Text.Encoding]::UTF8.GetBytes('never load this retired dependency'))
$prior = @{}
foreach ($file in Get-SafePayloadFiles $appDir) {
  if ($file.DirectoryName -eq $appDir -and $file.Name -match '^unins\d+\.(exe|dat|msg)$') { continue }
  $prior[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
}
$sentinels = @{}
$sentinelRoot = Join-Path $dataDir ('recovery-sentinels-' + [guid]::NewGuid().ToString('N'))
foreach ($relative in @('settings\preferences.json','history\run.json','reports\report.csv','cache\cache.bin','user-files\keep.txt')) {
  $path = Join-Path $sentinelRoot $relative
  New-Item (Split-Path $path -Parent) -ItemType Directory -Force | Out-Null
  [IO.File]::WriteAllBytes($path, [Text.Encoding]::UTF8.GetBytes([guid]::NewGuid().ToString()))
  $sentinels[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
function Assert-PriorPayload {
  foreach ($path in $prior.Keys) {
    Assert-NoReparsePath $path
    if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $prior[$path]) { throw "Prior runtime changed: $path" }
  }
}
function Assert-Sentinels {
  Assert-ActualSettings
  foreach ($path in $sentinels.Keys) {
    if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $sentinels[$path]) { throw 'User data sentinel changed' }
  }
}
# A real directory junction at the expected root must fail closed, without writes.
$backupDir = $appDir + '.recovery-' + [guid]::NewGuid().ToString('N')
[IO.Directory]::Move($appDir, $backupDir)
try {
  New-Item -ItemType Junction -Path $appDir -Target $backupDir | Out-Null
  $refused = Start-Process $candidate -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\reparse-refused.log`"") -PassThru
  if (-not $refused.WaitForExit(30000)) { & taskkill.exe /PID $refused.Id /T /F | Out-Null; throw 'Reparse-path setup did not refuse promptly' }
  if ($refused.ExitCode -eq 0) { throw 'Reparse-path setup was not rejected' }
} finally {
  if (Test-Path -LiteralPath $appDir) {
    $junction = Get-Item -LiteralPath $appDir -Force
    if (($junction.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -or @($junction.Target)[0] -ne $backupDir) {
      throw 'Unexpected path replacement: refusing recovery cleanup'
    }
    # Nonrecursive removal of this exact test-created link, never its target.
    [IO.Directory]::Delete($appDir, $false)
  }
  [IO.Directory]::Move($backupDir, $appDir)
}
Assert-PriorPayload
Assert-Sentinels
$payloadRoot = Join-Path $appDir "payloads\$Version"
$existing = @(if (Test-Path $payloadRoot) { Get-ChildItem -LiteralPath $payloadRoot -Directory | ForEach-Object { $_.FullName } })
$interruptedLog = Join-Path $results 'interrupted-install.log'
$p = Start-Process $candidate -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$interruptedLog`"") -PassThru
$watch = [Diagnostics.Stopwatch]::StartNew()
$partial = $null
try {
  while ($watch.Elapsed.TotalSeconds -lt 120 -and -not $p.HasExited) {
    if (Test-Path $payloadRoot) {
      foreach ($directory in Get-ChildItem -LiteralPath $payloadRoot -Directory) {
        if ($existing -contains $directory.FullName) { continue }
        $files = @(Get-ChildItem -LiteralPath $directory.FullName -File -Recurse -ErrorAction SilentlyContinue)
        if ($files.Count -gt 0 -and -not (Test-Path (Join-Path $directory.FullName 'payload-inventory.txt'))) {
          $partial = $directory.FullName
          & taskkill.exe /PID $p.Id /T /F | Out-File (Join-Path $results 'taskkill.txt')
          if ($LASTEXITCODE -ne 0) { throw 'Could not interrupt the owned installer process tree' }
          break
        }
      }
    }
    if ($partial) { break }
    Start-Sleep -Milliseconds 5
    $p.Refresh()
  }
} finally {
  $p.Refresh()
  if (-not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null }
}
if (-not $partial) { throw 'BLOCKED: real extraction-interruption checkpoint not observed; no crash-recovery pass claimed' }
if (-not $p.WaitForExit(30000)) { throw 'Interrupted setup did not exit' }
Start-Sleep -Seconds 2
if (Test-Path (Join-Path $partial 'payload-inventory.txt')) { throw 'Interruption occurred too late to prove incomplete extraction; repeat on disposable VM' }
if ((Target $startMenu) -ne $oldExe -or (Target $desktop) -ne $oldExe) { throw 'Incomplete payload activated' }
Assert-PriorPayload
Assert-Sentinels
Smoke $oldExe $BaselineVersion 'interrupted-before-activation'
# Recovery is a normal rerun of the exact candidate, with a fresh immutable directory.
Run-Setup $candidate 'retry-install'
$newExe = Target $startMenu
$newDir = Split-Path $newExe -Parent
if (-not $newDir.StartsWith("$payloadRoot\", [StringComparison]::OrdinalIgnoreCase) -or $newDir -eq $partial -or (Target $desktop) -ne $newExe) { throw 'Retry did not activate one fresh payload' }
if (Test-Path (Join-Path $newDir '_internal\obsolete-test.dll')) { throw 'Obsolete dependency leaked into new payload' }
Assert-PayloadTarget $newExe $Version
Assert-Inventory $newDir
Assert-PriorPayload
Assert-Sentinels
Smoke $newExe $Version 'recovered-smoke'
# Construct the possible split-shortcut state explicitly; this is NOT reported as
# a second real process-crash checkpoint. Both targets have already been run.
$desktopLink = $shell.CreateShortcut($desktop)
$desktopLink.TargetPath = $oldExe
$desktopLink.WorkingDirectory = Split-Path $oldExe -Parent
$desktopLink.Save()
if ((Target $startMenu) -ne $newExe -or (Target $desktop) -ne $oldExe) { throw 'Split-shortcut recovery precondition failed' }
# A same-version retry repairs both links without mutating a verified payload.
$firstTarget = $newExe
Run-Setup $candidate 'same-version-reinstall'
$secondTarget = Target $startMenu
if ($secondTarget -eq $firstTarget -or (Target $desktop) -ne $secondTarget) { throw 'Same-version install reused an existing payload' }
Assert-PayloadTarget $secondTarget $Version
Assert-Inventory (Split-Path $firstTarget -Parent)
Assert-Inventory (Split-Path $secondTarget -Parent)
Smoke $firstTarget $Version 'retained-candidate-smoke'
Smoke $secondTarget $Version 'reinstalled-smoke'
Assert-PriorPayload
Assert-Sentinels
@{status='passed'; baseline="released $BaselineVersion"; candidate=$Version;
  baseline_source_commit=$baselineEvidence.source_commit; candidate_source_commit=$candidateEvidence.source_commit;
  released_workspace_guard=$workspaceGuardEvidence;
  interruption='actual setup process tree killed during extraction before inventory/shortcut activation';
  recovery='rerun exact candidate; fresh payload verified before both shortcuts activate';
  split_shortcut_recovery='constructed old/new shortcut state, repaired by actual ordinary rerun; not an additional crash checkpoint';
  preserved_prior_files=$prior.Count; preserved_data_sentinels=$sentinels.Count;
  lifecycle_settings_archive=@{path=$lifecycleArchive; sha256=$lifecycleArchiveDigest; deleted=$false};
  actual_settings=@{relative_path='state-v1/settings.json'; schema_version=1; sha256=$settingsDigest;
    fixture='non-sensitive existing-schema preferences, created only when absent';
    execution="released $BaselineVersion and candidate startup load actual settings; bytes checked before and after every subsequent smoke";
    scope='compatible existing settings preservation, not historical schema migration'};
  partial_payload=$partial; prior_target=$oldExe; first_verified_target=$firstTarget; active_target=$secondTarget;
  limitations=@('One real process-crash extraction checkpoint, not exhaustive power-loss durability proof',
    'Windows Server CI is not independent Windows 10/11 client acceptance',
    'Unknown preexisting files and interrupted/orphan payload directories are retained; no wildcard cleanup')
} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $results 'update-recovery-results.json')
