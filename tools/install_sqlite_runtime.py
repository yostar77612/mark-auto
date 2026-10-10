"""Provision a hash-pinned SQLite in a NEW private runtime; never modify Python in place.

Windows: copy CPython into destination, update only that copy's DLL.
Linux: compile pinned source into destination and scope LD_LIBRARY_PATH to children.
Network is only used during setup, never in application/tests.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'packaging/sqlite-runtime.json'
MAX_ARCHIVE = 16 * 1024 * 1024
LINUX_FLAGS = ['-O2', '-fPIC', '-shared', '-DSQLITE_THREADSAFE=1',
               '-DSQLITE_ENABLE_COLUMN_METADATA', '-DSQLITE_ENABLE_FTS5',
               '-DSQLITE_ENABLE_RTREE', '-Wl,-soname,libsqlite3.so.0']


def reject_links(path):
    for entry in (*reversed(path.absolute().parents), path.absolute()):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Private-runtime path contains symlink or reparse point')


def validate_destination(source, destination):
    reject_links(destination)
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise RuntimeError('Destination must be NEW and separate from the base Python installation')


def download(pin):
    with urllib.request.urlopen(pin['url'], timeout=90) as response:
        if not response.url.startswith('https://www.sqlite.org/'):
            raise RuntimeError('SQLite download redirected outside official HTTPS origin')
        data = response.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise RuntimeError('SQLite archive exceeds size limit')
    for algorithm in ('sha256', 'sha3_256'):
        if hashlib.new(algorithm, data).hexdigest() != pin[algorithm]:
            raise RuntimeError(f'SQLite archive {algorithm} mismatch')
    return data


def member(data, name, maximum=12 * 1024 * 1024):
    # No extractall: exact named bytes only, no archive-specified write paths.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        matches = [entry for entry in archive.infolist() if entry.filename == name]
        if len(matches) != 1 or matches[0].file_size > maximum:
            raise RuntimeError('Missing, duplicated or oversized pinned archive member')
        return archive.read(matches[0])


def provision(destination, report, github=False):
    if sys.platform not in ('win32', 'linux') or sys.maxsize <= 2**32:
        raise RuntimeError('Provisioning supports 64-bit Windows/Linux only')
    if sys.platform == 'win32' and platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('Official pinned Windows DLL requires x64')
    if sys.prefix != sys.base_prefix:
        raise RuntimeError('Run from base CPython, not a venv')
    destination = destination.absolute()
    validate_destination(Path(sys.base_prefix), destination)
    pin = json.loads(MANIFEST.read_text(encoding='utf-8'))
    env = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(name, None)
    evidence = {'pin': pin, 'base_python': sys.executable, 'base_version': sys.version,
                'platform': platform.platform()}
    if sys.platform == 'win32':
        archive = download(pin['windows_x64'])
        dll = member(archive, 'sqlite3.dll')
        if hashlib.sha256(dll).hexdigest() != pin['windows_x64']['dll_sha256']:
            raise RuntimeError('Pinned DLL content mismatch')
        source = Path(sys.base_prefix)
        original = source / 'DLLs/sqlite3.dll'
        if not original.is_file() or not (source / 'python.exe').is_file():
            raise RuntimeError('Expected full Windows CPython layout is missing')
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__'))
        target = destination / 'DLLs/sqlite3.dll'
        reject_links(target)
        target.write_bytes(dll)
        if hashlib.sha256(original.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError('Base Python DLL unexpectedly changed')
        executable = destination / 'python.exe'
        evidence['base_sqlite_sha256_unchanged'] = original_hash
        env['PATH'] = str(destination) + os.pathsep + env.get('PATH', '')
    else:
        archive = download(pin['amalgamation'])
        source_bytes = member(archive, pin['amalgamation']['member'])
        if hashlib.sha3_256(source_bytes).hexdigest() != pin['amalgamation']['source_sha3_256']:
            raise RuntimeError('SQLite amalgamation source hash mismatch')
        destination.mkdir(parents=True)
        source_file = destination / 'sqlite3.c'
        source_file.write_bytes(source_bytes)
        target = destination / 'libsqlite3.so.0'
        command = ['cc', *LINUX_FLAGS, str(source_file), '-o', str(target), '-lm', '-ldl', '-lpthread']
        subprocess.run(command, check=True, timeout=180)
        evidence.update(compiler=subprocess.check_output(['cc', '--version'], text=True), command=command)
        executable = Path(sys.executable)
        env['LD_LIBRARY_PATH'] = str(destination) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
        env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH'].rstrip(os.pathsep)
    library_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    probe = [str(executable), '-I', str(ROOT / 'quantlab/sqlite_runtime.py'),
             '--manifest', str(MANIFEST), '--root', str(destination), '--sha256', library_hash]
    evidence['runtime'] = json.loads(subprocess.check_output(probe, env=env, text=True, timeout=30))
    if evidence['runtime']['python'] != sys.version:
        raise RuntimeError('Private runtime changed Python version')
    if sys.platform == 'win32' and Path(evidence['runtime']['python_prefix']).resolve() != destination.resolve():
        raise RuntimeError('Private Python resolved its prefix outside the private copy')
    (destination / 'markauto-sqlite-runtime.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    if github:
        if sys.platform == 'win32':
            with open(os.environ['GITHUB_PATH'], 'a', encoding='utf-8') as stream:
                stream.write(str(destination) + '\n')
        else:
            with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as stream:
                stream.write('LD_LIBRARY_PATH=' + env['LD_LIBRARY_PATH'] + '\n')
    print(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--github', action='store_true')
    args = parser.parse_args()
    provision(args.destination, args.report, args.github)


if __name__ == '__main__':
    main()
