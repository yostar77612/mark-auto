$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path (Split-Path -Parent $taskRoot) '.repo\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = (Get-Command python -ErrorAction Stop).Source
}
& $taskPython (Join-Path $PSScriptRoot 'ui_redesign_preview.py') @args
exit $LASTEXITCODE
