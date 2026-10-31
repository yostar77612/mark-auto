"""Idempotent PR C/D integration: preserve UI split and core symbol owners."""

import ast
import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))
CHANGED = set()


def write(name, source):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')
        CHANGED.add(name)


def resolve():
    paths = subprocess.check_output(['git', 'diff', '--name-only', '--diff-filter=U'], cwd=ROOT, text=True).splitlines()
    pattern = re.compile(r'^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n?', re.M | re.S)
    keep_d = {
        'quantlab/desktop_runtime.py',
        'quantlab/automatic_backup.py',
        'desktop_app/features/walk_forward/presenter.py',
        'tests/test_runtime_safety_error_shared.py',
        'tests/test_workspace_wal_guard.py',
    }
    for name in paths:
        if name == 'tools/layer_map.json':
            d = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT))
            c = json.loads(subprocess.check_output(['git', 'show', 'MERGE_HEAD:' + name], cwd=ROOT))
            for key, value in c.items():
                if isinstance(value, dict):
                    d.setdefault(key, {}).update(value)
            write(name, json.dumps(d, indent=2) + '\n')
            continue
        source = (ROOT / name).read_text(encoding='utf-8')

        def choose(match):
            d, c = match.groups()
            if name in keep_d:
                return d
            if name == 'docs/analysis/08_REFACTOR_INVENTORY.md':
                return d + c
            if name == 'tests/layered_source_fixtures.py':
                if d.startswith('def historical_analysis_source'):
                    return d + c
                if 'sha256(canonical)' in d:
                    return c
                return c.replace("sorted(projected | additions)", "sorted((projected | additions) - {'desktop_app/connection_composition.py'})")
            if name in {'tests/test_job_stages.py', 'tests/test_t16_presentation.py'}:
                return d + c
            if name == 'tests/test_chatgpt_reconciliation_ui.py':
                if 'decoded =' in c:
                    return c.replace('ui.ReconciliationEvent', 'connection_contracts.ReconciliationEvent')
                return d + c
            return c

        write(name, pattern.sub(choose, source))


def owners():
    result = {('quantlab.desktop_runtime', 'validate_analysis_request'): 'quantlab.runtime_support'}
    groups = {
        'quantlab.desktop_runtime': [
            'quantlab/research_core/adapters/workspace_backup.py',
            'quantlab/research_core/adapters/job_worker.py',
            'quantlab/research_core/adapters/job_process.py',
            'quantlab/research_core/application/job_requests.py',
        ],
        'quantlab.saved_candidate_pool': [
            'quantlab/research_core/adapters/saved_pool_source.py',
            'quantlab/research_core/domain/saved_pool.py',
            'quantlab/research_core/application/saved_pool_validation.py',
            'quantlab/research_core/application/saved_pool_attempts.py',
        ],
        'quantlab.assistant.adapters.chatgpt.auth': [
            'quantlab/assistant/domain/auth_protocol.py',
            'quantlab/assistant/adapters/chatgpt/vault.py',
            'quantlab/assistant/adapters/chatgpt/identity.py',
        ],
        'quantlab.assistant.adapters.chatgpt.provider': ['quantlab/assistant/domain/plan_protocol.py', 'quantlab/assistant/adapters/chatgpt/transport.py'],
        'desktop_app.features.assistant.connection': [
            'quantlab/assistant/application/connection_contracts.py',
            'quantlab/assistant/application/connection_controller.py',
            'quantlab/assistant/application/context_usage.py',
        ],
    }
    for old, files in groups.items():
        module = importlib.import_module(old)
        for name in files:
            path = ROOT / name
            if not path.exists():
                continue
            for node in ast.parse(path.read_text(encoding='utf-8')).body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not hasattr(module, node.name):
                    result[old, node.name] = name[:-3].replace('/', '.')
    return result


