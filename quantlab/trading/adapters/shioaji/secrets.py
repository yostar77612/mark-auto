"""Exact-reference Windows Credential Manager access, only after explicit use.

No enumeration, environment-file fallback or credential discovery is provided.
Importing this module never calls the operating system credential APIs.
"""

import ctypes
from ctypes import wintypes
import json
import os
from typing import Protocol

from quantlab.trading.domain.validation import DomainError
from .sdk import BrokerCredentials, CertificateCredentials

PREFIX = 'MarkAuto/v2/'


class CredentialBackend(Protocol):
    def read(self, target: str) -> bytes: ...


class WindowsCredentialBackend:
    def read(self, target: str) -> bytes:
        if os.name != 'nt' or not target.startswith(PREFIX):
            raise DomainError('capability_missing', 'Windows credential reference required')

        class Credential(ctypes.Structure):
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

        pointer = ctypes.POINTER(Credential)()
        library = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        library.CredReadW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential)))
        library.CredReadW.restype = wintypes.BOOL
        library.CredFree.argtypes = (ctypes.c_void_p,)
        library.CredFree.restype = None
        if not library.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            raise DomainError('capability_missing', 'configured credential reference unavailable')
        try:
            count = pointer.contents.CredentialBlobSize
            if not 1 <= count <= 2560:
                raise DomainError('validation_failed', 'credential payload size')
            return ctypes.string_at(pointer.contents.CredentialBlob, count)
        finally:
            library.CredFree(pointer)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


class WindowsSecretResolver:
    def __init__(self, backend: CredentialBackend | None = None) -> None:
        self.backend = backend if backend is not None else WindowsCredentialBackend()

    def _read(self, reference: str, kind: str, fields: frozenset[str]) -> dict[str, str]:
        prefix = PREFIX + kind + '/'
        if not isinstance(reference, str) or not reference.startswith(prefix) or not 1 <= len(reference[len(prefix) :]) <= 80:
            raise DomainError('capability_missing', 'explicit scoped credential reference required')
        suffix = reference[len(prefix) :]
        if not all(char.isascii() and (char.isalnum() or char in ('-', '_')) for char in suffix):
            raise DomainError('validation_failed', 'credential reference characters')
        try:
            raw = self.backend.read(reference)
            if not isinstance(raw, bytes) or not 1 <= len(raw) <= 2560:
                raise ValueError('size')
            # Windows' Generic Credential password UI stores UTF-16LE; API
            # enrollment may use UTF-8. Neither path discovers another target.
            encoding = 'utf-16-le' if b'\0' in raw else 'utf-8-sig'
            value = json.loads(raw.decode(encoding), object_pairs_hook=_pairs)
            if not isinstance(value, dict) or set(value) != fields or any(not isinstance(item, str) or not item for item in value.values()):
                raise ValueError('shape')
        except DomainError:
            raise
        except Exception:
            raise DomainError('capability_missing', 'configured credential payload invalid') from None
        return value

    def broker_credentials(self, reference: str) -> BrokerCredentials:
        value = self._read(reference, 'broker', frozenset(('api_key', 'secret_key')))
        return BrokerCredentials(value['api_key'], value['secret_key'])

    def certificate_credentials(self, reference: str) -> CertificateCredentials:
        value = self._read(reference, 'certificate', frozenset(('ca_path', 'ca_password', 'person_id')))
        return CertificateCredentials(value['ca_path'], value['ca_password'], value['person_id'])
