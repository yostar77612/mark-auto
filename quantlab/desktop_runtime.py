"""Desktop DPAPI credential boundary; secrets resolve only in the HTTP child."""

from __future__ import annotations

import ctypes
from pathlib import Path
import re
import sys
from dataclasses import dataclass
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .runtime_support import (
    WindowsAppMutex as WindowsAppMutex,
    WINDOWS_APP_MUTEX as WINDOWS_APP_MUTEX,
    atomic_write,
)


class CredentialVault:
    """Current-user Windows DPAPI blobs, never plaintext or environment variables.

    The caller must never log the returned value. Backups exclude this directory;
    credentials must be re-entered after account/machine migration.
    """

    def __init__(self, paths):
        self.directory = paths.credentials

    def _path(self, name):
        if sys.platform != 'win32':
            raise RuntimeSafetyError('Credential storage requires Windows DPAPI')
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name):
            raise RuntimeSafetyError('Invalid credential name')
        return self.directory / (name + '.dpapi')

    @staticmethod
    def _crypt(raw, decrypt=False):
        # Load this platform-specific API only on its supported execution path.
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

        buffer = ctypes.create_string_buffer(raw)
        source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        target = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        crypt.CryptProtectData.argtypes = [
            ctypes.POINTER(Blob),
            wintypes.LPCWSTR,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        crypt.CryptProtectData.restype = wintypes.BOOL
        crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        crypt.CryptUnprotectData.restype = wintypes.BOOL
        if decrypt:
            ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
        else:
            ok = crypt.CryptProtectData(ctypes.byref(source), 'MarkAuto credential', None, None, None, 1, ctypes.byref(target))
        try:
            if not ok:
                raise RuntimeSafetyError('Windows credential operation failed')
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            ctypes.memset(buffer, 0, len(buffer))
            if target.pbData:
                ctypes.memset(target.pbData, 0, target.cbData)
                kernel.LocalFree(target.pbData)

    def save(self, name, secret):
        path = self._path(name)
        if not isinstance(secret, str) or not 1 <= len(secret) <= 8192:
            raise RuntimeSafetyError('Credential length invalid')
        atomic_write(path, self._crypt(secret.encode('utf-8')))

    def load(self, name):
        path = self._path(name)
        if not path.exists():
            return None
        if path.stat().st_size > 65536:
            raise RuntimeSafetyError('Invalid credential blob')
        return self._crypt(path.read_bytes(), decrypt=True).decode('utf-8')

    def delete(self, name):
        self._path(name).unlink(missing_ok=True)


@dataclass(frozen=True)
class DesktopCredentialReference:
    """Pickle-safe DPAPI reference; resolves only when the HTTP child calls it."""

    root: str
    name: str = 'model_api_key'

    def __post_init__(self):
        if not isinstance(self.root, str) or not Path(self.root).is_absolute():
            raise RuntimeSafetyError('Credential root must be an absolute app-data path')
        if not isinstance(self.name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.name):
            raise RuntimeSafetyError('Invalid credential name')

    def __call__(self):
        from quantlab.research_core.adapters.workspace_store import AppPaths

        return CredentialVault(AppPaths(Path(self.root))).load(self.name)
