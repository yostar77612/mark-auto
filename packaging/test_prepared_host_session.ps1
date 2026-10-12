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
  # Stack labels are untrusted display text (including <No file>), never paths.
  # Bound allocation and matching; malformed/oversized frames cannot mask the failure.
  try {
    $trace=[string]$Failure.ScriptStackTrace
    $trace=$trace.Substring(0,[Math]::Min($trace.Length,16384))
    foreach ($line in @($trace -split "`n" | Select-Object -First 8)) {
      $frame=[regex]::Match($line,'^at ([^,\r\n]{1,128}), ([^\r\n]{1,2048}): line ([0-9]{1,10})\s*$')
      if (-not $frame.Success) { continue }
      $function=$frame.Groups[1].Value; $label=$frame.Groups[2].Value; $file='other-script'
      foreach ($known in @('test_prepared_host_session.ps1','prepared_host_session.ps1','acceptance_process.ps1')) {
        if ($label -ceq $known -or $label.EndsWith(('\'+$known),[StringComparison]::Ordinal) -or $label.EndsWith(('/'+$known),[StringComparison]::Ordinal)) { $file=$known; break }
      }
      $number=0
      if (-not [int]::TryParse($frame.Groups[3].Value,[ref]$number)) { $number=0 }
      if ($function -notin @('<ScriptBlock>','Require','Reject','Test-PreparedNavigation','Confirm-AcceptanceWorker',
          'Start-OwnedAcceptanceProcess','Assert-OwnedAcceptanceProcess','Wait-OwnedAcceptanceWindow',
          'Wait-OwnedAcceptanceProcess','Close-AcceptanceProcesses','Read-PreparedBootstrap')) { $function='other-function' }
      [void]$frames.Add(@{script=$file;function=$function;line=$number})
    }
  } catch { $frames.Clear() } # Diagnostic text must never prevent reports or owned cleanup.
  return @{status='failed';stage=$Stage;case=$UiCase;assertion=$assertion;exceptions=@($chain);native_code=$native;
    ui_phase=$script:preparedUiPhase;ui_elements=$script:preparedUiElements;
    ui_navigation_found=$script:preparedUiFound;ui_selections=$script:preparedUiSelected;stack=@($frames)}
}
function Write-PreparedFixtureReport([string]$Name, $Record) {
  if ($Name -notmatch '^(owned|foreign)-(primary|cleanup|supervisor|proof|readiness)\.(json|txt)$' -and $Name -notin @('bootstrap.json','controller.json','controller-cleanup.json')) { throw 'Unknown native evidence name' }
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
$evidenceReady=$false
try {
  . (Join-Path $PSScriptRoot 'acceptance_process.ps1')
  if (-not $isFixtureWorker) {
    Assert-AcceptancePath $nativeEvidence -RequireAbsent
    [void][IO.Directory]::CreateDirectory($nativeEvidence)
    $evidenceReady=$true
    Write-PreparedFixtureReport 'bootstrap.json' @{status='started';stage='ownership_helper_loaded'}
  }
  $workerStage='import_session_routines'
  $savedJob=$AcceptanceJob
  . (Join-Path $PSScriptRoot 'prepared_host_session.ps1')
  $AcceptanceJob=$savedJob
} catch {
  if ($isFixtureWorker -and $UiCase -in @('owned','foreign')) { Write-PreparedFixtureReport ($UiCase+'-primary.json') (Get-PreparedFixtureFailure $_ $workerStage) }
  elseif ($evidenceReady) { Write-PreparedFixtureReport 'controller.json' (Get-PreparedFixtureFailure $_ $workerStage) }
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
    $ownedReady=Join-Path (Split-Path $UiFixture -Parent) ($UiCase+'-owned.ready')
    Assert-AcceptancePath $ownedReady -RequireAbsent
    $renderClock=[Diagnostics.Stopwatch]::StartNew()
    $owned=Start-OwnedAcceptanceProcess $UiFixture @('"'+$ownedReady+'"')
    $workerStage='wait_owned_window'
    Wait-OwnedAcceptanceWindow $owned
    $workerStage='wait_owned_render'
    # Readiness shares the existing 30-second supervisor cap and five-second reserve.
    while (-not [IO.File]::Exists($ownedReady)) {
      Assert-OwnedAcceptanceProcess $owned
      Require (-not $owned.Process.get_HasExited()) 'Owned fixture exited before rendering'
      Require ($renderClock.Elapsed.TotalSeconds -lt 25) 'Owned fixture rendering timed out'
      Start-Sleep -Milliseconds 50
    }
    Require ([IO.File]::ReadAllText($ownedReady) -ceq 'ready-seven-rendered') 'Owned fixture render proof invalid'
    Write-PreparedFixtureReport ($UiCase+'-readiness.json') @{status='passed';framework='WPF';stage='content_rendered';realized_items=7}
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
$controllerStage='preparation_controls'
$fixture=Join-Path $env:TEMP ('prepared-state-'+[guid]::NewGuid().ToString('N'))
$fixtureCreated=$false; $outsider=$null
try {
  Assert-AcceptancePath $fixture -RequireAbsent
  [void][IO.Directory]::CreateDirectory($fixture)
  $fixtureCreated=$true
  $syntheticFailure=$null
  try { throw (New-Object InvalidOperationException('synthetic-private-message C:\private-fixture\value')) }
  catch { $syntheticFailure=$_ }
  $safeDiagnostic=Get-PreparedFixtureFailure $syntheticFailure 'diagnostic_control'
  $safeJson=$safeDiagnostic | ConvertTo-Json -Depth 7 -Compress
  Require ($safeDiagnostic.exceptions.Count -le 4 -and $safeDiagnostic.stack.Count -le 8) 'Native diagnostic bounds exceeded'
  Require (@($safeDiagnostic.exceptions | Where-Object { $_.type -eq 'System.InvalidOperationException' }).Count -eq 1) 'Native diagnostic lost original exception type'
  Require (-not $safeJson.Contains('synthetic-private-message') -and -not $safeJson.Contains('private-fixture') -and -not $safeJson.Contains($fixture)) 'Native diagnostic leaked a message or path'
  $stackCases=@(
    @{trace='at <ScriptBlock>, <No file>: line 1';count=1;file='other-script';number=1},
    @{trace=('at Require, C:\private-fixture\bad'+[char]0+'<>"|.ps1: line 2');count=1;file='other-script';number=2},
    @{trace='at Require, C:\private-fixture\test_prepared_host_session.ps1: line 7';count=1;file='test_prepared_host_session.ps1';number=7},
    @{trace='at Require, /private-fixture/prepared_host_session.ps1: line 2147483648';count=1;file='prepared_host_session.ps1';number=0},
    @{trace=('at Require, acceptance_process.ps1: line '+('9'*1000));count=0;file='';number=0},
    @{trace='unstructured private-fixture text';count=0;file='';number=0},
    @{trace=('x'*20000);count=0;file='';number=0},
    @{trace=$null;count=0;file='';number=0},
    @{trace=(('at Require, acceptance_process.ps1: line 3'+"`n")*9);count=8;file='acceptance_process.ps1';number=3}
  )
  foreach ($sample in $stackCases) {
    $diagnostic=Get-PreparedFixtureFailure ([pscustomobject]@{Exception=$syntheticFailure.Exception;ScriptStackTrace=$sample.trace}) 'diagnostic_control'
    Require ($diagnostic.stack.Count -eq $sample.count) 'Native diagnostic malformed-stack count changed'
    foreach ($frame in $diagnostic.stack) {
      Require ($frame.script -ceq $sample.file -and $frame.line -eq $sample.number) 'Native diagnostic basename or line was not sanitized'
    }
    $json=$diagnostic | ConvertTo-Json -Depth 7 -Compress
    Require (-not $json.Contains('private-fixture') -and -not $json.Contains('synthetic-private-message') -and -not $json.Contains('<No file>')) 'Native diagnostic leaked untrusted stack text'
  }
  [Console]::Out.WriteLine('{"stage":"diagnostic_controls","status":"passed","cases":9}')
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
  # Resolve installed strong-named .NET Framework assemblies, not a search-path guess.
  $wpfReferences=@('PresentationFramework','PresentationCore','WindowsBase','System.Xaml') | ForEach-Object {
    $token=if ($_ -ceq 'System.Xaml') { 'b77a5c561934e089' } else { '31bf3856ad364e35' }
    [Reflection.Assembly]::Load(($_+', Version=4.0.0.0, Culture=neutral, PublicKeyToken='+$token)).get_Location()
  }
  Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
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
        if(args.Length!=1 && args.Length!=2) throw new InvalidOperationException("Fixture readiness target required");
        var app=new Application(); app.ShutdownMode=ShutdownMode.OnMainWindowClose;
        var form=new Window(); form.Title="Prepared-host native fixture"; form.Width=640; form.Height=480;
        var list=new ListBox(); list.SelectionMode=SelectionMode.Single; list.IsTabStop=false;
        // Built-in WPF peers expose actual ListItems; no custom accessibility provider.
        VirtualizingPanel.SetIsVirtualizing(list,false);
        foreach(string label in new string[] {"市場總覽","資料匯入與更新","AI 策略中心","回測與結果","比較與策略選擇","紙上交易與復原","設定與備份"}) {
            list.Items.Add(new ListBoxItem { Content=label });
        }
        form.Content=list; bool armed=false;
        list.SelectionChanged+=delegate { if(armed && args.Length==2) File.WriteAllText(args[1],"foreign navigation touched"); };
        form.ContentRendered+=delegate {
            if(armed) return;
            if(list.Items.Count!=7) throw new InvalidOperationException("Fixture item count changed");
            for(int i=0;i<7;i++) {
                var item=list.ItemContainerGenerator.ContainerFromIndex(i) as ListBoxItem;
                if(item==null || !item.IsVisible) throw new InvalidOperationException("Fixture item not realized");
            }
            list.SelectedIndex=-1; armed=true;
            // Atomic publication prevents the controller observing an incomplete marker.
            File.WriteAllText(args[0]+".tmp","ready-seven-rendered"); File.Move(args[0]+".tmp",args[0]);
        };
        var timer=new DispatcherTimer(); timer.Interval=TimeSpan.FromMilliseconds(120000);
        timer.Tick+=delegate { form.Close(); }; timer.Start();
        try { app.Run(form); } finally { timer.Stop(); }
    }
}
'@ -ReferencedAssemblies $wpfReferences -OutputAssembly $exe -OutputType WindowsApplication
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
  Require ([IO.File]::ReadAllText($ready) -ceq 'ready-seven-rendered') 'Foreign fixture render proof invalid'
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
    if ($fixtureCreated) { Remove-Item -LiteralPath $fixture -Recurse -Force }
  }
}
