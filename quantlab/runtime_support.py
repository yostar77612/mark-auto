"""Shared durable I/O and request grammar; no runtime/recovery imports."""

import ctypes
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from .windows_paths import native_path


from quantlab.shared.runtime_errors import RuntimeSafetyError


WINDOWS_APP_MUTEX = r'Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420'


class WindowsAppMutex:
    """Installer-visible lifetime guard; QLockFile still owns single-instance logic."""

    def __init__(self):
        self.handle = None
        if sys.platform == 'win32':
            # Load this platform-specific API only on its supported execution path.
            from ctypes import wintypes

            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.CreateMutexW(None, False, WINDOWS_APP_MUTEX)
            if not self.handle:
                raise RuntimeSafetyError('Cannot establish installation safety guard')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def atomic_write(path, raw, *, durable=False):
    path = native_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if durable:
            _durable_replace(name, path)
        else:
            replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _retry_replace(operation):
    """Retry only the same Windows rename while a short-lived reader releases it.

    No serialization, database commit, admission or research operation is replayed.
    Permanent access denial and exhausted attempts still raise the original error.
    This bound is inside, and does not restart, the caller's existing deadline.
    """
    deadline = time.monotonic() + 0.1
    delays = iter((0.001, 0.002, 0.004, 0.008, 0.016, 0.032))
    while True:
        try:
            return operation()
        except OSError as error:
            if sys.platform != 'win32' or getattr(error, 'winerror', None) not in (5, 32, 33):
                raise
            delay = next(delays, None)
            remaining = deadline - time.monotonic()
            if delay is None or remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            if time.monotonic() >= deadline:
                raise


def replace_file(source, destination):
    """Same atomic replace and path spelling, with bounded Windows contention."""
    source, destination = native_path(source), native_path(destination)
    return _retry_replace(lambda: os.replace(source, destination))


def _sync_directory(path):
    if sys.platform != 'win32':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _durable_replace(source, destination):
    if sys.platform == 'win32':
        source, destination = native_path(source), native_path(destination)
        # Load this platform-specific API only on its supported execution path.
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL

        def promote():
            if not move(str(source), str(destination), 0x1 | 0x8):
                raise ctypes.WinError(ctypes.get_last_error())

        _retry_replace(promote)
    else:
        os.replace(source, destination)
        _sync_directory(Path(destination).parent)
        if Path(source).parent != Path(destination).parent:
            _sync_directory(Path(source).parent)


def validate_analysis_request(request):
    """References only: no model context, credentials or caller-selected budgets."""
    if type(request) is not dict or set(request) != {
        'campaign_reference',
        'original_dataset',
        'attempt_ids',
        'task',
        'registration',
        'model',
        'timeout_seconds',
    }:
        raise RuntimeSafetyError('Invalid analysis request fields')
    for field, length in (('campaign_reference', 64), ('registration', 32)):
        if type(request[field]) is not str or not re.fullmatch('[a-f0-9]{' + str(length) + '}', request[field]):
            raise RuntimeSafetyError('Invalid analysis reference')
    attempts = request['attempt_ids']
    task = request['task']
    if (
        task not in ('critique', 'compare')
        or type(attempts) is not list
        or not (len(attempts) == 1 if task == 'critique' else 2 <= len(attempts) <= 5)
        or any(type(value) is not str or not re.fullmatch('[a-f0-9]{64}', value) for value in attempts)
        or len(set(attempts)) != len(attempts)
    ):
        raise RuntimeSafetyError('Select bounded distinct analysis candidates')
    original = request['original_dataset']
    if type(original) is not dict or set(original) != {'kind', 'path'} or original['kind'] != 'local_dataset_file':
        raise RuntimeSafetyError('Explicit original dataset required')
    path = original['path']
    if (
        type(path) is not str
        or not path
        or len(path) > 4096
        or chr(0) in path
        or '://' in path
        or path.startswith(('//', chr(92) * 2))
        or not Path(path).is_absolute()
        or '..' in Path(path).parts
    ):
        raise RuntimeSafetyError('Explicit local dataset path required')
    if (
        type(request['model']) is not str
        or not re.fullmatch('[A-Za-z0-9._:-]{1,128}', request['model'])
        or type(request['timeout_seconds']) is not int
        or not 1 <= request['timeout_seconds'] <= 120
    ):
        raise RuntimeSafetyError('Invalid analysis model or timeout')
    return request
