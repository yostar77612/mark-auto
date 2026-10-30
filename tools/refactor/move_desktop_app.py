"""Prepare/apply the fixed R0 desktop relocation; plan/check never write files.

Run from a clean PR-B worktree after A is merged. Review --check output first.
The controller records GitNexus impact and owns commits, CI and independent QA.
"""

from __future__ import annotations

import argparse
import ast
import copy
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import pprint
import re
import subprocess
import tokenize

if __package__ in (None, ""):
    from adapt_test_paths import configure, adapt
    from repair_paths import repair
else:
    from .adapt_test_paths import configure, adapt
    from .repair_paths import repair

BASE_MAPPING_SHA = 'b1f30593fa4736ea17ef5eca319a91de9e2f05411171e353100b8303d32942e2'
MAPPING_SHA = 'fa66be37970e64bbe132d90645c505d7120de6d7680784ec02e9fc6a3f2d3e17'
MANIFEST = 'desktop_chatgpt_dependency_manifest.json'
ADAPTER = 'quantlab/assistant/adapters/chatgpt/'
PROFILE = 'LAYERED_PATHS_SIWC_PROFILE_V1'
PROTECTED = {
    'tools/layer_allowlist.json',
    'tools/layer_relocations.json',
    'docs/analysis/07_LAYERED_REFACTOR_SPEC.md',
    'docs/analysis/08_REFACTOR_INVENTORY.md',
}
SUFFIXES = {'.py', '.spec', '.toml', '.yml', '.yaml', '.json', '.ps1', '.md'}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def module(path):
    parts = Path(path).with_suffix('').parts
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def read_mapping(root):
    raw = (root / 'tools/layer_relocations.json').read_bytes()
    digest = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
    if digest not in (BASE_MAPPING_SHA, MAPPING_SHA):
        raise ValueError('R0 mapping changed; do not regenerate its frozen identity')
    result = json.loads(raw)
    if digest == BASE_MAPPING_SHA:
        if result['desktop_pages/__init__.py'] != 'desktop_app/shell/__init__.py':
            raise ValueError('Unexpected original initializer destination')
        result['desktop_pages/__init__.py'] = 'desktop_app/shell/pages.py'
    if hashlib.sha256((json.dumps(result, indent=2) + '\n').encode()).hexdigest() != MAPPING_SHA:
        raise ValueError('Only the one reviewed initializer destination may change')
    if len(result) != 102 or len(set(result.values())) != 102:
        raise ValueError('Expected the approved one-to-one 102-source relocation')
    return result


@lru_cache(maxsize=8)
def replacement_pattern(keys):
    return re.compile(r'(?<![\w.])(' + '|'.join(re.escape(key) for key in sorted(keys, key=len, reverse=True)) + r')(?![\w/]|\.py\b)')


def substitutions(text, pairs):
    if not pairs:
        return text
    # One pass avoids cascading replacements; .py names are physical paths,
    # not dotted modules (legacy provenance keys intentionally keep them).
    return replacement_pattern(tuple(pairs)).sub(lambda found: pairs[found[0]], text)


