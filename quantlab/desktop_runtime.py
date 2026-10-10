"""Native desktop services. Import is side-effect free; no broker or secret lookup.

State format versions are independent of binary versions. Incompatible state is
never migrated in place, allowing an older installer to be restored safely.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass

from . import __version__

STATE_VERSION = 1
MAX_JSON = 1024 * 1024
MAX_BACKUP = 512 * 1024 * 1024
MAX_FILES = 10000


class RuntimeSafetyError(ValueError):
    pass


def _json_bytes(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_JSON:
        raise RuntimeSafetyError('JSON size limit exceeded')
    return raw


def atomic_write(path, raw, *, durable=False):
    path = Path(path)
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
            os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)



WORKSPACE_FORMAT = {'kind': 'markauto_workspace', 'schema_version': STATE_VERSION}
REPLAY_REQUIREMENT = {'profile': 'wal_full', 'minimum_runtime': '3.51.3'}
GUARDED_BACKUP_VERSION = 2


def _workspace_format(value):
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int:
        raise RuntimeSafetyError('Unsupported workspace version; original preserved')
    if value == WORKSPACE_FORMAT:
        return value
    if (isinstance(value, dict) and set(value) == set(WORKSPACE_FORMAT) | {'sqlite_replay'}
            and {key: value[key] for key in WORKSPACE_FORMAT} == WORKSPACE_FORMAT
            and value['sqlite_replay'] == REPLAY_REQUIREMENT):
        return value
    raise RuntimeSafetyError('Unsupported workspace version; original preserved')


def _verify_replay_runtime(value):
    if 'sqlite_replay' not in value:
        return
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(':memory:')) as connection:
        version = connection.execute('SELECT sqlite_version()').fetchone()[0]
    try:
        actual = tuple(int(part) for part in version.split('.'))
    except (ValueError, AttributeError):
        actual = ()
    if actual != sqlite3.sqlite_version_info or actual < (3, 51, 3):
        raise RuntimeSafetyError('This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)')


def _sync_directory(path):
    if sys.platform != 'win32':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _durable_replace(source, destination):
    if sys.platform == 'win32':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, destination)
        _sync_directory(Path(destination).parent)
        if Path(source).parent != Path(destination).parent:
            _sync_directory(Path(source).parent)


def _marker_stream(marker):
    if sys.platform != 'win32':
        return marker.open('wb')
    # WRITE_THROUGH also flushes NTFS metadata for a newly created marker.
    # FlushFileBuffers via os.fsync below remains the explicit WAL barrier.
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
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
    path = Path(path)
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

    @classmethod
    def discover(cls):
        if sys.platform == 'win32':
            # SHGetFolderPathW avoids writing to Program Files or trusting cwd.
            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001c, None, 0, buf) != 0:
                raise RuntimeSafetyError('Cannot locate Windows Local AppData')
            return cls(Path(buf.value) / 'MarkAuto')
        return cls(Path.home() / '.local' / 'share' / 'MarkAuto')

    @property
    def state(self):
        return self.root / 'state-v1'

    @property
    def cache(self):
        return self.root / 'cache'

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
        marker = self.root / 'workspace-format.json'
        if marker.exists() or marker.is_symlink():
            BackupManager._check_regular_path(marker)
            _verify_replay_runtime(_workspace_format(_read_json(marker)))
        for path in (self.root, self.state, self.cache, self.logs, self.credentials, self.controls):
            path.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            _write_workspace_format(self.root, WORKSPACE_FORMAT)
        return self

    def require_replay_wal(self):
        self.ensure()
        required = {**WORKSPACE_FORMAT, 'sqlite_replay': REPLAY_REQUIREMENT}
        _verify_replay_runtime(required)
        _write_workspace_format(self.root, required)
        return self


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
        for identifier in (0x0026, 0x002a, 0x0023):  # Program Files, x86, ProgramData
            if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer) == 0:
                result.append(Path(buffer.value))
        return result

    def _validate(self, value, *, probe=False):
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise RuntimeSafetyError('Workspace path is required')
        text = str(value)
        path = Path(value)
        if not path.is_absolute() or text.startswith(('\\', '//')) or path == Path(path.anchor):
            raise RuntimeSafetyError('Choose an absolute local folder, not a drive root or network share')
        for ancestor in (path, *path.parents):
            if ancestor.exists() or ancestor.is_symlink():
                info = ancestor.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise RuntimeSafetyError('Workspace path cannot contain symlinks or reparse points')
        resolved = path.resolve()
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
        if resolved != self.bootstrap.resolve() and self.bootstrap.resolve().is_relative_to(resolved):
            raise RuntimeSafetyError('Workspace cannot contain the fixed application bootstrap')
        for protected in (self.bootstrap / 'credentials', self.bootstrap / 'state-v1', self.bootstrap / 'cache', self.bootstrap / 'logs', self.bootstrap / 'control-v1'):
            if resolved.is_relative_to(protected.resolve()):
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
            if contents and resolved != self.bootstrap.resolve():
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
            if not isinstance(value, dict) or set(value) != {'schema_version', 'root'} or value['schema_version'] != STATE_VERSION or not isinstance(value['root'], str):
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
        if not isinstance(value, dict) or set(value) != {'schema_version', 'root'} or value['schema_version'] != STATE_VERSION or not isinstance(value['root'], str):
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
        crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        crypt.CryptProtectData.restype = wintypes.BOOL
        crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
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


WINDOWS_APP_MUTEX = r'Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420'


class WindowsAppMutex:
    """Installer-visible lifetime guard; QLockFile still owns single-instance logic."""
    def __init__(self):
        self.handle = None
        if sys.platform == 'win32':
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


class RedactedEventLog:
    """Bounded local status log: only approved operation/status codes, never payloads."""
    MAX_BYTES = 128 * 1024
    EVENTS = frozenset({'started', 'progress', 'result', 'error', 'cancelled'})

    def __init__(self, path):
        self.path = Path(path)

    def append(self, operation, event_type):
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
        with self.path.open('ab') as stream:
            stream.write(_json_bytes(record) + b'\n')

    def tail(self, limit=200):
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
                if not isinstance(value, dict) or set(value) != {'time', 'operation', 'event'}:
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


class BackupManager:
    """Quiescent-only, bounded, hash-verified state backups; no secret/cache files.

    Fixed-bootstrap credentials and control-v1 audit ledgers are excluded.
    Restoring research state must never reset spend reservations or the history
    of examined holdouts; those irreversible controls remain in their original
    per-user location across workspace switches and backup restoration.

    Restore uses a same-volume staging directory and recovery marker. A crash
    between the two directory renames is recovered on next startup.
    """
    def __init__(self, paths, jobs=None):
        self.paths, self.jobs = paths, jobs

    def _quiescent(self):
        if self.jobs is not None and self.jobs.active:
            raise RuntimeSafetyError('Stop active jobs before backup or restore')

    def recover(self):
        self._quiescent()
        rollback = self.paths.root / 'state-v1.rollback'
        journal = self.paths.root / 'restore-transaction.json'
        token = self.paths.state / '.restore-transaction'
        transaction = None
        if journal.exists():
            try:
                value = _read_json(journal)
                if isinstance(value, dict) and value.get('phase') in ('prepared', 'committed') and isinstance(value.get('id'), str) and re.fullmatch(r'[a-f0-9]{32}', value['id']):
                    transaction = value
            except (OSError, ValueError):
                pass  # Unknown journal is never evidence that rollback is disposable.
        verified_commit = False
        if transaction and transaction['phase'] == 'committed' and token.is_file():
            try:
                verified_commit = _read_json(token) == {'id': transaction['id']}
            except (OSError, ValueError):
                pass
        had_rollback = rollback.exists()
        if had_rollback:
            self._check_regular_path(rollback)
            if verified_commit:
                # Promotion identity and durable commit marker both agree.
                shutil.rmtree(rollback)
            else:
                if self.paths.state.exists():
                    self._check_regular_path(self.paths.state)
                    # Never delete an ambiguous directory, even if another callback
                    # recreated it during the interrupted two-rename window.
                    preserved = self.paths.root / ('state-v1.interrupted-' + uuid.uuid4().hex)
                    _durable_replace(self.paths.state, preserved)
                _durable_replace(rollback, self.paths.state)
        # Only a verified promotion can remove a WAL requirement. A real
        # pre-upgrade snapshot is old-binary compatible again after commit.
        if transaction and (had_rollback or verified_commit) and 'prior_format' in transaction and 'restored_format' in transaction:
            selected = transaction['restored_format'] if verified_commit else transaction['prior_format']
            _write_workspace_format(self.paths.root, _workspace_format(selected))
        # Retire the promoted token before its journal. A crash in this order
        # leaves only a harmless journal, never an orphan token in a new backup.
        token = self.paths.state / '.restore-transaction'
        if verified_commit and token.exists():
            token.unlink()
        if journal.exists():
            journal.unlink()
        # Unknown partial staging directories are intentionally preserved for
        # diagnosis rather than guessed to be disposable user data.

    @staticmethod
    def _safe_name(name):
        parts = PurePosixPath(name).parts
        if not name or '\\' in name or ':' in name or name.startswith('/') or any(p in ('.', '..') or p.endswith((' ', '.')) for p in parts) or '/'.join(parts) != name:
            raise RuntimeSafetyError('Unsafe backup path')
        if any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I) for p in parts):
            raise RuntimeSafetyError('Reserved Windows backup path')
        return name

    @staticmethod
    def _check_regular_path(path):
        info = Path(path).lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeSafetyError('Symlinks and Windows reparse points cannot be backed up')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise RuntimeSafetyError('Hard-linked files cannot be backed up')

    def create(self, destination):
        self._quiescent()
        destination = Path(destination).resolve()
        # Validate before recovery/ensure: even a rejected destination must not
        # alter journals, locks, vaults or irreversible accounting controls.
        # Keep archives outside both the active workspace and fixed bootstrap;
        # this also protects future internal files without a brittle allowlist.
        for root in (self.paths.root, self.paths.bootstrap or self.paths.root):
            if destination.is_relative_to(Path(root).resolve()):
                raise RuntimeSafetyError('Backup must be outside workspace and application bootstrap directories')
        self.recover()
        self.paths.ensure()
        files, size = [], 0
        self._check_regular_path(self.paths.state)
        state_root = self.paths.state.resolve()
        for folder, directories, filenames in os.walk(self.paths.state, followlinks=False):
            for name in directories + filenames:
                path = Path(folder) / name
                self._check_regular_path(path)
                if not path.resolve().is_relative_to(state_root):
                    raise RuntimeSafetyError('Backup entry leaves state directory')
            for filename in sorted(filenames):
                path = Path(folder) / filename
                if not path.is_file():
                    raise RuntimeSafetyError('Unsupported backup file')
                name = self._safe_name(path.relative_to(self.paths.state).as_posix())
                if name == '.restore-transaction':
                    continue  # Internal control token, including legacy crash orphans.
                size += path.stat().st_size
                files.append((name, path))
                if size > MAX_BACKUP or len(files) > MAX_FILES:
                    raise RuntimeSafetyError('Backup size limit exceeded')
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destination.parent, suffix='.zip.tmp')
        os.close(fd)
        try:
            workspace_format = _workspace_format(_read_json(self.paths.root / 'workspace-format.json'))
            manifest = {'schema_version': STATE_VERSION, 'app_version': __version__, 'files': {}}
            if 'sqlite_replay' in workspace_format:
                manifest.update(schema_version=GUARDED_BACKUP_VERSION, workspace_format=workspace_format)
            with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, path in files:
                    self._check_regular_path(path)
                    raw = path.read_bytes()
                    manifest['files'][name] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                    archive.writestr('state/' + name, raw)
                archive.writestr('manifest.json', _json_bytes(manifest))
            os.replace(tmp, destination)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return destination

    def restore(self, source):
        self._quiescent()
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.recover()
        staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=self.paths.root))
        try:
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                names = [i.filename for i in infos]
                if len(infos) > MAX_FILES + 1 or len(set(n.casefold() for n in names)) != len(names) or sum(i.file_size for i in infos) > MAX_BACKUP:
                    raise RuntimeSafetyError('Backup size or duplicate-entry violation')
                for info in infos:
                    self._safe_name(info.filename)
                    if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                        raise RuntimeSafetyError('Unsupported archive entry')
                if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > MAX_JSON:
                    raise RuntimeSafetyError('Missing or oversized backup manifest')
                manifest = json.loads(archive.read('manifest.json'))
                if not isinstance(manifest, dict) or manifest.get('schema_version') not in (STATE_VERSION, GUARDED_BACKUP_VERSION) or not isinstance(manifest.get('files'), dict):
                    raise RuntimeSafetyError('Incompatible backup state version')
                restored_format = WORKSPACE_FORMAT
                if manifest['schema_version'] == GUARDED_BACKUP_VERSION:
                    restored_format = _workspace_format(manifest.get('workspace_format'))
                    _verify_replay_runtime(restored_format)
                    if 'sqlite_replay' not in restored_format:
                        raise RuntimeSafetyError('Guarded backup is missing its runtime requirement')
                elif 'workspace_format' in manifest:
                    raise RuntimeSafetyError('Unexpected backup runtime requirement')
                entries = manifest['files']
                if set(names) != {'manifest.json'} | {'state/' + n for n in entries}:
                    raise RuntimeSafetyError('Manifest does not match archive')
                for name, expected in entries.items():
                    self._safe_name(name)
                    if name == '.restore-transaction':
                        raise RuntimeSafetyError('Backup contains a reserved restore control file')
                    raw = archive.read('state/' + name)
                    if not isinstance(expected, dict) or len(raw) != expected.get('size') or hashlib.sha256(raw).hexdigest() != expected.get('sha256'):
                        raise RuntimeSafetyError('Backup hash mismatch')
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(target, raw, durable=True)
            settings = staging / 'settings.json'
            if settings.exists():
                BackupManager._check_regular_path(settings)
                SettingsStore(settings).load()
            rollback = self.paths.root / 'state-v1.rollback'
            journal = self.paths.root / 'restore-transaction.json'
            self.paths.ensure()
            prior_format = _workspace_format(_read_json(self.paths.root / 'workspace-format.json'))
            # Guard before promotion; never inspect or open SQLite during restore.
            if 'sqlite_replay' in restored_format:
                _write_workspace_format(self.paths.root, restored_format)
            transaction_id = uuid.uuid4().hex
            formats = {'prior_format': prior_format, 'restored_format': restored_format}
            atomic_write(staging / '.restore-transaction', _json_bytes({'id': transaction_id}), durable=True)
            atomic_write(journal, _json_bytes({'id': transaction_id, 'phase': 'prepared', **formats}), durable=True)
            try:
                if self.paths.state.exists():
                    _durable_replace(self.paths.state, rollback)
                _durable_replace(staging, self.paths.state)
                atomic_write(journal, _json_bytes({'id': transaction_id, 'phase': 'committed', **formats}), durable=True)
            except BaseException:
                self.recover()
                raise
            self.recover()
        finally:
            if staging.exists():
                shutil.rmtree(staging)


UI_OPERATIONS = frozenset({
    'ui_local_ai', 'ui_demo', 'ui_import', 'ui_refresh', 'ui_market_refresh', 'ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile', 'ui_backtest', 'ui_campaign',
    'ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read', 'ui_walk_forward_reconcile',
    'ui_compare', 'ui_select', 'ui_disable', 'ui_paper_snapshot',
    'ui_paper_reconcile', 'ui_paper_kill', 'ui_paper_replay',
    'ui_paper_submit', 'ui_paper_cancel', 'ui_backup_create', 'ui_backup_restore',
})
OPERATIONS = UI_OPERATIONS | {'demo', 'backtest', 'campaign'}
WALK_FORWARD_OPERATIONS = frozenset({
    'ui_walk_forward_preview', 'ui_walk_forward_run',
    'ui_walk_forward_read', 'ui_walk_forward_reconcile',
})


def _job_worker(sender, gate, operation, payload, root, bootstrap, job_id,
                reconciliation_admitted=False):
    if sys.platform != 'win32':
        os.setsid()
    if not gate.wait(15):
        return
    def emit(kind, **values):
        sender.send_bytes(_json_bytes({'job_id': job_id, 'type': kind, **values}))
    try:
        emit('progress', message='Working', progress=0)
        paths = AppPaths(Path(root), Path(bootstrap) if bootstrap else None)
        if operation in UI_OPERATIONS:
            from desktop_ui import execute_ui_operation
            result = execute_ui_operation(operation, payload, paths, emit=emit,
                descendants_stopped=reconciliation_admitted is True and operation in (
                    'ui_chatgpt_reconcile', 'ui_walk_forward_reconcile'))
        else:
            from argparse import Namespace
            from .__main__ import execute
            stage = paths.state / 'runs' / (job_id + '.partial')
            stage.mkdir(parents=True, exist_ok=False)
            args = {'command': operation, 'output': stage, **payload}
            if 'dataset' in args:
                args['dataset'] = Path(args['dataset'])
            args.setdefault('config', None)
            args.setdefault('family', 'trend')
            args.setdefault('bars', 240)
            execute(Namespace(**args))
            final = stage.with_suffix('')
            os.replace(stage, final)
            result = {'output': str(final)}
        from .core import to_dict
        result = to_dict(result)
        try:
            _json_bytes(result)
        except RuntimeSafetyError:
            result = {'output': str(paths.state), 'summary': 'Completed; detailed results exceed the IPC display limit and remain on disk'}
        emit('result', result=result, message='Completed', progress=100)
    except BaseException as exc:
        # Do not echo exception text: providers/files may include credentials.
        categories = {'ValidationError': '輸入驗證失敗，請檢查資料、設定與紙上帳戶對帳', 'FileNotFoundError': '找不到所需檔案，請重新選取資料', 'PermissionError': '檔案存取遭拒，請檢查路徑及檔案是否被占用', 'RuntimeSafetyError': '安全檢查未通過，請檢查備份版本或作業狀態'}
        emit('error', message=categories.get(type(exc).__name__, '作業失敗；既有資料已保留，請檢查輸入後重試'), error_type=type(exc).__name__)
    finally:
        sender.close()


class _WindowsProcessTree:
    """Kill-on-close job object. Child waits until assigned; grandchildren inherit."""
    def __init__(self, pid):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Counters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeSafetyError('Cannot create worker isolation job')
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        child = k.OpenProcess(0x0100 | 0x0001, False, pid)
        try:
            if not child or not k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not k.AssignProcessToJobObject(self.handle, child):
                self.close()
                raise RuntimeSafetyError('Cannot isolate worker process tree')
        finally:
            if child:
                k.CloseHandle(child)

    def stop_and_join(self):
        """Keep the Job handle until Windows confirms all descendants exited."""
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')] + [(name,w.DWORD) for name in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]
        k = self.kernel
        k.TerminateJobObject.argtypes = [w.HANDLE,w.UINT]
        k.QueryInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
        if not self.handle or not k.TerminateJobObject(self.handle,1):
            raise RuntimeSafetyError('Cannot stop worker process tree')
        deadline = time.monotonic()+6
        while True:
            info = Accounting()
            if not k.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):
                raise RuntimeSafetyError('Cannot verify worker process tree')
            if info.ActiveProcesses == 0: return
            if time.monotonic() >= deadline: raise RuntimeSafetyError('Worker descendants still active')
            time.sleep(.02)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def validate_walk_forward_request(plan_payload, saved_source=None):
    """Read-only desktop grammar; an unadmitted saved plan cannot carry DSL.

    The temporary builtin plan checks only chronology, costs and resource types.
    Its one-slot budget is never used to run an experiment or displayed as consent.
    The worker restores the explicit saved budget after authoritative admission.
    """
    from .core import ValidationError
    from .walk_forward import walk_forward_plan_from_dict
    if not isinstance(plan_payload, dict):
        raise ValidationError('Explicit walk-forward plan required')
    saved = plan_payload.get('pool_origin', 'exact_builtin_pool') == 'saved_campaign_pool'
    if not saved:
        if saved_source is not None:
            raise ValidationError('Built-in and saved pools cannot be mixed')
        return walk_forward_plan_from_dict(plan_payload)
    if 'candidate_pool' in plan_payload or 'pool_admission' in plan_payload:
        raise ValidationError('Saved candidates must be admitted from local source records')
    if (not isinstance(saved_source, dict) or set(saved_source) != {'campaign_reference', 'original_dataset'}
        or type(saved_source['campaign_reference']) is not str
        or not re.fullmatch(r'[0-9a-f]{64}', saved_source['campaign_reference'])):
        raise ValidationError('Explicit immutable source campaign reference required')
    original = saved_source['original_dataset']
    if (not isinstance(original, dict) or set(original) != {'kind', 'path'}
        or original['kind'] != 'local_dataset_file'):
        raise ValidationError('Explicit local original dataset file reference required')
    path = original['path']
    if (type(path) is not str or not path or len(path) > 4096 or '\0' in path
        or '://' in path or path.startswith(('//', '\\\\'))
        or not Path(path).is_absolute() or '..' in Path(path).parts):
        raise ValidationError('Original dataset must be an explicitly selected local absolute file path')
    budget = plan_payload.get('max_evaluations')
    if type(budget) is not int or not 1 <= budget <= 620:
        raise ValidationError('Saved-pool evaluation budget must be explicitly set within 1..620')
    template = {**plan_payload, 'pool_origin': 'exact_builtin_pool', 'max_evaluations': 1}
    return walk_forward_plan_from_dict(template)


class JobManager:
    """One spawned bounded-IPC task at a time; no arbitrary callable execution."""
    def __init__(self, paths):
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
        # This proof is deliberately process-local. An on-disk running journal,
        # a caller-provided flag, or a restarted manager cannot establish it.
        self._walk_forward_reference = None
        self._walk_forward_result_reference = None
        self._quiesced_walk_forward = None
        self._tree_quiesced = False

    def _log(self, event_type):
        if not self.logging_enabled:
            return
        try:
            self.event_log.append(self._operation, event_type)
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
                BackupManager._check_regular_path(path)
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
            stream.write(_json_bytes({'kind': 'desktop_walk_forward_owner_v1',
                'job_id': job_id, 'reference': reference}))
            stream.flush()
            os.fsync(stream.fileno())
        # A pre-existing writer is never adopted as this worker's descendants.
        if (owner.parent / 'walk_forward.sqlite3').exists():
            raise RuntimeSafetyError('Existing walk-forward journals are read-only; use read')

    def _check_walk_forward_owner(self, job_id, reference):
        owner = self._walk_forward_owner_path(reference)
        try:
            BackupManager._check_regular_path(owner)
            value = _read_json(owner)
        except (OSError, RuntimeSafetyError) as exc:
            raise RuntimeSafetyError('Walk-forward original run ownership cannot be verified') from exc
        if value != {'kind': 'desktop_walk_forward_owner_v1', 'job_id': job_id, 'reference': reference}:
            raise RuntimeSafetyError('Walk-forward original run ownership mismatch')

    def start(self, operation, payload):
        if self.active:
            raise RuntimeSafetyError('A job is already running')
        if operation not in OPERATIONS or not isinstance(payload, dict):
            raise RuntimeSafetyError('Unsupported operation')
        _json_bytes(payload)
        if operation not in UI_OPERATIONS:
            allowed = {'demo': {'bars'}, 'backtest': {'dataset', 'family'}, 'campaign': {'dataset'}}[operation]
            if set(payload) - allowed:
                raise RuntimeSafetyError('Unsupported job parameters')
            if operation == 'demo' and (type(payload.get('bars', 240)) is not int or not 20 <= payload.get('bars', 240) <= 10000):
                raise RuntimeSafetyError('Demo bars must be 20..10000')
        deadline = None
        auth_request_id = None
        reconciliation_admitted = False
        walk_forward_reference = None
        walk_forward_result_reference = None
        if operation == 'ui_local_ai':
            action = payload.get('action')
            allowed = {'action', 'consent', 'runtime_archive', 'model_file'} if action == 'install' else ({'action', 'consent', 'owner'} if action == 'probe' else {'action', 'consent'})
            if action not in ('install', 'download', 'serve', 'probe') or set(payload) != allowed or payload.get('consent') is not True:
                raise RuntimeSafetyError('Invalid explicit local AI request')
            deadline = time.monotonic() + {'install': 300, 'download': 2100, 'serve': 8*60*60+150, 'probe': 135}[action]
        elif operation in WALK_FORWARD_OPERATIONS:
            allowed = {
                'ui_walk_forward_preview': {'plan'},
                'ui_walk_forward_run': {'plan', 'preview_identity'},
                'ui_walk_forward_read': {'reference'},
                'ui_walk_forward_reconcile': {'reference', 'stopped_job_id'},
            }[operation]
            if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run') and 'saved_source' in payload:
                if not isinstance(payload.get('plan'), dict) or payload['plan'].get('pool_origin') != 'saved_campaign_pool':
                    raise RuntimeSafetyError('Built-in and saved pools cannot be mixed')
                allowed = allowed | {'saved_source'}
            if set(payload) != allowed:
                raise RuntimeSafetyError('Unsupported walk-forward job parameters')
            if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run'):
                if not isinstance(payload['plan'], dict):
                    raise RuntimeSafetyError('Explicit walk-forward plan required')
                from .core import ValidationError
                try:
                    plan = validate_walk_forward_request(payload['plan'], payload.get('saved_source'))
                except (ValidationError, TypeError, KeyError) as exc:
                    raise RuntimeSafetyError('Invalid bounded walk-forward plan') from exc
                if operation == 'ui_walk_forward_run':
                    walk_forward_reference = payload['preview_identity']
                    walk_forward_result_reference = walk_forward_reference
                    deadline = time.monotonic() + plan.max_runtime_seconds + 10
            else:
                walk_forward_result_reference = payload['reference']
            if operation != 'ui_walk_forward_preview':
                if not isinstance(walk_forward_result_reference, str) or not re.fullmatch(r'[0-9a-f]{64}', walk_forward_result_reference):
                    raise RuntimeSafetyError('Invalid walk-forward reference')
            if operation == 'ui_walk_forward_run':
                journal = self.paths.state / 'walk_forward' / walk_forward_reference / 'walk_forward.sqlite3'
                if journal.exists() or journal.is_symlink():
                    # A new reader's process stop is not proof about an older
                    # journal writer. Never mint recovery authority by reopening.
                    raise RuntimeSafetyError('Existing walk-forward journals are read-only; use read')
            if operation == 'ui_walk_forward_reconcile':
                if (not self._quiesced_walk_forward
                    or (payload['stopped_job_id'], payload['reference']) != self._quiesced_walk_forward):
                    raise RuntimeSafetyError('Matching walk-forward subtree stop proof required')
                self._check_walk_forward_owner(payload['stopped_job_id'], payload['reference'])
                reconciliation_admitted = True
            if deadline is None:
                deadline = time.monotonic() + 60
        elif operation == 'ui_chatgpt_auth':
            request = payload.get('request')
            if set(payload) != {'request'} or not isinstance(request, dict):
                raise RuntimeSafetyError('Invalid authentication request')
            allowed = {'request_id', 'action', 'registration', 'max_runtime_seconds', 'user_confirmed'}
            if set(request) != allowed or type(request['request_id']) is not int or request['request_id'] < 1 or type(request['max_runtime_seconds']) is not int or not 1 <= request['max_runtime_seconds'] <= 600:
                raise RuntimeSafetyError('Invalid bounded authentication request')
            auth_request_id = request['request_id']
            deadline = time.monotonic() + request['max_runtime_seconds'] + 5
        elif operation in ('ui_chatgpt_usage','ui_chatgpt_reconcile'):
            if operation == 'ui_chatgpt_reconcile' and (not self._quiesced_subscription_id or payload.get('stopped_job_id') != self._quiesced_subscription_id):
                raise RuntimeSafetyError('Subscription subtree stop proof required')
            reconciliation_admitted = operation == 'ui_chatgpt_reconcile'
            deadline = time.monotonic() + 60
        elif operation == 'ui_campaign' and payload.get('provider', {}).get('mode') in ('chatgpt_plan', 'local'):
            seconds = payload.get('config', {}).get('max_runtime_seconds')
            if type(seconds) is not int or not 1 <= seconds <= 7200:
                raise RuntimeSafetyError('Explicit bounded subscription campaign required')
            deadline = time.monotonic() + seconds + 10
        job_id = uuid.uuid4().hex
        if walk_forward_reference is not None:
            self._claim_walk_forward(walk_forward_reference, job_id)
        self._subscription_job = operation == 'ui_campaign' and payload.get('provider',{}).get('mode') == 'chatgpt_plan'
        if self._subscription_job: self._quiesced_subscription_id = None
        self._walk_forward_reference = walk_forward_reference
        self._walk_forward_result_reference = walk_forward_result_reference
        if walk_forward_reference is not None:
            self._quiesced_walk_forward = None
        self._tree_quiesced = False
        self._requires_tree_quiescence = (operation == 'ui_campaign' and payload.get('provider', {}).get('mode') == 'local') or operation == 'ui_local_ai' or operation in WALK_FORWARD_OPERATIONS or operation in ('ui_chatgpt_auth','ui_chatgpt_usage','ui_chatgpt_reconcile') or self._subscription_job
        self._operation = operation
        self._deadline = deadline
        self._auth_request_id = auth_request_id
        context = mp.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        gate = context.Event()
        self._gate = gate
        self.job_id = job_id
        self._terminal = False
        self._pipe_eof = False
        self._deferred = []
        self.process = context.Process(target=_job_worker, args=(sender, gate, operation, payload, str(self.paths.root), str(self.paths.bootstrap) if self.paths.bootstrap else None, self.job_id, reconciliation_admitted))
        self.receiver = receiver
        try:
            self.process.start()
            sender.close()
            if sys.platform == 'win32':
                self.tree = _WindowsProcessTree(self.process.pid)
            gate.set()
            self._log('started')
        except BaseException:
            sender.close()
            self.cancel()
            raise
        return self.job_id

    def poll(self):
        events, self._pending = self._pending, []
        if not self.active:
            return events

        def drain():
            for _ in range(16):
                # The protocol ends at its terminal packet. Windows PeekNamedPipe
                # raises ERROR_BROKEN_PIPE after sender close, unlike POSIX poll.
                if self._terminal or self._pipe_eof:
                    return
                try:
                    if not self.receiver.poll():
                        return
                    raw = self.receiver.recv_bytes(MAX_JSON)
                except EOFError:
                    self._pipe_eof = True
                    return
                except OSError as exc:
                    if getattr(exc, 'winerror', None) == 109:  # ERROR_BROKEN_PIPE
                        self._pipe_eof = True
                        return
                    raise  # Invalid handles, oversized packets, etc. fail closed.
                event = json.loads(raw)
                if not isinstance(event, dict) or event.get('job_id') != self.job_id or event.get('type') not in {'progress', 'result', 'error', 'auth_progress'}:
                    raise RuntimeSafetyError('Invalid worker response')
                if event['type'] == 'result' and self._walk_forward_result_reference is not None:
                    result = event.get('result')
                    if not isinstance(result, dict) or result.get('reference') != self._walk_forward_result_reference:
                        raise RuntimeSafetyError('Walk-forward worker reference mismatch')
                if event['type'] == 'auth_progress':
                    auth_event = event.get('auth_event')
                    allowed = {'request_id','kind','state','registrations','active_registration','authorization_url','error_code','revocation_confirmed','models'}
                    if self._operation != 'ui_chatgpt_auth' or not isinstance(auth_event, dict) or set(auth_event) - allowed or auth_event.get('request_id') != self._auth_request_id or auth_event.get('kind') not in ('authorization', 'progress'):
                        raise RuntimeSafetyError('Invalid private authentication event')
                    # Transient OAuth query data must never enter persistent logs.
                else:
                    self._log(event['type'])
                if event['type'] in {'result', 'error'}:
                    self._terminal = True
                    self._deferred.append(event)
                else:
                    events.append(event)

        try:
            drain()
            exited = not self.process.is_alive()
            if not exited and self._deadline is not None and time.monotonic() >= self._deadline:
                terminal = self._terminal
                self.cancel()  # Stops/joins the whole tree before releasing the slot.
                pending, self._pending = self._pending, []
                events.extend(event for event in pending if event.get('type') != 'cancelled')
                if not terminal:
                    events.append({'job_id': self.job_id, 'type': 'error', 'message': '背景作業超過期限並已停止；遠端完成／額度可能未知，禁止自動重送或退還。', 'error_type': 'DeadlineExceeded'})
                return events
            if exited:
                self.process.join()
                # The child can send and exit between initial poll and liveness
                # check. Drain once more before classifying an incomplete stream.
                drain()
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
        if self._subscription_job:
            self._quiesced_subscription_id = self.job_id
        if self._walk_forward_reference is not None and self._tree_quiesced and ownership_error is None:
            self._quiesced_walk_forward = (self.job_id, self._walk_forward_reference)
        if self._operation == 'ui_backup_restore':
            BackupManager(self.paths).recover()
        if ownership_error is not None:
            raise ownership_error

    def _join_descendants(self, pid):
        if self.tree:
            self.tree.stop_and_join()
            return
        if not pid or sys.platform == 'win32':
            if self._operation in WALK_FORWARD_OPERATIONS:
                raise RuntimeSafetyError('Cannot prove walk-forward subtree stopped; reconciliation blocked')
            return
        try: os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError: return
        deadline = time.monotonic()+6
        while True:
            try: os.killpg(pid,0)
            except ProcessLookupError: return
            # A reparented zombie cannot perform I/O. Linux may retain it until
            # its new parent reaps it; prove every remaining group member is Z.
            if sys.platform.startswith('linux'):
                live = False
                for item in Path('/proc').iterdir():
                    if not item.name.isdigit(): continue
                    try: fields=(item/'stat').read_text().rsplit(')',1)[1].split()
                    except (FileNotFoundError, ProcessLookupError): continue
                    if int(fields[2]) == pid and fields[0] != 'Z': live=True;break
                if not live: return
            if time.monotonic() >= deadline: raise RuntimeSafetyError('Worker descendants still active; reconciliation blocked')
            time.sleep(.02)

    def cancel(self):
        if not self.active:
            return
        proc = self.process
        if self.tree:
            if self._requires_tree_quiescence: self.tree.stop_and_join()
            else: self.tree.close()
        elif proc.pid and proc.is_alive():
            if sys.platform != 'win32':
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    proc.terminate()
            else:
                proc.terminate()
        if proc.pid:
            proc.join(3)
            if proc.is_alive():
                proc.kill()
                proc.join(3)
            if proc.is_alive():
                raise RuntimeSafetyError('Worker did not stop; do not restore or close')
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
