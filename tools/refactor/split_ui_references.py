"""Scripted imports and patch selectors for the strings/forms/charts split."""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tokenize

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.refactor import move_desktop_app as relocation


def expression_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return '.'.join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else ''


def owner_prefix(value, owners):
    return next((name for name in sorted(owners, key=len, reverse=True) if value == name or value.startswith(name + '.')), None)


def rewrite_source(source, path, owners, module_names):
    tree = ast.parse(source, filename=path)
    lines, starts = relocation.offsets(source)
    aliases = []
    imports = {}
    import_bases = {}
    import_ranges = []
    moved = {old: new for old, new in owners.items() if old != new}
    relevant_modules = {name.rpartition('.')[0] for name in moved}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            start, stop = relocation.span(node, lines, starts)
            statements = [source[start:stop]]
            for alias in node.names:
                if alias.name in relevant_modules:
                    aliases.append((alias.asname or alias.name, alias.name, node, alias))
            imports[id(node)] = (node, statements)
            import_bases[id(node)] = None
            import_ranges.append(relocation.span(node, lines, starts))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                package = relocation.module(path) if path.endswith('/__init__.py') else relocation.module(path).rpartition('.')[0]
                parts = package.split('.')
                base = '.'.join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
            grouped = defaultdict(list)
            for alias in node.names:
                old = base + '.' + alias.name
                if old in module_names and old in relevant_modules:
                    aliases.append((alias.asname or alias.name, old, node, alias))
                target = owners.get(old, old)
                module, _, name = target.rpartition('.')
                local = alias.asname or (alias.name if name != alias.name else None)
                grouped[module].append(name + (' as ' + local if local else ''))
            statements = ['from ' + module + ' import ' + ', '.join(names) for module, names in grouped.items()]
            if all(base + '.' + alias.name not in moved for alias in node.names):
                start, stop = relocation.span(node, lines, starts)
                statements = [source[start:stop]]
            imports[id(node)] = (node, statements)
            import_bases[id(node)] = base
            import_ranges.append(relocation.span(node, lines, starts))
    edits, mapped_ranges, alias_imports = [], [], defaultdict(dict)
    dynamic = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        name = expression_name(node)
        if not name:
            continue
        for prefix, module, imported, alias in aliases:
            if not name.startswith(prefix + '.'):
                continue
            resolved = module + name[len(prefix) :]
            old = owner_prefix(resolved, owners)
            if old is None or owners[old] == old:
                continue
            if path.startswith('tests/') and old in ('quantlab.runtime_support.RuntimeSafetyError', 'quantlab.desktop_runtime.RuntimeSafetyError'):
                # These actual raiser modules still import/use the unique leaf.
                # Retain their identity assertions instead of making them tautologies.
                continue
            target = owners[old]
            target_module, _, symbol = target.rpartition('.')
            binding = '_c_' + re.sub(r'\W+', '_', prefix + '_' + symbol)
            alias_imports[id(imported)][binding] = 'from ' + target_module + ' import ' + symbol + ' as ' + binding
            left, right = relocation.span(node, lines, starts)
            edits.append((left, right, binding + resolved[len(old) :]))
            mapped_ranges.append((left, right))
            break
    # Only change actual patch/import selectors. Historical producer fixture
    # text never contains these definition paths and is not part of this scope.
    pattern = re.compile(r'(?<![\w.])(?:' + '|'.join(re.escape(name) for name in sorted(moved, key=len, reverse=True)) + r')(?![\w])')
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING:
            continue
        start = starts[token.start[0] - 1] + token.start[1]
        stop = starts[token.end[0] - 1] + token.end[1]
        if any(left <= start < right for left, right in import_ranges):
            continue
        changed = pattern.sub(lambda match: moved[match[0]], token.string)
        if changed != token.string:
            edits.append((start, stop, changed))
    # patch.object(module_alias, 'member') must follow the same concrete owner
    # as an ordinary module_alias.member access. Keep side-effect signatures.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not expression_name(node.func).endswith('patch.object') or len(node.args) < 2:
            continue
        receiver, member = expression_name(node.args[0]), node.args[1]
        if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
            continue
        for prefix, module, imported, alias in aliases:
            if receiver != prefix:
                continue
            target = owners.get(module + '.' + member.value)
            if not target or target == module + '.' + member.value:
                continue
            changed = ast.parse(ast.unparse(node), mode='eval').body
            changed.func = changed.func.value
            changed.args = [ast.Constant(value=target), *changed.args[2:]]
            for keyword in changed.keywords:
                if (
                    keyword.arg == 'side_effect'
                    and isinstance(keyword.value, ast.Lambda)
                    and keyword.value.args.args
                    and target.startswith('quantlab.research_core.application.')
                    and not keyword.value.args.vararg
                ):
                    keyword.value.args.args.insert(0, ast.arg(arg='ports'))
            left, right = relocation.span(node, lines, starts)
            edits.append((left, right, ast.unparse(ast.fix_missing_locations(changed))))
            mapped_ranges.append((left, right))
            break
    removed_aliases = defaultdict(set)
    for prefix, module, imported, alias in aliases:
        used = False
        for node in ast.walk(tree):
            name = expression_name(node) if isinstance(node, (ast.Attribute, ast.Name)) else ''
            if name != prefix and not name.startswith(prefix + '.'):
                continue
            left, _ = relocation.span(node, lines, starts)
            if not any(start <= left < stop for start, stop in mapped_ranges):
                used = True
                break
        if not used and alias_imports[id(imported)]:
            removed_aliases[id(imported)].add(id(alias))
    for key, (node, statements) in imports.items():
        if removed_aliases[key]:
            remaining = [alias for alias in node.names if id(alias) not in removed_aliases[key]]
            if isinstance(node, ast.Import):
                statements = ['import ' + ', '.join(alias.name + (' as ' + alias.asname if alias.asname else '') for alias in remaining)] if remaining else []
            else:
                grouped = defaultdict(list)
                for alias in remaining:
                    old = import_bases[key] + '.' + alias.name
                    module, _, name = owners.get(old, old).rpartition('.')
                    local = alias.asname or (alias.name if name != alias.name else None)
                    grouped[module].append(name + (' as ' + local if local else ''))
                statements = ['from ' + module + ' import ' + ', '.join(names) for module, names in grouped.items()]
        statements += list(alias_imports[key].values())
        start, stop = relocation.span(node, lines, starts)
        replacement = ('\n' + ' ' * node.col_offset).join(statements)
        if replacement != source[start:stop]:
            edits.append((start, stop, replacement))
    for prefix, module, imported, alias in aliases:
        if '.' in prefix:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name) or node.id != prefix or not isinstance(node.ctx, ast.Load):
                continue
            left, right = relocation.span(node, lines, starts)
            if not any(start <= left < stop for start, stop in mapped_ranges):
                dynamic.append({'line': node.lineno, 'alias': prefix, 'module': module})
    selected = []
    for edit in sorted(set(edits), key=lambda item: (item[0], -item[1])):
        if not selected or edit[0] >= selected[-1][1]:
            selected.append(edit)
    for start, stop, value in reversed(selected):
        source = source[:start] + value + source[stop:]
    ast.parse(source, filename=path)
    return source, dynamic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owners', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    owners = json.loads(args.owners.read_text(encoding='utf-8'))
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.py'], cwd=root).decode().split('\0')
    modules = {relocation.module(path.relative_to(root).as_posix()) for path in (root / 'desktop_app').rglob('*.py')}
    paths = sorted(
        set(paths) | {path.relative_to(root).as_posix() for base in ('desktop_app', 'quantlab/research_core') for path in (root / base).rglob('*.py')}
    )
    changed, unresolved = [], {}
    for name in paths:
        if not name or name.startswith(('archives/', 'tools/refactor/')):
            continue
        path = root / name
        original = path.read_text(encoding='utf-8-sig')
        updated, dynamic = rewrite_source(original, name, owners, modules)
        if updated != original:
            path.write_text(updated, encoding='utf-8', newline='\n')
            changed.append(name)
        if dynamic:
            unresolved[name] = dynamic
    print(json.dumps({'changed': changed, 'dynamic_review': unresolved}, indent=2))


if __name__ == '__main__':
    main()
