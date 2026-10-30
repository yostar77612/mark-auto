"""Replay the r3f repair after split_ui_r3d.py; retain base sample ownership."""

import ast
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = 'desktop_app/features/market/dashboard.py'
SAMPLES = 'desktop_app/features/market/samples.py'


def write(name, source):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')


def main():
    base = subprocess.check_output(['git', 'show', f'6b78239:{DASHBOARD}'], cwd=ROOT, text=True, encoding='utf-8')
    node = next(node for node in ast.parse(base).body if isinstance(node, ast.FunctionDef) and node.name == 'sample_market_series')
    sample = ast.get_source_segment(base, node)
    source = (ROOT / DASHBOARD).read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    existing = next((node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'sample_market_series'), None)
    if existing is not None:
        del lines[existing.lineno - 1 : existing.end_lineno]
    source = ''.join(lines).rstrip() + '\n\n\n' + sample + '\n'
    source = source.replace(
        'from quantlab.market import MarketValidationError as MarketValidationError',
        'from quantlab.market import MarketSeries, MarketValidationError as MarketValidationError',
    )
    write(DASHBOARD, source)
    (ROOT / SAMPLES).unlink(missing_ok=True)
    for name in ('desktop_app/features/market/market.py', 'tests/test_market_empty_ui.py', 'tools/refactor/split_ui_owners.json'):
        source = (ROOT / name).read_text(encoding='utf-8')
        write(name, source.replace('desktop_app.features.market.samples', 'desktop_app.features.market.dashboard'))
    name = 'tests/test_r7_characterization.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    for anchor, public_name in (("                'MarketRows',\n", 'MarketSeries'), ("                'deepcopy',\n", 'sample_market_series')):
        binding = f"                '{public_name}',\n"
        if binding not in source:
            source = source.replace(anchor, anchor + binding)
    write(name, source)
    name = 'tools/layer_map.json'
    data = json.loads((ROOT / name).read_text(encoding='utf-8'))
    data['overrides'].pop(SAMPLES, None)
    write(name, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    name = 'tools/layer_allowlist.json'
    entries = json.loads((ROOT / name).read_text(encoding='utf-8'))
    historical = json.loads(subprocess.check_output(['git', 'show', f'6b78239:{name}'], cwd=ROOT))
    debt = next(row for row in historical if row['path'] == 'desktop_market.py' and row['target'] == 'quantlab.reporting')
    if debt not in entries:
        entries.append(debt)
    assert len(entries) <= len(historical)
    write(name, json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
    name = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = (ROOT / name).read_text(encoding='utf-8')
    write(name, ''.join(line for line in source.splitlines(keepends=True) if f'| `{SAMPLES}` |' not in line))
    source = (ROOT / name).read_text(encoding='utf-8')
    for revision in ('r3b', 'r3c', 'r3d', 'r3f'):
        script = f'tools/refactor/split_ui_{revision}.py'
        if f'| `{script}` |' not in source:
            count = len((ROOT / script).read_text(encoding='utf-8-sig').splitlines())
            row = f'| `{script}` | {count} | tooling | `{script}` | PR C repair replay; existing behavior retained. |\n'
            marker = source.index('## 3 ')
            source = source[:marker] + row + '\n' + source[marker:]
    write(name, source)
    name = 'tools/refactor/test-edit-reasons.json'
    rows = [row for row in (json.loads((ROOT / name).read_text(encoding='utf-8-sig')) if (ROOT / name).exists() else []) if row.get('slice') != 'T3-r3f']
    reasons = {
        'tests/test_market_empty_ui.py': 'Import sample_market_series from its restored base dashboard owner; behavior assertions unchanged.',
        'tests/test_r7_characterization.py': 'Restore base public names MarketSeries and sample_market_series in dashboard expected tuple; frozen BASE and exact equality unchanged.',
    }
    rows.extend({'slice': 'T3-r3f', 'path': path, 'reason': reason} for path, reason in reasons.items())
    if (ROOT / name).exists():
        write(name, json.dumps(rows, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