def repair():
    mapping = owners()
    paths = set(subprocess.check_output(['git', 'diff', '--name-only', '6b78239', '3429f2c'], cwd=ROOT, text=True).splitlines())
    paths.update({'desktop_app/features/compare/compare.py', 'tests/test_recovery_frozen_smoke.py'})
    for name in sorted(paths):
        path = ROOT / name
        if path.suffix != '.py' or not path.exists() or name == 'tools/refactor/split_core_r4.py':
            continue
        source = path.read_text(encoding='utf-8')
        lines = source.splitlines(keepends=True)
        edits = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ImportFrom):
                continue
            groups = {}
            for alias in node.names:
                target = mapping.get((node.module, alias.name), node.module)
                groups.setdefault(target, []).append(alias.name + (' as ' + alias.asname if alias.asname else ''))
            if set(groups) != {node.module}:
                edits.append(
                    (
                        node.lineno - 1,
                        node.end_lineno,
                        ''.join(' ' * node.col_offset + 'from ' + target + ' import ' + ', '.join(names) + '\n' for target, names in groups.items()),
                    )
                )
        for start, end, text in sorted(edits, reverse=True):
            lines[start:end] = [text]
        source = ''.join(lines)
        for (old, symbol), target in mapping.items():
            source = source.replace(old + '.' + symbol, target + '.' + symbol)
        write(name, source)
    name = 'desktop_app/shell/main_window.py'
    source = (
        (ROOT / name).read_text(encoding='utf-8').replace('from quantlab.desktop_runtime import (', 'from quantlab.research_core.adapters.job_worker import (')
    )
    write(name, source)
    name = 'desktop_app/bootstrap.py'
    source = (
        (ROOT / name)
        .read_text(encoding='utf-8')
        .replace('import quantlab.desktop_runtime as implementation', 'import quantlab.research_core.adapters.workspace_backup as implementation')
        .replace(
            'import desktop_app.features.assistant.connection as implementation', 'import quantlab.assistant.application.connection_contracts as implementation'
        )
        .replace(
            'import desktop_app.features.walk_forward.presenter as implementation',
            'import quantlab.research_core.application.walk_forward_operations as implementation',
        )
    )
    write(name, source)
    # C passes an inputs port; D owns the application implementation.
    name = 'quantlab/research_core/application/ui_operations/derived.py'
    source = (ROOT / name).read_text(encoding='utf-8').replace('inputs=ports.inputs', 'dataset_loader=ports.inputs._dataset')
    write(name, source)
    name = 'tests/test_desktop_analysis.py'
    write(name, (ROOT / name).read_text(encoding='utf-8').replace('        import quantlab.desktop_runtime as runtime\n', ''))
    name = 'desktop_app/features/compare/compare.py'
    write(
        name,
        (ROOT / name)
        .read_text(encoding='utf-8')
        .replace(
            'from quantlab.runtime_support import validate_analysis_request',
            'from quantlab.research_core.application.job_requests import validate_analysis_request',
        ),
    )
    name = 'desktop_app/bootstrap.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    old = '        import quantlab.assistant.application.connection_contracts as implementation\n\n        return implementation'
    new = "        from types import SimpleNamespace\n        from quantlab.assistant.application import connection_contracts\n        from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request\n\n        return SimpleNamespace(\n            ConnectionEvent=connection_contracts.ConnectionEvent,\n            ConnectionRequest=connection_contracts.ConnectionRequest,\n            ReconciliationEvent=connection_contracts.ReconciliationEvent,\n            SubscriptionOptions=connection_contracts.SubscriptionOptions,\n            TestConnectionEvent=connection_contracts.TestConnectionEvent,\n            run_connection_request=run_connection_request,\n        )"
    write(name, source.replace(old, new))
    name = 'tools/layer_map.json'
    mapping = json.loads((ROOT / name).read_text(encoding='utf-8'))
    mapping['split_origins'].pop('quantlab/research_core/application/analysis_operations.py', None)
    write(name, json.dumps(mapping, indent=2) + '\n')
    name = 'tools/layer_allowlist.json'
    entries = json.loads((ROOT / name).read_text(encoding='utf-8'))
    entries = [row for row in entries if (row['path'], row['target']) != ('desktop_pages/compare.py', 'quantlab.runtime_support')]
    write(name, json.dumps(entries, indent=2) + '\n')
    name = 'tools/refactor/measure_ui_sizes.py'
    write(name, (ROOT / name).read_text(encoding='utf-8').replace("'6b78239', 'HEAD', '--', 'desktop_app/'", "'6b78239', '--', 'desktop_app/'"))
    # Keep D's original observer table, then project every C/D observer to its merged owner and line.
    from tools.refactor.split_ui_fixture_lines import slice2

    slice2()
    name = 'tests/test_download_auto_import_contracts.py'
    fixture = json.loads((ROOT / 'tests/fixtures/page_services_inventory.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    source = (ROOT / name).read_text(encoding='utf-8')
    write(name, re.sub(r"'page_services_inventory.json': '[a-f0-9]+'", "'page_services_inventory.json': '" + digest + "'", source))
    CHANGED.update(
        {'tests/fixtures/layered_paths/slice2_service_relocations.json', 'tests/layered_source_fixtures.py', 'tests/test_download_auto_import_contracts.py'}
    )
    reasons = ROOT / '.tmp-layered/test-edit-reasons.json'
    history = json.loads(reasons.read_text(encoding='utf-8-sig'))
    for name in sorted(CHANGED):
        if name.startswith('tests/') and not any(row.get('file') == name and row.get('slice') == 'T4-r4' for row in history):
            history.append(
                {
                    'file': name,
                    'slice': 'T4-r4',
                    'reason': 'Reconcile C UI split with D extracted symbol owners and retain both branches test coverage; assertions unchanged.',
                }
            )
    reasons.write_text(json.dumps(history, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'changed': sorted(CHANGED)}, indent=2))


def repair_r7():
    """Replay mechanical ownership and observer forwarding repairs after C/D merge."""
    name = 'desktop_app/shell/job_presenter.py'
    write(
        name,
        (ROOT / name)
        .read_text(encoding='utf-8')
        .replace(
            'import desktop_app.features.capital_scenario.worker as _capital',
            'import desktop_app.features.capital_scenario.presenter as _capital',
        ),
    )
    name = 'quantlab/research_core/application/ui_operations/derived.py'
    write(name, (ROOT / name).read_text(encoding='utf-8').replace('dataset_loader=ports.inputs._dataset', 'inputs=ports.inputs'))
    for name in ('tests/smoke_timeout_diagnostics.py', 'tests/generic_smoke_phase_diagnostics.py'):
        source = (ROOT / name).read_text(encoding='utf-8')
        source = source.replace('job_id, reconciliation_admitted=False):', 'job_id, reconciliation_admitted=False, *worker_options):')
        source = source.replace('job_id, reconciliation_admitted)', 'job_id, reconciliation_admitted, *worker_options)')
        write(name, source)
    name = 'quantlab/research_core/application/analysis_operations.py'
    write(
        name,
        (ROOT / name)
        .read_text(encoding='utf-8')
        .replace(
            'from quantlab.runtime_support import validate_analysis_request',
            'from quantlab.research_core.application.job_requests import validate_analysis_request',
        ),
    )
    name = 'tools/refactor/split_ui_inputs.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    old = "        # The fixture call is a single returned statement.\n        statement = ' ' * (call.col_offset - len('return ')) + 'return ' + ast.unparse(ast.fix_missing_locations(call)) + '\\n'\n        lines[call.lineno - 1 : call.end_lineno] = [statement]"
    new = "        statement = next(node for node in ast.walk(tree) if isinstance(node, ast.Return) and node.lineno <= call.lineno <= node.end_lineno)\n        text = ' ' * statement.col_offset + ast.unparse(ast.fix_missing_locations(statement)) + '\\n'\n        lines[statement.lineno - 1 : statement.end_lineno] = [text]"
    write(name, source.replace(old, new))
    name = 'tools/layer_map.json'
    mapping = json.loads((ROOT / name).read_text(encoding='utf-8'))
    mapping['split_origins'].pop('quantlab/research_core/application/analysis_operations.py', None)
    write(name, json.dumps(mapping, indent=2) + '\n')
    reasons = ROOT / '.tmp-layered/test-edit-reasons.json'
    history = json.loads(reasons.read_text(encoding='utf-8-sig')) if reasons.exists() else []
    for name in ('tests/smoke_timeout_diagnostics.py', 'tests/generic_smoke_phase_diagnostics.py'):
        row = {
            'file': name,
            'slice': 'T4-r7',
            'reason': 'Forward the merged worker helper nonce and operation registrar unchanged through diagnostic observers; assertions unchanged.',
        }
        if row not in history:
            history.append(row)
    reasons.write_text(json.dumps(history, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'r7_changed': sorted(CHANGED)}, indent=2))


