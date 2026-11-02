"""Workspace-local pseudonym key; never an API credential or account value."""

import os
from pathlib import Path
from secrets import token_bytes
from stat import S_ISREG

from quantlab.trading.domain.validation import DomainError

KEY_FILE = '.sinopac-account-alias.key'


def workspace_alias_key(root: Path) -> bytes:
    path = root / KEY_FILE
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == 'posix':
                directory = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        # A linked or malformed key is not silently replaced. A racing incomplete
        # create fails closed; no preference migration occurs before a full read.
        mode = path.stat().st_mode
        if path.is_symlink() or not S_ISREG(mode) or (os.name == 'posix' and mode & 0o077):
            raise ValueError('key file type')
        with path.open('rb') as stream:
            key = stream.read(33)
        if len(key) != 32:
            raise ValueError('key size')
        return key
    except (OSError, ValueError):
        raise DomainError('validation_failed', 'workspace account alias key unavailable') from None
