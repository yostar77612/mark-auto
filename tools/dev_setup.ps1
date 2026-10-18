# Windows PowerShell 5.1. No environment activation or administrator rights needed.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Python = 'python',
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtime = Join-Path $repoRoot '.runtime-sqlite'
$venv = Join-Path $repoRoot '.venv'
$downloadRoot = Join-Path $repoRoot 'build/dev-setup-downloads'
$manifest = Join-Path $repoRoot 'packaging/sqlite-runtime.json'
$pythonManifest = Join-Path $repoRoot 'packaging/python-runtime.json'
$installer = Join-Path $PSScriptRoot 'install_sqlite_runtime.py'
$probe = Join-Path $repoRoot 'quantlab/sqlite_runtime.py'

# Return before invoking Python, making directories or opening a network connection.
if ($DryRun -or $WhatIfPreference) {
  Write-Host "Plan: resolve base Python from $Python; require packaging/python-runtime.json version (desktop lock ABI)."
  Write-Host "Plan: download SQLite with Windows certificate validation into $downloadRoot (unique temporary child)."
  Write-Host 'Plan: installer verifies archive SHA256 + SHA3-256, then extracted DLL content SHA256 against manifest.'
  Write-Host "Plan: create or verify $runtime; create or verify $venv; require SQLite >= 3.51.3."
  Write-Host 'Plan: pip install --require-hashes -r requirements-desktop.lock; print desktop launch command.'
  return
}

function Assert-ProjectPath([string]$Path) {
  $full = [IO.Path]::GetFullPath($Path)
  if (-not $full.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Setup path is outside project: $Path"
  }
  # Refuse junctions/symlinks, including an existing parent of an output path.
  $cursor = $full
  while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
      $item = Get-Item -LiteralPath $cursor -Force
      if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point refused: $cursor" }
    }
    $cursor = Split-Path -Parent $cursor
  }
}

function Invoke-Python([string]$Executable, [string[]]$Arguments) {
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE): $Executable" }
}

$downloadDir = $null
$creatingRuntime = $false
try {
  if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) {
    throw 'Developer setup requires Windows x64 PowerShell and full x64 CPython.'
  }
  foreach ($path in @($runtime, $venv, $downloadRoot)) { Assert-ProjectPath $path }
  $basePython = Invoke-Python $Python @('-I', '-c', 'import sys; print(sys._base_executable)')
  $basePython = ([string]$basePython).Trim()
  $expectedPython = (Get-Content -LiteralPath $pythonManifest -Raw | ConvertFrom-Json).version
  # requirements-desktop.lock includes cp313 wheels, so an older base cannot use this lock.
  $versionCheck = "import sys; assert sys.version.split()[0] == '$expectedPython', 'Use pinned CPython $expectedPython for requirements-desktop.lock'; assert sys.maxsize > 2**32"
  Invoke-Python $basePython @('-I', '-c', $versionCheck)
  if (-not (Test-Path -LiteralPath $runtime)) {
    $downloadDir = Join-Path $downloadRoot ([Guid]::NewGuid().ToString('N'))
    Assert-ProjectPath $downloadDir
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
    $archive = Join-Path $downloadDir 'sqlite.zip'
    $pin = (Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json).windows_x64
    if ($pin.url -notmatch '^https://www\.sqlite\.org/') { throw 'SQLite URL must use official HTTPS origin.' }
    # Windows .NET certificate verifier / OS trust store; no Python SSL dependency.
    # Refuse redirects rather than silently leaving the pinned official origin.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $request = [Net.HttpWebRequest]::Create($pin.url)
    $request.AllowAutoRedirect = $false
    $request.Timeout = 90000
    $response = $request.GetResponse()
    try {
      if ([int]$response.StatusCode -ne 200) { throw 'SQLite download requires HTTP 200 without redirects.' }
      $inputStream = $response.GetResponseStream()
      $outputStream = [IO.File]::Create($archive)
      try {
        $buffer = New-Object byte[] 65536
        $total = 0
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
          $total += $count
          if ($total -gt 16777216) { throw 'SQLite archive exceeds size limit.' }
          $outputStream.Write($buffer, 0, $count)
        }
      } finally { $outputStream.Dispose(); $inputStream.Dispose() }
    } finally { $response.Dispose() }
    # Preserve BOTH stages: archive SHA256 + SHA3-256 AND extracted DLL content SHA256.
    # The installer performs these before copying Python or creating the runtime.
    $creatingRuntime = $true
    Invoke-Python $basePython @($installer, '--destination', $runtime, '--report', (Join-Path $downloadDir 'report.json'), '--archive', $archive)
  }
  $privatePython = Join-Path $runtime 'python.exe'
  Invoke-Python $privatePython @('-I', '-c', $versionCheck)
  # Re-probe existing runtimes too: version/source ID, loaded-library path and DLL hash.
  Invoke-Python $privatePython @('-I', $probe, '--manifest', $manifest, '--root', $runtime)
  $creatingRuntime = $false
  if (-not (Test-Path -LiteralPath $venv)) {
    Invoke-Python $privatePython @('-I', '-m', 'venv', $venv)
  }
  $venvPython = Join-Path $venv 'Scripts/python.exe'
  Invoke-Python $venvPython @('-I', '-c', $versionCheck)
  $baseCheck = 'import pathlib, sys; assert pathlib.Path(sys.base_prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), "Existing .venv uses another base; move it aside and rerun setup"'
  Invoke-Python $venvPython @('-I', '-c', $baseCheck, $runtime)
  Invoke-Python $venvPython @('-I', $probe, '--manifest', $manifest, '--root', $runtime)
  Invoke-Python $venvPython @('-I', '-m', 'pip', 'install', '--require-hashes', '-r', (Join-Path $repoRoot 'requirements-desktop.lock'))
  Write-Host "Ready. In '$repoRoot', activate .\.venv\Scripts\Activate.ps1, then run: python desktop.py"
  Write-Host "Or run: & '$venvPython' '$repoRoot\desktop.py'"
} catch {
  if ($creatingRuntime -and (Test-Path -LiteralPath $runtime)) {
    Assert-ProjectPath $runtime
    Remove-Item -LiteralPath $runtime -Recurse -Force
  }
  [Console]::Error.WriteLine("Developer setup failed: $($_.Exception.Message)")
  exit 1
} finally {
  if ($downloadDir -and (Test-Path -LiteralPath $downloadDir)) {
    Assert-ProjectPath $downloadDir
    Remove-Item -LiteralPath $downloadDir -Recurse -Force
  }
}
