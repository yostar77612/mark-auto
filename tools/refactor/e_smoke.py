"""T5-E5: replay verbatim smoke extraction and mechanical consumer relocation."""

import ast
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = 'f994240'
PREFIX = 'desktop_app.smoke.'
GROUPS = {
    'fixtures': ['_SmokeSettingsView', '_smoke_steps'],
    'auth': ['_auth_smoke_dependencies'],
    'market': ['_market_smoke_ui', '_market_smoke_response', '_check_market_worker_result'],
    'history': ['_history_smoke_fixture', '_check_history_worker_result', '_history_smoke_ui'],
    'walk_forward': ['_walk_forward_smoke_fixture', '_check_walk_forward_smoke_result'],
    'lifecycle': ['_start_smoke_job', '_close_smoke_worker', '_retain_smoke_directory'],
    'runner': ['run_smoke'],
}
OWNERS = {name: PREFIX + module for module, names in GROUPS.items() for name in names}
HEADERS = {
    'fixtures': '',
    'auth': 'from pathlib import Path\nimport quantlab.assistant.adapters.chatgpt.identity as _auth_identity\nimport quantlab.assistant.domain.auth_protocol as _auth_auth_protocol\n',
    'market': 'from pathlib import Path\nfrom desktop_app.smoke.fixtures import _smoke_steps\n',
    'history': 'from pathlib import Path\nfrom desktop_app.strings.catalog import ui_text\n',
    'walk_forward': '',
    'lifecycle': 'import sys\n',
    'runner': 'from pathlib import Path\nimport sys\n'
    + ''.join(
        f'from {PREFIX}{module} import {", ".join(name for name in names if name != "_SmokeSettingsView" and name != "_retain_smoke_directory")}\n'
        for module, names in GROUPS.items()
        if module != 'runner'
    ),
}


def write(path, source):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8', newline='\n')


