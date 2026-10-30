"""Extend slice 1 reference edits with required ports and concrete view services."""

from __future__ import annotations
import ast
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.refactor.split_ui_references import expression_name
from tools.refactor.move_desktop_app import offsets, span
from tools.refactor import split_ui_workers as workers

ROOT = Path(__file__).resolve().parents[2]


def inject(source, filename, port_targets):
    if filename in (
        'desktop.py',
        'tools/ui_snapshot.py',
        'tools/ui_readability_audit.py',
        'desktop_app/research_bootstrap.py',
        'desktop_app/smoke/__init__.py',
    ):
        return repair_composition(source, filename)
    tree = ast.parse(source)
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module or '') + '.' + alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
    edits, required = [], set()
    lines, starts = offsets(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = expression_name(node.func)
        prefix = next((key for key in sorted(imports, key=len, reverse=True) if func == key or func.startswith(key + '.')), None)
        target = imports[prefix] + func[len(prefix) :] if prefix else ''
        if (
            target.startswith('desktop_app.shell.window.MainWindow.')
            and target.rsplit('.', 1)[-1] in ('start_job', 'cancel_job', 'poll_jobs', '_busy', 'notify_local', '_notification_link', '_quiesce_and_recover')
            and node.args
        ):
            receiver = node.args.pop(0)
            node.func = ast.Attribute(
                value=ast.Call(func=ast.Name(id='_c_JobPresenter', ctx=ast.Load()), args=[receiver], keywords=[]),
                attr=target.rsplit('.', 1)[-1],
                ctx=ast.Load(),
            )
            required.add('presenter')
            left, right = span(node, lines, starts)
            edits.append((left, right, ast.unparse(ast.fix_missing_locations(node))))
            continue
        if target in port_targets and not (node.args and ast.unparse(node.args[0]) in ('_c_create_operation_ports()', 'ports')):
            node.args.insert(0, ast.parse('_c_create_operation_ports()', mode='eval').body)
            required.add('ports')
        elif target == 'desktop_app.shell.window.MainWindow' and not any(key.arg == 'services' for key in node.keywords):
            node.keywords.append(ast.keyword(arg='services', value=ast.parse('_c_create_ui_services(_c_create_operation_ports())', mode='eval').body))
            required.update(('ports', 'services'))
        elif target in (
            'desktop_app.features.walk_forward.presenter.preview_walk_forward',
            'desktop_app.features.walk_forward.presenter.execute_walk_forward',
        ) and not any(key.arg == 'inputs' for key in node.keywords):
            node.keywords.append(ast.keyword(arg='inputs', value=ast.parse('_c_create_operation_ports().inputs', mode='eval').body))
            required.add('ports')
        else:
            continue
        left, right = span(node, lines, starts)
        edits.append((left, right, ast.unparse(ast.fix_missing_locations(node))))
    selected = []
    for edit in sorted(edits, key=lambda e: (e[0], -e[1])):
        if not selected or edit[0] >= selected[-1][1]:
            selected.append(edit)
    for left, right, text in reversed(selected):
        source = source[:left] + text + source[right:]
    if required:
        anchor = 0
        for node in ast.parse(source).body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                or isinstance(node, ast.ImportFrom)
                and node.module == '__future__'
            ):
                anchor = node.end_lineno
            else:
                break
        existing = ast.parse(source)
        names = {alias.asname for node in existing.body if isinstance(node, ast.ImportFrom) and node.module == 'desktop_app.bootstrap' for alias in node.names}
        added = []
        if 'ports' in required and '_c_create_operation_ports' not in names:
            added.append('create_operation_ports as _c_create_operation_ports')
        if 'services' in required and '_c_create_ui_services' not in names:
            added.append('create_ui_services as _c_create_ui_services')
        if 'presenter' in required:
            lines = source.splitlines(keepends=True)
            lines.insert(anchor, '\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n')
            source = ''.join(lines)
        if added:
            lines = source.splitlines(keepends=True)
            lines.insert(anchor, '\nfrom desktop_app.bootstrap import ' + ', '.join(added) + '\n')
            source = ''.join(lines)
    return source


def main():
    targets = {
        workers.BASE.removesuffix('/').replace('/', '.') + '.' + group + '.' + name
        for group, names in workers.GROUPS.items()
        for name in names
        if name not in workers.PURE_FUNCTIONS
    }
    targets.update(
        {
            'quantlab.research_core.application.' + group + '_operations.' + name
            for group in ('analysis', 'research', 'paper')
            for name in workers.GROUPS[group]
            if name not in workers.PURE_FUNCTIONS
        }
    )
    changed = []
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.py'], cwd=ROOT).decode().split('\0')
    for name in paths:
        if not name or name.startswith(('archives/', 'tools/refactor/')) or name == 'desktop_app/features/walk_forward/presenter.py':
            continue
        path = ROOT / name
        source = path.read_text(encoding='utf-8-sig')
        while '_c_create_operation_ports(), _c_create_operation_ports(),' in source:
            source = source.replace('_c_create_operation_ports(), _c_create_operation_ports(),', '_c_create_operation_ports(),')
        updated = inject(source, name, targets)
        if updated != path.read_text(encoding='utf-8-sig'):
            path.write_text(updated, encoding='utf-8', newline='\n')
            changed.append(name)
    print(json.dumps(changed))


def repair_composition(source, filename):
    """Keep launchers lazy and delegate construction to the assembly root."""
    import re

    source = re.sub(r'^from desktop_app.bootstrap import .*\n\n?', '', source, flags=re.MULTILINE)
    if filename == 'desktop_app/smoke/__init__.py':
        anchor = '    expected = preview_walk_forward('
        if '_c_create_operation_ports' in source and '    from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports' not in source:
            source = source.replace(anchor, '    from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports\n\n' + anchor)
        return source
    if filename == 'desktop_app/research_bootstrap.py':
        source = (
            source.replace(
                '        from desktop_app.shell.window import MainWindow\n',
                '        from desktop_app.shell.window import MainWindow\n        from desktop_app.shell.main_window import create_window\n',
            )
            if '        from desktop_app.shell.main_window import create_window' not in source
            else source
        )
        return source.replace(
            'window = EmbeddedWindow(state.paths, state.jobs, state.settings, state.backups, state.guard)',
            'window = create_window(state.paths, state.jobs, state.settings, state.backups, state.guard, window_type=EmbeddedWindow)',
        )
    source = source.replace('from desktop_app.shell.window import MainWindow', 'from desktop_app.shell.main_window import create_window')
    source = source.replace('state.window = MainWindow(', 'state.window = create_window(').replace('window = MainWindow(', 'window = create_window(')
    return re.sub(r'^\s*services=_c_create_ui_services\(_c_create_operation_ports\(\)\),?\n', '', source, flags=re.MULTILINE)


if __name__ == '__main__':
    main()
