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


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


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
    def credentials(self):
        return self.root / 'credentials'

    def ensure(self):
        for path in (self.root, self.state, self.cache, self.logs, self.credentials):
            path.mkdir(parents=True, exist_ok=True)
        return self


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

    Restore uses a same-volume staging directory and recovery marker. A crash
    between the two directory renames is recovered on next startup.
    """
    def __init__(self, paths, jobs=None):
        self.paths, self.jobs = paths, jobs

    def _quiescent(self):
        if self.jobs is not None and self.jobs.active:
            raise RuntimeSafetyError('Stop active jobs before backup or restore')

    def recover(self):
        rollback = self.paths.root / 'state-v1.rollback'
        if rollback.exists():
            if not self.paths.state.exists():
                os.replace(rollback, self.paths.state)
            else:
                shutil.rmtree(rollback)
        for old in self.paths.root.glob('.restore-*'):
            if old.is_dir() and not old.is_symlink():
                shutil.rmtree(old)

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

    def create(self, destination):
        self._quiescent()
        self.paths.ensure()
        destination = Path(destination).resolve()
        if destination.is_relative_to(self.paths.state.resolve()) or destination.is_relative_to(self.paths.credentials.resolve()):
            raise RuntimeSafetyError('Backup must be outside state and credential directories')
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
                size += path.stat().st_size
                files.append((name, path))
                if size > MAX_BACKUP or len(files) > MAX_FILES:
                    raise RuntimeSafetyError('Backup size limit exceeded')
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destination.parent, suffix='.zip.tmp')
        os.close(fd)
        try:
            manifest = {'schema_version': STATE_VERSION, 'app_version': __version__, 'files': {}}
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
                if not isinstance(manifest, dict) or manifest.get('schema_version') != STATE_VERSION or not isinstance(manifest.get('files'), dict):
                    raise RuntimeSafetyError('Incompatible backup state version')
                entries = manifest['files']
                if set(names) != {'manifest.json'} | {'state/' + n for n in entries}:
                    raise RuntimeSafetyError('Manifest does not match archive')
                for name, expected in entries.items():
                    self._safe_name(name)
                    raw = archive.read('state/' + name)
                    if not isinstance(expected, dict) or len(raw) != expected.get('size') or hashlib.sha256(raw).hexdigest() != expected.get('sha256'):
                        raise RuntimeSafetyError('Backup hash mismatch')
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(target, raw)
            settings = staging / 'settings.json'
            if settings.exists():
                SettingsStore(settings).load()
            rollback = self.paths.root / 'state-v1.rollback'
            if self.paths.state.exists():
                os.replace(self.paths.state, rollback)
            try:
                os.replace(staging, self.paths.state)
            except BaseException:
                if rollback.exists():
                    os.replace(rollback, self.paths.state)
                raise
            if rollback.exists():
                shutil.rmtree(rollback)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


UI_OPERATIONS = frozenset({
    'ui_demo', 'ui_import', 'ui_refresh', 'ui_backtest', 'ui_campaign',
    'ui_compare', 'ui_select', 'ui_disable', 'ui_paper_snapshot',
    'ui_paper_reconcile', 'ui_paper_kill', 'ui_paper_replay',
    'ui_paper_submit', 'ui_paper_cancel', 'ui_backup_create', 'ui_backup_restore',
})
OPERATIONS = UI_OPERATIONS | {'demo', 'backtest', 'campaign'}


def _job_worker(sender, gate, operation, payload, root, job_id):
    if sys.platform != 'win32':
        os.setsid()
    if not gate.wait(15):
        return
    def emit(kind, **values):
        sender.send_bytes(_json_bytes({'job_id': job_id, 'type': kind, **values}))
    try:
        emit('progress', message='Working', progress=0)
        paths = AppPaths(Path(root))
        if operation in UI_OPERATIONS:
            from desktop_ui import execute_ui_operation
            result = execute_ui_operation(operation, payload, paths)
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

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class JobManager:
    """One spawned bounded-IPC task at a time; no arbitrary callable execution."""
    def __init__(self, paths):
        self.paths = paths.ensure()
        self.process = self.receiver = self.tree = None
        self.job_id = None
        self._terminal = False
        self._pending = []

    @property
    def active(self):
        # A completed child still needs its IPC/result drained before another job.
        return self.process is not None

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
        context = mp.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        gate = context.Event()
        self._gate = gate
        self.job_id = uuid.uuid4().hex
        self._terminal = False
        self.process = context.Process(target=_job_worker, args=(sender, gate, operation, payload, str(self.paths.root), self.job_id))
        self.receiver = receiver
        try:
            self.process.start()
            sender.close()
            if sys.platform == 'win32':
                self.tree = _WindowsProcessTree(self.process.pid)
            gate.set()
        except BaseException:
            sender.close()
            self.cancel()
            raise
        return self.job_id

    def poll(self):
        events, self._pending = self._pending, []
        if not self.active:
            return events
        eof = False
        try:
            for _ in range(16):
                if not self.receiver.poll():
                    break
                try:
                    event = json.loads(self.receiver.recv_bytes(MAX_JSON))
                except EOFError:
                    eof = True
                    break
                if not isinstance(event, dict) or event.get('job_id') != self.job_id or event.get('type') not in {'progress', 'result', 'error'}:
                    raise RuntimeSafetyError('Invalid worker response')
                events.append(event)
                if event['type'] in {'result', 'error'}:
                    self._terminal = True
        except (OSError, ValueError):
            self.cancel()
            events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker response rejected'})
            return events
        if not self.process.is_alive():
            self.process.join()
            # The child can send and exit between the initial poll and liveness
            # check; drain that final message before reporting a crash.
            if not eof and self.receiver.poll():
                return events + self.poll()
            if not self._terminal:
                events.append({'job_id': self.job_id, 'type': 'error', 'message': 'Worker stopped unexpectedly; incomplete output retained as partial'})
            self._release()
        return events

    def _release(self):
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

    def cancel(self):
        if not self.active:
            return
        proc = self.process
        if self.tree:
            self.tree.close()
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
        self._pending.append({'job_id': self.job_id, 'type': 'cancelled', 'message': 'Cancelled; completed durable records are preserved'})
        self._release()

    def close(self):
        self.cancel()
