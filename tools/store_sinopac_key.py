"""Store the SinoPac API key pair in Windows Credential Manager for MarkAuto.

Run it yourself in a terminal: the two values are typed or pasted at visible
prompts and are never printed back, logged or written to any file.
"""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

TARGET = 'MarkAuto/v2/broker/sinopac'


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]


_GENERIC, _LOCAL_MACHINE = 1, 2
_MAX_COPIES = 8


def _advapi():
    return ctypes.WinDLL('Advapi32.dll', use_last_error=True)


def _stored(library, target: str) -> tuple[int, int] | None:
    """(persistence, payload size) of the copy Windows currently returns for `target`, or None."""
    pointer = ctypes.POINTER(_Credential)()
    if not library.CredReadW(target, _GENERIC, 0, ctypes.byref(pointer)):
        return None
    try:
        return pointer.contents.Persist, pointer.contents.CredentialBlobSize
    finally:
        library.CredFree(pointer)


def _write(target: str, payload: bytes, library=None) -> None:
    """Replace every stored copy of `target` with one local-machine copy, then prove Windows returns that copy.

    One target name can exist twice: a roaming (enterprise) copy, e.g. one created in the Credential Manager UI or
    by cmdkey, and a local-machine copy. Windows returns whichever its vault loaded last, so a stale empty roaming
    copy came back over a fresh key whenever another program changed a roaming credential (seen 2026-11-20).
    """
    library = library if library is not None else _advapi()
    for _ in range(_MAX_COPIES):
        if not library.CredDeleteW(target, _GENERIC, 0):
            break
    else:
        raise OSError('could not remove the existing copies of ' + target)
    blob = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    cred = _Credential(Type=_GENERIC, TargetName=target, CredentialBlobSize=len(payload), CredentialBlob=blob, Persist=_LOCAL_MACHINE, UserName='sinopac')
    if not library.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error() or 'CredWriteW failed')
    if _stored(library, target) != (_LOCAL_MACHINE, len(payload)):
        raise OSError('Windows does not return the saved copy of ' + target)


def main() -> int:
    api_key = input('貼上 API Key 後按 Enter: ').strip()
    secret_key = input('貼上 Secret Key 後按 Enter: ').strip()
    print(f'收到字數：API Key {len(api_key)} 字，Secret Key {len(secret_key)} 字')
    if len(api_key) < 10 or len(secret_key) < 10:
        print('字數太少，應該沒有貼完整，沒有儲存。請重新執行。')
        return 1
    _write(TARGET, json.dumps({'api_key': api_key, 'secret_key': secret_key}).encode('utf-8'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver

    WindowsSecretResolver().broker_credentials(TARGET)
    print(f'成功：已存入 {TARGET}（舊的重複項目已清除），MarkAuto 讀取驗證通過。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
