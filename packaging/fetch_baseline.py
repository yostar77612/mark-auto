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

BASE = 'https://github.com/yostar77612/mark-auto/releases/download/desktop-preview-38009150044-1/'
SOURCE = '28c9f9020e5f44a7a986380e3a6d16bdb7235b2d'
ASSETS = {
    'MarkAuto-0.1.2-windows-x64-setup.exe': ('0f92f70fb17bc3f0c2c816cbb5f963ecb2de6dde40745759f415a4755e85c469', 36695486),
    'build-manifest.json': ('baaf01a01d8a830297604e1c6d9ebaf4f9b2be6f1a037c1acff09c21959daee6', 5751),
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
    if manifest.get('source_commit') != SOURCE or manifest.get('artifacts_sha256', {}).get('MarkAuto-0.1.2-windows-x64-setup.exe') != ASSETS['MarkAuto-0.1.2-windows-x64-setup.exe'][0]:
        raise ValueError('Baseline manifest provenance mismatch')
    return manifest


if __name__ == '__main__':
    fetch(sys.argv[1])
    print('Pinned released 0.1.2 baseline verified; not executed by this tool.')