def extract():
    source = subprocess.check_output(['git', 'show', BASE + ':desktop_app/smoke/__init__.py'], cwd=ROOT).decode('utf-8')
    lines = source.splitlines(keepends=True)
    definitions = {
        node.name: ''.join(lines[node.lineno - 1 : node.end_lineno]) for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    for module, names in GROUPS.items():
        body = '\n\n\n'.join(definitions[name].rstrip('\n') for name in names)
        write(
            'desktop_app/smoke/' + module + '.py',
            f'"""Offline smoke {module}; ordered fixture/evidence behavior is preserved."""\n\nfrom __future__ import annotations\n\n'
            + HEADERS[module].rstrip('\n')
            + ('\n\n' if HEADERS[module] else '\n')
            + body
            + '\n',
        )
    write('desktop_app/smoke/__init__.py', '"""Offline desktop smoke package; entry point lives in smoke.runner."""\n')


def import_edits(source, modules=('desktop', 'desktop_app.smoke')):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in sorted(ast.walk(tree), key=lambda n: getattr(n, 'lineno', 0), reverse=True):
        if not isinstance(node, ast.ImportFrom) or node.module not in modules:
            continue
        if not any(item.name in OWNERS for item in node.names):
            continue
        grouped = defaultdict(list)
        for item in node.names:
            grouped[OWNERS.get(item.name, node.module)].append(item.name + (' as ' + item.asname if item.asname else ''))
        indent = ' ' * node.col_offset
        lines[node.lineno - 1 : node.end_lineno] = [indent + f'from {module} import {", ".join(names)}\n' for module, names in grouped.items()]
    return ''.join(lines)


def consumer_edits(path, source):
    source = import_edits(source)
    source = source.replace("desktop_app/smoke/__init__.py').read_text", "desktop_app/smoke/runner.py').read_text")
    # Injected callbacks patch the runner's imported bindings, where they are looked up.
    source = source.replace("__import__('desktop_app.smoke', fromlist=['__name__'])", "__import__('desktop_app.smoke.runner', fromlist=['__name__'])")
    for name in OWNERS:
        if name not in ('run_smoke', '_SmokeSettingsView', '_close_smoke_worker', '_retain_smoke_directory'):
            source = source.replace('desktop.' + name, "__import__('desktop_app.smoke.runner', fromlist=['__name__'])." + name)
    if path == 'tests/test_desktop_auth_smoke.py':
        source = source.replace("patch('desktop.Path.cwd'", "patch('desktop_app.smoke.auth.Path.cwd'")
    if path == 'tests/test_desktop_market_smoke.py':
        source = source.replace("patch('desktop.Path.read_text'", "patch('desktop_app.smoke.market.Path.read_text'")
    if path == 'tests/test_core_shards.py':
        source = source.replace('from desktop import _auth_smoke_dependencies;', 'from desktop_app.smoke.auth import _auth_smoke_dependencies;')
    return source


def package_test(source):
    source = source.replace('import desktop_app.smoke\n', 'import importlib\nimport desktop_app.smoke.runner\n')
    if '\nOWNERS = ' not in source:
        source = source.replace(
            '\n\nclass SmokePackageTests',
            '\n\nOWNERS = {\n' + ''.join(f'    {name!r}: {owner!r},\n' for name, owner in OWNERS.items()) + '}\n\n\nclass SmokePackageTests',
        )
    source = source.replace('def test_compatibility_exports_are_identical(self):', 'def test_definitions_live_at_direct_owners(self):')
    source = source.replace(
        'self.assertIs(getattr(desktop, name), getattr(desktop_app.smoke, name))',
        'self.assertEqual(getattr(importlib.import_module(OWNERS[name]), name).__module__, OWNERS[name])',
    )
    source = source.replace('patch.object(desktop_app.smoke, name, sentinel)', 'patch.object(desktop_app.smoke.runner, name, sentinel)')
    return source


def references():
    changed_tests = []
    paths = [ROOT / 'desktop.py', *sorted((ROOT / 'tests').glob('*.py')), ROOT / 'tools/ui_redesign_preview.py']
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding='utf-8-sig')
        if relative == 'desktop.py':
            tree = ast.parse(source)
            node = next(n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module in ('desktop_app.smoke', 'desktop_app.smoke.fixtures'))
            if node.module == 'desktop_app.smoke':
                lines = source.splitlines(keepends=True)
                lines[node.lineno - 1 : node.end_lineno] = [
                    'from desktop_app.smoke.fixtures import _SmokeSettingsView\n',
                    'from desktop_app.smoke.lifecycle import _close_smoke_worker, _retain_smoke_directory\n',
                    'from desktop_app.smoke.runner import run_smoke\n',
                ]
                source = ''.join(lines)
        else:
            source = consumer_edits(relative, source)
            if relative == 'tests/test_desktop_smoke_package.py':
                source = package_test(source)
        if source != path.read_text(encoding='utf-8-sig'):
            write(relative, source)
            if relative.startswith('tests/'):
                changed_tests.append(relative)
    update_r2_tool()
    spec = ROOT / 'packaging/markauto.spec'
    source = spec.read_text(encoding='utf-8')
    if "'desktop_app.smoke.runner'" not in source:
        source = source.replace(
            "                   # Lazy JWT import",
            ''.join(f"                   '{PREFIX}{module}',\n" for module in (*GROUPS, 'recovery', 'tls')) + '\n                   # Lazy JWT import',
        )
        write('packaging/markauto.spec', source)
    format_paths(paths + [ROOT / ('desktop_app/smoke/' + module + '.py') for module in GROUPS] + [ROOT / 'tools/extract_desktop_smoke_r2.py'])
    record_tests(changed_tests)


def update_r2_tool():
    path = 'tools/extract_desktop_smoke_r2.py'
    source = (ROOT / path).read_text(encoding='utf-8')
    start = source.find("    moved = [node for node in nodes if node.name not in PRODUCTION]\n")
    if start != -1:
        end = source.index('    current = {', start)
        source = source[:start] + "    package = ROOT / 'desktop_app/smoke/__init__.py'\n" + source[end:]
    source = source.replace(
        "ast.parse(package.read_text(encoding='utf-8')).body",
        "[node for owner in sorted(package.parent.glob('*.py')) for node in ast.parse(owner.read_text(encoding='utf-8')).body]",
    )
    source = source.replace(
        'Reproduce the R2 extraction and record canonical AST preservation evidence.',
        'Record canonical R2 AST evidence across current owners; replay lives in refactor/e_smoke.py.',
    )
    write(path, source)


def format_paths(paths):
    import os
    import shutil

    ruff = os.environ.get('RUFF') or shutil.which('ruff') or str(ROOT / '.venv/Scripts/ruff.exe')
    subprocess.run([ruff, 'format', *(path.relative_to(ROOT).as_posix() for path in paths)], cwd=ROOT, check=True)


