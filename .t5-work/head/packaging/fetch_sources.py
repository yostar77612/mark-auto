"""Ship corresponding sources beside binary releases, verified against Qt hashes."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

SOURCES = [
    ('https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz',
     '099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751'),
    ('https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz',
     '98ff4f44bac6ec3e1e62ee2a4316ae0e3d15badb015d753cc0268a20db52f165'),
]
# Expected digests verified from each official URL + '.sha256' on 2026-10-09.


def main(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for url, expected in SOURCES:
        path = destination / url.rsplit('/', 1)[1]
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=120) as response, path.open('wb') as output:
            if not response.url.startswith('https://'):
                raise RuntimeError('Refusing non-HTTPS source mirror')
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected:
            path.unlink()
            raise RuntimeError(f'Upstream source hash mismatch: {path.name}')
        manifest.append({'file': path.name, 'source': url, 'sha256': expected})
    (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
