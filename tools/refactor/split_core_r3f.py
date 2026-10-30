"""Reproduce T4-r3f/r3g base patch points and passive desktop imports."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def repair():
    path = ROOT / 'quantlab/research_core/application/walk_forward_operations.py'
    source = path.read_text(encoding='utf-8')
    names = (
        '_validate_source',
        'walk_forward_plan_from_dict',
        'walk_forward_binding',
        'planned_evaluations',
        'run_walk_forward',
        'read_walk_forward_state',
        'reconcile_interrupted_walk_forward',
    )
    binding = 'from quantlab.walk_forward import (\n' + ''.join(f'    {name},\n' for name in names) + ')\n'
    source = source.replace('from quantlab.walk_forward import run_walk_forward\n', '')
    if binding not in source:
        if 'from quantlab import walk_forward\n' in source:
            source = source.replace('from quantlab import walk_forward\n', binding)
        else:
            source = binding + '\n' + source
    source = source.replace('from quantlab import walk_forward\n', '')
    for name in names:
        source = source.replace('walk_forward.' + name + '(', name + '(')
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8', newline='\n')

    path = ROOT / 'desktop_app/connection_composition.py'
    source = path.read_text(encoding='utf-8')
    source = source.replace('import desktop_app.shell.main_window as operations\n', '')
    source = source.replace('    from desktop_app.shell import main_window as operations\n\n', '')
    source = source.replace('return operations.execute_ui_operation(*args, **kwargs)', 'return execute(*args, **kwargs)')
    anchor = 'def execute_ui_operation(*args, **kwargs):\n'
    source = source.replace('    from desktop_app.shell.main_window import execute_ui_operation as execute\n\n', '')
    lazy_import = (
        '    from quantlab.research_core.adapters.job_worker import _worker_operation_executor\n\n'
        "    execute = _worker_operation_executor('desktop_app.shell.main_window:execute_ui_operation')\n\n"
    )
    if anchor + lazy_import not in source:
        source = source.replace(anchor, anchor + lazy_import)
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8', newline='\n')

    repair_launch_lookup()
    repair_inventory()


def repair_launch_lookup():
    path = ROOT / 'quantlab/research_core/adapters/job_process.py'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'(?m)^from quantlab.research_core.adapters import job_worker\n', '', source)
    anchor = 'def _launch_job_process(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request):\n'
    local_import = '    from quantlab.research_core.adapters import job_worker\n\n'
    if anchor + local_import not in source:
        source = source.replace(anchor, anchor + local_import)
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8', newline='\n')


def repair_inventory():
    path = ROOT / 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = path.read_text(encoding='utf-8')
    mapping_path = ROOT / 'tools/layer_map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    for script in sorted((ROOT / 'tools/refactor').glob('split_core_*.py')):
        name = script.relative_to(ROOT).as_posix()
        count = len(script.read_text(encoding='utf-8').splitlines())
        row = f'| `{name}` | {count} | tooling | `{name}` | PR D reproducible repair |'
        pattern = rf'(?m)^\| `{re.escape(name)}` \|[^\n]*$'
        if re.search(pattern, source):
            source = re.sub(pattern, lambda match: row, source)
        else:
            index = source.index('\n## 3 ')
            source = source[:index] + '\n' + row + '\n' + source[index:]
        mapping['overrides'][name] = 'tooling'
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8', newline='\n')
    updated = json.dumps(mapping, ensure_ascii=False, indent=2) + '\n'
    if updated != mapping_path.read_text(encoding='utf-8'):
        mapping_path.write_text(updated, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    repair()
