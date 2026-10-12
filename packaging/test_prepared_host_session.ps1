param([string]$AcceptanceJob='', [string]$UiFixture='', [string]$UiCase='', [long]$ForeignWindow=0, [string]$UiProof='')
# Native preparation controls only; this fixture never touches a host MarkAuto profile.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Native preparation fixtures require the ephemeral CI runner' }
. (Join-Path $PSScriptRoot 'acceptance_process.ps1')
$savedJob=$AcceptanceJob
. (Join-Path $PSScriptRoot 'prepared_host_session.ps1')
$AcceptanceJob=$savedJob
function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Reject([scriptblock]$Action,[string]$Message,[string]$ExpectedFailure) {
  $rejected=$false
  try { & $Action } catch { if ($_.Exception.Message -cne $ExpectedFailure) { throw }; $rejected=$true }
  Require $rejected $Message
}
if ($AcceptanceJob) {
  Confirm-AcceptanceWorker $AcceptanceJob
  $script:acceptanceProcesses=New-Object System.Collections.ArrayList
  $imageLease=$null
  try {
    $imageDigest=(Get-FileHash -LiteralPath $UiFixture -Algorithm SHA256).Hash.ToLowerInvariant()
    $imageLease=Read-PreparedBootstrap $UiFixture $imageDigest 1MB -Hold
    [void][Reflection.Assembly]::Load([IO.File]::ReadAllBytes($UiFixture))
    $owned=Start-OwnedAcceptanceProcess $UiFixture
    Wait-OwnedAcceptanceWindow $owned
    $real=$owned.Process
    try {
      if ($UiCase -eq 'foreign') {
        # Only the observation wrapper changes; both genuinely owned handles stay retained.
        $owned.Process=New-Object PreparedFixtureView($real,[IntPtr]$ForeignWindow)
        Reject { Test-PreparedNavigation $owned } 'Foreign HWND accepted' 'UI root ownership not proven'
        Require ($script:preparedUiPhase -ceq 'root_ownership') 'Foreign HWND reached control metadata or navigation'
        [IO.File]::WriteAllText($UiProof,'foreign-root-refused-before-metadata')
      } elseif ($UiCase -eq 'owned') {
        $result=Test-PreparedNavigation $owned
        Require ($result.status -ceq 'observed' -and $result.selected_pages.Count -eq 7) 'Owned native UIA positive control incomplete'
        [IO.File]::WriteAllText($UiProof,'owned-seven-selections-observed')
      } else { throw 'Unknown UI fixture case' }
    } finally { $owned.Process=$real }
    Require ($real.CloseMainWindow()) 'Owned fixture close rejected'
    Wait-OwnedAcceptanceProcess $owned 5000 'Owned fixture close timed out' -DrainJob
    Require ($real.get_ExitCode() -eq 0) 'Owned fixture failed'
  } finally { try { Close-AcceptanceProcesses } finally { if ($imageLease) { $imageLease.Dispose() } } }
  exit 0
}
$fixture=Join-Path $env:TEMP ('prepared-state-'+[guid]::NewGuid().ToString('N'))
Assert-AcceptancePath $fixture -RequireAbsent
[void][IO.Directory]::CreateDirectory($fixture)
$outsider=$null
try {
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
    $report=Join-Path $fixture ($case+'-supervisor.json'); $proof=Join-Path $fixture ($case+'-proof.txt')
    $parameters=@{UiFixture=$exe;UiCase=$case;ForeignWindow=$outsider.get_MainWindowHandle().ToInt64();UiProof=$proof}
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $code=Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath -Parameters $parameters -Clock $clock -LimitSeconds 30 -ReportPath $report
    $jobReport=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    Require ($code -eq 0 -and $jobReport.cleanup_verified -eq $true) 'Native UIA case or cleanup failed'
    $expected=if ($case -eq 'owned') { 'owned-seven-selections-observed' } else { 'foreign-root-refused-before-metadata' }
    Require ([IO.File]::ReadAllText($proof) -ceq $expected) 'Native UIA case lacks exact proof'
    Require (-not $outsider.get_HasExited() -and [MarkAutoAcceptanceJob]::Created($outsiderHandle) -eq $outsiderCreated) 'Foreign fixture process changed'
    Require (-not [IO.File]::Exists($touched)) 'Foreign fixture navigation was touched'
  }
  Write-Host 'Prepared-host UIA controls: owned seven-page selection and foreign HWND refusal before metadata passed'
  Write-Host 'Prepared-host backup controls: exact bytes, absent output, changed state, extra files/directories, credentials and receipt traversal passed'
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
  } finally {
    # This exact random fixture was created above; no host app state is touched.
    Remove-Item -LiteralPath $fixture -Recurse -Force
  }
}
