# CI build prerequisite, outside any acceptance round. Never run on a personal host.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Acceptance helper compilation requires the ephemeral CI builder' }
$source = Join-Path $PSScriptRoot 'acceptance_process.cs'
$output = Join-Path $PSScriptRoot 'acceptance_process.dll'
if (Test-Path -LiteralPath $output) { throw 'Refusing to overwrite an existing acceptance helper' }
Add-Type -TypeDefinition (Get-Content -LiteralPath $source -Raw) -OutputAssembly $output -OutputType Library
