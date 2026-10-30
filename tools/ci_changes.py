"""Decide whether a pull request changed only documentation that no test reads.

Used by the Quantlab workflow to skip the heavy test groups for pure prose
changes. Fail-closed: anything unknown, unreadable, non-PR or referenced by code
or tests is reported as ``code=true`` so the full gates run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Directories consumed wholesale (globbed or contract-checked) by tests/runtime.
PROTECTED_PREFIXES = ('docs/adr/', 'docs/agent/', 'docs/skills/', 'packaging/', 'tests/', 'archives/', 'quantlab/', 'tools/')
SCAN_DIRECTORIES = ('tests', 'tools', 'packaging', 'quantlab', 'desktop_app', '.github')
SCAN_SUFFIXES = {'.py', '.ps1', '.yml', '.yaml', '.json', '.toml', '.spec', '.iss', '.txt', '.md', '.cfg'}


def is_doc_candidate(path: str) -> bool:
    if path == '.github/pull_request_template.md':
        return True
    if path.startswith(PROTECTED_PREFIXES) or not path.endswith('.md'):
        return False
    return path.startswith('docs/') or '/' not in path or path.startswith('examples/')


def corpus(root: Path, exclude: set[str]) -> str:
    chunks = []
    candidates = [p for p in root.glob('*') if p.is_file()]
    for name in SCAN_DIRECTORIES:
        base = root / name
        if base.is_dir():
            candidates.extend(p for p in base.rglob('*') if p.is_file())
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if rel in exclude or path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        try:
            chunks.append(path.read_text(encoding='utf-8-sig', errors='ignore'))
        except OSError:
            raise RuntimeError(f'unreadable {rel}')
    return '\n'.join(chunks)


def docs_only(changed: list[str], root: Path = ROOT) -> bool:
    if not changed or not all(is_doc_candidate(path) for path in changed):
        return False
    text = corpus(root, set(changed))
    for path in changed:
        if path in text or Path(path).name in text:
            return False  # a test, tool or workflow reads this file
    return True


def changed_files(base: str, head: str, root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ['git', 'diff', '--name-only', '-z', '--no-renames', f'{base}...{head}'],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode('utf-8')
    return [item for item in out.split('\0') if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', default=os.environ.get('GITHUB_EVENT_NAME', ''))
    parser.add_argument('--base', default='')
    parser.add_argument('--head', default='')
    args = parser.parse_args()
    code = True
    if args.event == 'pull_request' and args.base and args.head:
        try:
            files = changed_files(args.base, args.head)
            code = not docs_only(files)
            print(f'changed files: {len(files)}; docs-only: {not code}')
        except Exception as error:  # fail closed: run everything
            print(f'change detection failed ({type(error).__name__}); running all gates')
    else:
        print('not a pull_request event; running all gates')
    line = f'code={"true" if code else "false"}'
    print(line)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
