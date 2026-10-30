"""Verify ordered base replay without mutating the audited PR C tree."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.refactor.replay_pr_c import BASE, git


def snapshot(root):
    names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names if name and (root / name).is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    root = parser.parse_args().root.resolve()
    before, status = snapshot(root), git(root, 'status', '--porcelain', '--untracked-files=all')
    scratch = root / '.tmp-pr-c-replay'
    scratch.mkdir(exist_ok=True)
    directory = scratch / ('audit-' + uuid.uuid4().hex[:8])
    directory.mkdir()
    try:
        subprocess.run(['git', 'init', str(directory)], check=True, capture_output=True)
        objects = git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'objects').decode().strip()
        (directory / '.git/objects/info/alternates').write_text(objects + '\n', encoding='utf-8', newline='\n')
        subprocess.run(['git', '-C', str(directory), 'checkout', '--detach', BASE], check=True, capture_output=True)
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'tools.refactor.replay_pr_c', '--root', str(directory), '--expect-root', str(root)], cwd=root, check=False
        )
    finally:
        if not directory.is_relative_to(root):
            raise ValueError('Audit cleanup must stay inside its worktree')
        shutil.rmtree(directory)
        for suffix in ('-source', '-preparation'):
            sibling = directory.with_name(directory.name + suffix)
            if sibling.is_dir():
                shutil.rmtree(sibling)
    if before != snapshot(root) or status != git(root, 'status', '--porcelain', '--untracked-files=all'):
        print('ui scripts: audited tree changed')
        return 1
    if result.returncode:
        return result.returncode
    print('ui scripts: ordered replay verified, 0 changes to audited tree')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
