"""Measure every changed desktop source and scan untracked split responsibilities."""

from __future__ import annotations

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/shell/window.py').is_file():
    print('split_ui_verify.py: already applied')
    raise SystemExit(0)

import ast
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import check_layers

ROOT = Path(__file__).resolve().parents[2]


def changed_files():
    tracked = subprocess.check_output(['git', 'diff', '--name-only', '--diff-filter=ACMRT'], cwd=ROOT).decode().splitlines()
    added = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT).decode().splitlines()
    return sorted(set(tracked + added))


def measurements():
    rows = []
    for name in changed_files():
        if not name.startswith('desktop_app/') or not name.endswith('.py'):
            continue
        source = (ROOT / name).read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        functions, classes = [], []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
                row = {'name': node.name, 'line': start, 'lines': node.end_lineno - start + 1}
                (classes if isinstance(node, ast.ClassDef) else functions).append(row)
        rows.append({'path': name, 'lines': len(source.splitlines()), 'classes': classes, 'functions': functions})
    return rows


def main():
    directory = ROOT / '.tmp-layered'
    rows = measurements()
    (directory / 'slice2-sizes.json').write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
    paths = sorted(
        set(check_layers.tracked_sources(ROOT)) | {name for name in changed_files() if name.endswith('.py') and not name.startswith(('tests/', 'archives/'))}
    )
    with patch.object(check_layers, 'tracked_sources', return_value=tuple(paths)):
        findings = check_layers.scan(ROOT)
    if findings:
        print('\n'.join(map(str, findings)))
        raise SystemExit(1)
    print(json.dumps({'all_product_sources_scanned': len(paths), 'layer_findings': 0, 'desktop_files_measured': len(rows)}))


if __name__ == '__main__':
    main()
