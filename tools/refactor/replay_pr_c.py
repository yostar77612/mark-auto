"""Rebuild PR C from its fixed base, then verify PR bytes and the whole tree.

Content is explicit; consumer edits are executed in order, never copied from the
expected tree. --expect-root supplies uncommitted content and comparison bytes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = '6b78239'
SOURCE = Path(__file__).resolve().parents[2]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def write(root, name, raw):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def invoke(name, root, *args):
    command = [sys.executable, '-B', '-m', 'tools.refactor.' + name, *map(str, args)]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
    if result.returncode:
        print(result.stdout[-3000:])
        print(result.stderr[-4000:])
        raise RuntimeError(f'{name}: exit {result.returncode}')
    print(f'mechanical: {name}', flush=True)


def run(root, expected, reference, manifest, names):
    baseline = git(root, 'rev-parse', 'HEAD').decode().strip()
    if baseline != git(root, 'rev-parse', BASE).decode().strip():
        raise ValueError('--root must be detached at 6b78239')
    if subprocess.run(['git', '-C', str(root), 'symbolic-ref', '-q', 'HEAD'], capture_output=True).returncode == 0:
        raise ValueError('--root must have a detached HEAD')
    status = git(root, 'status', '--porcelain', '--untracked-files=all').strip()
    if status:
        raise ValueError('--root must be a fresh, clean worktree: ' + status.decode('utf-8'))
    sys.path.insert(0, str(root))
    os.environ.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', QT_QPA_PLATFORM='offscreen')
    content = {row['path'] for row in manifest['files']}
    for name in sorted(content):
        if name.startswith('tools/refactor/'):
            # Bootstrap the executing tooling package; consumer outputs are never copied.
            raw = (SOURCE / name).read_bytes()
        else:
            raw = (expected / name).read_bytes() if expected else git(SOURCE, 'show', reference + ':' + name)
        write(root, name, raw)
    preparation = root.parent / (root.name + '-preparation')
    preparation.mkdir(parents=True, exist_ok=True)
    invoke('extract_runtime_error', root, '--source-root', root, '--output-root', preparation)
    for path in preparation.rglob('*.py'):
        name = path.relative_to(preparation).as_posix()
        if name in names and name not in content:
            write(root, name, path.read_bytes())
    # Run historical generators against immutable inputs, isolated from authored bodies.
    source = root.parent / (root.name + '-source')
    source.mkdir(parents=True, exist_ok=True)
    inputs = (
        'desktop_app/strings/catalog.py',
        'desktop_app/components/forms.py',
        'desktop_app/components/charts.py',
        'desktop_app/shell/main_window.py',
        'desktop_app/shell/host.py',
        'desktop_app/components/formatting.py',
        'desktop_app/features/market/dashboard.py',
        'desktop_app/features/strategy/idea_research.py',
        'desktop_app/features/walk_forward/presenter.py',
        'quantlab/market_history.py',
        'tools/layer_relocations.json',
    )
    for name in inputs:
        write(source, name, git(root, 'show', BASE + ':' + name))
    for name in ('strings', 'modules', 'workers', 'market', 'idea', 'inputs', 'shell'):
        invoke('split_ui_' + name, root, '--source-root', source, '--output-root', preparation)
    for name in ('tools/layer_map.json', 'tools/layer_allowlist.json', 'tools/refactor/split_ui_owners.json'):
        write(preparation, name, (root / name).read_bytes())
    code = (
        "from tools.refactor import split_ui_slice2 as m; import sys; "
        "m.__file__=sys.argv[1]+'/tools/refactor/split_ui_slice2.py'; "
        "sys.argv=['split_ui_slice2','--source-root',sys.argv[2]]; m.main()"
    )
    subprocess.run([sys.executable, '-B', '-c', code, str(preparation), str(source)], cwd=root, check=True, capture_output=True)
    print('mechanical: split_ui_slice2', flush=True)
    for name in ('desktop_app/shell/host.py', 'desktop_app/features/walk_forward/presenter.py'):
        if name not in names:
            continue
        raw = (preparation / name).read_bytes()
        if name.endswith('host.py'):
            raw = raw.replace(b'    sample_market_series: Callable\n', b'')
        write(root, name, raw)
    owners = root / 'tools/refactor/split_ui_owners.json'
    invoke('split_ui_references', root, '--owners', owners)
    invoke('split_ui_consumers', root)
    invoke('split_ui_tests', root)
    invoke('split_ui_r3b', root)
    invoke('split_ui_r3c', root)
    invoke('split_ui_r3f', root)
    # Historical passes used formatting between slices; preserve that ordering.
    format_tree(root)
    invoke('replay_pr_c_mechanical', root)
    render_metadata(root)
    format_tree(root)
    subprocess.run([sys.executable, '-B', '-c', 'from tools.refactor.split_ui_fixture_lines import slice2; slice2()'], cwd=root, check=True)
    subprocess.run([sys.executable, '-B', '-c', 'from tools.refactor.split_ui_finish import layer_inventory; layer_inventory()'], cwd=root, check=True)
    print('mechanical: split_ui_finish', flush=True)
    invoke('split_ui_r3d', root)
    format_tree(root)
    render_metadata(root)
    invoke('split_ui_catalog_check', root)
    invoke('split_ui_verify', root)
    return content


def format_tree(root):
    executable = os.environ.get('RUFF', 'ruff')
    subprocess.run([executable, 'check', '--fix', str(root)], cwd=root, check=True, capture_output=True)
    subprocess.run([executable, 'format', str(root)], cwd=root, check=True, capture_output=True)


def render_metadata(root):
    import re

    data = json.loads((root / 'tools/refactor/replay_pr_c_inventory.json').read_text(encoding='utf-8'))
    rows = data['additions']
    rows = re.sub(r'\{\{([^}]+)\}\}', lambda m: str(len((root / m[1]).read_text(encoding='utf-8-sig').splitlines())), rows)
    path = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = git(root, 'show', BASE + ':' + path).decode('utf-8')
    source = re.sub(
        r'^\| `desktop_ui.py` \| (\d+) \| \w+ \| `desktop_app/shell/main_window.py` \|[^\n]+',
        r'| `desktop_ui.py` | \1 | composition | `desktop_app/shell/main_window.py` | PR C: shell split leaves registrar and window factory |',
        source,
        flags=re.M,
    )
    source = source.replace('`jobs.py`', '`job.py`')
    source = source.replace('`trading.py`', '`v2.py`')
    source = source.replace('## 3 ', rows + '## 3 ', 1)
    write(root, path, (source + data['size_and_replay']).encode('utf-8'))
    mapping_path = root / 'tools/layer_map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    mapping['prefixes'].update(
        {
            'quantlab/shared/': 'shared',
            'quantlab/research_core/application/': 'application',
            'quantlab/research_core/ports/': 'application',
            'quantlab/research_core/domain/': 'domain',
        }
    )
    mapping['overrides'].update(
        {
            'desktop_app/bootstrap.py': 'composition',
            'desktop_app/shell/main_window.py': 'composition',
            'tools/refactor/measure_ui_sizes.py': 'tooling',
            'tools/refactor/check_ui_scripts.py': 'tooling',
        }
    )
    for row in json.loads((root / 'tools/refactor/replay_pr_c_content.json').read_text(encoding='utf-8'))['files']:
        if row['path'].startswith('tools/refactor/replay_pr_c'):
            mapping['overrides'][row['path']] = 'tooling'
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path = root / 'tools/layer_allowlist.json'
    entries = json.loads(git(root, 'show', BASE + ':tools/layer_allowlist.json'))
    debt = next(row for row in entries if row['path'] == 'desktop_market.py' and row['target'] == 'quantlab.reporting')
    entries = [
        row
        for row in entries
        if row['path'] not in ('desktop_forms.py', 'desktop_ui.py', 'desktop_presentation.py', 'desktop_pages/preferences.py', 'quantlab/desktop_errors.py')
        and not (row['path'] == 'desktop_market.py' and row['target'] in ('quantlab.market_history', 'quantlab.reporting'))
    ]
    entries.append(debt)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ignored_path(name):
    return name.startswith('.tmp-layered/') or '__pycache__' in Path(name).parts or name.endswith('.pyc')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--content-ref')
    parser.add_argument('--expect-root', type=Path)
    args = parser.parse_args()
    manifest = json.loads((SOURCE / 'tools/refactor/replay_pr_c_content.json').read_text(encoding='utf-8'))
    reference = args.content_ref or manifest['content_ref']
    root = args.root.resolve()
    expected = args.expect_root.resolve() if args.expect_root else None
    names = set(git(SOURCE, 'diff', '--name-only', '--no-renames', BASE, 'HEAD').decode().splitlines())
    if expected:
        names.update(git(expected, 'diff', '--name-only', '--no-renames', 'HEAD').decode().splitlines())
        names.update(git(expected, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
    names = {name for name in names if not ignored_path(name)}
    content = run(root, expected, reference, manifest, names)
    differences = []
    for name in sorted(names):
        if expected:
            path = expected / name
            wanted = path.read_bytes() if path.is_file() else None
        else:
            result = subprocess.run(['git', '-C', str(SOURCE), 'show', 'HEAD:' + name], capture_output=True)
            wanted = result.stdout if result.returncode == 0 else None
        path = root / name
        actual = path.read_bytes() if path.is_file() else None
        if name.endswith(('.py', '.json', '.md')):
            actual = actual.replace(b'\r\n', b'\n') if actual is not None else None
            wanted = wanted.replace(b'\r\n', b'\n') if wanted is not None else None
        if actual != wanted:
            differences.append(name)
    status = git(root, 'status', '--porcelain', '-z', '--untracked-files=all', '--no-renames').decode()
    changed = {entry[3:] for entry in status.split('\0') if entry and not ignored_path(entry[3:])}
    outside = sorted(changed - names)
    print(f'mechanical paths produced by scripts: {len(names - content)}')
    print(
        f'replay: {len(names)} paths, {len(content)} content, {len(names - content)} mechanical, {len(differences)} differences, {len(outside)} outside-PR changes'
    )
    for name in differences:
        print('difference: ' + name)
    for name in outside:
        print('outside PR: ' + name)
    return int(bool(differences or outside))


if __name__ == '__main__':
    raise SystemExit(main())
