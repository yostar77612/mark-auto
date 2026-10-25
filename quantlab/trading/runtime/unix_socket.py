"""Short, private AF_UNIX endpoints bound to a canonical engine root.

Only the socket lives in the OS temporary directory. Session metadata, journal
and authentication key remain in the original isolated engine root.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile

from quantlab.trading.domain.validation import DomainError


def _prefix(root: Path, uid: int) -> str:
    identity = sha256(os.fsencode(root.resolve())).hexdigest()[:32]
    return f'ma-v2-{uid}-{identity}-'


def _checked(path: Path, uid: int, mode: int, *, directory: bool) -> os.stat_result:
    value = path.lstat()
    expected_kind = stat.S_ISDIR if directory else stat.S_ISSOCK
    if value.st_uid != uid or stat.S_IMODE(value.st_mode) != mode or not expected_kind(value.st_mode):
        raise DomainError('validation_failed', 'unsafe local socket ownership, mode or type')
    return value


def _base(uid: int) -> Path:
    # TMPDIR can be arbitrarily deep; AF_UNIX sockaddr paths cannot. /tmp is
    # the standard local Unix filesystem location, never a network listener.
    base = Path('/tmp').resolve(strict=True)
    value = base.stat()
    if not stat.S_ISDIR(value.st_mode) or value.st_uid not in (0, uid) or (value.st_mode & 0o022 and not value.st_mode & stat.S_ISVTX):
        raise DomainError('validation_failed', 'unsafe local socket base')
    return base


@dataclass(frozen=True)
class UnixEndpoint:
    directory: Path
    address: str
    uid: int
    device: int
    inode: int

    def secure(self) -> None:
        self._owned_directory()
        path = Path(self.address)
        value = path.lstat()
        if value.st_uid != self.uid or not stat.S_ISSOCK(value.st_mode):
            raise DomainError('validation_failed', 'unsafe local socket')
        path.chmod(0o600)
        _checked(path, self.uid, 0o600, directory=False)

    def _owned_directory(self) -> None:
        value = _checked(self.directory, self.uid, 0o700, directory=True)
        if (value.st_dev, value.st_ino) != (self.device, self.inode):
            raise DomainError('validation_failed', 'local socket directory replaced')

    def close(self) -> None:
        if not self.directory.exists():
            return
        self._owned_directory()
        # Listener.close owns its socket unlink. Never recursively delete a
        # directory or remove an unexpected object during ownership cleanup.
        self.directory.rmdir()


@contextmanager
def unix_endpoint(root: Path):
    uid = os.geteuid()
    directory = Path(tempfile.mkdtemp(prefix=_prefix(root, uid), dir=_base(uid)))
    endpoint = None
    try:
        value = _checked(directory, uid, 0o700, directory=True)
        address = str(directory / 'control.sock')
        if len(os.fsencode(address)) > 100:
            raise DomainError('validation_failed', 'local Unix socket address exceeds portable bound')
        endpoint = UnixEndpoint(directory, address, uid, value.st_dev, value.st_ino)
        yield endpoint
    finally:
        if endpoint is not None:
            endpoint.close()
        else:
            directory.rmdir()


def validate_unix_address(root: Path, address: str) -> None:
    uid = os.geteuid()
    path, root = Path(address), root.resolve()
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise DomainError('validation_failed', 'local socket must be canonical and not linked')
    if path.parent == root and re.fullmatch(r'engine-[0-9a-f]{32}\.sock', path.name):
        # Safe compatibility with already-running engines from the old layout.
        parent = root.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid or parent.st_mode & 0o022:
            raise DomainError('validation_failed', 'unsafe legacy socket directory')
    elif path.name == 'control.sock' and path.parent.parent == _base(uid):
        if len(os.fsencode(address)) > 100 or not re.fullmatch(re.escape(_prefix(root, uid)) + r'[a-z0-9_]{8}', path.parent.name):
            raise DomainError('validation_failed', 'socket does not belong to the selected engine root')
        _checked(path.parent, uid, 0o700, directory=True)
    else:
        raise DomainError('validation_failed', 'socket outside isolated endpoint')
    _checked(path, uid, 0o600, directory=False)
