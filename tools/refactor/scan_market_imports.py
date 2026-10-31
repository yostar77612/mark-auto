"""Resolve E4 market/history imports and literal mock patch targets without running tests."""

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
PREFIXES = (
    'quantlab.market_history',
    'quantlab.market_providers',
    'quantlab.research_core.domain.market_sessions',
    'quantlab.research_core.adapters.history_decoder',
    'quantlab.research_core.adapters.market_history',
    'quantlab.research_core.application.history_import',
    'quantlab.research_core.ports.history',
    'quantlab.research_core.ports.market_data',
)


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
        elif not embedded and isinstance(node, ast.Constant) and isinstance(node.value, str) and '\n' in node.value:
            # Executable embedded smoke programs are scanned; historical rewrite recipes are data.
            if path.startswith('tools/refactor/'):
                continue
            try:
                nested = ast.parse(node.value)
            except SyntaxError:
                continue
            found.extend(collect(nested, path, embedded=True))
    return found


def main():
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    totals = {'files': 0, 'imports': 0, 'patch_targets': 0, 'failures': []}
    for path in sorted(set(paths)):
        if not path.endswith(('.py', '.spec')) or not (ROOT / path).is_file():
            continue
        tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'), filename=path)
        found = collect(tree, path)
        totals['files'] += bool(found)
        for kind, name, line in found:
            totals['imports' if kind == 'import' else 'patch_targets'] += 1
            try:
                resolve(name, patch=kind == 'patch')
            except Exception as exc:
                totals['failures'].append({'path': path, 'line': line, 'target': name, 'error': str(exc)})
    print(json.dumps(totals, indent=2))
    (ROOT / '.tmp-layered/e4-import-resolution.json').write_text(json.dumps(totals, indent=2) + '\n', encoding='utf-8')
    return bool(totals['failures'])


if __name__ == '__main__':
    raise SystemExit(main())
