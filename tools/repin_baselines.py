"""Detect and regenerate the mechanically regenerable test baselines (work rule R6).

Dry-run is the default and prints a per-baseline summary. ``--write`` applies it.
The tool only regenerates expected values from the current tree: it never edits an
assertion's logic, never deletes a check and never touches the G3 locked files,
``tests/fixtures/r7_base.json`` or the hash-frozen ``tests/fixtures/layered_paths``
tables. A baseline is refused (BLOCKED) when its test would still fail for a
non-baseline reason, and a written baseline is verified by running its test
modules, with automatic rollback when they still fail.

Exit codes: 0 everything current (or written and verified), 1 stale baselines
found in dry-run, 2 at least one baseline blocked or failed verification.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_layers import layer_for, load_map, tracked_sources

ROOT = Path(__file__).resolve().parents[1]
CATALOG_FIXTURE = 'tests/fixtures/desktop_catalog_main_6b78239.json'
CATALOG_TEST = 'tests/test_desktop_catalog_split.py'
INVENTORY_DOC = 'docs/analysis/08_REFACTOR_INVENTORY.md'
LAYER_TEST = 'tests/test_layer_gate.py'
APPEARANCE_TEST = 'tests/test_b4_appearance.py'
OBSERVER_DELTA = 'tests/fixtures/download_auto_import_ui_delta.json'
DEFAULT_NOTE = 'Registered by tools/repin_baselines.py: new module; existing rows and layer rules retained.'


class Blocked(Exception):
    """The tree has a non-baseline problem that regenerating a baseline cannot fix."""


@dataclass
class Plan:
    name: str
    edits: dict[str, str] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    verify: tuple[str, ...] = ()
    failed: str = ''


def read(root: Path, relative: str) -> str:
    return (root / relative).read_bytes().decode('utf-8')


def like(original: str, text: str) -> str:
    """Keep the file's existing newline style."""
    return text.replace('\n', '\r\n') if '\r\n' in original else text


def render_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def run_python(root: Path, code: str) -> str:
    """Run code with the target tree first on sys.path; stdout is UTF-8 text."""
    program = f'import sys\nsys.path.insert(0, {str(root)!r})\n{code}'
    env = {**os.environ, 'PYTHONUTF8': '1', 'QT_QPA_PLATFORM': 'offscreen'}
    with tempfile.TemporaryDirectory() as cache:  # a private bytecode cache: never trust stale .pyc files for edits made within one second
        done = subprocess.run([sys.executable, '-X', f'pycache_prefix={cache}', '-c', program], cwd=root, env=env, capture_output=True)
    if done.returncode:
        tail = done.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]
        raise Blocked(f'cannot evaluate the current tree: {tail[0] if tail else "no error output"}')
    return done.stdout.decode('utf-8')


def replace_literal(text: str, pattern: str, value: str, label: str) -> str:
    """Swap the single captured literal of a pin; the surrounding assertion is untouched."""
    found = list(re.finditer(pattern, text))
    if len(found) != 1:
        raise Blocked(f'{label}: expected exactly one pin site, found {len(found)}; the test was restructured')
    start, stop = found[0].span(1)
    return text[:start] + value + text[stop:]


# --- catalog: fixture of every lookup and insertion order, plus contiguous record counts ---

CATALOG_CODE = """
import json
from desktop_app.strings import catalog
from tools.refactor.split_ui_catalog_check import dump
sys.stdout.buffer.write(json.dumps(dump(vars(catalog)), ensure_ascii=False).encode('utf-8'))
"""


def entry_orders(root: Path) -> tuple[list[int], list[int], list[str]]:
    """Mirror the contiguity test: literal ENTRIES rows of every strings module."""
    translations, aliases, problems = [], [], []
    phases: dict[int, set[str]] = {}
    for path in sorted((root / 'desktop_app/strings').rglob('*.py')):
        for node in ast.parse(path.read_bytes().decode('utf-8')).body:
            if not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ENTRIES' for t in node.targets)):
                continue
            for row in ast.literal_eval(node.value):
                if 'aliases' in path.relative_to(root).parts:
                    aliases.append(row[0])
                    continue
                phase, order, key, _ = row
                if key in phases.setdefault(phase, set()):
                    problems.append(f'duplicate key {key!r} in phase {phase} ({path.name})')
                phases[phase].add(key)
                translations.append(order)
    return translations, aliases, problems


