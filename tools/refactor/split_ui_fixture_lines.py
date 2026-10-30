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


if __name__ == '__main__':
    main()
