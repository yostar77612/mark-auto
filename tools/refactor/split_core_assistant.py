"""Reproduce the assistant provider split and mechanical reference updates.

Extraction reads the reviewed pre-split Git object; reference updates are
idempotent and use symbol ownership, retaining patch targets at lookup sites.
"""

import ast
import builtins
from pathlib import Path
import subprocess
import symtable

ROOT = Path(__file__).resolve().parents[2]
BASE = '6b78239'
OLD = 'quantlab.assistant.adapters.chatgpt.provider'
PREFIX = 'quantlab.assistant.adapters.chatgpt.'
GROUPS = {
    'quantlab.assistant.domain.plan_protocol': (
        'MODELS_URL MODELS_MAX_RESPONSE_BYTES RESPONSES_URL ACKNOWLEDGEMENT_VERSION '
        '_CONFIRMED_CONSUMED _RESOLUTION_MIN_AGE_SECONDS _FINISHED_UNKNOWN_STATUSES '
        'FINISHED_ACKNOWLEDGEMENT_VERSION _FINISHED_ACKNOWLEDGEMENT_VERSIONS ERROR_STATES '
        'PlanError _fail _unique _json _integer _remote_error parse_models'
    ).split(),
    PREFIX + 'account_paths': '_controls_for _reject_links'.split(),
    PREFIX + 'response_stream': 'SSEParser _CompletedItems _completed_payload'.split(),
    PREFIX + 'transport': '_check PlanHTTPTransport'.split(),
    PREFIX + 'provenance': '_dependency_manifest _dependency_target implementation_provenance'.split(),
    PREFIX + 'account_store': ('_CONTROL_MARKER _open_account_controls _persist_account_pause _installation_barrier').split(),
    PREFIX + 'resolution_audit': (
        '_resolution_registration _resolution_audit_triggers _FINISHED_AUDIT_TABLE_SQL '
        '_finished_audit_triggers_sql _normalized_sql _finished_audit_valid _receipt_digest '
        '_confirmed_registration _resolution_controls'
    ).split(),
    PREFIX + 'unknown_reconciliation': '_unknown_request_snapshot _create_resolution_audit'.split(),
    PREFIX + 'finished_reconciliation': ('_finished_request_snapshot _create_finished_resolution_audit').split(),
    PREFIX + 'campaign_receipts': '_checked_campaign_rows _rows_to_receipts'.split(),
    OLD: (
        'parse_completed ChatGPTPlanProvider analysis_provider discover_models '
        'inspect_unknown_request resolve_unknown_request inspect_finished_unknown_request '
        'resolve_finished_unknown_request clear_account_pause read_account_status'
    ).split(),
}
OWNERS = {name: module for module, names in GROUPS.items() for name in names}


def globals_used(source):
    pending = [symtable.symtable(source, '<split>', 'exec')]
    result = set()
    while pending:
        table = pending.pop()
        result.update(s.get_name() for s in table.get_symbols() if s.is_global() and s.is_referenced())
        pending.extend(table.get_children())
    return result


def extract():
    source = subprocess.check_output(['git', 'show', BASE + ':quantlab/assistant/adapters/chatgpt/provider.py'], cwd=ROOT).decode('utf-8')
    tree = ast.parse(source)
    nodes, imports = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for item in node.names:
                if item.name == 'annotations':
                    continue
                module = node.module if isinstance(node, ast.ImportFrom) else None
                if item.name == 'official_tls_context':
                    module = PREFIX + 'identity'
                elif item.name == '_validated_receipt_snapshot':
                    module = 'quantlab.research_core.domain.receipts'
                imports[item.asname or item.name.split('.')[0]] = ('from ' + module + ' import ' + item.name if module else 'import ' + item.name) + (
                    ' as ' + item.asname if item.asname else ''
                )
    for module, names in GROUPS.items():
        body = '\n\n\n'.join(ast.get_source_segment(source, nodes[name]) for name in names) + '\n'
        used = globals_used(body) - set(names) - set(dir(builtins)) - {'__file__'}
        lines = []
        for name in sorted(used):
            if name in OWNERS:
                lines.append('from ' + OWNERS[name] + ' import ' + name)
            elif name in imports:
                lines.append(imports[name])
            else:
                raise ValueError('Unresolved global: ' + module + ':' + name)
        path = ROOT / (module.replace('.', '/') + '.py')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '"""'
            + module.rsplit('.', 1)[-1].replace('_', ' ').capitalize()
            + ' responsibility; original guards and ordering preserved."""\n'
            + 'from __future__ import annotations\n\n'
            + '\n'.join(sorted(set(lines)))
            + '\n\n\n'
            + body,
            encoding='utf-8',
            newline='\n',
        )


