"""Raw, verified, read-only archive of every workspace file, taken before any storage migration (M4b-1a).

Sources are never modified, moved or deleted. Every file under each source root is copied byte for byte
(SQLite main files together with their -wal/-shm/-journal sidecars, hidden and unknown files, logs and the
opaque credential/control bytes), hashed while copying, then re-read from the archive and compared. The
archive is refused rather than shortened when anything is unsafe: a destination inside a source (or the
reverse), an existing destination, a link or reparse point, a network path, too little free space, or a
source file that changed while it was being copied. A refused or cancelled run deletes only the directory it
created itself.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

CHUNK = 1024 * 1024
MANIFEST = 'manifest.json'
FILES = 'files'
VERSION = 1
SAFETY_MARGIN_BYTES = 64 * 1024 * 1024
SIDECARS = ('-wal', '-shm', '-journal')


class ArchiveError(Exception):
    """A stable code only; paths and file contents never appear in the message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Entry:
    label: str
    path: str  # relative to the source root, '/'-separated
    size: int
    sha256: str = ''
    kind: str = 'file'

    @property
    def key(self) -> str:
        return f'{self.label}/{self.path}'


def _kind(name: str) -> str:
    lower = name.lower()
    if lower.endswith(SIDECARS):
        return 'sqlite-sidecar'
    if lower.endswith(('.sqlite', '.sqlite3', '.db')):
        return 'sqlite'
    return 'json' if lower.endswith('.json') else 'log' if lower.endswith(('.log', '.jsonl')) else 'file'


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _checked_label(label: str) -> str:
    if type(label) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,32}', label) is None:
        raise ArchiveError('bad_source_label')
    return label


def _checked_root(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ArchiveError('path_not_local_absolute')
    if not path.is_dir():
        raise ArchiveError('source_missing')
    if _is_link(path):
        raise ArchiveError('link_refused')
    return path.resolve()


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def inventory(sources: Mapping[str, Path]) -> tuple[Entry, ...]:
    """Every file below every source root, in a stable order; read-only."""
    entries = []
    for label in sorted(sources):
        root = _checked_root(sources[_checked_label(label)])
        for current, directories, names in os.walk(root, followlinks=False):
            here = Path(current)
            for name in directories:
                if _is_link(here / name):
                    raise ArchiveError('link_refused')
            directories.sort()
            for name in sorted(names):
                path = here / name
                if _is_link(path):
                    raise ArchiveError('link_refused')
                try:
                    size = path.stat().st_size
                except OSError:
                    raise ArchiveError('source_unreadable') from None
                entries.append(Entry(label, path.relative_to(root).as_posix(), size, kind=_kind(name)))
    return tuple(entries)


def _copy_and_hash(source: Path, target: Path) -> str:
    digest = hashlib.sha256()
    try:
        with source.open('rb') as reader, target.open('wb') as writer:
            while chunk := reader.read(CHUNK):
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError:
        raise ArchiveError('source_unreadable') from None
    return digest.hexdigest()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as reader:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp(path: Path):
    state = path.stat()
    return state.st_size, state.st_mtime_ns


def create_archive(
    sources: Mapping[str, Path],
    destination: Path,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    cancelled: Callable[[], bool] = lambda: False,
    extra_free_bytes: int = 0,
) -> dict:
    """Copy and verify everything. Returns the manifest; raises ArchiveError with a stable code."""
    if not isinstance(destination, Path) or not destination.is_absolute() or str(destination).startswith(('\\\\', '//')):
        raise ArchiveError('path_not_local_absolute')
    roots = {_checked_label(label): _checked_root(path) for label, path in sources.items()}
    target = destination.resolve()
    if any(_inside(target, root) or _inside(root, target) for root in roots.values()):
        raise ArchiveError('destination_overlaps_source')
    if destination.exists():
        raise ArchiveError('destination_exists')
    entries = inventory(roots)
    total = sum(entry.size for entry in entries)
    if shutil.disk_usage(destination.parent).free < total + SAFETY_MARGIN_BYTES + extra_free_bytes:
        raise ArchiveError('not_enough_space')
    destination.mkdir(parents=False)
    try:
        done = []
        for entry in entries:
            if cancelled():
                raise ArchiveError('cancelled')
            source = roots[entry.label] / entry.path
            before = _stamp(source)
            copy = destination / FILES / entry.label / entry.path
            copy.parent.mkdir(parents=True, exist_ok=True)
            digest = _copy_and_hash(source, copy)
            if _stamp(source) != before or before[0] != entry.size:
                raise ArchiveError('source_changed_during_archive')
            if _hash(copy) != digest:
                raise ArchiveError('archive_verification_failed')
            done.append(Entry(entry.label, entry.path, entry.size, digest, entry.kind))
        manifest = {
            'version': VERSION,
            'created_at': now().astimezone(timezone.utc).isoformat(),
            'sources': {label: str(root) for label, root in sorted(roots.items())},
            'file_count': len(done),
            'total_bytes': total,
            'entries': [{'label': e.label, 'path': e.path, 'size': e.size, 'sha256': e.sha256, 'kind': e.kind} for e in done],
        }
        pending = destination / (MANIFEST + '.part')
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(pending, destination / MANIFEST)
        return manifest
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)  # only the directory this call created
        raise


def verify_archive(destination: Path) -> dict:
    """Re-read every archived file; the archive must hold exactly what the manifest lists."""
    try:
        manifest = json.loads((destination / MANIFEST).read_text(encoding='utf-8'))
        listed = {f'{e["label"]}/{e["path"]}': e for e in manifest['entries']}
    except (OSError, ValueError, KeyError, TypeError):
        raise ArchiveError('manifest_unreadable') from None
    if manifest.get('version') != VERSION or len(listed) != len(manifest['entries']):
        raise ArchiveError('manifest_unsupported')
    present = {path.relative_to(destination / FILES).as_posix() for path in (destination / FILES).rglob('*') if path.is_file()}
    if present != set(listed):
        raise ArchiveError('archive_files_differ_from_manifest')
    for key, entry in listed.items():
        path = destination / FILES / key
        if path.stat().st_size != entry['size'] or _hash(path) != entry['sha256']:
            raise ArchiveError('archive_verification_failed')
    return manifest
