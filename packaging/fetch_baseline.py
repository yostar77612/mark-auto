"""Fetch the exact previously delivered installer for real upgrade verification.

No credentials or dynamic latest-release lookup. Bytes and source commit are pinned.
This downloads but never executes the installer; execution belongs to Windows CI.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request
import os
import sys

BASE = 'https://github.com/yostar77612/mark-auto/releases/download/desktop-preview-38013204925-1/'
SOURCE = 'fc2dfacbf297004095e971ec10cf3620307417a2'
ASSETS = {
    'MarkAuto-0.2.0-windows-x64-setup.exe': ('be1c749e9fc83ede8c9a0e18d9be99a3c7e3104b4798dda6ccb1834f29471f29', 36848324),
    'build-manifest.json': ('7cf66be9406b842949cdf5501c2c28915a6baad532a46dcd4d911e818174e33d', 6539),
}


def fetch(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, (expected, size) in ASSETS.items():
        target = destination / name
        if target.exists():
            if target.is_symlink() or target.stat().st_size != size or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError('Existing baseline artifact differs; refusing overwrite')
            continue
        fd, temporary = tempfile.mkstemp(prefix='.baseline-', dir=destination)
        try:
            count, digest = 0, hashlib.sha256()
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(BASE + name, timeout=90) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('Baseline redirect is not HTTPS')
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    count += len(block)
                    if count > size:
                        raise ValueError('Baseline artifact exceeds pinned size')
                    output.write(block)
                    digest.update(block)
            if count != size or digest.hexdigest() != expected:
                raise ValueError('Baseline artifact integrity mismatch')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    manifest = json.loads((destination / 'build-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('source_commit') != SOURCE or manifest.get('artifacts_sha256', {}).get('MarkAuto-0.2.0-windows-x64-setup.exe') != ASSETS['MarkAuto-0.2.0-windows-x64-setup.exe'][0]:
        raise ValueError('Baseline manifest provenance mismatch')
    return manifest


if __name__ == '__main__':
    fetch(sys.argv[1])
    print('Pinned released 0.2.0 baseline verified; not executed by this tool.')
