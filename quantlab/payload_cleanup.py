"""Explicit, fail-closed cleanup of installer version directories.

The caller supplies the payload root and active version, never a user workspace.
All descendants are inspected without following
links; immutable plans record identities and are re-planned before each deletion.
This is not protection against a hostile same-user process racing rmtree.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat


def parse_version(value):
    """Canonical numeric release versions, two or three components only."""
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(\.(0|[1-9][0-9]{0,8}))?', value):
        raise ValueError('bad_version')
    parts = tuple(int(part) for part in value.split('.'))
    return parts + (0,) * (3 - len(parts))


@dataclass(frozen=True)
class CleanupPlan:
    root: Path
    current_version: str
    candidates: tuple[Path, ...] = ()
    reason: str = ''
    identities: tuple = ()


@dataclass(frozen=True)
class CleanupResult:
    deleted: tuple[Path, ...] = ()
    reason: str = ''


def _inspect(path, root, identities):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('unsafe_link')
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('outside_root')
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise ValueError('unsafe_entry')
    identities.append((str(path.relative_to(root)), info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_size))
    if stat.S_ISDIR(info.st_mode):
        for child in sorted(path.iterdir()):
            _inspect(child, root, identities)


def plan_payload_cleanup(payload_root, current_version):
    """Keep current + newest strictly older release; refuse the entire unsafe tree."""
    if '..' in Path(payload_root).parts:
        return CleanupPlan(Path(payload_root), current_version, reason='invalid_root')
    root = Path(os.path.abspath(payload_root))
    try:
        current = parse_version(current_version)
        local = os.environ.get('LOCALAPPDATA')
        if local and root.resolve().is_relative_to((Path(local) / 'MarkAuto').resolve()):
            raise ValueError('user_workspace')
        # Check every ancestor with lstat before resolving, including junctions.
        for parent in (root, *root.parents):
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('unsafe_link')
        resolved = root.resolve(strict=True)
        if not root.is_dir() or resolved != root:
            raise ValueError('invalid_root')
        versions = {}
        children = sorted(root.iterdir())
        for child in children:
            version = parse_version(child.name)
            if version in versions:
                raise ValueError('ambiguous_version')
            versions[version] = child
        if current not in versions or versions[current].name != current_version:
            raise ValueError('missing_current')
        identities = []
        _inspect(root, resolved, identities)
        if any(not stat.S_ISDIR(child.lstat().st_mode) for child in children):
            raise ValueError('invalid_version_directory')
        older = [version for version in versions if version < current]
        keep = {current, max(older)} if older else {current}
        candidates = tuple(path for version, path in sorted(versions.items()) if version not in keep)
        return CleanupPlan(root, current_version, candidates, identities=tuple(identities))
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else 'filesystem_error'
        return CleanupPlan(root, current_version, reason=reason)


def execute_payload_cleanup(plan):
    """Delete only an unchanged, valid plan; stop on the first rmtree error."""
    if not isinstance(plan, CleanupPlan) or plan.reason:
        return CleanupResult(reason=getattr(plan, 'reason', '') or 'invalid_plan')
    fresh = plan_payload_cleanup(plan.root, plan.current_version)
    if fresh != plan:
        return CleanupResult(reason=fresh.reason or 'plan_changed')
    deleted = []

    def stop_on_error(function, path, error):
        raise error[1]

    for candidate in plan.candidates:
        # Full revalidation catches newly introduced links, names and identity changes.
        check = plan_payload_cleanup(plan.root, plan.current_version)
        if check.reason or check != fresh or candidate.parent != plan.root or candidate not in check.candidates:
            return CleanupResult(tuple(deleted), check.reason or 'plan_changed')
        try:
            shutil.rmtree(candidate, onerror=stop_on_error)
        except (OSError, ValueError):
            return CleanupResult(tuple(deleted), 'delete_failed')
        deleted.append(candidate)
        # Deleting a child changes the root directory mtime; take a new baseline.
        fresh = plan_payload_cleanup(plan.root, plan.current_version)
        if fresh.reason:
            return CleanupResult(tuple(deleted), fresh.reason)
    return CleanupResult(tuple(deleted))
