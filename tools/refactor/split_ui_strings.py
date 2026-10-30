"""Prepare PR C's literal-only catalog split in an explicit output directory.

This does not move files. The existing lookup entry point and every non-literal
statement remain in their original order. Dictionaries are partitioned by the
semantic key prefix; their original literal tokens and insertion order survive.
"""

from __future__ import annotations

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/strings/catalog_data.py').is_file():
    print('split_ui_strings.py: already applied')
    raise SystemExit(0)


import argparse
import ast
from collections import defaultdict
import hashlib
import json
import keyword
from pathlib import Path
import runpy
import subprocess
import sys


LIMIT = 360


def module_name(parts):
    words = [part.replace('-', '_') for part in parts]
    name = '_'.join(word + '_strings' if keyword.iskeyword(word) else word for word in words)
    return 'ui/' + name.removeprefix('ui_') if name.startswith('ui_') else name


def semantic_group(key):
    if not key.startswith('ui.'):
        return key
    operation = key.split('.')[1]
    if 'walk_forward' in operation:
        feature = 'walk_forward'
    elif 'analysis' in operation or 'recovery' in operation:
        feature = 'analysis'
    elif 'chatgpt' in operation or 'plan_' in operation or operation == 'connection_event_from_payload':
        feature = 'assistant'
    elif 'paper' in operation or operation == 'show_account':
        feature = 'paper'
    elif 'market' in operation:
        feature = 'market'
    elif 'backtest' in operation:
        feature = 'backtest'
    elif 'campaign' in operation or 'candidate' in operation or operation in ('strategy_page', 'research_controls', 'select_strategy', 'use_builtin'):
        feature = 'strategy'
    elif 'settings' in operation or operation in ('configure_workspace', 'open_releases', 'backup'):
        feature = 'settings'
    elif 'result' in operation or operation in ('compare_page', 'refresh_views'):
        feature = 'results'
    elif 'data' in operation or operation in ('load_form_file', 'export_manual_request'):
        feature = 'data'
    else:
        feature = 'shell'
    return f'ui_{feature}.{key}'


def partition(records):
    """Split only at a semantic prefix boundary, never by an arbitrary row cap."""
    result = {}

    def visit(items, prefix, depth):
        if len(items) <= LIMIT:
            result[module_name(prefix)] = items
            return
        children = defaultdict(list)
        for record in items:
            components = record['semantic_key'].split('.')
            if len(components) <= depth:
                raise ValueError(f'Catalog feature {prefix} needs a deliberate finer responsibility split')
            children[components[depth]].append(record)
        for key, group in children.items():
            visit(group, (*prefix, key), depth + 1)

    groups = defaultdict(list)
    for record in records:
        groups[record['semantic_key'].split('.')[0]].append(record)
    for key, group in groups.items():
        visit(group, (key,), 1)
    return result


def literal_record(source, lines, key, value, phase, order, *, alias=False):
    name, text = ast.literal_eval(key), ast.literal_eval(value)
    if not isinstance(name, str) or not isinstance(text, str):
        raise ValueError('Only the existing string-to-string catalog literals can be partitioned')
    return {
        'semantic_key': semantic_group(text if alias else name),
        'key': name,
        'value': text,
        'key_source': lines[key.lineno - 1][key.col_offset : key.end_col_offset].decode('utf-8')
        if key.lineno == key.end_lineno
        else ast.get_source_segment(source, key),
        'value_source': lines[value.lineno - 1][value.col_offset : value.end_col_offset].decode('utf-8')
        if value.lineno == value.end_lineno
        else ast.get_source_segment(source, value),
        'phase': phase,
        'order': order,
    }


def collect(source):
    translations, aliases, replacements = [], [], []
    lines = source.encode('utf-8').splitlines()
    phase = 0
    for node in ast.parse(source).body:
        name, table, alias = None, None, False
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('ZH_TW', 'TEXT_ALIASES'):
                table, alias = node.value, name == 'TEXT_ALIASES'
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if ast.unparse(call.func) == 'ZH_TW.update':
                if len(call.args) != 1 or call.keywords:
                    raise ValueError('Unexpected catalog update operation')
                table, name = call.args[0], 'ZH_TW.update'
        if table is None:
            continue
        if not isinstance(table, ast.Dict) or any(key is None for key in table.keys):
            raise ValueError('Catalog must contain explicit literal dictionary entries')
        rows = aliases if alias else translations
        for key, value in zip(table.keys, table.values):
            rows.append(literal_record(source, lines, key, value, phase, len(rows), alias=alias))
        replacement = (
            'TEXT_ALIASES = _TEXT_ALIASES'
            if alias
            else f'ZH_TW = _ZH_TW_CHUNKS[{phase}].copy()'
            if name == 'ZH_TW'
            else f'ZH_TW.update(_ZH_TW_CHUNKS[{phase}])'
        )
        replacements.append((node, replacement))
        if not alias:
            phase += 1
    return translations, aliases, replacements


def replace_statements(source, replacements):
    lines = source.encode('utf-8').splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    raw = source.encode('utf-8')
    for node, replacement in reversed(replacements):
        start = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        raw = raw[:start] + replacement.encode('utf-8') + raw[end:]
    text = raw.decode('utf-8')
    tree = ast.parse(text)
    docstring = tree.body[0]
    lines = text.splitlines(keepends=True)
    lines.insert(docstring.end_lineno, '\nfrom .catalog_data import ZH_TW_CHUNKS as _ZH_TW_CHUNKS, TEXT_ALIASES as _TEXT_ALIASES\n')
    return ''.join(lines)


