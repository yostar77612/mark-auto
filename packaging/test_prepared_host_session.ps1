param([string]$AcceptanceJob='', [string]$UiFixture='', [string]$UiCase='', [long]$ForeignWindow=0, [string]$UiProof='')
# Native preparation controls only; this fixture never touches a host MarkAuto profile.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Native preparation fixtures require the ephemeral CI runner' }
function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Reject([scriptblock]$Action,[string]$Message,[string]$ExpectedFailure) {
  $rejected=$false
  try { & $Action } catch { if ($_.Exception.Message -cne $ExpectedFailure) { throw }; $rejected=$true }
  Require $rejected $Message
}
# Fixed fields only: no raw messages, command lines, environment values or full paths.
function Get-PreparedFixtureFailure($Failure, [string]$Stage) {
  $exception=$Failure.Exception; $chain=New-Object System.Collections.ArrayList; $native=$null
  for ($i=0; $exception -and $i -lt 4; $i++) {
    [void]$chain.Add(@{type=$exception.GetType().FullName; hresult=$exception.HResult})
    if ($exception -is [ComponentModel.Win32Exception]) { $native=$exception.NativeErrorCode }
    $exception=$exception.InnerException
  }
  $assertions=@{
    'Owned native UIA positive control incomplete'='owned_navigation_incomplete';
    'UI root ownership not proven'='root_ownership';
    'UI descendant ownership not proven'='descendant_ownership';
    'Navigation ownership changed'='selection_ownership';
    'Owned application window is not visibly exposed'='window_not_visible';
    'Application navigation selection not confirmed'='selection_unconfirmed';
    'Ambiguous application navigation'='ambiguous_navigation';
    'Application UI inventory exceeds bounded scope'='ui_inventory_limit';
    'Owned fixture close rejected'='close_rejected';
    'Owned fixture close timed out'='close_timeout';
    'Owned fixture failed'='fixture_exit';
    'Native UIA case or cleanup failed'='case_or_cleanup';
    'Foreign HWND accepted'='foreign_accepted';
    'Foreign HWND reached control metadata or navigation'='foreign_metadata';
    'Foreign fixture navigation was touched'='foreign_selection'
  }
  $assertion='unclassified'
  $message=$Failure.Exception.GetBaseException().Message
  if ($assertions.ContainsKey($message)) { $assertion=$assertions[$message] }
  $frames=New-Object System.Collections.ArrayList
  foreach ($line in @($Failure.ScriptStackTrace -split "`n" | Select-Object -First 8)) {
    if ($line -match '^at ([^,]+), (.+): line ([0-9]+)\s*$') {
      $function=$Matches[1]; $file=[IO.Path]::GetFileName($Matches[2]); $number=[int]$Matches[3]
      if ($file -notin @('test_prepared_host_session.ps1','prepared_host_session.ps1','acceptance_process.ps1')) { $file='other-script' }
      if ($function -notin @('<ScriptBlock>','Require','Reject','Test-PreparedNavigation','Confirm-AcceptanceWorker',
          'Start-OwnedAcceptanceProcess','Assert-OwnedAcceptanceProcess','Wait-OwnedAcceptanceWindow',
          'Wait-OwnedAcceptanceProcess','Close-AcceptanceProcesses','Read-PreparedBootstrap')) { $function='other-function' }
      [void]$frames.Add(@{script=$file;function=$function;line=$number})
    }
  }
  return @{status='failed';stage=$Stage;case=$UiCase;assertion=$assertion;exceptions=@($chain);native_code=$native;
    ui_phase=$script:preparedUiPhase;ui_elements=$script:preparedUiElements;
    ui_navigation_found=$script:preparedUiFound;ui_selections=$script:preparedUiSelected;stack=@($frames)}
}
function Write-PreparedFixtureReport([string]$Name, $Record) {
  if ($Name -notmatch '^(owned|foreign)-(primary|cleanup|supervisor|proof)\.(json|txt)$' -and $Name -notin @('controller.json','controller-cleanup.json')) { throw 'Unknown native evidence name' }
  $json=$Record | ConvertTo-Json -Depth 7 -Compress
  [Console]::Out.WriteLine($json)
  $bytes=[Text.Encoding]::UTF8.GetBytes($json)
  $path=Join-Path $nativeEvidence $Name
  $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
  try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
$nativeEvidence=Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\validation\prepared-host-native'
$script:preparedUiPhase='not_entered'; $script:preparedUiElements=0; $script:preparedUiFound=0; $script:preparedUiSelected=0
$workerStage='load_ownership_helper'
$isFixtureWorker=[bool]$AcceptanceJob
try {
  . (Join-Path $PSScriptRoot 'acceptance_process.ps1')
  $workerStage='import_session_routines'
  $savedJob=$AcceptanceJob
  . (Join-Path $PSScriptRoot 'prepared_host_session.ps1')
  $AcceptanceJob=$savedJob
} catch {
  if ($isFixtureWorker -and $UiCase -in @('owned','foreign')) { Write-PreparedFixtureReport ($UiCase+'-primary.json') (Get-PreparedFixtureFailure $_ $workerStage) }
  throw
}
if ($AcceptanceJob) {
  $script:acceptanceProcesses=New-Object System.Collections.ArrayList
  $imageLease=$null; $primaryFailure=$null; $cleanupFailure=$null
  try {
    $workerStage='confirm_worker'
    Confirm-AcceptanceWorker $AcceptanceJob
    $workerStage='hash_fixture'
    $imageDigest=(Get-FileHash -LiteralPath $UiFixture -Algorithm SHA256).Hash.ToLowerInvariant()
    $workerStage='lease_fixture'
    $imageLease=Read-PreparedBootstrap $UiFixture $imageDigest 1MB -Hold
    $workerStage='load_fixture_assembly'
    [void][Reflection.Assembly]::Load([IO.File]::ReadAllBytes($UiFixture))
    $workerStage='create_owned_fixture'
    $owned=Start-OwnedAcceptanceProcess $UiFixture
    $workerStage='wait_owned_window'
    Wait-OwnedAcceptanceWindow $owned
    $real=$owned.Process
    try {
      if ($UiCase -eq 'foreign') {
        # Only the observation wrapper changes; both genuinely owned handles stay retained.
        $owned.Process=New-Object PreparedFixtureView($real,[IntPtr]$ForeignWindow)
        $workerStage='foreign_navigation'
        Reject { Test-PreparedNavigation $owned } 'Foreign HWND accepted' 'UI root ownership not proven'
        Require ($script:preparedUiPhase -ceq 'root_ownership') 'Foreign HWND reached control metadata or navigation'
        [IO.File]::WriteAllText($UiProof,'foreign-root-refused-before-metadata')
      } elseif ($UiCase -eq 'owned') {
        $workerStage='owned_navigation'
        $result=Test-PreparedNavigation $owned
        $workerStage='assert_owned_navigation'
        Require ($result.status -ceq 'observed' -and $result.selected_pages.Count -eq 7) 'Owned native UIA positive control incomplete'
        [IO.File]::WriteAllText($UiProof,'owned-seven-selections-observed')
      } else { throw 'Unknown UI fixture case' }
    } finally { $owned.Process=$real }
    $workerStage='close_owned_window'
    Require ($real.CloseMainWindow()) 'Owned fixture close rejected'
    $workerStage='wait_owned_close'
    Wait-OwnedAcceptanceProcess $owned 5000 'Owned fixture close timed out' -DrainJob
    Require ($real.get_ExitCode() -eq 0) 'Owned fixture failed'
  } catch { $primaryFailure=$_ }
  finally {
    # Persist original failure before cleanup can throw a different exception.
    try {
      $primary=if ($primaryFailure) { Get-PreparedFixtureFailure $primaryFailure $workerStage } else { @{status='passed';case=$UiCase;stage='assertions_complete'} }
      Write-PreparedFixtureReport ($UiCase+'-primary.json') $primary
    }
    finally {
      try { Close-AcceptanceProcesses } catch { $cleanupFailure=$_ }
      finally {
        try { if ($imageLease) { $imageLease.Dispose() } }
        catch { if (-not $cleanupFailure) { $cleanupFailure=$_ } }
      }
      $cleanup=if ($cleanupFailure) { Get-PreparedFixtureFailure $cleanupFailure 'close_records_or_lease' } else { @{status='passed';case=$UiCase;stage='records_and_lease_closed'} }
      Write-PreparedFixtureReport ($UiCase+'-cleanup.json') $cleanup
    }
  }
  if ($primaryFailure) { throw $primaryFailure }
  if ($cleanupFailure) { throw $cleanupFailure }
  exit 0
}
Assert-AcceptancePath $nativeEvidence -RequireAbsent
[void][IO.Directory]::CreateDirectory($nativeEvidence)
$controllerStage='preparation_controls'
$fixture=Join-Path $env:TEMP ('prepared-state-'+[guid]::NewGuid().ToString('N'))
Assert-AcceptancePath $fixture -RequireAbsent
[void][IO.Directory]::CreateDirectory($fixture)
$outsider=$null
try {
  $syntheticFailure=$null
  try { throw (New-Object InvalidOperationException('synthetic-private-message C:\private-fixture\value')) }
  catch { $syntheticFailure=$_ }
  $safeDiagnostic=Get-PreparedFixtureFailure $syntheticFailure 'diagnostic_control'
  $safeJson=$safeDiagnostic | ConvertTo-Json -Depth 7 -Compress
  Require ($safeDiagnostic.exceptions.Count -le 4 -and $safeDiagnostic.stack.Count -le 8) 'Native diagnostic bounds exceeded'
  Require (@($safeDiagnostic.exceptions | Where-Object { $_.type -eq 'System.InvalidOperationException' }).Count -eq 1) 'Native diagnostic lost original exception type'
  Require (-not $safeJson.Contains('synthetic-private-message') -and -not $safeJson.Contains('private-fixture') -and -not $safeJson.Contains($fixture)) 'Native diagnostic leaked a message or path'
  $source=Join-Path $fixture 'source'; [void][IO.Directory]::CreateDirectory($source)
  Assert-PreparedSeparateRoots $source (Join-Path $fixture 'peer-session')
  Reject { Assert-PreparedSeparateRoots $source (Join-Path $source 'child') } 'Session nested inside kit was accepted' 'Kit and session directories must not overlap'
  Reject { Assert-PreparedSeparateRoots (Join-Path $source 'child') $source } 'Kit nested inside session was accepted' 'Kit and session directories must not overlap'
  Reject { Assert-PreparedSeparateRoots $source $source } 'Kit reused as session was accepted' 'Kit and session directories must not overlap'
  [void][IO.Directory]::CreateDirectory((Join-Path $source 'empty'))
  [IO.File]::WriteAllText((Join-Path $source 'installer-preservation-test.txt'),'test-only-sentinel')
  $sentinelPath=Join-Path $source 'installer-preservation-test.txt'
  $sentinelHash=(Get-FileHash -LiteralPath $sentinelPath -Algorithm SHA256).Hash.ToLowerInvariant()
  Require ((Read-PreparedBootstrap $sentinelPath $sentinelHash 1KB -Text) -ceq 'test-only-sentinel') 'Read-only bootstrap changed content'
  $writer=[IO.File]::Open($sentinelPath,[IO.FileMode]::Open,[IO.FileAccess]::Write); $writer.Dispose()
  $held=Read-PreparedBootstrap $sentinelPath $sentinelHash 1KB -Hold
  try {
    $writeRefused=$false
    try { $writer=[IO.File]::Open($sentinelPath,[IO.FileMode]::Open,[IO.FileAccess]::Write); $writer.Dispose() }
    catch { $writeRefused=($_.Exception.GetBaseException() -is [IO.IOException]) }
    Require $writeRefused 'Digest-verified helper lease allowed replacement/write'
  } finally { $held.Dispose() }
  $writer=[IO.File]::Open($sentinelPath,[IO.FileMode]::Open,[IO.FileAccess]::Write); $writer.Dispose()
  Require ((Get-FileHash -LiteralPath $sentinelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $sentinelHash) 'Read-only bootstrap lease changed source'
  Reject { Read-PreparedBootstrap $sentinelPath ('0'*64) 1KB } 'Wrong bootstrap digest accepted' 'Pinned bootstrap digest mismatch'
  Reject { Read-PreparedBootstrap $sentinelPath $sentinelHash 1 } 'Oversized bootstrap accepted' 'Bootstrap input exceeds bounded size'
  $redirect=Join-Path $fixture 'redirect'
  New-Item -ItemType Junction -Path $redirect -Target $source | Out-Null
  try {
    Reject { Read-PreparedBootstrap (Join-Path $redirect 'installer-preservation-test.txt') $sentinelHash 1KB } 'Bootstrap redirect was followed' 'Bootstrap redirect refused before content reads'
  } finally { [IO.Directory]::Delete($redirect) }
  $enumerator=[IO.Directory]::EnumerateFileSystemEntries($source).GetEnumerator()
  try {
    Require ($enumerator -is [Collections.IEnumerator] -and $enumerator -isnot [Array]) 'PowerShell eagerly unrolled the inventory iterator'
    Require ($enumerator.MoveNext() -and $enumerator.get_Current() -is [string]) 'Native inventory iterator did not yield one entry'
  } finally { $enumerator.Dispose() }
  $many=Join-Path $fixture 'entry-limit'; [void][IO.Directory]::CreateDirectory($many)
  for ($index=0; $index -lt 4097; $index++) { [void][IO.Directory]::CreateDirectory((Join-Path $many ('item-'+$index))) }
  Reject { Get-PreparedStateInventory $many } 'Inventory entry cap was bypassed' 'Prepared test inventory exceeds bounded scope'
  Require ([IO.Directory]::GetDirectories($many).Length -eq 4097) 'Bounded inventory refusal changed fixture entries'
  $inventory=Get-PreparedStateInventory $source
  $receipt=$inventory | ConvertTo-Json -Depth 5 | ConvertFrom-Json
  Confirm-PreparedStateInventory $inventory $receipt
  $backup=Join-Path $fixture 'backup'
  Backup-PreparedState $source $backup $receipt
  Require ([IO.File]::ReadAllText((Join-Path $backup 'installer-preservation-test.txt')) -ceq 'test-only-sentinel') 'Backup changed exact sentinel bytes'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $source) $receipt
  Reject { Backup-PreparedState $source $backup $receipt } 'Existing backup overwritten' 'Existing MarkAuto destination refused; original state preserved'
  [IO.File]::WriteAllText((Join-Path $source 'unknown.txt'),'unexplained')
  Reject { Backup-PreparedState $source (Join-Path $fixture 'unknown-backup') $receipt } 'Unexplained file was accepted' 'Unexplained prepared data entries; originals preserved'
  Require (-not [IO.Directory]::Exists((Join-Path $fixture 'unknown-backup'))) 'Rejected source created a backup'
  [IO.File]::Delete((Join-Path $source 'unknown.txt'))
  [void][IO.Directory]::CreateDirectory((Join-Path $source 'unknown-directory'))
  Reject { Confirm-PreparedStateInventory (Get-PreparedStateInventory $source) $receipt } 'Unexplained empty directory accepted' 'Unexplained prepared data entries; originals preserved'
  [IO.Directory]::Delete((Join-Path $source 'unknown-directory'))
  [IO.File]::WriteAllText((Join-Path $source 'installer-preservation-test.txt'),'changed')
  Reject { Backup-PreparedState $source (Join-Path $fixture 'changed-backup') $receipt } 'Changed sentinel was accepted' 'Prepared data digest changed; originals preserved'
  [IO.File]::WriteAllText((Join-Path $source 'installer-preservation-test.txt'),'test-only-sentinel')
  $credentials=Join-Path $source 'credentials'; [void][IO.Directory]::CreateDirectory($credentials)
  [IO.File]::WriteAllText((Join-Path $credentials 'synthetic-marker.bin'),'fixture-not-a-credential')
  Reject { Get-PreparedStateInventory $source } 'Credential-bearing directory was opened as ordinary test data' 'Credential-bearing state is outside this test phase'
  [IO.File]::Delete((Join-Path $credentials 'synthetic-marker.bin')); [IO.Directory]::Delete($credentials)
  $malicious=@{directories=@('../escape');files_sha256=@{'../escape'=('a'*64)}}
  Reject { Backup-PreparedState $source (Join-Path $fixture 'escaped-backup') $malicious } 'Receipt paths escaped backup ownership' 'Unexplained prepared data entries; originals preserved'
  Require (-not [IO.File]::Exists((Join-Path $fixture 'escape'))) 'Untrusted receipt created an output'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $source) $receipt
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $backup) $receipt
  [Console]::Out.WriteLine('{"stage":"preparation_controls","status":"passed"}')
  $controllerStage='compile_window_fixture'
  $exe=Join-Path $fixture 'PreparedUiFixture.exe'
  Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
