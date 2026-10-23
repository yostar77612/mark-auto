"""Windows extended-length I/O spelling; no settings, loader or VFS changes.

This is not admission: callers retain their local-drive, link and source checks.
Keep ordinary paths for persisted identities and only adapt the I/O spelling.
"""

import os
from pathlib import Path
import re
import sys
from urllib.parse import quote


def canonical_path(path):
    """Remove only a local drive's extended prefix, never UNC/device namespaces."""
    path = Path(path)
    text = str(path)
    if sys.platform == 'win32' and re.match(r'^\\\\\?\\[A-Za-z]:\\', text):
        return Path(text[4:])
    return path


def native_path(path, *, force=False):
    """Reserve room for journal/temp suffixes without changing short path behavior."""
    path = Path(path)
    if sys.platform == 'win32':
        absolute = os.path.abspath(path)
        # Extended paths do not perform Win32's dot/space normalization. Never
        # turn an ambiguous/traversing spelling into a newly accessible target.
        parts = path.parts[1:] if path.anchor else path.parts
        safe_parts = all(
            part not in ('.', '..')
            and not part.endswith((' ', '.'))
            and ':' not in part
            and not re.match(r'^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)
            for part in parts
        )
        units = len(absolute.encode('utf-16-le')) // 2
        if (force or units >= 240) and safe_parts and re.match(r'^[A-Za-z]:\\', absolute):
            return Path('\\\\?\\' + absolute)
    return path


def sqlite_uri(path):
    """Escape the filename while preserving the caller's exact SQLite open mode.

    Path.as_uri interprets an extended prefix as a URI authority. SQLite instead
    needs that prefix inside its escaped filename; '#' and '%' must remain data.
    No nolock, immutable, VFS override or other connection option is introduced.
    """
    path = native_path(path).absolute()
    if sys.platform == 'win32' and re.match(r'^\\\\\?\\[A-Za-z]:\\', str(path)):
        return 'file:' + quote(str(path), safe='/:')
    return path.as_uri()
