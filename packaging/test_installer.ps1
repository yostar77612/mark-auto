param([string]$Version = '0.2.1', [string]$BaselineVersion = '0.0.0',
      [string]$BaselineAppVersion = '', [string]$BaselineManifest = '', [string]$CandidateManifest = '',
      [switch]$CreateRecoveryHandoff)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $BaselineAppVersion) { $BaselineAppVersion = $Version }
$root = Split-Path $PSScriptRoot -Parent
$results = Join-Path $root 'dist\validation'
New-Item $results -ItemType Directory -Force | Out-Null
$os = Get-CimInstance Win32_OperatingSystem
@{caption=$os.Caption; version=$os.Version; build=$os.BuildNumber; architecture=$os.OSArchitecture;
  runner_image=$env:ImageOS; runner_image_version=$env:ImageVersion;
  windows_10_22h2_clean='BLOCKED: requires independent clean client VM';
  windows_11_clean='BLOCKED: requires independent clean client VM'} | ConvertTo-Json | Set-Content "$results\os-evidence.json"
$appDir = Join-Path $env:LOCALAPPDATA 'Programs\MarkAuto'
$dataDir = Join-Path $env:LOCALAPPDATA 'MarkAuto'
$handoffSettings = Join-Path $dataDir 'state-v1\settings.json'
$handoffPath = Join-Path $results 'lifecycle-state-handoff.json'
function Get-OptionalStateItem([string]$path) {
  try { return Get-Item -LiteralPath $path -Force -ErrorAction Stop }
  catch [System.Management.Automation.ItemNotFoundException] { return $null }
}
if ($CreateRecoveryHandoff) {
  # Ownership begins before any test launch, never inferred merely from location.
  foreach ($unknown in @($handoffSettings, (Join-Path $dataDir 'workspace-location.json'), (Join-Path $dataDir 'installer-preservation-test.txt'), $handoffPath)) {
    if (Get-OptionalStateItem $unknown) { throw 'Recovery handoff requires absent initial settings/workspace/receipt; existing state preserved' }
  }
  $inspect = [IO.Path]::GetFullPath($handoffSettings)
  while ($inspect) {
    $item = Get-OptionalStateItem $inspect
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse state cannot be owned by lifecycle test' }
    $inspect = Split-Path $inspect -Parent
  }
}
New-Item $dataDir -ItemType Directory -Force | Out-Null
$sentinel = Join-Path $dataDir 'installer-preservation-test.txt'
$sentinelValue = [guid]::NewGuid().ToString()
Set-Content $sentinel $sentinelValue
function Assert-Sentinel {
  if (-not (Test-Path $sentinel) -or (Get-Content $sentinel -Raw).Trim() -ne $sentinelValue) { throw 'User data was modified or lost' }
}
function Install-Version([string]$number, [string]$manifestPath) {
  $manifest = if ($manifestPath) { Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } else { $null }
  $installer = Join-Path $root "dist\installers\MarkAuto-$number-windows-x64-setup.exe"
  if ($manifest) {
    $digest = $manifest.artifacts_sha256.PSObject.Properties[(Split-Path $installer -Leaf)].Value
    if ((Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'Installer does not match its build manifest' }
  }
  $p = Start-Process $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\install-$number.log`"") -Wait -PassThru
  if ($p.ExitCode) { throw "Installer failed: $($p.ExitCode)" }
  $startLink = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
  if (-not (Test-Path $startLink)) { throw 'Installed Start Menu shortcut missing' }
  $shortcutShell = New-Object -ComObject WScript.Shell
  $script:installedExe = $shortcutShell.CreateShortcut($startLink).TargetPath
  $activeDirectory = Split-Path $script:installedExe -Parent
  if (-not [IO.Path]::GetFullPath($script:installedExe).StartsWith(([IO.Path]::GetFullPath($appDir) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase) -or
      (Split-Path $script:installedExe -Leaf) -ne 'MarkAuto.exe' -or -not (Test-Path -LiteralPath $script:installedExe)) { throw 'Installed executable missing or shortcut escaped app directory' }
  $sourceHashes = @{}
  foreach ($name in @('core.py','data.py','strategies.py','backtest.py','research.py','provider.py')) {
    $shipped = Join-Path $activeDirectory "_internal\quantlab\$name"
    if (-not (Test-Path $shipped)) { throw "Engine source missing from installed bundle: $name" }
    $actual = (Get-FileHash $shipped -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = if ($manifest) { ($manifest.inputs_sha256.PSObject.Properties | Where-Object { $_.Name.Replace('\','/') -eq "quantlab/$name" }).Value } else {
      (Get-FileHash (Join-Path $root "quantlab\$name") -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if ($actual -ne $expected) { throw "Installed engine source differs from build input: $name" }
    $sourceHashes[$name] = $actual
  }
  $sourceHashes | ConvertTo-Json | Set-Content "$results\installed-source-hashes-$number.json"
  Assert-Sentinel
}
function Smoke([string]$stage, [string]$expectedVersion) {
  $report = "$results\smoke-$stage.json"
  $oldPath = $env:PATH
  # Remove developer tools from lookup: the executable must use its bundled runtime.
  $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
  try {
    $p = Start-Process $script:installedExe -ArgumentList @('--smoke-test',"`"$report`"") -PassThru -WorkingDirectory $env:TEMP
    if (-not $p.WaitForExit(180000)) { $p.Kill(); throw 'Native Qt smoke timed out' }
    if ($p.ExitCode -ne 0) { throw "Native Qt smoke failed: $($p.ExitCode)" }
  } finally { $env:PATH = $oldPath }
  if (-not (Test-Path $report)) { throw 'Smoke report missing' }
  $json = Get-Content $report -Raw | ConvertFrom-Json
  if ($json.status -ne 'passed' -or $json.version -ne $expectedVersion -or $json.native_window_visible -ne $true -or $json.worker_completed -ne $true -or [IO.Path]::GetFullPath($json.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Smoke report invalid or app data not separated' }
  foreach ($field in @('backtest_completed','campaign_completed','paper_completed')) {
    if ($json.$field -ne $true) { throw "Frozen smoke operation did not pass: $field" }
  }
  if ($json.steps.Count -ne 7 -or @($json.steps | Where-Object { $_.passed -ne $true }).Count -ne 0) { throw 'Frozen seven-operation smoke incomplete' }
  if ($json.generator -ne 'fixture' -or $json.source_type -ne 'synthetic' -or $json.real_model_status -ne 'not_verified' -or $json.live_status -ne 'disabled') { throw 'Frozen smoke must be explicitly fixture-only with live trading disabled' }
  Assert-Sentinel
}
Install-Version $BaselineVersion $BaselineManifest
Smoke 'installed' $BaselineAppVersion
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'
$shell = New-Object -ComObject WScript.Shell
foreach ($link in @($startMenu, $desktop)) {
  if (-not (Test-Path $link)) { throw "Shortcut missing: $link" }
  if ($shell.CreateShortcut($link).TargetPath -ne $script:installedExe) { throw 'Shortcut target incorrect' }
}
Install-Version $Version $CandidateManifest
Smoke 'upgraded' $Version
# Launch normal mode via the Start-menu shortcut and check a real top-level window.
$launchClock = [Diagnostics.Stopwatch]::StartNew()
Start-Process $startMenu
$window = $null
for ($i=0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  $window = Get-Process MarkAuto -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if ($window) { break }
}
if (-not $window) { throw 'Start menu launch did not create a native window' }
$launchClock.Stop()
Start-Sleep -Seconds 2
$window.Refresh()
@{scope='Windows Server CI observation, not Windows 10/11 client SLO';
  startup_to_main_window_seconds=$launchClock.Elapsed.TotalSeconds;
  startup_sampling_interval_seconds=1;
  idle_working_set_bytes=$window.WorkingSet64;
  idle_sampling='Single sample two seconds after first detected main window, no task running';
  process_id=$window.Id; os_caption=$os.Caption; os_build=$os.BuildNumber} | ConvertTo-Json | Set-Content "$results\performance-observation.json"
# Running work must never be closed automatically by an upgrade or uninstall.
foreach ($attempt in @('upgrade', 'uninstall')) {
  $command = if ($attempt -eq 'upgrade') { Join-Path $root "dist\installers\MarkAuto-$Version-windows-x64-setup.exe" } else { "$appDir\unins000.exe" }
  $refused = Start-Process $command -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\refused-$attempt.log`"") -PassThru
  if (-not $refused.WaitForExit(30000)) { $refused.Kill(); throw "Active-app $attempt did not refuse promptly" }
  if ($refused.ExitCode -eq 0) { throw "Active-app $attempt was not rejected" }
  $window.Refresh()
  if ($window.HasExited) { throw "Active-app $attempt stopped the application" }
  Assert-Sentinel
}
[void]$window.CloseMainWindow()
if (-not $window.WaitForExit(15000)) { $window.Kill(); throw 'Window did not close cleanly' }
$p = Start-Process "$appDir\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\uninstall.log`"") -Wait -PassThru
if ($p.ExitCode) { throw "Uninstall failed: $($p.ExitCode)" }
if ((Test-Path $script:installedExe) -or (Test-Path "$appDir\MarkAuto.exe")) { throw 'Executable remains after uninstall' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Shortcut remains after uninstall' }
Assert-Sentinel
@{status='passed'; tests=@('install','bundled-runtime-launch','start-menu-shortcut','desktop-shortcut','version-upgrade','reject-active-upgrade','reject-active-uninstall','native-window-close','uninstall','preserve-user-data');
  upgrade_scope=$(if ($BaselineVersion -eq '0.0.0') { 'installer version upgrade with same application payload; not historical data schema migration' } else { 'distinct released versions; sentinel preservation only, historical schema migration requires separate evidence' });
  client_os_acceptance='BLOCKED'; signing='unsigned'} | ConvertTo-Json | Set-Content "$results\installer-results.json"

if ($CreateRecoveryHandoff) {
  if (Test-Path -LiteralPath (Join-Path $dataDir 'workspace-location.json')) { throw 'Unexpected workspace pointer; no ownership handoff issued' }
  $created = Test-Path -LiteralPath $handoffSettings -PathType Leaf
  $digest = if ($created) { (Get-FileHash -LiteralPath $handoffSettings -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
  $receipt = @{schema_version=1; owner='installer-lifecycle-test'; initial_settings_absent=$true;
    initial_workspace_pointer_absent=$true; lifecycle_passed=$true; candidate_version=$Version;
    candidate_sha256=(Get-FileHash -LiteralPath (Join-Path $root "dist\installers\MarkAuto-$Version-windows-x64-setup.exe") -Algorithm SHA256).Hash.ToLowerInvariant();
    app_data_path=[IO.Path]::GetFullPath($dataDir); settings_relative_path='state-v1/settings.json';
    settings_created=$created; settings_sha256=$digest}
  $bytes = [Text.Encoding]::UTF8.GetBytes(($receipt | ConvertTo-Json))
  $receiptStream = [IO.File]::Open($handoffPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
  try { $receiptStream.Write($bytes, 0, $bytes.Length) } finally { $receiptStream.Dispose() }
}
