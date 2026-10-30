"""Owned filesystem metadata, bounded reads and temporary publication."""

from pathlib import Path
from tempfile import TemporaryDirectory
from quantlab.core import ValidationError

__all__ = ('TemporaryDirectory', '_root', 'mkdir', 'exists', 'unlink', 'is_dir', 'is_symlink', '_promote_report', 'official_source')


def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def mkdir(path, *args, **kwargs):
    return path.mkdir(*args, **kwargs)


def exists(path):
    return path.exists()


def unlink(path):
    return path.unlink()


def is_dir(path):
    return path.is_dir()


def is_symlink(path):
    return path.is_symlink()


def _promote_report(folder, destination):
    from quantlab.runtime_support import replace_file

    return replace_file(folder, destination)


def official_source(path, limit, message):
    if path.stat().st_size > limit:
        raise ValidationError(message)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError(message)
    return raw
