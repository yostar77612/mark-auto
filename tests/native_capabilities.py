"""Actual native fixture prerequisites; unexpected OS failures remain errors."""

from functools import lru_cache
from pathlib import Path
import sys
import tempfile


@lru_cache(maxsize=1)
def symlinks_available():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = root / 'target'
        target.write_bytes(b'synthetic capability probe')
        try:
            (root / 'link').symlink_to(target)
        except OSError as error:
            if sys.platform == 'win32' and error.winerror == 1314:
                return False
            raise
    return True


SYMLINK_REASON = 'Creating native symlinks requires Windows SeCreateSymbolicLinkPrivilege or Developer Mode (WinError 1314)'