def references():
    # Do not touch C-owned files; the preserved shell import is recorded separately.
    excluded = {
        'desktop_app/shell/main_window.py',
        'desktop_app/components/forms.py',
        'desktop_app/components/charts.py',
        'desktop_app/features/market/dashboard.py',
        'desktop_app/features/strategy/idea_research.py',
    }
    auth = {
        **{name: PREFIX + 'vault' for name in ('DPAPIVault',)},
        **{name: PREFIX + 'identity' for name in ('OfficialTransport', 'IdentityValidator', 'official_tls_context')},
        **{
            name: 'quantlab.assistant.domain.auth_protocol'
            for name in (
                'AuthError',
                'HttpResponse',
                'AUTHORIZE',
                'TOKEN',
                'REVOCATION',
                'DISCOVERY',
                'JWKS',
                'ISSUER',
                'RESOURCE',
                'DYNAMIC_CLIENT',
                'SCOPES',
                'PLAN_SCOPES',
                'PINNED_DISCOVERY',
                'MAX_RECORD',
                'TERMINAL_REFRESH_ERRORS',
                'pkce_challenge',
                '_validate_record',
                '_json',
                '_unique',
                '_bytes',
                '_text',
                '_number',
                '_client',
            )
        },
    }
    for folder in ('quantlab', 'desktop_app', 'tests', 'tools', 'packaging'):
        for path in (ROOT / folder).rglob('*.py'):
            relative = path.relative_to(ROOT).as_posix()
            if relative in excluded or relative.startswith(('tools/refactor/', 'desktop_app/strings/')):
                continue
            source = path.read_text(encoding='utf-8')
            if 'auth_status_summary' in source:
                parsed = ast.parse(source)
                replacements = []
                offsets = [0]
                for line in source.splitlines(keepends=True):
                    offsets.append(offsets[-1] + len(line))
                for call in ast.walk(parsed):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'auth_status_summary':
                        argument = ast.get_source_segment(source, call.args[0])
                        replacements.append(
                            (offsets[call.lineno - 1] + call.col_offset, offsets[call.end_lineno - 1] + call.end_col_offset, argument + '.status_summary()')
                        )
                for start, end, value in sorted(replacements, reverse=True):
                    source = source[:start] + value + source[end:]
                source = source.replace('from quantlab.assistant.adapters.chatgpt.account_summary import status_summary as auth_status_summary\n', '')
            tree = ast.parse(source)
            changes = []
            lines = source.splitlines(keepends=True)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                provider_modules = set(GROUPS) - {'quantlab.assistant.domain.plan_protocol'}
                mapping = OWNERS if node.module in provider_modules else auth if node.module == PREFIX + 'auth' else {}
                if not mapping:
                    continue
                groups = {}
                for item in node.names:
                    groups.setdefault(mapping.get(item.name, node.module), []).append(item.name + (' as ' + item.asname if item.asname else ''))
                if set(groups) == {node.module}:
                    continue
                indent = ' ' * node.col_offset
                replacement = ''.join(indent + 'from ' + owner + ' import ' + ', '.join(names) + '\n' for owner, names in groups.items())
                changes.append((node.lineno - 1, node.end_lineno, replacement))
            for start, end, replacement in sorted(changes, reverse=True):
                lines[start:end] = [replacement]
            updated = ''.join(lines)
            if updated != path.read_text(encoding='utf-8'):
                path.write_text(updated, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--extract', action='store_true', help='Extract baseline bodies before applying reviewed provenance edits')
    options = parser.parse_args()
    if options.extract:
        extract()
    references()
