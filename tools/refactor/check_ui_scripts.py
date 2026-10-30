"""Audit historical UI scripts on a detached PR C head without changing it.

The order below follows extraction, slice 1 references, slice 2 preparation and
application, then the r3 repairs and final audits. Preparation CLIs receive the
same source/output root deliberately: an applied output must be detected before
their historical overwrite check. Reference updates receive the committed owner
map. No preparation files or local reports are inputs to this audit.

An existing precommit overlay is accepted as the initial baseline. Both raw file
digests and porcelain status must remain identical, including untracked files.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys


# (script, CLI mode). Keep this explicit so added scripts cannot be silently missed.
ORDER = (
    ('extract_runtime_error.py', 'prepare'),
    ('split_ui_strings.py', 'prepare'),
    ('split_ui_modules.py', 'prepare'),
    ('split_ui_references.py', 'owners'),
    ('split_ui_tests.py', ''),
    ('split_ui_fixture_lines.py', ''),
    ('split_ui_workers.py', 'prepare'),
    ('split_ui_market.py', 'prepare'),
    ('split_ui_idea.py', 'prepare'),
    ('split_ui_inputs.py', 'prepare'),
    ('split_ui_shell.py', 'prepare'),
    ('split_ui_slice2.py', 'source'),
    ('split_ui_consumers.py', ''),
    ('split_ui_finish.py', ''),
    ('split_ui_r3b.py', ''),
    ('split_ui_r3c.py', ''),
    ('split_ui_r3d.py', ''),
    ('split_ui_r3f.py', ''),
    ('split_ui_catalog_check.py', ''),
    ('split_ui_oracles.py', 'baseline'),
    ('split_ui_verify.py', ''),
)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def snapshot(root):
    """Include dirty and untracked candidates; Git ignores remain authoritative."""
    names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0')
    return {
        os.fsdecode(name): hashlib.sha256((root / os.fsdecode(name)).read_bytes()).hexdigest()
        for name in names
        if name and (root / os.fsdecode(name)).is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Detached worktree at the committed PR C head')
    args = parser.parse_args()
    root = args.root.resolve()
    directory = root / 'tools/refactor'
    expected = {name for name, _ in ORDER}
    actual = {path.name for path in directory.glob('split_ui_*.py')} | {'extract_runtime_error.py'}
    if actual != expected:
        parser.error(f'Update ORDER: missing={sorted(actual - expected)}, obsolete={sorted(expected - actual)}')
    before_status = git(root, 'status', '--porcelain', '--untracked-files=all')
    before = snapshot(root)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', QT_QPA_PLATFORM='offscreen')
    failed = False
    for name, mode in ORDER:
        command = [sys.executable, '-B', str(directory / name)]
        if mode == 'prepare':
            command += ['--source-root', str(root), '--output-root', str(root)]
        elif mode == 'owners':
            command += ['--owners', str(directory / 'split_ui_owners.json')]
        elif mode == 'source':
            command += ['--source-root', str(root)]
        elif mode == 'baseline':
            command += ['--baseline', str(root)]
        result = subprocess.run(command, cwd=root, env=env, check=False)
        if result.returncode:
            print(f'{name}: exit {result.returncode}', flush=True)
            failed = True
    after_status = git(root, 'status', '--porcelain', '--untracked-files=all')
    after = snapshot(root)
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    if failed or changed or after_status != before_status:
        print(f'ui scripts: audit failed; changed paths={changed}')
        if after_status != before_status:
            print(after_status.decode('utf-8', errors='replace'))
        return 1
    print(f'ui scripts: {len(ORDER)} run, 0 changes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
