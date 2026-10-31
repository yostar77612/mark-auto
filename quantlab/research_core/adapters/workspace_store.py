"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import stat
import sys
import tempfile
from dataclasses import dataclass
from quantlab.windows_paths import canonical_path, native_path
from quantlab.runtime_support import atomic_write, _sync_directory
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import STATE_VERSION, _json_bytes, _read_json
from .settings_store import SettingsStore
from .runtime_safety import _verify_replay_runtime


WORKSPACE_FORMAT = {'kind': 'markauto_workspace', 'schema_version': STATE_VERSION}


REPLAY_REQUIREMENT = {'profile': 'wal_full', 'minimum_runtime': '3.51.3'}


WALK_FORWARD_REQUIREMENT = {'profile': 'wal_full', 'minimum_runtime': '3.51.3'}


GUARDED_BACKUP_VERSION = 2


MAX_BACKUP = 512 * 1024 * 1024


MAX_FILES = 10000


def _workspace_format(value):
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int:
        raise RuntimeSafetyError('Unsupported workspace version; original preserved')
    if value == WORKSPACE_FORMAT:
        return value
    requirements = {'sqlite_replay': REPLAY_REQUIREMENT, 'sqlite_walk_forward': WALK_FORWARD_REQUIREMENT}
    extras = set(value) - set(WORKSPACE_FORMAT)
    if (
        set(WORKSPACE_FORMAT) <= set(value)
        and extras
        and extras <= set(requirements)
        and {key: value[key] for key in WORKSPACE_FORMAT} == WORKSPACE_FORMAT
        and all(value[key] == requirements[key] for key in extras)
    ):
        return value
    raise RuntimeSafetyError('Unsupported workspace version; original preserved')


def _marker_stream(marker):
    marker = native_path(marker)
    if sys.platform != 'win32':
        return marker.open('wb')
    # WRITE_THROUGH also flushes NTFS metadata for a newly created marker.
    # FlushFileBuffers via os.fsync below remains the explicit WAL barrier.
    import msvcrt

    # Load this platform-specific API only on its supported execution path.
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(marker), 0x40000000, 0, None, 2, 0x80000000 | 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(fd, 'wb')


def _write_workspace_format(root, value):
    """Flush the existing inode before any WAL access; torn writes fail closed.

    Do not replace an existing marker: retaining its durable directory entry
    avoids relying on rename durability for the compatibility barrier.
    """
    # Defer the adapter until this operation runs in its owning process.
    from quantlab.research_core.adapters.workspace_backup import BackupManager

    value = _workspace_format(value)
    marker = Path(root) / 'workspace-format.json'
    if marker.exists() or marker.is_symlink():
        BackupManager._check_regular_path(marker)
    raw = _json_bytes(value)
    with _marker_stream(marker) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(root)


@dataclass(frozen=True)
class AppPaths:
    root: Path
    bootstrap: Path | None = None

    def __post_init__(self):
        object.__setattr__(self, 'root', native_path(self.root))
        if self.bootstrap is not None:
            object.__setattr__(self, 'bootstrap', native_path(self.bootstrap))

    @classmethod
    def discover(cls):
        if sys.platform == 'win32':
            # SHGetFolderPathW avoids writing to Program Files or trusting cwd.
            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, buf) != 0:
                raise RuntimeSafetyError('Cannot locate Windows Local AppData')
            return cls(Path(buf.value) / 'MarkAuto')
        return cls(Path.home() / '.local' / 'share' / 'MarkAuto')

    @property
    def state(self):
        return native_path(self.root / 'state-v1')

    @property
    def cache(self):
        return native_path(self.root / 'cache')

    @property
    def logs(self):
        return self.root / 'logs'

    @property
    def controls(self):
        # Irreversible provider reservations and examined-holdout history must
        # survive workspace switching and restoring older research backups.
        return (self.bootstrap or self.root) / 'control-v1'

    @property
    def credentials(self):
        return (self.bootstrap or self.root) / 'credentials'

    def ensure(self):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        marker = self.root / 'workspace-format.json'
        if marker.exists() or marker.is_symlink():
            BackupManager._check_regular_path(marker)
            _verify_replay_runtime(_workspace_format(_read_json(marker)))
        for path in (self.root, self.state, self.cache, self.logs, self.credentials, self.controls):
            path.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            _write_workspace_format(self.root, WORKSPACE_FORMAT)
        return self

    def _require_wal(self, key, requirement):
        self.ensure()
        current = _workspace_format(_read_json(self.root / 'workspace-format.json'))
        required = {**current, key: requirement}
        _verify_replay_runtime(required)
        _write_workspace_format(self.root, required)
        return self

    def require_replay_wal(self):
        return self._require_wal('sqlite_replay', REPLAY_REQUIREMENT)

    def require_walk_forward_wal(self):
        return self._require_wal('sqlite_walk_forward', WALK_FORWARD_REQUIREMENT)


