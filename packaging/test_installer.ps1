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
  Assert-Sentinel
}
function Smoke([string]$stage) {
  $report = "$results\smoke-$stage.json"
  $oldPath = $env:PATH
  # Remove developer tools from lookup: the executable must use its bundled runtime.
  $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
  try {
    $p = Start-Process "$appDir\MarkAuto.exe" -ArgumentList @('--smoke-test',"`"$report`"") -PassThru -WorkingDirectory $env:TEMP
    if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'Native Qt smoke timed out' }
    if ($p.ExitCode -ne 0) { throw "Native Qt smoke failed: $($p.ExitCode)" }
  } finally { $env:PATH = $oldPath }
  if (-not (Test-Path $report)) { throw 'Smoke report missing' }
  $json = Get-Content $report -Raw | ConvertFrom-Json
  if ($json.status -ne 'passed' -or $json.version -ne $Version -or $json.native_window_visible -ne $true -or $json.worker_completed -ne $true -or [IO.Path]::GetFullPath($json.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) { throw 'Smoke report invalid or app data not separated' }
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
Start-Process $startMenu
$window = $null
for ($i=0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  $window = Get-Process MarkAuto -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if ($window) { break }
}
if (-not $window) { throw 'Start menu launch did not create a native window' }
[void]$window.CloseMainWindow()
if (-not $window.WaitForExit(15000)) { $window.Kill(); throw 'Window did not close cleanly' }
$p = Start-Process "$appDir\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\uninstall.log`"") -Wait -PassThru
if ($p.ExitCode) { throw "Uninstall failed: $($p.ExitCode)" }
if (Test-Path "$appDir\MarkAuto.exe") { throw 'Executable remains after uninstall' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Shortcut remains after uninstall' }
Assert-Sentinel
@{status='passed'; tests=@('install','bundled-runtime-launch','start-menu-shortcut','desktop-shortcut','version-upgrade','native-window-close','uninstall','preserve-user-data');
  upgrade_scope='installer version upgrade with same application payload; not historical data schema migration';
  client_os_acceptance='BLOCKED'; signing='unsigned'} | ConvertTo-Json | Set-Content "$results\installer-results.json"
