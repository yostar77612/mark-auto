"""Finish the four reviewed slice 2 compatibility and inventory corrections."""

from __future__ import annotations


import json
from pathlib import Path
import re
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import check_layers
from tools.refactor import split_ui_fixture_lines

ROOT = Path(__file__).resolve().parents[2]


def compatibility():
    """Keep the E2 adapter and its typed consumers at their original public owner."""
    path = ROOT / 'quantlab/market_history.py'
    path.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:quantlab/market_history.py'], cwd=ROOT))
    for name in ('tests/test_market_history.py', 'tools/validate_market_history_import.py', 'desktop_app/smoke/__init__.py'):
        path = ROOT / name
        source = path.read_text(encoding='utf-8')
        path.write_text(
            source.replace('quantlab.research_core.domain.market_sessions import', 'quantlab.market_history import'), encoding='utf-8', newline='\n'
        )
    path = ROOT / 'desktop_app/features/market/dashboard.py'
    source = path.read_text(encoding='utf-8')
    line = 'from quantlab.market import MarketValidationError as MarketValidationError\n'
    if line not in source:
        path.write_text(line + source, encoding='utf-8', newline='\n')
    path = ROOT / 'tools/refactor/split_ui_owners.json'
    owners = json.loads(path.read_text(encoding='utf-8'))
    owners = {key: value for key, value in owners.items() if not key.startswith('quantlab.market_history.')}
    path.write_text(json.dumps(owners, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def layer_inventory():
    """Inventory every new product/tool source using the authoritative layer map."""
    mapping = check_layers.load_map(ROOT / 'tools/layer_map.json')
    names = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', '*.py'], cwd=ROOT).decode().splitlines()
    path = ROOT / 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(
        r'^\| `desktop_ui.py` \| (\d+) \| \w+ \| `desktop_app/shell/main_window.py` \|[^\n]+',
        r'| `desktop_ui.py` | \1 | composition | `desktop_app/shell/main_window.py` | PR C: shell split leaves registrar and window factory |',
        source,
        flags=re.M,
    )
    # Re-running after staging still retains all previously inventoried additions.
    heading = '### 2.2 PR C slice 2 added responsibilities'
    if heading in source:
        prior = source.split(heading)[1].split('## 3 ')[0]
        names += re.findall(r'^\| `([^`]+\.py)`', prior, re.M)
        source = source[: source.index(heading)] + '## 3 ' + source.split('## 3 ', 1)[1]
    rows = []
    for name in sorted(set(names)):
        layer = check_layers.layer_for(name, mapping)
        if layer and not name.startswith(('tests/', '.tmp-layered/')):
            count = len((ROOT / name).read_text(encoding='utf-8').splitlines())
            rows.append(f'| `{name}` | {count} | {layer} | `{name}` | PR C: slice 2 responsibility extraction |')
    addition = heading + '\n\n| Source | Lines | Layer | Target | Reason |\n| --- | ---: | --- | --- | --- |\n' + '\n'.join(rows) + '\n\n'
    source = source.replace('## 3 ', addition + '## 3 ', 1)
    path.write_text(source, encoding='utf-8', newline='\n')


def main():
    compatibility()
    layer_inventory()
    split_ui_fixture_lines.slice2()


if __name__ == '__main__':
    main()