def strings(text, moves, *, physical=False):
    if 'desktop' not in text and 'quantlab' not in text:
        return text
    text = substitutions(text, {module(old): module(new) for old, new in moves.items()})
    paths = dict(moves)
    if not physical:
        paths = {old: new for old, new in paths.items() if old not in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py')}
    for old, new in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(r'(?<![\w])' + re.escape(old), lambda match: new, text)
        text = re.sub(r'(?<![\w])' + re.escape(old.replace('/', '\\\\')), lambda match: new.replace('/', '\\\\'), text)
    if physical:
        text = re.sub(r'(?<![\w/])' + re.escape(MANIFEST), ADAPTER + MANIFEST, text)
    for old, new in (('desktop_pages/', 'desktop_app/'), ('desktop_trading/', 'desktop_app/features/trading/'), ('desktop_smoke/', 'desktop_app/smoke/')):
        text = text.replace(old + '*.py', new + '**/*.py').replace(old + '**/*.py', new + '**/*.py')
    text = text.replace('desktop_trading/', 'desktop_app/features/trading/')
    return text


def offsets(source):
    lines = source.splitlines(keepends=True)
    starts, total = [], 0
    for line in lines:
        starts.append(total)
        total += len(line)
    return lines, starts


def span(node, lines, starts):
    def position(row, column):
        return starts[row - 1] + len(lines[row - 1].encode('utf-8')[:column].decode('utf-8'))

    return position(node.lineno, node.col_offset), position(node.end_lineno, node.end_col_offset)


def python_source(source, old_path, moves):
    if 'desktop' not in source and old_path not in moves:
        return source
    tree = ast.parse(source, filename=old_path)
    lines, starts = offsets(source)
    modules = {module(old): module(new) for old, new in moves.items()}
    package = module(old_path) if old_path.endswith('/__init__.py') else module(old_path).rpartition('.')[0]
    edits, protected = [], []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == 'BASELINE' for name in node.targets):
            protected.append(span(node, lines, starts))
    if old_path == 'tests/test_layer_gate.py':
        for method in ast.walk(tree):
            if isinstance(method, ast.FunctionDef) and method.name == 'test_relocated_debt_cannot_expand_or_replace_original_debt':
                protected.extend(
                    span(node, lines, starts)
                    for node in ast.walk(method)
                    if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == 'entry' for name in node.targets)
                )
    for node in ast.walk(tree):
        replacement = None
        if isinstance(node, ast.Import):
            replacement = 'import ' + ', '.join(modules.get(alias.name, alias.name) + (' as ' + alias.asname if alias.asname else '') for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                parts = package.split('.')
                base = '.'.join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
            rows = []
            for alias in node.names:
                target = base + '.' + alias.name
                if target in modules:
                    parent, _, name = modules[target].rpartition('.')
                    suffix = alias.asname or (alias.name if name != alias.name else None)
                    rows.append(f'from {parent} import {name}' + (' as ' + suffix if suffix else ''))
                else:
                    rows.append(f'from {modules.get(base, base)} import {alias.name}' + (' as ' + alias.asname if alias.asname else ''))
            parents = [row.split(' import ', 1)[0] for row in rows]
            selectors = [row.split(' import ', 1)[1] for row in rows]
            original_selectors = [alias.name + (' as ' + alias.asname if alias.asname else '') for alias in node.names]
            if len(set(parents)) == 1 and selectors == original_selectors:
                start, stop = span(node, lines, starts)
                replacement = re.sub(r'^from\s+\S+(?=\s+import\b)', parents[0], source[start:stop], count=1)
            else:
                replacement = ('\n' + ' ' * node.col_offset).join(rows)
            if not node.level and base not in modules and not any(base + '.' + alias.name in modules for alias in node.names):
                replacement = None
            if node.level and moves.get(old_path, old_path) == old_path and not any(base + '.' + alias.name in modules for alias in node.names):
                replacement = None
        if replacement is not None:
            start, stop = span(node, lines, starts)
            if source[start:stop] != replacement:
                edits.append((start, stop, replacement))
    # Token edits preserve comments, quote style, frozen producer data and EOLs.
    imported = {node.names[0].asname for node in ast.walk(tree) if isinstance(node, ast.Import) and len(node.names) == 1 and node.names[0].asname}
    references = {old: new for old, new in modules.items() if old not in imported}
    import_spans = [(start, stop) for start, stop, _ in edits]
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for token in tokens:
        start = starts[token.start[0] - 1] + token.start[1] if token.start[0] <= len(starts) else len(source)
        stop = starts[token.end[0] - 1] + token.end[1] if token.end[0] <= len(starts) else len(source)
        if any(left <= start < right for left, right in (*import_spans, *protected)):
            continue
        if token.type == tokenize.STRING:
            changed = strings(token.string, moves)
            if changed != token.string:
                edits.append((start, stop, changed))
    # Attribute expressions denote imported modules; canonical names may be used
    # without an import (e.g. tests inspecting sys.modules), so rewrite all names.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Name)):
            continue
        parts, current = [], node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name) or not current.id.startswith('desktop_'):
            continue
        text = '.'.join([current.id, *reversed(parts)])
        changed = substitutions(text, references)
        if changed != text:
            start, stop = span(node, lines, starts)
            if not any(left <= start < right for left, right in (*import_spans, *protected)):
                edits.append((start, stop, changed))
    # Keep the outermost attribute edit, rather than editing each nested Name.
    selected = []
    for edit in sorted(edits, key=lambda item: (item[0], -item[1])):
        if not selected or edit[0] >= selected[-1][1]:
            selected.append(edit)
    for start, stop, replacement in reversed(selected):
        source = source[:start] + replacement + source[stop:]
    if old_path == 'desktop_icon.py':
        source = source.replace('Path(__file__).resolve().parent', 'Path(__file__).resolve().parents[2]')
    if old_path == 'desktop_ui.py':
        source = source.replace('Path(__file__).parent', 'Path(__file__).parents[2]')
        physical = {name: moves[name] for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py')}
        physical[MANIFEST] = ADAPTER + MANIFEST
        source = source.replace('(source_root / name)', '(source_root / ' + repr(physical) + '.get(name, name))')
    if old_path == 'desktop_chatgpt_provider.py':
        source = source.replace(
            "raw=(root/name).read_bytes()", "raw=(root/{'desktop_chatgpt_auth.py':'auth.py','desktop_chatgpt_provider.py':'provider.py'}[name]).read_bytes()"
        )
    ast.parse(source, filename=moves.get(old_path, old_path))
    return source


def layer_map(source, moves):
    data = json.loads(source)
    overrides = {moves.get(path, path): layer for path, layer in data['overrides'].items()}
    for old, new in moves.items():
        if new not in overrides:
            prefixes = sorted(data['prefixes'], key=len, reverse=True)
            overrides[new] = next(data['prefixes'][prefix] for prefix in prefixes if old.startswith(prefix))
    data['overrides'] = overrides
    data['prefixes'].pop('desktop_pages/', None)
    data['prefixes'].pop('desktop_trading/', None)
    data['prefixes'].update(
        {
            'desktop_app/shell/': 'presentation',
            'desktop_app/components/': 'presentation',
            'desktop_app/features/': 'presentation',
            'desktop_app/strings/': 'shared',
            'desktop_app/smoke/': 'tooling',
            'quantlab/assistant/adapters/': 'infrastructure',
            'quantlab/research_core/adapters/': 'infrastructure',
        }
    )
    data['overrides']['desktop_app/__init__.py'] = 'presentation'
    for path in ('quantlab/assistant/__init__.py', 'quantlab/research_core/__init__.py'):
        data['overrides'][path] = 'shared'
    return json.dumps(data, indent=2) + '\n'


def add_profile(source, outputs, moves):
    if PROFILE in source:
        return source
    tree = ast.parse(source)
    original = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == 'ATOMIC_REPLACE_SIWC_PROFILE_V1' for name in node.targets)
    )
    profile = copy.deepcopy(ast.literal_eval(original.value.args[0]))
    literal_before = ast.get_source_segment(source, original)
    profile['protocol'] = 'mark_auto_0_2_2_campaign_layered_paths_siwc_v1'
    for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
        for name in implementation['source_sha256']:
            raw = outputs[moves[name]].encode('utf-8').replace(b'\r\n', b'\n')
            implementation['source_sha256'][name] = hashlib.sha256(raw.replace(b'\n', b'\r\n') if index else raw).hexdigest()
    literal = (
        '\n# Reviewed mechanical-path producer; all earlier literal blocks remain exact.\n'
        + PROFILE
        + ' = freeze('
        + pprint.pformat(profile, width=150, sort_dicts=False)
        + ')\n\n'
    )
    source = source.replace('SUPPORTED_PRODUCERS = (', literal + 'SUPPORTED_PRODUCERS = (', 1)
    source = source.replace(
        'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, ATOMIC_REPLACE_SIWC_PROFILE_V1)',
        'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, ATOMIC_REPLACE_SIWC_PROFILE_V1, ' + PROFILE + ')',
        1,
    )
    # The historical frozen literal region must remain exactly present.
    old_region = ast.get_source_segment(
        source,
        next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == 'ATOMIC_REPLACE_SIWC_PROFILE_V1' for name in node.targets)
        ),
    )
    if old_region != literal_before:
        raise ValueError('Historical producer block changed')
    return source


