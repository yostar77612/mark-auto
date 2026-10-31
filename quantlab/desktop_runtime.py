"""Native desktop services. Import is side-effect free; no broker or secret lookup.

State format versions are independent of binary versions. Incompatible state is
never migrated in place, allowing an older installer to be restored safely.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass

from . import __version__
from .windows_paths import canonical_path, native_path
from .runtime_support import (
    WindowsAppMutex as WindowsAppMutex,
    WINDOWS_APP_MUTEX as WINDOWS_APP_MUTEX,
    atomic_write,
    _sync_directory,
)
from quantlab.shared.runtime_errors import RuntimeSafetyError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quantlab.research_core.ports.jobs import JobProcessPort, JobStoragePort
from quantlab.research_core.domain.job_protocol import OPERATIONS, UI_OPERATIONS, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS


def _job_ports(process_port, storage_port):
    # Composition for legacy direct construction; JobManager uses only ports.
    from quantlab.research_core.adapters.job_process import DesktopJobProcess

    # Defer the adapter until this operation runs in its owning process.
    from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage

    return process_port or DesktopJobProcess(), storage_port or WorkspaceJobStorage()


STATE_VERSION = 1
MAX_JSON = 1024 * 1024
MAX_BACKUP = 512 * 1024 * 1024
MAX_FILES = 10000

# UI-owned worker protocol, retained as the default for legacy JobManager(paths)
# callers. This is the sole desktop registrar literal in quantlab. Resolution is
# dynamic so the runtime has no static dependency on a desktop module.


def _json_bytes(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_JSON:
        raise RuntimeSafetyError('JSON size limit exceeded')
    return raw


WORKSPACE_FORMAT = {'kind': 'markauto_workspace', 'schema_version': STATE_VERSION}
REPLAY_REQUIREMENT = {'profile': 'wal_full', 'minimum_runtime': '3.51.3'}
WALK_FORWARD_REQUIREMENT = {'profile': 'wal_full', 'minimum_runtime': '3.51.3'}
GUARDED_BACKUP_VERSION = 2


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


def _verify_replay_runtime(value):
    """Validate the shared WAL runtime requirement for replay and walk-forward."""
    if not {'sqlite_replay', 'sqlite_walk_forward'} & set(value):
        return
    # Keep operation-specific dependencies out of module startup.
    import sqlite3

    # Keep operation-specific dependencies out of module startup.
    from contextlib import closing

    with closing(sqlite3.connect(':memory:')) as connection:
        version = connection.execute('SELECT sqlite_version()').fetchone()[0]
    try:
        actual = tuple(int(part) for part in version.split('.'))
    except (ValueError, AttributeError):
        actual = ()
    if actual != sqlite3.sqlite_version_info or actual < (3, 51, 3):
        raise RuntimeSafetyError('This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)')


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


def _read_json(path):
    path = native_path(path)
    if path.stat().st_size > MAX_JSON:
        raise RuntimeSafetyError('JSON size limit exceeded')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeSafetyError('Invalid JSON; original file preserved') from exc


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


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {}
        value = _read_json(self.path)
        if not isinstance(value, dict) or value.get('schema_version') != STATE_VERSION or not isinstance(value.get('settings'), dict):
            raise RuntimeSafetyError('Unsupported settings version; original preserved')
        return value['settings']

    def save(self, settings):
        if not isinstance(settings, dict):
            raise RuntimeSafetyError('Settings must be a dictionary')
        if self.path.exists():
            self.load()  # Never silently overwrite future/corrupt settings.
        atomic_write(self.path, _json_bytes({'schema_version': STATE_VERSION, 'settings': settings}))


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
        return CredentialVault(AppPaths(Path(self.root))).load(self.name)


class RedactedEventLog:
    """Bounded local status log: only approved operation/status codes, never payloads."""

    MAX_BYTES = 128 * 1024
    EVENTS = frozenset({'started', 'progress', 'result', 'error', 'cancelled'})

    def __init__(self, path):
        self.path = Path(path)

    def append(self, operation, event_type, *, error_code=None):
        # Load the optional UI adapter only when this operation is requested.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        # Defer the adapter until this operation runs in its owning process.
        from .desktop_errors import ERROR_TABLE

        if error_code is not None and (type(error_code) is not str or error_code not in ERROR_TABLE):
            raise RuntimeSafetyError('Only fixed error codes can be logged')
        if operation not in OPERATIONS or event_type not in self.EVENTS:
            raise RuntimeSafetyError('Only fixed operation and event codes can be logged')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            BackupManager._check_regular_path(self.path)
            if self.path.stat().st_size >= self.MAX_BYTES:
                previous = self.path.with_suffix(self.path.suffix + '.1')
                if previous.exists():
                    BackupManager._check_regular_path(previous)
                os.replace(self.path, previous)
        record = {'time': round(time.time(), 3), 'operation': operation, 'event': event_type}
        if error_code is not None:
            record['error_code'] = error_code
        with self.path.open('ab') as stream:
            stream.write(_json_bytes(record) + b'\n')

    def tail(self, limit=200):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.adapters.workspace_backup import BackupManager

        if type(limit) is not int or not 1 <= limit <= 1000:
            raise RuntimeSafetyError('Log limit must be 1..1000')
        if not self.path.exists():
            return []
        BackupManager._check_regular_path(self.path)
        with self.path.open('rb') as stream:
            stream.seek(max(0, self.path.stat().st_size - self.MAX_BYTES))
            lines = stream.read(self.MAX_BYTES + 256).splitlines()
        result = []
        for raw in lines[-limit:]:
            try:
                value = json.loads(raw)
                if not isinstance(value, dict) or set(value) not in ({'time', 'operation', 'event'}, {'time', 'operation', 'event', 'error_code'}):
                    continue
                # Load the optional UI adapter only when this operation is requested.
                from .desktop_errors import ERROR_TABLE

                if 'error_code' in value and (type(value['error_code']) is not str or value['error_code'] not in ERROR_TABLE):
                    continue
                if value['operation'] not in OPERATIONS or value['event'] not in self.EVENTS or type(value['time']) not in (int, float):
                    continue
                result.append(json.dumps(value, ensure_ascii=False))
            except (ValueError, TypeError):
                continue
        return result


class RuntimeGuard:
    """Every startup and clock discontinuity requires explicit paper reconciliation."""

    def __init__(self, paths):
        self.paths = paths
        self.marker = paths.root / 'session.json'
        self.wall, self.mono = time.time(), time.monotonic()
        self.reconciliation_required = True

    def start(self):
        self.paths.ensure()
        unclean = self.marker.exists()
        atomic_write(self.marker, _json_bytes({'pid': os.getpid(), 'started_at': time.time(), 'version': __version__}))
        return unclean

    def check_clock(self):
        wall, mono = time.time(), time.monotonic()
        gap = mono - self.mono
        changed = gap > 15 or gap < 0 or abs((wall - self.wall) - gap) > 5
        self.wall, self.mono = wall, mono
        if changed:
            self.reconciliation_required = True
        return changed

    def finish(self):
        self.marker.unlink(missing_ok=True)


class JobManager:
    """One spawned bounded-IPC task at a time; no arbitrary callable execution."""

    def __init__(self, paths, *, process_port: JobProcessPort | None = None, storage_port: JobStoragePort | None = None):
        self.process_port, self.storage_port = _job_ports(process_port, storage_port)
        self.paths = paths.ensure()
        self.process = self.receiver = self.tree = None
        self.job_id = None
        self._terminal = False
        self._pipe_eof = False
        self._pending = []
        self._deferred = []
        self.event_log = RedactedEventLog(paths.logs / 'desktop-events.jsonl')
        self._operation = None
        self.logging_enabled = True
        self._deadline = None
        self._auth_request_id = None
        self._requires_tree_quiescence = False
        self._subscription_job = False
        self._quiesced_subscription_id = None
        self._analysis_job_identity = None
        self._analysis_result_reference = None
        self._quiesced_analysis = None
        # This proof is deliberately process-local. An on-disk running journal,
        # a caller-provided flag, or a restarted manager cannot establish it.
        self._walk_forward_reference = None
        self._walk_forward_result_reference = None
        self._quiesced_walk_forward = None
        self._tree_quiesced = False

    def _log(self, event_type, *, error_code=None):
        if not self.logging_enabled:
            return
        if event_type == 'error':
            # Normalize untrusted IPC metadata without inspecting exception text.
            from .errors import ERROR_TABLE

            if type(error_code) is not str or error_code not in ERROR_TABLE:
                error_code = 'operation_failed'
        try:
            self.event_log.append(self._operation, event_type, error_code=error_code)
        except (OSError, RuntimeSafetyError):
            pass  # Diagnostic storage cannot break cancellation or task completion.

    @property
    def active(self):
        # A completed child still needs its IPC/result drained before another job.
        return self.process is not None

    def _walk_forward_owner_path(self, reference):
        folder = self.paths.state / 'walk_forward' / reference
        for path in (self.paths.state, folder.parent, folder):
            if path.exists() or path.is_symlink():
                self.storage_port.check_regular_path(path)
                if not path.is_dir():
                    raise RuntimeSafetyError('Invalid walk-forward state directory')
        return folder / '.desktop-run-owner.json'

    def _claim_walk_forward(self, reference, job_id):
        """One original desktop writer, even across concurrent managers/restarts.

        Keep the marker after failure or cancellation; it grants no authority
        by itself and must never turn a failed launch into an evaluation retry.
        """
        owner = self._walk_forward_owner_path(reference)
        owner.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(owner, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RuntimeSafetyError('Walk-forward run already claimed; use read without retry') from exc
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json_bytes({'kind': 'desktop_walk_forward_owner_v1', 'job_id': job_id, 'reference': reference}))
            stream.flush()
            os.fsync(stream.fileno())
        # A pre-existing writer is never adopted as this worker's descendants.
        if (owner.parent / 'walk_forward.sqlite3').exists():
            raise RuntimeSafetyError('Existing walk-forward journals are read-only; use read')

    def _check_walk_forward_owner(self, job_id, reference):
        owner = self._walk_forward_owner_path(reference)
        try:
            self.storage_port.check_regular_path(owner)
            value = _read_json(owner)
        except (OSError, RuntimeSafetyError) as exc:
            raise RuntimeSafetyError('Walk-forward original run ownership cannot be verified') from exc
        if value != {'kind': 'desktop_walk_forward_owner_v1', 'job_id': job_id, 'reference': reference}:
            raise RuntimeSafetyError('Walk-forward original run ownership mismatch')

    def _validate_job_request(self, operation, payload):
        if operation not in OPERATIONS or not isinstance(payload, dict):
            raise RuntimeSafetyError('Unsupported operation')
        _json_bytes(payload)
        # Keep operation-specific dependencies out of module startup.
        from .analysis_recovery import require_operation

        require_operation(self.paths, operation)
        if operation == 'ui_campaign' and (
            not isinstance(payload.get('provider'), dict) or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')
        ):
            raise RuntimeSafetyError('Unsupported model provider; local models and paid API fallback are disabled')
        if operation not in UI_OPERATIONS:
            allowed = {'demo': {'bars'}, 'backtest': {'dataset', 'family'}, 'campaign': {'dataset'}}[operation]
            if set(payload) - allowed:
                raise RuntimeSafetyError('Unsupported job parameters')
            if operation == 'demo' and (type(payload.get('bars', 240)) is not int or not 20 <= payload.get('bars', 240) <= 10000):
                raise RuntimeSafetyError('Demo bars must be 20..10000')

    def _prepare_walk_forward_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_walk_forward_job(self, operation, payload)

    def _prepare_analysis_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_analysis_job(self, operation, payload)

    def _prepare_other_job(self, operation, payload):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.application import job_requests

        return job_requests._prepare_other_job(self, operation, payload)

    def _launch_job_process(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request):
        # Characterization callers may construct the lifecycle with __new__.
        if not hasattr(self, 'process_port'):
            self.process_port, self.storage_port = _job_ports(None, None)
        return self.process_port.launch(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request)

    def _join_descendants(self, pid):
        # Defer the adapter until this operation runs in its owning process.
        from quantlab.research_core.adapters.job_process import DesktopJobProcess

        port = getattr(self, 'process_port', None) or DesktopJobProcess()
        return port.join_descendants(self, pid)

    def start(self, operation, payload):
        if self.active:
            raise RuntimeSafetyError('A job is already running')
        self._validate_job_request(operation, payload)
        deadline = None
        auth_request_id = None
        reconciliation_admitted = False
        analysis_job_identity = None
        analysis_result_reference = None
        walk_forward_reference = None
        walk_forward_result_reference = None
        approved_analysis_plan = None
        helper_nonce = None
        request = None
        if operation in WALK_FORWARD_OPERATIONS:
            deadline, walk_forward_reference, walk_forward_result_reference, reconciliation_admitted = self._prepare_walk_forward_job(operation, payload)
        elif operation in ANALYSIS_OPERATIONS:
            (deadline, analysis_job_identity, analysis_result_reference, approved_analysis_plan, helper_nonce, reconciliation_admitted, request) = (
                self._prepare_analysis_job(operation, payload)
            )
        else:
            deadline, auth_request_id, reconciliation_admitted = self._prepare_other_job(operation, payload)
        job_id = uuid.uuid4().hex
        if walk_forward_reference is not None:
            self.paths.require_walk_forward_wal()
            self._claim_walk_forward(walk_forward_reference, job_id)
        self._analysis_job_identity = analysis_job_identity
        self._analysis_result_reference = analysis_result_reference
        if analysis_job_identity is not None:
            self._quiesced_analysis = None
        self._subscription_job = operation == 'ui_campaign' and payload.get('provider', {}).get('mode') == 'chatgpt_plan'
        if self._subscription_job:
            self._quiesced_subscription_id = None
        self._walk_forward_reference = walk_forward_reference
        self._walk_forward_result_reference = walk_forward_result_reference
        if walk_forward_reference is not None:
            self._quiesced_walk_forward = None
        self._tree_quiesced = False
        self._requires_tree_quiescence = (
            operation in WALK_FORWARD_OPERATIONS
            or operation in ANALYSIS_OPERATIONS
            or operation in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile', 'ui_idea_research')
            or self._subscription_job
        )
        self._operation = operation
        self._deadline = deadline
        self._auth_request_id = auth_request_id
        self._launch_job_process(operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request)
        return self.job_id

    def poll(self):
        events, self._pending = self._pending, []
        if not self.active:
            return events

        try:
            self.process_port.drain(self, events)
            exited = not self.process.is_alive()
            if not exited and self._deadline is not None and time.monotonic() >= self._deadline:
                terminal = self._terminal
                self.cancel()  # Stops/joins the whole tree before releasing the slot.
                pending, self._pending = self._pending, []
                events.extend(event for event in pending if event.get('type') != 'cancelled')
                if not terminal:
                    events.append(
                        {
                            'job_id': self.job_id,
                            'type': 'error',
                            'message': '背景作業超過期限並已停止；遠端完成／額度可能未知，禁止自動重送或退還。',
                            'error_type': 'DeadlineExceeded',
                        }
                    )
                return events
            if exited:
                self.process.join()
                # The child can send and exit between initial poll and liveness
                # check. Drain once more before classifying an incomplete stream.
                self.process_port.drain(self, events)
        except (OSError, ValueError):
            self.cancel()
            events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker response rejected'})
            return events
        if exited:
            if self._requires_tree_quiescence:
                self._join_descendants(self.process.pid)
                self._tree_quiesced = True
            if not self._terminal:
                self._log('error')
                events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker stopped unexpectedly; incomplete output retained as partial'})
            self._release()
            events.extend(self._deferred)
            self._deferred = []
        return events

    def _release(self):
        ownership_error = None
        if self._walk_forward_reference is not None and self._tree_quiesced:
            try:
                self._check_walk_forward_owner(self.job_id, self._walk_forward_reference)
            except Exception as exc:
                # The subtree is already joined. Release its handles even when
                # journal ownership is corrupt, but never grant recovery proof.
                ownership_error = exc
        if self.tree:
            self.tree.close()
        self.tree = None
        if self.receiver:
            self.receiver.close()
        self.receiver = None
        if self.process:
            self.process.close()
        self.process = None
        self._gate = None
        self._deadline = None
        self._auth_request_id = None
        if self._analysis_job_identity is not None and self._tree_quiesced:
            self._quiesced_analysis = (self.job_id, *self._analysis_job_identity)
        if self._subscription_job:
            self._quiesced_subscription_id = self.job_id
        if self._walk_forward_reference is not None and self._tree_quiesced and ownership_error is None:
            self._quiesced_walk_forward = (self.job_id, self._walk_forward_reference)
        if self._operation == 'ui_backup_restore':
            self.storage_port.recover(self.paths)
        if ownership_error is not None:
            raise ownership_error

    def cancel(self):
        if not self.active:
            return
        proc = self.process
        self.process_port.stop(self)
        if self._requires_tree_quiescence:
            self._join_descendants(proc.pid)
            self._tree_quiesced = True
        if self._terminal:
            # A terminal outcome already received is authoritative even if the
            # process still needed cleanup. Never relabel a failure as cancelled.
            self._pending.extend(self._deferred)
            self._deferred = []
        else:
            self._log('cancelled')
            self._pending.append({'job_id': self.job_id, 'type': 'cancelled', 'message': 'Cancelled; completed durable records are preserved'})
        self._release()

    def close(self):
        self.cancel()