def contiguity_problems(label: str, orders: list[int]) -> list[str]:
    expected = set(range(len(orders)))
    duplicates = sorted(order for order, n in Counter(orders).items() if n > 1)
    gaps = sorted(expected - set(orders))
    if not duplicates and not gaps:
        return []
    return [f'{label} orders are not contiguous 0..{len(orders) - 1}: duplicates {duplicates[:5]}, missing {gaps[:5]}; fix the entry numbers by hand']


def catalog_changes(old: dict, new: dict) -> tuple[list[str], int, list[str]]:
    """Summary lines, count of additive entries, and reviewed (non-additive) change descriptions."""
    summary, added_total, reviewed = [], 0, []
    for locale in sorted(old['lookups'].keys() | new['lookups'].keys()):
        before, after = old['lookups'].get(locale, {}), new['lookups'].get(locale, {})
        added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
        changed = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
        summary.append(f'{locale}: +{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed')
        added_total += len(added)
        reviewed += [f'{locale} removed {key}' for key in removed] + [f'{locale} changed {key}' for key in changed]
    alias_added, alias_gone = new['aliases'].keys() - old['aliases'].keys(), old['aliases'].keys() - new['aliases'].keys()
    alias_changed = [k for k in old['aliases'].keys() & new['aliases'].keys() if old['aliases'][k] != new['aliases'][k]]
    summary.append(f'aliases: +{len(alias_added)} added, -{len(alias_gone)} removed, ~{len(alias_changed)} changed')
    reviewed += [f'alias removed {key}' for key in sorted(alias_gone)] + [f'alias changed {key}' for key in sorted(alias_changed)]
    for name in ('key_order', 'alias_order'):
        old_keys, new_keys = set(old[name]), set(new[name])
        if [key for key in new[name] if key in old_keys] != [key for key in old[name] if key in new_keys]:
            reviewed.append(f'{name} of existing keys was reordered')
    return summary, added_total, reviewed


def catalog_plan(root: Path, accept_changed: bool = False) -> Plan:
    plan = Plan('catalog', verify=('test_desktop_catalog_split', 'test_desktop_text_aliases'))
    old = json.loads(read(root, CATALOG_FIXTURE))
    source_commit = old.pop('source_commit')
    new = json.loads(run_python(root, CATALOG_CODE))
    translations, aliases, plan.blockers = entry_orders(root)
    plan.blockers += contiguity_problems('catalog', translations) + contiguity_problems('alias', aliases)
    summary, _, reviewed = catalog_changes(old, new)
    plan.summary = summary
    if reviewed and not accept_changed:
        plan.blockers.append(f'{len(reviewed)} existing strings changed/removed/reordered (e.g. {reviewed[0]}); review them, then pass --accept-changed')
    original = read(root, CATALOG_FIXTURE)
    text = like(original, render_json({'source_commit': source_commit, **new}))
    if text != original:
        plan.edits[CATALOG_FIXTURE] = text
    test = read(root, CATALOG_TEST)
    for subject, count in (('orders', len(translations)), ('aliases', len(aliases))):
        pattern = rf'assertEqual\(sorted\({subject}\), list\(range\((\d+)\)\)\)'
        updated = replace_literal(test, pattern, str(count), f'{CATALOG_TEST} {subject}')
        if updated != test:
            plan.summary.append(f'{CATALOG_TEST}: {subject} record count -> {count}')
            test = updated
    if test != read(root, CATALOG_TEST):
        plan.edits[CATALOG_TEST] = test
    return plan


# --- inventory: every tracked product source needs a section 2 row of the right layer ---


def inventory_rows(text: str) -> dict[str, str]:
    section = text.split('## 2 ')[1].split('## 3 ')[0]
    return dict(re.findall(r'^\| `([^`]+\.py)` \| \d+ \| (\w+) \|', section, re.M))


def layer_test_metadata(root: Path) -> set[str]:
    """Paths the layer gate test registers itself (initializers, historical tools)."""
    for node in ast.walk(ast.parse(read(root, LAYER_TEST))):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'metadata' for t in node.targets) and isinstance(node.value, ast.Dict):
            return {key.value for key in node.value.keys if isinstance(key, ast.Constant)}
    return set()


