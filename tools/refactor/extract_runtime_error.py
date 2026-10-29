"""Extract the single runtime exception and batch exact import-only consumers."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess


TARGET = 'quantlab.shared.runtime_errors'


def extract(source):
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'RuntimeSafetyError']
    if len(classes) != 1:
        raise ValueError('Expected exactly one actual original RuntimeSafetyError definition')
    node = classes[0]
    lines = source.splitlines(keepends=True)
    definition = ''.join(lines[node.lineno - 1 : node.end_lineno])
    lines[node.lineno - 1 : node.end_lineno] = ['from quantlab.shared.runtime_errors import RuntimeSafetyError\n']
    remaining = ''.join(lines)
    return remaining, '"""Shared runtime admission and durable-operation rejection type."""\n\n' + definition


def update_imports(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    replacements = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module == TARGET:
            continue
        moved = [alias for alias in node.names if alias.name == 'RuntimeSafetyError']
        if not moved:
            continue
        # Actual producer consumers import through runtime_support or desktop_runtime.
        if node.module not in ('runtime_support', 'desktop_runtime', 'quantlab.runtime_support', 'quantlab.desktop_runtime'):
            raise ValueError('Unexpected RuntimeSafetyError import owner: ' + str(node.module))
        remaining = [alias for alias in node.names if alias not in moved]
        statements = [ast.unparse(ast.ImportFrom(module=node.module, names=remaining, level=node.level))] if remaining else []
        statements.append(ast.unparse(ast.ImportFrom(module=TARGET, names=moved, level=0)))
        indentation = ' ' * node.col_offset
        replacement = ('\n' + indentation).join(statements)
        replacements.append((offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset, replacement))
    for start, end, text in sorted(replacements, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Preparation cannot overwrite product sources')
    tracked = subprocess.run(['git', 'ls-files', '-z', '--', '*.py'], cwd=root, check=True, capture_output=True).stdout.decode('utf-8').split('\0')
    sources = {}
    source_hashes = {}
    for name in tracked:
        if not name or name.startswith(('archives/', 'MarkAuto-handoff')):
            continue
        path = root / name
        raw = path.read_bytes()
        if b'RuntimeSafetyError' not in raw:
            continue
        source = raw.decode('utf-8-sig')
        if name == 'quantlab/runtime_support.py':
            source, leaf = extract(source)
            sources['quantlab/shared/runtime_errors.py'] = leaf
        changed = update_imports(source)
        if changed != raw.decode('utf-8-sig'):
            sources[name] = changed
            source_hashes[name] = hashlib.sha256(raw).hexdigest()
    # Prepared C application modules must depend on the true shared leaf already.
    for path in output.rglob('*.py'):
        if 'fixture_tests' in path.parts or '__pycache__' in path.parts:
            continue
        name = path.relative_to(output).as_posix()
        if name in sources:
            continue
        source = path.read_text(encoding='utf-8-sig')
        if 'RuntimeSafetyError' in source:
            changed = update_imports(source)
            if changed != source:
                sources[name] = changed
    for name, source in sources.items():
        ast.parse(source)
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')
    shared = output / 'quantlab/shared/__init__.py'
    if not shared.exists():
        shared.write_text('"""Pure shared contracts for Quantlab layers."""\n', encoding='utf-8')
    relocations = json.loads((root / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
    profile_inputs = {
        'desktop_chatgpt_auth.py',
        'desktop_chatgpt_provider.py',
        'quantlab/core.py',
        'quantlab/backtest.py',
        'quantlab/research.py',
        'quantlab/strategies.py',
        'quantlab/provider.py',
        'quantlab/data.py',
    }
    profile_inputs |= {relocations.get(name, name) for name in profile_inputs}
    changed_profile_inputs = sorted(set(sources) & profile_inputs)
    report = {
        'definition': TARGET + '.RuntimeSafetyError',
        'actual_class_copies': 1,
        'consumer_paths': sorted(sources),
        'original_source_sha256': source_hashes,
        'historical_fixtures_modified': False,
        'changed_source_profile_inputs': changed_profile_inputs,
        'new_producer_profile_required': bool(changed_profile_inputs),
    }
    (output / 'runtime-error-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(
        json.dumps(
            {
                'class_copies': 1,
                'consumer_files': len(sources),
                'changed_source_profile_inputs': changed_profile_inputs,
                'new_producer_profile_required': bool(changed_profile_inputs),
            }
        )
    )


if __name__ == '__main__':
    main()
