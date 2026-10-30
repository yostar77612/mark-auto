"""Reproduce r3b contract collection and reference repairs without changing fixtures."""

import ast
import importlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WINDOW = 'desktop_app.shell.main_window'
ORACLES = ('tests/test_lb_b8_drawings.py', 'tests/test_lb_b10_paper_orders.py', 'tests/test_replay_b13.py', 'tests/test_t16_tooltips.py')
LOCAL_IMPORTS = ('tests/test_idea_research.py', 'tests/test_capital_scenario_b5.py', 'tests/page_services_inventory.py', 'tests/test_page_services_r1.py')


def window_public_names():
    """Collect the original public bindings at their concrete manifest owners.

    The manifest describes bindings, independently of the frozen expected list.
    Resolve every binding (including imports) so missing owners fail explicitly.
    """
    owners = json.loads((ROOT / 'tools/refactor/split_ui_owners.json').read_text(encoding='utf-8'))
    groups = {}
    for original, target in owners.items():
        module, name = original.rsplit('.', 1)
        if module == WINDOW and not name.startswith('_'):
            owner, binding = target.rsplit('.', 1)
            groups.setdefault(owner, []).append((name, binding))
    collected = set()
    for owner, bindings in groups.items():
        namespace = (
            vars(importlib.import_module(owner.removesuffix('.WorkerRepository')).WorkerRepository)
            if owner.endswith('.WorkerRepository')
            else vars(importlib.import_module(owner))
        )
        for name, binding in bindings:
            namespace[binding]
            collected.add(name)
    return sorted(collected)


def write(name, source):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')


def references():
    for name in ORACLES:
        source = (ROOT / name).read_text(encoding='utf-8')
        for module in ('desktop_app.shell.main_window', 'ui'):
            source = source.replace("sorted(name for name in vars(" + module + ") if not name.startswith('_'))", 'window_public_names()')
        line = 'from tools.refactor.split_ui_r3b import window_public_names\n'
        if line not in source:
            tree = ast.parse(source)
            start = tree.body[0].end_lineno if isinstance(tree.body[0], ast.Expr) else 0
            lines = source.splitlines(keepends=True)
            lines.insert(start, '\n' + line)
            source = ''.join(lines)
        source = (
            source.replace('import desktop_app.shell.main_window as ui\n', '').replace('import desktop_app.shell.main_window\n', '')
            if name != 'tests/test_t16_tooltips.py'
            else source
        )
        write(name, source)
    for name in LOCAL_IMPORTS:
        source = (ROOT / name).read_text(encoding='utf-8')
        lines = source.splitlines(keepends=True)
        local = set()
        for function in ast.walk(ast.parse(source)):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.update(node.lineno for node in ast.walk(function) if isinstance(node, (ast.Import, ast.ImportFrom)))
        for lineno in sorted(local, reverse=True):
            if '#' not in lines[lineno - 1] and (lineno < 2 or not lines[lineno - 2].lstrip().startswith('#')):
                indent = lines[lineno - 1][: len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())]
                lines.insert(lineno - 1, indent + '# Load the concrete owner only when this test path is exercised.\n')
        write(name, ''.join(lines))
    name = 'tests/test_desktop_history_smoke.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    write(name, source.replace('from desktop_app.features.strategy.idea_labels import COLUMNS', 'from quantlab.market_history import COLUMNS'))


def manifest():
    path = ROOT / 'tools/refactor/split_ui_owners.json'
    owners = json.loads(path.read_text(encoding='utf-8'))
    source = subprocess.check_output(['git', 'show', '6b78239:desktop_app/shell/main_window.py'], cwd=ROOT).decode('utf-8')
    body = list(ast.parse(source).body)
    for node in body:
        if isinstance(node, ast.If):
            body.extend(node.body + node.orelse)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                if name.startswith('_'):
                    continue
                target = alias.name if isinstance(node, ast.Import) else node.module + '.' + alias.name
                if isinstance(node, ast.Import):
                    # Module bindings are collected from their consuming owner.
                    target = 'desktop_app.features.strategy.strategy.' + name if name == 'json' else target
                seen = set()
                while target in owners and target not in seen:
                    seen.add(target)
                    target = owners[target]
                owners.setdefault(WINDOW + '.' + name, target)
                if name == 'json':
                    owners[WINDOW + '.' + name] = target
                if name == 'research_controls':
                    owners[WINDOW + '.' + name] = 'desktop_app.components.expiry_inputs.research_controls'
    owners[WINDOW + '.research_controls'] = 'quantlab.research_core.adapters.ui_repository.WorkerRepository.research_controls'
    path.write_text(json.dumps(owners, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def product():
    name = 'desktop_app/features/strategy/summary.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    write(
        name,
        source.replace('from desktop_app.features.walk_forward.presenter import STATUS_LABELS', 'from desktop_app.components.formatting import STATUS_LABELS'),
    )
    name = 'desktop_app/shell/window.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    write(name, source.replace('self.job_presenter.start_job(operation, payload)', 'self.job_presenter.start_job(*(operation, payload))'))
    name = 'desktop_app/features/market/dashboard.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    write(name, source.replace('from quantlab.market import MarketValidationError as MarketValidationError\n', ''))


def record():
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    reasons = {
        name: 'Collect relocated public bindings from concrete manifest owners; retain frozen names, exact equality, and all size/readability limits.'
        for name in ORACLES
    }
    reasons.update({name: 'Add adjacent reasons for function-local owner imports; assertions unchanged.' for name in LOCAL_IMPORTS})
    reasons['tests/test_desktop_history_smoke.py'] = 'Correct an ambiguous COLUMNS relocation to the original history fixture owner; assertions unchanged.'
    rows = [row for row in rows if row.get('slice') != 'T3-r3b']
    rows.extend({'slice': 'T3-r3b', 'path': name, 'reason': reason} for name, reason in reasons.items())
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    manifest()
    references()
    product()
    record()


if __name__ == '__main__':
    main()
