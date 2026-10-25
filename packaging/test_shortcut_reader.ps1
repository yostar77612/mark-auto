# Native metadata-only fixtures. The helper must already be built and loaded.
# Never execute a shortcut/target, resolve it, or create a user Start Menu entry.
function Test-AcceptanceShortcutReader([string]$Root) {
  Assert-AcceptancePath $Root -RequireAbsent
  [void][IO.Directory]::CreateDirectory($Root)
  $target=Join-Path $Root 'MarkAuto.exe'
  $wrongTarget=Join-Path $Root 'different.exe'
  [IO.File]::WriteAllText($target,'INERT FIXTURE: never executable')
  [IO.File]::WriteAllText($wrongTarget,'INERT FIXTURE: never executable')
  $creator=New-Object -ComObject WScript.Shell
  $rows=[Collections.Generic.List[object]]::new()
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
      $metadata=Read-AcceptanceShortcut $path
      if ($metadata.get_TargetPath() -cne $target -or $metadata.get_Arguments() -cne '--platform-v2' -or
          $metadata.get_WorkingDirectory() -cne $Root) { throw 'Unicode reader changed exact original metadata' }
      $exclusive=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
      $exclusive.Dispose()
      [void]$rows.Add(@{case=$name;passed=$true;original_path_read=$true;same_bytes=$true;exclusive_reopen=$true})
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
      $metadata=Read-AcceptanceShortcut $path
      $accepted=($metadata.get_TargetPath() -ceq $target -and $metadata.get_Arguments() -ceq '--platform-v2' -and
        $metadata.get_WorkingDirectory() -ceq $Root)
      if ($accepted) { throw ('Wrong shortcut '+$fault+' was accepted') }
      $exclusive=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
      $exclusive.Dispose()
      [void]$rows.Add(@{case=('wrong-'+$fault);passed=$true;exact_comparison_refused=$true;exclusive_reopen=$true})
    }
    $corrupt=Join-Path $Root 'corrupt.lnk'
    [IO.File]::WriteAllText($corrupt,'NOT A SHELL LINK')
    $empty=Join-Path $Root 'empty-target.lnk'
    $header=New-Object byte[] 80
    [BitConverter]::GetBytes([uint32]76).CopyTo($header,0)
    ([guid]'00021401-0000-0000-C000-000000000046').ToByteArray().CopyTo($header,4)
    [BitConverter]::GetBytes([uint32]1).CopyTo($header,60)
    [IO.File]::WriteAllBytes($empty,$header)
    foreach ($path in @((Join-Path $Root 'missing.lnk'),$corrupt,$empty,'relative.lnk',
        ('\\localhost\share\original.lnk'),($ascii+':stream'))) {
      $refused=$false
      try { [void][MarkAutoAcceptanceJob]::ReadShortcutExact($path) } catch { $refused=$true }
      if (-not $refused) { throw ('Unsafe, missing or empty shortcut admitted: '+$path) }
      [void]$rows.Add(@{case=([IO.Path]::GetFileName($path));passed=$true;reader_refused=$true})
    }
    foreach ($path in @($corrupt,$empty)) {
      $exclusive=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
      $exclusive.Dispose()
    }
    $receipt=@{scope='Native original-path shortcut metadata only; no target execution or lifecycle acceptance';
      passed=$true;cases=$rows.ToArray();helper_source='precompiled acceptance_process.dll';compile_during_fixture=$false}
    [IO.File]::WriteAllText((Join-Path $Root 'shortcut-reader-fixture.json'),($receipt|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
  } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($creator) }
}
