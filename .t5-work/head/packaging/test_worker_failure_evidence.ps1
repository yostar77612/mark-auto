param([string]$Helper=(Join-Path $PSScriptRoot 'acceptance_process.ps1'), [string]$EvidenceRoot='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) { $EvidenceRoot=Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\validation\worker-failure-native' }
. $Helper
function New-WorkerFailureFixtureRoot([string]$EvidenceRoot, [string]$RunId='') {
  if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId=[guid]::NewGuid().ToString('N') }
  if ($RunId -cnotmatch '^[a-f0-9]{32}$') { throw 'Fixture run identifier refused' }
  $evidencePath=[IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
  if ($evidencePath -notmatch '^[A-Za-z]:\\' -or $evidencePath.Substring(2).Contains(':')) { throw 'Only ordinary local acceptance paths are supported' }
  # Inspect root-to-leaf before descendant metadata or any output creation.
  $ancestors=[Collections.Generic.Stack[string]]::new(); $inspect=$evidencePath
  while ($inspect) {
    $ancestors.Push($inspect); $parent=Split-Path $inspect -Parent
    if ($parent -eq $inspect) { break }; $inspect=$parent
  }
  while ($ancestors.Count) {
    $path=$ancestors.Pop(); $attributes=[MarkAutoAcceptanceJob]::PathAttributes($path)
    if ($attributes -eq [uint32]::MaxValue) { continue }
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse destination or ancestor refused; original state preserved' }
    if (($attributes -band [IO.FileAttributes]::Directory) -eq 0) { throw 'Fixture evidence ancestor requires a directory' }
  }
  Assert-AcceptancePath $evidencePath
  $runPath=Join-Path $evidencePath ('diagnostic-regressions-'+$RunId)
  Assert-AcceptancePath $runPath -RequireAbsent
  [void][IO.Directory]::CreateDirectory($runPath)
  Assert-AcceptancePath $runPath
  return $runPath
}
function Require-WorkerFixture([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Reject-WorkerFixture([scriptblock]$Action,[string]$Expected) {
  $refused=$false
  try { & $Action } catch { if ($_.Exception.Message -cne $Expected) { throw }; $refused=$true }
  Require-WorkerFixture $refused 'Fixture ownership refusal did not occur'
}
$run=New-WorkerFailureFixtureRoot $EvidenceRoot
$ownershipResults=@()
$collisionId=[guid]::NewGuid().ToString('N')
$collision=New-WorkerFailureFixtureRoot $run $collisionId
$sentinel=Join-Path $collision 'owned-sentinel.txt'
[IO.File]::WriteAllText($sentinel,'preserve-owned-fixture',[Text.UTF8Encoding]::new($false))
Reject-WorkerFixture { New-WorkerFailureFixtureRoot $run $collisionId } 'Existing MarkAuto destination refused; original state preserved'
Require-WorkerFixture ([IO.File]::ReadAllText($sentinel) -ceq 'preserve-owned-fixture' -and [IO.Directory]::GetFileSystemEntries($collision).Length -eq 1) 'Directory collision altered original fixture'
$ownershipResults+=@{case='directory_collision';passed=$true;preexisting_state_unchanged=$true}
$fileId=[guid]::NewGuid().ToString('N'); $collisionFile=Join-Path $run ('diagnostic-regressions-'+$fileId)
[IO.File]::WriteAllText($collisionFile,'preserve-owned-file',[Text.UTF8Encoding]::new($false))
Reject-WorkerFixture { New-WorkerFailureFixtureRoot $run $fileId } 'Existing MarkAuto destination refused; original state preserved'
Require-WorkerFixture ([IO.File]::ReadAllText($collisionFile) -ceq 'preserve-owned-file') 'File collision altered original fixture'
$ownershipResults+=@{case='file_collision';passed=$true;preexisting_state_unchanged=$true}
$redirectTarget=Join-Path $run 'owned-reparse-target'; [void][IO.Directory]::CreateDirectory($redirectTarget)
$redirect=Join-Path $run 'owned-evidence-redirect'
New-Item -ItemType Junction -Path $redirect -Target $redirectTarget -ErrorAction Stop | Out-Null
try {
  Reject-WorkerFixture { New-WorkerFailureFixtureRoot $redirect } 'Reparse destination or ancestor refused; original state preserved'
  Require-WorkerFixture ([IO.Directory]::GetFileSystemEntries($redirectTarget).Length -eq 0) 'Reparse root control wrote through redirect'
  $ownershipResults+=@{case='reparse_evidence_root';passed=$true;redirect_target_unchanged=$true}
  Reject-WorkerFixture { New-WorkerFailureFixtureRoot (Join-Path $redirect 'uncreated/descendant') } 'Reparse destination or ancestor refused; original state preserved'
  Require-WorkerFixture ([IO.Directory]::GetFileSystemEntries($redirectTarget).Length -eq 0) 'Reparse ancestor control wrote through redirect'
  $ownershipResults+=@{case='reparse_evidence_ancestor';passed=$true;redirect_target_unchanged=$true}
} finally {
  # Remove only this verified, nonrecursive junction inside the owned fresh tree.
  if (-not [IO.Path]::GetFullPath($redirect).StartsWith(($run+'\'),[StringComparison]::OrdinalIgnoreCase) -or
      ([MarkAutoAcceptanceJob]::PathAttributes($redirect) -band [IO.FileAttributes]::ReparsePoint) -eq 0) { throw 'Owned fixture redirect cleanup identity refused' }
  [IO.Directory]::Delete($redirect)
}
[IO.File]::WriteAllText((Join-Path $run 'ownership-regression-results.json'),($ownershipResults|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
[Console]::Out.WriteLine((@{stage='fixture_root_ownership';guid_root=$true;cases=$ownershipResults.Count;passed=$ownershipResults.Count;collision_state_preserved=$true;reparse_targets_unchanged=$true}|ConvertTo-Json -Compress))

$cases=@('early','runtime','primary_cleanup','secret_record','preexisting_output','denied_output','partial_exit')
$results=@()
$workerBody=@'
param([string]$AcceptanceJob,[string]$AcceptanceScope,[string]$Helper,[string]$Case,[string]$EvidenceRoot)
$ErrorActionPreference='Stop'
if($Case -eq 'early'){throw [ComponentModel.Win32Exception]::new(5,'fixture-sensitive-early-error')}
if($Case -eq 'partial_exit'){exit 2}
. $Helper
Confirm-AcceptanceWorker $AcceptanceJob
$diagnostic=Join-Path $EvidenceRoot 'worker-failure.json'
if($Case -eq 'runtime' -or $Case -eq 'primary_cleanup'){
 $global:acceptanceDiagnosticPhase='kit_integrity'
 try{throw 'Pinned bootstrap digest mismatch'}
 catch{
  try{Write-AcceptanceWorkerFailure -Failure $_ -Path $diagnostic -Source prepared_runtime -Phase $global:acceptanceDiagnosticPhase}catch{}
  throw
 }
 finally{if($Case -eq 'primary_cleanup'){$global:acceptanceDiagnosticPhase='owned_cleanup';throw [InvalidOperationException]::new('fixture-sensitive-cleanup-error')}}
}
if($Case -eq 'secret_record'){
 $global:acceptanceDiagnosticPhase='current_receipt'
 $secret='fixture-sensitive-message-arguments-environment-targetobject'
 $exception=[InvalidOperationException]::new(($secret*4096))
 $exception.Data.Add('credential',$secret)
 $errorRecord=[Management.Automation.ErrorRecord]::new($exception,($secret*256),[Management.Automation.ErrorCategory]::InvalidOperation,@{credential=$secret})
 function fixture_sensitive_function_name { param($Record); throw $Record }
 fixture_sensitive_function_name $errorRecord
}
if($Case -eq 'preexisting_output' -or $Case -eq 'denied_output'){
 $global:acceptanceDiagnosticPhase='bootstrap_prior_context'
 throw [InvalidOperationException]::new('fixture-sensitive-diagnostic-output-error')
}
throw 'Unknown synthetic case'
'@
foreach($case in $cases){
 $directory=Join-Path $run $case
 if($case -eq 'secret_record'){$directory=Join-Path $directory 'fixture-sensitive-private-directory'}
 [void][IO.Directory]::CreateDirectory($directory)
 $worker=Join-Path $directory 'diagnostic-fixture-worker.ps1'
 [IO.File]::WriteAllText($worker,$workerBody,[Text.UTF8Encoding]::new($true))
 $diagnostic=Join-Path $directory 'worker-failure.json'
 $sentinel='preserve-preexisting-fixture'
 if($case -eq 'preexisting_output'){[IO.File]::WriteAllText($diagnostic,$sentinel,[Text.UTF8Encoding]::new($false))}
 if($case -eq 'denied_output'){[void][IO.Directory]::CreateDirectory($diagnostic)}
 $clock=[Diagnostics.Stopwatch]::StartNew()
 $exit=Invoke-AcceptanceSupervisor -ScriptPath $worker -Parameters @{AcceptanceScope='PreparedHost';Helper=$helper;Case=$case;EvidenceRoot=$directory} -Clock $clock -LimitSeconds 30 -ReportPath (Join-Path $directory 'supervisor.json') -FailureReportPath (Join-Path $directory 'session-results.json')
 $supervisor=Get-Content -LiteralPath (Join-Path $directory 'supervisor.json') -Raw|ConvertFrom-Json
 $expectedExit=if($case -eq 'partial_exit'){2}else{1}
 $passed=($exit-eq $expectedExit -and $supervisor.worker_exit_code-eq $expectedExit -and $supervisor.cleanup_verified-eq $true -and $supervisor.owned_processes_before_cleanup-eq 0)
 $record=@{case=$case;exit_code=$exit;worker_exit_code=$supervisor.worker_exit_code;cleanup_verified=$supervisor.cleanup_verified;remaining_owned=$supervisor.owned_processes_before_cleanup;passed=$passed;diagnostic_bytes=0;redaction_passed=$true}
 if($case -eq 'preexisting_output'){
  $record.passed=$record.passed -and [IO.File]::ReadAllText($diagnostic)-ceq $sentinel
 }elseif($case -eq 'denied_output'){
  $record.passed=$record.passed -and [IO.Directory]::Exists($diagnostic) -and -not [IO.File]::Exists($diagnostic)
 }elseif($case -eq 'partial_exit'){
  $record.passed=$record.passed -and -not [IO.File]::Exists($diagnostic)
 }else{
  if(-not [IO.File]::Exists($diagnostic)){$record.passed=$false}else{
   $bytes=[IO.File]::ReadAllBytes($diagnostic);$text=[Text.Encoding]::UTF8.GetString($bytes)
   $proof=$text|ConvertFrom-Json
   $record.diagnostic_bytes=$bytes.Length
   $record.redaction_passed=(-not $text.Contains('fixture-sensitive') -and -not $text.Contains('fixture_sensitive') -and -not $text.Contains($directory) -and -not $text.Contains('credential') -and -not $text.Contains('TargetObject'))
   $record.passed=$record.passed -and $record.redaction_passed -and $bytes.Length-le 8192 -and $proof.schema_version-eq 1 -and $proof.exceptions.Count-le 4 -and $proof.stack.Count-le 8
   if($case -eq 'runtime' -or $case -eq 'primary_cleanup'){$record.passed=$record.passed -and $proof.source-ceq 'prepared_runtime' -and $proof.phase-ceq 'kit_integrity' -and $proof.assertion-ceq 'bootstrap_digest_mismatch'}
   if($case -eq 'early'){$record.passed=$record.passed -and $proof.source-ceq 'encoded_wrapper' -and @($proof.exceptions|Where-Object{$_.native_code-eq 5}).Count-gt 0}
  }
 }
 $results+=$record
 [Console]::Out.WriteLine(($record|ConvertTo-Json -Compress))
}
[IO.File]::WriteAllText((Join-Path $run 'regression-results.json'),($results|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$summary=@{native_synthetic_cases=$results.Count;passed=@($results|Where-Object{$_.passed}).Count;failed=@($results|Where-Object{-not $_.passed}).Count;all_private_job_cleanup_verified=@($results|Where-Object{-not $_.cleanup_verified -or $_.remaining_owned-ne 0}).Count-eq 0;run_root=$run;product_executed=$false;security_changes=$false}
$summary|ConvertTo-Json
if($summary.failed){exit 1}
