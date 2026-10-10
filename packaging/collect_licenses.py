"""Retain dependency license/notice texts and Python license in the bundle."""
from importlib.metadata import distributions, version
from pathlib import Path
import shutil
import hashlib
import stat
import sys


# Exact independently reviewed notice archive: 93 files plus its manifest.
# Manifest SHA256: b4b60f442869779652bd13278aea86efb397a659c88ec181dae10c56141001fe
# Changing any dependency or archive content requires a new review and code pin.
NATIVE_NOTICES_SHA256 = 'cbf2c6123cd25e53b33e766fb27bea9c9b4d8d174deb5ae54519d07f62dc9b24'
AUTH_DEPENDENCY_VERSIONS = {
    'PyJWT': '2.15.1', 'cryptography': '50.0.2',
    'cffi': '2.1.1', 'pycparser': '3.11',
}
MAX_NATIVE_NOTICES_BYTES = 2 * 1024 * 1024


def _reject_reparse_ancestry(path):
    # lstat does not follow Windows junctions or dangling symlinks.
    absolute = path.absolute()
    for entry in (*reversed(absolute.parents), absolute):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Native-notice path contains a link or reparse point')


def _reviewed_notice_bytes():
    source = Path('packaging/third_party/chatgpt-auth-native-notices.zip')
    _reject_reparse_ancestry(source)
    try:
        info = source.lstat()
    except FileNotFoundError:
        raise RuntimeError('Pinned native-notice archive is missing') from None
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_NATIVE_NOTICES_BYTES:
        raise RuntimeError('Native-notice archive must be a bounded regular file')
    with source.open('rb') as stream:
        raw = stream.read(MAX_NATIVE_NOTICES_BYTES + 1)
    if len(raw) > MAX_NATIVE_NOTICES_BYTES or hashlib.sha256(raw).hexdigest() != NATIVE_NOTICES_SHA256:
        raise RuntimeError('Native-notice archive checksum mismatch')
    for name, expected in AUTH_DEPENDENCY_VERSIONS.items():
        if version(name) != expected:
            raise RuntimeError('Native-notice dependency version mismatch')
    return raw


# Check the entire immutable input before creating/copying build output. Never
# extract ZIP members or trust paths/component lists asserted by the input.
reviewed_notices = _reviewed_notice_bytes()

output = Path('build/licenses')
_reject_reparse_ancestry(output)
output.mkdir(parents=True, exist_ok=True)
for distribution in distributions():
    name = distribution.metadata['Name']
    for relative in distribution.files or []:
        if any(token in str(relative).lower() for token in ('license', 'copying', 'notice')):
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = output / name / str(relative).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if not python_license.exists():
    raise RuntimeError('Python LICENSE.txt is required for distribution')
shutil.copy2(python_license, output / 'PYTHON-LICENSE.txt')

# Use the verified in-memory bytes, not a second read of a mutable source path.
native_target = output / 'chatgpt-auth-native-notices.zip'
_reject_reparse_ancestry(native_target)
if native_target.exists() and not stat.S_ISREG(native_target.lstat().st_mode):
    raise RuntimeError('Native-notice destination must be a regular file')
native_target.write_bytes(reviewed_notices)
