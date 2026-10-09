param([string]$Version = '0.1.1')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
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
New-Item $dataDir -ItemType Directory -Force | Out-Null
$sentinel = Join-Path $dataDir 'installer-preservation-test.txt'
$sentinelValue = [guid]::NewGuid().ToString()
Set-Content $sentinel $sentinelValue
function Assert-Sentinel {
  if (-not (Test-Path $sentinel) -or (Get-Content $sentinel -Raw).Trim() -ne $sentinelValue) { throw 'User data was modified or lost' }
}
function Install-Version([string]$number) {
  $installer = Join-Path $root "dist\installers\MarkAuto-$number-windows-x64-setup.exe"
  $p = Start-Process $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\install-$number.log`"") -Wait -PassThru
  if ($p.ExitCode) { throw "Installer failed: $($p.ExitCode)" }
  if (-not (Test-Path "$appDir\MarkAuto.exe")) { throw 'Installed executable missing' }
  $sourceHashes = @{}
  foreach ($name in @('core.py','data.py','strategies.py','backtest.py','research.py','provider.py')) {
    $shipped = Join-Path $appDir "_internal\quantlab\$name"
    if (-not (Test-Path $shipped)) { throw "Engine source missing from installed bundle: $name" }
    $actual = (Get-FileHash $shipped -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = (Get-FileHash (Join-Path $root "quantlab\$name") -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Installed engine source differs from build input: $name" }
    $sourceHashes[$name] = $actual
  }
  $sourceHashes | ConvertTo-Json | Set-Content "$results\installed-source-hashes-$number.json"
  Assert-Sentinel
}
function Smoke([string]$stage) {
  $report = "$results\smoke-$stage.json"
  $oldPath = $env:PATH
  # Remove developer tools from lookup: the executable must use its bundled runtime.
  $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
  try {
    $p = Start-Process "$appDir\MarkAuto.exe" -ArgumentList @('--smoke-test',"`"$report`"") -PassThru -WorkingDirectory $env:TEMP
    if (-not $p.WaitForExit(180000)) { $p.Kill(); throw 'Native Qt smoke timed out' }
    if ($p.ExitCode -ne 0) { throw "Native Qt smoke failed: $($p.ExitCode)" }
  } finally { $env:PATH = $oldPath }
  if (-not (Test-Path $report)) { throw 'Smoke report missing' }
  $json = Get-Content $report -Raw | ConvertFrom-Json
  if ($json.status -ne 'passed' -or $json.version -ne $Version -or $json.native_window_visible -ne $true -or $json.worker_completed -ne $true -or [IO.Path]::GetFullPath($json.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Smoke report invalid or app data not separated' }
  foreach ($field in @('backtest_completed','campaign_completed','paper_completed')) {
    if ($json.$field -ne $true) { throw "Frozen smoke operation did not pass: $field" }
  }
  if ($json.steps.Count -ne 7 -or @($json.steps | Where-Object { $_.passed -ne $true }).Count -ne 0) { throw 'Frozen seven-operation smoke incomplete' }
  if ($json.generator -ne 'fixture' -or $json.source_type -ne 'synthetic' -or $json.real_model_status -ne 'not_verified' -or $json.live_status -ne 'disabled') { throw 'Frozen smoke must be explicitly fixture-only with live trading disabled' }
  Assert-Sentinel
}
Install-Version '0.0.0'
Smoke 'installed'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'
$shell = New-Object -ComObject WScript.Shell
foreach ($link in @($startMenu, $desktop)) {
  if (-not (Test-Path $link)) { throw "Shortcut missing: $link" }
  if ($shell.CreateShortcut($link).TargetPath -ne "$appDir\MarkAuto.exe") { throw 'Shortcut target incorrect' }
}
Install-Version $Version
Smoke 'upgraded'
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
  process_id=$window.Id; os_caption=$os.Caption; os_build=$os.BuildNumber} | ConvertTo-Json | Set-Content "$results\performance-observation.json
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
if (Test-Path "$appDir\MarkAuto.exe") { throw 'Executable remains after uninstall' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Shortcut remains after uninstall' }
Assert-Sentinel
@{status='passed'; tests=@('install','bundled-runtime-launch','start-menu-shortcut','desktop-shortcut','version-upgrade','reject-active-upgrade','reject-active-uninstall','native-window-close','uninstall','preserve-user-data');
  upgrade_scope='installer version upgrade with same application payload; not historical data schema migration';
  client_os_acceptance='BLOCKED'; signing='unsigned'} | ConvertTo-Json | Set-Content "$results\installer-results.json"
