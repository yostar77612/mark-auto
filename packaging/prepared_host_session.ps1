param([string]$KitRoot, [string]$KitSha256, [string]$StateReceipt, [string]$StateReceiptSha256,
      [string]$SessionRoot,
      [ValidateSet('LifecycleHandoff','CurrentBaseline')][string]$ReceiptKind = 'LifecycleHandoff',
      [ValidateSet('PreparedHost')][string]$AcceptanceScope = 'PreparedHost',
      [Parameter(DontShow=$true)][string]$AcceptanceJob = '')
# Separate, deliberately partial follow-on. Never relax test_installer.ps1's absence guard.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-PreparedInteractiveUser {
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  try {
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or [Diagnostics.Process]::GetCurrentProcess().get_SessionId() -eq 0 -or -not [Environment]::Is64BitProcess) { throw 'Requires a non-elevated interactive x64 session' }
  } finally { $identity.Dispose() }
}

function Assert-PreparedSeparateRoots([string]$Kit, [string]$Session) {
  $kitPath=[IO.Path]::GetFullPath($Kit).TrimEnd('\')
  $sessionPath=[IO.Path]::GetFullPath($Session).TrimEnd('\')
  if ($kitPath -ieq $sessionPath -or $sessionPath.StartsWith(($kitPath+'\'),[StringComparison]::OrdinalIgnoreCase) -or $kitPath.StartsWith(($sessionPath+'\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Kit and session directories must not overlap' }
}

# Lexical containment only; callers retain their original identity and native path gates.
function Assert-PreparedLabContainment([string]$Path, [string]$LabPath, [string]$Failure) {
  $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
  $labRoot=[IO.Path]::GetFullPath($LabPath).TrimEnd('\')
  if (-not $full.StartsWith(($labRoot+'\'),[StringComparison]::OrdinalIgnoreCase)) { throw $Failure }
}

function Assert-PreparedShortcutContainment([string]$Target, [string]$AppPath) {
  $appRoot=[IO.Path]::GetFullPath($AppPath).TrimEnd('\')
  if (-not [IO.Path]::GetFullPath($Target).StartsWith(($appRoot+'\'),[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $Target -Leaf) -cne 'MarkAuto.exe') { throw 'Installed shortcut escaped the exact app tree' }
}

function Assert-PreparedBootstrapPath([string]$Path, [switch]$AllowAbsent) {
  $full=[IO.Path]::GetFullPath($Path)
  if ($full -notmatch '^[A-Za-z]:\\' -or $full.Substring(2).Contains(':')) { throw 'Ordinary local bootstrap paths required' }
  # Inspect ancestors before descendants; never traverse a known redirect first.
  $paths=New-Object 'System.Collections.Generic.Stack[string]'
  $inspect=$full
  while ($inspect) {
    $paths.Push($inspect); $parent=Split-Path $inspect -Parent
    if ($parent -eq $inspect) { break }; $inspect=$parent
  }
  while ($paths.Count) {
    $next=$paths.Pop()
    if ($AllowAbsent) {
      # This mode is used only after the digest-verified native helper was loaded.
      $attributes=[MarkAutoAcceptanceJob]::PathAttributes($next)
      if ($attributes -eq [uint32]::MaxValue) { continue }
    } else {
      $item=Get-Item -LiteralPath $next -Force -ErrorAction Stop
      $attributes=[uint32]$item.get_Attributes()
    }
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Bootstrap redirect refused before content reads' }
  }
}
function Read-PreparedBootstrap([string]$Path,[string]$Digest,[long]$MaxBytes,[switch]$Text,[switch]$Hold) {
  Assert-PreparedBootstrapPath $Path
  if ($Digest -cnotmatch '^[a-f0-9]{64}$') { throw 'Exact external bootstrap digest required' }
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  $retained=$false
  try {
    if ($stream.get_Length() -gt $MaxBytes) { throw 'Bootstrap input exceeds bounded size' }
    $hash=[Security.Cryptography.SHA256]::Create()
    try { $actual=([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
    if ($actual -cne $Digest) { throw 'Pinned bootstrap digest mismatch' }
    if ($Hold) { $retained=$true; return $stream }
    if ($Text) {
      $stream.Position=0; $reader=New-Object IO.StreamReader($stream,[Text.Encoding]::UTF8,$true)
      try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    }
  } finally { if (-not $retained) { $stream.Dispose() } }
}


function Get-PreparedFileSha256([string]$Path) {
  # Keep SHA256 independent of inherited cross-edition PowerShell modules.
  # Callers retain their existing path, manifest and alias admission checks.
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  try {
    $hash=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
  } finally { $stream.Dispose() }
}

function Assert-PreparedReceiptKeys($Object, [string[]]$Expected) {
  $names=@($Object.PSObject.Properties.Name)
  if ($names.Count -ne $Expected.Count -or
      (@($names | Sort-Object) -join '|') -cne (@($Expected | Sort-Object) -join '|')) {
    throw 'Current baseline receipt schema refused'
  }
}
function Read-PreparedUtc([string]$Value) {
  if ($Value -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$') { throw 'Current baseline timestamp refused' }
  try { return [DateTime]::ParseExact($Value,'o',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind) }
  catch { throw 'Current baseline timestamp refused' }
}
function Assert-PreparedUnaliasedFile([IO.FileStream]$Stream, [string]$Path) {
  if (-not [MarkAutoAcceptanceJob].GetMethod('RequireSingleLinkDefaultStream')) { throw 'Verified helper lacks current-baseline alias admission' }
  try { [MarkAutoAcceptanceJob]::RequireSingleLinkDefaultStream($Stream.get_SafeFileHandle().DangerousGetHandle(),$Path) }
  catch { throw 'Current baseline file alias or stream refused' }
}
function Confirm-PreparedCurrentBaseline($Receipt, $Kit, [string]$KitDigest, [string]$InstallerDigest,
    [string]$EntrypointDigest, [string]$KitPath, [string]$DataPath, [string]$AppPath, $Invocation, $PriorKit,
    [DateTime]$Now = [DateTime]::UtcNow) {
  # Operational arguments may be aliases; declared receipt identities remain exact.
  $KitPath=[IO.Path]::GetFullPath($KitPath).TrimEnd('\')
  $DataPath=[IO.Path]::GetFullPath($DataPath).TrimEnd('\')
  $AppPath=[IO.Path]::GetFullPath($AppPath).TrimEnd('\')
  Assert-PreparedReceiptKeys $Receipt @('schema_version','owner','original_lifecycle_continuity','captured_at_utc',
    'kit_root','kit_sha256','candidate_commit','candidate_version','baseline_version','installer_sha256',
    'helper_sha256','helper_script_sha256','entrypoint_sha256','app_data_path','install_path',
    'directories','files_sha256','install_directories','install_metadata','prior_reports_sha256',
    'lifecycle_invocation_path','lifecycle_invocation_sha256','prior_kit_root','prior_kit_sha256',
    'prior_candidate_commit','prior_candidate_version','prior_baseline_version')
  if ($Receipt.schema_version -ne 2 -or $Receipt.owner -cne 'prepared-host-current-baseline' -or
      $Receipt.original_lifecycle_continuity -cne 'UNPROVEN') { throw 'Current baseline provenance refused' }
  $capture=Read-PreparedUtc $Receipt.captured_at_utc
  $started=Read-PreparedUtc $Invocation.StartedAtUtc
  $finished=Read-PreparedUtc $Invocation.FinishedAtUtc
  if ($capture -gt $Now.AddSeconds(5) -or $capture -lt $Now.AddMinutes(-30) -or
      $finished -lt $started -or $finished -gt $capture) { throw 'Current baseline freshness refused' }
  if ($Receipt.kit_root -cne $KitPath -or $Receipt.app_data_path -cne $DataPath -or
      $Receipt.install_path -cne $AppPath -or $Receipt.kit_sha256 -cne $KitDigest -or
      $Receipt.candidate_commit -cne $Kit.candidate_commit -or $Receipt.candidate_version -cne $Kit.version -or
      $Receipt.baseline_version -cne $Kit.baseline_version -or $Receipt.installer_sha256 -cne $InstallerDigest -or
      $Receipt.helper_sha256 -cne $Kit.files_sha256.'packaging/acceptance_process.dll' -or
      $Receipt.helper_script_sha256 -cne $Kit.files_sha256.'packaging/acceptance_process.ps1' -or
      $Receipt.entrypoint_sha256 -cne $EntrypointDigest -or $Receipt.prior_candidate_commit -cne $PriorKit.candidate_commit -or
      $Receipt.prior_candidate_version -cne $PriorKit.version -or $Receipt.prior_baseline_version -cne $PriorKit.baseline_version -or
      $PriorKit.schema_version -ne 1 -or $Invocation.ExecutionSha -cne $Receipt.prior_candidate_commit -or
      $Invocation.ActualCallerExitCode -ne 2 -or $Invocation.TimedOut -ne $false) { throw 'Current baseline provenance refused' }
  foreach ($digest in @($KitDigest,$InstallerDigest,$EntrypointDigest,$Receipt.helper_sha256,
      $Receipt.helper_script_sha256,$Receipt.lifecycle_invocation_sha256,$Receipt.prior_kit_sha256)) {
    if ($digest -cnotmatch '^[a-f0-9]{64}$') { throw 'Current baseline digest refused' }
  }
  $knownFiles=@('.analysis-recovery-admission.lock','installer-preservation-test.txt',
    'state-v1/desktop_safety.json','state-v1/settings.json','workspace-format.json')
  $knownDirectories=@('cache','control-v1','credentials','logs','state-v1','state-v1/market_cache')
  Assert-PreparedReceiptKeys $Receipt.files_sha256 $knownFiles
  if (($Receipt.directories -join '|') -cne ($knownDirectories -join '|')) { throw 'Current baseline reviewed directory map refused' }
  foreach ($entry in $Receipt.files_sha256.PSObject.Properties) {
    if ($entry.Value -cnotmatch '^[a-f0-9]{64}$') { throw 'Current baseline digest refused' }
  }
  Assert-PreparedReceiptKeys $Receipt.prior_reports_sha256 @('installer-results.json','installer-supervisor.json',
    'installer-scope-preflight.json','smoke-installed.json','smoke-upgraded.json')
  foreach ($entry in $Receipt.prior_reports_sha256.PSObject.Properties) {
    if ($entry.Value -cnotmatch '^[a-f0-9]{64}$') { throw 'Current baseline digest refused' }
  }
  foreach ($name in @('installer-results.json','installer-supervisor.json','installer-scope-preflight.json')) {
    $record=@($Invocation.NativeReports | Where-Object { $_.Name -ceq $name })
    if ($record.Count -ne 1 -or $record[0].Sha256 -cne $Receipt.prior_reports_sha256.PSObject.Properties[$name].Value) {
      throw 'Current baseline invocation context refused'
    }
  }
}
function Assert-PreparedInstallScaffolding([string]$Root, $Receipt, $Kit, $Invocation) {
  $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\')
  $rootPrefix=$rootPath+'\'
  $script:preparedScaffoldPhase='root_metadata'; $script:preparedScaffoldRawLength=$Root.Length
  $script:preparedScaffoldCanonicalLength=$rootPath.Length; $script:preparedScaffoldRelativeDepth=0; $script:preparedScaffoldPrefixMatch=$false
  Assert-PreparedBootstrapPath $Root -AllowAbsent
  Assert-AcceptancePath $Root
  $attributes=[MarkAutoAcceptanceJob]::PathAttributes($Root)
  $expected=@($Receipt.install_directories)
  if ($attributes -eq [uint32]::MaxValue) {
    if ($expected.Count -ne 0 -or @($Receipt.install_metadata.PSObject.Properties).Count -ne 0) { throw 'Pinned installer scaffolding changed' }
    return
  }
  if (($attributes -band [IO.FileAttributes]::Directory) -eq 0) { throw 'Installer scaffolding contains a file' }
  $base=@('payloads',('payloads/'+$Kit.baseline_version),('payloads/'+$Kit.version))
  if ($Kit.baseline_version -ceq $Kit.version -or $expected.Count -ne 5) { throw 'Reviewed installer scaffolding map refused' }
  foreach ($name in $base) { if ($expected -cnotcontains $name) { throw 'Reviewed installer scaffolding map refused' } }
  foreach ($version in @($Kit.baseline_version,$Kit.version)) {
    $prefix='payloads/'+$version+'/'
    $leaves=@($expected | Where-Object { $_.StartsWith($prefix,[StringComparison]::Ordinal) })
    if ($leaves.Count -ne 1 -or $leaves[0].Substring($prefix.Length) -cnotmatch '^is-[A-Z0-9]{5}$') { throw 'Reviewed installer scaffolding map refused' }
  }
  Assert-PreparedReceiptKeys $Receipt.install_metadata (@('.')+$expected)
  $started=Read-PreparedUtc $Invocation.StartedAtUtc; $finished=Read-PreparedUtc $Invocation.FinishedAtUtc
  $actual=New-Object System.Collections.ArrayList; $pending=New-Object 'System.Collections.Generic.Queue[string]'
  $pending.Enqueue($rootPath)
  while ($pending.Count) {
    $directory=$pending.Dequeue()
    Assert-PreparedBootstrapPath $directory -AllowAbsent
    Assert-AcceptancePath $directory
    Assert-PreparedDirectoryStreams $directory
    $script:preparedScaffoldPhase='relative_path'
    $script:preparedScaffoldPrefixMatch=($directory -ceq $rootPath -or $directory.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase))
    if (-not $script:preparedScaffoldPrefixMatch) { throw 'Unknown installer scaffolding directory' }
    $relative=if ($directory -ceq $rootPath) { '.' } else { $directory.Substring($rootPrefix.Length).Replace('\','/') }
    $script:preparedScaffoldRelativeDepth=(@($relative.Split('/')).Count)
    $script:preparedScaffoldPhase='reviewed_directory_map'
    if ($relative -cne '.' -and $expected -cnotcontains $relative) { throw 'Unknown installer scaffolding directory' }
    if ($actual.Count -ge 6) { throw 'Installer scaffolding exceeds reviewed map' }
    [void]$actual.Add($relative)
    $meta=$Receipt.install_metadata.PSObject.Properties[$relative].Value
    Assert-PreparedReceiptKeys $meta @('created_at_utc','modified_at_utc')
    $created=Read-PreparedUtc $meta.created_at_utc; $modified=Read-PreparedUtc $meta.modified_at_utc
    $info=New-Object IO.DirectoryInfo($directory)
    if ($created -lt $started -or $created -gt $finished -or $modified -lt $started -or $modified -gt $finished -or
        $info.get_CreationTimeUtc().ToString('o') -cne $meta.created_at_utc -or
        $info.get_LastWriteTimeUtc().ToString('o') -cne $meta.modified_at_utc) { throw 'Pinned installer scaffolding metadata changed' }
    $entries=[IO.Directory]::EnumerateFileSystemEntries($directory).GetEnumerator()
    try { while ($entries.MoveNext()) {
      $path=$entries.get_Current(); Assert-PreparedBootstrapPath $path -AllowAbsent; Assert-AcceptancePath $path
      if (([MarkAutoAcceptanceJob]::PathAttributes($path) -band [IO.FileAttributes]::Directory) -eq 0) { throw 'Installer scaffolding contains a file' }
      $pending.Enqueue($path)
      if ($pending.Count -gt 6) { throw 'Installer scaffolding exceeds reviewed map' }
    } } finally { $entries.Dispose() }
  }
  if ((@($actual | Where-Object { $_ -cne '.' } | Sort-Object) -join '|') -cne (@($expected | Sort-Object) -join '|')) { throw 'Pinned installer scaffolding changed' }
}


function Read-PreparedPriorContext($Receipt, $Kit, [string]$KitDigest,
    [string]$KitRootPath, [string]$SessionPath, [string]$LabPath) {
  if ($Receipt.schema_version -ne 2 -or $Receipt.owner -cne 'prepared-host-current-baseline' -or
      $Receipt.original_lifecycle_continuity -cne 'UNPROVEN') { throw 'Current baseline provenance refused' }
  $labRoot=[IO.Path]::GetFullPath($LabPath).TrimEnd('\')
  $kitPath=[IO.Path]::GetFullPath($KitRootPath).TrimEnd('\')
  $sessionPath=[IO.Path]::GetFullPath($SessionPath).TrimEnd('\')
  $priorRoot=[IO.Path]::GetFullPath($Receipt.prior_kit_root).TrimEnd('\')
  if ($priorRoot -cne $Receipt.prior_kit_root -or
      -not $priorRoot.StartsWith(($labRoot+'\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Current baseline prior kit path refused' }
  Assert-PreparedSeparateRoots $kitPath $sessionPath
  Assert-PreparedSeparateRoots $priorRoot $sessionPath
  Assert-PreparedBootstrapPath $priorRoot -AllowAbsent
  $priorKit=Read-PreparedJson (Join-Path $priorRoot 'kit.json') $Receipt.prior_kit_sha256
  if ($priorKit.schema_version -ne 1 -or $priorKit.candidate_commit -cne $Receipt.prior_candidate_commit -or
      $priorKit.version -cne $Receipt.prior_candidate_version -or
      $priorKit.baseline_version -cne $Receipt.prior_baseline_version) { throw 'Current baseline prior kit context refused' }
  if ($priorRoot.TrimEnd('\') -ieq $kitPath -and ($Receipt.prior_kit_sha256 -cne $KitDigest -or
      $priorKit.candidate_commit -cne $Kit.candidate_commit -or $priorKit.version -cne $Kit.version -or
      $priorKit.baseline_version -cne $Kit.baseline_version)) { throw 'Current/prior kit identity was not explicitly pinned' }
  return @{root=$priorRoot;kit=$priorKit}
}
function Assert-PreparedDirectoryStreams([string]$Path) {
  if (-not [MarkAutoAcceptanceJob].GetMethod('RequireNoDirectoryDataStreams')) { throw 'Verified helper lacks directory stream admission' }
  try { [MarkAutoAcceptanceJob]::RequireNoDirectoryDataStreams($Path) }
  catch { throw [InvalidOperationException]::new('Current baseline directory stream or metadata refused',$_.Exception) }
}

function Get-PreparedStateInventory([string]$Root, [switch]$RequireUnaliased, [string]$OwnedPointerDigest = '') {
  if ($RequireUnaliased) { Assert-PreparedBootstrapPath $Root -AllowAbsent }
  Assert-AcceptancePath $Root
  if (-not [IO.Directory]::Exists($Root)) { throw 'Prepared data directory missing' }
  if ($RequireUnaliased) { Assert-PreparedDirectoryStreams $Root }
  $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\')
  $pending=New-Object 'System.Collections.Generic.Queue[string]'
  $pending.Enqueue($rootPath)
  $directories=New-Object System.Collections.ArrayList
  $files=@{}; [long]$total=0; $count=0
  while ($pending.Count) {
    $directory=$pending.Dequeue()
    $entries=[IO.Directory]::EnumerateFileSystemEntries($directory).GetEnumerator()
    if ($entries -isnot [Collections.IEnumerator]) { throw 'Inventory enumerator is unavailable' }
    try { while ($entries.MoveNext()) {
      $path=$entries.get_Current()
      if (++$count -gt 4096) { throw 'Prepared test inventory exceeds bounded scope' }
      if ($RequireUnaliased) { Assert-PreparedBootstrapPath $path -AllowAbsent }
      Assert-AcceptancePath $path
      $relative=$path.Substring($rootPath.Length+1).Replace('\','/')
      $attributes=[MarkAutoAcceptanceJob]::PathAttributes($path)
      if ($attributes -eq [uint32]::MaxValue) { throw 'Prepared data changed during inventory' }
      if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) {
        if ($RequireUnaliased -and $relative -cnotin @('cache','control-v1','credentials','logs','state-v1','state-v1/market_cache')) { throw 'Current baseline unknown directory refused' }
        if ($RequireUnaliased) { Assert-PreparedDirectoryStreams $path }
        [void]$directories.Add($relative); $pending.Enqueue($path)
      } else {
        # Do not open, hash, decrypt or copy credential values, even a test receipt's.
        if ($relative -eq 'credentials' -or $relative.StartsWith('credentials/',[StringComparison]::OrdinalIgnoreCase)) { throw 'Credential-bearing state is outside this test phase' }
        $ownedPointer=($RequireUnaliased -and $relative -ceq 'workspace-location.json' -and $OwnedPointerDigest -cmatch '^[a-f0-9]{64}$')
        if ($RequireUnaliased -and -not $ownedPointer -and $relative -cnotin @('.analysis-recovery-admission.lock','installer-preservation-test.txt','state-v1/desktop_safety.json','state-v1/settings.json','workspace-format.json')) { throw 'Current baseline unknown file refused' }
        if ($files.ContainsKey($relative)) { throw 'Ambiguous prepared data name' }
        $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        try {
          if ($RequireUnaliased) { Assert-PreparedUnaliasedFile $stream $path }
          $total += $stream.get_Length()
          if ($total -gt 128MB) { throw 'Prepared test data exceeds bounded backup scope' }
          $hash=[Security.Cryptography.SHA256]::Create()
          try { $files[$relative]=([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
          finally { $hash.Dispose() }
          if ($RequireUnaliased) { Assert-PreparedUnaliasedFile $stream $path }
          if ($ownedPointer) {
            if ($files[$relative] -cne $OwnedPointerDigest) { throw 'Owned workspace pointer changed' }
            $files.Remove($relative)
          }
        } finally { $stream.Dispose() }
      }
    } } finally { $entries.Dispose() }
  }
  return @{directories=@($directories | Sort-Object); files_sha256=$files; total_bytes=$total}
}
function Confirm-PreparedStateInventory($Actual, $Expected) {
  $expectedNames=@($Expected.files_sha256.PSObject.Properties.Name)
  if ($Expected.files_sha256 -is [Collections.IDictionary]) { $expectedNames=@($Expected.files_sha256.Keys) }
  if ($expectedNames.Count -ne $Actual.files_sha256.get_Count() -or
      (@($Expected.directories | Sort-Object) -join "`n") -cne (@($Actual.directories | Sort-Object) -join "`n")) { throw 'Unexplained prepared data entries; originals preserved' }
  foreach ($name in $expectedNames) {
    if (-not $Actual.files_sha256.ContainsKey($name) -or $Actual.files_sha256[$name] -cne $(if ($Expected.files_sha256 -is [Collections.IDictionary]) { $Expected.files_sha256[$name] } else { $Expected.files_sha256.PSObject.Properties[$name].Value })) { throw 'Prepared data digest changed; originals preserved' }
  }
}
function Backup-PreparedState([string]$Root, [string]$Destination, $Expected, [switch]$RequireUnaliased) {
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $Root -RequireUnaliased:$RequireUnaliased) $Expected
  if ($RequireUnaliased) { Assert-PreparedBootstrapPath $Destination -AllowAbsent }
  Assert-AcceptancePath $Destination -RequireAbsent
  [void][IO.Directory]::CreateDirectory($Destination)
  # Names come only from the just-verified actual inventory, never unchecked receipt paths.
  $actual=Get-PreparedStateInventory $Root -RequireUnaliased:$RequireUnaliased
  Confirm-PreparedStateInventory $actual $Expected
  foreach ($relative in $actual.directories) { [void][IO.Directory]::CreateDirectory((Join-Path $Destination $relative)) }
  foreach ($relative in $actual.files_sha256.Keys) {
    $source=Join-Path $Root $relative; $target=Join-Path $Destination $relative
    Assert-AcceptancePath $source; Assert-AcceptancePath $target -RequireAbsent
    $inputStream=[IO.File]::Open($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
      if ($RequireUnaliased) { Assert-PreparedUnaliasedFile $inputStream $source }
      $outputStream=[IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
      try { $inputStream.CopyTo($outputStream); $outputStream.Flush($true); if ($RequireUnaliased) { Assert-PreparedUnaliasedFile $inputStream $source } } finally { $outputStream.Dispose() }
    } finally { $inputStream.Dispose() }
  }
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $Destination -RequireUnaliased:$RequireUnaliased) $Expected
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $Root -RequireUnaliased:$RequireUnaliased) $Expected
}
function Assert-PreparedNoProcess {
  if (Get-Process -Name MarkAuto -ErrorAction SilentlyContinue -ErrorVariable inspectionErrors) { throw 'Another MarkAuto process is present; no process is adopted' }
  foreach ($failure in $inspectionErrors) {
    if ($failure.FullyQualifiedErrorId -notlike 'NoProcessFoundForGivenName,*') { throw 'MarkAuto process inventory failed' }
  }
}
function Read-PreparedJson([string]$Path, [string]$Digest) {
  # Hash and parse the same read-locked stream, never reopen a pinned receipt.
  Assert-AcceptancePath $Path
  return (Read-PreparedBootstrap $Path $Digest 1MB -Text) | ConvertFrom-Json
}
function Test-PreparedNavigation($Owned) {
  # Built-in framework assemblies only. No C# compilation, desktop root or mouse injection.
  $script:preparedUiPhase='load_client'; $script:preparedUiElements=0; $script:preparedUiFound=0; $script:preparedUiSelected=0
  Add-Type -AssemblyName UIAutomationClient
  $script:preparedUiPhase='load_types'
  Add-Type -AssemblyName UIAutomationTypes
  $script:preparedUiPhase='owned_identity'
  Assert-OwnedAcceptanceProcess $Owned
  $Owned.Process.Refresh()
  if ($Owned.Process.get_HasExited()) { throw 'Owned UI exited before inspection' }
  $managed=$Owned.Process.get_Handle()
  if ([MarkAutoAcceptanceJob]::Created($managed) -ne $Owned.Created -or -not [MarkAutoAcceptanceJob]::Owns($AcceptanceJob,$managed)) { throw 'Managed GUI handle differs from retained creation ownership' }
  $hwnd=$Owned.Process.get_MainWindowHandle()
  if ($hwnd -eq [IntPtr]::Zero) { throw 'Owned main window missing' }
  $script:preparedUiPhase='root_from_handle'
  $ui=[Windows.Automation.AutomationElement]::FromHandle($hwnd)
  $script:preparedUiPhase='root_ownership'
  $pidProperty=[Windows.Automation.AutomationElement]::ProcessIdProperty
  $ownedPid=$Owned.Process.get_Id()
  if ($ui.GetCurrentPropertyValue($pidProperty) -ne $ownedPid) { throw 'UI root ownership not proven' }
  $script:preparedUiPhase='visibility'
  if ($ui.GetCurrentPropertyValue([Windows.Automation.AutomationElement]::IsOffscreenProperty) -ne $false) { throw 'Owned application window is not visibly exposed' }
  $navigation=@('市場總覽','資料匯入與更新','AI 策略中心','回測與結果','比較與策略選擇','紙上交易與復原','設定與備份')
  $script:preparedUiPhase='control_metadata'
  $found=@{}; $pending=New-Object 'System.Collections.Generic.Queue[object]'; $pending.Enqueue($ui); $count=0
  while ($pending.Count) {
    $element=$pending.Dequeue()
    if (++$count -gt 512) { throw 'Application UI inventory exceeds bounded scope' }
    $script:preparedUiElements=$count
    $script:preparedUiPhase='descendant_ownership'
    Assert-OwnedAcceptanceProcess $Owned
    if ($element.GetCurrentPropertyValue($pidProperty) -ne $ownedPid) { throw 'UI descendant ownership not proven' }
    $script:preparedUiPhase='control_metadata'
    $control=$element.GetCurrentPropertyValue([Windows.Automation.AutomationElement]::ControlTypeProperty)
    if ($control -eq [Windows.Automation.ControlType]::ListItem) {
      $name=$element.GetCurrentPropertyValue([Windows.Automation.AutomationElement]::NameProperty)
      if ($navigation -ccontains $name) {
        if ($found.ContainsKey($name)) { throw 'Ambiguous application navigation' }
        $found[$name]=$element
        $script:preparedUiFound=$found.Count
      }
    }
    $script:preparedUiPhase='enumerate_children'
    foreach ($child in $element.FindAll([Windows.Automation.TreeScope]::Children,[Windows.Automation.Condition]::TrueCondition)) { $pending.Enqueue($child) }
  }
  $script:preparedUiPhase='required_navigation'
  if ($found.Count -ne $navigation.Count) { return @{status='BLOCKED'; reason='native_provider_did_not_expose_all_navigation'; selected_pages=@()} }
  $selected=New-Object System.Collections.ArrayList
  foreach ($name in $navigation) {
    Assert-OwnedAcceptanceProcess $Owned
    $element=$found[$name]
    if ($element.GetCurrentPropertyValue($pidProperty) -ne $ownedPid) { throw 'Navigation ownership changed' }
    $script:preparedUiPhase='navigation_selection'
    $pattern=$element.GetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern)
    $pattern.Select()
    if ($pattern.get_Current().get_IsSelected() -ne $true) { throw 'Application navigation selection not confirmed' }
    [void]$selected.Add($name)
    $script:preparedUiSelected=$selected.Count
  }
  return @{status='observed'; selected_pages=@($selected); scope='owned application navigation only; no workflow, screenshot or visual-layout acceptance'}
}
# Native regression imports these narrowly scoped routines without running host operations.
if ($MyInvocation.InvocationName -eq '.') { return }
$acceptanceClock=[Diagnostics.Stopwatch]::StartNew()
$global:acceptanceDiagnosticPhase='bootstrap_interactive'
Assert-PreparedInteractiveUser
$global:acceptanceDiagnosticPhase='bootstrap_roots'
foreach ($required in @($KitRoot,$KitSha256,$StateReceipt,$StateReceiptSha256,$SessionRoot)) {
  if ([string]::IsNullOrWhiteSpace($required)) { throw 'Exact kit, pinned state receipt and fresh session directory are required' }
}
$KitRoot=[IO.Path]::GetFullPath($KitRoot)
$SessionRoot=[IO.Path]::GetFullPath($SessionRoot)
Assert-PreparedSeparateRoots $KitRoot $SessionRoot
$lab=[IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'MarkAuto-TestLab')).TrimEnd('\')
foreach ($path in @($KitRoot,$SessionRoot,$StateReceipt,$PSCommandPath)) {
  Assert-PreparedLabContainment $path $lab 'Kit, script, receipt and session evidence must stay in MarkAuto-TestLab'
}
if ('MarkAutoAcceptanceJob' -as [type]) { throw 'Use a fresh PowerShell process; preloaded ownership types cannot prove this kit' }
# Read-only, size-bounded bootstrap; the precompiled helper is the only native dependency.
# No process is created before the private supervisor job. OS/storage must respond.
foreach ($path in @($KitRoot,$StateReceipt,$PSCommandPath)) { Assert-PreparedBootstrapPath $path }
$kit=(Read-PreparedBootstrap (Join-Path $KitRoot 'kit.json') $KitSha256 64KB -Text) | ConvertFrom-Json
$global:acceptanceDiagnosticPhase='bootstrap_helper_load'
$helperStreams=New-Object System.Collections.ArrayList
try {
  foreach ($name in @('packaging/acceptance_process.ps1','packaging/acceptance_process.dll')) {
    if ($acceptanceClock.Elapsed.TotalSeconds -ge 30) { throw 'Read-only bootstrap exceeded its bounded preparation allowance' }
    $digest=$kit.files_sha256.PSObject.Properties[$name].Value
    [void]$helperStreams.Add((Read-PreparedBootstrap (Join-Path $KitRoot $name) $digest 1MB -Hold))
  }
  if ($acceptanceClock.Elapsed.TotalSeconds -ge 30) { throw 'Read-only bootstrap exceeded its bounded preparation allowance' }
  . (Join-Path $KitRoot 'packaging/acceptance_process.ps1')
} finally { foreach ($locked in $helperStreams) { $locked.Dispose() } }
if ($acceptanceClock.Elapsed.TotalSeconds -ge 30) { throw 'Read-only bootstrap exceeded its bounded preparation allowance' }
$global:acceptanceDiagnosticPhase='bootstrap_paths'
foreach ($path in @($KitRoot,$SessionRoot,$StateReceipt,$PSCommandPath)) { Assert-PreparedBootstrapPath $path -AllowAbsent; Assert-AcceptancePath $path }
if ($ReceiptKind -ceq 'CurrentBaseline') {
  $global:acceptanceDiagnosticPhase='bootstrap_prior_context'
  $bootstrapReceipt=Read-PreparedJson $StateReceipt $StateReceiptSha256
  $bootstrapPriorContext=Read-PreparedPriorContext $bootstrapReceipt $kit $KitSha256 $KitRoot $SessionRoot $lab
  if ($acceptanceClock.Elapsed.TotalSeconds -ge 30) { throw 'Read-only bootstrap exceeded its bounded preparation allowance' }
}
if (-not $AcceptanceJob) {
  Assert-AcceptancePath $SessionRoot -RequireAbsent
  [void][IO.Directory]::CreateDirectory($SessionRoot)
  $parameters=@{}; foreach ($key in $PSBoundParameters.Keys) { $parameters[$key]=$PSBoundParameters[$key] }
  $parameters.AcceptanceScope='PreparedHost'
  $code=Invoke-AcceptanceSupervisor -ScriptPath $PSCommandPath -Parameters $parameters -Clock $acceptanceClock -ReportPath (Join-Path $SessionRoot 'supervisor.json') -FailureReportPath (Join-Path $SessionRoot 'session-results.json')
  exit $code
}
$global:acceptanceDiagnosticPhase='worker_membership'
Confirm-AcceptanceWorker $AcceptanceJob
$script:acceptanceProcesses=New-Object System.Collections.ArrayList
$installerLease=$null
$record=@{status='FAILED'; scope='prepared-host follow-on'; client_os_acceptance='BLOCKED'; full_functionality='BLOCKED'; real_ai='NOT RUN'; live_trading='DISABLED'; visual_layout='NOT VERIFIED'; screenshots='NOT CAPTURED'}
try {
  Assert-PreparedInteractiveUser
  $global:acceptanceDiagnosticPhase='client_os'
  $os=Get-CimInstance Win32_OperatingSystem
  if ($os.ProductType -ne 1 -or [int]$os.BuildNumber -lt 19045) { throw 'Requires the authorized Windows client' }
  $global:acceptanceDiagnosticPhase='kit_integrity'
  foreach ($entry in $kit.files_sha256.PSObject.Properties) {
    $path=[IO.Path]::GetFullPath((Join-Path $KitRoot $entry.Name))
    if (-not $path.StartsWith(($KitRoot.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Kit entry escapes its root' }
    Assert-AcceptancePath $path
    if ($entry.Value -cnotmatch '^[a-f0-9]{64}$' -or (Get-PreparedFileSha256 $path) -cne $entry.Value) { throw 'Kit file digest changed' }
  }
  $global:acceptanceDiagnosticPhase='candidate_manifest'
  $candidate=Read-PreparedJson (Join-Path $KitRoot 'candidate-manifest.json') $kit.files_sha256.'candidate-manifest.json'
  if ($kit.schema_version -ne 1 -or $candidate.source_commit -cne $kit.candidate_commit -or $kit.candidate_commit -cnotmatch '^[a-f0-9]{40}$' -or $kit.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid exact candidate provenance' }
  $candidateHelper=($candidate.inputs_sha256.PSObject.Properties | Where-Object { $_.Name.Replace('\','/') -ceq 'packaging/acceptance_process.dll' }).Value
  if ($candidateHelper -cne $kit.files_sha256.'packaging/acceptance_process.dll') { throw 'Kit helper differs from candidate build manifest' }
  $installer=Join-Path $KitRoot "dist/installers/MarkAuto-$($kit.version)-windows-x64-setup.exe"
  $installerDigest=$candidate.artifacts_sha256.PSObject.Properties[(Split-Path $installer -Leaf)].Value
  # Retain the verified installer read lease through creation/execution, not hash then reopen.
  $global:acceptanceDiagnosticPhase='installer_lease'
  $installerLease=Read-PreparedBootstrap $installer $installerDigest 128MB -Hold
  $global:acceptanceDiagnosticPhase='current_receipt'
  $receipt=Read-PreparedJson $StateReceipt $StateReceiptSha256
  $data=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'MarkAuto'
  $currentBaseline=($ReceiptKind -ceq 'CurrentBaseline')
  $app=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\MarkAuto'
  $invocation=$null; $priorKit=$kit; $priorKitRoot=$KitRoot
  if ($currentBaseline) {
    $invocationPath=[IO.Path]::GetFullPath($receipt.lifecycle_invocation_path).TrimEnd('\')
    Assert-PreparedLabContainment $invocationPath $lab 'Current baseline invocation path refused'
    $invocation=Read-PreparedJson $invocationPath $receipt.lifecycle_invocation_sha256
    $priorKitRoot=$bootstrapPriorContext.root; $priorKit=$bootstrapPriorContext.kit
    Confirm-PreparedCurrentBaseline $receipt $kit $KitSha256 $installerDigest (Get-PreparedFileSha256 $PSCommandPath) $KitRoot $data $app $invocation $priorKit
  } elseif ($receipt.schema_version -ne 1 -or $receipt.owner -cne 'prepared-host-lifecycle-handoff' -or $receipt.candidate_commit -cne $kit.candidate_commit -or $receipt.kit_sha256 -cne $KitSha256 -or $receipt.app_data_path -ine $data -or $receipt.no_intervening_app_use -ne $true) { throw 'Observed lifecycle handoff required; existing data cannot be adopted' }
  $global:acceptanceDiagnosticPhase='prior_reports'
  $prior=Join-Path $priorKitRoot 'dist\validation'
  $lifecycle=Read-PreparedJson (Join-Path $prior 'installer-results.json') $receipt.prior_reports_sha256.'installer-results.json'
  $scope=Read-PreparedJson (Join-Path $prior 'installer-scope-preflight.json') $receipt.prior_reports_sha256.'installer-scope-preflight.json'
  $supervisor=Read-PreparedJson (Join-Path $prior 'installer-supervisor.json') $receipt.prior_reports_sha256.'installer-supervisor.json'
  $cases=@('install','bundled-runtime-launch','start-menu-shortcut','desktop-shortcut','version-upgrade','reject-active-upgrade','reject-active-uninstall','native-window-close','uninstall','preserve-user-data')
  if ($lifecycle.status -cne 'partial' -or ($lifecycle.tests -join '|') -cne ($cases -join '|') -or $scope.scope -cne 'PreparedHost' -or $scope.backup_required -ne $false -or $scope.destinations_initially_absent -inotcontains $data -or $supervisor.exit_code -ne 2 -or $supervisor.cleanup_verified -ne $true -or $supervisor.reason -cne 'worker_and_descendants_exit') { throw 'Prior complete bounded partial lifecycle proof required' }
  if ($currentBaseline) {
    foreach ($stage in @('installed','upgraded')) {
      $name='smoke-'+$stage+'.json'
      $proof=Read-PreparedJson (Join-Path $prior $name) $receipt.prior_reports_sha256.PSObject.Properties[$name].Value
      $expectedVersion=if ($stage -ceq 'installed') { $priorKit.baseline_version } else { $priorKit.version }
      if ($proof.status -cne 'passed' -or $proof.version -cne $expectedVersion -or $proof.source_type -cne 'synthetic' -or $proof.generator -cne 'fixture' -or $proof.live_status -cne 'disabled') { throw 'Current baseline prior smoke context refused' }
    }
  }
  if (-not $receipt.files_sha256.PSObject.Properties['installer-preservation-test.txt'] -or $receipt.files_sha256.PSObject.Properties['workspace-location.json']) { throw 'Original sentinel and absent workspace pointer are required' }
  $app=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\MarkAuto'
  $start=Join-Path ([Environment]::GetFolderPath('Programs')) 'Mark Auto\Mark Auto.lnk'
  $desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mark Auto.lnk'
  $global:acceptanceDiagnosticPhase='destinations'
  $destinations=@($app,(Split-Path $start -Parent),$desktop,(Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Mark Auto'),(Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Mark Auto.lnk'))
  foreach ($path in $destinations) {
    if ($currentBaseline -and $path -ceq $app) { Assert-PreparedInstallScaffolding $app $receipt $priorKit $invocation }
    else { Assert-AcceptancePath $path -RequireAbsent }
  }
  $global:acceptanceDiagnosticPhase='process_registration'
  $registryEvidence=@(Assert-AbsentAcceptanceRegistration 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{58788303-95B7-491B-A67A-B1EBA50DA420}_is1')
  Assert-PreparedNoProcess
  $backup=Join-Path $SessionRoot 'prior-data-backup'
  $global:acceptanceDiagnosticPhase='backup'
  Backup-PreparedState $data $backup $receipt -RequireUnaliased:$currentBaseline
  $record.entrypoint_sha256=(Get-PreparedFileSha256 $PSCommandPath)
  $record.receipt_kind=$ReceiptKind; $record.original_lifecycle_continuity=$(if ($currentBaseline) { 'UNPROVEN' } else { 'externally attested lifecycle handoff' })
  $record.backup_verified=$true; $record.state_receipt_sha256=$StateReceiptSha256; $record.candidate_commit=$kit.candidate_commit; $record.kit_sha256=$KitSha256
  $workspace=Join-Path $SessionRoot 'workspace'; $temporary=Join-Path $SessionRoot 'temp'
  # Durable evidence must precede every new workspace/bootstrap/profile mutation.
  $state=Get-PreparedStateInventory $data -RequireUnaliased:$currentBaseline
  Confirm-PreparedStateInventory $state $receipt
  $pointer=Join-Path $data 'workspace-location.json'
  Assert-AcceptancePath $pointer -RequireAbsent
  $preflight=@{schema_version=1;scope='PreparedHost follow-on';status='prepared';
    candidate_commit=$kit.candidate_commit;kit_sha256=$KitSha256;state_receipt_sha256=$StateReceiptSha256;
    entrypoint_sha256=$record.entrypoint_sha256;backup_verified=$true;backup_path=$backup;
    app_data_path=$data;workspace_path=$workspace;temp_path=$temporary;
    file_count=$state.files_sha256.get_Count();directory_count=$state.directories.Count;total_bytes=$state.total_bytes;
    receipt_kind=$ReceiptKind;original_lifecycle_continuity=$record.original_lifecycle_continuity;
    prior_candidate_commit=$priorKit.candidate_commit;prior_kit_root=$priorKitRoot;
    installer_scaffolding_preserved=$currentBaseline;
    destinations_initially_absent=@($destinations | Where-Object { -not $currentBaseline -or $_ -cne $app });registrations_initially_absent=$registryEvidence;
    workspace_pointer_initially_absent=$true;clean_client_acceptance='BLOCKED'}
  $global:acceptanceDiagnosticPhase='preflight_persist'
  $preflightPath=Join-Path $SessionRoot 'preflight.json'
  Assert-AcceptancePath $preflightPath -RequireAbsent
  $preflightBytes=[Text.Encoding]::UTF8.GetBytes(($preflight | ConvertTo-Json -Depth 5))
  $preflightStream=[IO.File]::Open($preflightPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
  try { $preflightStream.Write($preflightBytes,0,$preflightBytes.Length); $preflightStream.Flush($true) }
  finally { $preflightStream.Dispose() }
  $global:acceptanceDiagnosticPhase='mutation_admission'
  foreach ($path in @($workspace,$temporary)) { Assert-AcceptancePath $path -RequireAbsent; [void][IO.Directory]::CreateDirectory($path) }
  $env:TEMP=$temporary; $env:TMP=$temporary
  Assert-PreparedNoProcess
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $data -RequireUnaliased:$currentBaseline) $receipt
  if ($currentBaseline) {
    Confirm-PreparedCurrentBaseline $receipt $kit $KitSha256 $installerDigest $record.entrypoint_sha256 $KitRoot $data $app $invocation $priorKit
    Assert-PreparedInstallScaffolding $app $receipt $priorKit $invocation
  }
  [void](Assert-AbsentAcceptanceRegistration 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{58788303-95B7-491B-A67A-B1EBA50DA420}_is1')
  foreach ($path in @((Split-Path $start -Parent),$desktop,(Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Mark Auto'),(Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Mark Auto.lnk'))) { Assert-AcceptancePath $path -RequireAbsent }
  $pointer=Join-Path $data 'workspace-location.json'
  Assert-AcceptancePath $pointer -RequireAbsent
  $bytes=[Text.Encoding]::UTF8.GetBytes((@{schema_version=1;root=$workspace} | ConvertTo-Json))
  $stream=[IO.File]::Open($pointer,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
  try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
  if ($currentBaseline) {
    $pointerHasher=[Security.Cryptography.SHA256]::Create()
    try { $ownedPointerDigest=([BitConverter]::ToString($pointerHasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() } finally { $pointerHasher.Dispose() }
    Confirm-PreparedStateInventory (Get-PreparedStateInventory $data -RequireUnaliased -OwnedPointerDigest $ownedPointerDigest) $receipt
    Confirm-PreparedStateInventory (Get-PreparedStateInventory $backup -RequireUnaliased) $receipt
    Assert-PreparedInstallScaffolding $app $receipt $priorKit $invocation
    Confirm-PreparedCurrentBaseline $receipt $kit $KitSha256 $installerDigest $record.entrypoint_sha256 $KitRoot $data $app $invocation $priorKit
    Assert-PreparedNoProcess
    [void](Assert-AbsentAcceptanceRegistration 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{58788303-95B7-491B-A67A-B1EBA50DA420}_is1')
    foreach ($path in @((Split-Path $start -Parent),$desktop,(Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Mark Auto'),(Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Mark Auto.lnk'))) { Assert-AcceptancePath $path -RequireAbsent }
  }
  $global:acceptanceDiagnosticPhase='install'
  $owned=Start-OwnedAcceptanceProcess $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$(Join-Path $SessionRoot 'install.log')`"") -WorkingDirectory $temporary
  Wait-OwnedAcceptanceProcess $owned 180000 'Follow-on install timed out' -DrainJob
  if ($owned.Process.get_ExitCode() -ne 0) { throw 'Follow-on install failed' }
  $shell=New-Object -ComObject WScript.Shell
  $shortcut=$shell.CreateShortcut($start); $exe=$shortcut.TargetPath
  Assert-PreparedShortcutContainment $exe $app
  Assert-AcceptancePath $exe
  foreach ($link in @($start,$desktop)) {
    Assert-AcceptancePath $link
    $resolved=$shell.CreateShortcut($link)
    if ($resolved.TargetPath -ine $exe -or $resolved.Arguments -or $resolved.WorkingDirectory -ine (Split-Path $exe -Parent)) { throw 'Shortcut resolution changed' }
  }
  foreach ($name in @('core.py','data.py','strategies.py','backtest.py','research.py','provider.py')) {
    $expected=($candidate.inputs_sha256.PSObject.Properties | Where-Object { $_.Name.Replace('\','/') -ceq "quantlab/$name" }).Value
    $source=Join-Path (Split-Path $exe -Parent) "_internal\quantlab\$name"
    Assert-AcceptancePath $source
    if ((Get-PreparedFileSha256 $source) -cne $expected) { throw 'Installed engine source differs from candidate inputs' }
  }
  $record.install='observed'; $record.shortcut_execution='NOT RUN: exact resolution only'
  Assert-PreparedNoProcess
  $global:acceptanceDiagnosticPhase='synthetic_smoke'
  $smokeReport=Join-Path $SessionRoot 'synthetic-smoke.json'
  $smoke=Start-OwnedAcceptanceProcess $exe -ArgumentList @('--smoke-test',"`"$smokeReport`"") -WorkingDirectory $temporary
  Wait-OwnedAcceptanceProcess $smoke 180000 'Follow-on synthetic functional smoke timed out' -DrainJob
  if ($smoke.Process.get_ExitCode() -ne 0) { throw 'Follow-on synthetic functional smoke failed' }
  $proof=Get-Content -LiteralPath $smokeReport -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($proof.status -cne 'passed' -or $proof.version -cne $kit.version -or $proof.native_window_visible -ne $true -or $proof.worker_completed -ne $true -or [IO.Path]::GetFullPath($proof.data_dir) -ine $workspace -or $proof.steps.Count -ne 7 -or @($proof.steps | Where-Object { $_.passed -ne $true }).Count -ne 0 -or $proof.generator -cne 'fixture' -or $proof.source_type -cne 'synthetic' -or $proof.real_model_status -cne 'not_verified' -or $proof.live_status -cne 'disabled') { throw 'Synthetic functional proof incomplete or scope changed' }
  foreach ($field in @('backtest_completed','campaign_completed','paper_completed')) {
    if ($proof.$field -ne $true) { throw 'Synthetic functional operation missing' }
  }
  $record.synthetic_functional='seven original frozen fixture operations observed; not real AI, market or full UI acceptance'
  Assert-PreparedNoProcess
  $global:acceptanceDiagnosticPhase='native_navigation'
  $gui=Start-OwnedAcceptanceProcess $exe -WorkingDirectory $temporary
  Wait-OwnedAcceptanceWindow $gui
  $record.native_window='observed'
  $record.navigation=Test-PreparedNavigation $gui
  Assert-OwnedAcceptanceProcess $gui
  if (-not $gui.Process.CloseMainWindow()) { throw 'Owned GUI close was not accepted' }
  Wait-OwnedAcceptanceProcess $gui 15000 'Follow-on GUI did not close cleanly' -DrainJob
  if ($gui.Process.get_ExitCode() -ne 0) { throw 'Owned GUI exit failed' }
  Assert-PreparedNoProcess
  $record.clean_close='observed'
  Confirm-PreparedStateInventory (Get-PreparedStateInventory $backup -RequireUnaliased:$currentBaseline) $receipt
  if ((Get-PreparedFileSha256 (Join-Path $data 'installer-preservation-test.txt')) -cne $receipt.files_sha256.'installer-preservation-test.txt') { throw 'First-round sentinel changed' }
  $record.status='partial'; $record.installed_app='left installed, no process left running'; $record.workspace=$workspace
} catch {
  try { Write-AcceptanceWorkerFailure -Failure $_ -Path (Join-Path $SessionRoot 'worker-failure.json') -Source prepared_runtime -Phase $global:acceptanceDiagnosticPhase }
  catch { [Console]::Error.WriteLine('Acceptance worker diagnostic unavailable; primary failure preserved') }
  $record.reason='Prepared-host phase preflight, integrity, UI or owned-process assertion failed'; throw
}
finally {
  $global:acceptanceDiagnosticPhase='owned_cleanup'
  try { Close-AcceptanceProcesses }
  finally {
    if ($installerLease) { $installerLease.Dispose() }
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $SessionRoot 'session-results.json') -Encoding UTF8
  }
}
exit 2
