# Native regression tests run in Windows PowerShell 5.1 on an ephemeral CI runner.
# All files/registry values/processes below are exclusively created by this test.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Native regression fixtures require a GitHub-hosted ephemeral runner' }
. (Join-Path $PSScriptRoot 'acceptance_process.ps1')
# The existing ephemeral quality job enforces a 15-minute outer timeout.
# This fixture adds checkpoints under that same bound; no case budget changes.
$suiteClock=[Diagnostics.Stopwatch]::StartNew()
$suiteLimitSeconds=900
function Check([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Native-Code($ErrorRecord) {
  $exception=$ErrorRecord.Exception
  while ($exception) {
    if ($exception -is [ComponentModel.Win32Exception]) { return $exception.NativeErrorCode }
    $exception=$exception.InnerException
  }
  return $null
}

$fixture = Join-Path $env:TEMP ("markauto ownership's-" + [guid]::NewGuid().ToString('N'))
New-Item $fixture -ItemType Directory | Out-Null
$outsider = $null
$outsiderStop=Join-Path $fixture 'outsider-complete'
$registration = 'Software\MarkAuto-TestLab\' + [guid]::NewGuid().ToString('N')
try {
  . (Join-Path $PSScriptRoot 'test_shortcut_reader.ps1')
  Test-AcceptanceShortcutReader (Join-Path $fixture 'unicode-shortcuts')
  $name='Local\MarkAutoAcceptance-Test-' + [guid]::NewGuid().ToString('N')
  $first=New-Object MarkAutoAcceptanceJob($name)
  try {
    Check ($first.get_ActiveProcesses() -eq 0) 'Valid empty job accounting did not return zero'
    $refused=$false
    try { $duplicate=New-Object MarkAutoAcceptanceJob($name); $duplicate.Dispose() } catch { $refused=$true }
    Check $refused 'Existing job name was accepted'
    $refused=$false
    try { $first.Start((Join-Path $fixture 'missing.exe'), '') } catch { $refused=$true }
    Check $refused 'Missing native executable was accepted'
  } finally { $first.Dispose() }
  # Diagnostic-only old syntax demonstrates the native CI failure without using
  # its null/error outcome as proof of safe accounting.
  $propertyValue=$null; $propertyError=$null
  try { $propertyValue=$first.ActiveProcesses } catch { $propertyError=$_.Exception.GetType().FullName }
  $refused=$false; $getterError=$null
  try { [void]$first.get_ActiveProcesses() }
  catch {
    $cause=$_.Exception.GetBaseException(); $getterError=$cause.GetType().FullName
    $refused=($cause -is [InvalidOperationException] -and $cause.Message -eq 'Owned job handle is unavailable')
  }
  Write-Host ((@{case='disposed-job-accounting'; property_returned_null=($null -eq $propertyValue);
    property_error_type=$propertyError; getter_error_type=$getterError; native_guard_refused=$refused}) | ConvertTo-Json -Compress)
  Check $refused 'Unavailable disposed-job accounting was not refused by the native guard'
  $refused=$false
  try { [void]$first.get_ExitCode() } catch { $refused=((Native-Code $_) -eq 6) }
  Check $refused 'Unavailable disposed-worker exit code was not refused'

  $exe = Join-Path $fixture 'MarkAuto.exe'
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public sealed class MarkAutoThrowingProcess {
    readonly bool failHasExited;
    public MarkAutoThrowingProcess(bool failHasExited) { this.failHasExited=failHasExited; }
    public void Refresh() { }
    public System.Diagnostics.Process DisposeTarget;
    public void Dispose() { DisposeTarget.Dispose(); throw new InvalidOperationException("fixture_dispose_failure"); }
    public bool HasExited { get {
        if(failHasExited) throw new InvalidOperationException("fixture_has_exited_getter");
        return false;
    } }
    public IntPtr MainWindowHandle { get { throw new InvalidOperationException("fixture_window_handle_getter"); } }
}
public static class MarkAutoFixture {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFileAttributes(string path);
    public static int AttributeError(string path) { return GetFileAttributes(path)==0xffffffff ? Marshal.GetLastWin32Error() : 0; }
    [STAThread]
    public static void Main(string[] args) {
        if(args.Length==3 && args[0]=="owned-dialog") {
            var main=new System.Windows.Forms.Form(); main.Text="MarkAuto owned root";
            main.Shown+=delegate {
                var dialog=new System.Windows.Forms.Form(); dialog.Text="MarkAuto owned close scope";
                dialog.Show(main);
                System.IO.File.WriteAllText(args[1]+".tmp",main.Handle.ToInt64()+":"+dialog.Handle.ToInt64());
                System.IO.File.Move(args[1]+".tmp",args[1]);
                var clock=System.Diagnostics.Stopwatch.StartNew();
                var timer=new System.Windows.Forms.Timer(); timer.Interval=25;
                timer.Tick+=delegate {
                    if(System.IO.File.Exists(args[2])) { timer.Stop(); dialog.Close(); main.Close(); }
                    else if(clock.ElapsedMilliseconds>5000) Environment.Exit(3);
                };
                timer.Start();
            };
            System.Windows.Forms.Application.Run(main); return;
        }
        if(args.Length==2 && args[0]=="write-marker") { System.IO.File.WriteAllText(args[1],"executed"); return; }
        if(args.Length==3 && args[0]=="outsider") {
            var wait=System.Diagnostics.Stopwatch.StartNew();
            int limit=int.Parse(args[2]);
            while(!System.IO.File.Exists(args[1])) {
                if(wait.ElapsedMilliseconds>=limit) Environment.Exit(3);
                System.Threading.Thread.Sleep(50);
            }
            return;
        }
        if(args.Length==4 && args[0]=="child") {
            System.IO.File.WriteAllText(args[2]+".ready","ready");
            var wait=System.Diagnostics.Stopwatch.StartNew();
            while(!System.IO.File.Exists(args[3])) {
                if(wait.ElapsedMilliseconds>=15000) Environment.Exit(3);
                System.Threading.Thread.Sleep(10);
            }
            System.IO.File.WriteAllText(args[2],"child completed"); return;
        }
        if(args.Length==4 && args[0]=="parent") {
            var start=new System.Diagnostics.ProcessStartInfo(System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName);
            start.UseShellExecute=false; start.Arguments="child "+args[1]+" \""+args[2]+"\" \""+args[3]+"\"";
            using(var child=System.Diagnostics.Process.Start(start)) { }
            return;
        }
        System.Threading.Thread.Sleep(60000);
    }
}
'@ -ReferencedAssemblies @('System.dll','System.Windows.Forms.dll','System.Drawing.dll') -OutputAssembly $exe -OutputType ConsoleApplication
  [void][Reflection.Assembly]::Load([IO.File]::ReadAllBytes($exe))
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName=$exe; $info.UseShellExecute=$false
  $info.Arguments='outsider "' + $outsiderStop + '" ' + ($suiteLimitSeconds * 1000)
  $outsider = [Diagnostics.Process]::Start($info)
  $outsiderHandle = $outsider.get_Handle()
  $outsiderCreated = [MarkAutoAcceptanceJob]::Created($outsiderHandle)
  $sentinel = Join-Path $fixture 'original-sentinel.txt'
  [IO.File]::WriteAllText($sentinel, 'original bytes')
  $refused = $false
  try { Assert-AcceptancePath $sentinel -RequireAbsent } catch { $refused = $true }
  Check $refused 'Preexisting file was not refused'
  Check ([IO.File]::ReadAllText($sentinel) -eq 'original bytes') 'Preexisting sentinel changed'
  $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($registration)
  try { $key.SetValue('original', 'preserve') } finally { $key.Dispose() }
  $refused = $false
  try { [void](Assert-AbsentAcceptanceRegistration $registration) } catch { $refused = $true }
  Check $refused 'Preexisting registration was not refused'
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registration)
  try { Check ($key.GetValue('original') -eq 'preserve') 'Preexisting registration changed' } finally { $key.Dispose() }
  $junction=Join-Path $fixture 'reparse'
  New-Item -ItemType Junction -Path $junction -Target $fixture | Out-Null
  try {
    $refused=$false
    try { Assert-AcceptancePath (Join-Path $junction 'not-created') } catch { $refused=$true }
    Check $refused 'Reparse ancestor was accepted'
  } finally { [IO.Directory]::Delete($junction) }
  # Metadata access can also be granted by listing the containing directory.
  # Keep both ACL surfaces inside a dedicated, exclusively owned fixture subtree.
  $aclParent=Join-Path $fixture 'acl-parent'
  New-Item $aclParent -ItemType Directory | Out-Null
  $denied=Join-Path $aclParent 'denied'
  New-Item $denied -ItemType Directory | Out-Null
  [IO.File]::WriteAllText((Join-Path $denied 'existing.txt'), 'unchanged')
  $target=Join-Path $denied 'existing.txt'
  Check ([MarkAutoAcceptanceJob]::PathAttributes($target) -ne [uint32]::MaxValue) 'Accessible fixture metadata was not readable before denial'
  Assert-AcceptancePath $target
  $absentControl=Join-Path $denied 'absent-control'
  Check ([MarkAutoAcceptanceJob]::PathAttributes($absentControl) -eq [uint32]::MaxValue) 'Ordinary absent fixture was not classified absent'
  Assert-AcceptancePath $absentControl -RequireAbsent
  Check (-not (Test-Path -LiteralPath $absentControl)) 'Metadata probe created absent fixture'
  $originalFileAcl=Get-Acl -LiteralPath $target
  $deniedFileAcl=Get-Acl -LiteralPath $target
  $originalParentAcl=Get-Acl -LiteralPath $aclParent
  $deniedParentAcl=Get-Acl -LiteralPath $aclParent
  $originalAcl=Get-Acl -LiteralPath $denied
  Check ([MarkAutoAcceptanceJob]::PathAttributes($denied) -ne [uint32]::MaxValue) 'Accessible ancestor metadata was not readable before denial'
  Assert-AcceptancePath (Join-Path $denied 'absent-child') -RequireAbsent
  try {
    $acl=Get-Acl -LiteralPath $denied
    $user=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($user, 'ReadData,ReadAttributes', 'ContainerInherit,ObjectInherit', 'None', 'Deny')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $denied -AclObject $acl
    $fileRule=New-Object Security.AccessControl.FileSystemAccessRule($user, 'ReadAttributes', 'Deny')
    $deniedFileAcl.AddAccessRule($fileRule)
    Set-Acl -LiteralPath $target -AclObject $deniedFileAcl
    $observation=[ordered]@{case='acl-denied-metadata'; get_item='not_run'; provider_category=$null;
      provider_error_id=$null; attribute_query_code=[MarkAutoFixture]::AttributeError($target); native_open_code=$null; inventory_code=$null}
    try { [void](Get-Item -LiteralPath $target -Force -ErrorAction Stop); $observation.get_item='returned_metadata' }
    catch {
      $observation.get_item='error'; $observation.provider_category=[string]$_.CategoryInfo.Category
      $observation.provider_error_id=$_.FullyQualifiedErrorId
    }
    try { [void][MarkAutoAcceptanceJob]::PathAttributes($target); $observation.native_open_code=0 }
    catch { $observation.native_open_code=Native-Code $_ }
    $refused=$false
    try { Assert-AcceptancePath $target }
    catch { $refused=$true; $observation.inventory_code=Native-Code $_ }
    # Only fixed field labels and error identifiers/codes, never ACLs, identities or path contents.
    Write-Host ($observation | ConvertTo-Json -Compress)
    Check ($observation.native_open_code -eq 5) 'ACL fixture did not deny the native metadata-read query with ERROR_ACCESS_DENIED'
    Check ($refused -and $observation.inventory_code -eq 5) 'Access-denied inventory was accepted as absence'
    $ancestorBeforeParentDeny=$null
    try { [void][MarkAutoAcceptanceJob]::PathAttributes($denied); $ancestorBeforeParentDeny=0 }
    catch { $ancestorBeforeParentDeny=Native-Code $_ }
    # A target deny is insufficient while its parent grants FILE_LIST_DIRECTORY.
    # This self-only deny changes no ancestor, sibling, or inherited child ACL.
    $parentRule=New-Object Security.AccessControl.FileSystemAccessRule($user, 'ListDirectory', 'None', 'None', 'Deny')
    $deniedParentAcl.AddAccessRule($parentRule)
    Set-Acl -LiteralPath $aclParent -AclObject $deniedParentAcl
    $appliedParentAcl=Get-Acl -LiteralPath $aclParent
    $appliedRules=@($appliedParentAcl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]) | Where-Object {
      $_.get_IdentityReference() -eq $user -and $_.get_AccessControlType() -eq [Security.AccessControl.AccessControlType]::Deny
    })
    $parentDenyVerified=@($appliedRules | Where-Object {
      ($_.get_FileSystemRights() -band [Security.AccessControl.FileSystemRights]::ListDirectory) -ne 0 -and
      $_.get_InheritanceFlags() -eq [Security.AccessControl.InheritanceFlags]::None -and
      $_.get_PropagationFlags() -eq [Security.AccessControl.PropagationFlags]::None
    }).Count -gt 0
    Check $parentDenyVerified 'Fixture parent-list denial was not present on ACL readback'
    $ancestorCode=$null; $childCode=$null
    try { [void][MarkAutoAcceptanceJob]::PathAttributes($denied); $ancestorCode=0 } catch { $ancestorCode=Native-Code $_ }
    try { Assert-AcceptancePath (Join-Path $denied 'absent-child'); $childCode=0 } catch { $childCode=Native-Code $_ }
    Write-Host ((@{case='denied-ancestor-absent-child'; native_before_parent_deny=$ancestorBeforeParentDeny;
      parent_list_deny_verified=$parentDenyVerified; parent_deny_inheritance='None'; parent_deny_propagation='None';
      native_ancestor_code=$ancestorCode; inventory_code=$childCode}) | ConvertTo-Json -Compress)
    Check ($ancestorCode -eq 5) 'ACL fixture did not deny ancestor metadata-read query'
    Check ($childCode -eq 5) 'Absent child bypassed denied ancestor metadata'
  } finally {
    # Restore the containing directory first so metadata access is available to cleanup.
    Set-Acl -LiteralPath $aclParent -AclObject $originalParentAcl
    Set-Acl -LiteralPath $denied -AclObject $originalAcl
    Set-Acl -LiteralPath $target -AclObject $originalFileAcl
  }
  Check ([MarkAutoAcceptanceJob]::PathAttributes($target) -ne [uint32]::MaxValue) 'Restored fixture metadata was not readable'
  Assert-AcceptancePath $target
  Check ([MarkAutoAcceptanceJob]::PathAttributes($denied) -ne [uint32]::MaxValue) 'Restored ancestor metadata was not readable'
  Assert-AcceptancePath (Join-Path $denied 'absent-child') -RequireAbsent
  Check (-not (Test-Path -LiteralPath (Join-Path $denied 'absent-child'))) 'Ancestor metadata probe created the absent child'
  Check ([IO.File]::ReadAllText($target) -eq 'unchanged') 'ACL probe changed original fixture bytes'
  $worker = Join-Path $fixture 'worker.ps1'
  @'