def render_records(rows, *, alias=False):
    header = 'Historical single-hop alias literals' if alias else 'Traditional Chinese feature literals'
    lines = [f'"""{header}; ordered records preserve the original catalog."""', '', 'ENTRIES = (']
    for record in rows:
        fields = [str(record['order']), record['key_source'], record['value_source']]
        if not alias:
            fields.insert(0, str(record['phase']))
        lines.append('    (' + ', '.join(fields) + '),')
    lines.extend((')', ''))
    return '\n'.join(lines)


def render_parts(groups, *, alias=False):
    imports, names = [], []
    for name in groups:
        local = '_part_' + name.replace('/', '_')
        imports.append(f'from .{"aliases." if alias else ""}{name.replace("/", ".")} import ENTRIES as {local}')
        names.append(local)
    text = '"""Feature partitions in original registration order."""\n\n'
    text += '\n'.join(imports) + '\n\n'
    return text + 'PARTS = (\n' + ''.join(f'    {name},\n' for name in names) + ')\n'


def render_aggregation():
    text = '"""Assemble feature data in original mutation and insertion order."""\n\nfrom itertools import chain\n'
    text += 'from .translation_parts import PARTS as _TRANSLATION_PARTS\nfrom .alias_parts import PARTS as _ALIAS_PARTS\n\n'
    text += "ZH_TW_CHUNKS = {}\nfor phase, order, key, value in sorted(chain.from_iterable(_TRANSLATION_PARTS), key=lambda row: row[1]):\n    ZH_TW_CHUNKS.setdefault(phase, {})[key] = value\n\n"
    text += "TEXT_ALIASES = {key: value for order, key, value in sorted(chain.from_iterable(_ALIAS_PARTS))}\n"
    return text


def prepare(source, destination):
    translations, aliases, replacements = collect(source)
    text_groups, alias_groups = partition(translations), partition(aliases)
    outputs = {
        'catalog.py': replace_statements(source, replacements),
        'catalog_data.py': render_aggregation(),
        'translation_parts.py': render_parts(text_groups),
        'alias_parts.py': render_parts(alias_groups, alias=True),
    }
    lookup = outputs['catalog.py']
    stage = next(node for node in ast.parse(lookup).body if isinstance(node, ast.FunctionDef) and node.name == 'stage_error_message')
    lines = lookup.splitlines(keepends=True)
    messages = '"""Worker stage error text, presented through the canonical catalog lookup."""\n\nfrom desktop_app.strings.catalog import ui_text\n\n\n'
    messages += ''.join(lines[stage.lineno - 1 : stage.end_lineno])
    del lines[stage.lineno - 1 : stage.end_lineno]
    outputs['catalog.py'] = ''.join(lines)
    message_path = destination.parent / 'components/job_messages.py'
    message_path.parent.mkdir(parents=True, exist_ok=True)
    message_path.write_text(messages, encoding='utf-8', newline='\n')
    outputs.update({name + '.py': render_records(rows) for name, rows in text_groups.items()})
    outputs.update({'aliases/' + name + '.py': render_records(rows, alias=True) for name, rows in alias_groups.items()})
    outputs['aliases/__init__.py'] = '"""Historical catalog aliases partitioned by destination feature."""\n'
    outputs['ui/__init__.py'] = '"""Catalog text grouped by the UI feature that owns it."""\n'
    outputs['aliases/ui/__init__.py'] = '"""Historical aliases grouped by the UI destination feature."""\n'
    for name, text in outputs.items():
        ast.parse(text, feature_version=(3, 11))
        if len(text.splitlines()) > 400:
            raise ValueError(f'Generated responsibility {name} exceeds 400 lines')
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    return outputs, translations, aliases


def verify(original, destination):
    """Compare actual constant values, order, live lookup and original metadata."""
    reference = runpy.run_path(str(original))
    program = """
import importlib, json, pathlib, sys
base = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(base.parent))
catalog = importlib.import_module(f'{base.name}.catalog')
names = ('ZH_TW', 'TEXT_ALIASES', 'RETAINED_CATALOG_KEYS', 'GLOSSARY', 'FORBIDDEN_DEFAULT_TERMS', 'DEFAULT_TERM_ALLOWLIST', 'LOG_OPERATION_NAMES', 'LOG_EVENT_NAMES')
print(json.dumps({name: list(getattr(catalog, name).items()) if isinstance(getattr(catalog, name), dict) else sorted(getattr(catalog, name)) for name in names}, ensure_ascii=False))
"""
    initializer = destination / '__init__.py'
    if not initializer.exists():
        initializer.write_text('', encoding='utf-8')
    completed = subprocess.run([sys.executable, '-c', program, str(destination)], check=True, capture_output=True, text=True, encoding='utf-8')
    actual = json.loads(completed.stdout)
    expected = {name: list(map(list, reference[name].items())) if isinstance(reference[name], dict) else sorted(reference[name]) for name in actual}
    if actual != expected:
        raise AssertionError('Split changed catalog values, order, aliases or metadata')
    return {name: len(value) for name, value in actual.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    source_root, output_root = args.source_root.resolve(), args.output_root.resolve()
    if source_root == output_root:
        parser.error('Preparation requires a separate output root; product application is controller-owned')
    source = source_root / 'desktop_app/strings/catalog.py'
    if not source.exists():
        source = source_root / 'desktop_strings.py'
    destination = output_root / 'desktop_app/strings'
    text = source.read_text(encoding='utf-8-sig')
    outputs, translations, aliases = prepare(text, destination)
    counts = verify(source, destination)
    report = dict(
        source=str(source),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        files=len(outputs),
        translation_records=len(translations),
        alias_records=len(aliases),
        compared=counts,
    )
    (output_root / 'strings-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
