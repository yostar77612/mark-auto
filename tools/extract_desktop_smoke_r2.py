"""Record canonical R2 AST evidence across current owners; replay lives in refactor/e_smoke.py."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = '4c72a302b833d73ab9caf1c9385dd84210d56b4b'
PRODUCTION = {
    'parse_args',
    'acquire_instance_lock',
    'prepare_workspace',
    'run_gui',
    'main',
    '_prepare_startup_workspace',
    '_offer_workspace_after_recovery_block',
}


def main():
    source = subprocess.check_output(['git', 'show', BASE + ':desktop.py'], cwd=ROOT).decode('utf-8')
    nodes = [node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    package = ROOT / 'desktop_app/smoke/__init__.py'
    current = {
        node.name: node
        for node in [node for owner in sorted(package.parent.glob('*.py')) for node in ast.parse(owner.read_text(encoding='utf-8')).body]
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    production = {node.name: node for node in ast.parse((ROOT / 'desktop.py').read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef)}
    records = {}
    for node in nodes:
        destination = production if node.name in PRODUCTION else current
        before = ast.dump(node, include_attributes=False)
        after = ast.dump(destination[node.name], include_attributes=False)
        records[node.name] = {'equal': before == after, 'sha256': hashlib.sha256(before.encode()).hexdigest()}
    evidence = {
        'base': BASE,
        'comparison': 'ast.dump full definitions, include_attributes=False; no normalization',
        'definitions': records,
        'differing': [name for name, record in records.items() if not record['equal']],
    }
    (ROOT / 'docs/analysis/r2_ast_preservation.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    if evidence['differing']:
        raise SystemExit('AST preservation failure')


if __name__ == '__main__':
    main()