class WorkspaceLocator:
    """Fixed per-user bootstrap pointer; configuration applies on next startup.

    Changing this pointer never moves, merges, deletes or overwrites workspace
    contents. Credentials and the single-instance lock stay in the bootstrap.
    """

    def __init__(self, bootstrap):
        self.bootstrap = Path(bootstrap)
        self.pointer = self.bootstrap / 'workspace-location.json'

    @property
    def lock_path(self):
        return self.bootstrap / 'desktop.lock'

    @staticmethod
    def _protected_windows_locations():
        if sys.platform != 'win32':
            return []
        buffer = ctypes.create_unicode_buffer(32768)
        result = []
        if not ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer)):
            raise RuntimeSafetyError('Cannot validate Windows system directory')
        result.append(Path(buffer.value))
        for identifier in (0x0026, 0x002A, 0x0023):  # Program Files, x86, ProgramData
            if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer) == 0:
                result.append(Path(buffer.value))
        return result

    def _validate(self, value, *, probe=False):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise RuntimeSafetyError('Workspace path is required')
        text = str(value)
        path = Path(value)
        if not path.is_absolute() or text.startswith(('\\', '//')) or path == Path(path.anchor):
            raise RuntimeSafetyError('Choose an absolute local folder, not a drive root or network share')
        path = native_path(path)
        for ancestor in (path, *path.parents):
            if ancestor.exists() or ancestor.is_symlink():
                info = ancestor.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise RuntimeSafetyError('Workspace path cannot contain symlinks or reparse points')
        resolved = canonical_path(path.resolve())
        if sys.platform == 'win32':
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor))
            if drive_type in (0, 1, 4):
                raise RuntimeSafetyError('Workspace must be on an available local drive')
            for part in resolved.parts[1:]:
                BackupManager._safe_name(part)
        for protected in self._protected_windows_locations():
            if resolved.is_relative_to(protected.resolve()):
                raise RuntimeSafetyError('Workspace cannot use a system or Program Files directory')
        # Do not let a new workspace enclose the fixed bootstrap/vault.
        bootstrap = canonical_path(self.bootstrap.resolve())
        if resolved != bootstrap and bootstrap.is_relative_to(resolved):
            raise RuntimeSafetyError('Workspace cannot contain the fixed application bootstrap')
        for protected in (
            self.bootstrap / 'credentials',
            self.bootstrap / 'state-v1',
            self.bootstrap / 'cache',
            self.bootstrap / 'logs',
            self.bootstrap / 'control-v1',
        ):
            if resolved.is_relative_to(canonical_path(protected.resolve())):
                raise RuntimeSafetyError('Choose a standalone workspace, not an internal application directory')
        if path.exists():
            if not path.is_dir():
                raise RuntimeSafetyError('Workspace must be a directory')
            for child_name in ('workspace-format.json', 'state-v1', 'cache', 'logs'):
                child = path / child_name
                if child.exists() or child.is_symlink():
                    BackupManager._check_regular_path(child)
            contents = list(path.iterdir())
            marker = path / 'workspace-format.json'
            if contents and resolved != bootstrap:
                if not marker.is_file():
                    raise RuntimeSafetyError('Choose an empty folder or a compatible MarkAuto workspace')
            if marker.exists():
                _verify_replay_runtime(_workspace_format(_read_json(marker)))
            settings = path / 'state-v1' / 'settings.json'
            if settings.exists():
                BackupManager._check_regular_path(settings)
                SettingsStore(settings).load()
        if probe:
            path.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.markauto-write-probe-', dir=path)
            os.close(fd)
            os.unlink(temporary)
        return resolved

    def configure(self, next_root):
        if self.pointer.exists():
            value = _read_json(self.pointer)
            if (
                not isinstance(value, dict)
                or set(value) != {'schema_version', 'root'}
                or value['schema_version'] != STATE_VERSION
                or not isinstance(value['root'], str)
            ):
                raise RuntimeSafetyError('Unsupported workspace pointer; original preserved')
        destination = self._validate(next_root, probe=True)
        self.bootstrap.mkdir(parents=True, exist_ok=True)
        atomic_write(self.pointer, _json_bytes({'schema_version': STATE_VERSION, 'root': str(destination)}))
        return destination

    def load(self, *, probe=True):
        # Smoke may inspect settings without creating a workspace or write probe.
        # Ordinary startup retains its existing writable-workspace validation.
        if not self.pointer.exists():
            return AppPaths(self.bootstrap, self.bootstrap)
        value = _read_json(self.pointer)
        if (
            not isinstance(value, dict)
            or set(value) != {'schema_version', 'root'}
            or value['schema_version'] != STATE_VERSION
            or not isinstance(value['root'], str)
        ):
            raise RuntimeSafetyError('Unsupported workspace pointer; original preserved')
        root = self._validate(value['root'], probe=probe)
        return AppPaths(root, self.bootstrap)
