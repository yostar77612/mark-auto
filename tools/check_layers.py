"""Repo-wide spec 3.1 import gate; assignments follow inventory 08 section 2.

Scan tracked Python sources without importing product code. The existing trading
and quality gates remain independent, stricter safety checks. This gate checks
lexical imports (including local/conditional imports), as inventoried in R0;
it does not infer re-exports, callbacks, or arbitrary dynamic execution.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_trading_architecture import Finding, _module, _relative
from tools.quality_gate import git

ROOT = Path(__file__).resolve().parents[1]
LAYERS = frozenset(('domain', 'application', 'infrastructure', 'presentation', 'shared', 'composition', 'tooling'))
ALLOWED = {
    'domain': {'domain', 'shared'},
    'application': {'application', 'domain', 'shared'},
    'infrastructure': {'infrastructure', 'domain', 'shared'},
    'presentation': {'presentation', 'application', 'domain', 'shared'},
    'shared': {'shared'},
}


def load_map(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    for layer in (*data['prefixes'].values(), *data['overrides'].values()):
        if layer not in LAYERS:
            raise ValueError(f'Unknown layer: {layer}')
    if any(not prefix or not prefix.endswith('/') for prefix in data['prefixes']):
        raise ValueError('Layer prefixes must be nonempty directory paths ending in /')
    return data


def layer_for(path: str, mapping: dict) -> str | None:
    if path in mapping['overrides']:
        return mapping['overrides'][path]
    for prefix in sorted(mapping['prefixes'], key=len, reverse=True):
        if path.startswith(prefix):
            return mapping['prefixes'][prefix]
    return None


def tracked_sources(root: Path) -> tuple[str, ...]:
    return tuple(
        name
        for name in git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.py').decode('utf-8').split('\0')
        if name and not name.startswith(('tests/', 'archives/'))
    )


def module_index(paths: tuple[str, ...]) -> dict[str, str]:
    modules = {_module(path)[0]: path for path in paths}
    # Namespace packages (notably tools/) have no tracked __init__.py.
    for path in paths:
        for parent in Path(path).parents:
            if parent != Path('.'):
                modules.setdefault('.'.join(parent.parts), parent.as_posix() + '/')
    return modules


def resolve_target(name: str, modules: dict[str, str]) -> tuple[str, str | None]:
    """Resolve a from-import symbol to its longest tracked module ancestor."""
    candidate = name
    while candidate:
        if candidate in modules:
            return candidate, modules[candidate]
        candidate = candidate.rpartition('.')[0]
    return name, None


def dependency_rule(layer: str, target: str, target_path: str | None, mapping: dict) -> str | None:
    if layer in ('composition', 'tooling'):
        return None
    if target_path is not None:
        other = layer_for(target_path, mapping)
        if other is None:
            return 'unassigned-target'
        if layer == 'infrastructure' and other == 'application' and any(target_path.startswith(prefix) for prefix in mapping['ports']):
            return None
        return None if other in ALLOWED[layer] else f'{layer}-to-{other}'
    root = target.split('.')[0]
    if root in sys.stdlib_module_names or root == '__future__':
        return None
    if root == 'PySide6':
        return None if layer == 'presentation' else f'{layer}-to-pyside6'
    return None if layer == 'infrastructure' else f'{layer}-to-external-sdk'


def check_source(source: str, path: str, mapping: dict, modules: dict[str, str]) -> tuple[Finding, ...]:
    layer = layer_for(path, mapping)
    if layer is None:
        return (Finding(path, 1, 'unassigned-file', path),)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return (Finding(path, error.lineno or 1, 'invalid-syntax', ''),)
    _, package = _module(path)
    findings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _relative('.' * node.level + (node.module or ''), package)
            if base is None:
                findings.add(Finding(path, node.lineno, 'unresolved-relative-import', node.module or ''))
                continue
            names = [base if alias.name == '*' else base + '.' + alias.name for alias in node.names]
        else:
            continue
        for name in names:
            target, target_path = resolve_target(name, modules)
            # External from-imports are keyed by module, not imported symbols.
            if target_path is None and isinstance(node, ast.ImportFrom):
                target = base
            rule = dependency_rule(layer, target, target_path, mapping)
            if rule:
                findings.add(Finding(path, node.lineno, rule, target))
    return tuple(sorted(findings, key=lambda item: (item.path, item.line, item.rule, item.target)))


def finding_key(item: Finding, relocations: dict[str, str] | None = None, split_origins: dict[str, str] | None = None) -> tuple[str, str, str]:
    """Keep R0 debt identities stable across the approved whole-file moves."""
    relocations = relocations or {}
    paths = {new: old for old, new in relocations.items()}
    paths.update(split_origins or {})
    modules = {_module(new)[0]: _module(old)[0] for old, new in relocations.items()}
    modules.update({_module(new)[0]: _module(old)[0] for new, old in (split_origins or {}).items()})
    return paths.get(item.path, item.path), modules.get(item.target, item.target), item.rule


def allowlist_key(entry: dict) -> tuple[str, str, str]:
    return entry['path'], entry['target'], entry['rule']


def apply_allowlist(
    findings: tuple[Finding, ...], entries: list[dict], relocations: dict[str, str] | None = None, split_origins: dict[str, str] | None = None
) -> tuple[Finding, ...]:
    allowed = set()
    errors = []
    for entry in entries:
        key = allowlist_key(entry)
        if not entry['justification'].strip() or key in allowed:
            errors.append(Finding(entry['path'], 1, 'invalid-allowlist-entry', entry['target']))
        allowed.add(key)
    actual = {finding_key(item, relocations, split_origins) for item in findings}
    errors.extend(item for item in findings if finding_key(item, relocations, split_origins) not in allowed)
    errors.extend(Finding(path, 1, 'stale-allowlist-entry', f'{target} ({rule})') for path, target, rule in sorted(allowed - actual))
    return tuple(errors)


def restored_debts(entries: list[dict], previous: list[dict]) -> tuple[Finding, ...]:
    allowed = {allowlist_key(entry) for entry in previous}
    return tuple(Finding(entry['path'], 1, 'restored-allowlist-entry', entry['target']) for entry in entries if allowlist_key(entry) not in allowed)


def scan(root: Path, mapping: dict | None = None, entries: list[dict] | None = None, baseline_ref: str | None = None) -> tuple[Finding, ...]:
    if mapping is None:
        mapping = load_map(root / 'tools/layer_map.json')
    if entries is None:
        entries = json.loads((root / 'tools/layer_allowlist.json').read_text(encoding='utf-8'))
    paths = tracked_sources(root)
    if not paths:
        return (Finding('.', 1, 'empty-source-scope', ''),)
    modules = module_index(paths)
    findings = []
    relocation_file = root / 'tools/layer_relocations.json'
    relocations = json.loads(relocation_file.read_text(encoding='utf-8')) if relocation_file.is_file() else {}
    if len(set(relocations.values())) != len(relocations) or set(relocations) & set(relocations.values()):
        raise ValueError('Relocations must be one-to-one without chains')
    for old, new in relocations.items():
        if old in paths and new in paths:
            findings.append(Finding(new, 1, 'duplicate-relocated-source', old))
    for path in paths:
        if not (root / path).is_file():
            findings.append(Finding(path, 1, 'tracked-file-missing', path))
            continue
        findings.extend(check_source((root / path).read_text(encoding='utf-8-sig'), path, mapping, modules))
    errors = apply_allowlist(tuple(findings), entries, relocations, mapping.get('split_origins'))
    if baseline_ref and git(root, 'ls-tree', baseline_ref, '--', 'tools/layer_allowlist.json').strip():
        previous = json.loads(git(root, 'show', f'{baseline_ref}:tools/layer_allowlist.json'))
        errors += restored_debts(entries, previous)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--baseline-ref', help='Reject debt restored since this commit (CI uses HEAD^)')
    args = parser.parse_args(argv)
    try:
        findings = scan(args.root.resolve(), baseline_ref=args.baseline_ref)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f'tools/check_layers.py:1: layer-scan-failed: {type(error).__name__}')
        return 1
    for item in findings:
        print(f'{item.path}:{item.line}: {item.rule}: {item.target}')
    print(f'Repository layers: {len(findings)} finding(s)')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
