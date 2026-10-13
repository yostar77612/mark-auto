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

function Reject-PreparedHashIO([scriptblock]$Action, [int]$ExpectedCode, [string]$Message) {
  $rejected=$false
  try { & $Action } catch {
    # CLR method invocation wraps the concrete filesystem exception.
    $exception=$_.Exception.GetBaseException()
    $native=$null; $allowed=$false
    if ($exception -is [ComponentModel.Win32Exception]) {
      $native=$exception.NativeErrorCode; $allowed=$true
    } elseif (($exception.HResult -band 0xffff0000) -eq 0x80070000) {
      $native=$exception.HResult -band 0xffff
      $allowed=($ExpectedCode -eq 2 -and $exception -is [IO.FileNotFoundException]) -or
               ($ExpectedCode -eq 32 -and $exception -is [IO.IOException])
    }
    if (-not $allowed -or $native -ne $ExpectedCode) { throw }
    $rejected=$true
  }
  Require $rejected $Message
}

function Test-PreparedKitIntegrityGuard([string]$Root, [string]$SourcePath) {
  $sourceTokens=$null; $sourceErrors=$null
  $sourceAst=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$sourceTokens,[ref]$sourceErrors)
  Require ($sourceErrors.Count -eq 0) 'Real kit-integrity source parse failed'
  $loops=@($sourceAst.FindAll({param($node)
    $node -is [Management.Automation.Language.ForEachStatementAst] -and
    $node.Condition.Extent.Text -ceq '$kit.files_sha256.PSObject.Properties'
  },$true))
  Require ($loops.Count -eq 1) 'Real kit-integrity loop not unique'
  $code=[scriptblock]::Create($loops[0].Extent.Text)
  $file=Join-Path $Root 'native-hash-control.bin'
  [IO.File]::WriteAllBytes($file,[byte[]](0,1,2,3,254,255))
  $before=[IO.File]::ReadAllBytes($file)
  # This child scope cannot leak the poison command into the remaining fixture.
  & {
    param($KitRoot,$Code,$File,$OriginalBytes)
    function Get-FileHash { throw 'Module-dependent hash command was invoked' }
    $expected='7ea646958715ed687aa9ac2f5d785feb1a93411f4f25fdd6c7fcc6ab07fdf0e3'
    $kit=@{files_sha256=[pscustomobject]@{'native-hash-control.bin'=$expected}}
    & $Code
    Require ((Get-PreparedFileSha256 $File) -ceq $expected) 'Known SHA256 control mismatch'
    # Every digest decision uses real SHA256 over real file bytes.
    [IO.File]::WriteAllBytes($File,[byte[]](9,8,7))
    Reject { & $Code } 'Changed kit bytes were admitted' 'Kit file digest changed'
    [IO.File]::WriteAllBytes($File,$OriginalBytes)
    $kit.files_sha256.'native-hash-control.bin'='INVALID'
    Reject { & $Code } 'Malformed kit digest was admitted' 'Kit file digest changed'
    $kit.files_sha256=[pscustomobject]@{'../outside.bin'=$expected}
    Reject { & $Code } 'Escaped kit path was admitted' 'Kit entry escapes its root'
    $kit.files_sha256=[pscustomobject]@{'missing.bin'=$expected}
    Reject-PreparedHashIO { Get-PreparedFileSha256 (Join-Path $KitRoot 'missing.bin') } 2 'Missing helper input did not fail with native error 2'
    Reject-PreparedHashIO { & $Code } 2 'Missing kit member did not fail with native error 2'
    $kit.files_sha256=[pscustomobject]@{'native-hash-control.bin'=$expected}
    $exclusive=[IO.File]::Open($File,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
    try {
      Reject-PreparedHashIO { Get-PreparedFileSha256 $File } 32 'Read-denied helper input did not fail with native error 32'
      Reject-PreparedHashIO { & $Code } 32 'Read-denied kit member did not fail with native error 32'
    } finally { $exclusive.Dispose() }
    & $Code
    # Successful return releases the actual file lease.
    $writer=[IO.File]::Open($File,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $writer.Dispose()
    # Fault injection changes ONLY the factory in the real production helper
    # body. Its real stream open, ComputeHash call and both finally blocks run.
    $body=(Get-Command Get-PreparedFileSha256 -CommandType Function).ScriptBlock.ToString()
    $factory='[Security.Cryptography.SHA256]::Create()'
    Require ([regex]::Matches($body,[regex]::Escape($factory)).Count -eq 1) 'Hash factory seam not unique'
    $algorithm=New-Object PSObject -Property @{ComputeCalls=0;DisposeCalls=0;OpenStreamSeen=$false;CapturedStream=$null}
    $algorithm | Add-Member -MemberType ScriptMethod -Name ComputeHash -Value {
      param($inputStream)
      $this.ComputeCalls++; $this.OpenStreamSeen=$inputStream.get_CanRead(); $this.CapturedStream=$inputStream
      throw [InvalidOperationException]::new('Injected post-open hash failure')
    }
    $algorithm | Add-Member -MemberType ScriptMethod -Name Dispose -Value { $this.DisposeCalls++ }
    $injected=[scriptblock]::Create($body.Replace($factory,'$algorithm'))
    $failed=$false
    try { & $injected $File } catch {
      $exception=$_.Exception.GetBaseException()
      Require ($exception -is [InvalidOperationException] -and $exception.Message -ceq 'Injected post-open hash failure') 'Unexpected hashing fault accepted'
      $failed=$true
    }
    Require ($failed -and $algorithm.ComputeCalls -eq 1 -and $algorithm.OpenStreamSeen) 'Hash fault did not occur after actual stream open'
    Require ($algorithm.DisposeCalls -eq 1) 'Algorithm disposal missing after hashing fault'
    Require (-not $algorithm.CapturedStream.get_CanRead()) 'Real stream remained open after hashing fault'
    $writer=[IO.File]::Open($File,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $writer.Dispose()
    & $Code
  } $Root $code $file $before
  Require ([Convert]::ToBase64String([IO.File]::ReadAllBytes($file)) -ceq [Convert]::ToBase64String($before)) 'Guard controls changed original fixture bytes'
}

function Get-PreparedNativeCode($Failure) {
  $exception=$Failure.Exception
  while ($exception) {
    if ($exception -is [ComponentModel.Win32Exception]) { return $exception.NativeErrorCode }
    $exception=$exception.InnerException
  }
  return $null
}
function Confirm-PreparedSelfOnlyListDeny([string]$Parent, $Sid) {
  $acl=Get-Acl -LiteralPath $Parent
  $rules=@($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]) | Where-Object {
    $_.get_IdentityReference() -eq $Sid -and
    $_.get_AccessControlType() -eq [Security.AccessControl.AccessControlType]::Deny -and
    ($_.get_FileSystemRights() -band [Security.AccessControl.FileSystemRights]::ListDirectory) -ne 0 -and
    $_.get_InheritanceFlags() -eq [Security.AccessControl.InheritanceFlags]::None -and
    $_.get_PropagationFlags() -eq [Security.AccessControl.PropagationFlags]::None
  })
  Require ($rules.Count -gt 0) 'Fixture self-only parent listing denial missing on readback'
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
    ui_navigation_found=$script:preparedUiFound;ui_selections=$script:preparedUiSelected;
    scaffold_phase=$script:preparedScaffoldPhase;scaffold_raw_root_length=$script:preparedScaffoldRawLength;
    scaffold_canonical_root_length=$script:preparedScaffoldCanonicalLength;
    scaffold_root_length_changed=($script:preparedScaffoldRawLength -ne $script:preparedScaffoldCanonicalLength);
    scaffold_relative_depth=$script:preparedScaffoldRelativeDepth;scaffold_prefix_match=$script:preparedScaffoldPrefixMatch;
    stack=@($frames)}
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
$script:preparedScaffoldPhase='not_entered'; $script:preparedScaffoldRawLength=0; $script:preparedScaffoldCanonicalLength=0; $script:preparedScaffoldRelativeDepth=0; $script:preparedScaffoldPrefixMatch=$false
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

  # Fixture-only raw Win32 setup avoids .NET Framework colon-path validation.
  Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
