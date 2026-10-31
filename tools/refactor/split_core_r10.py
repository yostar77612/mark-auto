"""Reproduce T4-r10 registrar parity and the deferred-import reason."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'
IMPORT = '    from quantlab.research_core.application.walk_forward_operations import execute_walk_forward as execute'
REASON = '    # Keep operation-specific dependencies out of module startup.\n'


def write(name, source):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')


def main():
    name = 'quantlab/research_core/domain/job_protocol.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    source = re.sub(r"(?m)^DEFAULT_OPERATION_REGISTRAR = .*", f'DEFAULT_OPERATION_REGISTRAR = {REGISTRAR!r}', source)
    write(name, source)
    for name in ('desktop_app/features/walk_forward/presenter.py', 'tools/refactor/split_core_r8.py'):
        source = (ROOT / name).read_text(encoding='utf-8')
        if REASON + IMPORT not in source:
            source = source.replace(IMPORT, REASON + IMPORT)
        write(name, source)
    for name, target in (
        ('tools/refactor/split_core_r3c.py', 'desktop_app/shell/main_window.py'),
        ('tools/refactor/split_core_ui.py', 'quantlab/research_core/domain/job_protocol.py'),
    ):
        source = (ROOT / name).read_text(encoding='utf-8')
        # Earlier migrations must retain PR C's canonical registrar.
        pattern = r'    replace\(\n        ' + re.escape(repr(target)) + r',\n        "[^"\n]*REGISTRAR[^"\n]*",\n        "[^"\n]*REGISTRAR[^"\n]*",\n    \)\n'
        write(name, re.sub(pattern, '', source))
    name = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = (ROOT / name).read_text(encoding='utf-8')
    paths = {
        'desktop_walk_forward.py': 'desktop_app/features/walk_forward/presenter.py',
        **{f'tools/refactor/{stem}.py': f'tools/refactor/{stem}.py' for stem in ('split_core_r3c', 'split_core_ui', 'split_core_r8', 'split_core_r10')},
    }
    if '| `tools/refactor/split_core_r10.py` |' not in source:
        anchor = next(line for line in source.splitlines() if line.startswith('| `tools/refactor/split_core_r8.py` |'))
        source = source.replace(
            anchor,
            anchor
            + '\n| `tools/refactor/split_core_r10.py` | 0 | tooling | `tools/refactor/split_core_r10.py` | T4-r10 reproducible integration repair; existing tools/ layer assignment. |',
        )
    for logical, physical in paths.items():
        count = len((ROOT / physical).read_text(encoding='utf-8').splitlines())
        # Only the current inventory table, not historical split-plan counts.
        pattern = r'(?m)^(\| `' + re.escape(logical) + r'` \| )\d+( \| (?:presentation|tooling) \|)'
        source = re.sub(pattern, lambda match: f'{match[1]}{count}{match[2]}', source)
    write(name, source)


if __name__ == '__main__':
    main()
