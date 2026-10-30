"""Refresh only reviewed patch line locations after scripted import changes."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.page_services_inventory import inventory, reviewed_inventory

ROOT = Path(__file__).resolve().parents[2]


def main():
    fixture = ROOT / 'tests/fixtures/page_services_inventory.json'
    base = json.loads(fixture.read_text(encoding='utf-8'))
    path = ROOT / 'tests/fixtures/layered_paths/page_service_line_relocations.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    delta = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))
    original = reviewed_inventory(base, delta['inventory'])
    for row in table['line_relocations']:
        projected = {**row['original'], 'line': row['current_line']}
        original['patch_points'][original['patch_points'].index(projected)] = row['original']
    original['patch_points'].sort(key=lambda p: (p['file'], p['line'], p['name'], p['kind']))
    points = inventory()['patch_points']
    locations = defaultdict(list)
    for point in points:
        locations[tuple(sorted((key, value) for key, value in point.items() if key != 'line'))].append(point['line'])
    rows = []
    for point in original['patch_points']:
        identity = tuple(sorted((key, value) for key, value in point.items() if key != 'line'))
        current_line = locations[identity].pop(0)
        if current_line != point['line']:
            rows.append({'original': point, 'current_line': current_line})
    if len(points) != table['patch_points'] or any(locations.values()):
        raise ValueError('Patch identities or counts changed; only line relocation is authorized')
    before = hashlib.sha256(json.dumps(table, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    table['line_relocations'] = rows
    after = hashlib.sha256(json.dumps(table, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    helper = ROOT / 'tests/layered_source_fixtures.py'
    source = helper.read_text(encoding='utf-8')
    if source.count(before) != 1:
        raise ValueError('Expected the original pinned line table hash once')
    helper.write_text(source.replace(before, after), encoding='utf-8', newline='\n')
    path.write_text(json.dumps(table, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'patch_points': len(points), 'line_relocations': len(rows), 'sha256': after}))


def slice2():
    """Pin all original observers at their new lines/owners, with no removals."""
    from unittest.mock import patch
    import re

    fixture = json.loads((ROOT / 'tests/fixtures/page_services_inventory.json').read_text(encoding='utf-8'))
    delta = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))
    with patch('tests.page_services_inventory.project_page_service_lines', lambda value: value):
        expected = reviewed_inventory(fixture, delta['inventory'])
    previous = json.loads((ROOT / 'tests/fixtures/layered_paths/page_service_line_relocations.json').read_text(encoding='utf-8'))
    previous_rows = {tuple(sorted(row['original'].items())): row['current_line'] for row in previous['line_relocations']}
    for point in expected['patch_points']:
        point['line'] = previous_rows.get(tuple(sorted(point.items())), point['line'])
    actual = inventory()
    service = next(row for row in expected['services'] if row['name'] == '_paper')
    assert service['patch_sensitive'] is False
    service['patch_sensitive'] = True  # The WAL control now patches its concrete application owner.
    for name in ('services', 'aliases', 'state_copies'):
        assert actual[name] == expected[name], name
    remaining = list(actual['patch_points'])
    rows = []
    for old in expected['patch_points']:
        candidates = [point for point in remaining if point['file'] == old['file'] and point['name'] == old['name']]
        exact = [point for point in candidates if point['kind'] == old['kind'] and point['receiver'] == old['receiver']]
        current = min(exact or candidates, key=lambda point: point['line'])
        assert old['kind'] == current['kind'] or (old['kind'], current['kind']) == ('patch.object', 'patch')
        if old['receiver'] != current['receiver']:
            assert current['receiver'] in (
                'quantlab.reporting',
                'desktop_app.features.analysis.presenter',
                'desktop_app.components.formatting',
                'quantlab.research_core.adapters.ui_repository.WorkerRepository',
            )
        remaining.remove(current)
        if old != current:
            rows.append({'original': old, 'current': current})
    assert [(point['file'], point['name'], point['receiver']) for point in remaining] == [
        ('tests/test_compare_equity_f2.py', 'load_result', 'quantlab.reporting'),
        ('tests/test_workspace_wal_guard.py', '_paper', 'paper_operations'),
    ]
    payload = {'original_observers': len(expected['patch_points']), 'relocations': rows, 'newly_discovered_existing_observers': remaining}
    target = ROOT / 'tests/fixtures/layered_paths/slice2_service_relocations.json'
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    contract = ROOT / 'tests/test_download_auto_import_contracts.py'
    contract_source = contract.read_text(encoding='utf-8')
    pin = "            'layered_paths/slice2_service_relocations.json': '" + digest + "',"
    if 'layered_paths/slice2_service_relocations.json' in contract_source:
        contract_source = re.sub(r"            'layered_paths/slice2_service_relocations.json': '[a-f0-9]+',", pin, contract_source)
    else:
        contract_source = contract_source.replace('        expected = {', '        expected = {\n' + pin, 1)
    contract.write_text(contract_source, encoding='utf-8', newline='\n')
    helper_path = ROOT / 'tests/layered_source_fixtures.py'
    source = helper_path.read_text(encoding='utf-8')
    if '_SLICE2_PATCH_SHA' in source:
        source = source[: source.index('_SLICE2_PATCH_SHA =')].rstrip()
    source += SLICE2_PROJECTION
    source = source.replace(
        "    return result\n\n\ndef mechanically_restored_source", "    return _project_slice2_service_refs(result)\n\n\ndef mechanically_restored_source"
    )
    source = re.sub(r"_SLICE2_PATCH_SHA = '[a-zA-Z0-9_]+'", "_SLICE2_PATCH_SHA = '" + digest + "'", source)
    helper_path.write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'retained_observers': payload['original_observers'], 'relocated': len(rows), 'additional_existing': len(remaining), 'sha256': digest}))


SLICE2_PROJECTION = '''


_SLICE2_PATCH_SHA = 'PLACEHOLDER'


def _project_slice2_service_refs(result):
    """Project reviewed observer locations; every historical observer is retained."""
    import json

    path = Path(__file__).parent / 'fixtures/layered_paths/slice2_service_relocations.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    canonical = json.dumps(table, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest() != _SLICE2_PATCH_SHA:
        raise ValueError('Reviewed slice 2 observer table changed')
    assert len(result['patch_points']) == table['original_observers'] == 174
    service = next(row for row in result['services'] if row['name'] == '_paper')
    assert service['patch_sensitive'] is False
    service['patch_sensitive'] = True
    for row in table['relocations']:
        original, current = row['original'], row['current']
        assert (original['file'], original['name']) == (current['file'], current['name'])
        index = result['patch_points'].index(original)
        result['patch_points'][index] = dict(current)
    additions = table['newly_discovered_existing_observers']
    assert [(point['file'], point['name'], point['receiver']) for point in additions] == [
        ('tests/test_compare_equity_f2.py', 'load_result', 'quantlab.reporting'),
        ('tests/test_workspace_wal_guard.py', '_paper', 'paper_operations'),
    ]
    result['patch_points'].extend(additions)
    result['patch_points'].sort(key=lambda point: (point['file'], point['line'], point['name'], point['kind']))
    return result
'''


if __name__ == '__main__':
    if (ROOT / 'desktop_app/bootstrap.py').exists():
        slice2()
    else:
        main()