def insert_rows(text: str, rows: list[str]) -> str:
    lines = text.split('\n')
    end = next(index for index, line in enumerate(lines) if line.startswith('## 3 '))
    last = end - 1
    while not lines[last].strip():
        last -= 1
    return '\n'.join(lines[: last + 1] + rows + lines[last + 1 :])


def inventory_plan(root: Path, note: str = DEFAULT_NOTE) -> Plan:
    plan = Plan('inventory', verify=('test_layer_gate',))
    mapping = load_map(root / 'tools/layer_map.json')
    relocations = json.loads(read(root, 'tools/layer_relocations.json'))
    inverse = {new: old for old, new in relocations.items()}
    text = read(root, INVENTORY_DOC)
    rows, metadata = inventory_rows(text), layer_test_metadata(root)
    new_rows = []
    for path in sorted(tracked_sources(root)):
        layer = layer_for(path, mapping)
        canonical = inverse.get(path, path)
        if layer is None:
            plan.blockers.append(f'{path}: no layer assigned; add it to tools/layer_map.json first')
        elif canonical in rows and rows[canonical] != layer:
            plan.blockers.append(f'{path}: inventory says {rows[canonical]} but tools/layer_map.json says {layer}')
        elif canonical not in rows and path not in metadata and canonical not in metadata:
            if path.endswith('/__init__.py'):
                plan.blockers.append(f'{path}: package initializers are registered by hand in {LAYER_TEST} metadata')
                continue
            lines = read(root, path).count('\n')
            new_rows.append(f'| `{path}` | {lines} | {layer} | `{path}` | {note} |')
            plan.summary.append(f'register {path} ({layer}, {lines} lines)')
    if new_rows:
        plan.edits[INVENTORY_DOC] = like(text, insert_rows(text.replace('\r\n', '\n'), new_rows))
    return plan


# --- stylesheet: SHA-256 of the default application and market stylesheets ---

STYLE_CODE = """
import hashlib, json
from desktop_app.shell import theme
out = {}
for name in ('build_app_stylesheet', 'build_market_stylesheet'):
    build = getattr(theme, name)
    out[name] = {'sha256': hashlib.sha256(build().encode()).hexdigest(), 'dark_same': build() == build('dark'), 'light_differs': build() != build('light')}
print(json.dumps(out))
"""


def stylesheet_plan(root: Path) -> Plan:
    plan = Plan('stylesheet', verify=('test_b4_appearance', 'test_no_inline_stylesheet'))
    measured = json.loads(run_python(root, STYLE_CODE))
    text = read(root, APPEARANCE_TEST)
    for name, facts in measured.items():
        if not (facts['dark_same'] and facts['light_differs']):
            plan.blockers.append(f'{name}: default theme is no longer the dark theme or equals light; not a hash-only change')
        pattern = rf"theme\.{name}, '([0-9a-f]{{64}})'"
        updated = replace_literal(text, pattern, facts['sha256'], f'{APPEARANCE_TEST} {name}')
        if updated != text:
            plan.summary.append(f'{name}: sha256 -> {facts["sha256"]}')
            text = updated
    if text != read(root, APPEARANCE_TEST):
        plan.edits[APPEARANCE_TEST] = text
    return plan


# --- observers: patch-point line/identity pins of the page service inventory ---

OBSERVER_CODE = """
import copy, json
from tests.page_services_inventory import ROOT, FIXTURE, inventory, reviewed_inventory
delta = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))['inventory']
neutral = copy.deepcopy(delta)
neutral['m1_patch_points'] = {'removed': [], 'added': []}
neutral['m1_aliases'] = []
pre = reviewed_inventory(json.loads(FIXTURE.read_text(encoding='utf-8')), neutral)
sys.stdout.buffer.write(json.dumps({'pre': pre, 'cur': inventory()}, ensure_ascii=False).encode('utf-8'))
"""


