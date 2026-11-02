"""Explicit installer handoff after the desktop's normal close has completed.

The helper uses Windows' built-in PowerShell, so it keeps no frozen payload DLLs
open. It waits for the original desktop and refuses any remaining installation
guard. No process is terminated, and no workspace/settings path is written.
"""

import base64
from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from quantlab.runtime_support import WINDOWS_APP_MUTEX
from quantlab.update_check import UpdateError


@dataclass(frozen=True)
class InstallRequest:
    installer: Path
    sha256: str
    install_root: Path
    error_texts: dict[str, str]


_pending: InstallRequest | None = None


def can_install() -> bool:
    """The supported per-user frozen layout is the installer I/O boundary."""
    local = os.environ.get('LOCALAPPDATA')
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False) or not local:
        return False
    executable = Path(sys.executable)
    root = Path(local) / 'Programs' / 'MarkAuto'
    return executable.name == 'MarkAuto.exe' and executable.parent.parent.parent == root / 'payloads'


def queue_install(installer: Path, sha256: str, error_texts: dict[str, str]) -> None:
    """Retain a verified download only after the user explicitly confirmed it."""
    global _pending
    if not can_install():
        raise UpdateError('update_not_installed')
    _pending = InstallRequest(installer, sha256, Path(sys.executable).parents[3], error_texts)


def pending_install() -> bool:
    return _pending is not None


def cancel_pending_install() -> None:
    """Discard only this download, never a payload, workspace, or settings."""
    global _pending
    request, _pending = _pending, None
    if request is not None:
        request.installer.unlink(missing_ok=True)
        # Remove the isolated download folder only when empty.
        request.installer.parent.rmdir()


# Only a base64 JSON object is interpolated; paths/messages never become code.
_HELPER = r'''
$ErrorActionPreference = 'Stop'
$cfg = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CONFIG__')) | ConvertFrom-Json
$code = 'update_parent_timeout'
$exitCode = $null
$stream = $null
$log = Join-Path ([IO.Path]::GetDirectoryName($cfg.installer)) 'install.log'
try {
    try { $parent = [Diagnostics.Process]::GetProcessById([int]$cfg.parentPid) }
    catch [ArgumentException] { $parent = $null }
    if ($null -ne $parent) {
        try { if (-not $parent.WaitForExit([int]$cfg.waitMs)) { throw 'parent-timeout' } }
        finally { $parent.Dispose() }
    }
    $code = 'update_app_running'
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MarkAutoUpdateGuard {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr OpenMutex(uint access, bool inherit, string name);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
'@
    $guard = [MarkAutoUpdateGuard]::OpenMutex(0x00100000, $false, $cfg.mutexName)
    if ($guard -ne [IntPtr]::Zero) {
        [void][MarkAutoUpdateGuard]::CloseHandle($guard)
        throw 'installation-guard-present'
    }
    if ([Runtime.InteropServices.Marshal]::GetLastWin32Error() -ne 2) { throw 'guard-status-unknown' }
    $code = 'update_hash_mismatch'
    # Keep a read-only sharing handle through installation, preventing another
    # writer from replacing the verified executable between hashing and launch.
    $stream = [IO.File]::Open($cfg.installer, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
    if ($actual -cne $cfg.sha256) { throw 'hash-mismatch' }
    $code = 'update_install_start_failed'
    $arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $log + '"'
    $installer = Start-Process -FilePath $cfg.installer -ArgumentList $arguments -WindowStyle Hidden -PassThru
    try {
        $installer.WaitForExit()
        $exitCode = $installer.ExitCode
    } finally { $installer.Dispose() }
    $code = 'update_installer_failed'
    if ($exitCode -ne 0) { throw 'installer-nonzero' }
    $stream.Dispose()
    $stream = $null
    $code = 'update_restart_failed'
    # Inno logs this marker only after validating every new payload file. An
    # exit code of zero is also required before activating the resulting path.
    $verified = @(Get-Content -LiteralPath $log | Select-String 'MARKAUTO_PAYLOAD_VERIFIED=(.+)$')
    if ($verified.Count -ne 1) { throw 'missing-verified-payload' }
    $payload = [IO.Path]::GetFullPath($verified[0].Matches[0].Groups[1].Value.Trim())
    $prefix = [IO.Path]::Combine($cfg.installRoot, 'payloads') + [IO.Path]::DirectorySeparatorChar
    if (-not $payload.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'unexpected-payload' }
    $executable = Join-Path $payload 'MarkAuto.exe'
    if (-not [IO.File]::Exists($executable)) { throw 'missing-installed-executable' }
    Start-Process -FilePath $executable -WorkingDirectory $payload -WindowStyle Normal
    $code = 'installed'
} catch {
    # No exception/OS details or server-controlled strings enter the dialog.
    if ($cfg.showErrors) {
        Add-Type -AssemblyName System.Windows.Forms
        $message = $cfg.errorTexts.$code
        if ($code -eq 'update_installer_failed') { $message = $message -f $exitCode }
        [void][Windows.Forms.MessageBox]::Show($message, 'MarkAuto', 'OK', 'Error')
    }
} finally {
    if ($null -ne $stream) { $stream.Dispose() }
    if ($cfg.resultPath) {
        @{ code = $code; exitCode = $exitCode } | ConvertTo-Json | Set-Content -LiteralPath $cfg.resultPath -Encoding UTF8
    }
    foreach ($path in @($cfg.installer, $log)) {
        if ([IO.File]::Exists($path)) { Remove-Item -LiteralPath $path -Force }
    }
    $directory = [IO.Path]::GetDirectoryName($cfg.installer)
    if ([IO.Directory]::Exists($directory) -and [IO.Directory]::GetFileSystemEntries($directory).Length -eq 0) {
        [IO.Directory]::Delete($directory)
    }
}
if ($code -ne 'installed') { exit 1 }
'''


def _helper_command(
    request: InstallRequest,
    *,
    parent_pid: int,
    mutex_name: str = WINDOWS_APP_MUTEX,
    wait_ms: int = 30000,
    result_path: Path | None = None,
    show_errors: bool = True,
) -> list[str]:
    config = {
        'installer': str(request.installer),
        'sha256': request.sha256,
        'installRoot': str(request.install_root),
        'errorTexts': request.error_texts,
        'parentPid': parent_pid,
        'mutexName': mutex_name,
        'waitMs': wait_ms,
        'resultPath': str(result_path) if result_path else '',
        'showErrors': show_errors,
    }
    encoded = base64.b64encode(json.dumps(config, ensure_ascii=False).encode()).decode('ascii')
    script = _HELPER.replace('__CONFIG__', encoded)
    command = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # EncodedCommand runs local generated text; no execution policy is changed.
    return [str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-EncodedCommand', command]


def launch_pending_install(launch: Callable[[list[str]], object]) -> None:
    """Called only after the normal owned-engine close and guard release."""
    global _pending
    request = _pending
    if request is None:
        return
    command = _helper_command(request, parent_pid=os.getpid())
    launch(command)
    _pending = None
