"""Bounded, read-only backup projections. Never decompress member payloads.

Names are untrusted data too: only fixed product filenames leave this module.
The restore worker remains responsible for manifest, CRC and content validation.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import stat
import struct
import zipfile

from .desktop_runtime import BackupManager, MAX_BACKUP, MAX_FILES, MAX_JSON

MAX_STATE_BYTES = 65536
MAX_CENTRAL_BYTES = 4 * 1024 * 1024
MAX_DISPLAY_MEMBERS = 50
DISPLAY_NAMES = frozenset(('manifest.json', 'state/settings.json', 'state/research.sqlite3', 'state/research.sqlite'))


@dataclass(frozen=True)
class ArchiveMetadata:
    modified: float
    size: int


@dataclass(frozen=True)
class ArchivePreview:
    identity: tuple
    count: int
    names: tuple[str, ...]
    hidden: int
    truncated: int
    error_code: str = ''


def identity(path):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('validation_failed')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def latest_metadata(state_path, *, session_archive=None):
    """Read at most 64 KiB of state, then stat archives; no directory scan."""
    try:
        candidates = []
        if Path(state_path).exists():
            identity(state_path)
            with Path(state_path).open('rb') as source:
                raw = source.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                return None
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get('last_archive'), str):
                return None
            if value['last_archive']:
                candidates.append(value['last_archive'])
        if session_archive:
            candidates.append(session_archive)
        available = []
        for candidate in candidates:
            try:
                identity(candidate)
                info = Path(candidate).stat()
                available.append(ArchiveMetadata(info.st_mtime, info.st_size))
            except (OSError, ValueError):
                continue
        return max(available, key=lambda item: item.modified, default=None)
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def local_time(timestamp):
    """Injectable local clock/locale boundary; absolute time avoids relative drift."""
    return datetime.fromtimestamp(timestamp).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')


def human_size(size):
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024 or unit == 'GiB':
            return f'{size:.1f} {unit}'
        size /= 1024


def inspect_archive(path):
    """Inspect bounded ZIP central metadata only, without extraction or writes.

    ZIP64/multidisk archives and excessive central directories fail closed before
    ZipFile allocates its member list. EOCD and central metadata are the only reads.
    """
    try:
        before = identity(path)
        if before[2] > MAX_BACKUP + MAX_CENTRAL_BYTES:
            raise ValueError('validation_failed')
        with Path(path).open('rb') as source:
            if before[2] < 22:
                raise ValueError('validation_failed')
            source.seek(-22, 2)
            tail = source.read(22)
            signature, disk, central_disk, disk_count, count, central_size, offset, comment = struct.unpack('<4s4H2LH', tail)
            if (
                signature != b'PK\x05\x06'
                or disk
                or central_disk
                or disk_count != count
                or count > MAX_FILES + 1
                or central_size > MAX_CENTRAL_BYTES
                or count == 65535
                or offset + central_size != before[2] - 22
                or comment
            ):
                raise ValueError('validation_failed')
            # Isolate central metadata in memory: ZipFile's EOCD search must
            # never scan backwards into a payload (possibly sensitive data).
            source.seek(offset)
            central = source.read(central_size)
            import io  # Keep the metadata buffer local to explicit inspection.

            central_end = struct.pack('<4s4H2LH', signature, disk, central_disk, disk_count, count, central_size, 0, 0)
            with zipfile.ZipFile(io.BytesIO(central + central_end)) as archive:
                infos = archive.infolist()
                if len(infos) != count or sum(item.file_size for item in infos) > MAX_BACKUP:
                    raise ValueError('validation_failed')
                seen = set()
                names = []
                hidden = 0
                for item in infos:
                    BackupManager._safe_name(item.orig_filename)
                    name = item.filename
                    if (
                        name != item.orig_filename
                        or name.casefold() in seen
                        or item.is_dir()
                        or stat.S_ISLNK(item.external_attr >> 16)
                        or item.flag_bits & 1
                        or (name != 'manifest.json' and not name.startswith('state/'))
                        or item.header_offset < 0
                        or item.header_offset >= offset
                    ):
                        raise ValueError('validation_failed')
                    seen.add(name.casefold())
                    if name in DISPLAY_NAMES:
                        if len(names) < MAX_DISPLAY_MEMBERS:
                            names.append(name)
                    else:
                        hidden += 1
                if 'manifest.json' not in seen or archive.getinfo('manifest.json').file_size > MAX_JSON:
                    raise ValueError('validation_failed')
        if identity(path) != before:
            raise ValueError('validation_failed')
        return ArchivePreview(before, count, tuple(names), hidden, max(0, count - MAX_DISPLAY_MEMBERS))
    except (OSError, ValueError, OverflowError, zipfile.BadZipFile, struct.error):
        return ArchivePreview((), 0, (), 0, 0, 'validation_failed')
