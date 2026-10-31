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


def _write(target: str, payload: bytes) -> None:
    blob = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    cred = _Credential(Type=1, TargetName=target, CredentialBlobSize=len(payload), CredentialBlob=blob, Persist=2, UserName='sinopac')
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error() or 'CredWriteW failed')


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
    print(f'成功：已存入 {TARGET}，MarkAuto 讀取驗證通過。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
