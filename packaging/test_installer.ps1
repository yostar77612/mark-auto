param([ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.2.2', [ValidatePattern('^\d+\.\d+\.\d+$')][string]$BaselineVersion = '0.0.0',
      [string]$BaselineAppVersion = '', [string]$BaselineManifest = '', [string]$CandidateManifest = '',
      [switch]$CreateRecoveryHandoff,
      [ValidateSet('HostedCi','DisposableVm','PreparedHost')][string]$AcceptanceScope,
      [Parameter(DontShow=$true)][string]$AcceptanceJob = '',
      [Parameter(DontShow=$true)][switch]$EvidenceReserved)
$acceptanceClock = [Diagnostics.Stopwatch]::StartNew()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $BaselineAppVersion) { $BaselineAppVersion = $Version }
$root = Split-Path $PSScriptRoot -Parent
$results = Join-Path $root 'dist\validation'
# Scope is an explicit attestation, not a sandbox or proof that a used host is clean.
if ($AcceptanceScope -eq 'PreparedHost' -and $CreateRecoveryHandoff) { throw 'Recovery handoff requires the complete disposable lifecycle, not partial host evidence' }
if (-not $AcceptanceScope) { throw 'Choose an explicit authorized HostedCi, DisposableVm or PreparedHost acceptance scope' }
if ($AcceptanceScope -eq 'HostedCi' -and ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted')) {
  throw 'HostedCi requires the ephemeral GitHub-hosted runner environment'
}
if ($AcceptanceScope -ne 'HostedCi') {
  if (-not $CandidateManifest -or -not $BaselineManifest) { throw 'Host and VM acceptance require exact baseline and candidate build manifests' }
  $bootstrapManifest = Get-Content -LiteralPath $CandidateManifest -Raw | ConvertFrom-Json
  $helperDigest = ($bootstrapManifest.inputs_sha256.PSObject.Properties | Where-Object { $_.Name.Replace('\','/') -eq 'packaging/acceptance_process.dll' }).Value
  if (-not $helperDigest -or (Get-FileHash (Join-Path $PSScriptRoot 'acceptance_process.dll') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $helperDigest) { throw 'Prebuilt helper differs from candidate build manifest' }
}
. (Join-Path $PSScriptRoot 'acceptance_process.ps1')
Assert-AcceptancePath $results
New-Item $results -ItemType Directory -Force | Out-Null
if ($AcceptanceJob) { Confirm-AcceptanceWorker $AcceptanceJob }
if (-not $EvidenceReserved) {
  $evidenceNames = @('installer-results.json','installer-supervisor.json','installer-scope-preflight.json',
    'os-evidence.json','smoke-installed.json','smoke-upgraded.json','performance-observation.json',
    'refused-upgrade.log','refused-uninstall.log','uninstall.log',
    "installed-source-hashes-$BaselineVersion.json","installed-source-hashes-$Version.json",
    "install-$BaselineVersion.log","install-$Version.log")
  # Exclusive reservation proves ownership of every report/log before any write.
  foreach ($evidence in ($evidenceNames | Select-Object -Unique)) {
    $path = Join-Path $results $evidence
    Assert-AcceptancePath $path -RequireAbsent
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $stream.Dispose()
  }
  if ($CreateRecoveryHandoff) { Assert-AcceptancePath (Join-Path $results 'lifecycle-state-handoff.json') -RequireAbsent }
}
if (-not $AcceptanceJob) {
  $workerParameters = @{}
  foreach ($key in $PSBoundParameters.Keys) { $workerParameters[$key] = $PSBoundParameters[$key] }
  $workerParameters['EvidenceReserved'] = [switch]$true
  $code = Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath -Parameters $workerParameters -Clock $acceptanceClock -ReportPath (Join-Path $results 'installer-supervisor.json') -FailureReportPath (Join-Path $results 'installer-results.json')
  if ($code -eq 2 -and $AcceptanceScope -eq 'PreparedHost') { exit 2 }
  if ($code -ne 0) { throw 'Installer acceptance failed; see bounded supervisor and lifecycle evidence' }
  return
}
Confirm-AcceptanceWorker $AcceptanceJob
$script:acceptanceProcesses = New-Object System.Collections.ArrayList
try {
$os = Get-CimInstance Win32_OperatingSystem
@{caption=$os.Caption; version=$os.Version; build=$os.BuildNumber; architecture=$os.OSArchitecture;
  runner_image=$env:ImageOS; runner_image_version=$env:ImageVersion;
  windows_10_22h2_clean='BLOCKED: requires independent clean client VM';
  windows_11_clean='BLOCKED: requires independent clean client VM'} | ConvertTo-Json | Set-Content "$results\os-evidence.json"
$appDir = Join-Path $env:LOCALAPPDATA 'Programs\MarkAuto'
$dataDir = Join-Path $env:LOCALAPPDATA 'MarkAuto'
$handoffSettings = Join-Path $dataDir 'state-v1\settings.json'
$handoffPath = Join-Path $results 'lifecycle-state-handoff.json'
# Never overwrite or uninstall original host state, even if someone says it was backed up.
# A separate reviewed backup/isolation operation must resolve existing state first.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($AcceptanceScope -ne 'HostedCi' -and ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0)) {
  throw 'Prepared host and disposable VM tests require a non-elevated interactive user session'
}
$destinations = @($appDir, $dataDir,
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto'),
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'),
  (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Mark Auto'),
  (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Mark Auto.lnk'))
foreach ($destination in $destinations) { Assert-AcceptancePath $destination -RequireAbsent }
$registration = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{58788303-95B7-491B-A67A-B1EBA50DA420}_is1'
$registryEvidence = @(Assert-AbsentAcceptanceRegistration $registration)
# Detection only: no process returned by name is ever adopted, closed or terminated.
if (Get-Process -Name MarkAuto -ErrorAction SilentlyContinue -ErrorVariable processErrors) { throw 'Existing MarkAuto process refused; original process preserved' }
foreach ($processError in $processErrors) {
  if ($processError.FullyQualifiedErrorId -notlike 'NoProcessFoundForGivenName,*') { throw 'Unable to inspect existing MarkAuto processes safely' }
}
@{scope=$AcceptanceScope; destinations_initially_absent=$destinations; registrations_initially_absent=$registryEvidence;
  backup_required=$false; backup_reason='All exact target state was absent; existing state is always refused';
  host_isolation=$false; clean_client_acceptance='BLOCKED'} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $results 'installer-scope-preflight.json')
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
$sentinelStream = [IO.File]::Open($sentinel, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
  $sentinelBytes = [Text.Encoding]::UTF8.GetBytes($sentinelValue)
  $sentinelStream.Write($sentinelBytes, 0, $sentinelBytes.Length)
} finally { $sentinelStream.Dispose() }
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
  $owned = Start-OwnedAcceptanceProcess $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\install-$number.log`"")
  Wait-OwnedAcceptanceProcess $owned 180000 'Installer timed out'
  $p = $owned.Process
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
    $owned = Start-OwnedAcceptanceProcess $script:installedExe -ArgumentList @('--smoke-test',"`"$report`"")
    Wait-OwnedAcceptanceProcess $owned 180000 'Native Qt smoke timed out'
    $p = $owned.Process
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
if ($AcceptanceScope -eq 'PreparedHost') {
  # ShellExecute may delegate outside the job. Never exercise that route on a used host.
  $shortcut = $shell.CreateShortcut($startMenu)
  if ($shortcut.TargetPath -ne $script:installedExe -or $shortcut.Arguments -or
      [IO.Path]::GetFullPath($shortcut.WorkingDirectory) -ne [IO.Path]::GetFullPath((Split-Path $script:installedExe -Parent))) { throw 'Prepared-host shortcut target, arguments or working directory changed' }
  $gui = Start-OwnedAcceptanceProcess $shortcut.TargetPath -WorkingDirectory $shortcut.WorkingDirectory
} else {
  # Preserve the original real .lnk execution assertion on disposable CI/VM scopes.
  $gui = Start-OwnedAcceptanceProcess $startMenu -ExpectedImage $script:installedExe
}
$window = $gui.Process
Wait-OwnedAcceptanceWindow $gui
$launchClock.Stop()
Start-Sleep -Seconds 2
$window.Refresh()
@{scope=$(if ($AcceptanceScope -eq 'HostedCi') { 'Windows Server CI observation, not Windows 10/11 client SLO' } else { 'Authorized Windows fixture observation; not full clean-client acceptance or SLO' });
  startup_to_main_window_seconds=$launchClock.Elapsed.TotalSeconds;
  startup_sampling_interval_seconds=1;
  idle_working_set_bytes=$window.WorkingSet64;
  idle_sampling='Single sample two seconds after first detected main window, no task running';
  process_id=$window.Id; os_caption=$os.Caption; os_build=$os.BuildNumber} | ConvertTo-Json | Set-Content "$results\performance-observation.json"
# Running work must never be closed automatically by an upgrade or uninstall.
foreach ($attempt in @('upgrade', 'uninstall')) {
  $command = if ($attempt -eq 'upgrade') { Join-Path $root "dist\installers\MarkAuto-$Version-windows-x64-setup.exe" } else { "$appDir\unins000.exe" }
  $owned = Start-OwnedAcceptanceProcess $command -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\refused-$attempt.log`"")
  Wait-OwnedAcceptanceProcess $owned 30000 "Active-app $attempt did not refuse promptly"
  $refused = $owned.Process
  if ($refused.ExitCode -eq 0) { throw "Active-app $attempt was not rejected" }
  $window.Refresh()
  if ($window.HasExited) { throw "Active-app $attempt stopped the application" }
  Assert-Sentinel
}
Assert-OwnedAcceptanceProcess $gui
[void]$window.CloseMainWindow()
Wait-OwnedAcceptanceProcess $gui 15000 'Window did not close cleanly'
$owned = Start-OwnedAcceptanceProcess "$appDir\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$results\uninstall.log`"")
Wait-OwnedAcceptanceProcess $owned 180000 'Uninstall timed out'
$p = $owned.Process
if ($p.ExitCode) { throw "Uninstall failed: $($p.ExitCode)" }
if ((Test-Path $script:installedExe) -or (Test-Path "$appDir\MarkAuto.exe")) { throw 'Executable remains after uninstall' }
if ((Test-Path $startMenu) -or (Test-Path $desktop)) { throw 'Shortcut remains after uninstall' }
Assert-Sentinel
@{status=$(if ($AcceptanceScope -eq 'PreparedHost') { 'partial' } else { 'passed' });
  shortcut_execution=$(if ($AcceptanceScope -eq 'PreparedHost') { 'NOT RUN: verified shortcut resolution and owned direct-target launch only' } else { 'passed: real shell shortcut launch' });
  tests=@('install','bundled-runtime-launch','start-menu-shortcut','desktop-shortcut','version-upgrade','reject-active-upgrade','reject-active-uninstall','native-window-close','uninstall','preserve-user-data');
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

} catch {
  @{status='failed'; reason='Lifecycle assertion, preflight or owned-process wait failed'; client_os_acceptance='BLOCKED'} |
    ConvertTo-Json | Set-Content (Join-Path $results 'installer-results.json')
  throw
} finally { Close-AcceptanceProcesses }
if ($AcceptanceScope -eq 'PreparedHost') { exit 2 }

