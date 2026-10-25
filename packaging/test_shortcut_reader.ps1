# Native metadata-only fixtures. The helper must already be built and loaded.
# Never execute a shortcut/target, resolve it, or create a user Start Menu entry.
function Test-AcceptanceShortcutReader([string]$Root) {
  $suppliedRoot=$Root
  $Root=[IO.Path]::GetFullPath($Root)
  # Expanding a missing leaf can retain its parent's 8.3 name. Expand the
  # existing parent separately before deriving any fixture/expected pathname.
  $parent=[IO.Path]::GetDirectoryName($Root)
  if (-not [IO.Directory]::Exists($parent)) { throw 'Shortcut fixture requires an existing isolated parent' }
  $Root=[IO.Path]::Combine([IO.Path]::GetFullPath($parent),[IO.Path]::GetFileName($Root))
  Assert-AcceptancePath $Root -RequireAbsent
  [void][IO.Directory]::CreateDirectory($Root)
  $target=Join-Path $Root 'MarkAuto.exe'
  $wrongTarget=Join-Path $Root 'different.exe'
  [IO.File]::WriteAllText($target,'INERT FIXTURE: never executable')
  [IO.File]::WriteAllText($wrongTarget,'INERT FIXTURE: never executable')
  $creator=New-Object -ComObject WScript.Shell
  $rows=[Collections.Generic.List[object]]::new()
  $ownedPaths=[Collections.Generic.List[string]]::new()
  $calibrations=[Collections.Generic.List[object]]::new()
  function Confirm-FixtureOwnedHandles([string]$CalibrationPath) {
    [TestOnlyShortcutHandles]::RequireClosed($CalibrationPath)
    $pin=[IO.File]::Open($CalibrationPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
      $count=[TestOnlyShortcutHandles]::CountExact($CalibrationPath)
      if ($count -lt 1) { throw 'Owned-handle positive calibration missed a deliberately pinned file' }
      $closedRefused=$false
      try { [TestOnlyShortcutHandles]::RequireClosed($CalibrationPath) }
      catch {
        $cause=$_.Exception.GetBaseException()
        if ($cause -isnot [InvalidOperationException] -or $cause.Message -cne 'Current-process fixture file handle remains open') { throw }
        $closedRefused=$true
      }
      if (-not $closedRefused) { throw 'Closed-handle assertion admitted a deliberately retained own pin' }
    } finally { $pin.Dispose() }
    [TestOnlyShortcutHandles]::RequireClosed($CalibrationPath)
    [void]$calibrations.Add(@{path=$CalibrationPath;pinned_count=$count;retained_pin_refused=$true;after_dispose_zero=$true})
  }
  function Assert-FixtureOwnedHandlesClosed {
    foreach ($ownedPath in $ownedPaths) { [TestOnlyShortcutHandles]::RequireClosed($ownedPath) }
  }
  try {
    $ascii=Join-Path $Root 'original.lnk'
    $link=$creator.CreateShortcut($ascii)
    try {
      $link.TargetPath=$target; $link.Arguments='--platform-v2'; $link.WorkingDirectory=$Root; $link.Save()
    } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) }
    $sourceHash=(Get-FileHash -LiteralPath $ascii -Algorithm SHA256).Hash
    $names=@('original.lnk',('Mark Auto '+(-join [char[]]@(0x591A,0x5E02,0x5834,0x5E73,0x53F0))+'.lnk'),
      ('outside-ansi-'+[char]::ConvertFromUtf32(0x1F680)+'.lnk'))
    foreach ($name in $names) {
      $path=Join-Path $Root $name
      if ($path -cne $ascii) { [IO.File]::Copy($ascii,$path,$false) }
      if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $sourceHash) { throw 'Unicode fixture bytes changed' }
      [void]$ownedPaths.Add($path)
      Confirm-FixtureOwnedHandles $path
      $metadata=Read-AcceptanceShortcut $path
      if ($metadata.get_TargetPath() -cne $target -or $metadata.get_Arguments() -cne '--platform-v2' -or
          $metadata.get_WorkingDirectory() -cne $Root) { throw 'Unicode reader changed exact original metadata' }
      if ([Runtime.InteropServices.Marshal]::IsComObject($metadata)) { throw 'Mutable COM object escaped the native reader' }
      Assert-FixtureOwnedHandlesClosed
      [void]$rows.Add(@{case=$name;passed=$true;original_path_read=$true;same_bytes=$true;owned_handles_after=0})
    }
    foreach ($fault in @('target','arguments','working_directory')) {
      $path=Join-Path $Root ('wrong-'+$fault+'.lnk')
      $link=$creator.CreateShortcut($path)
      try {
        $link.TargetPath=$(if ($fault -eq 'target') { $wrongTarget } else { $target })
        $link.Arguments=$(if ($fault -eq 'arguments') { '--platform-v1' } else { '--platform-v2' })
        $link.WorkingDirectory=$(if ($fault -eq 'working_directory') { [IO.Path]::GetDirectoryName($Root) } else { $Root })
        $link.Save()
      } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) }
      [void]$ownedPaths.Add($path)
      Confirm-FixtureOwnedHandles $path
      $metadata=Read-AcceptanceShortcut $path
      $accepted=($metadata.get_TargetPath() -ceq $target -and $metadata.get_Arguments() -ceq '--platform-v2' -and
        $metadata.get_WorkingDirectory() -ceq $Root)
      if ($accepted) { throw ('Wrong shortcut '+$fault+' was accepted') }
      Assert-FixtureOwnedHandlesClosed
      [void]$rows.Add(@{case=('wrong-'+$fault);passed=$true;exact_comparison_refused=$true;owned_handles_after=0})
    }
    $corrupt=Join-Path $Root 'corrupt.lnk'
    [IO.File]::WriteAllText($corrupt,'NOT A SHELL LINK')
    [void]$ownedPaths.Add($corrupt)
    $empty=Join-Path $Root 'empty-target.lnk'
    $header=New-Object byte[] 80
    [BitConverter]::GetBytes([uint32]76).CopyTo($header,0)
    ([guid]'00021401-0000-0000-C000-000000000046').ToByteArray().CopyTo($header,4)
    [BitConverter]::GetBytes([uint32]1).CopyTo($header,60)
    [IO.File]::WriteAllBytes($empty,$header)
    [void]$ownedPaths.Add($empty)
    $noncanonical=$Root+'\..\'+[IO.Path]::GetFileName($Root)+'\original.lnk'
    if (-not [IO.File]::Exists($noncanonical) -or [IO.Path]::GetFullPath($noncanonical) -cne $ascii) { throw 'Noncanonical negative must identify the existing original link' }
    foreach ($path in @((Join-Path $Root 'missing.lnk'),$corrupt,$empty,'relative.lnk',$noncanonical,
        ('\\localhost\share\original.lnk'),($ascii+':stream'))) {
      $refused=$false
      $controlPath=if ($path -ceq $corrupt -or $path -ceq $empty) { $path } else { $ascii }
      Confirm-FixtureOwnedHandles $controlPath
      try { [void][MarkAutoAcceptanceJob]::ReadShortcutExact($path) } catch { $refused=$true }
      if (-not $refused) { throw ('Unsafe, missing or empty shortcut admitted: '+$path) }
      Assert-FixtureOwnedHandlesClosed
      [void]$rows.Add(@{case=([IO.Path]::GetFileName($path));passed=$true;reader_refused=$true;owned_handles_after=0;noncanonical_original_refused=($path -ceq $noncanonical)})
    }
    $receipt=@{scope='Native original-path shortcut metadata only; no target execution or lifecycle acceptance';
      supplied_root=$suppliedRoot; canonical_fixture_root=$Root;
      passed=$true;cases=$rows.ToArray();calibrations=$calibrations.ToArray();
      resource_scope='Current-process exact owned fixture handles, not absence of unrelated system readers';
      helper_source='precompiled acceptance_process.dll';compile_during_fixture=$false}
    [IO.File]::WriteAllText((Join-Path $Root 'shortcut-reader-fixture.json'),($receipt|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
  } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($creator) }
}
