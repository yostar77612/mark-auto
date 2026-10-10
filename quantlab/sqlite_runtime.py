"""Verify the actual SQLite native runtime, without altering loader state."""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def loaded_library() -> Path:
    if sys.platform == 'win32':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
        kernel.GetModuleFileNameW.restype = ctypes.c_uint
        handle = kernel.GetModuleHandleW('sqlite3.dll')
        path = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(handle, path, len(path)) if handle else 0
        if not length or length >= len(path):
            raise RuntimeError('Cannot identify loaded SQLite DLL')
        return Path(path.value).resolve()
    if sys.platform.startswith('linux'):
        paths = {Path(line.split(maxsplit=5)[5].strip()).resolve()
                 for line in Path('/proc/self/maps').read_text().splitlines()
                 if len(line.split(maxsplit=5)) == 6 and '/libsqlite3.so' in line}
        if len(paths) == 1:
            return paths.pop()
    raise RuntimeError('Cannot uniquely identify loaded SQLite library')


def verify(manifest: Path, expected_root: Path, expected_sha256: str | None = None) -> dict:
    pin = json.loads(manifest.read_text(encoding='utf-8'))
    with closing(sqlite3.connect(':memory:')) as db:
        version, source_id = db.execute('SELECT sqlite_version(), sqlite_source_id()').fetchone()
        compile_options = [row[0] for row in db.execute('PRAGMA compile_options')]
    if version != pin['version'] or source_id != pin['source_id'] or sqlite3.sqlite_version != version:
        raise RuntimeError(f'Unpinned SQLite runtime: {version} / {source_id}')
    library = loaded_library()
    if not library.is_relative_to(expected_root.resolve()):
        raise RuntimeError(f'SQLite loaded outside private runtime: {library}')
    actual_hash = hashlib.sha256(library.read_bytes()).hexdigest()
    expected_hash = expected_sha256 or pin['windows_x64']['dll_sha256']
    if actual_hash != expected_hash:
        raise RuntimeError('Loaded SQLite library hash mismatch')
    return {'python': sys.version, 'python_executable': sys.executable,
            'python_prefix': sys.prefix, 'sqlite_version': version, 'sqlite_source_id': source_id,
            'library': str(library), 'library_sha256': actual_hash, 'compile_options': compile_options}


def verify_binaries(binaries, manifest: Path):
    libraries = [Path(source) for name, source, kind in binaries
                 if Path(name).name.lower() == 'sqlite3.dll']
    pin = json.loads(manifest.read_text(encoding='utf-8'))
    if len(libraries) != 1:
        raise RuntimeError('Expected exactly one bundled SQLite DLL')
    if hashlib.sha256(libraries[0].read_bytes()).hexdigest() != pin['windows_x64']['dll_sha256']:
        raise RuntimeError('PyInstaller selected an unpinned SQLite DLL')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    print(json.dumps(verify(args.manifest, args.root, args.sha256)))


if __name__ == '__main__':
    main()
