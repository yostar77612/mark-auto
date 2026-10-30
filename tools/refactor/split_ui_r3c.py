"""Run after split_ui_r3b.py to reproduce the controller-diagnosed r3c repairs."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = 'desktop_app/features/market/samples.py'


def write(name, source):
    path = ROOT / name
    if not path.exists() or path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')


def replace(name, old, new):
    write(name, (ROOT / name).read_text(encoding='utf-8').replace(old, new))


def product():
    name = 'desktop_app/features/market/dashboard.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    binding = 'from quantlab.market import MarketValidationError as MarketValidationError\n'
    if binding not in source:
        write(name, binding + source)
    name = 'desktop_app/bootstrap.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    node = next((node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'sample_market_series'), None)
    if node is not None:
        lines = source.splitlines(keepends=True)
        sample = ''.join(lines[node.lineno - 1 : node.end_lineno])
        write(SAMPLES, '"""Pure offline demo market data for presentation."""\n\nfrom desktop_app.strings.catalog import ui_text\n\n\n' + sample)
        del lines[node.lineno - 1 : node.end_lineno]
        write(name, ''.join(lines).rstrip() + '\n')
    replace(name, '        sample_market_series=sample_market_series,\n', '')
    replace('desktop_app/shell/services.py', '    sample_market_series: Callable[..., Any]\n', '')
    replace('desktop_app/shell/host.py', '    sample_market_series: Callable\n', '')
    replace('desktop_app/shell/setup.py', '        sample_market_series=window.services.sample_market_series,\n', '')
    name = 'desktop_app/features/market/market.py'
    source = (ROOT / name).read_text(encoding='utf-8')
    binding = 'from desktop_app.features.market.samples import sample_market_series\n'
    if binding not in source:
        source = binding + source
    write(name, source.replace('series = self.host.sample_market_series()', 'series = sample_market_series()'))
    name = 'tools/refactor/split_ui_owners.json'
    replace(name, 'desktop_app.bootstrap.sample_market_series', 'desktop_app.features.market.samples.sample_market_series')


def references():
    replace('tests/test_r7_characterization.py', "                'MarketRows',\n", "                'MarketRows',\n                'MarketValidationError',\n")
    # Keep the repair idempotent when replayed on an already repaired tree.
    replace(
        'tests/test_r7_characterization.py',
        "                'MarketValidationError',\n                'MarketValidationError',\n",
        "                'MarketValidationError',\n",
    )
    name = 'tests/test_ui_snapshot.py'
    replace(name, 'from desktop_app.shell.window import MainWindow as _c_desktop_app_shell_main_window_MainWindow', 'import desktop_app.shell.main_window')
    replace(name, 'original_window = _c_desktop_app_shell_main_window_MainWindow', 'original_window = desktop_app.shell.main_window.MainWindow')
    replace(name, "patch('desktop_app.shell.window.MainWindow',", "patch('desktop_app.shell.main_window.MainWindow',")
    replace(
        'tests/test_market_empty_ui.py',
        'from desktop_app.bootstrap import sample_market_series',
        'from desktop_app.features.market.samples import sample_market_series',
    )


def metadata():
    path = ROOT / 'tools/layer_map.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['overrides'][SAMPLES] = 'presentation'
    write('tools/layer_map.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    name = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    source = (ROOT / name).read_text(encoding='utf-8')
    row = f'| `{SAMPLES}` | {len((ROOT / SAMPLES).read_text(encoding="utf-8").splitlines())} | presentation | `{SAMPLES}` | PR C r3c: pure offline demo data, called directly by MarketPage; no composition dependency. |\n'
    if f'| `{SAMPLES}` |' not in source:
        marker = '| `desktop_app/features/market/rows.py` |'
        index = source.index(marker)
        source = source[:index] + row + source[index:]
    write(name, source)
    name = 'tools/refactor/test-edit-reasons.json'
    rows = json.loads((ROOT / name).read_text(encoding='utf-8-sig')) if (ROOT / name).exists() else []
    rows = [row for row in rows if row.get('slice') != 'T3-r3c']
    reasons = {
        'tests/test_r7_characterization.py': 'Restore the base public MarketValidationError binding in the PR-written expected tuple; frozen BASE and exact equality unchanged.',
        'tests/test_ui_snapshot.py': 'Patch both MainWindow calls at the main_window lookup site and read original_window there; every isolation/fallback assertion retained.',
        'tests/test_market_empty_ui.py': 'Import pure demo data from its real presentation owner instead of bootstrap; every offline/clearing assertion retained.',
    }
    rows.extend({'slice': 'T3-r3c', 'path': name, 'reason': reason} for name, reason in reasons.items())
    if (ROOT / name).exists():
        write(name, json.dumps(rows, ensure_ascii=False, indent=2) + '\n')


def main():
    if 'def sample_market_series' in (ROOT / 'desktop_app/bootstrap.py').read_text(encoding='utf-8'):
        product()
        metadata()
    references()


if __name__ == '__main__':
    main()
