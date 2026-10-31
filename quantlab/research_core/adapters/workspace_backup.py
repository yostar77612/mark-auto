"""Desktop job implementation extracted without changing safety control flow."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
from quantlab import __version__
from quantlab.windows_paths import canonical_path, native_path
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.runtime_support import atomic_write, _durable_replace
from quantlab.research_core.domain.job_protocol import MAX_JSON
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.research_core.adapters.state_json import _read_json, _json_bytes, STATE_VERSION
from quantlab.research_core.adapters.workspace_store import (
    _workspace_format,
    _write_workspace_format,
    WORKSPACE_FORMAT,
    GUARDED_BACKUP_VERSION,
    MAX_BACKUP,
    MAX_FILES,
)
from quantlab.research_core.adapters.runtime_safety import _verify_replay_runtime


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
        artifacts = (self.paths.root / 'state-v1.rollback', self.paths.root / 'restore-transaction.json', self.paths.state / '.restore-transaction')
        if not any(path.exists() or path.is_symlink() for path in artifacts):
            return  # No mutation, including intact unresolved-analysis startup.
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import operation_guard

        with operation_guard(self.paths, 'restore_recovery') as ownership:
            return self._recover(ownership)

    def _recover(self, ownership):
        self._quiescent()
        rollback = self.paths.root / 'state-v1.rollback'
        journal = self.paths.root / 'restore-transaction.json'
        token = self.paths.state / '.restore-transaction'
        transaction = None
        if journal.exists():
            try:
                value = _read_json(journal)
                if (
                    isinstance(value, dict)
                    and value.get('phase') in ('prepared', 'committed')
                    and isinstance(value.get('id'), str)
                    and re.fullmatch(r'[a-f0-9]{32}', value['id'])
                ):
                    transaction = value
            except (OSError, ValueError):
                pass  # Unknown journal is never evidence that rollback is disposable.
        if transaction:
            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery import advance_restore_epoch

            advance_restore_epoch(self.paths, transaction['id'], admission=ownership)
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
        if (
            not name
            or '\\' in name
            or ':' in name
            or name.startswith('/')
            or any(p in ('.', '..') or p.endswith((' ', '.')) for p in parts)
            or '/'.join(parts) != name
        ):
            raise RuntimeSafetyError('Unsafe backup path')
        if any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I) for p in parts):
            raise RuntimeSafetyError('Reserved Windows backup path')
        return name

    @staticmethod
    def _check_regular_path(path):
        info = native_path(path).lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeSafetyError('Symlinks and Windows reparse points cannot be backed up')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise RuntimeSafetyError('Hard-linked files cannot be backed up')

    def create(self, destination):
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import operation_guard

        with operation_guard(self.paths, 'ui_backup_create'):
            return self._create(destination)

    def _create(self, destination):
        # Archive support is only needed for an explicit backup operation.
        import zipfile

        self._quiescent()
        destination = native_path(destination).resolve()
        # Validate before recovery/ensure: even a rejected destination must not
        # alter journals, locks, vaults or irreversible accounting controls.
        # Keep archives outside both the active workspace and fixed bootstrap;
        # this also protects future internal files without a brittle allowlist.
        for root in (self.paths.root, self.paths.bootstrap or self.paths.root):
            if canonical_path(destination).is_relative_to(canonical_path(Path(root).resolve())):
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
            if {'sqlite_replay', 'sqlite_walk_forward'} & set(workspace_format):
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
        # Keep operation-specific dependencies out of module startup.
        from quantlab.analysis_recovery import operation_guard

        (self.paths.bootstrap or self.paths.root).mkdir(parents=True, exist_ok=True)
        with operation_guard(self.paths, 'ui_backup_restore') as ownership:
            return self._restore(source, ownership)

    def _restore(self, source, ownership):
        # Archive support is only needed for an explicit restore operation.
        import zipfile

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
                if (
                    not isinstance(manifest, dict)
                    or manifest.get('schema_version') not in (STATE_VERSION, GUARDED_BACKUP_VERSION)
                    or not isinstance(manifest.get('files'), dict)
                ):
                    raise RuntimeSafetyError('Incompatible backup state version')
                restored_format = WORKSPACE_FORMAT
                if manifest['schema_version'] == GUARDED_BACKUP_VERSION:
                    restored_format = _workspace_format(manifest.get('workspace_format'))
                    _verify_replay_runtime(restored_format)
                    if not {'sqlite_replay', 'sqlite_walk_forward'} & set(restored_format):
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
            # Keep both data generations protected until verified promotion or
            # rollback selects its exact format. Never open SQLite during restore.
            if {'sqlite_replay', 'sqlite_walk_forward'} & set(restored_format):
                _write_workspace_format(self.paths.root, {**prior_format, **restored_format})
            transaction_id = uuid.uuid4().hex
            # Keep operation-specific dependencies out of module startup.
            from quantlab.analysis_recovery import advance_restore_epoch

            advance_restore_epoch(self.paths, transaction_id, admission=ownership)
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


class WorkspaceJobStorage:
    check_regular_path = staticmethod(BackupManager._check_regular_path)

    @staticmethod
    def recover(paths):
        return BackupManager(paths).recover()

    @staticmethod
    def validate_payload(payload):
        return _json_bytes(payload)

    @staticmethod
    def _walk_forward_owner_path(paths, reference):
        from .walk_forward_owner import WalkForwardOwner

        return WalkForwardOwner(paths, BackupManager._check_regular_path)._walk_forward_owner_path(reference)

    @staticmethod
    def _claim_walk_forward(paths, reference, job_id):
        from .walk_forward_owner import WalkForwardOwner

        return WalkForwardOwner(paths, BackupManager._check_regular_path)._claim_walk_forward(reference, job_id)

    @staticmethod
    def _check_walk_forward_owner(paths, job_id, reference):
        from .walk_forward_owner import WalkForwardOwner

        return WalkForwardOwner(paths, BackupManager._check_regular_path)._check_walk_forward_owner(job_id, reference)

    @staticmethod
    def worker_paths(root, bootstrap):
        from .workspace_store import AppPaths

        return AppPaths(root, bootstrap)

    @staticmethod
    def configure_workspace(paths, destination):
        from .workspace_store import WorkspaceLocator

        return WorkspaceLocator(paths.bootstrap or paths.root).configure(destination)
