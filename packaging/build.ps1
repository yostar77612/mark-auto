param([string]$Version = '0.2.1')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
& (Join-Path $PSScriptRoot 'validate_powershell.ps1')
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must be numeric x.y.z' }
if (-not [Environment]::Is64BitProcess) { throw 'Build requires x64 Python/PowerShell' }
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  python -c "import sys; assert sys.version_info[:3] == (3, 13, 16), sys.version; assert sys.maxsize > 2**32"
  if ($LASTEXITCODE) { throw 'Build requires pinned CPython 3.13.16 x64' }
  python -m pip install --require-hashes --only-binary=:all: -r requirements-desktop.lock
  if ($LASTEXITCODE) { throw 'Dependency install failed' }
  python -c "from PySide6.QtWidgets import QApplication; import PySide6; print('Native Qt preflight', PySide6.__version__)"
  if ($LASTEXITCODE) { throw 'Native Qt preflight failed; refusing skipped UI tests' }
  $env:MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS = '1'
  python -c "from desktop_chatgpt_provider import implementation_provenance; print(implementation_provenance()['dependency_target'])"
  if ($LASTEXITCODE) { throw 'Native authentication dependencies or provenance unavailable' }
  python -m unittest discover -s tests -v
  if ($LASTEXITCODE) { throw 'Regression suite failed before freezing' }
  python packaging/collect_licenses.py
  if ($LASTEXITCODE) { throw 'License collection failed' }
  python -m PyInstaller --noconfirm --clean packaging/markauto.spec
  if ($LASTEXITCODE) { throw 'PyInstaller failed' }
  python packaging/payload_inventory.py dist/MarkAuto dist/payload-inventory.txt dist/payload-inventory.iss
  if ($LASTEXITCODE) { throw 'Payload inventory failed' }
  $temporary = $env:RUNNER_TEMP
  if (-not $temporary) { $temporary = $env:TEMP }
  $compilerInstaller = Join-Path $temporary 'innosetup-6.4.3.exe'
  $url = 'https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe'
  # Official GitHub release asset digest, checked against official API on 2026-10-09.
  # https://api.github.com/repos/jrsoftware/issrc/releases/tags/is-6_4_3
  $sha = 'f3c42116542c4cc57263c5ba6c4feabfc49fe771f2f98a79d2f7628b8762723b'
  Invoke-WebRequest $url -OutFile $compilerInstaller
  if ((Get-FileHash $compilerInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw 'Inno Setup SHA256 mismatch' }
  $compilerDir = Join-Path $env:TEMP 'MarkAuto-Inno-6.4.3'
  $process = Start-Process $compilerInstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',"/DIR=`"$compilerDir`"") -Wait -PassThru
  if ($process.ExitCode) { throw "Inno Setup install failed: $($process.ExitCode)" }
  # Build a lower-version fixture and the actual candidate with a stable AppId.
  & "$compilerDir\ISCC.exe" '/DAppVersion=0.0.0' 'packaging\markauto.iss'
  if ($LASTEXITCODE) { throw 'Upgrade baseline compilation failed' }
  & "$compilerDir\ISCC.exe" "/DAppVersion=$Version" 'packaging\markauto.iss'
  if ($LASTEXITCODE) { throw 'Installer compilation failed' }
} finally { Pop-Location }
