"""Measure every PR D size exception and verify inventory section 10.3."""

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = 'docs/analysis/08_REFACTOR_INVENTORY.md'
DEFAULT_BASE = '3429f2c'


def changed_paths(root, base):
    """Match the controller's A/M set relative to the committed PR head."""
    output = subprocess.check_output(
        ['git', 'diff', '--name-only', '--diff-filter=AM', '-z', base, 'HEAD', '--'],
        cwd=root,
    ).decode('utf-8')
    return sorted(p for p in output.split('\0') if p.endswith('.py') and not p.startswith(('tests/', 'tools/refactor/')))


def measure(root, base=DEFAULT_BASE):
    items = []
    for path in changed_paths(root, base):
        source = (root / path).read_text(encoding='utf-8-sig')
        count = len(source.splitlines())
        if count > 400:
            items.append(dict(path=path, line=1, name='<module>', kind='file', lines=count, limit=400))
        for node in ast.walk(ast.parse(source, filename=path)):
            if isinstance(node, ast.ClassDef):
                kind, limit = 'class', 300
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind, limit = 'function', 50
            else:
                continue
            count = node.end_lineno - node.lineno + 1
            if count > limit:
                items.append(dict(path=path, line=node.lineno, name=node.name, kind=kind, lines=count, limit=limit))
    return sorted(items, key=lambda row: (row['path'], row['line'], row['kind'], row['name']))


def check_inventory(root, items):
    source = (root / INVENTORY).read_text(encoding='utf-8')
    match = re.search(r'^### 10\.3 PR D size exceptions\n(.*?)(?=^## |^### |\Z)', source, re.M | re.S)
    if match is None:
        print('Missing section 10.3 PR D size exceptions')
        return False
    pattern = r'^\| (file|class|function) \| `([^`]+):(\d+)` \| `([^`]+)` \| (\d+) \| (.+) \|$'
    listed = Counter((path, int(line), name, kind, int(size)) for kind, path, line, name, size, reason in re.findall(pattern, match[1], re.M) if reason.strip())
    measured = Counter((r['path'], r['line'], r['name'], r['kind'], r['lines']) for r in items)
    if listed != measured:
        print(json.dumps({'missing': list((measured - listed).elements()), 'extra': list((listed - measured).elements())}, indent=2))
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--base', default=DEFAULT_BASE)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    items = measure(args.root, args.base)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    print(f'{len(changed_paths(args.root, args.base))} modules measured; {len(items)} exceeding items')
    return int(args.check and not check_inventory(args.root, items))


if __name__ == '__main__':
    raise SystemExit(main())
