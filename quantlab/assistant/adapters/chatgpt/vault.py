"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

from quantlab.assistant.domain.auth_protocol import AuthError
from quantlab.assistant.domain.auth_protocol import MAX_RECORD
from pathlib import Path
from quantlab.assistant.domain.auth_protocol import _bytes
from quantlab.assistant.domain.auth_protocol import _json
from quantlab.assistant.domain.auth_protocol import _validate_record
from contextlib import contextmanager
import stat
import sys
import threading
import time


class DPAPIVault:
    """Windows-only installation-local vault, outside restorable workspace state.

    Bootstrap must be the original installation app-data root, never a selected
    workspace. A missing record is never recreated except through explicit
    ``initialize_host``. ACL hardening and DPAPI require Windows validation.
    """

    def __init__(self, bootstrap):
        root = Path(bootstrap)
        if not root.is_absolute():
            raise AuthError('absolute_bootstrap_required')
        if '..' in root.parts:
            raise AuthError('invalid_bootstrap')
        self.directory = root / 'credentials' / 'chatgpt-oauth-v1'
        self.path = self.directory / 'accounts.dpapi'
        self.host_marker = root / 'chatgpt-oauth-host-v1.marker'
        self._thread_lock = threading.RLock()

    def _windows(self):
        if sys.platform != 'win32':
            raise AuthError('windows_dpapi_required')

    @staticmethod
    def _check_path(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise AuthError('vault_reparse_point')

    def _prepare(self):
        self._windows()
        for ancestor in (self.directory, *self.directory.parents):
            self._check_path(ancestor)
        # Restrict DACL to current user using their actual process-token SID.
        import ctypes
        from ctypes import wintypes

        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = wintypes.HANDLE()
        size = wintypes.DWORD()
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        adv.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        sid = wintypes.LPWSTR()
        descriptor = ctypes.c_void_p()
        try:
            if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(handle)):
                raise AuthError('vault_acl_failed')
            adv.GetTokenInformation(handle, 1, None, 0, ctypes.byref(size))
            data = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(handle, 1, data, size, ctypes.byref(size)):
                raise AuthError('vault_acl_failed')
            sid_pointer = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
            if not adv.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid)):
                raise AuthError('vault_acl_failed')
            if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;OICI;FA;;;' + sid.value + ')', 1, ctypes.byref(descriptor), None):
                raise AuthError('vault_acl_failed')
            self.directory.mkdir(parents=True, exist_ok=True)
            for p in (self.directory, self.path, self.directory / 'vault.lock'):
                self._check_path(p)
                if p.exists():
                    if not adv.SetFileSecurityW(str(p), 0x80000004, descriptor):
                        raise AuthError('vault_acl_failed')
        finally:
            if descriptor:
                kernel.LocalFree(descriptor)
            if sid:
                kernel.LocalFree(sid)
            if handle:
                kernel.CloseHandle(handle)

    @contextmanager
    def lock(self):
        self._prepare()
        import msvcrt

        with self._thread_lock:
            with (self.directory / 'vault.lock').open('a+b') as stream:
                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise AuthError('vault_busy') from None
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def load(self):
        self._windows()
        self._check_path(self.path)
        if not self.path.exists():
            return None
        if self.path.is_symlink() or self.path.stat().st_size > MAX_RECORD:
            raise AuthError('invalid_vault')
        from quantlab.desktop_runtime import CredentialVault

        try:
            raw = CredentialVault._crypt(self.path.read_bytes(), decrypt=True)
            return _validate_record(_json(raw))
        except Exception:
            raise AuthError('vault_read_failed') from None

    def assert_first_use(self):
        # A missing credential file is not sufficient evidence of first use.
        root = self.directory.parent.parent
        evidence = (self.host_marker, root / 'chatgpt-plan-controls-v1.marker')
        for path in evidence:
            self._check_path(path)
            if path.exists():
                raise AuthError('explicit_host_recovery_required')
        # Partial vault writes/backups are evidence too. The lock alone is
        # created by local status reads and carries no account information.
        if self.directory.exists():
            for index, path in enumerate(self.directory.iterdir()):
                if index >= 64 or path.name != 'vault.lock':
                    raise AuthError('explicit_host_recovery_required')
        controls = root / 'control-v1'
        self._check_path(controls)
        if controls.exists():
            for index, path in enumerate(controls.iterdir()):
                if index >= 1024 or path.name.casefold().startswith(('chatgpt-plan-', 'chatgpt-analysis-')):
                    raise AuthError('explicit_host_recovery_required')

    def save(self, record):
        self._windows()
        raw = _bytes(_validate_record(record))
        from quantlab.desktop_runtime import CredentialVault, atomic_write

        try:
            encrypted = CredentialVault._crypt(raw)
            if len(encrypted) > MAX_RECORD:
                raise AuthError('record_size')
            self._check_path(self.host_marker)
            atomic_write(self.path, encrypted)
            atomic_write(self.host_marker, b'markauto-chatgpt-host-v1\n')
        except Exception:
            raise AuthError('vault_write_failed') from None
