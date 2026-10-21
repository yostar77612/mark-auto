<#
Fast local pre-push checks (offline, no network). Mirrors the cheap CI gates:
ruff lint + format, Python 3.11 syntax of every tracked .py, tools/quality_gate.py,
and optionally the unit tests of changed files. Exits nonzero on the first failing step.

  powershell -File tools/prepush.ps1              # lint, syntax, quality gate
  powershell -File tools/prepush.ps1 -Tests       # also run tests for changed files
  powershell -File tools/prepush.ps1 -Base origin/main
#>
param(
    [switch]$Tests,
    [string]$Base = 'origin/main'
)
$ErrorActionPreference = 'Stop'
$root = (git rev-parse --show-toplevel).Trim()
Set-Location $root
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'

# Prefer this checkout's .venv, then the main checkout's (git worktrees), then PATH.
$python = 'python'
$common = (git rev-parse --git-common-dir).Trim()
foreach ($dir in @($root, (Split-Path -Parent (Resolve-Path $common)))) {
    $candidate = Join-Path $dir '.venv\Scripts\python.exe'
    if (Test-Path $candidate) { $python = $candidate; break }
}
$failed = @()

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "== $Name"
    & $Body
    if ($LASTEXITCODE -ne 0) { $script:failed += $Name; Write-Host "FAILED: $Name" -ForegroundColor Red }
}

Invoke-Step 'ruff check' { & $python -m ruff check . }
Invoke-Step 'ruff format --check' { & $python -m ruff format --check . }

Invoke-Step 'python 3.11 syntax scan' {
    $scan = @'
import subprocess, sys
files = subprocess.run(['git', 'ls-files', '-z', '*.py'], capture_output=True, check=True).stdout.decode('utf-8').split('\0')
bad = 0
for name in filter(None, files):
    try:
        with open(name, encoding='utf-8-sig') as handle:
            compile(handle.read(), name, 'exec', dont_inherit=True)
    except (SyntaxError, ValueError, OSError) as error:
        bad += 1
        print(f'{name}: {error}')
print(f'checked {len(files) - 1} files, {bad} failing')
sys.exit(1 if bad else 0)
'@
    $scan | py -3.11 -
}

Invoke-Step 'tools/quality_gate.py' { & $python tools/quality_gate.py }

if ($Tests) {
    $changed = @(git diff --name-only "$Base...HEAD"; git diff --name-only; git diff --name-only --cached) | Where-Object { $_ } | Sort-Object -Unique
    $targets = @()
    foreach ($file in $changed) {
        if ($file -match '^tests/test_.*\.py$' -and (Test-Path $file)) { $targets += $file }
        elseif ($file -match '\.py$') {
            $stem = [IO.Path]::GetFileNameWithoutExtension($file)
            $targets += Get-ChildItem tests -Filter "test_$stem*.py" -ErrorAction SilentlyContinue | ForEach-Object { "tests/$($_.Name)" }
        }
    }
    $targets = $targets | Sort-Object -Unique
    if ($targets) {
        $modules = $targets | ForEach-Object { ($_ -replace '\.py$', '') -replace '/', '.' }
        Invoke-Step 'unit tests of changed files' { & $python -m unittest @modules }
    } else {
        Write-Host '== no changed test targets found'
    }
}

if ($failed.Count) { Write-Host ("Pre-push FAILED: " + ($failed -join ', ')) -ForegroundColor Red; exit 1 }
Write-Host 'Pre-push checks passed.' -ForegroundColor Green
exit 0
