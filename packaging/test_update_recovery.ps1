param([string]$Version = '0.1.2',
      [Parameter(Mandatory=$true)][string]$BaselineInstaller,
      [Parameter(Mandatory=$true)][string]$BaselineManifest,
      [Parameter(Mandatory=$true)][string]$CandidateManifest)
# DESTRUCTIVE PROCESS INTERRUPTION TEST: only run in a disposable Windows test profile.
# Only the installer process tree started here is terminated. User data is never deleted.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path $PSScriptRoot -Parent
$results = Join-Path $root 'dist\validation\update-recovery'
New-Item $results -ItemType Directory -Force | Out-Null
$appDir = Join-Path $env:LOCALAPPDATA 'Programs\MarkAuto'
$dataDir = Join-Path $env:LOCALAPPDATA 'MarkAuto'
$settingsPath = Join-Path $dataDir 'state-v1\settings.json'
$settingsDigest = $null
if ((Test-Path -LiteralPath $settingsPath) -or (Test-Path -LiteralPath (Join-Path $dataDir 'workspace-location.json'))) {
  throw 'Unknown settings/workspace state: refusing to overwrite or relocate existing user preferences'
}
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'
$candidate = Join-Path $root "dist\installers\MarkAuto-$Version-windows-x64-setup.exe"
$shell = New-Object -ComObject WScript.Shell
if (Test-Path "$appDir\unins000.exe") { throw 'Recovery test requires no installed app; run lifecycle uninstall first in a disposable profile' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Existing app shortcut: refusing to replace an unknown installation' }
function Assert-Artifact([string]$file, [string]$manifestPath) {
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $property = $manifest.artifacts_sha256.PSObject.Properties[(Split-Path $file -Leaf)]
  if (-not $property -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw 'Installer digest does not match supplied release manifest' }
}
Assert-Artifact $BaselineInstaller $BaselineManifest
Assert-Artifact $candidate $CandidateManifest
if ((Split-Path $BaselineInstaller -Leaf) -ne 'MarkAuto-0.1.1-windows-x64-setup.exe') { throw 'Recovery baseline must be the actual released 0.1.1 artifact' }
function Run-Setup([string]$installer, [string]$stage) {
  $p = Start-Process $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\$stage.log`"") -PassThru -Wait
  if ($p.ExitCode -ne 0) { throw "$stage failed: $($p.ExitCode)" }
}
function Target([string]$link) {
  if (-not (Test-Path -LiteralPath $link)) { throw "Missing shortcut: $link" }
  return $shell.CreateShortcut($link).TargetPath
}
function Assert-ActualSettings {
  if ($settingsDigest -and (-not (Test-Path -LiteralPath $settingsPath) -or (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash -ne $settingsDigest)) {
    throw 'Actual app settings changed or disappeared'
  }
}
function Smoke([string]$exe, [string]$versionExpected, [string]$stage) {
  Assert-ActualSettings
  $report = Join-Path $results "$stage.json"
  $p = Start-Process $exe -ArgumentList @('--smoke-test',"`"$report`"") -WorkingDirectory $env:TEMP -PassThru
  if (-not $p.WaitForExit(180000)) { $p.Kill(); throw 'Recovery smoke timed out' }
  if ($p.ExitCode -ne 0) { throw 'Recovery smoke failed' }
  $evidence = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
  if ($evidence.status -ne 'passed' -or $evidence.version -ne $versionExpected -or $evidence.live_status -ne 'disabled' -or [IO.Path]::GetFullPath($evidence.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Recovery smoke evidence invalid or settings workspace not used' }
  Assert-ActualSettings
}
Run-Setup $BaselineInstaller 'baseline-install'
$oldExe = Target $startMenu
if ($oldExe -ne "$appDir\MarkAuto.exe" -or (Target $desktop) -ne $oldExe) { throw 'Released baseline shortcut layout changed' }
Smoke $oldExe '0.1.1' 'baseline-smoke'
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
Smoke $oldExe '0.1.1' 'baseline-existing-settings-smoke'
# Freeze old-payload and unknown-file expectations before invoking the candidate.
$obsolete = Join-Path $appDir '_internal\obsolete-test.dll'
if (Test-Path $obsolete) { throw 'Unexpected preexisting test marker' }
[IO.File]::WriteAllBytes($obsolete, [Text.Encoding]::UTF8.GetBytes('never load this retired dependency'))
$prior = @{}
foreach ($file in Get-ChildItem -LiteralPath $appDir -Recurse -File) {
  if ($file.DirectoryName -eq $appDir -and $file.Name -like 'unins*') { continue }
  if ($file.FullName.StartsWith("$appDir\payloads\", [StringComparison]::OrdinalIgnoreCase)) { continue }
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
Smoke $oldExe '0.1.1' 'interrupted-before-activation'
# Recovery is a normal rerun of the exact candidate, with a fresh immutable directory.
Run-Setup $candidate 'retry-install'
$newExe = Target $startMenu
$newDir = Split-Path $newExe -Parent
if (-not $newDir.StartsWith("$payloadRoot\", [StringComparison]::OrdinalIgnoreCase) -or $newDir -eq $partial -or (Target $desktop) -ne $newExe) { throw 'Retry did not activate one fresh payload' }
if (Test-Path (Join-Path $newDir '_internal\obsolete-test.dll')) { throw 'Obsolete dependency leaked into new payload' }
$inventory = @(Get-Content -LiteralPath (Join-Path $newDir 'payload-inventory.txt'))
foreach ($row in $inventory) {
  if ($row -notmatch '^([0-9a-f]{64})  (.+)$') { throw 'Malformed active inventory' }
  $digest = $Matches[1]; $relative = $Matches[2]
  if ((Get-FileHash -LiteralPath (Join-Path $newDir $relative) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'Active payload hash mismatch' }
}
if (@(Get-ChildItem -LiteralPath $newDir -Recurse -File).Count -ne $inventory.Count + 1) { throw 'Unexpected active payload file' }
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
Smoke $firstTarget $Version 'retained-candidate-smoke'
Smoke $secondTarget $Version 'reinstalled-smoke'
Assert-PriorPayload
Assert-Sentinels
@{status='passed'; baseline='released 0.1.1'; candidate=$Version;
  interruption='actual setup process tree killed during extraction before inventory/shortcut activation';
  recovery='rerun exact candidate; fresh payload verified before both shortcuts activate';
  split_shortcut_recovery='constructed old/new shortcut state, repaired by actual ordinary rerun; not an additional crash checkpoint';
  preserved_prior_files=$prior.Count; preserved_data_sentinels=$sentinels.Count;
  actual_settings=@{relative_path='state-v1/settings.json'; schema_version=1; sha256=$settingsDigest;
    fixture='non-sensitive existing-schema preferences, created only when absent';
    execution='released 0.1.1 and candidate startup load actual settings; bytes checked before and after every subsequent smoke';
    scope='compatible existing settings preservation, not historical schema migration'};
  partial_payload=$partial; prior_target=$oldExe; first_verified_target=$firstTarget; active_target=$secondTarget;
  limitations=@('One real process-crash extraction checkpoint, not exhaustive power-loss durability proof',
    'Windows Server CI is not independent Windows 10/11 client acceptance',
    'Unknown preexisting files and interrupted/orphan payload directories are retained; no wildcard cleanup')
} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $results 'update-recovery-results.json')
