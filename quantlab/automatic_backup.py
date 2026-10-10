"""Opt-in, in-app daily backups. No daemon, restore automation, or file pruning.

The durable attempt watermark is outside restorable research state. An uncertain
attempt consumes its UTC day, including cancellation or a process crash. This
bounds retries and prevents clock rollback from producing duplicate archives.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import sys
import stat
from pathlib import Path
import time
import uuid

from .desktop_runtime import BackupManager, MAX_BACKUP, RuntimeSafetyError, _json_bytes, _read_json, atomic_write


MAX_ARCHIVES = 7
MAX_MANAGED_BYTES = 2 * 1024 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 10000


class AutomaticBackup:
    def __init__(self, paths, *, clock=time.time):
        self.paths = paths
        self.clock = clock
        self.workspace_id = hashlib.sha256(str(paths.root.resolve()).encode('utf-8')).hexdigest()
        self.path = (paths.bootstrap or paths.root) / 'automatic-backups' / (self.workspace_id + '.json')

    @staticmethod
    def _default():
        return {'schema_version': 1, 'enabled': False, 'directory': '',
                'last_attempt_day': None, 'last_status': 'never', 'last_archive': ''}

    @staticmethod
    def _regular_ancestors(path):
        for item in (path, *path.parents):
            if item.exists() or item.is_symlink():
                BackupManager._check_regular_path(item)

    def destination_directory(self, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise RuntimeSafetyError('Choose an external automatic backup directory')
        if value.startswith(('\\\\', '//')):
            raise RuntimeSafetyError('Automatic backups require a local directory, not a network or device path')
        directory = Path(value)
        if not directory.is_absolute():
            raise RuntimeSafetyError('Automatic backup directory must be absolute')
        if sys.platform == 'win32':
            import ctypes
            # DRIVE_FIXED or DRIVE_REMOVABLE only. Reject mapped network drives
            # as well as UNC/device forms before capacity scans or disk writes.
            get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
            get_drive_type.argtypes = [ctypes.c_wchar_p]
            get_drive_type.restype = ctypes.c_uint
            kind = get_drive_type(str(directory.anchor))
            if kind not in (2, 3):
                raise RuntimeSafetyError('Automatic backups require a local fixed or removable drive')
        self._regular_ancestors(directory)
        directory = directory.resolve()
        for root in (self.paths.root, self.paths.bootstrap or self.paths.root):
            if directory.is_relative_to(root.resolve()):
                raise RuntimeSafetyError('Backup must be outside workspace and application bootstrap directories')
        if directory.exists() and not directory.is_dir():
            raise RuntimeSafetyError('Automatic backup destination must be a directory')
        return directory

    def check_capacity(self, directory):
        count = total = 0
        prefix = f'markauto-{self.workspace_id[:16]}-'
        if directory.exists():
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_DIRECTORY_ENTRIES:
                        raise RuntimeSafetyError('Automatic backup folder has too many entries; choose another folder')
                    if entry.name.startswith(prefix) or entry.name.endswith('.zip.tmp'):
                        # Also count orphan temporary/unknown matching files;
                        # never delete or assume they are safe to overwrite.
                        info = entry.stat(follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
                            raise RuntimeSafetyError('Automatic backup folder contains an unsafe matching entry')
                        count += 1
                        total += info.st_size
            if count >= MAX_ARCHIVES or total + MAX_BACKUP + 16 * 1024 * 1024 > MAX_MANAGED_BYTES:
                raise RuntimeSafetyError('Automatic backup storage limit reached (7 archives / 2 GiB); move files or choose another folder')
        existing = directory
        while not existing.exists():
            existing = existing.parent
        if shutil.disk_usage(existing).free < MAX_BACKUP + 16 * 1024 * 1024:
            raise RuntimeSafetyError('Insufficient free space for automatic backup; at least 528 MiB required')

    def load(self, *, validate_destination=True):
        self._regular_ancestors(self.path)
        if not self.path.exists():
            return self._default()
        if not stat.S_ISREG(self.path.lstat().st_mode):
            raise RuntimeSafetyError('Automatic backup settings must be a regular file')
        value = _read_json(self.path)
        expected = self._default()
        if (not isinstance(value, dict) or set(value) != set(expected)
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(value['enabled']) is not bool
                or not isinstance(value['directory'], str) or len(value['directory']) > 4096
                or (value['last_attempt_day'] is not None and
                    (type(value['last_attempt_day']) is not int or not 0 <= value['last_attempt_day'] <= 3652058))
                or value['last_status'] not in ('never', 'attempted', 'success', 'error', 'cancelled')
                or not isinstance(value['last_archive'], str) or len(value['last_archive']) > 8192):
            raise RuntimeSafetyError('Invalid automatic backup settings; original preserved')
        if validate_destination and value['enabled']:
            self.destination_directory(value['directory'])
        return value

    def _save(self, value):
        self._regular_ancestors(self.path)
        atomic_write(self.path, _json_bytes(value), durable=True)

    def configure(self, *, enabled, directory):
        if type(enabled) is not bool or not isinstance(directory, str) or len(directory) > 4096:
            raise RuntimeSafetyError('Automatic backup enabled must be boolean')
        value = self.load(validate_destination=False)
        # Disabling never probes the old folder (it may be offline). Preserve
        # its text and durable watermark; enabling validates the new selection.
        if enabled:
            directory = str(self.destination_directory(directory))
        value.update(enabled=enabled, directory=directory)
        self._save(value)
        return value

    def claim_due(self, *, quiescent):
        """Return an existing backup-worker payload, or None; never run work here.

        The UI owns job admission, checks every manager, and calls synchronously
        immediately before starting its existing cancellable background worker.
        A failed launch deliberately consumes the day, rather than tight-looping.
        """
        if quiescent is not True:
            return None
        value = self.load()
        if not value['enabled']:
            return None
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now < 253402300800:
            raise RuntimeSafetyError('Invalid system clock for automatic backup')
        day = int(now // 86400)
        if value['last_attempt_day'] is not None and day <= value['last_attempt_day']:
            return None
        directory = self.destination_directory(value['directory'])
        self.check_capacity(directory)
        destination = directory / f'markauto-{self.workspace_id[:16]}-{day}-{uuid.uuid4().hex}.zip'
        if destination.exists() or destination.is_symlink():
            raise RuntimeSafetyError('Automatic backup destination already exists')
        value.update(last_attempt_day=day, last_status='attempted', last_archive=str(destination))
        self._save(value)  # Failure here must never start a worker.
        return {'path': str(destination)}

    def complete(self, *, archive, status):
        if status not in ('success', 'error', 'cancelled'):
            raise RuntimeSafetyError('Invalid automatic backup outcome')
        value = self.load()
        if value['last_status'] != 'attempted' or value['last_archive'] != str(archive):
            raise RuntimeSafetyError('Automatic backup outcome does not match its attempt')
        if status == 'success':
            self._regular_ancestors(Path(archive))
            if not Path(archive).is_file():
                raise RuntimeSafetyError('Automatic backup result is missing')
        value['last_status'] = status
        self._save(value)
