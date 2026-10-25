"""Protect only the generated local IPC key; never discover financial secrets."""

import ctypes
from ctypes import wintypes
import os


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, encrypt: bool) -> bytes:
    if os.name != 'nt':
        return value  # Unix session file and socket are owner-only (0600).
    source = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    blob, result = _Blob(len(value), source), _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(blob), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), 'local control key protection failed')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)


def protect(value: bytes) -> bytes:
    return _crypt(value, True)


def unprotect(value: bytes) -> bytes:
    return _crypt(value, False)