public sealed class PreparedFixtureView {
    readonly Process process; readonly IntPtr window;
    public PreparedFixtureView(Process process, IntPtr window) { this.process=process; this.window=window; }
    public void Refresh() { process.Refresh(); }
    public bool HasExited { get { return process.HasExited; } }
    public IntPtr Handle { get { return process.Handle; } }
    public IntPtr MainWindowHandle { get { return window; } }
    public int Id { get { return process.Id; } }
}
public static class PreparedUiFixture {
    [STAThread] public static void Main(string[] args) {
        Application.EnableVisualStyles();
        using(var form=new Form()) using(var list=new ListBox()) using(var timer=new Timer()) {
            form.Text="Prepared-host native fixture"; form.Width=640; form.Height=480;
            list.Dock=DockStyle.Fill; list.TabStop=false;
            list.Items.AddRange(new object[] {"市場總覽","資料匯入與更新","AI 策略中心","回測與結果","比較與策略選擇","紙上交易與復原","設定與備份"});
            form.Controls.Add(list); bool armed=false;
            list.SelectedIndexChanged+=delegate { if(armed && args.Length==2) File.WriteAllText(args[1],"foreign navigation touched"); };
            form.Shown+=delegate { list.ClearSelected(); armed=true; if(args.Length==2) File.WriteAllText(args[0],"ready"); };
            timer.Interval=120000; timer.Tick+=delegate { form.Close(); }; timer.Start();
            Application.Run(form);
        }
    }
}
'@ -ReferencedAssemblies System.Windows.Forms,System.Drawing -OutputAssembly $exe -OutputType WindowsApplication
  $controllerStage='outsider_setup'
  $ready=Join-Path $fixture 'foreign.ready'; $touched=Join-Path $fixture 'foreign.selected'
  $start=New-Object Diagnostics.ProcessStartInfo
  $start.FileName=$exe; $start.UseShellExecute=$false; $start.Arguments='"'+$ready+'" "'+$touched+'"'
  $outsider=[Diagnostics.Process]::Start($start)
  $outsiderHandle=$outsider.get_Handle(); $outsiderCreated=[MarkAutoAcceptanceJob]::Created($outsiderHandle)
  $readyClock=[Diagnostics.Stopwatch]::StartNew()
  do {
    $outsider.Refresh()
    Require (-not $outsider.get_HasExited()) 'Foreign fixture exited during setup'
    if ([IO.File]::Exists($ready) -and $outsider.get_MainWindowHandle() -ne [IntPtr]::Zero) { break }
    Require ($readyClock.Elapsed.TotalSeconds -lt 10) 'Foreign fixture window did not become ready'
    Start-Sleep -Milliseconds 50
  } while ($true)
  Require (-not [IO.File]::Exists($touched)) 'Foreign fixture navigation precondition changed'
  foreach ($case in @('owned','foreign')) {
    $controllerStage=$case+'_case'
    $report=Join-Path $nativeEvidence ($case+'-supervisor.json'); $proof=Join-Path $nativeEvidence ($case+'-proof.txt')
    $parameters=@{UiFixture=$exe;UiCase=$case;ForeignWindow=$outsider.get_MainWindowHandle().ToInt64();UiProof=$proof}
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $code=Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath -Parameters $parameters -Clock $clock -LimitSeconds 30 -ReportPath $report
    $jobReport=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    [Console]::Out.WriteLine((@{case=$case;worker_exit=$jobReport.worker_exit_code;supervisor_exit=$code;supervisor_reason=$jobReport.reason;cleanup_verified=$jobReport.cleanup_verified} | ConvertTo-Json -Compress))
    Require ($code -eq 0 -and $jobReport.cleanup_verified -eq $true) 'Native UIA case or cleanup failed'
    $expected=if ($case -eq 'owned') { 'owned-seven-selections-observed' } else { 'foreign-root-refused-before-metadata' }
    Require ([IO.File]::ReadAllText($proof) -ceq $expected) 'Native UIA case lacks exact proof'
    Require (-not $outsider.get_HasExited() -and [MarkAutoAcceptanceJob]::Created($outsiderHandle) -eq $outsiderCreated) 'Foreign fixture process changed'
    Require (-not [IO.File]::Exists($touched)) 'Foreign fixture navigation was touched'
  }
  Write-PreparedFixtureReport 'controller.json' @{status='passed';stage='all_controls_complete'}
  Write-Host 'Prepared-host UIA controls: owned seven-page selection and foreign HWND refusal before metadata passed'
  Write-Host 'Prepared-host backup controls: exact bytes, absent output, changed state, extra files/directories, credentials and receipt traversal passed'
} catch {
  Write-PreparedFixtureReport 'controller.json' (Get-PreparedFixtureFailure $_ $controllerStage)
  throw
} finally {
  try {
    if ($outsider) {
      try {
        if (-not $outsider.get_HasExited()) {
          [void]$outsider.CloseMainWindow()
          if (-not $outsider.WaitForExit(1000)) {
            try { $outsider.Kill() } catch { if (-not $outsider.WaitForExit(0)) { throw } }
            Require ($outsider.WaitForExit(1000)) 'Foreign fixture retained-handle cleanup failed'
          }
        }
      } finally { $outsider.Dispose() }
    }
  } catch {
    Write-PreparedFixtureReport 'controller-cleanup.json' (Get-PreparedFixtureFailure $_ 'outsider_cleanup')
    throw
  } finally {
    # Durable sanitized reports are outside this exact owned scratch directory.
    # This exact random fixture was created above; no host app state is touched.
    Remove-Item -LiteralPath $fixture -Recurse -Force
  }
}