def row_key(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def counted(rows: Counter, previous: list[dict]) -> list[dict]:
    """Rows still present keep their committed position (minimal diffs); new rows follow in sorted order."""
    kept = [item['row'] for item in previous if row_key(item['row']) in rows]
    known = {row_key(row) for row in kept}
    fresh = sorted((json.loads(key) for key in rows if key not in known), key=lambda r: (r['file'], r['line'], r['name'], r['kind'], r['receiver']))
    return [{'row': row, 'count': rows[row_key(row)]} for row in kept + fresh]


def observer_delta(pre: dict, cur: dict, previous: dict) -> tuple[dict, list[dict], list[str]]:
    """The m1 sections that turn the reviewed inventory into the current one."""
    blockers = [f'{key} changed; that is a real page service change, not an observer move' for key in ('services', 'state_copies') if pre[key] != cur[key]]
    changes = []
    if len(pre['aliases']) != len(cur['aliases']):
        blockers.append('the alias set changed; that is a real page change, not an observer move')
    else:
        for old, new in zip(pre['aliases'], cur['aliases']):
            if old == new:
                continue
            if {k: v for k, v in old.items() if k != 'patch_sensitive'} != {k: v for k, v in new.items() if k != 'patch_sensitive'}:
                blockers.append(f'alias {old["name"]} changed beyond its patch_sensitive flag')
            changes.append({'original': json.loads(row_key(old)), 'current': json.loads(row_key(new))})
    before, after = Counter(map(row_key, pre['patch_points'])), Counter(map(row_key, cur['patch_points']))
    return {'removed': counted(before - after, previous['removed']), 'added': counted(after - before, previous['added'])}, changes, blockers


def observer_plan(root: Path) -> Plan:
    plan = Plan('observers', verify=('test_page_services_r1', 'test_download_auto_import_contracts'))
    evaluated = json.loads(run_python(root, OBSERVER_CODE))
    original = read(root, OBSERVER_DELTA)
    delta = json.loads(original)
    committed = delta['inventory']['m1_patch_points']
    patch_points, aliases, plan.blockers = observer_delta(evaluated['pre'], evaluated['cur'], committed)
    delta['inventory']['m1_patch_points'] = patch_points
    delta['inventory']['m1_aliases'] = aliases
    pins = {side: {row_key(item) for item in patch_points[side]} for side in patch_points}
    old = {side: {row_key(item) for item in committed[side]} for side in committed}
    for side in ('removed', 'added'):
        plan.summary.append(f'observers {side}: {len(pins[side])} pinned rows, {len(pins[side] - old[side])} new, {len(old[side] - pins[side])} dropped')
    plan.summary.append(f'alias patch_sensitive changes: {len(aliases)}')
    text = like(original, render_json(delta))
    if text != original:
        plan.edits[OBSERVER_DELTA] = text
    return plan


SETTINGS_PRESENTATION = 'tests/fixtures/ui_redesign_empty_presentation.json'
SETTINGS_TOOLTIP_POLICY = 'tests/fixtures/ui_redesign_tooltip_coverage.json'
SETTINGS_INPUT_CODE = """
import json
from desktop_app.strings.catalog import ui_text
from tests.snapshot_cache import default_metrics
pages = default_metrics()['pages']
name = ui_text('ui.settings_page.title')
sys.stdout.buffer.write(json.dumps({
    'name': name,
    'settings': pages[name],
    'counts': [page['visible_input_count'] for page in pages.values()],
}, ensure_ascii=False).encode('utf-8'))
"""


def settings_inputs_plan(root: Path) -> Plan:
    """Record M4a's one new settings checkbox without widening UI budgets."""
    plan = Plan('settings_inputs', verify=('test_b4_appearance', 'test_t16_tooltips'))
    measured = json.loads(run_python(root, SETTINGS_INPUT_CODE))
    presentation_text = read(root, SETTINGS_PRESENTATION)
    presentation = json.loads(presentation_text)
    policy_text = read(root, SETTINGS_TOOLTIP_POLICY)
    policy = json.loads(policy_text)
    actual = measured['settings']
    expected_counts = [3, 0, 0, 0, 3, 4, 5]
    if measured['counts'] != expected_counts:
        plan.blockers.append('M4a permits exactly one new settings input; another page/input changed')
    if actual['unlabeled_inputs']:
        plan.blockers.append('settings contains an unlabeled input; a baseline cannot fix accessibility')
    if actual['page_height'] > policy['max_default_page_height']:
        plan.blockers.append('settings exceeds the existing page-height budget')
    if actual['primary_button_count'] > policy['max_default_primary_buttons']:
        plan.blockers.append('settings exceeds the existing primary-button budget')
    if plan.blockers:
        return plan
    before = presentation['pages'][measured['name']]
    after = {key: actual[key] for key in before}
    presentation['pages'][measured['name']] = after
    updated = like(presentation_text, render_json(presentation))
    if updated != presentation_text:
        plan.edits[SETTINGS_PRESENTATION] = updated
    updated_policy = replace_literal(
        policy_text,
        r'"default_input_counts":\s*(\[[^\]]*\])',
        json.dumps(expected_counts),
        'default input counts',
    )
    if updated_policy != policy_text:
        plan.edits[SETTINGS_TOOLTIP_POLICY] = updated_policy
    plan.summary.append('settings inputs: exactly 5; all other page counts and UI budgets retained')
    plan.summary.append('settings presentation fields: ' + ', '.join(key for key in before if before[key] != after[key]))
    return plan


# --- runner ---

BASELINES = {
    'catalog': lambda root, args: catalog_plan(root, args.accept_changed),
    'inventory': lambda root, args: inventory_plan(root, args.inventory_note),
    'stylesheet': lambda root, args: stylesheet_plan(root),
    'observers': lambda root, args: observer_plan(root),
    'settings_inputs': lambda root, args: settings_inputs_plan(root),
}


def collect(root: Path, args: argparse.Namespace) -> list[Plan]:
    plans = []
    for name in args.only or BASELINES:
        try:
            plans.append(BASELINES[name](root, args))
        except Blocked as error:
            plans.append(Plan(name, blockers=[str(error)]))
    return plans


def verify(root: Path, modules: tuple[str, ...]) -> str:
    """Run the baseline's own test modules; return the failing module's output tail, or ''."""
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONUTF8': '1'}
    for module in modules:
        done = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', module + '.py'], cwd=root, env=env, capture_output=True)
        if done.returncode:
            return f'{module}: ' + '\n'.join(done.stderr.decode('utf-8', 'replace').strip().splitlines()[-12:])
    return ''


def apply(root: Path, plan: Plan, check: bool) -> None:
    originals = {path: (root / path).read_bytes() for path in plan.edits}
    for path, text in plan.edits.items():
        (root / path).write_bytes(text.encode('utf-8'))
    failure = verify(root, plan.verify) if check else ''
    if failure:
        for path, data in originals.items():
            (root / path).write_bytes(data)
        plan.failed = failure


def status(plan: Plan) -> str:
    if plan.blockers:
        return 'BLOCKED'
    return 'FAILED-VERIFY (rolled back)' if plan.failed else ('STALE' if plan.edits else 'up-to-date')


def report(plans: list[Plan], written: bool) -> None:
    for plan in plans:
        print(f'[{plan.name}] {status(plan)}' + (' -> written' if written and plan.edits and not plan.blockers and not plan.failed else ''))
        for path in plan.edits:
            print(f'  file: {path}')
        for line in plan.summary:
            print(f'  {line}')
        for blocker in plan.blockers:
            print(f'  blocker: {blocker}')
        if plan.failed:
            print(f'  verification failed, files restored:\n{plan.failed}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--write', action='store_true', help='apply the regenerated baselines (default is a dry-run)')
    parser.add_argument('--only', action='append', choices=sorted(BASELINES), help='limit to one baseline (repeatable)')
    parser.add_argument('--accept-changed', action='store_true', help='allow catalog strings that changed, were removed or reordered (review them first)')
    parser.add_argument('--inventory-note', default=DEFAULT_NOTE, help='note column for newly registered inventory rows')
    parser.add_argument('--no-verify', action='store_true', help='skip running the baseline test modules after writing')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    plans = collect(root, args)
    if args.write:
        for plan in plans:
            if plan.edits and not plan.blockers:
                apply(root, plan, not args.no_verify)
    report(plans, args.write)
    if any(plan.blockers or plan.failed for plan in plans):
        return 2
    return 0 if args.write or not any(plan.edits for plan in plans) else 1


if __name__ == '__main__':
    raise SystemExit(main())
