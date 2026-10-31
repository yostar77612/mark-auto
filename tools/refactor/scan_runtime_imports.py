"""Resolve E3 runtime imports and literal mock patch targets without running tests."""

import ast
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
PREFIXES = ('quantlab', 'desktop_app')


def resolve(name, *, patch=False):
    parts = name.replace(':', '.').split('.')
    for size in range(len(parts), 0, -1):
        try:
            value = importlib.import_module('.'.join(parts[:size]))
        except ModuleNotFoundError as exc:
            if exc.name != '.'.join(parts[:size]) and not '.'.join(parts[:size]).startswith(exc.name + '.'):
                raise
            continue
        for part in parts[size:]:
            value = getattr(value, part)
        return
    raise ImportError(name)


def collect(tree, path, embedded=False):
    found = []
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update({a.asname or a.name.split('.')[0]: a.name if a.asname else a.name.split('.')[0] for a in node.names})
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            aliases.update({a.asname or a.name: node.module + '.' + a.name for a in node.names})
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(('import', a.name, node.lineno) for a in node.names if a.name.startswith(PREFIXES))
        elif isinstance(node, ast.ImportFrom):
            package = path.removesuffix('.py').replace('/', '.').rpartition('.')[0]
            if path.endswith('/__init__.py'):
                package = path.removesuffix('/__init__.py').replace('/', '.')
            module = node.module or ''
            if node.level:
                if embedded:
                    continue  # Relative injection snippets are fixture data, not executable imports.
                module = importlib.util.resolve_name('.' * node.level + module, package)
            for alias in node.names:
                target = module + '.' + alias.name
                if module.startswith(PREFIXES) or target.startswith(PREFIXES):
                    found.append(('import', target, node.lineno))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            name = ast.unparse(node.func)
            target = node.args[0].value
            if name.endswith('patch') and target.startswith(PREFIXES):
                if any(k.arg == 'create' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                    target = target.rpartition('.')[0]
                found.append(('patch', target, node.lineno))
        elif isinstance(node, ast.Call) and ast.unparse(node.func).endswith('patch.object') and len(node.args) >= 2:
            receiver, attr = ast.unparse(node.args[0]), node.args[1]
            head, *tail = receiver.split('.')
            if head in aliases and isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                target = '.'.join([aliases[head], *tail, attr.value])
                if target.startswith(PREFIXES):
                    if any(k.arg == 'create' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                        target = target.rpartition('.')[0]
                    found.append(('patch', target, node.lineno))
        elif not embedded and isinstance(node, ast.Constant) and isinstance(node.value, str) and '\n' in node.value:
            # Executable embedded smoke programs are scanned; historical rewrite recipes are data.
            if path.startswith('tools/refactor/') or path == 'tests/test_layer_gate.py':
                continue
            try:
                nested = ast.parse(node.value)
            except SyntaxError:
                continue
            found.extend(collect(nested, path, embedded=True))
    return found


def main():
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    totals = {'files': 0, 'scanned_files': 0, 'imports': 0, 'patch_targets': 0, 'platform_only': [], 'failures': []}
    for path in sorted(set(paths)):
        if not path.endswith(('.py', '.spec')) or not (ROOT / path).is_file():
            continue
        tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'), filename=path)
        found = collect(tree, path)
        totals['files'] += bool(found)
        totals['scanned_files'] += 1
        for kind, name, line in found:
            totals['imports' if kind == 'import' else 'patch_targets'] += 1
            try:
                resolve(name, patch=kind == 'patch')
            except Exception as exc:
                # This class is explicitly skipped on Windows; retain its target as evidence.
                linux_scope = any(
                    isinstance(n, ast.ClassDef)
                    and n.name == 'ProcDisappearanceTests'
                    and n.lineno <= line <= n.end_lineno
                    and any("sys.platform.startswith('linux')" in ast.unparse(d) for d in n.decorator_list)
                    for n in tree.body
                )
                if linux_scope and name.endswith('.os.killpg') and sys.platform == 'win32':
                    totals['platform_only'].append({'path': path, 'line': line, 'target': name, 'reason': 'Linux-only class skipped on Windows'})
                    continue
                totals['failures'].append({'path': path, 'line': line, 'target': name, 'error': str(exc)})
    print(json.dumps(totals, indent=2))
    (ROOT / '.tmp-layered/e6-import-resolution.json').write_text(json.dumps(totals, indent=2) + '\n', encoding='utf-8')
    return bool(totals['failures'])


if __name__ == '__main__':
    raise SystemExit(main())