param([string]$AcceptanceJob, [string]$Helper, [string]$Fixture, [string]$Case)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. $Helper
Confirm-AcceptanceWorker $AcceptanceJob
$script:acceptanceProcesses=New-Object System.Collections.ArrayList
$script:acceptancePhase='case_start'
try {
  if ($Case -eq 'exit-two') { exit 2 }
  if ($Case -eq 'post-exit-diagnostic') {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$env:ComSpec; $start.Arguments='/c exit 7'; $start.UseShellExecute=$false
    $direct=[Diagnostics.Process]::Start($start)
    try {
      $handle=$direct.get_Handle()
      if (-not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$handle)) { throw 'Diagnostic creation escaped its private job' }
      if (-not $direct.WaitForExit(1000)) { throw 'Immediate diagnostic did not exit' }
      if ($direct.get_ExitCode() -ne 7) { throw 'Immediate diagnostic exit code changed' }
      foreach ($operation in @('creation_time','job_membership','image_query')) {
        $code=0; $errorType=$null
        try {
          if ($operation -eq 'creation_time') { [void][MarkAutoAcceptanceJob]::Created($handle) }
          elseif ($operation -eq 'job_membership') { if (-not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$handle)) { throw 'Diagnostic job membership was lost' } }
          else { [void][MarkAutoAcceptanceJob]::Image($handle) }
        } catch {
          $code=$null; $errorType=$_.Exception.GetType().FullName; $cause=$_.Exception
          while ($cause) { if ($cause -is [ComponentModel.Win32Exception]) { $code=$cause.NativeErrorCode }; $cause=$cause.InnerException }
        }
        [Console]::Out.WriteLine((@{case=$Case; phase=$operation; confirmed_exited=$true; native_code=$code; error_type=$errorType} | ConvertTo-Json -Compress))
      }
    } finally { $direct.Dispose() }
    exit 0
  }
  if ($Case -eq 'fast-nonzero') {
    $owned=Start-OwnedAcceptanceProcess $env:ComSpec -ArgumentList @('/c','exit','7')
    Wait-OwnedAcceptanceProcess $owned 1000 'Fast exit timed out'
    $script:acceptancePhase='fast_exit_code'
    if ($owned.Process.get_ExitCode() -ne 7) { throw 'Nonzero native exit code lost' }
    $nativeHandle=$owned.NativeHandle; $managedHandle=$owned.Process.get_SafeHandle()
    if ($nativeHandle.IsClosed -or $nativeHandle.IsInvalid -or $managedHandle.IsClosed) { throw 'Creation handles were not retained through the exit check' }
    Close-AcceptanceProcesses
    $script:acceptanceProcesses.Clear()
    if (-not $nativeHandle.IsClosed -or -not $managedHandle.IsClosed) { throw 'Creation or managed handle was not closed' }
    @{exit_code=7; native_handle_closed=$true; managed_handle_closed=$true} | ConvertTo-Json | Set-Content (Join-Path $Fixture 'fast-nonzero-proof.json')
    exit 0
  }
  if ($Case -eq 'owned-dialog') {
    $ready=Join-Path $Fixture 'owned-dialog-ready.txt'; $release=Join-Path $Fixture 'owned-dialog-release.txt'
    $owned=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe') -ArgumentList @('owned-dialog',"`"$ready`"","`"$release`"")
    $readyClock=[Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $ready) -and $readyClock.ElapsedMilliseconds -lt 2000) { Start-Sleep -Milliseconds 25 }
    if (-not (Test-Path -LiteralPath $ready)) { throw 'Owned dialog fixture not ready' }
    $handles=[IO.File]::ReadAllText($ready).Split(':')
    $main=[IntPtr][long]$handles[0]; $dialog=[IntPtr][long]$handles[1]
    $actual=[MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$owned.Handle,$main,'MarkAuto owned close scope')
    if ($actual -ne $dialog) { throw 'Exact owned dialog was not found' }
    if ([MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$owned.Handle,$main,'wrong scope') -ne [IntPtr]::Zero) { throw 'Unrelated dialog title was accepted' }
    if ([MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$owned.Handle,$dialog,'MarkAuto owned close scope') -ne [IntPtr]::Zero) { throw 'Dialog without the retained main owner was accepted' }
    $refused=$false
    try { [void][MarkAutoAcceptanceJob]::OwnedDialog('Local\UnownedAcceptanceFixture',$owned.Handle,$main,'MarkAuto owned close scope') } catch { $refused=$true }
    if (-not $refused) { throw 'Dialog outside creation ownership was accepted' }
    [IO.File]::WriteAllText($release,'release')
    Wait-OwnedAcceptanceProcess $owned 2000 'Owned dialog fixture did not finish'
    if ($owned.Process.get_ExitCode() -ne 0) { throw 'Owned dialog fixture failed' }
    @{exact_dialog=$true;wrong_title_refused=$true;wrong_owner_refused=$true;wrong_job_refused=$true} | ConvertTo-Json | Set-Content (Join-Path $Fixture 'owned-dialog-proof.json')
    exit 0
  }
  if ($Case -like 'descendant-*' -or $Case -like 'worker-exits-*') {
    $hang=$Case.EndsWith('-hang')
    $marker=Join-Path $Fixture ($Case+'-child.txt')
    $release=$marker+'.release'
    $owned=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe') -ArgumentList @('parent', 'barrier', "`"$marker`"", "`"$release`"")
    Wait-OwnedAcceptanceProcess $owned 1000 'Fixture parent did not exit'
    $readyClock=[Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath ($marker+'.ready')) -and $readyClock.ElapsedMilliseconds -lt 1000) { Start-Sleep -Milliseconds 10 }
    if (-not (Test-Path -LiteralPath ($marker+'.ready')) -or -not $owned.Process.get_HasExited() -or (Test-Path -LiteralPath $marker) -or
        [MarkAutoAcceptanceJob]::OwnedActiveProcesses($AcceptanceJob) -le 1) {
      throw 'Descendant fixture did not establish root-exited child-still-running precondition'
    }
    Write-Host ((@{case=$Case; root_exited=$true; child_ready=$true; completion_marker_absent=$true}) | ConvertTo-Json -Compress)
    # Release only after the required concurrent state was actually observed.
    # Hanging cases keep the barrier closed and must be cancelled by the owned job.
    if (-not $hang) { [IO.File]::WriteAllText($release, 'release') }
    if ($Case -like 'descendant-*') {
      $wait=if($hang){500}else{3000}
      $drainClock=[Diagnostics.Stopwatch]::StartNew()
      try { Wait-OwnedAcceptanceProcess $owned $wait 'Owned descendant wait timed out' -DrainJob }
      catch {
        if ($hang -and $_.Exception.Message -eq 'Owned descendant wait timed out' -and
            $drainClock.ElapsedMilliseconds -ge $wait -and $owned.Process.get_HasExited() -and
            [MarkAutoAcceptanceJob]::OwnedActiveProcesses($AcceptanceJob) -gt 1) {
          @{expected_failure='owned_descendant_timeout'; elapsed_ms=$drainClock.ElapsedMilliseconds;
            phase_budget_ms=$wait; root_exited=$true; child_still_pending=$true} |
            ConvertTo-Json | Set-Content ($marker+'.timeout-proof.json')
        }
        throw
      }
      if ($hang) { throw 'Hanging descendant returned without its required bounded timeout' }
      if (-not (Test-Path -LiteralPath $marker)) { throw 'Descendant completion was not awaited' }
    }
    exit 0
  }
  if ($Case -eq 'cleanup-error-closes-all') {
    [void][Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Fixture 'MarkAuto.exe')))
    $one=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe')
    $two=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe')
    $handles=@($one.NativeHandle,$one.Process.get_SafeHandle(),$two.NativeHandle,$two.Process.get_SafeHandle())
    $throwing=New-Object MarkAutoThrowingProcess($false)
    $throwing.DisposeTarget=$one.Process; $one.Process=$throwing
    $expectedFailure=$false
    try { Close-AcceptanceProcesses }
    catch { $cause=$_.Exception.GetBaseException(); $expectedFailure=($cause -is [InvalidOperationException] -and $cause.Message -eq 'fixture_dispose_failure') }
    finally { $script:acceptanceProcesses.Clear() }
    if (-not $expectedFailure) { throw 'Cleanup did not preserve the first injected disposal error' }
    foreach ($handle in $handles) { if (-not $handle.IsClosed) { throw 'Cleanup error left a retained creation-bound handle open' } }
    @{expected_failure='fixture_dispose_failure'; all_four_handles_closed=$true} | ConvertTo-Json | Set-Content (Join-Path $Fixture 'cleanup-error-proof.json')
    exit 0
  }
  if ($Case -eq 'verified-image-marker') {
    $marker=Join-Path $Fixture 'verified-image-executed.txt'
    $owned=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe') -ArgumentList @('write-marker',"`"$marker`"")
    Wait-OwnedAcceptanceProcess $owned 1000 'Verified marker process did not exit'
    if ($owned.Process.get_ExitCode() -ne 0 -or -not (Test-Path -LiteralPath $marker)) { throw 'Verified image did not execute its marker control' }
    exit 0
  }
  if ($Case -eq 'wrong-image') {
    $marker=Join-Path $Fixture 'rejected-image-executed.txt'
    try { [void](Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe') -ArgumentList @('write-marker',"`"$marker`"") -ExpectedImage $env:ComSpec) }
    catch {
      $cause=$_.Exception; $phase=$null
      while ($cause) { if ($cause.Data.Contains('acceptance_phase')) { $phase=$cause.Data['acceptance_phase'] }; $cause=$cause.InnerException }
      $rejectionClock=[Diagnostics.Stopwatch]::StartNew()
      while ([MarkAutoAcceptanceJob]::OwnedActiveProcesses($AcceptanceJob) -gt 1 -and $rejectionClock.ElapsedMilliseconds -lt 1000) { Start-Sleep -Milliseconds 10 }
      if ($phase -eq 'image_compare' -and [MarkAutoAcceptanceJob]::OwnedActiveProcesses($AcceptanceJob) -eq 1 -and -not (Test-Path -LiteralPath $marker)) {
        @{expected_failure='image_compare'; child_marker_absent=$true; owned_children_remaining=0} | ConvertTo-Json | Set-Content (Join-Path $Fixture 'wrong-image-proof.json')
      }
      throw
    }
    throw 'Wrong image was accepted'
  }
  $owned=Start-OwnedAcceptanceProcess (Join-Path $Fixture 'MarkAuto.exe')
  if ($Case -in @('window-exited-getter-failure','window-handle-getter-failure')) {
    [void][Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Fixture 'MarkAuto.exe')))
    $realProcess=$owned.Process
    $failExited=($Case -eq 'window-exited-getter-failure')
    $expectedFailure=if($failExited){'fixture_has_exited_getter'}else{'fixture_window_handle_getter'}
    try {
      # Membership still uses the genuine retained handle. Only the read-only GUI
      # observation object is substituted, then restored before owned cleanup.
      $owned.Process=New-Object MarkAutoThrowingProcess($failExited)
      try { Wait-OwnedAcceptanceWindow $owned -Seconds 1 }
      catch {
        $cause=$_.Exception.GetBaseException()
        if ($cause -is [InvalidOperationException] -and $cause.Message -eq $expectedFailure) {
          @{expected_failure=$expectedFailure; native_membership_retained=$true} | ConvertTo-Json |
            Set-Content (Join-Path $Fixture ($Case+'-proof.json'))
        }
        throw
      }
      throw 'GUI getter failure was accepted as window readiness'
    } finally { $owned.Process=$realProcess }
  }
  elseif ($Case -eq 'missing-window') { Wait-OwnedAcceptanceWindow $owned -Seconds 1 }
  elseif ($Case -eq 'install-hang' -or $Case -eq 'uninstall-hang') { Wait-OwnedAcceptanceProcess $owned 500 'Injected installer/uninstaller wait timed out' }
  elseif ($Case -eq 'unrelated') {
    $outside=[Diagnostics.Process]::GetProcessById([int](Get-Content (Join-Path $Fixture 'outsider-pid.txt')))
    try {
      if ([MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$outside.get_Handle())) { throw 'Unrelated process adopted by job' }
      $refused=$false
      try { [MarkAutoAcceptanceJob]::StopOwned($AcceptanceJob,$outside.get_Handle()) } catch { $refused=$true }
      if (-not $refused -or $outside.get_HasExited()) { throw 'Unrelated same-name process was stopped' }
    } finally { $outside.Dispose() }
  } else {
    $identityPath=Join-Path $Fixture 'owned-process.json'
    $identityTemp=$identityPath+'.tmp'
    @{id=$owned.Process.Id; created=$owned.Created} | ConvertTo-Json | Set-Content -LiteralPath $identityTemp
    [IO.File]::Move($identityTemp,$identityPath) # Publish only complete JSON, without replacing prior evidence.
    Start-Sleep -Seconds 60
  }
} catch {
  $errorType=$_.Exception.GetType().FullName; $nativeCode=$null; $exception=$_.Exception; $phase=$script:acceptancePhase
  $cleanupFailed=$false
  while ($exception) {
    if ($exception -is [ComponentModel.Win32Exception]) { $nativeCode=$exception.NativeErrorCode }
    if ($exception.Data.Contains('acceptance_phase')) { $phase=$exception.Data['acceptance_phase'] }
    if ($exception.Data.Contains('acceptance_cleanup_failed')) { $cleanupFailed=$true }
    $exception=$exception.InnerException
  }
  $failure=@{case=$Case; error_type=$errorType; native_code=$nativeCode; phase=$phase; launch_cleanup_failed=$cleanupFailed}
  $failure | ConvertTo-Json | Set-Content (Join-Path $Fixture ($Case+'-error.json'))
  [Console]::Out.WriteLine(($failure | ConvertTo-Json -Compress))
  throw
} finally { Close-AcceptanceProcesses }
'@ | Set-Content $worker
  Set-Content (Join-Path $fixture 'outsider-pid.txt') $outsider.Id
  $caseResults=New-Object System.Collections.ArrayList
  foreach ($case in @('post-exit-diagnostic','owned-dialog','install-hang','uninstall-hang','missing-window','window-exited-getter-failure','window-handle-getter-failure','verified-image-marker','wrong-image','cleanup-error-closes-all','unrelated','whole-run-hang','fast-nonzero','exit-two','descendant-completes','descendant-hang','worker-exits-completes','worker-exits-hang')) {
    Check ($suiteClock.Elapsed.TotalSeconds -lt $suiteLimitSeconds) 'Native fixture suite exceeded its existing outer deadline'
    $parameters = @{Helper=(Join-Path $PSScriptRoot 'acceptance_process.ps1'); Fixture=$fixture; Case=$case}
    $report = Join-Path $fixture ($case + '.json')
    $failure = Join-Path $fixture ($case + '-failure.json')
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $caseFailure=$null; $exitCode=$null
    try {
    $exitCode = Invoke-AcceptanceSupervisor $worker $parameters $report $clock -LimitSeconds 10 -FailureReportPath $failure
    $expected = if ($case -in @('post-exit-diagnostic','owned-dialog','verified-image-marker','cleanup-error-closes-all','unrelated','fast-nonzero','descendant-completes','worker-exits-completes')) { 0 } elseif ($case -eq 'exit-two') { 2 } else { 1 }
    Check ($exitCode -eq $expected) ('Unexpected exit: ' + $case)
    Check ($clock.Elapsed.TotalSeconds -lt 10) ('Unbounded wait: ' + $case)
    Check (Test-Path $report) ('Missing supervisor report: ' + $case)
    if ($expected -in @(0,2)) {
      Check ((Get-Content $report -Raw | ConvertFrom-Json).owned_processes_before_cleanup -eq 0) 'Success was reported before owned-job quiescence'
    }
    if ($expected -eq 1) { Check (Test-Path $failure) ('Missing failure report: ' + $case) }
    if ($case -eq 'cleanup-error-closes-all') {
      $proof=Get-Content -LiteralPath (Join-Path $fixture 'cleanup-error-proof.json') -Raw | ConvertFrom-Json
      Check ($proof.expected_failure -eq 'fixture_dispose_failure' -and $proof.all_four_handles_closed -eq $true) 'Failed cleanup did not close all original and managed handles'
    }
    if ($case -eq 'fast-nonzero') {
      $proof=Get-Content -LiteralPath (Join-Path $fixture 'fast-nonzero-proof.json') -Raw | ConvertFrom-Json
      Check ($proof.exit_code -eq 7 -and $proof.native_handle_closed -eq $true -and $proof.managed_handle_closed -eq $true) 'Fast exit did not retain and close both creation-bound handles'
    }
    if ($case -eq 'wrong-image') {
      $proof=Get-Content -LiteralPath (Join-Path $fixture 'wrong-image-proof.json') -Raw | ConvertFrom-Json
      Check ($proof.expected_failure -eq 'image_compare' -and $proof.child_marker_absent -eq $true -and $proof.owned_children_remaining -eq 0) 'Image rejection was not proved before execution'
      Check (-not (Test-Path -LiteralPath (Join-Path $fixture 'rejected-image-executed.txt'))) 'Rejected image executed before verification'
    }
    if ($case -in @('window-exited-getter-failure','window-handle-getter-failure')) {
      $proofPath=Join-Path $fixture ($case+'-proof.json')
      Check (Test-Path -LiteralPath $proofPath) 'GUI getter failure did not propagate from the window-ready gate'
      $proof=Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json
      $expectedFailure=if($case -eq 'window-exited-getter-failure'){'fixture_has_exited_getter'}else{'fixture_window_handle_getter'}
      Check ($proof.expected_failure -eq $expectedFailure -and $proof.native_membership_retained -eq $true) 'GUI getter failure proof was invalid'
    }
    if ($case -eq 'whole-run-hang') {
      Check ((Get-Content $report -Raw | ConvertFrom-Json).reason -eq 'whole_run_deadline') 'Whole deadline not enforced'
    }
    if ($case -eq 'descendant-hang') {
      $proofPath=Join-Path $fixture ($case+'-child.txt.timeout-proof.json')
      Check (Test-Path -LiteralPath $proofPath) 'Hanging descendant did not prove the specific bounded drain timeout'
      $proof=Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json
      Check ($proof.expected_failure -eq 'owned_descendant_timeout' -and $proof.root_exited -eq $true -and
        $proof.child_still_pending -eq $true -and $proof.elapsed_ms -ge $proof.phase_budget_ms) 'Invalid bounded drain timeout evidence'
    }
    if ($case -eq 'worker-exits-hang') {
      $drainReport=Get-Content $report -Raw | ConvertFrom-Json
      Check ($drainReport.reason -eq 'owned_descendants_deadline' -and $drainReport.worker_exit_code -eq 0) 'Successful worker exit hid a hanging descendant'
    }
    if ($case -in @('descendant-completes','worker-exits-completes')) {
      Check (Test-Path -LiteralPath (Join-Path $fixture ($case+'-child.txt'))) 'Supervisor killed an unfinished cleanup child'
    }
    } catch { $caseFailure=$_.Exception.GetType().FullName }
    # Aggregation is allowed only after native cleanup and outsider isolation are proved.
    # Missing reports, uncertain cleanup, changed identity or liveness stop immediately.
    $caseReport=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    Check ($caseReport.cleanup_verified -eq $true) ('Unverified private-job cleanup: ' + $case)
    $workerFailurePath=Join-Path $fixture ($case+'-error.json')
    $workerFailure=$null
    if (Test-Path -LiteralPath $workerFailurePath) {
      $workerFailure=Get-Content -LiteralPath $workerFailurePath -Raw | ConvertFrom-Json
      Check (-not $workerFailure.launch_cleanup_failed) ('Unverified launch cleanup: ' + $case)
    }
    $outsider.Refresh()
    Check (-not $outsider.get_HasExited()) ('Unrelated same-name process exited: ' + $case)
    Check ([MarkAutoAcceptanceJob]::Created($outsiderHandle) -eq $outsiderCreated) 'Unrelated creation identity changed'
    $caseResult=@{case=$case; passed=($null -eq $caseFailure); actual_exit=$exitCode; assertion_error_type=$caseFailure;
      phase=$(if($workerFailure){$workerFailure.phase}else{$null}); native_code=$(if($workerFailure){$workerFailure.native_code}else{$null})}
    [void]$caseResults.Add($caseResult)
    [Console]::Out.WriteLine(($caseResult | ConvertTo-Json -Compress))
  }
  Check ($suiteClock.Elapsed.TotalSeconds -lt $suiteLimitSeconds) 'Native fixture suite exceeded its existing outer deadline'
  # Forced supervisor termination must also close the private job without a finally block.
  $supervisor = Join-Path $fixture 'supervisor.ps1'
  @'
