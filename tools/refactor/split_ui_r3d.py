"""Run after split_ui_r3c.py to reproduce the r3d import and fixture repairs."""

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/shell/window.py').is_file():
    print('split_ui_r3d.py: already applied')
    raise SystemExit(0)


import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def replace(name, old, new):
    path = ROOT / name
    source = path.read_text(encoding='utf-8')
    updated = source.replace(old, new)
    if updated != source:
        path.write_text(updated, encoding='utf-8', newline='\n')


def main():
    path = ROOT / 'desktop_app/features/market/dashboard.py'
    source = path.read_text(encoding='utf-8')
    binding = 'from desktop_app.components.widgets import PanelCard\n'
    source = source.removeprefix(binding)
    local_binding = '        ' + binding
    reason = '        # Keep widget dependencies out of module startup.\n'
    if local_binding not in source:
        source = source.replace('    def __init__(self, parent=None):\n', '    def __init__(self, parent=None):\n' + local_binding + '\n', 1)
    if reason + local_binding not in source:
        source = source.replace(local_binding, reason + local_binding, 1)
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8', newline='\n')
    replace(
        'tests/test_import_graph.py',
        "{'quantlab.ui_preferences', 'quantlab.runtime_support', 'desktop_app.strings.catalog'}",
        "{'quantlab.ui_preferences', 'quantlab.shared.runtime_errors', 'desktop_app.strings.catalog'}",
    )
    replace(
        'tests/test_import_graph.py',
        "                        'quantlab/research_core/adapters/market_layout.py',\n",
        "                        'quantlab/research_core/adapters/market_layout.py',\n                        'quantlab/shared/runtime_errors.py',\n",
    )
    replace(
        'tests/test_import_graph.py',
        "                        'quantlab/shared/runtime_errors.py',\n                        'quantlab/shared/runtime_errors.py',\n",
        "                        'quantlab/shared/runtime_errors.py',\n",
    )
    replace(
        'tests/test_import_graph.py',
        "graph['quantlab.runtime_support'], {'quantlab.windows_paths'}",
        "graph['quantlab.runtime_support'], {'quantlab.windows_paths', 'quantlab.shared.runtime_errors'}",
    )
    # Admit the concrete inputs owner already introduced by r3a, retaining the
    # generator's exact observer counts, identities, and receiver validation.
    replace(
        'tools/refactor/split_ui_fixture_lines.py',
        "('quantlab.reporting', 'desktop_app.features.analysis.presenter', 'desktop_app.components.formatting')",
        "('quantlab.reporting', 'desktop_app.features.analysis.presenter', 'desktop_app.components.formatting', 'quantlab.research_core.adapters.ui_repository.WorkerRepository')",
    )
    from tests.page_services_inventory import FIXTURE, inventory, reviewed_inventory
    from tools.refactor.split_ui_fixture_lines import slice2

    base = json.loads(FIXTURE.read_text(encoding='utf-8'))
    delta = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))
    actual, reviewed = inventory(), reviewed_inventory(base, delta['inventory'])
    for name in ('services', 'aliases', 'state_copies'):
        assert actual[name] == reviewed[name], name

    def normalized(points):
        rows = []
        for point in points:
            row = {key: value for key, value in point.items() if key != 'line'}
            if row['name'] == '_dataset' and row['file'] in ('tests/test_paper_stop_a1.py', 'tests/test_replay_b13.py'):
                row.update(kind='patch', receiver='quantlab.research_core.adapters.ui_repository.WorkerRepository')
            rows.append(json.dumps(row, sort_keys=True))
        return Counter(rows)

    assert normalized(actual['patch_points']) == normalized(reviewed['patch_points'])
    report = ROOT / '.tmp-layered/r3d-inventory-difference.json'
    if not report.exists():
        differences = {}
        for name in actual:
            left = Counter(json.dumps(row, sort_keys=True) for row in actual[name])
            right = Counter(json.dumps(row, sort_keys=True) for row in reviewed[name])
            differences[name] = {
                'actual_only': [json.loads(row) for row in (left - right).elements()],
                'reviewed_only': [json.loads(row) for row in (right - left).elements()],
            }
        differences['normalized_difference'] = []
        report.write_text(json.dumps(differences, indent=2) + '\n', encoding='utf-8')
    slice2()
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    rows = [row for row in json.loads(path.read_text(encoding='utf-8-sig')) if row.get('slice') != 'T3-r3d']
    reasons = {
        'tests/test_import_graph.py': 'Follows 1cd7e4e ownership move: RuntimeSafetyError now belongs to quantlab.shared.runtime_errors; include that owner in scanned sources and both preferences/runtime_support exact dependency sets; exact equality retained.',
        'tests/fixtures/layered_paths/slice2_service_relocations.json': 'Regenerated by the repo generator for 18 line shifts and two concrete _dataset owner moves; normalized difference empty, every observer retained.',
        'tests/layered_source_fixtures.py': 'Fixture-only SHA re-pin following f05328b; historical fixture and projection assertions unchanged.',
        'tests/test_download_auto_import_contracts.py': 'Fixture-only SHA re-pin following f05328b; exact equality retained.',
    }
    rows.extend({'slice': 'T3-r3d', 'path': name, 'reason': reason} for name, reason in reasons.items())
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
