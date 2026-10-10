param(
  [Parameter(Mandatory=$true)][ValidateSet('Windows10-22H2','Windows11')][string]$Target,
  [Parameter(Mandatory=$true)][string]$SnapshotReference,
  [switch]$DisposableVmConfirmed,
  [switch]$LicenseAlreadyAccepted
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path $PSScriptRoot -Parent
$results = Join-Path $root 'dist\validation'
# Never overwrite prior evidence, or clean up user/app state in order to pass.
if (Test-Path $results) { throw 'Existing evidence: use a fresh kit and restore a clean VM snapshot' }
New-Item $results -ItemType Directory | Out-Null
$record = [ordered]@{
  status='EXTERNAL BLOCKED'; target=$Target; started_utc=[DateTime]::UtcNow.ToString('o');
  snapshot_reference=$SnapshotReference; lifecycle='NOT RUN'; full_functionality='BLOCKED';
  real_ai='NOT VERIFIED'; real_market='NOT VERIFIED'; live_trading='DISABLED';
  manual_gui='BLOCKED'; historical_data_migration='BLOCKED'; reason='Preflight not completed'
}
$exitCode = 2
try {
  if (-not $DisposableVmConfirmed -or -not $LicenseAlreadyAccepted -or [string]::IsNullOrWhiteSpace($SnapshotReference)) {
    throw 'A disposable clean snapshot and previously accepted valid OS license are required; this kit accepts no license'
  }
  $os = Get-CimInstance Win32_OperatingSystem
  $cpu = @(Get-CimInstance Win32_Processor)
  $record.os = @{caption=$os.Caption; version=$os.Version; build=$os.BuildNumber; product_type=$os.ProductType; architecture=$os.OSArchitecture; cpu_architecture=@($cpu | ForEach-Object { $_.Architecture })}
  if ($os.ProductType -ne 1 -or -not [Environment]::Is64BitProcess -or @($cpu | Where-Object { $_.Architecture -ne 9 }).Count -gt 0 -or $cpu.Count -eq 0) {
    throw 'Requires native AMD64 Windows client and x64 PowerShell; Server, ARM/emulation and x86 are refused'
  }
  $build = [int]$os.BuildNumber
  if (($Target -eq 'Windows10-22H2' -and $build -ne 19045) -or ($Target -eq 'Windows11' -and ($build -lt 22000 -or $os.Caption -notmatch 'Windows 11'))) {
    throw 'Wrong client OS/build for requested target'
  }
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or (Get-Process -Id $PID).SessionId -eq 0) {
    throw 'Use a non-elevated interactive standard-user desktop session'
  }
  if ($env:GITHUB_ACTIONS -or $env:ImageOS -or $env:RUNNER_TOOL_CACHE) { throw 'Developer/CI images are not clean clients' }
  foreach ($path in @((Join-Path $env:LOCALAPPDATA 'MarkAuto'), (Join-Path $env:LOCALAPPDATA 'Programs\MarkAuto'),
                     (Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto'),
                     (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'))) {
    if (Test-Path $path) { throw 'Existing MarkAuto app, data or shortcut found; nothing will be removed' }
  }
  if (Get-Process MarkAuto -ErrorAction SilentlyContinue) { throw 'Existing MarkAuto process found' }
  $foundTools = @()
  foreach ($name in @('python.exe','python3.exe','py.exe','pip.exe','git.exe','node.exe','npm.cmd','cl.exe','devenv.exe')) {
    foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
      # Fresh Windows includes Store Python execution aliases, not an installed runtime.
      if ($command.Source -notlike '*\Microsoft\WindowsApps\*') { $foundTools += $command.Source }
    }
  }
  $programs = @(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
       'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
       'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
       Where-Object { $_.PSObject.Properties['DisplayName'] -and $_.DisplayName -match 'Python|Git version|Git for Windows|Visual Studio|Anaconda|Miniconda|Node\.js' } |
       ForEach-Object { $_.DisplayName })
  $storeTools = @(Get-AppxPackage -ErrorAction Stop | Where-Object { $_.Name -match 'PythonSoftwareFoundation\.Python|Anaconda|VisualStudio' } | ForEach-Object { $_.Name })
  foreach ($directory in @((Join-Path $env:LOCALAPPDATA 'Programs\Python'), (Join-Path $env:ProgramFiles 'Git'),
                           (Join-Path $env:ProgramFiles 'Python*'), (Join-Path $env:USERPROFILE 'anaconda3'),
                           (Join-Path $env:USERPROFILE 'miniconda3'))) {
    if (Test-Path $directory) { $foundTools += $directory }
  }
  $record.developer_tools = @($foundTools) + @($programs) + @($storeTools)
  if ($record.developer_tools.Count) { throw 'Developer tools detected; PATH removal is not a clean-machine test' }
  $kit = Get-Content (Join-Path $root 'kit.json') -Raw | ConvertFrom-Json
  if ($kit.schema_version -ne 1 -or $kit.baseline_version -eq '0.0.0' -or [version]$kit.baseline_version -ge [version]$kit.version -or $kit.baseline_commit -eq $kit.candidate_commit) { throw 'Invalid historical upgrade kit' }
  foreach ($required in @('packaging/test_installer.ps1', 'packaging/clean_windows_acceptance.ps1', 'packaging/clean_windows_README.md',
                         'baseline-manifest.json', 'candidate-manifest.json',
                         "dist/installers/MarkAuto-$($kit.baseline_version)-windows-x64-setup.exe",
                         "dist/installers/MarkAuto-$($kit.version)-windows-x64-setup.exe")) {
    if (-not $kit.files_sha256.PSObject.Properties[$required]) { throw 'Required kit digest missing' }
  }
  foreach ($entry in $kit.files_sha256.PSObject.Properties) {
    $path = [IO.Path]::GetFullPath((Join-Path $root $entry.Name))
    if (-not $path.StartsWith(([IO.Path]::GetFullPath($root) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw 'Kit path escapes root' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw 'Kit file hash mismatch' }
  }
  $baseline = Get-Content (Join-Path $root 'baseline-manifest.json') -Raw | ConvertFrom-Json
  $candidate = Get-Content (Join-Path $root 'candidate-manifest.json') -Raw | ConvertFrom-Json
  if ($baseline.source_commit -ne $kit.baseline_commit -or $candidate.source_commit -ne $kit.candidate_commit) { throw 'Manifest commit does not match kit' }
  $record.kit_sha256 = (Get-FileHash (Join-Path $root 'kit.json') -Algorithm SHA256).Hash
  $record.baseline_commit = $kit.baseline_commit
  $record.candidate_commit = $kit.candidate_commit
  $record.lifecycle = 'RUNNING'
  # Child scope prevents shared harness locals ($os/$results/$root) changing this record.
  & (Join-Path $PSScriptRoot 'test_installer.ps1') -Version $kit.version -BaselineVersion $kit.baseline_version -BaselineAppVersion $kit.baseline_version -BaselineManifest (Join-Path $root 'baseline-manifest.json') -CandidateManifest (Join-Path $root 'candidate-manifest.json')
  $lifecycle = Get-Content (Join-Path $results 'installer-results.json') -Raw | ConvertFrom-Json
  if ($lifecycle.status -ne 'passed') { throw 'Lifecycle evidence not passed' }
  $record.lifecycle = 'PASSED: install, fixture smoke, shortcut launch, upgrade, active-app refusal, uninstall, sentinel'
  $record.reason = 'Automated subset passed; manual GUI, real AI/market and historical application-data migration remain unverified'
} catch {
  if ($record.lifecycle -eq 'RUNNING') { $record.status = 'FAILED'; $record.lifecycle = 'FAILED'; $exitCode = 1 }
  $record.reason = $_.Exception.Message
} finally {
  $record.finished_utc = [DateTime]::UtcNow.ToString('o')
  $record | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $results 'clean-client-results.json') -Encoding UTF8
}
Write-Host ($record.status + ': ' + $record.reason)
# 2 deliberately prevents fixture-only success from passing full release acceptance.
exit $exitCode