param([string]$Helper,[string]$Worker,[string]$Fixture)
$ErrorActionPreference='Stop'
. $Helper
$p=@{Helper=$Helper;Fixture=$Fixture;Case='cancel'}
[void](Invoke-AcceptanceSupervisor $Worker $p (Join-Path $Fixture 'cancel-report.json') ([Diagnostics.Stopwatch]::StartNew()) -LimitSeconds 30)
'@ | Set-Content $supervisor
  [IO.File]::Delete((Join-Path $fixture 'owned-process.json'))
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName=[Diagnostics.Process]::GetCurrentProcess().get_MainModule().get_FileName()
  $start.UseShellExecute=$false
  $start.Arguments='-NoProfile -File "' + $supervisor + '" -Helper "' + (Join-Path $PSScriptRoot 'acceptance_process.ps1') + '" -Worker "' + $worker + '" -Fixture "' + $fixture + '"'
  $outer = [Diagnostics.Process]::Start($start)
  [void]$outer.get_Handle()
  $observed = $null
  try {
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path (Join-Path $fixture 'owned-process.json')) -and $clock.Elapsed.TotalSeconds -lt 15) { Start-Sleep -Milliseconds 100 }
    $identity=Get-Content (Join-Path $fixture 'owned-process.json') -Raw | ConvertFrom-Json
    # PID is used only to observe an identified fixture, never for termination.
    $observed=[Diagnostics.Process]::GetProcessById($identity.id)
    Check ([MarkAutoAcceptanceJob]::Created($observed.get_Handle()) -eq $identity.created) 'Fixture identity mismatch'
    $outer.Kill() # Exact creation-returned supervisor handle retained above.
    Check ($outer.WaitForExit(2000)) 'Supervisor did not exit'
    Check ($observed.WaitForExit(2000)) 'Owned child survived abrupt supervisor cancellation'
    $outsider.Refresh()
    Check (-not $outsider.get_HasExited()) 'Cancellation stopped unrelated same-name process'
  } finally {
    if (-not $outer.get_HasExited()) { $outer.Kill(); [void]$outer.WaitForExit(2000) }
    $outer.Dispose()
    if ($observed) { $observed.Dispose() }
  }
  Check ($suiteClock.Elapsed.TotalSeconds -lt $suiteLimitSeconds) 'Native fixture suite exceeded its existing outer deadline'
  $caseResults | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $fixture 'case-results.json')
  $failedCases=@($caseResults | Where-Object { -not $_.passed })
  Check ($failedCases.Count -eq 0) ('Native ownership cases failed: ' + $failedCases.Count)
  Write-Host 'Native acceptance ownership regressions passed; this is not client lifecycle acceptance'
} finally {
  if ($outsider) {
    $cleanupClock=[Diagnostics.Stopwatch]::StartNew()
    try { [IO.File]::WriteAllText($outsiderStop,'complete') }
    finally {
      try {
        # Signal completion first; retain the original total 2000 ms cleanup allowance.
        if (-not $outsider.WaitForExit([int][Math]::Max(0,1000-$cleanupClock.ElapsedMilliseconds))) {
          try { $outsider.Kill() }
          catch { if (-not $outsider.WaitForExit(0)) { throw } } # Only ignore a proven concurrent exit.
          Check ($outsider.WaitForExit([int][Math]::Max(0,2000-$cleanupClock.ElapsedMilliseconds))) 'Owned outsider fixture did not exit within cleanup allowance'
        }
      } finally { $outsider.Dispose() }
    }
  }
  [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($registration, $false)
  Remove-Item -LiteralPath $fixture -Recurse -Force
}