def record_tests(paths):
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else []
    if isinstance(data, dict):
        entries = data.setdefault('T5-E5', [])
    else:
        entries = data
    for name in paths:
        row = {
            'slice': 'T5-E5',
            'path': name,
            'reason': 'Mechanical smoke owner/import, patch lookup, physical source scan, or definition-ownership contract relocation; no fixture or safety behavior changed.',
        }
        if row not in entries:
            entries.append(row)
    write('.tmp-layered/test-edit-reasons.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def inventory():
    from tools.refactor.measure_core_sizes import measure

    path = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = (ROOT / path).read_text(encoding='utf-8')
    rows = source.splitlines()
    for index, row in enumerate(rows):
        if row.startswith('| `desktop_smoke/__init__.py` | 961 | E') and '**DONE (T5-E5)**' not in row:
            rows[index] = row.replace('| orchestrator', '| **DONE (T5-E5)**: orchestrator').replace(
                '保留 smoke deadline／證據。',
                '保留 smoke deadline／證據。 `_SmokeSettingsView`、`_smoke_steps` → `desktop_app/smoke/fixtures.py`；所有原函式完整搬移，沒有拆分函式。',
            )
        if row.startswith('|') and 'desktop_app/smoke/__init__.py:' in row:
            if '`<module>`' in row:
                rows[index] = ''
                continue
            name = 'complete_smoke' if '`complete_smoke`' in row else next(name for name in OWNERS if '`' + name + '`' in row)
            owner = OWNERS.get(name, PREFIX + 'runner').replace('.', '/') + '.py'
            node = next(n for n in ast.walk(ast.parse((ROOT / owner).read_text(encoding='utf-8'))) if getattr(n, 'name', None) == name)
            span = node.end_lineno - node.lineno + 1
            reason = 'T5-E5 DONE: complete definition moved verbatim to its final owner; justified exception in 10.4.'
            if row.startswith('| function |'):
                rows[index] = f'| function | `{owner}:{node.lineno}` | `{name}` | {span} | {reason} |'
            else:
                rows[index] = f'| `{owner}:{node.lineno}` | `{name}` | function | {span} | {reason} |'
    for index, row in enumerate(rows):
        if row.startswith('|') and 'desktop_app/smoke/recovery.py:' in row and 'T5-E5 DONE' not in row:
            rows[index] = row[:-2] + ' T5-E5 DONE: final recovery owner retained verbatim, including its 40-second cap and reserve. |'
    source = '\n'.join(rows) + '\n'
    source = source.replace('\n\n| `desktop_app/smoke/', '\n| `desktop_app/smoke/').replace(
        '\n\n| function | `desktop_app/smoke/', '\n| function | `desktop_app/smoke/'
    )
    for section in ('10.1 PR C size exceptions', '10.3 PR D size exceptions'):
        marker = '### ' + section + '\n'
        note = '\nT5-E5 smoke rows: **DONE**. `desktop_app/smoke/__init__.py` is metadata only;\nfinal definition paths are listed below and current size exceptions are in 10.4.\n'
        if marker + note not in source:
            source = source.replace(marker, marker + note)
    start = source.index('### 10.4 PR E size exceptions\n')
    before, overlay = source[:start], source[start:]
    overlay = re.sub(r'^\| (?:file|class|function) \| `(?:desktop.py|desktop_app/smoke/[^`]+|tools/refactor/e_smoke.py):\d+`.*\n', '', overlay, flags=re.M)
    for item in measure(ROOT):
        if item['path'] == 'desktop.py' or item['path'].startswith('desktop_app/smoke/') or item['path'] == 'tools/refactor/e_smoke.py':
            reason = 'T5-E5: complete inherited definition moved verbatim; keep ordered fixtures, validation, timer callbacks and terminal evidence together as section 10 specifies no further function split.'
            if item['path'] == 'desktop.py':
                reason = 'T5-E5: only imports point to direct smoke owners; frozen dispatch, startup, cleanup and report ordering retained.'
            if item['path'] == 'tools/refactor/e_smoke.py':
                reason = 'T5-E5 one-shot mechanical migration: keep ordered owner/reference and exact-size inventory updates together for idempotent replay; not product runtime.'
            overlay += f"| {item['kind']} | `{item['path']}:{item['line']}` | `{item['name']}` | {item['lines']} | {reason} |\n"
    if 'E5 smoke plan: **DONE**' not in overlay:
        overlay = overlay.replace(
            '### 10.4 PR E size exceptions\n',
            '### 10.4 PR E size exceptions\n\nE5 smoke plan: **DONE**. Direct owners: fixtures, auth, market, history,\nwalk_forward, lifecycle and runner under desktop_app/smoke/. Package metadata\nexports no implementation names. All moved definitions retain exact source bytes;\nrunner callbacks, recovery helper, timeouts and terminal evidence remain whole.\n',
        )
    write(path, before + overlay)


if __name__ == '__main__':
    import sys

    sys.path.insert(0, str(ROOT))
    extract()
    references()
    inventory()