public static class MarkAutoPreparedStreamFixture {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct StreamInfo {
        public long size;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=296)] public string name;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern IntPtr CreateFileW(string path,uint access,uint sharing,IntPtr security,uint disposition,uint flags,IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool WriteFile(IntPtr file,byte[] bytes,uint count,out uint written,IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool FlushFileBuffers(IntPtr file);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern bool DeleteFileW(string path);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern IntPtr FindFirstStreamW(string path,int level,out StreamInfo stream,uint flags);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern bool FindNextStreamW(IntPtr search,out StreamInfo stream);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool FindClose(IntPtr search);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr file);
    static string Target(string root,string path,string name) {
        root=Path.GetFullPath(root).TrimEnd((char)92)+(char)92;
        path=Path.GetFullPath(path);
        if(!path.StartsWith(root,StringComparison.OrdinalIgnoreCase) || path.Substring(2).Contains(":") ||
           !Regex.IsMatch(name,"^synthetic-[a-z-]+$"))
            throw new InvalidOperationException("Stream fixture path escaped private root");
        return path+":"+name;
    }

    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern uint GetShortPathNameW(string path,System.Text.StringBuilder buffer,uint length);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern uint GetLongPathNameW(string path,System.Text.StringBuilder buffer,uint length);
    public static string ShortPath(string root,string path) {
        Target(root,path,"synthetic-path-alias");
        var buffer=new System.Text.StringBuilder(32768);
        uint count=GetShortPathNameW(path,buffer,(uint)buffer.Capacity);
        if(count==0) throw new Win32Exception(Marshal.GetLastWin32Error());
        if(count>=buffer.Capacity) throw new InvalidOperationException("Fixture short path exceeds bound");
        return buffer.ToString();
    }
    public static string LongPath(string path) {
        var buffer=new System.Text.StringBuilder(32768);
        uint count=GetLongPathNameW(path,buffer,(uint)buffer.Capacity);
        if(count==0) throw new Win32Exception(Marshal.GetLastWin32Error());
        if(count>=buffer.Capacity) throw new InvalidOperationException("Fixture long path exceeds bound");
        return buffer.ToString();
    }

    public static bool Exists(string root,string path,string name) {
        Target(root,path,name);
        StreamInfo stream; IntPtr search=FindFirstStreamW(path,0,out stream,0);
        if(search==new IntPtr(-1)) {
            int error=Marshal.GetLastWin32Error();
            if(error==38) return false;
            throw new Win32Exception(error);
        }
        try {
            for(int count=0;count<8;count++) {
                if(String.Equals(stream.name,":"+name+":$DATA",StringComparison.Ordinal)) return true;
                if(!FindNextStreamW(search,out stream)) {
                    int error=Marshal.GetLastWin32Error();
                    if(error==38) return false;
                    throw new Win32Exception(error);
                }
            }
            throw new InvalidOperationException("Fixture stream enumeration exceeds bound");
        } finally { FindClose(search); }
    }
    public static void Create(string root,string path,string name) {
        string target=Target(root,path,name);
        IntPtr file=CreateFileW(target,0x40000000,0,IntPtr.Zero,1,0x02000080,IntPtr.Zero);
        if(file==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            byte[] bytes=new byte[]{102,105,120,116,117,114,101}; uint written;
            if(!WriteFile(file,bytes,(uint)bytes.Length,out written,IntPtr.Zero) || written!=bytes.Length)
                throw new Win32Exception(Marshal.GetLastWin32Error());
            if(!FlushFileBuffers(file)) throw new Win32Exception(Marshal.GetLastWin32Error());
        } finally { CloseHandle(file); }
    }
    public static void Delete(string root,string path,string name) {
        if(!DeleteFileW(Target(root,path,name))) throw new Win32Exception(Marshal.GetLastWin32Error());
    }
}
'@
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

  # Explicit new-baseline contract controls. All paths belong to this CI scratch tree.
  $controllerStage='kit_integrity_guard_controls'
  $hashRoot=Join-Path $fixture 'kit-integrity-guard'; [void][IO.Directory]::CreateDirectory($hashRoot)
  Test-PreparedKitIntegrityGuard $hashRoot (Join-Path $PSScriptRoot 'prepared_host_session.ps1')
  [Console]::Out.WriteLine('{"stage":"kit_integrity_guard_controls","status":"passed","scope":"real-production-loop-no-install"}')

  $controllerStage='current_baseline_controls'
  $current=Join-Path $fixture 'current-state'; [void][IO.Directory]::CreateDirectory($current)
  foreach ($name in @('cache','control-v1','credentials','logs','state-v1','state-v1/market_cache')) { [void][IO.Directory]::CreateDirectory((Join-Path $current $name)) }
  foreach ($name in @('.analysis-recovery-admission.lock','installer-preservation-test.txt','state-v1/desktop_safety.json','state-v1/settings.json','workspace-format.json')) { [IO.File]::WriteAllText((Join-Path $current $name),'synthetic-baseline-only') }
  $scaffold=Join-Path $fixture 'install-scaffold'
  foreach ($name in @('payloads/0.2.1/is-ABCDE','payloads/0.2.2/is-FGHIJ')) { [void][IO.Directory]::CreateDirectory((Join-Path $scaffold $name)) }
  $directoryMap=@('payloads','payloads/0.2.1','payloads/0.2.1/is-ABCDE','payloads/0.2.2','payloads/0.2.2/is-FGHIJ')
  $metadata=@{}
  foreach ($name in (@('.')+$directoryMap)) {
    $path=if($name -ceq '.'){$scaffold}else{Join-Path $scaffold $name}
    $info=New-Object IO.DirectoryInfo($path)
    $metadata[$name]=@{created_at_utc=$info.get_CreationTimeUtc().ToString('o');modified_at_utc=$info.get_LastWriteTimeUtc().ToString('o')}
  }
  $kitContext=@{version='0.2.2';baseline_version='0.2.1';candidate_commit=('a'*40);files_sha256=@{'packaging/acceptance_process.dll'=('b'*64);'packaging/acceptance_process.ps1'=('c'*64)}}
  $priorKitContext=@{schema_version=1;version='0.2.2';baseline_version='0.2.1';candidate_commit=('7'*40)}
  $invocationContext=@{StartedAtUtc=[DateTime]::UtcNow.AddMinutes(-1).ToString('o');FinishedAtUtc=[DateTime]::UtcNow.ToString('o');ExecutionSha=('7'*40);ActualCallerExitCode=2;TimedOut=$false;
    NativeReports=@(@{Name='installer-results.json';Sha256=('d'*64)},@{Name='installer-supervisor.json';Sha256=('d'*64)},@{Name='installer-scope-preflight.json';Sha256=('d'*64)})}
  # Canonical declared identities are separate from raw launch/alias controls.
  $canonicalFixture=[IO.Path]::GetFullPath($fixture).TrimEnd('\')
  $canonicalSource=[IO.Path]::GetFullPath($source).TrimEnd('\')
  $canonicalCurrent=[IO.Path]::GetFullPath($current).TrimEnd('\')
  $canonicalScaffold=[IO.Path]::GetFullPath($scaffold).TrimEnd('\')
  $currentInventory=Get-PreparedStateInventory $current -RequireUnaliased
  $reviewed=@{schema_version=2;owner='prepared-host-current-baseline';original_lifecycle_continuity='UNPROVEN';captured_at_utc=[DateTime]::UtcNow.ToString('o');
    kit_root=$canonicalSource;kit_sha256=('e'*64);candidate_commit=('a'*40);candidate_version='0.2.2';baseline_version='0.2.1';installer_sha256=('f'*64);
    helper_sha256=('b'*64);helper_script_sha256=('c'*64);entrypoint_sha256=('1'*64);app_data_path=$canonicalCurrent;install_path=$canonicalScaffold;
    directories=$currentInventory.directories;files_sha256=$currentInventory.files_sha256;install_directories=$directoryMap;install_metadata=$metadata;
    prior_reports_sha256=@{'installer-results.json'=('d'*64);'installer-supervisor.json'=('d'*64);'installer-scope-preflight.json'=('d'*64);'smoke-installed.json'=('d'*64);'smoke-upgraded.json'=('d'*64)};
    lifecycle_invocation_path=(Join-Path $canonicalFixture 'invocation.json');lifecycle_invocation_sha256=('2'*64);
    prior_kit_root=$canonicalSource;prior_kit_sha256=('3'*64);prior_candidate_commit=('7'*40);prior_candidate_version='0.2.2';prior_baseline_version='0.2.1'}
  $reviewed=$reviewed | ConvertTo-Json -Depth 8 | ConvertFrom-Json
  function Confirm-CurrentFixture($r) { Confirm-PreparedCurrentBaseline $r $kitContext ('e'*64) ('f'*64) ('1'*64) $canonicalSource $canonicalCurrent $canonicalScaffold $invocationContext $priorKitContext }
  function Clone-CurrentFixture { return ($reviewed | ConvertTo-Json -Depth 8 | ConvertFrom-Json) }
  Confirm-CurrentFixture $reviewed
  $sourceOperationalAlias=(Split-Path $canonicalSource -Parent)+'\.\'+(Split-Path $canonicalSource -Leaf)
  $currentOperationalAlias=(Split-Path $canonicalCurrent -Parent)+'\.\'+(Split-Path $canonicalCurrent -Leaf)
  $scaffoldOperationalAlias=(Split-Path $canonicalScaffold -Parent)+'\.\'+(Split-Path $canonicalScaffold -Leaf)
  Confirm-PreparedCurrentBaseline $reviewed $kitContext ('e'*64) ('f'*64) ('1'*64) $sourceOperationalAlias $currentOperationalAlias $scaffoldOperationalAlias $invocationContext $priorKitContext
  # Each declared receipt path is canonical; a same-target alias is refused.
  foreach ($field in @('kit_root','app_data_path','install_path')) {
    $bad=Clone-CurrentFixture
    $declared=[string]$bad.PSObject.Properties[$field].Value
    $bad.PSObject.Properties[$field].Value=(Split-Path $declared -Parent)+'\.\'+(Split-Path $declared -Leaf)
    Reject { Confirm-CurrentFixture $bad } ('Noncanonical declared receipt identity admitted: '+$field) 'Current baseline provenance refused'
  }
  Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext


  $controllerStage='scaffold_dot_component_controls'
  $canonicalScaffold=[IO.Path]::GetFullPath($scaffold).TrimEnd('\')
  $dotScaffold=(Split-Path $canonicalScaffold -Parent)+'\.\'+(Split-Path $canonicalScaffold -Leaf)
  $dotCanonical=[IO.Path]::GetFullPath($dotScaffold).TrimEnd('\')
  Require ($dotCanonical -ceq $canonicalScaffold) 'Dot-component root did not identify the exact scaffold'
  Require ($dotScaffold.Length -ne $dotCanonical.Length) 'Dot-component root did not change canonical prefix length'
  Require ($dotScaffold.Length -eq ($dotCanonical.Length+2)) 'Dot-component offset precondition was not deterministic'
  Assert-PreparedInstallScaffolding $dotScaffold $reviewed $priorKitContext $invocationContext
  $dotUnknown=Join-Path $canonicalScaffold 'unreviewed-dot-child'
  [void][IO.Directory]::CreateDirectory($dotUnknown)
  [IO.Directory]::SetLastWriteTimeUtc($canonicalScaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  try {
    Reject { Assert-PreparedInstallScaffolding $dotScaffold $reviewed $priorKitContext $invocationContext } 'Dot-component root accepted unknown scaffold child' 'Unknown installer scaffolding directory'
  } finally {
    [IO.Directory]::Delete($dotUnknown)
    [IO.Directory]::SetLastWriteTimeUtc($canonicalScaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  }
  Assert-PreparedInstallScaffolding $dotScaffold $reviewed $priorKitContext $invocationContext
  [Console]::Out.WriteLine((@{stage='scaffold_dot_component_controls';status='passed';
    root_length_changed=$true;prefix_length_delta=2;canonical_target_matches=$true;
    positive_before_after=$true;unknown_child_refused=$true} | ConvertTo-Json -Compress))

  $controllerStage='scaffold_alias_controls'
  $longScaffold=[MarkAutoPreparedStreamFixture]::LongPath($scaffold)
  $shortScaffold=[MarkAutoPreparedStreamFixture]::ShortPath($fixture,$scaffold)
  $distinctAlias=-not [string]::Equals($shortScaffold,$longScaffold,[StringComparison]::OrdinalIgnoreCase)
  if (-not $distinctAlias) {
    [Console]::Out.WriteLine((@{stage='scaffold_alias_controls';status='BLOCKED';reason='no_distinct_native_short_alias';
      short_length=$shortScaffold.Length;long_length=$longScaffold.Length} | ConvertTo-Json -Compress))
    throw 'Native scaffold alias control unavailable; no short/long proof'
  }
  foreach ($aliasRoot in @($longScaffold,$shortScaffold)) {
    Assert-PreparedInstallScaffolding $aliasRoot $reviewed $priorKitContext $invocationContext
  }
  $aliasUnknown=Join-Path $longScaffold 'unreviewed-alias-child'
  [void][IO.Directory]::CreateDirectory($aliasUnknown)
  [IO.Directory]::SetLastWriteTimeUtc($longScaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  try {
    foreach ($aliasRoot in @($longScaffold,$shortScaffold)) {
      Reject { Assert-PreparedInstallScaffolding $aliasRoot $reviewed $priorKitContext $invocationContext } 'Native short alias accepted unknown scaffold child' 'Unknown installer scaffolding directory'
    }
  } finally {
    [IO.Directory]::Delete($aliasUnknown)
    [IO.Directory]::SetLastWriteTimeUtc($longScaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  }
  foreach ($aliasRoot in @($longScaffold,$shortScaffold)) {
    Assert-PreparedInstallScaffolding $aliasRoot $reviewed $priorKitContext $invocationContext
  }
  [Console]::Out.WriteLine((@{stage='scaffold_alias_controls';status='passed';short_long_distinct=$true;
    raw_short_root_length=$shortScaffold.Length;canonical_short_root_length=([IO.Path]::GetFullPath($shortScaffold).TrimEnd('\')).Length;
    root_length_changed=($shortScaffold.Length -ne ([IO.Path]::GetFullPath($shortScaffold).TrimEnd('\')).Length);
    expected_directories=5;unknown_child_refused=$true} | ConvertTo-Json -Compress))
  $controllerStage='current_baseline_controls'

  Backup-PreparedState $current (Join-Path $fixture 'current-backup') $reviewed -RequireUnaliased
  Require ([IO.Directory]::Exists($scaffold)) 'Current admission deleted installer scaffolding'
  $bad=Clone-CurrentFixture; $bad.owner='prepared-host-lifecycle-handoff'
  Reject { Confirm-CurrentFixture $bad } 'Current receipt relabelled as lifecycle handoff' 'Current baseline provenance refused'
  $bad=Clone-CurrentFixture; $bad.original_lifecycle_continuity='PROVEN'
  Reject { Confirm-CurrentFixture $bad } 'Historical continuity was manufactured' 'Current baseline provenance refused'
  $bad=Clone-CurrentFixture; $bad | Add-Member no_intervening_app_use $true
  Reject { Confirm-CurrentFixture $bad } 'Current schema accepted legacy continuity assertion' 'Current baseline receipt schema refused'
  foreach ($field in @('kit_root','app_data_path','install_path','kit_sha256','candidate_commit','candidate_version','baseline_version','installer_sha256','helper_sha256','helper_script_sha256','entrypoint_sha256','prior_candidate_commit','prior_candidate_version','prior_baseline_version')) {
    $bad=Clone-CurrentFixture; $bad.PSObject.Properties[$field].Value='wrong'
    Reject { Confirm-CurrentFixture $bad } ('Wrong current provenance accepted: '+$field) 'Current baseline provenance refused'
  }
  $bad=Clone-CurrentFixture; $bad.captured_at_utc=[DateTime]::UtcNow.AddMinutes(-31).ToString('o')
  Reject { Confirm-CurrentFixture $bad } 'Stale current baseline accepted' 'Current baseline freshness refused'
  $bad=Clone-CurrentFixture; $bad.captured_at_utc=[DateTime]::UtcNow.AddMinutes(1).ToString('o')
  Reject { Confirm-CurrentFixture $bad } 'Future current baseline accepted' 'Current baseline freshness refused'
  $bad=Clone-CurrentFixture; $bad.files_sha256 | Add-Member '../escape' ('a'*64)
  Reject { Confirm-CurrentFixture $bad } 'Unsafe current receipt map accepted' 'Current baseline receipt schema refused'
  $bad=Clone-CurrentFixture; $bad.prior_reports_sha256.'installer-supervisor.json'=('9'*64)
  Reject { Confirm-CurrentFixture $bad } 'Wrong prior invocation context accepted' 'Current baseline invocation context refused'
  [IO.File]::WriteAllText((Join-Path $current 'unknown.txt'),'not-approved')
  Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Current unknown file read' 'Current baseline unknown file refused'
  [IO.File]::Delete((Join-Path $current 'unknown.txt'))
  [void][IO.Directory]::CreateDirectory((Join-Path $current 'unknown'))
  Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Current unknown directory admitted' 'Current baseline unknown directory refused'
  [IO.Directory]::Delete((Join-Path $current 'unknown'))
  [IO.File]::WriteAllText((Join-Path $current 'credentials/synthetic.bin'),'not-a-secret')
  Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Current credential presence admitted' 'Credential-bearing state is outside this test phase'
  [IO.File]::Delete((Join-Path $current 'credentials/synthetic.bin'))
  $currentSentinel=Join-Path $current 'installer-preservation-test.txt'
  [IO.File]::WriteAllText($currentSentinel,'changed')
  Reject { Backup-PreparedState $current (Join-Path $fixture 'current-changed-backup') $reviewed -RequireUnaliased } 'Current changed content accepted' 'Prepared data digest changed; originals preserved'
  [IO.File]::WriteAllText($currentSentinel,'synthetic-baseline-only')
  $hardlink=Join-Path $fixture 'sentinel-alias.txt'
  New-Item -ItemType HardLink -Path $hardlink -Target $currentSentinel | Out-Null
  try { Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Hard-linked current file admitted' 'Current baseline file alias or stream refused' }
  finally { [IO.File]::Delete($hardlink) }
  [MarkAutoPreparedStreamFixture]::Create($fixture,$currentSentinel,'synthetic-stream')
  Require ([MarkAutoPreparedStreamFixture]::Exists($fixture,$currentSentinel,'synthetic-stream')) 'Regular ADS setup was not verified'
  try { Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Alternate current stream admitted' 'Current baseline file alias or stream refused' }
  finally { [MarkAutoPreparedStreamFixture]::Delete($fixture,$currentSentinel,'synthetic-stream') }
  Require (-not [MarkAutoPreparedStreamFixture]::Exists($fixture,$currentSentinel,'synthetic-stream')) 'Regular ADS cleanup was not verified'
  Require ((Get-FileHash -LiteralPath $currentSentinel -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $reviewed.files_sha256.'installer-preservation-test.txt') 'Regular ADS control changed baseline bytes'
  $redirect=Join-Path $fixture 'current-redirect'; New-Item -ItemType Junction -Path $redirect -Target $current | Out-Null
  try { Reject { Get-PreparedStateInventory $redirect -RequireUnaliased } 'Current redirect followed' 'Bootstrap redirect refused before content reads' }
  finally { [IO.Directory]::Delete($redirect) }

  # Match the proven native ACL convention: parent listing can grant metadata
  # despite a target ReadAttributes deny. No personal or global ACL is touched.
  $aclParent=Join-Path $fixture 'current-acl-parent'
  [void][IO.Directory]::CreateDirectory($aclParent)
  $aclRoot=Join-Path $aclParent 'denied'
  Backup-PreparedState $current $aclRoot $reviewed -RequireUnaliased
  $denied=Join-Path $aclRoot 'state-v1/settings.json'
  $originalParentAcl=Get-Acl -LiteralPath $aclParent
  $originalRootAcl=Get-Acl -LiteralPath $aclRoot
  $originalFileAcl=Get-Acl -LiteralPath $denied
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  try { $sid=$identity.User } finally { $identity.Dispose() }
  Require ([MarkAutoAcceptanceJob]::PathAttributes($aclRoot) -ne [uint32]::MaxValue) 'ACL positive root metadata control failed'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $aclRoot -RequireUnaliased) $reviewed
  try {
    $rootAcl=Get-Acl -LiteralPath $aclRoot
    $rootRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ReadData,ReadAttributes','ContainerInherit,ObjectInherit','None','Deny')
    $rootAcl.AddAccessRule($rootRule); Set-Acl -LiteralPath $aclRoot -AclObject $rootAcl
    $fileAcl=Get-Acl -LiteralPath $denied
    $fileRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ReadAttributes','Deny')
    $fileAcl.AddAccessRule($fileRule); Set-Acl -LiteralPath $denied -AclObject $fileAcl
    $parentAcl=Get-Acl -LiteralPath $aclParent
    $parentRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ListDirectory','None','None','Deny')
    $parentAcl.AddAccessRule($parentRule); Set-Acl -LiteralPath $aclParent -AclObject $parentAcl
    Confirm-PreparedSelfOnlyListDeny $aclParent $sid
    $nativeRootCode=0; try { [void][MarkAutoAcceptanceJob]::PathAttributes($aclRoot) } catch { $nativeRootCode=Get-PreparedNativeCode $_ }
    $predicateCode=0; try { Get-PreparedStateInventory $aclRoot -RequireUnaliased | Out-Null } catch { $predicateCode=Get-PreparedNativeCode $_ }
    Require ($nativeRootCode -eq 5) 'Current ACL fixture did not prove native ERROR_ACCESS_DENIED'
    Require ($predicateCode -eq 5) 'Current metadata access denial admitted'
  } finally {
    Set-Acl -LiteralPath $aclParent -AclObject $originalParentAcl
    Set-Acl -LiteralPath $aclRoot -AclObject $originalRootAcl
    Set-Acl -LiteralPath $denied -AclObject $originalFileAcl
  }
  Require ([MarkAutoAcceptanceJob]::PathAttributes($denied) -ne [uint32]::MaxValue) 'ACL restored file metadata control failed'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $aclRoot -RequireUnaliased) $reviewed
  Require ((Get-FileHash -LiteralPath $denied -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $reviewed.files_sha256.'state-v1/settings.json') 'ACL probe changed fixture bytes'

  [IO.File]::WriteAllText((Join-Path $scaffold 'unexplained.exe'),'not-executable')
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  Reject { Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext } 'Non-empty installer tree admitted' 'Installer scaffolding contains a file'
  [IO.File]::Delete((Join-Path $scaffold 'unexplained.exe'))
  [void][IO.Directory]::CreateDirectory((Join-Path $scaffold 'unknown'))
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  Reject { Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext } 'Unknown installer directory admitted' 'Unknown installer scaffolding directory'
  [IO.Directory]::Delete((Join-Path $scaffold 'unknown'))
  [IO.File]::WriteAllText((Join-Path $fixture 'current-backup/installer-preservation-test.txt'),'changed-backup')
  Reject { Confirm-PreparedStateInventory (Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased) $reviewed } 'Current backup mismatch accepted' 'Prepared data digest changed; originals preserved'
  [IO.File]::WriteAllText((Join-Path $current 'workspace-location.json'),'existing')
  Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Existing workspace pointer admitted' 'Current baseline unknown file refused'
  [IO.File]::Delete((Join-Path $current 'workspace-location.json'))
  $currentReceiptPath=Join-Path $fixture 'reviewed-current.json'
  [IO.File]::WriteAllText($currentReceiptPath,($reviewed | ConvertTo-Json -Depth 8))
  $currentReceiptDigest=(Get-FileHash -LiteralPath $currentReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
  [void](Read-PreparedJson $currentReceiptPath $currentReceiptDigest)
  [IO.File]::AppendAllText($currentReceiptPath,' ')
  Reject { Read-PreparedJson $currentReceiptPath $currentReceiptDigest } 'Tampered current receipt accepted' 'Pinned bootstrap digest mismatch'
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  $scaffoldRedirect=Join-Path $scaffold 'redirect'
  New-Item -ItemType Junction -Path $scaffoldRedirect -Target $source | Out-Null
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  try { Reject { Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext } 'Installer scaffold redirect admitted' 'Bootstrap redirect refused before content reads' }
  finally { [IO.Directory]::Delete($scaffoldRedirect) }
  $bad=Clone-CurrentFixture; $bad.install_metadata.'.'.modified_at_utc=[DateTime]::UtcNow.AddDays(-1).ToString('o')
  Reject { Assert-PreparedInstallScaffolding $scaffold $bad $priorKitContext $invocationContext } 'Wrong scaffold provenance accepted' 'Pinned installer scaffolding metadata changed'
  $pointerPath=Join-Path $current 'workspace-location.json'
  [IO.File]::WriteAllText($pointerPath,'owned-pointer-only')
  $pointerDigest=(Get-FileHash -LiteralPath $pointerPath -Algorithm SHA256).Hash.ToLowerInvariant()
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $current -RequireUnaliased -OwnedPointerDigest $pointerDigest) $reviewed
  [IO.File]::WriteAllText($pointerPath,'changed-owned-pointer')
  Reject { Get-PreparedStateInventory $current -RequireUnaliased -OwnedPointerDigest $pointerDigest } 'Changed owned workspace pointer admitted' 'Owned workspace pointer changed'
  [IO.File]::Delete($pointerPath)


  # v2 follow-on negatives: verify the actual runtime gates, never a copied oracle.
  $controllerStage='current_baseline_follow_on_controls'
  $bad=Clone-CurrentFixture; $bad.schema_version=1
  Reject { Confirm-CurrentFixture $bad } 'Version-one current receipt admitted' 'Current baseline provenance refused'
  $wrongInvocation=$invocationContext.Clone(); $wrongInvocation.ExecutionSha=('8'*40)
  Reject { Confirm-PreparedCurrentBaseline $reviewed $kitContext ('e'*64) ('f'*64) ('1'*64) $canonicalSource $canonicalCurrent $canonicalScaffold $wrongInvocation $priorKitContext } 'Wrong original invocation candidate admitted' 'Current baseline provenance refused'
  $wrongInvocation=$invocationContext.Clone(); $wrongInvocation.TimedOut=$true
  Reject { Confirm-PreparedCurrentBaseline $reviewed $kitContext ('e'*64) ('f'*64) ('1'*64) $canonicalSource $canonicalCurrent $canonicalScaffold $wrongInvocation $priorKitContext } 'Timed-out original invocation admitted' 'Current baseline provenance refused'
  $backupSentinel=Join-Path $fixture 'current-backup/installer-preservation-test.txt'
  [IO.File]::WriteAllText($backupSentinel,'synthetic-baseline-only')
  $backupAlias=Join-Path $fixture 'backup-sentinel-alias.txt'
  New-Item -ItemType HardLink -Path $backupAlias -Target $backupSentinel | Out-Null
  try { Reject { Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased } 'Hard-linked backup admitted' 'Current baseline file alias or stream refused' }
  finally { [IO.File]::Delete($backupAlias) }
  [MarkAutoPreparedStreamFixture]::Create($fixture,$backupSentinel,'synthetic-backup-stream')
  Require ([MarkAutoPreparedStreamFixture]::Exists($fixture,$backupSentinel,'synthetic-backup-stream')) 'Backup ADS setup was not verified'
  try { Reject { Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased } 'Alternate backup stream admitted' 'Current baseline file alias or stream refused' }
  finally { [MarkAutoPreparedStreamFixture]::Delete($fixture,$backupSentinel,'synthetic-backup-stream') }
  Require (-not [MarkAutoPreparedStreamFixture]::Exists($fixture,$backupSentinel,'synthetic-backup-stream')) 'Backup ADS cleanup was not verified'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased) $reviewed
  [IO.File]::WriteAllText($pointerPath,'owned-pointer-only')
  $pointerDigest=(Get-FileHash -LiteralPath $pointerPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $pointerAlias=Join-Path $fixture 'owned-pointer-alias.txt'
  New-Item -ItemType HardLink -Path $pointerAlias -Target $pointerPath | Out-Null
  try { Reject { Get-PreparedStateInventory $current -RequireUnaliased -OwnedPointerDigest $pointerDigest } 'Hard-linked owned pointer admitted' 'Current baseline file alias or stream refused' }
  finally { [IO.File]::Delete($pointerAlias); [IO.File]::Delete($pointerPath) }
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  $scaffoldLeaf=Join-Path $scaffold 'payloads/0.2.1/is-ABCDE'

  $scaffoldParent=Split-Path $scaffold -Parent
  $savedScaffoldParentAcl=Get-Acl -LiteralPath $scaffoldParent
  $savedScaffoldRootAcl=Get-Acl -LiteralPath $scaffold
  Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext
  try {
    $rootAcl=Get-Acl -LiteralPath $scaffold
    $rootRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ReadAttributes','Deny')
    $rootAcl.AddAccessRule($rootRule); Set-Acl -LiteralPath $scaffold -AclObject $rootAcl
    $parentAcl=Get-Acl -LiteralPath $scaffoldParent
    $parentRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ListDirectory','None','None','Deny')
    $parentAcl.AddAccessRule($parentRule); Set-Acl -LiteralPath $scaffoldParent -AclObject $parentAcl
    Confirm-PreparedSelfOnlyListDeny $scaffoldParent $sid
    $scaffoldNativeCode=0; try { [void][MarkAutoAcceptanceJob]::PathAttributes($scaffold) } catch { $scaffoldNativeCode=Get-PreparedNativeCode $_ }
    $scaffoldPredicateCode=0; try { Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext } catch { $scaffoldPredicateCode=Get-PreparedNativeCode $_ }
    Require ($scaffoldNativeCode -eq 5) 'Scaffold ACL fixture did not prove native ERROR_ACCESS_DENIED'
    Require ($scaffoldPredicateCode -eq 5) 'Scaffold metadata access denial admitted'
  } finally {
    Set-Acl -LiteralPath $scaffoldParent -AclObject $savedScaffoldParentAcl
    Set-Acl -LiteralPath $scaffold -AclObject $savedScaffoldRootAcl
  }
  Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext

  Require ([IO.Directory]::Exists($scaffoldLeaf) -and [IO.Directory]::GetFiles($scaffold,'*',[IO.SearchOption]::AllDirectories).Length -eq 0) 'Reviewed empty scaffolding changed after rejection controls'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $current -RequireUnaliased) $reviewed

  # Inject after the first successful production inventory, before the second.
  # A data-denied unknown file traps any content open; an outside hard link keeps
  # the source names/hashes unchanged, so a mere eventual mismatch cannot pass.
  $script:productionInventory=(Get-Command Get-PreparedStateInventory -CommandType Function).ScriptBlock
  foreach ($mutation in @('unknown','alias')) {
    $script:inventoryMutation=$mutation; $script:inventoryPasses=0
    $script:secondInventoryReturned=$false; $script:secondInventoryStrict=$false
    $script:betweenPassRoot=$current; $script:betweenPassFile=Join-Path $current 'unreviewed-between-pass.txt'
    $script:betweenPassAlias=Join-Path $fixture 'between-pass-alias.txt'
    $script:betweenPassOriginalAcl=$null; $script:contentTrapVerified=$false
    try {
      Set-Item -LiteralPath Function:Get-PreparedStateInventory -Value {
        param([string]$Root,[switch]$RequireUnaliased,[string]$OwnedPointerDigest='')
        if ($Root -ceq $script:betweenPassRoot) {
          $script:inventoryPasses++
          if ($script:inventoryPasses -eq 2) { $script:secondInventoryStrict=[bool]$RequireUnaliased }
        }
        $actual=& $script:productionInventory $Root -RequireUnaliased:$RequireUnaliased -OwnedPointerDigest $OwnedPointerDigest
        if ($Root -ceq $script:betweenPassRoot) {
          if ($script:inventoryPasses -eq 2) { $script:secondInventoryReturned=$true }
          if ($script:inventoryPasses -eq 1) {
            if ($script:inventoryMutation -ceq 'unknown') {
              [IO.File]::WriteAllText($script:betweenPassFile,'synthetic-unreviewed-only')
              $script:betweenPassOriginalAcl=Get-Acl -LiteralPath $script:betweenPassFile
              $acl=Get-Acl -LiteralPath $script:betweenPassFile
              $rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ReadData','Deny')
              $acl.AddAccessRule($rule); Set-Acl -LiteralPath $script:betweenPassFile -AclObject $acl
              Require ([MarkAutoAcceptanceJob]::PathAttributes($script:betweenPassFile) -ne [uint32]::MaxValue) 'Content trap metadata was unreadable'
              try { $probe=[IO.File]::Open($script:betweenPassFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read); $probe.Dispose() }
              catch {
                $cause=$_.Exception.GetBaseException()
                $script:contentTrapVerified=($cause -is [UnauthorizedAccessException] -and ($cause.HResult -band 0xffff) -eq 5)
              }
              Require $script:contentTrapVerified 'Unknown-file content access trap was not verified'
            } else {
              New-Item -ItemType HardLink -Path $script:betweenPassAlias -Target (Join-Path $Root 'installer-preservation-test.txt') | Out-Null
            }
          }
        }
        return $actual
      }
      $output=Join-Path $fixture ('between-pass-'+$mutation+'-backup')
      $expected=if ($mutation -ceq 'unknown') { 'Current baseline unknown file refused' } else { 'Current baseline file alias or stream refused' }
      Reject { Backup-PreparedState $current $output $reviewed -RequireUnaliased } ('Between-pass '+$mutation+' was not refused at inventory') $expected
      Require ($script:inventoryPasses -eq 2 -and $script:secondInventoryStrict -and -not $script:secondInventoryReturned) 'Second inventory bypassed strict admission before content access'
      Require ([IO.Directory]::GetFileSystemEntries($output).Length -eq 0) 'Between-pass refusal copied content before admission'
      if ($mutation -ceq 'unknown') { Require $script:contentTrapVerified 'Unknown-file content trap missing' }
    } finally {
      Set-Item -LiteralPath Function:Get-PreparedStateInventory -Value $script:productionInventory
      if ($script:betweenPassOriginalAcl) {
        Set-Acl -LiteralPath $script:betweenPassFile -AclObject $script:betweenPassOriginalAcl
        [IO.File]::Delete($script:betweenPassFile)
      }
      if ([IO.File]::Exists($script:betweenPassAlias)) { [IO.File]::Delete($script:betweenPassAlias) }
    }
    Confirm-PreparedStateInventory (Get-PreparedStateInventory $current -RequireUnaliased) $reviewed
  }


  # Every directory node is covered, including roots and empty credentials.
  foreach ($relative in @('.')+@($reviewed.directories)) {
    $directory=if ($relative -ceq '.') { $current } else { Join-Path $current $relative }
    Assert-PreparedBootstrapPath $directory -AllowAbsent
    [MarkAutoPreparedStreamFixture]::Create($fixture,$directory,'synthetic-directory-stream')
    try {
      Require ([MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-directory-stream')) 'Directory ADS setup was not independently verified'
      Reject { Get-PreparedStateInventory $current -RequireUnaliased } 'Directory ADS baseline admitted' 'Current baseline directory stream or metadata refused'
    } finally { [MarkAutoPreparedStreamFixture]::Delete($fixture,$directory,'synthetic-directory-stream') }
    Require (-not [MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-directory-stream')) 'Directory ADS cleanup was not verified'
    Confirm-PreparedStateInventory (Get-PreparedStateInventory $current -RequireUnaliased) $reviewed
  }
  foreach ($relative in @('.')+@($reviewed.directories)) {
    $directory=if ($relative -ceq '.') { Join-Path $fixture 'current-backup' } else { Join-Path (Join-Path $fixture 'current-backup') $relative }
    [MarkAutoPreparedStreamFixture]::Create($fixture,$directory,'synthetic-directory-stream')
    try {
      Require ([MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-directory-stream')) 'Backup directory ADS setup was not verified'
      Reject { Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased } 'Backup directory ADS admitted' 'Current baseline directory stream or metadata refused'
    } finally { [MarkAutoPreparedStreamFixture]::Delete($fixture,$directory,'synthetic-directory-stream') }
    Require (-not [MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-directory-stream')) 'Backup directory ADS cleanup was not verified'
    Confirm-PreparedStateInventory (Get-PreparedStateInventory (Join-Path $fixture 'current-backup') -RequireUnaliased) $reviewed
  }
  [IO.Directory]::SetLastWriteTimeUtc($scaffold,(Read-PreparedUtc $metadata['.'].modified_at_utc))
  foreach ($relative in @('.')+$directoryMap) {
    $directory=if ($relative -ceq '.') { $scaffold } else { Join-Path $scaffold $relative }
    $stamp=(New-Object IO.DirectoryInfo($directory)).get_LastWriteTimeUtc()
    [MarkAutoPreparedStreamFixture]::Create($fixture,$directory,'synthetic-scaffold-stream')
    [IO.Directory]::SetLastWriteTimeUtc($directory,$stamp)
    try {
      Require ([MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-scaffold-stream')) 'Scaffold directory ADS setup was not verified'
      Reject { Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext } 'Scaffold directory ADS admitted' 'Current baseline directory stream or metadata refused'
    } finally {
      [MarkAutoPreparedStreamFixture]::Delete($fixture,$directory,'synthetic-scaffold-stream')
      [IO.Directory]::SetLastWriteTimeUtc($directory,$stamp)
    }
    Require (-not [MarkAutoPreparedStreamFixture]::Exists($fixture,$directory,'synthetic-scaffold-stream')) 'Scaffold directory ADS cleanup was not verified'
    Assert-PreparedInstallScaffolding $scaffold $reviewed $priorKitContext $invocationContext
  }
  # Bootstrap separation runs before any session directory creation.
  $bootstrapLab=$canonicalFixture; $bootstrapSource=$canonicalSource
  $priorRoot=[IO.Path]::GetFullPath((Join-Path $bootstrapLab 'prior-kit-bootstrap')).TrimEnd('\'); [void][IO.Directory]::CreateDirectory($priorRoot)
  [IO.File]::WriteAllText((Join-Path $priorRoot 'kit.json'),($priorKitContext | ConvertTo-Json -Depth 5))
  $rootReceipt=Clone-CurrentFixture; $rootReceipt.prior_kit_root=$priorRoot
  $rootReceipt.prior_kit_sha256=(Get-FileHash -LiteralPath (Join-Path $priorRoot 'kit.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  $nestedSession=[IO.Path]::GetFullPath((Join-Path $priorRoot 'forbidden-output'))
  $disjointSession=[IO.Path]::GetFullPath((Join-Path $bootstrapLab 'disjoint-output'))
  $sameSession=[IO.Path]::GetFullPath((Join-Path $bootstrapLab 'same-kit-output'))
  Reject { Read-PreparedPriorContext $rootReceipt $kitContext ('e'*64) $bootstrapSource $nestedSession $bootstrapLab } 'Session inside prior kit admitted' 'Kit and session directories must not overlap'
  Require (-not [IO.Directory]::Exists($nestedSession)) 'Prior-kit refusal created output'
  Reject { Read-PreparedPriorContext $rootReceipt $kitContext ('e'*64) $bootstrapSource $priorRoot $bootstrapLab } 'Prior kit reused as session admitted' 'Kit and session directories must not overlap'
  Reject { Read-PreparedPriorContext $rootReceipt $kitContext ('e'*64) $bootstrapSource $bootstrapLab $bootstrapLab } 'Session ancestor of prior kit admitted' 'Kit and session directories must not overlap'
  $disjoint=Read-PreparedPriorContext $rootReceipt $kitContext ('e'*64) $bootstrapSource $disjointSession $bootstrapLab
  Require ($disjoint.root -ceq $priorRoot -and -not [IO.Directory]::Exists($disjointSession)) 'Read-only disjoint prior-kit positive control changed output'
  $sameKit=@{}+$kitContext; $sameKit.schema_version=1
  [IO.File]::WriteAllText((Join-Path $bootstrapSource 'kit.json'),($sameKit | ConvertTo-Json -Depth 5))
  $sameDigest=(Get-FileHash -LiteralPath (Join-Path $bootstrapSource 'kit.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  $sameReceipt=Clone-CurrentFixture; $sameReceipt.prior_kit_root=$bootstrapSource; $sameReceipt.prior_kit_sha256=$sameDigest
  $sameReceipt.prior_candidate_commit=$sameKit.candidate_commit
  [void](Read-PreparedPriorContext $sameReceipt $sameKit $sameDigest $bootstrapSource $sameSession $bootstrapLab)
  Reject { Read-PreparedPriorContext $sameReceipt $sameKit ('0'*64) $bootstrapSource $sameSession $bootstrapLab } 'Unpinned same-kit identity admitted' 'Current/prior kit identity was not explicitly pinned'

  $noncanonical=$rootReceipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json
  $noncanonical.prior_kit_root=$bootstrapLab+'\.\prior-kit-bootstrap'
  Require ([IO.Path]::GetFullPath($noncanonical.prior_kit_root) -ceq $priorRoot -and $noncanonical.prior_kit_root -cne $priorRoot) 'Noncanonical receipt refusal control was not distinct'
  Reject { Read-PreparedPriorContext $noncanonical $kitContext ('e'*64) $bootstrapSource $disjointSession $bootstrapLab } 'Noncanonical prior receipt admitted' 'Current baseline prior kit path refused'
  Require (-not [IO.Directory]::Exists($disjointSession)) 'Receipt refusal created output'
  $exactLab=$rootReceipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json
  $exactLab.prior_kit_root=$bootstrapLab
  Reject { Read-PreparedPriorContext $exactLab $kitContext ('e'*64) $bootstrapSource $disjointSession $bootstrapLab } 'Exact lab root adopted as prior kit' 'Current baseline prior kit path refused'
  foreach ($trailingRoot in @(($priorRoot+'\'),($bootstrapLab+'\'))) {
    $trailing=$rootReceipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $trailing.prior_kit_root=$trailingRoot
    Reject { Read-PreparedPriorContext $trailing $kitContext ('e'*64) $bootstrapSource $disjointSession $bootstrapLab } 'Trailing-separator prior receipt admitted' 'Current baseline prior kit path refused'
    Require (-not [IO.Directory]::Exists($disjointSession)) 'Trailing-separator receipt refusal created output'
  }
  $outside=$rootReceipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json
  $outside.prior_kit_root=[IO.Path]::GetFullPath((Join-Path (Split-Path $bootstrapLab -Parent) 'unapproved-prior-kit'))
  Reject { Read-PreparedPriorContext $outside $kitContext ('e'*64) $bootstrapSource $disjointSession $bootstrapLab } 'Outside lab prior kit admitted' 'Current baseline prior kit path refused'
  $labAlias=$bootstrapLab+'\.\'
  $sourceAlias=(Split-Path $bootstrapSource -Parent)+'\.\'+(Split-Path $bootstrapSource -Leaf)
  $sessionAlias=(Split-Path $disjointSession -Parent)+'\.\'+(Split-Path $disjointSession -Leaf)
  [void](Read-PreparedPriorContext $sameReceipt $sameKit $sameDigest $sourceAlias $sameSession $labAlias)
  Reject { Read-PreparedPriorContext $sameReceipt $sameKit ('0'*64) $sourceAlias $sameSession $labAlias } 'Operational alias bypassed same-kit digest pin' 'Current/prior kit identity was not explicitly pinned'
  $aliasContext=Read-PreparedPriorContext $rootReceipt $kitContext ('e'*64) $sourceAlias $sessionAlias $labAlias
  Require ($aliasContext.root -ceq $priorRoot -and -not [IO.Directory]::Exists($disjointSession)) 'Operational alias changed canonical receipt identity or output'

  # Pure production containment predicates: no launch, receipt reads or host paths.
  $controllerStage='canonical_boundary_controls'
  $boundaryLab=$bootstrapLab; $boundaryAlias=$bootstrapLab+'\.\'
  $boundaryChild=Join-Path $boundaryLab 'boundary-child'
  $boundaryChildAlias=$boundaryAlias+'boundary-child'
  foreach ($failure in @('Kit, script, receipt and session evidence must stay in MarkAuto-TestLab','Current baseline invocation path refused')) {
    Assert-PreparedLabContainment $boundaryChild $boundaryLab $failure
    Assert-PreparedLabContainment $boundaryChildAlias $boundaryAlias $failure
    foreach ($notDescendant in @($boundaryLab,($boundaryLab+'\'),($boundaryAlias),($boundaryLab+'-sibling\file.json'),(Split-Path $boundaryLab -Parent))) {
      Reject { Assert-PreparedLabContainment $notDescendant $boundaryAlias $failure } 'Lab containment accepted a non-descendant' $failure
    }
  }
  $boundaryScript=Join-Path $boundaryLab 'packaging\prepared_host_session.ps1'
  $boundaryScriptAlias=$boundaryAlias+'packaging\.\prepared_host_session.ps1'
  Require ([IO.Path]::GetFullPath($boundaryScriptAlias) -ceq $boundaryScript) 'Script operational alias was not the exact canonical target'
  Assert-PreparedLabContainment $boundaryScriptAlias $boundaryAlias 'Kit, script, receipt and session evidence must stay in MarkAuto-TestLab'
  $boundaryApp=Join-Path $boundaryLab 'app'
  $boundaryAppAlias=$boundaryAlias+'app\'
  $boundaryExe=Join-Path $boundaryApp 'MarkAuto.exe'
  Assert-PreparedShortcutContainment $boundaryExe $boundaryApp
  Assert-PreparedShortcutContainment $boundaryExe $boundaryAppAlias
  Assert-PreparedShortcutContainment ($boundaryAlias+'app\.\MarkAuto.exe') $boundaryAppAlias
  foreach ($wrongTarget in @($boundaryApp,($boundaryApp+'-sibling\MarkAuto.exe'),(Join-Path $boundaryApp 'Other.exe'),(Join-Path $boundaryApp 'markauto.exe'),($boundaryApp+'\..\MarkAuto.exe'))) {
    Reject { Assert-PreparedShortcutContainment $wrongTarget $boundaryAppAlias } 'Shortcut containment accepted an escaped or non-exact executable' 'Installed shortcut escaped the exact app tree'
  }
  [Console]::Out.WriteLine('{"stage":"canonical_boundary_controls","status":"passed","scope":"synthetic-native-only"}')

  [Console]::Out.WriteLine('{"stage":"current_baseline_follow_on_controls","status":"passed","scope":"synthetic-native-only"}')

  [Console]::Out.WriteLine('{"stage":"current_baseline_controls","status":"passed","scope":"synthetic-native-only"}')

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
