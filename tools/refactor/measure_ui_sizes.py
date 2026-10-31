"""Measure PR C desktop size exceptions and verify inventory section 10.1."""

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = 'docs/analysis/08_REFACTOR_INVENTORY.md'


def measure(root):
    paths = subprocess.check_output(
        ['git', 'diff', '--name-only', '--diff-filter=AM', '6b78239', '--', 'desktop_app/'],
        cwd=root,
        text=True,
        encoding='utf-8',
    ).splitlines()
    items = []
    for name in sorted(paths):
        if not name.endswith('.py'):
            continue
        source = (root / name).read_text(encoding='utf-8-sig')
        count = len(source.splitlines())
        if count > 400:
            items.append(dict(path=name, line=1, name='<module>', kind='file', lines=count, limit=400))
        tree = ast.parse(source, filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                kind, limit = 'class', 300
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind, limit = 'function', 50
            else:
                continue
            count = node.end_lineno - node.lineno + 1
            if count > limit:
                items.append(dict(path=name, line=node.lineno, name=node.name, kind=kind, lines=count, limit=limit))
    return sorted(items, key=lambda row: (row['path'], row['line'], row['kind'], row['name']))


def check_inventory(root, items):
    source = (root / INVENTORY).read_text(encoding='utf-8')
    match = re.search(r'^### 10\.1 PR C size exceptions\n(.*?)(?=^## |^### |\Z)', source, re.M | re.S)
    if match is None:
        print('Missing section 10.1 PR C size exceptions')
        return False
    pattern = r'^\| `([^`]+):(\d+)` \| `([^`]+)` \| (file|class|function) \| (\d+) \| (.+) \|$'
    listed = Counter((p, int(line), name, kind, int(size)) for p, line, name, kind, size, reason in re.findall(pattern, match[1], re.M) if reason.strip())
    measured = Counter((r['path'], r['line'], r['name'], r['kind'], r['lines']) for r in items)
    if listed != measured:
        print(json.dumps({'missing': list((measured - listed).elements()), 'extra': list((listed - measured).elements())}, indent=2))
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    items = measure(args.root)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return int(args.check and not check_inventory(args.root, items))


if __name__ == '__main__':
    raise SystemExit(main())
