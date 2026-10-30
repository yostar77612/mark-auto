"""Reproduce the T4-r3d walk-forward import and scan-path repairs."""

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REASONS = {}


def write(name, text, reason=None):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8', newline='\n')
    if reason:
        REASONS[name] = reason


def repair_walk_forward():
    name = 'quantlab/walk_forward.py'
    base = subprocess.check_output(['git', 'show', '6b78239:' + name], cwd=ROOT).decode('utf-8')
    source = base.replace(
        '            from .saved_candidate_pool import validate_admission_snapshot',
        '            from quantlab.research_core.application.saved_pool_validation import validate_admission_snapshot\n'
        '            from .saved_candidate_pool import SUPPORTED_PRODUCERS, AUDITED_PRODUCER  # Operation-specific profiles.',
    )
    source = source.replace(
        'validate_admission_snapshot(self.pool_admission, self.candidate_pool)',
        'validate_admission_snapshot(self.pool_admission, self.candidate_pool, profiles=SUPPORTED_PRODUCERS, audited_producer=AUDITED_PRODUCER)',
    ).replace(
        "validate_admission_snapshot(plan.get('pool_admission'), tuple(validate_dsl(spec) for spec in pool))",
        "validate_admission_snapshot(\n"
        "                plan.get('pool_admission'), tuple(validate_dsl(spec) for spec in pool), profiles=SUPPORTED_PRODUCERS, audited_producer=AUDITED_PRODUCER\n"
        '            )',
    )
    write(name, source)
    name = 'quantlab/research_core/application/walk_forward_operations.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    tree = ast.parse(source)
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.walk_forward' and [alias.name for alias in node.names] != ['run_walk_forward']
    ]
    if imports:
        node = imports[0]
        lines = source.splitlines(keepends=True)
        lines[node.lineno - 1 : node.end_lineno] = ['from quantlab import walk_forward\n']
        source = ''.join(lines)
        for alias in node.names:
            source = re.sub(r'(?<![\w.])' + alias.name + r'\(', 'walk_forward.' + alias.name + '(', source)
    write(name, source)
    return base


def repair_scan():
    name = 'tests/test_import_graph.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    source = source.replace("        + sorted((ROOT / 'quantlab/shared').glob('*.py'))\n", '')
    shared = "                        'quantlab/shared/runtime_errors.py',\n"
    if shared not in source:
        anchor = "                        'quantlab/research_core/adapters/market_layout.py',\n"
        if anchor not in source:
            raise ValueError('Missing named-source list anchor')
        source = source.replace(anchor, anchor + shared)
    source = source.replace(
        "self.assertEqual(graph['quantlab.runtime_support'], {'quantlab.windows_paths'})",
        "self.assertEqual(graph['quantlab.runtime_support'], {'quantlab.windows_paths', 'quantlab.shared.runtime_errors'})",
    )
    write(name, source)


def repair_historical_projection(base):
    name = 'tests/layered_source_fixtures.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    marker = "            return original_pool_text(source) if path == root / 'quantlab/saved_candidate_pool.py' else source"
    addition = "            if path == root / 'quantlab/walk_forward.py':\n                return historical_walk_forward_source(source)\n"
    if addition not in source:
        source = source.replace(marker, addition + marker)
    tail = '\n\ndef historical_walk_forward_source('
    if tail in source:
        source = source[: source.index(tail)]
    if '\ndef historical_walk_forward_source(' not in source:
        current = (ROOT / 'quantlab/walk_forward.py').read_text(encoding='utf-8')
        source += '\n\ndef historical_walk_forward_source(source):\n'
        source += '    """Undo only the exact reviewed lazy validation import/argument move."""\n'
        source += "    if hashlib.sha256(source.encode()).hexdigest() != " + repr(hashlib.sha256(current.encode()).hexdigest()) + ':\n'
        source += "        raise ValueError('Unreviewed walk-forward source drift')\n"
        source += '    source = source.replace(\n'
        source += "        'from quantlab.research_core.application.saved_pool_validation import validate_admission_snapshot\\n            from .saved_candidate_pool import SUPPORTED_PRODUCERS, AUDITED_PRODUCER  # Operation-specific profiles.',\n"
        source += "        'from .saved_candidate_pool import validate_admission_snapshot',\n    )\n"
        source += "    source = source.replace(', profiles=SUPPORTED_PRODUCERS, audited_producer=AUDITED_PRODUCER', '')\n"
        source += '    source = source.replace(\n'
        source += (
            '        '
            + repr("validate_admission_snapshot(\n                plan.get('pool_admission'), tuple(validate_dsl(spec) for spec in pool)\n            )")
            + ',\n'
        )
        source += '        ' + repr("validate_admission_snapshot(plan.get('pool_admission'), tuple(validate_dsl(spec) for spec in pool))") + ',\n    )\n'
        source += '    if hashlib.sha256(source.encode()).hexdigest() != ' + repr(hashlib.sha256(base.encode()).hexdigest()) + ':\n'
        source += "        raise ValueError('Historical walk-forward source outside the import move changed')\n    return source\n"
    write(
        name,
        source,
        'Project only the pinned lazy validation import/explicit profile arguments back to base for source-bound golden identities; no golden values or assertions changed.',
    )


def repair_smoke():
    name = 'desktop_app/smoke/__init__.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    source = source.replace(
        "for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py')",
        "for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py', 'research_core/domain/receipts.py')",
    )
    source = source.replace(
        "Path(research.__file__).with_name(name).read_text(encoding='utf-8')",
        "(Path(research.__file__).parent / name).read_text(encoding='utf-8')",
    )
    write(name, source)


def repair_inventory():
    name = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = (ROOT / name).read_text(encoding='utf-8')
    script = 'tools/refactor/split_core_r3d.py'
    if '| `' + script + '` |' not in source:
        index = source.index('\n## 3 ')
        count = len((ROOT / script).read_text(encoding='utf-8').splitlines())
        row = f'\n| `{script}` | {count} | tooling | `{script}` | PR D r3d reproducible repair |\n'
        source = source[:index] + row + source[index:]
    source = re.sub(
        r'(?m)^(\| `([^`]+\.py)` \| )\d+( \| [^\n]*PR D (?:extracted responsibility owner|r3d reproducible repair)[^\n]*)$',
        lambda match: match[1] + str(len((ROOT / match[2]).read_text(encoding='utf-8').splitlines())) + match[3],
        source,
    )
    write(name, source)


def record():
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    for name, reason in REASONS.items():
        rows = [row for row in rows if not (row.get('slice') == 'T4-r3d' and row.get('file') == name)]
        rows.append({'file': name, 'reason': reason, 'slice': 'T4-r3d'})
    rows = [row for row in rows if not (row.get('slice') == 'T4-r3e' and row.get('file') == 'tests/test_import_graph.py')]
    rows.append(
        {
            'file': 'tests/test_import_graph.py',
            'reason': 'Follows the 1cd7e4e ownership move; named-source scan and runtime_support dependency assertion are identical to PR C. Preserve D job_worker owner changes.',
            'slice': 'T4-r3e',
            'reproduced_by': 'tools/refactor/split_core_r3d.py',
        }
    )
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    base = repair_walk_forward()
    repair_scan()
    repair_smoke()
    repair_inventory()
    repair_historical_projection(base)
    record()
    # Retain the later passive-import and patch-point repair on reruns.
    import runpy

    runpy.run_path(str(ROOT / "tools/refactor/split_core_r3f.py"))["repair"]()


if __name__ == '__main__':
    main()
