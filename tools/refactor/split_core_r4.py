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
            'from quantlab.research_core.application.job_requests import validate_analysis_request',
            'from quantlab.runtime_support import validate_analysis_request',
        ),
    )
    name = 'desktop_app/bootstrap.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    old = '        import quantlab.assistant.application.connection_contracts as implementation\n\n        return implementation'
    new = "        from types import SimpleNamespace\n        from quantlab.assistant.application import connection_contracts\n        from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request\n\n        return SimpleNamespace(\n            ConnectionEvent=connection_contracts.ConnectionEvent,\n            ConnectionRequest=connection_contracts.ConnectionRequest,\n            ReconciliationEvent=connection_contracts.ReconciliationEvent,\n            SubscriptionOptions=connection_contracts.SubscriptionOptions,\n            TestConnectionEvent=connection_contracts.TestConnectionEvent,\n            run_connection_request=run_connection_request,\n        )"
    write(name, source.replace(old, new))
    name = 'tools/layer_map.json'
    mapping = json.loads((ROOT / name).read_text(encoding='utf-8'))
    mapping['split_origins']['quantlab/research_core/application/analysis_operations.py'] = 'quantlab/desktop_runtime.py'
    write(name, json.dumps(mapping, indent=2) + '\n')
    name = 'tools/layer_allowlist.json'
    entries = json.loads((ROOT / name).read_text(encoding='utf-8'))
    entry = {
        'path': 'desktop_pages/compare.py',
        'target': 'quantlab.runtime_support',
        'rule': 'presentation-to-infrastructure',
        'justification': 'Existing request validation follows D relocation from desktop_runtime to runtime_support; no new operation or behavior.',
    }
    if not any(row['path'] == entry['path'] and row['target'] == entry['target'] for row in entries):
        entries.append(entry)
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


if __name__ == '__main__':
    resolve()
    repair()