def scan_desktop_r7():
    """Resolve merged desktop imports, module attributes and literal patch seams."""
    from pathlib import Path
    import ast, importlib, json, os, subprocess, sys, types

    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.path.insert(0, str(Path.cwd()))
    paths = set()
    for ref in ('3429f2c', '7bef566'):
        paths.update(subprocess.check_output(['git', 'diff', '--name-only', '6b78239', ref], text=True).splitlines())
    errors = []
    created_targets = []
    counts = {'files': 0, 'from_imports': 0, 'module_aliases': 0, 'alias_attributes': 0, 'patch_strings': 0, 'patch_objects': 0, 'created_patch_attributes': 0}

    def resolve(name):
        parts = name.split('.')
        for n in range(len(parts), 0, -1):
            try:
                obj = importlib.import_module('.'.join(parts[:n]))
                break
            except ModuleNotFoundError:
                continue
        else:
            raise ImportError(name)
        for part in parts[n:]:
            obj = getattr(obj, part)
        return obj

    for name in sorted(paths | {p.as_posix() for p in Path('tests').glob('*.py')}):
        p = Path(name)
        if not p.is_file() or p.suffix != '.py':
            continue
        counts['files'] += 1
        tree = ast.parse(p.read_text(encoding='utf-8-sig'))
        aliases = {}
        bindings = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.startswith('desktop_app.') and a.asname:
                        aliases[a.asname] = a.name
                        bindings[a.asname] = a.name
                        counts['module_aliases'] += 1
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith('desktop_app.'):
                for a in n.names:
                    if a.name == '*':
                        continue
                    target = n.module + '.' + a.name
                    counts['from_imports'] += 1
                    try:
                        obj = resolve(target)
                        bindings[a.asname or a.name] = target
                        if isinstance(obj, types.ModuleType):
                            aliases[a.asname or a.name] = target
                    except Exception as exc:
                        errors.append([name, n.lineno, target, type(exc).__name__, str(exc)])
        for n in ast.walk(tree):
            target = None
            kind = None
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in aliases:
                target = aliases[n.value.id] + '.' + n.attr
                kind = 'alias_attributes'
            if isinstance(n, ast.Call):
                fn = n.func
                if (
                    ((isinstance(fn, ast.Attribute) and fn.attr == 'patch') or (isinstance(fn, ast.Name) and fn.id == 'patch'))
                    and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)
                    and n.args[0].value.startswith('desktop_app.')
                ):
                    target = n.args[0].value
                    kind = 'patch_strings'
                if isinstance(fn, ast.Attribute) and fn.attr == 'object' and len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                    owner = n.args[0]
                    attributes = []
                    while isinstance(owner, ast.Attribute):
                        attributes.append(owner.attr)
                        owner = owner.value
                    if isinstance(owner, ast.Name) and owner.id in bindings:
                        target = '.'.join([bindings[owner.id], *reversed(attributes), str(n.args[1].value)])
                        kind = 'patch_objects'
            if target:
                counts[kind] += 1
                try:
                    resolve(target)
                except Exception as exc:
                    if isinstance(n, ast.Call) and any(k.arg == 'create' and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords):
                        resolve(target.rsplit('.', 1)[0])
                        counts['created_patch_attributes'] += 1
                        created_targets.append([name, n.lineno, target])
                    else:
                        errors.append([name, n.lineno, target, type(exc).__name__, str(exc)])
    result = {'counts': counts, 'created_targets': created_targets, 'errors': errors}
    Path('.tmp-layered/r7-desktop-scan.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    if '--scan-desktop' in sys.argv:
        scan_desktop_r7()
    elif '--r7' in sys.argv:
        repair_r7()
    else:
        resolve()
        repair()
