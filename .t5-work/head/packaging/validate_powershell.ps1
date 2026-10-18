param([string]$Directory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$files = @(Get-ChildItem -LiteralPath $Directory -Filter '*.ps1' -File -Recurse)
if ($files.Count -eq 0) { throw 'No packaging PowerShell scripts found; validation refused' }
$failed = $false
foreach ($file in $files) {
  $tokens = $null
  $parseErrors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
  foreach ($parseError in $parseErrors) {
    $failed = $true
    # Report locations/IDs only, never source excerpts that could contain secrets.
    Write-Host ("{0}:{1}:{2}: {3}" -f $file.Name, $parseError.Extent.StartLineNumber, $parseError.Extent.StartColumnNumber, $parseError.ErrorId)
  }
}
if ($failed) { throw 'PowerShell syntax validation failed before build' }
Write-Host ("PowerShell parser: {0} script(s) passed" -f $files.Count)