def prepare(root, moves):
    names = git(root, 'ls-files', '-z').decode('utf-8').split('\0')
    outputs, originals = {}, {}
    for old in filter(None, names):
        path = root / old
        if not path.is_file() or old in PROTECTED or old.startswith(('archives/', 'docs/agent/history/', 'tools/refactor/')):
            continue
        if path.suffix not in SUFFIXES and old != '.gitattributes':
            continue
        raw = path.read_bytes()
        try:
            source = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        originals[old] = source
        if old == 'quantlab/saved_candidate_pool.py':
            continue
        if old == 'tools/layer_map.json':
            changed = layer_map(source, moves)
        else:
            changed = python_source(source, old, moves) if path.suffix == '.py' else source
            changed = configure(old, changed, moves, strings, MANIFEST, ADAPTER)
        outputs[moves.get(old, ADAPTER + MANIFEST if old == MANIFEST else old)] = changed
    pool = 'quantlab/saved_candidate_pool.py'
    outputs[pool] = add_profile(originals[pool], outputs, moves)
    for target in moves.values():
        for directory in Path(target).parents:
            if directory == Path('.'):
                break
            init = (directory / '__init__.py').as_posix()
            if init not in outputs and not (root / init).exists():
                outputs[init] = ''
    return originals, adapt(outputs, originals, moves, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--expected-head')
    parser.add_argument('--ruff', type=Path, help='Existing pinned Ruff executable; batch-format non-frozen sources after applying')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--plan', action='store_true')
    action.add_argument('--check', action='store_true')
    action.add_argument('--apply', action='store_true')
    action.add_argument('--repair', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
        raise ValueError('Run at the exact intended Git root')
    moves = read_mapping(root)
    if args.repair:
        if args.expected_head != git(root, 'rev-parse', 'HEAD').decode().strip():
            raise ValueError('Repair requires the exact reviewed --expected-head')
        print(json.dumps({'repaired': repair(root, moves)}))
        if args.ruff:
            subprocess.run([str(args.ruff.resolve()), 'format', '.'], cwd=root, check=True)
        return 0
    if args.plan or not (args.check or args.apply):
        print(json.dumps({'state': 'plan_only', 'moves': moves, 'data_move': {MANIFEST: ADAPTER + MANIFEST}}, ensure_ascii=False, indent=2))
        return 0
    if not all((root / old).is_file() for old in moves):
        complete = all((root / new).is_file() for new in moves.values()) and not any((root / old).exists() for old in moves)
        if complete and (root / (ADAPTER + MANIFEST)).is_file() and not (root / MANIFEST).exists():
            print(json.dumps({'state': 'already_moved_needs_validation', 'moved_files': 102}))
            return 0
        raise ValueError('Partial/unknown move state; inspect before resuming')
    originals, outputs = prepare(root, moves)
    changed = [path for path, source in outputs.items() if source != originals.get(next((old for old, new in moves.items() if new == path), path))]
    report = {
        'state': 'planned',
        'moved_files': len(moves),
        'changed_or_added': changed,
        'manual_review_required': [
            'versioned producer tuple and all legacy profiles',
            'current-source provenance tests physical lookup',
            'v2 gate path literals preserve all rules',
            'packaging data destinations and source coverage',
            'empty package layer assignments',
        ],
        'mapping_sha256': MAPPING_SHA,
    }
    if args.apply:
        head = git(root, 'rev-parse', 'HEAD').decode().strip()
        if not args.expected_head or head != args.expected_head:
            raise ValueError('--apply requires the exact reviewed --expected-head')
        if git(root, 'diff', '--name-only').strip() or git(root, 'diff', '--cached', '--name-only').strip():
            raise ValueError('Tracked worktree must be clean before migration')
        for old, new in {**moves, MANIFEST: ADAPTER + MANIFEST}.items():
            (root / new).parent.mkdir(parents=True, exist_ok=True)
            git(root, 'mv', '--', old, new)
        for name, source in outputs.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(source if isinstance(source, bytes) else source.encode('utf-8'))
        report['mechanical_repairs'] = repair(root, moves)
        if args.ruff:
            subprocess.run([str(args.ruff.resolve()), 'format', '.'], cwd=root, check=True)
        report['state'] = 'applied_needs_validation'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
